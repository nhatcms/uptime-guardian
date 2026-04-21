"""Property-based tests for Uptime Guardian.

Each test corresponds to exactly one numbered correctness property from the
design document and is tagged accordingly. Properties are added next to the
code they validate as their owning tasks are implemented.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from config import (
    DEFAULT_ALERT_COOLDOWN_MINUTES,
    DEFAULT_CHECK_INTERVAL_MINUTES,
    Settings,
)

# Required fields needed to construct Settings without touching the environment.
_REQUIRED: dict[str, str] = {
    "telegram_bot_token": "test_token",
    "telegram_chat_id": "test_chat",
    "auth_secret_key": "test_secret",
}


def _make_settings(**overrides: object) -> Settings:
    """Build Settings with required fields, ignoring any ambient `.env`."""
    return Settings(_env_file=None, **{**_REQUIRED, **overrides})  # type: ignore[arg-type]


# Strategy for values that are NOT positive integers: zero, negatives,
# fractional floats, non-numeric strings, and floats that are not whole.
_invalid_numeric = st.one_of(
    st.integers(max_value=0),
    st.floats(min_value=-1000, max_value=1000).filter(
        lambda f: not (f == f and float(f).is_integer() and f > 0)
    ),
    st.text(max_size=8).filter(lambda s: not s.strip().lstrip("-").isdigit()),
)


# Feature: uptime-guardian, Property 15: Configuration falls back on invalid values
@settings(max_examples=50)
@given(bad_interval=_invalid_numeric, bad_cooldown=_invalid_numeric)
def test_property_15_config_falls_back_on_invalid_values(
    bad_interval: object, bad_cooldown: object
) -> None:
    """For any non-positive or non-integer interval/cooldown value, Settings
    yields the corresponding default (5 or 10).

    Validates: Requirements 9.4
    """
    cfg = _make_settings(
        check_interval_minutes=bad_interval,
        alert_cooldown_minutes=bad_cooldown,
    )
    assert cfg.check_interval_minutes == DEFAULT_CHECK_INTERVAL_MINUTES
    assert cfg.alert_cooldown_minutes == DEFAULT_ALERT_COOLDOWN_MINUTES


# Feature: uptime-guardian, Property 15: Configuration falls back on invalid values
@settings(max_examples=50)
@given(good_interval=st.integers(min_value=1, max_value=10_000),
       good_cooldown=st.integers(min_value=1, max_value=10_000))
def test_property_15_valid_values_are_preserved(
    good_interval: int, good_cooldown: int
) -> None:
    """Positive integer values are preserved unchanged (complements 9.4).

    Validates: Requirements 9.4
    """
    cfg = _make_settings(
        check_interval_minutes=good_interval,
        alert_cooldown_minutes=good_cooldown,
    )
    assert cfg.check_interval_minutes == good_interval
    assert cfg.alert_cooldown_minutes == good_cooldown


# ---------------------------------------------------------------------------
# Feature: saas-multi-tenant
# ---------------------------------------------------------------------------

from decimal import Decimal

from pydantic import ValidationError

from schemas import PlanCreate

# Strategy for an in-bounds plan attribute set (Requirements 1.1-1.6, 17.1).
_plan_names = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1, max_size=100
).filter(lambda s: len(s) >= 1)
_plan_prices = st.decimals(
    min_value=Decimal("0"), max_value=Decimal("999999.99"), places=2
)
_plan_max_monitors = st.integers(min_value=1, max_value=100_000)
_plan_min_interval = st.integers(min_value=1, max_value=1440)
_plan_duration = st.integers(min_value=0, max_value=3650)


# Feature: saas-multi-tenant, Property 26: Plan bounds validation round-trip
@settings(max_examples=100)
@given(
    name=_plan_names,
    price=_plan_prices,
    max_monitors=_plan_max_monitors,
    ssl_enabled=st.booleans(),
    min_interval=_plan_min_interval,
    duration=_plan_duration,
)
def test_property_26_plan_within_bounds_round_trips(
    name: str,
    price: Decimal,
    max_monitors: int,
    ssl_enabled: bool,
    min_interval: int,
    duration: int,
) -> None:
    """Any in-bounds plan attribute set is accepted and preserved unchanged.

    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 17.1
    """
    plan = PlanCreate(
        name=name,
        price=price,
        max_monitors=max_monitors,
        ssl_check_enabled=ssl_enabled,
        min_interval_minutes=min_interval,
        duration_days=duration,
    )
    assert plan.name == name
    assert plan.price == price
    assert plan.max_monitors == max_monitors
    assert plan.ssl_check_enabled is ssl_enabled
    assert plan.min_interval_minutes == min_interval
    assert plan.duration_days == duration


# An out-of-bounds value generator per field, paired with the field name that
# must appear in the resulting validation error (Requirement 17.2).
_out_of_bounds_field = st.one_of(
    st.tuples(
        st.just("name"),
        st.one_of(st.just(""), st.text(min_size=101, max_size=200)),
    ),
    st.tuples(
        st.just("price"),
        st.one_of(
            st.just(Decimal("-0.01")), st.just(Decimal("1000000.00"))
        ),
    ),
    st.tuples(
        st.just("max_monitors"),
        st.one_of(st.just(0), st.integers(min_value=100_001, max_value=200_000)),
    ),
    st.tuples(
        st.just("min_interval_minutes"),
        st.one_of(st.just(0), st.integers(min_value=1441, max_value=5000)),
    ),
)


# Feature: saas-multi-tenant, Property 26: Plan bounds validation round-trip
@settings(max_examples=100)
@given(violation=_out_of_bounds_field)
def test_property_26_out_of_bounds_plan_is_rejected_naming_field(
    violation: tuple[str, object],
) -> None:
    """Any single out-of-bounds attribute is rejected, naming the bad field.

    Validates: Requirements 1.2, 1.3, 1.4, 1.6, 1.7, 17.2
    """
    field, bad_value = violation
    valid: dict[str, object] = {
        "name": "Pro",
        "price": Decimal("9.99"),
        "max_monitors": 10,
        "ssl_check_enabled": True,
        "min_interval_minutes": 5,
        "duration_days": 30,
    }
    valid[field] = bad_value

    with pytest.raises(ValidationError) as exc_info:
        PlanCreate(**valid)

    offending_fields = {
        str(err["loc"][-1]) for err in exc_info.value.errors()
    }
    assert field in offending_fields


# ---------------------------------------------------------------------------
# Property 20: Plan expiry resolution (Task 2.2)
# ---------------------------------------------------------------------------

import time
from datetime import datetime, timedelta, timezone

from hypothesis import HealthCheck
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import database
import plans
import crud
from database import Base
from models import Monitor, Plan, User

_FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
# Active-plan determination must complete within 200 ms (Requirement 16.5).
_RESOLUTION_BUDGET_SECONDS = 0.2


def _expiry_db() -> tuple[object, Session, int]:
    """Build an in-memory DB seeded with Free + a paid Pro plan.

    Uses a plain SQLite engine without foreign-key enforcement so the
    "plan_id references a non-existent plan" case of Requirement 16.4 can be
    represented directly. Returns (engine, session, pro_plan_id).
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = Session(engine)
    plans.seed_free_plan(db)
    pro = Plan(
        name="Pro",
        price=Decimal("9.99"),
        max_monitors=10,
        ssl_check_enabled=True,
        min_interval_minutes=1,
        duration_days=30,
    )
    db.add(pro)
    db.commit()
    db.refresh(pro)
    return engine, db, pro.id


