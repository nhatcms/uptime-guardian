"""Integration tests for the scheduler (Task 8.2).

These tests drive a :class:`MonitorScheduler` against a fresh in-memory SQLite
database built via ``database._make_engine`` so the real session/ORM path is
exercised without touching the application's on-disk database or the network.
The scheduled jobs use minute-level interval triggers, so they do not fire
during these short structural assertions; no real HTTP or Telegram I/O occurs.

Covered behaviors:
- One job is registered per active monitor when the scheduler starts
  (Requirement 4.1).
- ``reload_scheduler`` picks up a newly added monitor's job without a restart
  (Requirement 4.3).
- Shutdown stops the scheduler and its jobs (Requirement 10.5).
- The registered job callables are coroutine functions, so checks run on the
  event loop without blocking it (Requirement 4.4).
"""

from __future__ import annotations

import asyncio
from typing import Callable, Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

import database
from database import Base
from models import Monitor, User
from scheduler import MonitorScheduler


@pytest.fixture()
def session_factory() -> Iterator[Callable[[], Session]]:
    """Yield a session factory bound to a fresh in-memory database.

    A single shared in-memory engine (``StaticPool`` semantics via the
    ``_make_engine`` SQLite configuration) backs the factory so the scheduler
    and the test see the same data.
    """
    engine: Engine = database._make_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _add_monitor(
    factory: Callable[[], Session],
    *,
    name: str,
    url: str,
    is_active: bool = True,
    interval: int = 5,
) -> int:
    """Insert a monitor via the factory and return its id."""
    db = factory()
    try:
        # Ensure an owning Tenant_User exists; monitors require a non-null
        # owner (Requirement 3.1). A single shared owner is reused.
        owner = db.query(User).first()
        if owner is None:
            owner = User(
                username="owner",
                password_hash="x-hash",
                telegram_chat_id="123456",
            )
            db.add(owner)
            db.commit()
            db.refresh(owner)
        monitor = Monitor(
            user_id=owner.id,
            name=name,
            url=url,
            is_active=is_active,
            check_interval_minutes=interval,
        )
        db.add(monitor)
        db.commit()
        db.refresh(monitor)
        return monitor.id
    finally:
        db.close()


def _make_started_scheduler(
    factory: Callable[[], Session],
) -> MonitorScheduler:
    """Create a scheduler on the running loop, start it, and return it."""
    scheduler = MonitorScheduler(session_factory=factory)
    scheduler.start()
    return scheduler


async def test_start_registers_one_job_per_active_monitor(
    session_factory: Callable[[], Session],
) -> None:
    """On start, exactly one job is registered for each active monitor.

    An inactive monitor must not be scheduled.

    Validates: Requirements 4.1
    """
    _add_monitor(session_factory, name="A", url="https://a.example")
    _add_monitor(session_factory, name="B", url="https://b.example")
    _add_monitor(
        session_factory, name="Inactive", url="https://c.example", is_active=False
    )

    scheduler = _make_started_scheduler(session_factory)
    try:
        jobs = scheduler.get_jobs()
        assert len(jobs) == 2
    finally:
        scheduler.shutdown()


async def test_reload_registers_newly_added_monitor_job(
    session_factory: Callable[[], Session],
) -> None:
    """``reload_scheduler`` schedules a monitor added after start.

    Validates: Requirements 4.3
    """
    _add_monitor(session_factory, name="A", url="https://a.example")
    scheduler = _make_started_scheduler(session_factory)
    try:
        assert len(scheduler.get_jobs()) == 1

        _add_monitor(session_factory, name="B", url="https://b.example")
        scheduler.reload_scheduler()

        assert len(scheduler.get_jobs()) == 2
    finally:
        scheduler.shutdown()


async def test_shutdown_stops_jobs(
    session_factory: Callable[[], Session],
) -> None:
    """Shutdown stops the scheduler so no jobs remain scheduled.

    Validates: Requirements 10.5
    """
    _add_monitor(session_factory, name="A", url="https://a.example")
    scheduler = _make_started_scheduler(session_factory)
    assert scheduler.running is True
    assert len(scheduler.get_jobs()) == 1

    scheduler.shutdown()
    # AsyncIOScheduler.shutdown is dispatched onto the event loop, so yield
    # control once to let it run before asserting the scheduler has stopped.
    await asyncio.sleep(0)

    assert scheduler.running is False


