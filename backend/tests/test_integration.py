"""End-to-end and backward-compatibility integration tests (Task 14).

- 14.1: the full tenant flow (register -> login -> create -> pay -> webhook
  upgrade -> entitlement change) through the FastAPI app.
- 14.2: migrated monitors keep the original check/persist/alert behavior.
- 14.3: real API-key and HMAC-SHA256 webhook signature verification.

External services (the immediate check, scheduler registration, Telegram) are
stubbed so no network I/O runs.

Feature: saas-multi-tenant.
Requirements traceability: 5.1, 6.1, 7.3, 11.5, 13.1, 14.1-14.4, 24.1-24.6.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from decimal import Decimal
from unittest import mock

import pytest
from fastapi.testclient import TestClient

import routers.monitors as monitors_module
from tests import helpers as H


async def _fake_check(monitor):  # noqa: ANN001
    from models import CheckResult

    return CheckResult(
        monitor_id=getattr(monitor, "id", None),
        is_up=True,
        status_code=200,
        response_time_ms=1.0,
    )


@pytest.fixture()
def factory():
    return H.make_factory()


@pytest.fixture()
def client(factory):
    app = H.build_full_app(factory)
    with mock.patch.object(monitors_module, "check_monitor", _fake_check), \
            mock.patch("scheduler.register_monitor", lambda m: None):
        yield TestClient(app)


# --- 14.1: full tenant flow -------------------------------------------------

def test_full_tenant_flow(factory, client) -> None:
    """register -> login -> create -> initiate -> webhook upgrade -> entitlement.

    Validates: Requirements 5.1, 6.1, 7.3, 11.5, 13.1, 14.3, 14.4
    """
    H.seed_free_plan(factory)  # max_monitors=1, min_interval=5, ssl off
    pro_id = H.add_paid_plan(
        factory,
        name="Pro",
        price=Decimal("100000.00"),
        max_monitors=10,
        ssl=True,
        min_interval=1,
        duration_days=30,
    )

    # Register (Turnstile dev bypass accepts a non-empty token).
    reg = client.post(
        "/api/auth/register",
        json={"username": "carol", "email": "carol@e.co", "password": "pw", "turnstile_token": "x"},
    )
    assert reg.status_code == 201

    # Login -> token.
    login = client.post(
        "/api/auth/login",
        json={"username": "carol", "password": "pw", "turnstile_token": "x"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # On the Free plan: a 1-minute interval is below the 5-minute floor -> 403.
    too_fast = client.post(
        "/api/monitors/",
        json={"name": "m", "url": "https://e.example", "check_interval_minutes": 1},
        headers=headers,
    )
    assert too_fast.status_code == 403

    # A valid create on the Free plan (interval >= 5) -> 201.
    created = client.post(
        "/api/monitors/",
        json={"name": "m", "url": "https://e.example", "check_interval_minutes": 5},
        headers=headers,
    )
    assert created.status_code == 201

    # Free plan allows only 1 monitor -> a second create is 403.
    second = client.post(
        "/api/monitors/",
        json={"name": "m2", "url": "https://e2.example", "check_interval_minutes": 5},
        headers=headers,
    )
    assert second.status_code == 403

    # Settings reflect the Free plan (SSL off).
    settings = client.get("/api/settings", headers=headers).json()
    assert settings["plan"]["name"] == "Free"
    assert settings["plan"]["ssl_check_enabled"] is False

    # Initiate payment for Pro -> pending tx + reference code.
    init = client.post("/api/payments/initiate", json={"plan_id": pro_id}, headers=headers)
    assert init.status_code == 200
    reference = init.json()["reference_code"]
    amount = init.json()["amount"]

    # Simulate the SePay webhook (dev bypass: no signature configured) with the
    # matching amount -> completion + plan upgrade (14.3, 14.4).
    with mock.patch.dict(os.environ, {"SEPAY_API_KEY": "", "SEPAY_WEBHOOK_SECRET": ""}):
        hook = client.post(
            "/api/payments/sepay-webhook",
            content=f'{{"transferAmount": {amount}, "code": "{reference}"}}'.encode(),
        )
    assert hook.status_code == 200

    # Entitlements changed: now on Pro (SSL on), and a 1-minute interval is
    # accepted, and more than one monitor is allowed.
    settings2 = client.get("/api/settings", headers=headers).json()
    assert settings2["plan"]["name"] == "Pro"
    assert settings2["plan"]["ssl_check_enabled"] is True

    fast_now = client.post(
        "/api/monitors/",
        json={"name": "fast", "url": "https://e3.example", "check_interval_minutes": 1},
        headers=headers,
    )
    assert fast_now.status_code == 201


# --- 14.2: backward-compatible monitoring after migration -------------------

def test_backward_compatible_monitoring_after_migration() -> None:
    """After migrating a legacy DB, the check/persist/alert path is unchanged.

    Validates: Requirements 24.1, 24.2, 24.3, 24.4, 24.5, 24.6
    """
    import asyncio

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.pool import StaticPool

    import crud
    import migration as migration_module
    import scheduler as scheduler_module
    from database import Base
    from models import Monitor, User
    from scheduler import MonitorScheduler

    # Build a legacy single-user DB with one monitor and a global chat id.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR, "
            "password_hash VARCHAR, created_at DATETIME)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE monitors (id INTEGER PRIMARY KEY, name VARCHAR, url VARCHAR, "
            "is_active BOOLEAN, check_interval_minutes INTEGER, created_at DATETIME, "
            "notify_on_failure BOOLEAN)"
        )
        conn.exec_driver_sql(
            "INSERT INTO users (username, password_hash) VALUES ('legacy', 'h')"
        )
        conn.exec_driver_sql(
            "INSERT INTO monitors (name, url, is_active, check_interval_minutes, "
            "notify_on_failure) VALUES ('site', 'https://e.example', 1, 5, 1)"
        )

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    db = factory()
    try:
        result = migration_module.migrate(db, global_telegram_chat_id="555000")
        assert result.outcome == migration_module.MigrationOutcome.MIGRATED
        owner = db.query(User).first()
        monitor = db.query(Monitor).first()
        assert monitor.user_id == owner.id  # 24 (migrated ownership)
        assert owner.telegram_chat_id == "555000"  # 23.3
        monitor_id = monitor.id
        # Seed a prior "up" result so the next down result is a transition.
        crud.create_check_result(db, monitor_id, is_up=True, status_code=200)
    finally:
        db.close()

    sent: list[tuple[str, str]] = []

    async def fake_send(message, chat_id):  # noqa: ANN001
        sent.append((message, chat_id))

    async def fake_down_check(monitor):  # noqa: ANN001
        from models import CheckResult

        return CheckResult(
            monitor_id=monitor.id, is_up=False, status_code=None,
            response_time_ms=None, error_message="timeout",
        )

    with mock.patch.object(scheduler_module, "send_telegram_alert", fake_send), \
            mock.patch.object(scheduler_module, "check_monitor", fake_down_check):
        sched = MonitorScheduler(session_factory=factory)
        asyncio.run(sched.run_check(monitor_id))

    # Down transition dispatched exactly one alert routed to the migrated chat
    # id (24.3), and the Check_Result was persisted with the full field set
    # including the error and a null status code (24.2, 24.6).
    assert len(sent) == 1
    assert sent[0][1] == "555000"
    verify = factory()
    try:
        latest = crud.get_latest_result(verify, monitor_id)
        assert latest.is_up is False
        assert latest.status_code is None
        assert latest.error_message == "timeout"
    finally:
        verify.close()
    engine.dispose()


# --- 14.3: webhook signature verification modes -----------------------------

def test_webhook_api_key_verification() -> None:
    """Real API-key verification accepts only the matching key (Req 14.1, 14.2)."""
    from payments import sepay

    with mock.patch.dict(os.environ, {"SEPAY_API_KEY": "topsecret", "SEPAY_WEBHOOK_SECRET": ""}):
        assert sepay.verify_webhook({"authorization": "Apikey topsecret"}, b"{}") is True
        assert sepay.verify_webhook({"authorization": "Apikey nope"}, b"{}") is False
        assert sepay.verify_webhook({}, b"{}") is False


def test_webhook_hmac_verification() -> None:
    """Real HMAC-SHA256 verification accepts only a valid signature (Req 14.1, 14.2)."""
    from payments import sepay

    secret = "hmac-secret"
    raw = b'{"transferAmount": 100, "code": "NCMSX"}'
    good = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    bad = "0" * len(good)

    with mock.patch.dict(os.environ, {"SEPAY_API_KEY": "", "SEPAY_WEBHOOK_SECRET": secret}):
        assert sepay.verify_webhook({"x-signature": good}, raw) is True
        assert sepay.verify_webhook({"x-sepay-signature": good}, raw) is True
        assert sepay.verify_webhook({"x-signature": bad}, raw) is False
        assert sepay.verify_webhook({}, raw) is False