# Feature: saas-multi-tenant, Property 20: Plan expiry resolution
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    offset_seconds=st.integers(min_value=-1_000_000, max_value=1_000_000),
    has_expiry=st.booleans(),
    plan_resolves=st.booleans(),
)
def test_property_20_plan_expiry_resolution(
    offset_seconds: int, has_expiry: bool, plan_resolves: bool
) -> None:
    """The resolved active plan follows the expiry rules of Requirement 16, and
    each resolution completes within the 200 ms budget.

    Validates: Requirements 16.1, 16.2, 16.3, 16.4, 16.5
    """
    engine, db, pro_id = _expiry_db()
    try:
        free = plans.get_free_plan(db)
        # plan_id either references the real Pro plan or a non-existent id.
        plan_id = pro_id if plan_resolves else 999_999
        expires_at = (
            _FIXED_NOW + timedelta(seconds=offset_seconds)
            if has_expiry
            else None
        )
        user = User(
            username="u",
            password_hash="x",
            plan_id=plan_id,
            plan_expires_at=expires_at,
        )
        db.add(user)
        db.commit()

        start = time.perf_counter()
        resolved = plans.resolve_active_plan(db, user, now=_FIXED_NOW)
        elapsed = time.perf_counter() - start

        # Timing budget (16.5).
        assert elapsed < _RESOLUTION_BUDGET_SECONDS

        if not has_expiry:
            # No expiry recorded -> Free (16.3).
            assert resolved.id == free.id
        elif offset_seconds <= 0:
            # Expired (<= now) -> Free (16.1).
            assert resolved.id == free.id
        elif plan_resolves:
            # Active window and plan resolves -> that plan (16.2).
            assert resolved.id == pro_id
        else:
            # Active window but plan_id unresolved -> Free (16.4).
            assert resolved.id == free.id
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Property 4: Monitor count limit invariant (Task 2.4)
# ---------------------------------------------------------------------------

import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

import database
import crud
from schemas import MonitorCreate


def _attempt_create(factory, user_id: int, interval: int) -> bool:
    """Atomically enforce the limit then create; True if a monitor was created.

    Mirrors the router create path: ``enforce_can_create_monitor`` opens the
    BEGIN IMMEDIATE transaction and counts under the reserved write lock, then
    the insert+commit occurs in the same transaction so concurrent creators
    serialize (Requirement 5.4).
    """
    db = factory()
    try:
        user = db.get(User, user_id)
        plans.enforce_can_create_monitor(db, user, interval)
        crud.create_monitor(
            db,
            MonitorCreate(
                name="m", url="https://e.com", check_interval_minutes=interval
            ),
            user_id,
        )
        return True
    except plans.PlanLimitError:
        db.rollback()
        return False
    finally:
        db.close()


