"""Smoke and unit tests for the persistence layer.

Covers schema URL validation (good URLs accepted, bad URLs rejected),
ORM model registration, and ``init_db`` table creation. The formal
property-based tests for cascade delete and seeding live in their owning
tasks (Properties 13 and 14); these tests only verify the basic wiring.

Validates: Requirements 1.1, 1.2, 10.1
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.orm import Session

import database
import models
from database import Base
from schemas import MonitorCreate, MonitorOut, MonitorWithLatest
from models import CheckResult, Monitor


# --- Schema URL validation -------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "https://www.google.com",
        "http://example.com",
        "https://sub.domain.example.com/path?q=1",
        "http://localhost:8000",
    ],
)
def test_monitor_create_accepts_valid_urls(url: str) -> None:
    """Requirement 1.2: well-formed http/https URLs are accepted."""
    monitor = MonitorCreate(name="site", url=url)
    assert monitor.url == url


@pytest.mark.parametrize(
    "url",
    [
        "not-a-url",
        "ftp://example.com",
        "www.google.com",
        "",
        "javascript:alert(1)",
    ],
)
def test_monitor_create_rejects_invalid_urls(url: str) -> None:
    """Requirement 1.2: malformed/non-http URLs raise a validation error."""
    with pytest.raises(ValidationError):
        MonitorCreate(name="site", url=url)


def test_monitor_create_defaults_interval_to_five() -> None:
    """check_interval_minutes defaults to 5 when omitted."""
    monitor = MonitorCreate(name="site", url="https://example.com")
    assert monitor.check_interval_minutes == 5


# --- ORM <-> schema serialization -----------------------------------------

def test_monitor_out_serializes_from_orm_object() -> None:
    """MonitorOut serializes directly from an ORM Monitor (from_attributes)."""
    monitor = Monitor(
        id=1,
        name="Google",
        url="https://www.google.com",
        is_active=True,
        check_interval_minutes=5,
        notify_on_failure=True,
    )
    # created_at is normally auto-set on flush; set explicitly for this unit test.
    from datetime import datetime, timezone

    monitor.created_at = datetime.now(timezone.utc)

    out = MonitorOut.model_validate(monitor)
    assert out.id == 1
    assert out.name == "Google"
    assert out.url == "https://www.google.com"

    with_latest = MonitorWithLatest.model_validate(monitor)
    assert with_latest.latest is None


# --- init_db / table creation ---------------------------------------------

def test_init_db_creates_all_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    """Requirement 10.1: init_db creates tables for monitors, results, users."""
    test_engine = database._make_engine("sqlite://")
    monkeypatch.setattr(database, "engine", test_engine)

    database.init_db()

    table_names = set(inspect(test_engine).get_table_names())
    assert {"monitors", "check_results", "users"}.issubset(table_names)


def test_models_register_relationship_and_cascade() -> None:
    """A monitor and its results round-trip; deleting cascades to results.

    Uses ``_make_engine`` so the SQLite ON DELETE CASCADE pragma listener is
    active, matching the application's real configuration (Requirement 1.7).
    """
    test_engine = database._make_engine("sqlite://")
    Base.metadata.create_all(bind=test_engine)

    with Session(test_engine) as session:
        monitor = Monitor(name="GitHub", url="https://github.com")
        monitor.results.append(CheckResult(is_up=True, status_code=200))
        session.add(monitor)
        session.commit()

        monitor_id = monitor.id
        assert session.get(Monitor, monitor_id) is not None
        assert session.query(CheckResult).count() == 1

        session.delete(monitor)
        session.commit()

        assert session.get(Monitor, monitor_id) is None
        assert session.query(CheckResult).count() == 0
