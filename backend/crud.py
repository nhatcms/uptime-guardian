"""CRUD and statistics helpers for Uptime Guardian.

This module centralizes all read/write access to the persistence layer so that
the API routers and the scheduler share a single, well-typed data access path.
It provides monitor CRUD, check-result persistence and querying, statistics
aggregation over a list of results, user lookup/creation, and idempotent
seeding helpers for first-run initialization.

All functions take an explicit SQLAlchemy ``Session`` so they remain easy to
test against an in-memory database and free of hidden global state. Deleting a
monitor removes its associated check results via the ORM cascade /
``ON DELETE CASCADE`` foreign key configured in ``models``/``database``
(Requirement 1.7).

Requirements traceability: 1.3, 1.4, 1.6, 1.7, 8.1, 8.2, 8.3, 8.4, 10.3, 10.4.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import CheckResult, Monitor, User
from schemas import MonitorCreate, MonitorUpdate, StatsOut

# The two example monitors seeded on first run (Requirement 10.3).
_DEFAULT_MONITORS: tuple[tuple[str, str, int], ...] = (
    ("Google", "https://www.google.com", 5),
    ("GitHub", "https://github.com", 5),
)


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


# --- Monitor CRUD ----------------------------------------------------------

def create_monitor(db: Session, data: MonitorCreate) -> Monitor:
    """Persist a new monitor from a validated ``MonitorCreate`` payload.

    ``is_active`` defaults to true and ``notify_on_failure`` to true via the
    model column defaults (Requirement 1.1).
    """
    monitor = Monitor(
        name=data.name,
        url=data.url,
        check_interval_minutes=data.check_interval_minutes,
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    return monitor


def get_monitors(db: Session) -> list[Monitor]:
    """Return all monitors ordered by id (Requirement 1.3)."""
    return list(db.scalars(select(Monitor).order_by(Monitor.id)).all())


def get_monitor(db: Session, monitor_id: int) -> Optional[Monitor]:
    """Return the monitor with ``monitor_id`` or ``None`` if it does not exist."""
    return db.get(Monitor, monitor_id)


def get_active_monitors(db: Session) -> list[Monitor]:
    """Return all monitors whose ``is_active`` flag is true."""
    stmt = select(Monitor).where(Monitor.is_active.is_(True)).order_by(Monitor.id)
    return list(db.scalars(stmt).all())


def update_monitor(
    db: Session, monitor_id: int, data: MonitorUpdate
) -> Optional[Monitor]:
    """Apply the supplied changes to an existing monitor (Requirement 1.6).

    Only fields explicitly provided in ``data`` are updated; omitted fields are
    left unchanged. Returns the updated monitor, or ``None`` if no monitor with
    ``monitor_id`` exists.
    """
    monitor = db.get(Monitor, monitor_id)
    if monitor is None:
        return None

    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(monitor, field, value)

    db.commit()
    db.refresh(monitor)
    return monitor


def delete_monitor(db: Session, monitor_id: int) -> bool:
    """Delete a monitor and all of its check results (Requirement 1.7).

    Returns ``True`` if a monitor was deleted, ``False`` if no monitor with
    ``monitor_id`` existed. The associated ``CheckResult`` rows are removed via
    the configured cascade.
    """
    monitor = db.get(Monitor, monitor_id)
    if monitor is None:
        return False

    db.delete(monitor)
    db.commit()
    return True


# --- CheckResult persistence and queries -----------------------------------

def create_check_result(
    db: Session,
    monitor_id: int,
    *,
    is_up: bool,
    status_code: Optional[int] = None,
    response_time_ms: Optional[float] = None,
    ssl_valid: Optional[bool] = None,
    ssl_days_remaining: Optional[int] = None,
    error_message: Optional[str] = None,
    checked_at: Optional[datetime] = None,
) -> CheckResult:
    """Persist a new check result for ``monitor_id`` and return it.

    ``checked_at`` defaults to the model's auto timestamp when omitted. All
    check-specific fields are accepted as keyword arguments for a clean,
    explicit call site from the scheduler and the check-now endpoint.
    """
    result = CheckResult(
        monitor_id=monitor_id,
        is_up=is_up,
        status_code=status_code,
        response_time_ms=response_time_ms,
        ssl_valid=ssl_valid,
        ssl_days_remaining=ssl_days_remaining,
        error_message=error_message,
    )
    if checked_at is not None:
        result.checked_at = checked_at

    db.add(result)
    db.commit()
    db.refresh(result)
    return result


def get_latest_result(db: Session, monitor_id: int) -> Optional[CheckResult]:
    """Return the most recent check result for a monitor, or ``None``."""
    stmt = (
        select(CheckResult)
        .where(CheckResult.monitor_id == monitor_id)
        .order_by(CheckResult.checked_at.desc(), CheckResult.id.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def get_results(
    db: Session, monitor_id: int, limit: int = 100
) -> list[CheckResult]:
    """Return up to ``limit`` recent results for a monitor, newest first.

    Results are ordered from newest to oldest by ``checked_at`` (ties broken by
    descending id) and restricted to the requested monitor (Requirement 8.1).
    """
    stmt = (
        select(CheckResult)
        .where(CheckResult.monitor_id == monitor_id)
        .order_by(CheckResult.checked_at.desc(), CheckResult.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def get_results_in_window(
    db: Session, monitor_id: int, hours: int
) -> list[CheckResult]:
    """Return a monitor's results whose ``checked_at`` is within the last ``hours``.

    Used for statistics over a time window (Requirement 8.2). Results are
    ordered newest first.
    """
    since = _utcnow() - timedelta(hours=hours)
    stmt = (
        select(CheckResult)
        .where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= since,
        )
        .order_by(CheckResult.checked_at.desc(), CheckResult.id.desc())
    )
    return list(db.scalars(stmt).all())


# --- Statistics aggregation ------------------------------------------------

def compute_stats(results: list[CheckResult]) -> StatsOut:
    """Aggregate statistics over a list of check results.

    Computes uptime percentage, average/min/max response time, total and failed
    check counts (Requirements 8.2, 8.3). Response-time aggregates ignore
    ``None`` response times (e.g. connection failures). For an empty input,
    returns all-zero values without raising (Requirement 8.4).
    """
    total_checks = len(results)
    if total_checks == 0:
        return StatsOut(
            uptime_percentage=0.0,
            avg_response_time_ms=0.0,
            total_checks=0,
            failed_checks=0,
            min_response_time_ms=0.0,
            max_response_time_ms=0.0,
        )

    up_count = sum(1 for r in results if r.is_up)
    failed_checks = total_checks - up_count
    uptime_percentage = (up_count / total_checks) * 100.0

    response_times = [
        r.response_time_ms
        for r in results
        if r.response_time_ms is not None
    ]
    if response_times:
        avg_response_time_ms = sum(response_times) / len(response_times)
        min_response_time_ms = min(response_times)
        max_response_time_ms = max(response_times)
    else:
        avg_response_time_ms = 0.0
        min_response_time_ms = 0.0
        max_response_time_ms = 0.0

    return StatsOut(
        uptime_percentage=uptime_percentage,
        avg_response_time_ms=avg_response_time_ms,
        total_checks=total_checks,
        failed_checks=failed_checks,
        min_response_time_ms=min_response_time_ms,
        max_response_time_ms=max_response_time_ms,
    )


# --- User lookup and creation ----------------------------------------------

def get_user_by_username(db: Session, username: str) -> Optional[User]:
    """Return the user with ``username`` or ``None`` if not found."""
    stmt = select(User).where(User.username == username)
    return db.scalars(stmt).first()


def create_user(db: Session, username: str, password_hash: str) -> User:
    """Persist a new user with the given username and password hash."""
    user = User(username=username, password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# --- Seeding helpers (idempotent) ------------------------------------------

def seed_default_monitors(db: Session) -> None:
    """Insert the two example monitors only if the monitors table is empty.

    Idempotent: repeated invocations after the first leave the table unchanged,
    so the database always contains exactly the Google and GitHub monitors and
    no duplicates (Requirement 10.3, Property 14).
    """
    existing = db.scalar(select(Monitor).limit(1))
    if existing is not None:
        return

    for name, url, interval in _DEFAULT_MONITORS:
        db.add(Monitor(name=name, url=url, check_interval_minutes=interval))
    db.commit()


def seed_admin_user(db: Session, username: str, password_hash: str) -> None:
    """Insert the admin user only if the users table is empty.

    Idempotent: once a user exists, repeated invocations are no-ops, so exactly
    one admin user is present with no duplicates (Requirement 10.4, Property 14).
    """
    existing = db.scalar(select(User).limit(1))
    if existing is not None:
        return

    db.add(User(username=username, password_hash=password_hash))
    db.commit()