# Feature: saas-multi-tenant, Property 4: Monitor count limit invariant
# Threaded, file-backed SQLite is heavy, so this runs fewer examples than the
# default 100 while still exercising several concurrent-create interleavings.
@settings(max_examples=20, deadline=None, suppress_health_check=list(HealthCheck))
@given(
    max_monitors=st.integers(min_value=1, max_value=4),
    extra_attempts=st.integers(min_value=0, max_value=5),
)
def test_property_4_monitor_count_limit_invariant(
    max_monitors: int, extra_attempts: int
) -> None:
    """Under any interleaving of concurrent creates, the owner's monitor count
    never exceeds the active plan's Max_Monitors, and exactly Max_Monitors
    creates succeed when more are attempted.

    Validates: Requirements 5.1, 5.2, 5.4
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = database._make_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=engine)
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, class_=Session
    )
    try:
        setup = factory()
        try:
            plans.seed_free_plan(setup)
            team = Plan(
                name="Team",
                price=Decimal("19.99"),
                max_monitors=max_monitors,
                ssl_check_enabled=True,
                min_interval_minutes=1,
                duration_days=30,
            )
            setup.add(team)
            setup.commit()
            setup.refresh(team)
            user = User(
                username="owner",
                password_hash="x",
                plan_id=team.id,
                plan_expires_at=datetime.now(timezone.utc) + timedelta(days=10),
            )
            setup.add(user)
            setup.commit()
            user_id = user.id
        finally:
            setup.close()

        attempts = max_monitors + extra_attempts
        with ThreadPoolExecutor(max_workers=attempts) as pool:
            outcomes = list(
                pool.map(
                    lambda _: _attempt_create(factory, user_id, 5),
                    range(attempts),
                )
            )

        verify = factory()
        try:
            final_count = crud.count_monitors_for_user(verify, user_id)
        finally:
            verify.close()

        # The invariant: never exceed the limit (5.4) ...
        assert final_count <= max_monitors
        # ... and exactly max_monitors creates succeed when enough are attempted.
        assert final_count == min(attempts, max_monitors)
        assert sum(outcomes) == final_count
    finally:
        engine.dispose()
        os.remove(path)


# ---------------------------------------------------------------------------
# Tasks 2.5, 2.6, 3.4, 3.5
# ---------------------------------------------------------------------------

import pytest as _pytest  # noqa: F811  (already imported; alias for clarity)


def _fk_db() -> tuple[object, Session]:
    """Build a foreign-key-enforcing in-memory DB and a session (FK cascade on)."""
    engine = database._make_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    return engine, Session(engine)


def _make_user_on_plan(
    db: Session, username: str, plan_id: int, *, days: int = 30
) -> User:
    """Create a user with an active (future) subscription to ``plan_id``."""
    user = User(
        username=username,
        password_hash="x",
        plan_id=plan_id,
        plan_expires_at=datetime.now(timezone.utc) + timedelta(days=days),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# Feature: saas-multi-tenant, Property 5: Interval limit invariant
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    plan_min=st.integers(min_value=1, max_value=1440),
    requested=st.integers(min_value=-10, max_value=2000),
)
def test_property_5_interval_limit_invariant(plan_min: int, requested: int) -> None:
    """A create/update is accepted iff the requested interval is a positive int
    >= the active plan minimum; otherwise it is rejected and nothing changes.

    Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
    """
    engine, db = _fk_db()
    try:
        plan = Plan(
            name="P",
            price=Decimal("1.00"),
            max_monitors=100,
            ssl_check_enabled=False,
            min_interval_minutes=plan_min,
            duration_days=30,
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)
        user = _make_user_on_plan(db, "u", plan.id)

        if requested <= 0:
            # Invalid interval value (Requirement 6.5).
            with _pytest.raises(plans.InvalidIntervalError):
                plans.enforce_can_create_monitor(db, user, requested)
            with _pytest.raises(plans.InvalidIntervalError):
                plans.enforce_interval_for_update(db, user, requested)
        elif requested < plan_min:
            # Below the plan minimum (Requirements 6.2, 6.4).
            with _pytest.raises(plans.IntervalTooLowError):
                plans.enforce_can_create_monitor(db, user, requested)
            with _pytest.raises(plans.IntervalTooLowError):
                plans.enforce_interval_for_update(db, user, requested)
        else:
            # At or above the minimum: accepted (Requirements 6.1, 6.3).
            assert plans.enforce_can_create_monitor(db, user, requested).id == plan.id
            assert plans.enforce_interval_for_update(db, user, requested).id == plan.id
    finally:
        db.close()
        engine.dispose()


# Feature: saas-multi-tenant, Property: Free-plan seeding idempotence
@settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(repeats=st.integers(min_value=1, max_value=6))
def test_free_plan_seeding_is_idempotent(repeats: int) -> None:
    """Seeding the Free Plan any number of times yields exactly one Free Plan
    with the specified defaults.

    Validates: Requirements 1.8
    """
    engine, db = _fk_db()
    try:
        for _ in range(repeats):
            plans.seed_free_plan(db)

        all_plans = db.scalars(select(Plan)).all()
        assert len(all_plans) == 1
        free = all_plans[0]
        assert free.name == "Free"
        assert free.price == Decimal("0")
        assert free.max_monitors == 1
        assert free.ssl_check_enabled is False
        assert free.min_interval_minutes == 5
    finally:
        db.close()
        engine.dispose()


# Feature: saas-multi-tenant, Property 1: Tenant isolation
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    counts_a=st.integers(min_value=0, max_value=8),
    counts_b=st.integers(min_value=0, max_value=8),
)
def test_property_1_tenant_isolation(counts_a: int, counts_b: int) -> None:
    """A user's monitor list contains exactly its own monitors, and a monitor
    owned by another tenant is invisible (returns None, never the row).

    Validates: Requirements 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.7
    """
    engine, db = _fk_db()
    try:
        free = plans.seed_free_plan(db)
        a = _make_user_on_plan(db, "a", free.id)
        b = _make_user_on_plan(db, "b", free.id)
        for i in range(counts_a):
            db.add(Monitor(user_id=a.id, name=f"a{i}", url="https://a.example"))
        for i in range(counts_b):
            db.add(Monitor(user_id=b.id, name=f"b{i}", url="https://b.example"))
        db.commit()

        a_monitors = crud.get_monitors_for_user(db, a.id)
        b_monitors = crud.get_monitors_for_user(db, b.id)
        assert len(a_monitors) == counts_a
        assert len(b_monitors) == counts_b
        assert all(m.user_id == a.id for m in a_monitors)
        assert all(m.user_id == b.id for m in b_monitors)

        # Cross-tenant access returns None (caller raises identical 404).
        for m in b_monitors:
            assert crud.get_owned_monitor(db, a.id, m.id) is None
        for m in a_monitors:
            assert crud.get_owned_monitor(db, b.id, m.id) is None
        # A non-existent id is also None (indistinguishable from cross-tenant).
        assert crud.get_owned_monitor(db, a.id, 10_000_000) is None
    finally:
        db.close()
        engine.dispose()


# Feature: saas-multi-tenant, Property 3: Monitor deletion cascade atomicity
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    a_monitors=st.integers(min_value=0, max_value=6),
    results_each=st.integers(min_value=0, max_value=5),
    b_monitors=st.integers(min_value=0, max_value=4),
)
def test_property_3_monitor_deletion_cascade_atomicity(
    a_monitors: int, results_each: int, b_monitors: int
) -> None:
    """Deleting a user removes all of its monitors and their results (all-or-
    nothing) and leaves another tenant's data untouched.

    Validates: Requirements 3.3
    """
    from models import CheckResult

    engine, db = _fk_db()
    try:
        free = plans.seed_free_plan(db)
        a = _make_user_on_plan(db, "a", free.id)
        b = _make_user_on_plan(db, "b", free.id)
        for i in range(a_monitors):
            m = Monitor(user_id=a.id, name=f"a{i}", url="https://a.example")
            for _ in range(results_each):
                m.results.append(CheckResult(is_up=True, status_code=200))
            db.add(m)
        for i in range(b_monitors):
            db.add(Monitor(user_id=b.id, name=f"b{i}", url="https://b.example"))
        db.commit()

        b_ids = {m.id for m in crud.get_monitors_for_user(db, b.id)}

        db.delete(db.get(User, a.id))
        db.commit()

        # All of A's monitors and their results are gone.
        assert crud.count_monitors_for_user(db, a.id) == 0
        remaining_a_results = db.scalar(
            select(func.count())
            .select_from(CheckResult)
            .join(Monitor, CheckResult.monitor_id == Monitor.id)
            .where(Monitor.user_id == a.id)
        )
        assert int(remaining_a_results or 0) == 0
        # B is untouched.
        assert {m.id for m in crud.get_monitors_for_user(db, b.id)} == b_ids
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Task 5: authentication router properties (P10, P11, P12)
# ---------------------------------------------------------------------------

from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from auth import verify_password
from database import get_db
from turnstile import TurnstileResult

_usernames = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=20
)
_emails = st.from_regex(r"[a-z]{1,10}@[a-z]{1,10}\.[a-z]{2,3}", fullmatch=True)
_reg_passwords = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=122), min_size=1, max_size=40
)


def _auth_client() -> tuple[TestClient, sessionmaker]:
    """Build an isolated auth app (Free Plan seeded) and its session factory."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        plans.seed_free_plan(db)

    from routers.auth import router as auth_router

    app = FastAPI()
    app.include_router(auth_router)

    def _override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app), factory


