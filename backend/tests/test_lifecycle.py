"""Lifecycle and seeding tests for the application entrypoint (Tasks 10.3, 10.4).

Two concerns are covered:

- **Property 14 (seeding idempotence)**: calling the seeding helpers any number
  of times on a fresh in-memory database results in exactly the two example
  monitors and exactly one admin user, with no duplicates (Requirements 10.3,
  10.4).
- **Lifecycle smoke**: ``init_db`` creates the tables; a failing ``init_db``
  causes startup to propagate the error (Requirements 10.1, 10.2); and the
  scheduler is started and stopped across the app lifecycle (Requirement 10.5).

All database access uses a fresh in-memory SQLite engine and the scheduler is
monkeypatched with spies, so no real network or recurring jobs run.
"""

from __future__ import annotations

import asyncio
from typing import Callable, Iterator

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import Engine, inspect, select
from sqlalchemy.orm import Session, sessionmaker

import database
from database import Base
from models import Monitor, User


def _make_factory() -> tuple[Engine, Callable[[], Session]]:
    """Create a fresh in-memory engine with tables and a bound session factory."""
    engine: Engine = database._make_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )
    return engine, factory


# --- Property 14: seeding idempotence --------------------------------------

# Feature: uptime-guardian, Property 14: Seeding is idempotent
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(repeats=st.integers(min_value=1, max_value=8))
def test_seeding_is_idempotent(repeats: int) -> None:
    """Repeated seeding yields exactly two monitors and one admin user.

    For any number of repeated seed invocations on an initially empty database,
    the database contains exactly the Google and GitHub monitors and exactly one
    admin user, with no duplicates.

    Validates: Requirements 10.3, 10.4
    """
    import crud

    engine, factory = _make_factory()
    try:
        for _ in range(repeats):
            db = factory()
            try:
                # A fixed pre-hashed value stands in for the bcrypt hash; the
                # seeding helper does not interpret it, so this keeps the
                # property test fast and deterministic. The admin must be
                # seeded first so the example monitors can be owned by it
                # (Requirement 3.1).
                admin = crud.seed_admin_user(db, "admin", "hashed-admin-password")
                crud.seed_default_monitors(db, admin.id)
            finally:
                db.close()

        db = factory()
        try:
            monitors = list(db.scalars(select(Monitor).order_by(Monitor.name)).all())
            users = list(db.scalars(select(User)).all())
        finally:
            db.close()

        assert len(monitors) == 2
        assert [m.name for m in monitors] == ["GitHub", "Google"]
        assert {m.url for m in monitors} == {
            "https://github.com",
            "https://www.google.com",
        }
        assert len(users) == 1
        assert users[0].username == "admin"
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# --- Lifecycle smoke -------------------------------------------------------

def test_init_db_creates_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    """``init_db`` creates the monitors, check_results, and users tables.

    Validates: Requirements 10.1
    """
    engine = database._make_engine("sqlite://")
    monkeypatch.setattr(database, "engine", engine)

    database.init_db()

    table_names = set(inspect(engine).get_table_names())
    assert {"monitors", "check_results", "users"}.issubset(table_names)


def test_startup_propagates_init_db_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``init_db`` raises, the lifespan startup propagates the error.

    A broken schema must halt startup so the app does not serve requests.

    Validates: Requirements 10.1, 10.2
    """
    import main

    def boom() -> None:
        raise RuntimeError("create_all failed")

    started: list[bool] = []

    monkeypatch.setattr(main, "init_db", boom)
    monkeypatch.setattr(main, "_seed_initial_data", lambda: None)
    monkeypatch.setattr(main.scheduler, "start", lambda: started.append(True))
    monkeypatch.setattr(main.scheduler, "shutdown", lambda: None)

    async def drive() -> None:
        async with main.lifespan(main.app):
            pass

    with pytest.raises(RuntimeError, match="create_all failed"):
        asyncio.run(drive())

    # The scheduler must not have started when schema creation failed.
    assert started == []


def test_lifecycle_starts_and_stops_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scheduler is started on entry and stopped on exit of the lifespan.

    Validates: Requirements 10.5
    """
    import main

    events: list[str] = []

    monkeypatch.setattr(main, "init_db", lambda: events.append("init_db"))
    monkeypatch.setattr(main, "_run_migration", lambda: events.append("migrate"))
    monkeypatch.setattr(main, "_seed_initial_data", lambda: events.append("seed"))
    monkeypatch.setattr(main.scheduler, "start", lambda: events.append("start"))
    monkeypatch.setattr(main.scheduler, "shutdown", lambda: events.append("shutdown"))

    async def drive() -> None:
        async with main.lifespan(main.app):
            events.append("serving")

    asyncio.run(drive())

    # init_db, migration, and seeding happen before the scheduler starts;
    # shutdown runs last.
    assert events == ["init_db", "migrate", "seed", "start", "serving", "shutdown"]
