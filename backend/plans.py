"""Plan seeding, active-plan resolution, and enforcement (multi-tenant SaaS).

This module centralizes all plan-tier decision logic so the 200 ms active-plan
budget (Requirement 16.5) and the past/future/empty/unresolved rules
(Requirements 16.1-16.4) are implemented and tested in exactly one place and
reused by request-time enforcement, the scheduler, and the dashboard.

Key behaviors:

- :func:`seed_free_plan` idempotently seeds the single Free Plan on a database
  with no Plan records (Requirement 1.8).
- :func:`resolve_active_plan` always returns a concrete :class:`Plan` (never
  ``None``), applying the expiry rules of Requirement 16 with O(1) indexed
  lookups.

Feature: saas-multi-tenant.
Requirements traceability: 1.8, 2.5, 16.1, 16.2, 16.3, 16.4, 16.5.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config import load_settings
from models import Monitor, Plan, User

logger = logging.getLogger(__name__)


class PlanLimitError(Exception):
    """Raised when a create would exceed the active Plan's Max_Monitors (403)."""

    def __init__(self, max_monitors: int) -> None:
        self.max_monitors = max_monitors
        super().__init__(
            f"Monitor limit reached for the active plan (max {max_monitors})"
        )


class NoActivePlanError(Exception):
    """Raised when no active Plan can be resolved for the user (403)."""


class IntervalTooLowError(Exception):
    """Raised when a requested interval is below the Plan minimum (403)."""

    def __init__(self, min_interval_minutes: int) -> None:
        self.min_interval_minutes = min_interval_minutes
        super().__init__(
            "Check interval is below the active plan minimum of "
            f"{min_interval_minutes} minute(s)"
        )


class InvalidIntervalError(ValueError):
    """Raised when an interval is missing, non-numeric, zero, or negative (400)."""


@dataclass(frozen=True)
class PlanSeed:
    """Immutable attribute set used to seed a Plan."""

    name: str
    price: Decimal
    max_monitors: int
    ssl_check_enabled: bool
    min_interval_minutes: int
    duration_days: int


# Free Plan defaults (Requirement 1.8): name "Free", price 0, max_monitors 1,
# SSL disabled, min interval 5 minutes, no expiry (duration 0).
FREE_PLAN_DEFAULTS = PlanSeed(
    name="Free",
    price=Decimal("0"),
    max_monitors=1,
    ssl_check_enabled=False,
    min_interval_minutes=5,
    duration_days=0,
)


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