def _stub_turnstile(outcome: TurnstileResult):
    """Return an async stub for routers.auth.verify_token yielding ``outcome``."""

    async def _stub(token):  # noqa: ANN001
        return outcome

    return _stub


# Feature: saas-multi-tenant, Property 10: Password secrecy
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(username=_usernames, email=_emails, password=_reg_passwords)
def test_property_10_password_secrecy(
    username: str, email: str, password: str
) -> None:
    """A successful registration stores a hash that differs from the plaintext
    and verifies against it (dev Turnstile bypass accepts the non-empty token).

    Validates: Requirements 2.4, 11.5
    """
    client, factory = _auth_client()
    resp = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": email,
            "password": password,
            "turnstile_token": "dev-token",
        },
    )
    assert resp.status_code == 201, resp.text
    with factory() as db:
        user = crud.get_user_by_username(db, username)
        assert user is not None
        assert user.password_hash != password
        assert verify_password(password, user.password_hash) is True


# Feature: saas-multi-tenant, Property 11: Credential/identity uniqueness
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(username=_usernames, email=_emails)
def test_property_11_credential_identity_uniqueness(
    username: str, email: str
) -> None:
    """A duplicate username or email is rejected with 409 and creates no second
    record, leaving exactly one user.

    Validates: Requirements 2.2, 2.3, 2.9, 11.6
    """
    client, factory = _auth_client()

    def _register(u: str, e: str):
        return client.post(
            "/api/auth/register",
            json={
                "username": u,
                "email": e,
                "password": "pw",
                "turnstile_token": "dev-token",
            },
        )

    assert _register(username, email).status_code == 201
    # Duplicate username (different email) -> 409.
    assert _register(username, "other_" + email).status_code == 409
    # Duplicate email (different username) -> 409.
    assert _register(username + "x", email).status_code == 409

    with factory() as db:
        users = list(db.scalars(select(User)).all())
    assert len(users) == 1


# Feature: saas-multi-tenant, Property 12: Turnstile-gated authentication outcomes
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    failed=st.sampled_from([TurnstileResult.FAILED, TurnstileResult.UNAVAILABLE]),
    username=_usernames,
    email=_emails,
)
def test_property_12_turnstile_gated_auth_outcomes(
    failed: TurnstileResult, username: str, email: str
) -> None:
    """When Turnstile does not succeed, register creates no user and login
    issues no token; FAILED maps to 400 and UNAVAILABLE to 503.

    Validates: Requirements 11.1, 11.2, 11.3, 11.4, 12.1, 12.2, 12.3, 12.4, 12.6
    """
    client, factory = _auth_client()
    expected = 400 if failed is TurnstileResult.FAILED else 503

    with mock.patch("routers.auth.verify_token", _stub_turnstile(failed)):
        reg = client.post(
            "/api/auth/register",
            json={
                "username": username,
                "email": email,
                "password": "pw",
                "turnstile_token": "anything",
            },
        )
        assert reg.status_code == expected
        login = client.post(
            "/api/auth/login",
            json={
                "username": username,
                "password": "pw",
                "turnstile_token": "anything",
            },
        )
        assert login.status_code == expected
        assert "access_token" not in login.json()

    # No user was created by the rejected registration.
    with factory() as db:
        assert crud.get_user_by_username(db, username) is None


# ---------------------------------------------------------------------------
# Task 7: SePay payments properties (P13-P19)
# ---------------------------------------------------------------------------

import os

from payments import sepay
from payments.service import (
    WebhookOutcome,
    apply_webhook_confirmation,
    initiate_payment,
)
from models import Transaction
from schemas import SepayWebhookIn

_PRICE = Decimal("100000.00")  # whole VND-style amount


