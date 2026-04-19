"""Scheduled polling for Uptime Guardian.

This module wraps an APScheduler :class:`AsyncIOScheduler` so that each active
monitor is polled on its own interval without blocking the FastAPI event loop
(Requirement 4.4). Jobs are registered as coroutine functions and run on the
event loop; each job body is wrapped in a ``try/except`` so a failure in one
check is logged and never stops the scheduler or other jobs.

The job body (:meth:`MonitorScheduler.run_check`) performs a single check
cycle for one monitor:

1. Open a database session and load the monitor.
2. Read the previous latest result *before* persisting the new one
   (needed for up -> down transition detection).
3. Run the asynchronous :func:`check_monitor`.
4. Persist the returned result via ``crud.create_check_result``.
5. Apply :func:`decide_alerts` using per-monitor in-memory alert state and the
   configured ``alert_cooldown_minutes``; dispatch down / SSL alerts and update
   the per-monitor alert-state timestamps when alerts fire.

A module-level default :class:`MonitorScheduler` instance backs the module-level
``start`` / ``shutdown`` / ``register_monitor`` / ``reload_scheduler`` /
``run_check`` functions used by ``main.py``. The session factory is injectable so
tests can drive the scheduler against an in-memory database.

Requirements traceability: 4.1, 4.2, 4.3, 4.4, 5.1, 6.1, 10.5.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, List, Optional

from apscheduler.job import Job
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session

import crud
from alerter import (
    build_down_message,
    build_ssl_message,
    decide_alerts,
    send_telegram_alert,
)
from checker import check_monitor
from config import load_settings
from database import SessionLocal
from models import Monitor

logger = logging.getLogger(__name__)

# Factory that produces a new SQLAlchemy session when called.
SessionFactory = Callable[[], Session]


@dataclass
class _AlertState:
    """In-memory alert timestamps tracked per monitor across check cycles.

    These timestamps drive the cooldown / suppression decisions in
    :func:`decide_alerts`. They live only in process memory; the MVP does not
    persist alert history.
    """

    last_down_alert_at: Optional[datetime] = None
    last_ssl_alert_at: Optional[datetime] = None


def _job_id(monitor_id: int) -> str:
    """Return the deterministic APScheduler job id for a monitor."""
    return f"monitor-{monitor_id}"


class MonitorScheduler:
    """An :class:`AsyncIOScheduler` wrapper that polls monitors on intervals.

    Args:
        session_factory: A zero-argument callable returning a new SQLAlchemy
            ``Session``. Defaults to the application's ``SessionLocal``. Tests
            inject a factory bound to an in-memory database.
    """

    def __init__(self, session_factory: Optional[SessionFactory] = None) -> None:
        self._session_factory: SessionFactory = session_factory or SessionLocal
        self._scheduler: AsyncIOScheduler = AsyncIOScheduler()
        self._alert_state: dict[int, _AlertState] = {}

    # --- Lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Register a job for every active monitor and start the scheduler.

        Loads all active monitors and registers one recurring interval job per
        monitor before starting the underlying scheduler (Requirement 4.1).
        """
        self._register_all_active_monitors()
        if not self._scheduler.running:
            self._scheduler.start()

    def shutdown(self) -> None:
        """Stop all scheduled jobs and the scheduler (Requirement 10.5)."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    @property
    def running(self) -> bool:
        """Whether the underlying scheduler is currently running."""
        return self._scheduler.running

    @property
    def scheduler(self) -> AsyncIOScheduler:
        """Expose the underlying scheduler (primarily for tests)."""
        return self._scheduler

    # --- Job registration --------------------------------------------------

    def register_monitor(self, monitor: Monitor) -> Job:
        """Schedule a recurring interval job for ``monitor``.

        The job fires every ``monitor.check_interval_minutes`` minutes and runs
        :meth:`run_check` for the monitor's id. Re-registering an existing
        monitor replaces its job, so a monitor added or updated through the API
        is scheduled without a restart (Requirement 4.3).
        """
        return self._scheduler.add_job(
            self.run_check,
            trigger="interval",
            minutes=monitor.check_interval_minutes,
            args=[monitor.id],
            id=_job_id(monitor.id),
            replace_existing=True,
        )

    def reload_scheduler(self) -> None:
        """Clear all jobs and re-register every active monitor.

        Used after monitor configuration changes to bring the scheduled jobs
        back in sync with the database (Requirement 4.3).
        """
        self._scheduler.remove_all_jobs()
        self._register_all_active_monitors()

    def get_jobs(self) -> List[Job]:
        """Return the list of currently scheduled jobs."""
        return list(self._scheduler.get_jobs())

    def _register_all_active_monitors(self) -> None:
        """Register one job per active monitor read from the database."""
        db = self._session_factory()
        try:
            for monitor in crud.get_active_monitors(db):
                self.register_monitor(monitor)
        finally:
            db.close()

    # --- Job body ----------------------------------------------------------

    async def run_check(self, monitor_id: int) -> None:
        """Run one check cycle for ``monitor_id`` (the scheduled job body).

        The entire body is wrapped in a ``try/except`` so that any failure is
        logged and isolated, never stopping the scheduler or sibling jobs
        (Requirement 4.4, error-handling design).
        """
        try:
            db = self._session_factory()
            try:
                monitor = crud.get_monitor(db, monitor_id)
                if monitor is None:
                    logger.warning(
                        "Scheduled check skipped: monitor %s no longer exists",
                        monitor_id,
                    )
                    return

                # Read the previous latest result BEFORE persisting the new one
                # so up -> down transitions can be detected (Requirement 5.1).
                previous_result = crud.get_latest_result(db, monitor_id)

                # Perform the actual HTTP/SSL check (async, non-blocking).
                check = await check_monitor(monitor)

                # Persist the result (Requirement 4.2).
                saved = crud.create_check_result(
                    db,
                    monitor_id,
                    is_up=check.is_up,
                    status_code=check.status_code,
                    response_time_ms=check.response_time_ms,
                    ssl_valid=check.ssl_valid,
                    ssl_days_remaining=check.ssl_days_remaining,
                    error_message=check.error_message,
                )

                await self._apply_alerts(monitor, previous_result, saved)
            finally:
                db.close()
        except Exception:  # noqa: BLE001 - one bad job must not break others
            logger.exception(
                "Scheduled check for monitor %s failed", monitor_id
            )

    async def _apply_alerts(
        self,
        monitor: Monitor,
        previous_result: object,
        saved_result: object,
    ) -> None:
        """Apply alert decisions for a freshly saved result and dispatch alerts.

        Uses per-monitor in-memory alert state and the configured cooldown to
        decide whether to send a down alert and/or an SSL warning, updating the
        stored timestamps whenever an alert fires (Requirements 5.1, 6.1).
        """
        settings = load_settings()
        now = datetime.now(timezone.utc)
        state = self._alert_state.setdefault(monitor.id, _AlertState())

        send_down, send_ssl = decide_alerts(
            current_result=saved_result,
            previous_result=previous_result,
            monitor=monitor,
            last_down_alert_at=state.last_down_alert_at,
            last_ssl_alert_at=state.last_ssl_alert_at,
            now=now,
            cooldown_minutes=settings.alert_cooldown_minutes,
        )

        if send_down:
            await send_telegram_alert(build_down_message(monitor, saved_result))
            state.last_down_alert_at = now
        if send_ssl:
            await send_telegram_alert(build_ssl_message(monitor, saved_result))
            state.last_ssl_alert_at = now


# --- Module-level default instance and delegating functions ----------------

# Backs the module-level functions imported by ``main.py``. Constructed at
# import time; the underlying AsyncIOScheduler does not require an event loop
# until ``start()`` is called.
_default_scheduler = MonitorScheduler()


def get_scheduler() -> MonitorScheduler:
    """Return the module-level default scheduler instance."""
    return _default_scheduler


def start() -> None:
    """Start the default scheduler (see :meth:`MonitorScheduler.start`)."""
    _default_scheduler.start()


def shutdown() -> None:
    """Stop the default scheduler (see :meth:`MonitorScheduler.shutdown`)."""
    _default_scheduler.shutdown()


def register_monitor(monitor: Monitor) -> Job:
    """Register a job for ``monitor`` on the default scheduler."""
    return _default_scheduler.register_monitor(monitor)


def reload_scheduler() -> None:
    """Reload the default scheduler's jobs from the database."""
    _default_scheduler.reload_scheduler()


async def run_check(monitor_id: int) -> None:
    """Run a check cycle for ``monitor_id`` on the default scheduler."""
    await _default_scheduler.run_check(monitor_id)
