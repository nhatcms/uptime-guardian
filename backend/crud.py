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

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import CheckResult, Monitor, Plan, Transaction, User
from schemas import MonitorCreate, MonitorUpdate, StatsOut

# The two example monitors seeded on first run (Requirement 10.3).
_DEFAULT_MONITORS: tuple[tuple[str, str, int], ...] = (
    ("Google", "https://www.google.com", 5),
    ("GitHub", "https://github.com", 5),
)

# Maximum rows returned by any admin listing (Requirements 17.4, 18.5).
MAX_LISTING_ROWS: int = 100


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


# --- Monitor CRUD ----------------------------------------------------------

def create_monitor(db: Session, data: MonitorCreate, user_id: int) -> Monitor:
    """Persist a new monitor owned by ``user_id`` from a validated payload.

    Every monitor is owned by exactly one Tenant_User via the non-null
    ``user_id`` foreign key (Requirement 3.1). ``is_active`` defaults to true
    and ``notify_on_failure`` to true via the model column defaults.
    """
    monitor = Monitor(
        user_id=user_id,
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


# --- Owner-scoped monitor access (tenant isolation) ------------------------

def get_monitors_for_user(db: Session, user_id: int) -> list[Monitor]:
    """Return only the monitors owned by ``user_id`` (Requirements 4.1, 4.2)."""
    stmt = (
        select(Monitor)
        .where(Monitor.user_id == user_id)
        .order_by(Monitor.id)
    )
    return list(db.scalars(stmt).all())


def get_owned_monitor(
    db: Session, user_id: int, monitor_id: int
) -> Optional[Monitor]:
    """Return the monitor iff it exists AND is owned by ``user_id``.

    Returns ``None`` both when the monitor does not exist and when it belongs to
    a different tenant, so callers raise an identical 404 for the two cases
    (Requirements 4.3, 4.4, 4.5).
    """
    monitor = db.get(Monitor, monitor_id)
    if monitor is None or monitor.user_id != user_id:
        return None
    return monitor


def count_monitors_for_user(db: Session, user_id: int) -> int:
    """Return the number of monitors owned by ``user_id`` (Requirement 5)."""
    count = db.scalar(
        select(func.count())
        .select_from(Monitor)
        .where(Monitor.user_id == user_id)
    )
    return int(count or 0)


def update_owned_monitor(
    db: Session, user_id: int, monitor_id: int, data: MonitorUpdate
) -> Optional[Monitor]:
    """Apply updates to a monitor owned by ``user_id``; return it or ``None``.

    Returns ``None`` when the monitor does not exist or is owned by another
    tenant, leaving that monitor unchanged (Requirement 4.7).
    """
    monitor = get_owned_monitor(db, user_id, monitor_id)
    if monitor is None:
        return None

    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(monitor, field, value)

    db.commit()
    db.refresh(monitor)
    return monitor


def delete_owned_monitor(db: Session, user_id: int, monitor_id: int) -> bool:
    """Delete a monitor owned by ``user_id``; return ``True`` if deleted.

    Returns ``False`` when the monitor does not exist or is owned by another
    tenant, leaving it unchanged (Requirement 4.7).
    """
    monitor = get_owned_monitor(db, user_id, monitor_id)
    if monitor is None:
        return False

    db.delete(monitor)
    db.commit()
    return True


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


def create_tenant_user(
    db: Session,
    *,
    username: str,
    email: str,
    password_hash: str,
    plan_id: int,
    is_admin: bool = False,
) -> User:
    """Persist a new Tenant_User on the given Plan (Requirements 2.5, 11.5).

    ``plan_expires_at`` is left unset so the user is treated as being on the
    Free Plan until a paid upgrade completes (Requirement 2.7).
    """
    user = User(
        username=username,
        email=email,
        password_hash=password_hash,
        plan_id=plan_id,
        is_admin=is_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """Return the user with ``email`` or ``None`` if not found."""
    stmt = select(User).where(User.email == email)
    return db.scalars(stmt).first()


def get_user_by_google_id(db: Session, google_id: str) -> Optional[User]:
    """Return the user whose ``google_id`` matches, or ``None`` if not found."""
    stmt = select(User).where(User.google_id == google_id)
    return db.scalars(stmt).first()


def _unique_username_from_email(db: Session, email: str) -> str:
    """Derive a unique username from an email's local part.

    Uses the part before "@" as the base, sanitized to alphanumerics/._-, and
    appends a numeric suffix when the candidate already exists so the username
    uniqueness invariant holds for auto-provisioned Google accounts.
    """
    base = re.sub(r"[^A-Za-z0-9._-]", "", email.split("@", 1)[0]) or "user"
    candidate = base
    suffix = 1
    while get_user_by_username(db, candidate) is not None:
        suffix += 1
        candidate = f"{base}{suffix}"
    return candidate


def create_google_user(
    db: Session,
    *,
    google_id: str,
    email: str,
    display_name: Optional[str],
    avatar_url: Optional[str],
    plan_id: int,
) -> User:
    """Create a Tenant_User provisioned from a Google profile.

    The account is created with ``email_verified=True`` because Google has
    already verified the address. It is given a random, unusable password hash
    so password login can never succeed (the user signs in via Google) while
    still satisfying databases whose ``password_hash`` column predates the
    nullable change and is still ``NOT NULL``. A username is derived uniquely
    from the email local part (``display_name`` is accepted for
    forward-compatibility but the stored username must satisfy the uniqueness
    constraint). The user starts on the Free Plan (Requirements 2.5, 2.7).
    """
    from auth import hash_password  # lazy import to avoid import-order coupling

    username = _unique_username_from_email(db, email)
    # A random secret nobody holds: bcrypt of 32 random bytes. This keeps the
    # NOT NULL constraint satisfied on legacy schemas while making password
    # authentication impossible for a Google-provisioned account.
    unusable_password_hash = hash_password(secrets.token_urlsafe(32))
    user = User(
        username=username,
        email=email,
        password_hash=unusable_password_hash,
        google_id=google_id,
        avatar_url=avatar_url,
        email_verified=True,
        plan_id=plan_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def link_google_account(
    db: Session,
    user: User,
    *,
    google_id: str,
    avatar_url: Optional[str] = None,
) -> User:
    """Attach a Google identity to an existing (manually created) account.

    Sets ``google_id`` and marks the email verified (Google has verified it),
    backfilling ``avatar_url`` only when the account has none so a manual
    profile choice is preserved. The existing password is left intact so the
    user can still log in either way.
    """
    user.google_id = google_id
    user.email_verified = True
    if avatar_url and not user.avatar_url:
        user.avatar_url = avatar_url
    db.commit()
    db.refresh(user)
    return user


# --- Plan CRUD -------------------------------------------------------------

def get_plan(db: Session, plan_id: int) -> Optional[Plan]:
    """Return the plan with ``plan_id`` or ``None`` if it does not exist."""
    return db.get(Plan, plan_id)


def get_plan_by_name_ci(db: Session, name: str) -> Optional[Plan]:
    """Return the plan whose name matches ``name`` case-insensitively (Req 1.6)."""
    stmt = select(Plan).where(func.lower(Plan.name) == name.lower())
    return db.scalars(stmt).first()


def get_plans(db: Session) -> list[Plan]:
    """Return all plans ordered by id (Requirement 17.4)."""
    return list(db.scalars(select(Plan).order_by(Plan.id)).all())


def create_plan(db: Session, data) -> Plan:
    """Persist a new plan from a validated ``PlanCreate`` (Requirement 17.1)."""
    plan = Plan(
        name=data.name,
        price=data.price,
        max_monitors=data.max_monitors,
        ssl_check_enabled=data.ssl_check_enabled,
        min_interval_minutes=data.min_interval_minutes,
        duration_days=data.duration_days,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def update_plan(db: Session, plan: Plan, data) -> Plan:
    """Apply a validated ``PlanUpdate`` to ``plan`` (Requirement 17.3)."""
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(plan, field, value)
    db.commit()
    db.refresh(plan)
    return plan


def delete_plan(db: Session, plan: Plan) -> None:
    """Delete ``plan`` (caller must ensure it has no subscribers; Req 17.5)."""
    db.delete(plan)
    db.commit()


def count_plan_subscribers(db: Session, plan_id: int) -> int:
    """Return how many users currently reference ``plan_id`` (Requirement 17.6)."""
    count = db.scalar(
        select(func.count())
        .select_from(User)
        .where(User.plan_id == plan_id)
    )
    return int(count or 0)


# --- Transaction CRUD ------------------------------------------------------

def create_transaction(
    db: Session,
    *,
    user_id: int,
    plan_id: int,
    amount,  # Decimal
    reference_code: str,
    status: str = "pending",
) -> Transaction:
    """Persist a new transaction and return it (Requirement 13.1)."""
    txn = Transaction(
        user_id=user_id,
        plan_id=plan_id,
        amount=amount,
        reference_code=reference_code,
        status=status,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def get_transaction_by_reference(
    db: Session, reference_code: str
) -> Optional[Transaction]:
    """Return the transaction with ``reference_code`` or ``None``."""
    stmt = select(Transaction).where(
        Transaction.reference_code == reference_code
    )
    return db.scalars(stmt).first()


def get_pending_transaction(
    db: Session, user_id: int, plan_id: int
) -> Optional[Transaction]:
    """Return an existing pending transaction for the user+plan, or ``None``.

    Supports the single-pending idempotency rule for payment initiation
    (Requirement 13.5).
    """
    stmt = select(Transaction).where(
        Transaction.user_id == user_id,
        Transaction.plan_id == plan_id,
        Transaction.status == "pending",
    )
    return db.scalars(stmt).first()


def list_transactions(
    db: Session, limit: int = MAX_LISTING_ROWS
) -> list[Transaction]:
    """Return up to ``limit`` transactions, newest first (Requirement 18.5)."""
    capped = min(limit, MAX_LISTING_ROWS)
    stmt = (
        select(Transaction)
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .limit(capped)
    )
    return list(db.scalars(stmt).all())


def list_users(db: Session, limit: int = MAX_LISTING_ROWS) -> list[User]:
    """Return up to ``limit`` users ordered by id (Requirements 18.1, 18.5)."""
    capped = min(limit, MAX_LISTING_ROWS)
    stmt = select(User).order_by(User.id).limit(capped)
    return list(db.scalars(stmt).all())


# --- Seeding helpers (idempotent) ------------------------------------------

def seed_default_monitors(db: Session, user_id: int) -> None:
    """Insert the two example monitors for ``user_id`` if none exist yet.

    Idempotent: repeated invocations after the first leave the table unchanged,
    so the database always contains exactly the Google and GitHub monitors and
    no duplicates (Requirement 10.3, Property 14). The seeded monitors are owned
    by ``user_id`` so the non-null ownership invariant holds (Requirement 3.1).
    """
    existing = db.scalar(select(Monitor).limit(1))
    if existing is not None:
        return

    for name, url, interval in _DEFAULT_MONITORS:
        db.add(
            Monitor(
                user_id=user_id,
                name=name,
                url=url,
                check_interval_minutes=interval,
            )
        )
    db.commit()


def seed_admin_user(db: Session, username: str, password_hash: str) -> User:
    """Insert the admin user if the users table is empty; return the admin user.

    Idempotent: once a user exists, the existing first user is returned and no
    new row is created, so exactly one admin user is present with no duplicates
    (Requirement 10.4, Property 14). The returned user's id is used to own the
    seeded default monitors so the ownership invariant holds (Requirement 3.1).
    """
    existing = db.scalar(select(User).order_by(User.id).limit(1))
    if existing is not None:
        return existing

    user = User(username=username, password_hash=password_hash, is_admin=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