def _payment_db() -> tuple[object, Session, int, int]:
    """Build a DB with Free + a paid Pro plan and a user; return ids."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = Session(engine)
    free = plans.seed_free_plan(db)
    pro = Plan(
        name="Pro",
        price=_PRICE,
        max_monitors=10,
        ssl_check_enabled=True,
        min_interval_minutes=1,
        duration_days=30,
    )
    db.add(pro)
    db.commit()
    db.refresh(pro)
    user = User(username="u", password_hash="x", plan_id=free.id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return engine, db, pro.id, user.id


# Feature: saas-multi-tenant, Property 13: Payment-initiation single-pending invariant
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(repeats=st.integers(min_value=1, max_value=6))
def test_property_13_payment_initiation_single_pending(repeats: int) -> None:
    """Repeated initiation for the same user+plan returns the same pending
    transaction and never creates a second pending row.

    Validates: Requirements 13.1, 13.2, 13.5
    """
    engine, db, pro_id, user_id = _payment_db()
    try:
        user = db.get(User, user_id)
        first = initiate_payment(db, user, pro_id)
        for _ in range(repeats):
            again = initiate_payment(db, user, pro_id)
            assert again.id == first.id
        pending = db.scalars(
            select(Transaction).where(
                Transaction.user_id == user_id,
                Transaction.plan_id == pro_id,
                Transaction.status == "pending",
            )
        ).all()
        assert len(pending) == 1
        # The QR reference encodes the amount and reference code (13.2).
        qr = sepay.build_qr_reference(db.get(Plan, pro_id), first.reference_code)
        assert first.reference_code in qr
    finally:
        db.close()
        engine.dispose()


# Feature: saas-multi-tenant, Property 14: Webhook signature rejection
@settings(max_examples=50, deadline=None)
@given(
    good_key=st.text(alphabet="abcdef0123456789", min_size=8, max_size=32),
    bad_key=st.text(alphabet="abcdef0123456789", min_size=8, max_size=32),
)
def test_property_14_webhook_signature_rejection(
    good_key: str, bad_key: str
) -> None:
    """With an API key configured, only the matching ``Authorization: Apikey``
    header verifies; any other value is rejected.

    Validates: Requirements 14.1, 14.2
    """
    with mock.patch.dict(os.environ, {"SEPAY_API_KEY": good_key, "SEPAY_WEBHOOK_SECRET": ""}):
        assert sepay.verify_webhook(
            {"authorization": f"Apikey {good_key}"}, b"{}"
        ) is True
        # Missing header is rejected.
        assert sepay.verify_webhook({}, b"{}") is False
        # Wrong key is rejected.
        if bad_key != good_key:
            assert sepay.verify_webhook(
                {"authorization": f"Apikey {bad_key}"}, b"{}"
            ) is False


# Feature: saas-multi-tenant, Property 15: Webhook amount-match completion
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(amount_delta=st.integers(min_value=-50000, max_value=50000))
def test_property_15_webhook_amount_match_completion(amount_delta: int) -> None:
    """A pending transaction completes only when the paid amount equals its
    amount; a differing amount leaves the transaction and user plan unchanged.

    Validates: Requirements 14.3, 14.7
    """
    engine, db, pro_id, user_id = _payment_db()
    try:
        user = db.get(User, user_id)
        txn = initiate_payment(db, user, pro_id)
        paid = _PRICE + Decimal(amount_delta)
        payload = SepayWebhookIn(transferAmount=paid, code=txn.reference_code)

        outcome = apply_webhook_confirmation(db, payload)
        db.refresh(txn)
        db.refresh(user)

        if paid == _PRICE:
            assert outcome == WebhookOutcome.COMPLETED
            assert txn.status == "completed"
            assert user.plan_id == pro_id
        else:
            assert outcome == WebhookOutcome.AMOUNT_MISMATCH
            assert txn.status == "pending"
            # Plan unchanged (still on the free plan it started with).
            assert user.plan_id != pro_id
    finally:
        db.close()
        engine.dispose()


# Feature: saas-multi-tenant, Property 16: Webhook idempotence
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(replays=st.integers(min_value=1, max_value=5))
def test_property_16_webhook_idempotence(replays: int) -> None:
    """Re-applying a confirmation to an already-completed transaction leaves the
    transaction status and the user's plan unchanged.

    Validates: Requirements 14.5
    """
    engine, db, pro_id, user_id = _payment_db()
    try:
        user = db.get(User, user_id)
        txn = initiate_payment(db, user, pro_id)
        payload = SepayWebhookIn(transferAmount=_PRICE, code=txn.reference_code)

        assert apply_webhook_confirmation(db, payload) == WebhookOutcome.COMPLETED
        db.refresh(user)
        expires_after_first = user.plan_expires_at

        for _ in range(replays):
            outcome = apply_webhook_confirmation(db, payload)
            assert outcome == WebhookOutcome.ALREADY_COMPLETED
        db.refresh(txn)
        db.refresh(user)
        assert txn.status == "completed"
        assert user.plan_id == pro_id
        assert user.plan_expires_at == expires_after_first
    finally:
        db.close()
        engine.dispose()


# Feature: saas-multi-tenant, Property 17: Plan upgrade consistency
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(_n=st.integers(min_value=0, max_value=3))
def test_property_17_plan_upgrade_consistency(_n: int) -> None:
    """After a completed transaction, the user's plan_id equals the
    transaction's plan_id and plan_expires_at is in the future.

    Validates: Requirements 14.4
    """
    engine, db, pro_id, user_id = _payment_db()
    try:
        user = db.get(User, user_id)
        txn = initiate_payment(db, user, pro_id)
        payload = SepayWebhookIn(transferAmount=_PRICE, code=txn.reference_code)
        assert apply_webhook_confirmation(db, payload) == WebhookOutcome.COMPLETED
        db.refresh(user)
        assert user.plan_id == txn.plan_id
        assert user.plan_expires_at is not None
        expires = user.plan_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        assert expires > datetime.now(timezone.utc)
    finally:
        db.close()
        engine.dispose()


# Feature: saas-multi-tenant, Property 18: Unknown-transaction rejection
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(ref=st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", min_size=8, max_size=20))
def test_property_18_unknown_transaction_rejection(ref: str) -> None:
    """A confirmation that matches no transaction is rejected and modifies no
    user.

    Validates: Requirements 14.6, 15.6
    """
    engine, db, pro_id, user_id = _payment_db()
    try:
        user = db.get(User, user_id)
        before_plan = user.plan_id
        # Use a reference that does not exist (no transactions created at all).
        payload = SepayWebhookIn(transferAmount=_PRICE, code="UNKNOWN_" + ref)
        assert apply_webhook_confirmation(db, payload) == WebhookOutcome.NO_MATCH
        db.refresh(user)
        assert user.plan_id == before_plan
    finally:
        db.close()
        engine.dispose()


# Feature: saas-multi-tenant, Property 19: SePay reference uniqueness
@settings(max_examples=20, deadline=None)
@given(count=st.integers(min_value=2, max_value=200))
def test_property_19_reference_uniqueness(count: int) -> None:
    """Generated payment reference codes are unique across many generations.

    Validates: Requirements 15.5
    """
    refs = {sepay.generate_reference_code(1, 1) for _ in range(count)}
    assert len(refs) == count


# ---------------------------------------------------------------------------
# Task 8: scheduler / alerter properties (P6, P7, P8, P25, P24, live re-eval)
# ---------------------------------------------------------------------------

import asyncio

import scheduler as scheduler_module
from models import CheckResult
from scheduler import MonitorScheduler


def _sched_db_with_plan(*, ssl_enabled: bool, min_interval: int):
    """Build a DB + session factory with one user on a plan, return ids."""
    engine = database._make_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, class_=Session
    )
    db = factory()
    plans.seed_free_plan(db)
    plan = Plan(
        name="Custom",
        price=Decimal("5.00"),
        max_monitors=100,
        ssl_check_enabled=ssl_enabled,
        min_interval_minutes=min_interval,
        duration_days=30,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    user = User(
        username="u",
        password_hash="x",
        telegram_chat_id="987654",
        plan_id=plan.id,
        plan_expires_at=datetime.now(timezone.utc) + timedelta(days=10),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return engine, factory, user.id


def _add_owned_monitor(factory, user_id: int, interval: int) -> int:
    db = factory()
    try:
        m = Monitor(
            user_id=user_id,
            name="m",
            url="https://e.example",
            check_interval_minutes=interval,
        )
        db.add(m)
        db.commit()
        db.refresh(m)
        return m.id
    finally:
        db.close()


# Feature: saas-multi-tenant, Property 6: SSL gating invariant
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    ssl_enabled=st.booleans(),
    days=st.integers(min_value=1, max_value=120),
)
def test_property_6_ssl_gating_invariant(ssl_enabled: bool, days: int) -> None:
    """When the owner's active plan disables SSL checking, persisted SSL fields
    are empty; when enabled, the checker's SSL fields are preserved.

    Validates: Requirements 7.1, 7.3, 7.4, 7.5
    """
    engine, factory, user_id = _sched_db_with_plan(
        ssl_enabled=ssl_enabled, min_interval=1
    )
    try:
        monitor_id = _add_owned_monitor(factory, user_id, interval=5)

        async def fake_check(monitor):  # noqa: ANN001
            return CheckResult(
                monitor_id=monitor.id,
                is_up=True,
                status_code=200,
                response_time_ms=10.0,
                ssl_valid=True,
                ssl_days_remaining=days,
                error_message=None,
            )

        with mock.patch.object(scheduler_module, "check_monitor", fake_check):
            sched = MonitorScheduler(session_factory=factory)
            asyncio.run(sched.run_check(monitor_id))

        db = factory()
        try:
            latest = crud.get_latest_result(db, monitor_id)
        finally:
            db.close()
        if ssl_enabled:
            assert latest.ssl_days_remaining == days
            assert latest.ssl_valid is True
        else:
            assert latest.ssl_days_remaining is None
            assert latest.ssl_valid is None
    finally:
        engine.dispose()


# Feature: saas-multi-tenant, Property 7: Scheduler effective-interval bound
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    configured=st.integers(min_value=1, max_value=1440),
    plan_min=st.integers(min_value=1, max_value=1440),
)
def test_property_7_scheduler_effective_interval_bound(
    configured: int, plan_min: int
) -> None:
    """The effective polling interval is max(configured, plan minimum), hence
    always >= the owner's active-plan Min_Interval_Minutes.

    Validates: Requirements 8.1
    """
    engine, factory, user_id = _sched_db_with_plan(
        ssl_enabled=False, min_interval=plan_min
    )
    try:
        monitor_id = _add_owned_monitor(factory, user_id, interval=configured)
        sched = MonitorScheduler(session_factory=factory)
        db = factory()
        try:
            monitor = crud.get_monitor(db, monitor_id)
            effective = sched._effective_interval(db, monitor)
        finally:
            db.close()
        assert effective == max(configured, plan_min)
        assert effective >= plan_min
    finally:
        engine.dispose()


# Feature: saas-multi-tenant, Property 8: Alert routing
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(chat_id=st.sampled_from(["111222", "-1009999", "", "   "]))
def test_property_8_alert_routing(chat_id: str) -> None:
    """A dispatched down-alert is routed to the owning user's chat id, and is
    skipped (empty chat id) per Requirement 9.2.

    Validates: Requirements 9.1, 9.2
    """
    engine, factory, user_id = _sched_db_with_plan(
        ssl_enabled=False, min_interval=1
    )
    try:
        # Set the owner's chat id to the generated value.
        db = factory()
        try:
            user = db.get(User, user_id)
            user.telegram_chat_id = chat_id
            db.commit()
        finally:
            db.close()
        monitor_id = _add_owned_monitor(factory, user_id, interval=5)
        # Seed a prior "up" result so the next down result is a transition.
        db = factory()
        try:
            crud.create_check_result(db, monitor_id, is_up=True, status_code=200)
        finally:
            db.close()

        routed: list[tuple[str, str]] = []

        async def fake_send(message, cid):  # noqa: ANN001
            routed.append((message, cid))

        async def fake_check(monitor):  # noqa: ANN001
            return CheckResult(
                monitor_id=monitor.id, is_up=False, status_code=500,
                response_time_ms=1.0, error_message="down",
            )

        with mock.patch.object(scheduler_module, "send_telegram_alert", fake_send), \
                mock.patch.object(scheduler_module, "check_monitor", fake_check):
            sched = MonitorScheduler(session_factory=factory)
            asyncio.run(sched.run_check(monitor_id))

        # The scheduler always routes to the owner's chat id (never another's);
        # the alerter itself is responsible for skipping empty ids, so the
        # recorded destination equals the owner's stored chat id.
        assert len(routed) == 1
        assert routed[0][1] == chat_id
    finally:
        engine.dispose()


# Feature: saas-multi-tenant, Property 25: Down-alert cooldown suppression
@settings(max_examples=50, deadline=None)
@given(
    interval=st.integers(min_value=1, max_value=60),
    elapsed=st.integers(min_value=0, max_value=120),
)
def test_property_25_down_alert_cooldown(interval: int, elapsed: int) -> None:
    """With cooldown equal to the monitor interval, a repeat down transition is
    suppressed until the interval has elapsed since the last down alert.

    Validates: Requirements 24.3, 24.4, 24.5
    """
    from alerter import decide_alerts

    class _M:
        notify_on_failure = True

    class _R:
        def __init__(self, is_up):
            self.is_up = is_up
            self.status_code = 500
            self.checked_at = datetime.now(timezone.utc)
            self.error_message = "x"
            self.ssl_days_remaining = None

    now = datetime.now(timezone.utc)
    last = now - timedelta(minutes=elapsed)
    send_down, _ = decide_alerts(
        current_result=_R(False),
        previous_result=_R(True),
        monitor=_M(),
        last_down_alert_at=last,
        last_ssl_alert_at=None,
        now=now,
        cooldown_minutes=interval,
    )
    assert send_down == (elapsed >= interval)


# Feature: saas-multi-tenant, Property 24: Status classification (backward compat)
@settings(max_examples=100)
@given(code=st.integers(min_value=100, max_value=599))
def test_property_24_status_classification(code: int) -> None:
    """A response is classified up iff its status code is in 200..299.

    Validates: Requirements 24.1, 24.2
    """
    import httpx
    from checker import check_monitor

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **k):
            return httpx.Response(code, request=httpx.Request("GET", url))

    monitor = Monitor(id=1, user_id=1, name="m", url="http://e.example",
                      check_interval_minutes=5)
    with mock.patch.object(httpx, "AsyncClient", _Client):
        result = asyncio.run(check_monitor(monitor))
    assert result.is_up == (200 <= code <= 299)


# Live plan-change re-evaluation (Task 8.8)
def test_live_plan_change_reevaluation() -> None:
    """Changing a user's plan and running reconcile updates the effective
    interval without a restart.

    Validates: Requirements 8.5
    """
    engine, factory, user_id = _sched_db_with_plan(
        ssl_enabled=False, min_interval=5
    )
    try:
        monitor_id = _add_owned_monitor(factory, user_id, interval=5)

        async def _drive():
            sched = MonitorScheduler(session_factory=factory)
            sched._register_all_active_monitors()
            jobs = {j.id: j for j in sched.get_jobs()}
            before = jobs[f"monitor-{monitor_id}"].trigger.interval.total_seconds()

            # Raise the plan minimum to 30 minutes.
            db = factory()
            try:
                user = db.get(User, user_id)
                plan = db.get(Plan, user.plan_id)
                plan.min_interval_minutes = 30
                db.commit()
            finally:
                db.close()

            sched.reconcile()
            after_job = {j.id: j for j in sched.get_jobs()}[f"monitor-{monitor_id}"]
            after = after_job.trigger.interval.total_seconds()
            return before, after

        before, after = asyncio.run(_drive())
        assert before == 5 * 60
        assert after == 30 * 60
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Task 9: migration completeness and idempotence (P23)
# ---------------------------------------------------------------------------

import migration as migration_module
from migration import MigrationOutcome


def _legacy_db(num_monitors: int):
    """Create a legacy single-user schema (no new columns) with data."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR, "
            "password_hash VARCHAR, created_at DATETIME)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE monitors (id INTEGER PRIMARY KEY, name VARCHAR, "
            "url VARCHAR, is_active BOOLEAN, check_interval_minutes INTEGER, "
            "created_at DATETIME, notify_on_failure BOOLEAN)"
        )
        conn.exec_driver_sql(
            "INSERT INTO users (username, password_hash) VALUES ('legacy', 'h')"
        )
        for i in range(num_monitors):
            conn.exec_driver_sql(
                "INSERT INTO monitors (name, url, is_active, "
                "check_interval_minutes, notify_on_failure) "
                f"VALUES ('m{i}', 'https://e{i}.example', 1, 7, 1)"
            )
    return engine