async def test_registered_jobs_are_coroutine_functions(
    session_factory: Callable[[], Session],
) -> None:
    """Each scheduled job callable is a coroutine function.

    This guarantees checks run on the event loop without blocking it.

    Validates: Requirements 4.4
    """
    _add_monitor(session_factory, name="A", url="https://a.example")
    _add_monitor(session_factory, name="B", url="https://b.example")

    scheduler = _make_started_scheduler(session_factory)
    try:
        jobs = scheduler.get_jobs()
        assert jobs
        for job in jobs:
            assert asyncio.iscoroutinefunction(job.func)
    finally:
        scheduler.shutdown()


# --- run_check job body (Requirements 4.2, 5.1, 6.1) -----------------------


def _make_check_result(
    monitor_id: int,
    *,
    is_up: bool,
    status_code: int | None,
    ssl_days_remaining: int | None = None,
) -> object:
    """Build an unsaved CheckResult-like object mirroring ``check_monitor``."""
    from models import CheckResult

    return CheckResult(
        monitor_id=monitor_id,
        status_code=status_code,
        response_time_ms=12.5,
        is_up=is_up,
        ssl_valid=None if ssl_days_remaining is None else ssl_days_remaining > 0,
        ssl_days_remaining=ssl_days_remaining,
        error_message=None if is_up else "boom",
    )


async def test_run_check_persists_result(
    session_factory: Callable[[], Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The job body persists the result returned by the checker.

    Validates: Requirements 4.2
    """
    import scheduler as scheduler_module

    monitor_id = _add_monitor(
        session_factory, name="A", url="https://a.example"
    )

    async def fake_check(monitor: Monitor) -> object:
        return _make_check_result(monitor.id, is_up=True, status_code=200)

    monkeypatch.setattr(scheduler_module, "check_monitor", fake_check)

    sched = MonitorScheduler(session_factory=session_factory)
    await sched.run_check(monitor_id)

    import crud

    db = session_factory()
    try:
        latest = crud.get_latest_result(db, monitor_id)
        assert latest is not None
        assert latest.is_up is True
        assert latest.status_code == 200
    finally:
        db.close()


async def test_run_check_dispatches_down_alert_on_transition(
    session_factory: Callable[[], Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An up -> down transition dispatches exactly one down alert and records it.

    Validates: Requirements 5.1
    """
    import crud
    import scheduler as scheduler_module

    monitor_id = _add_monitor(
        session_factory, name="A", url="https://a.example"
    )
    # Seed a prior "up" result so the next down result is a transition.
    db = session_factory()
    try:
        crud.create_check_result(db, monitor_id, is_up=True, status_code=200)
    finally:
        db.close()

    sent: list[str] = []

    async def fake_send(message: str, chat_id: str) -> None:
        sent.append(message)

    async def fake_check(monitor: Monitor) -> object:
        return _make_check_result(monitor.id, is_up=False, status_code=500)

    monkeypatch.setattr(scheduler_module, "send_telegram_alert", fake_send)
    monkeypatch.setattr(scheduler_module, "check_monitor", fake_check)

    sched = MonitorScheduler(session_factory=session_factory)
    await sched.run_check(monitor_id)

    assert len(sent) == 1
    assert "SITE DOWN" in sent[0]


async def test_run_check_isolates_failures(
    session_factory: Callable[[], Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure inside the job body is contained and does not propagate.

    Validates: Requirements 4.4
    """
    import scheduler as scheduler_module

    monitor_id = _add_monitor(
        session_factory, name="A", url="https://a.example"
    )

    async def boom(monitor: Monitor) -> object:
        raise RuntimeError("checker exploded")

    monkeypatch.setattr(scheduler_module, "check_monitor", boom)

    sched = MonitorScheduler(session_factory=session_factory)
    # Must not raise despite the checker failing.
    await sched.run_check(monitor_id)