def _as_aware_utc(value: datetime) -> datetime:
    """Return ``value`` as a timezone-aware UTC datetime.

    SQLite returns naive datetimes for ``DateTime(timezone=True)`` columns;
    treat a naive value as already being in UTC so expiry comparisons are
    consistent regardless of the backend.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _free_plan_name() -> str:
    """Return the configured Free Plan name (defaults to "Free")."""
    return load_settings().free_plan_name or FREE_PLAN_DEFAULTS.name


def seed_free_plan(db: Session) -> Plan:
    """Seed the Free Plan if no Plan records exist; return the Free Plan.

    Idempotent (Requirement 1.8): when the ``plans`` table already contains any
    row, no new plan is created and the existing Free Plan is returned. The
    seeded plan uses :data:`FREE_PLAN_DEFAULTS` with the configured name.
    """
    existing_any = db.scalar(select(Plan).limit(1))
    if existing_any is not None:
        return get_free_plan(db)

    free = Plan(
        name=_free_plan_name(),
        price=FREE_PLAN_DEFAULTS.price,
        max_monitors=FREE_PLAN_DEFAULTS.max_monitors,
        ssl_check_enabled=FREE_PLAN_DEFAULTS.ssl_check_enabled,
        min_interval_minutes=FREE_PLAN_DEFAULTS.min_interval_minutes,
        duration_days=FREE_PLAN_DEFAULTS.duration_days,
    )
    db.add(free)
    db.commit()
    db.refresh(free)
    return free


def get_free_plan(db: Session) -> Plan:
    """Return the Free Plan, matching its name case-insensitively.

    Falls back to seeding the Free Plan when it is unexpectedly absent so the
    function always returns a concrete plan. Raises only if seeding cannot
    produce a plan (a corrupt database), which callers surface as 403.
    """
    name = _free_plan_name()
    stmt = select(Plan).where(func.lower(Plan.name) == name.lower())
    plan = db.scalars(stmt).first()
    if plan is not None:
        return plan
    # Absent Free Plan: seed it (idempotent on an otherwise empty table) or, if
    # other plans exist, create the Free Plan explicitly.
    return _ensure_free_plan(db)


def _ensure_free_plan(db: Session) -> Plan:
    """Create the Free Plan when it is missing; return it."""
    free = Plan(
        name=_free_plan_name(),
        price=FREE_PLAN_DEFAULTS.price,
        max_monitors=FREE_PLAN_DEFAULTS.max_monitors,
        ssl_check_enabled=FREE_PLAN_DEFAULTS.ssl_check_enabled,
        min_interval_minutes=FREE_PLAN_DEFAULTS.min_interval_minutes,
        duration_days=FREE_PLAN_DEFAULTS.duration_days,
    )
    db.add(free)
    db.commit()
    db.refresh(free)
    return free


def resolve_active_plan(
    db: Session, user: User, now: Optional[datetime] = None
) -> Plan:
    """Return ``user``'s currently active Plan (Requirement 16).

    Rules, evaluated with O(1) indexed lookups to stay within the 200 ms budget
    (Requirement 16.5):

    * ``plan_expires_at`` is None              -> Free Plan        (16.3)
    * ``plan_expires_at`` <= now (UTC)         -> Free Plan        (16.1)
    * ``plan_expires_at`` >  now AND plan_id resolves -> that Plan (16.2)
    * ``plan_expires_at`` >  now BUT plan_id unresolved -> Free + log (16.4)

    Always returns a concrete Plan; never raises for a missing paid plan.
    """
    current = now or _utcnow()
    current = _as_aware_utc(current)

    expires_at = user.plan_expires_at
    if expires_at is None:
        # No expiry recorded: treat as the Free Plan (16.3).
        return get_free_plan(db)

    if _as_aware_utc(expires_at) <= current:
        # Paid plan has lapsed: revert to Free (16.1).
        return get_free_plan(db)

    # Plan is currently in effect; resolve the referenced plan (16.2).
    if user.plan_id is not None:
        plan = db.get(Plan, user.plan_id)
        if plan is not None:
            return plan

    # Active window but the referenced plan cannot be resolved (16.4).
    logger.warning(
        "Active plan window for user_id=%s but plan_id=%s could not be "
        "resolved; falling back to the Free Plan",
        getattr(user, "id", "?"),
        user.plan_id,
    )
    return get_free_plan(db)


# --- Enforcement helpers ---------------------------------------------------

def _active_plan_or_raise(db: Session, user: User) -> Plan:
    """Return the user's active Plan, or raise :class:`NoActivePlanError`.

    :func:`resolve_active_plan` always returns the Free Plan as a fallback, so
    this only raises when even the Free Plan cannot be resolved or created (a
    corrupt database), which the router surfaces as 403 (Requirements 5.3, 6.6,
    8.2).
    """
    try:
        plan = resolve_active_plan(db, user)
    except Exception as exc:  # pragma: no cover - corrupt-DB defensive path
        raise NoActivePlanError(str(exc)) from exc
    if plan is None:  # pragma: no cover - resolve never returns None
        raise NoActivePlanError("no active plan could be resolved")
    return plan


def _validate_interval_value(interval: object) -> int:
    """Return ``interval`` as a positive int or raise :class:`InvalidIntervalError`.

    Rejects missing, non-numeric, zero, and negative values (Requirement 6.5).
    Booleans are rejected even though ``bool`` subclasses ``int``.
    """
    if interval is None or isinstance(interval, bool):
        raise InvalidIntervalError("check interval is required")
    if not isinstance(interval, int):
        raise InvalidIntervalError("check interval must be an integer")
    if interval <= 0:
        raise InvalidIntervalError("check interval must be a positive integer")
    return interval


def enforce_can_create_monitor(
    db: Session, user: User, requested_interval: object
) -> Plan:
    """Authorize creating a monitor for ``user`` and return the active Plan.

    Validates the requested interval against the active Plan minimum and the
    owner's current monitor count against the Plan's Max_Monitors. Raises:

    * :class:`InvalidIntervalError` -> 400 (Requirement 6.5)
    * :class:`IntervalTooLowError`  -> 403 (Requirement 6.2)
    * :class:`NoActivePlanError`    -> 403 (Requirement 5.3, 6.6)
    * :class:`PlanLimitError`       -> 403 (Requirement 5.2)

    Atomicity (Requirement 5.4): the active-plan lookup and the count run inside
    the session's ``BEGIN IMMEDIATE`` transaction (configured on the SQLite
    engine), which holds the reserved write lock until the caller inserts the
    monitor and commits. Two concurrent creates therefore cannot both observe
    ``count == max - 1`` and both insert. On success the transaction remains
    open so the caller's insert occurs under the same lock.
    """
    interval = _validate_interval_value(requested_interval)
    plan = _active_plan_or_raise(db, user)

    if interval < plan.min_interval_minutes:
        raise IntervalTooLowError(plan.min_interval_minutes)

    current_count = db.scalar(
        select(func.count())
        .select_from(Monitor)
        .where(Monitor.user_id == user.id)
    )
    if int(current_count or 0) >= plan.max_monitors:
        raise PlanLimitError(plan.max_monitors)

    return plan


def enforce_interval_for_update(
    db: Session, user: User, new_interval: object
) -> Plan:
    """Authorize updating a monitor's interval for ``user``; return active Plan.

    Raises :class:`InvalidIntervalError` (400) for missing/zero/negative values
    (Requirement 6.5), :class:`IntervalTooLowError` (403) when below the active
    Plan minimum (Requirement 6.4), or :class:`NoActivePlanError` (403) when no
    active Plan can be resolved (Requirement 6.6). The targeted monitor is left
    unchanged when this raises.
    """
    interval = _validate_interval_value(new_interval)
    plan = _active_plan_or_raise(db, user)
    if interval < plan.min_interval_minutes:
        raise IntervalTooLowError(plan.min_interval_minutes)
    return plan