# Feature: saas-multi-tenant, Property 23: Migration completeness and idempotence
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    num_monitors=st.integers(min_value=0, max_value=6),
    chat=st.one_of(st.none(), st.just(""), st.just("  "), st.just("123456")),
)
def test_property_23_migration_completeness_and_idempotence(
    num_monitors: int, chat
) -> None:
    """Migrating a legacy DB assigns every monitor to the promoted admin on the
    Free Plan, copies the global chat id only when present/non-empty, and a
    second run makes no further changes.

    Validates: Requirements 23.1, 23.2, 23.3, 23.4, 23.5, 23.6, 23.7
    """
    engine = _legacy_db(num_monitors)
    try:
        db = Session(engine)
        try:
            result = migration_module.migrate(db, global_telegram_chat_id=chat)
            assert result.outcome == MigrationOutcome.MIGRATED
        finally:
            db.close()

        verify = Session(engine)
        try:
            user = verify.scalars(select(User).order_by(User.id)).first()
            assert user is not None
            assert user.is_admin is True  # 23.2
            free = plans.get_free_plan(verify)
            assert user.plan_id == free.id  # 23.5
            assert user.plan_expires_at is None
            # 23.3 / 23.4: copy only a present, non-empty chat id.
            if chat and chat.strip():
                assert user.telegram_chat_id == chat.strip()
            else:
                assert user.telegram_chat_id is None

            monitors = verify.scalars(select(Monitor)).all()
            assert len(monitors) == num_monitors  # 23.1 (incl. zero)
            assert all(m.user_id == user.id for m in monitors)
            # Other monitor fields are unchanged.
            assert all(m.check_interval_minutes == 7 for m in monitors)
        finally:
            verify.close()

        # 23.7: a second migration is a no-op.
        db2 = Session(engine)
        try:
            again = migration_module.migrate(db2, global_telegram_chat_id=chat)
            assert again.outcome == MigrationOutcome.ALREADY_MIGRATED
            # Exactly one Free Plan exists (no duplicate seeding).
            free_count = db2.scalar(
                select(func.count()).select_from(Plan).where(Plan.name == "Free")
            )
            assert int(free_count) == 1
        finally:
            db2.close()
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Task 10: router properties (P2, P9, P21, P22)
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient

