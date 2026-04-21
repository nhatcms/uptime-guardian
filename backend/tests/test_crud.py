"""Tests for CRUD and statistics helpers (Task 5).

Contains the property-based tests for the recent-results query (Property 11),
statistics aggregation (Property 12), and cascade delete (Property 13), plus an
edge-case unit test for empty statistics windows (Requirement 8.4).

Sessions are built from an engine created via ``database._make_engine`` so the
SQLite ``PRAGMA foreign_keys=ON`` listener is active and ``ON DELETE CASCADE``
fires, matching the application's real configuration.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

import database
import crud
from database import Base
from models import CheckResult, Monitor, User


def _make_session() -> tuple[Engine, Session]:
    """Create a fresh in-memory SQLite engine (FK cascade on) and a session."""
    engine = database._make_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    return engine, Session(engine)


def _make_owner(db: Session, username: str = "owner") -> int:
    """Create a Tenant_User to own monitors and return its id (Requirement 3.1)."""
    user = User(username=username, password_hash="x-hash")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.id


@pytest.fixture()
def session() -> Iterator[Session]:
    """Yield a session backed by a fresh in-memory database with FK cascade on."""
    engine, db = _make_session()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# --- Property 13: Cascade delete -------------------------------------------

# Feature: uptime-guardian, Property 13: Cascade delete removes a monitor and its results
@settings(max_examples=50, deadline=None)
@given(num_results=st.integers(min_value=0, max_value=30))
def test_property_13_cascade_delete_removes_monitor_and_results(
    num_results: int,
) -> None:
    """Deleting a monitor leaves no monitor with that id and zero results
    referencing it, for any number of associated results.

    Validates: Requirements 1.7
    """
    engine, db = _make_session()
    try:
        owner_id = _make_owner(db)
        monitor = Monitor(user_id=owner_id, name="site", url="https://example.com")
        for i in range(num_results):
            monitor.results.append(CheckResult(is_up=bool(i % 2), status_code=200))
        db.add(monitor)
        db.commit()
        monitor_id = monitor.id

        assert db.get(Monitor, monitor_id) is not None
        result_count = db.scalar(
            select(func.count())
            .select_from(CheckResult)
            .where(CheckResult.monitor_id == monitor_id)
        )
        assert result_count == num_results

        deleted = crud.delete_monitor(db, monitor_id)
        assert deleted is True

        assert db.get(Monitor, monitor_id) is None
        remaining = db.scalar(
            select(func.count())
            .select_from(CheckResult)
            .where(CheckResult.monitor_id == monitor_id)
        )
        assert remaining == 0
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# --- Property 11: Recent results query respects limit and ordering ---------

# Feature: uptime-guardian, Property 11: Recent results query respects limit and ordering
@settings(max_examples=50, deadline=None)
@given(
    offsets=st.lists(
        st.integers(min_value=0, max_value=100_000),
        min_size=0,
        max_size=40,
    ),
    limit=st.integers(min_value=1, max_value=50),
)
def test_property_11_recent_results_respects_limit_and_ordering(
    offsets: list[int], limit: int
) -> None:
    """For any set of results and any positive limit, get_results returns at
    most ``limit`` records, all for the requested monitor, ordered newest first.

    Validates: Requirements 8.1
    """
    engine, db = _make_session()
    try:
        # SQLite returns naive datetimes, so use a naive base to keep the
        # test's own offset arithmetic consistent with what is read back.
        base = datetime(2024, 1, 1)

        owner_id = _make_owner(db)
        target = Monitor(user_id=owner_id, name="target", url="https://example.com")
        other = Monitor(user_id=owner_id, name="other", url="https://other.example.com")
        db.add_all([target, other])
        db.commit()

        for sec in offsets:
            db.add(
                CheckResult(
                    monitor_id=target.id,
                    is_up=True,
                    status_code=200,
                    checked_at=base + timedelta(seconds=sec),
                )
            )
        # Noise belonging to another monitor must never be returned.
        db.add(
            CheckResult(
                monitor_id=other.id,
                is_up=False,
                status_code=500,
                checked_at=base + timedelta(seconds=999_999),
            )
        )
        db.commit()

        results = crud.get_results(db, target.id, limit=limit)

        assert len(results) <= limit
        assert len(results) == min(len(offsets), limit)
        assert all(r.monitor_id == target.id for r in results)

        timestamps = [r.checked_at for r in results]
        assert timestamps == sorted(timestamps, reverse=True)

        # The returned records are the newest ``limit`` of the target's results.
        all_sorted = sorted(offsets, reverse=True)
        expected_top = all_sorted[:limit]
        returned_offsets = [
            int((r.checked_at - base).total_seconds()) for r in results
        ]
        assert returned_offsets == expected_top
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# --- Property 12: Statistics aggregation is consistent ---------------------

@st.composite
def _check_result_fields(draw: st.DrawFn) -> tuple[bool, float | None]:
    """Generate (is_up, response_time_ms) pairs; response time may be None."""
    is_up = draw(st.booleans())
    response_time = draw(
        st.one_of(
            st.none(),
            st.floats(
                min_value=0.0,
                max_value=60_000.0,
                allow_nan=False,
                allow_infinity=False,
            ),
        )
    )
    return is_up, response_time


# Feature: uptime-guardian, Property 12: Statistics aggregation is consistent
@settings(max_examples=50, deadline=None)
@given(rows=st.lists(_check_result_fields(), min_size=1, max_size=50))
def test_property_12_statistics_aggregation_is_consistent(
    rows: list[tuple[bool, float | None]],
) -> None:
    """For any non-empty set of results, compute_stats yields a consistent
    uptime percentage, counts, and ordered response-time aggregates.

    Validates: Requirements 8.2, 8.3
    """
    results = [
        CheckResult(
            monitor_id=1,
            is_up=is_up,
            status_code=200 if is_up else 500,
            response_time_ms=rt,
        )
        for is_up, rt in rows
    ]

    stats = crud.compute_stats(results)

    total = len(rows)
    up_count = sum(1 for is_up, _ in rows if is_up)

    assert stats.total_checks == total
    assert stats.failed_checks == total - up_count
    assert stats.uptime_percentage == pytest.approx((up_count / total) * 100.0)
    assert 0.0 <= stats.uptime_percentage <= 100.0
    # Allow for floating-point rounding in the average computation: when all
    # response times are equal, avg may differ from min/max by ~1e-16.
    assert stats.min_response_time_ms <= stats.avg_response_time_ms or (
        stats.min_response_time_ms == pytest.approx(stats.avg_response_time_ms)
    )
    assert stats.avg_response_time_ms <= stats.max_response_time_ms or (
        stats.avg_response_time_ms == pytest.approx(stats.max_response_time_ms)
    )


# --- Edge case: empty stats window (Requirement 8.4) -----------------------

def test_compute_stats_empty_returns_all_zero() -> None:
    """compute_stats([]) returns all-zero values without raising.

    Validates: Requirements 8.4
    """
    stats = crud.compute_stats([])

    assert stats.total_checks == 0
    assert stats.failed_checks == 0
    assert stats.uptime_percentage == 0.0
    assert stats.avg_response_time_ms == 0.0
    assert stats.min_response_time_ms == 0.0
    assert stats.max_response_time_ms == 0.0