from tests import helpers as H

import routers.monitors as monitors_module


async def _fake_check(monitor):  # noqa: ANN001
    return CheckResult(
        monitor_id=getattr(monitor, "id", None),
        is_up=True,
        status_code=200,
        response_time_ms=1.0,
    )


# Feature: saas-multi-tenant, Property 2: Monitor ownership on creation
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(name=st.text(alphabet="abcdefABCDEF ", min_size=1, max_size=20))
def test_property_2_monitor_ownership_on_creation(name: str) -> None:
    """A monitor created via the API is owned by the authenticated user.

    Validates: Requirements 3.1, 3.2
    """
    factory = H.make_factory()
    free_id = H.seed_free_plan(factory)
    user_id = H.add_user(factory, username="alice", plan_id=free_id)
    app = H.build_full_app(factory)

    with mock.patch.object(monitors_module, "check_monitor", _fake_check), \
            mock.patch("scheduler.register_monitor", lambda m: None):
        client = TestClient(app)
        resp = client.post(
            "/api/monitors/",
            json={"name": name, "url": "https://e.example", "check_interval_minutes": 5},
            headers=H.auth_header("alice"),
        )
    assert resp.status_code == 201, resp.text
    monitor_id = resp.json()["id"]
    with factory() as db:
        monitor = db.get(Monitor, monitor_id)
        assert monitor.user_id == user_id


# Feature: saas-multi-tenant, Property 9: Telegram configuration round-trip
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    chat_id=st.one_of(
        st.from_regex(r"-?[0-9]{1,15}", fullmatch=True), st.just("")
    )
)
def test_property_9_telegram_round_trip(chat_id: str) -> None:
    """Setting a valid Telegram id stores it and GET /settings returns it; an
    empty value clears it.

    Validates: Requirements 10.1, 10.2, 10.3, 10.4
    """
    factory = H.make_factory()
    free_id = H.seed_free_plan(factory)
    H.add_user(factory, username="bob", plan_id=free_id)
    client = TestClient(H.build_full_app(factory))

    put = client.put(
        "/api/settings/telegram",
        json={"telegram_chat_id": chat_id},
        headers=H.auth_header("bob"),
    )
    assert put.status_code == 200, put.text

    got = client.get("/api/settings", headers=H.auth_header("bob"))
    assert got.status_code == 200
    expected = chat_id if chat_id else None
    assert got.json()["telegram_chat_id"] == expected


# Feature: saas-multi-tenant, Property 21: Plan deletion subscriber protection
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(subscribers=st.integers(min_value=1, max_value=4))
def test_property_21_plan_deletion_subscriber_protection(subscribers: int) -> None:
    """Deleting a plan that has subscribers is rejected with 409 and the plan is
    retained.

    Validates: Requirements 17.6
    """
    factory = H.make_factory()
    H.seed_free_plan(factory)
    pro_id = H.add_paid_plan(factory)
    H.add_user(factory, username="admin", is_admin=True)
    for i in range(subscribers):
        H.add_user(factory, username=f"sub{i}", plan_id=pro_id)
    client = TestClient(H.build_full_app(factory))

    resp = client.delete(
        f"/api/admin/plans/{pro_id}", headers=H.auth_header("admin")
    )
    assert resp.status_code == 409
    with factory() as db:
        assert db.get(Plan, pro_id) is not None


# Feature: saas-multi-tenant, Property 22: Admin listing credential secrecy
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(extra_users=st.integers(min_value=0, max_value=4))
def test_property_22_admin_listing_credential_secrecy(extra_users: int) -> None:
    """No admin user-listing row exposes a credential field (password hash).

    Validates: Requirements 18.1, 18.2, 18.5
    """
    factory = H.make_factory()
    free_id = H.seed_free_plan(factory)
    H.add_user(factory, username="admin", is_admin=True, plan_id=free_id)
    for i in range(extra_users):
        H.add_user(factory, username=f"u{i}", plan_id=free_id, email=f"u{i}@e.co")
    client = TestClient(H.build_full_app(factory))

    resp = client.get("/api/admin/users", headers=H.auth_header("admin"))
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == extra_users + 1
    for row in rows:
        assert set(row.keys()) == {"username", "email", "plan_name"}
        assert "password_hash" not in row
