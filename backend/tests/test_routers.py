"""Endpoint status-code mapping tests (Task 10.11).

Concrete assertions for the 201/400/401/403/404/409/503 branches across the
auth, monitors, settings, payments, and admin routers, using the full app built
in ``tests.helpers`` over an isolated in-memory database. External services
(Turnstile, the immediate check, scheduler) are stubbed so no network I/O runs.

Feature: saas-multi-tenant.
Requirements traceability: 4.4, 5.2, 11.2, 14.2, 17.7, 18.6, 18.7.
"""

from __future__ import annotations

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


# --- Auth -------------------------------------------------------------------

def test_register_empty_turnstile_token_is_400(factory, client) -> None:
    H.seed_free_plan(factory)
    resp = client.post(
        "/api/auth/register",
        json={"username": "a", "email": "a@b.co", "password": "pw", "turnstile_token": ""},
    )
    assert resp.status_code == 400


def test_register_duplicate_is_409(factory, client) -> None:
    H.seed_free_plan(factory)
    body = {"username": "a", "email": "a@b.co", "password": "pw", "turnstile_token": "x"}
    assert client.post("/api/auth/register", json=body).status_code == 201
    assert client.post("/api/auth/register", json=body).status_code == 409


def test_login_bad_credentials_is_401(factory, client) -> None:
    H.seed_free_plan(factory)
    H.add_user(factory, username="a", password="right")
    resp = client.post(
        "/api/auth/login",
        json={"username": "a", "password": "wrong", "turnstile_token": "x"},
    )
    assert resp.status_code == 401


def test_register_turnstile_unavailable_is_503(factory, client) -> None:
    H.seed_free_plan(factory)
    from turnstile import TurnstileResult

    async def _unavailable(token):  # noqa: ANN001
        return TurnstileResult.UNAVAILABLE

    with mock.patch("routers.auth.verify_token", _unavailable):
        resp = client.post(
            "/api/auth/register",
            json={"username": "z", "email": "z@b.co", "password": "pw", "turnstile_token": "x"},
        )
    assert resp.status_code == 503


# --- Monitors ---------------------------------------------------------------

def test_monitors_unauthenticated_is_401(client) -> None:
    assert client.get("/api/monitors/").status_code == 401


def test_create_monitor_over_limit_is_403(factory, client) -> None:
    free_id = H.seed_free_plan(factory)  # max_monitors=1
    H.add_user(factory, username="a", plan_id=free_id)
    body = {"name": "m", "url": "https://e.example", "check_interval_minutes": 5}
    first = client.post("/api/monitors/", json=body, headers=H.auth_header("a"))
    assert first.status_code == 201
    second = client.post("/api/monitors/", json=body, headers=H.auth_header("a"))
    assert second.status_code == 403


def test_create_monitor_interval_too_low_is_403(factory, client) -> None:
    free_id = H.seed_free_plan(factory)  # min_interval=5
    H.add_user(factory, username="a", plan_id=free_id)
    body = {"name": "m", "url": "https://e.example", "check_interval_minutes": 1}
    resp = client.post("/api/monitors/", json=body, headers=H.auth_header("a"))
    assert resp.status_code == 403


def test_cross_tenant_monitor_is_404(factory, client) -> None:
    free_id = H.seed_free_plan(factory)
    a = H.add_user(factory, username="a", plan_id=free_id)
    H.add_user(factory, username="b", plan_id=free_id)
    created = client.post(
        "/api/monitors/",
        json={"name": "m", "url": "https://e.example", "check_interval_minutes": 5},
        headers=H.auth_header("a"),
    ).json()
    # b cannot see a's monitor -> 404 (indistinguishable from missing).
    resp = client.get(f"/api/monitors/{created['id']}", headers=H.auth_header("b"))
    assert resp.status_code == 404
    assert client.get("/api/monitors/999999", headers=H.auth_header("b")).status_code == 404


# --- Settings ---------------------------------------------------------------

def test_settings_unauthenticated_is_401(client) -> None:
    assert client.get("/api/settings").status_code == 401


def test_settings_bad_telegram_is_422(factory, client) -> None:
    free_id = H.seed_free_plan(factory)
    H.add_user(factory, username="a", plan_id=free_id)
    resp = client.put(
        "/api/settings/telegram",
        json={"telegram_chat_id": "not-a-number"},
        headers=H.auth_header("a"),
    )
    assert resp.status_code == 422


# --- Payments ---------------------------------------------------------------

def test_initiate_missing_plan_is_404(factory, client) -> None:
    H.seed_free_plan(factory)
    H.add_user(factory, username="a")
    resp = client.post(
        "/api/payments/initiate", json={"plan_id": 99999}, headers=H.auth_header("a")
    )
    assert resp.status_code == 404


def test_initiate_free_plan_is_400(factory, client) -> None:
    free_id = H.seed_free_plan(factory)
    H.add_user(factory, username="a")
    resp = client.post(
        "/api/payments/initiate", json={"plan_id": free_id}, headers=H.auth_header("a")
    )
    assert resp.status_code == 400


def test_webhook_bad_signature_is_401(factory, client) -> None:
    H.seed_free_plan(factory)
    with mock.patch.dict(os.environ, {"SEPAY_API_KEY": "secret", "SEPAY_WEBHOOK_SECRET": ""}):
        resp = client.post(
            "/api/payments/sepay-webhook",
            content=b'{"transferAmount": 1, "code": "X"}',
            headers={"authorization": "Apikey wrong"},
        )
    assert resp.status_code == 401


def test_webhook_no_match_is_404(factory, client) -> None:
    H.seed_free_plan(factory)
    # No API key/secret configured -> dev bypass accepts the request.
    with mock.patch.dict(os.environ, {"SEPAY_API_KEY": "", "SEPAY_WEBHOOK_SECRET": ""}):
        resp = client.post(
            "/api/payments/sepay-webhook",
            content=b'{"transferAmount": 100, "code": "NOPE"}',
        )
    assert resp.status_code == 404


def test_webhook_amount_mismatch_is_400(factory, client) -> None:
    pro_id = H.add_paid_plan(factory, price=Decimal("100000.00"))
    H.seed_free_plan(factory)
    uid = H.add_user(factory, username="a")
    # Create a pending transaction via the service.
    import crud
    from payments.service import initiate_payment

    with factory() as db:
        from models import User

        txn = initiate_payment(db, db.get(User, uid), pro_id)
        ref = txn.reference_code
    with mock.patch.dict(os.environ, {"SEPAY_API_KEY": "", "SEPAY_WEBHOOK_SECRET": ""}):
        resp = client.post(
            "/api/payments/sepay-webhook",
            content=f'{{"transferAmount": 5, "code": "{ref}"}}'.encode(),
        )
    assert resp.status_code == 400


# --- Admin ------------------------------------------------------------------

def test_admin_endpoints_non_admin_is_403(factory, client) -> None:
    free_id = H.seed_free_plan(factory)
    H.add_user(factory, username="a", is_admin=False, plan_id=free_id)
    assert client.get("/api/admin/plans", headers=H.auth_header("a")).status_code == 403
    assert client.get("/api/admin/users", headers=H.auth_header("a")).status_code == 403
    assert client.get("/api/admin/transactions", headers=H.auth_header("a")).status_code == 403


def test_admin_endpoints_unauthenticated_is_401(client) -> None:
    assert client.get("/api/admin/users").status_code == 401


def test_admin_create_plan_201_and_duplicate_400(factory, client) -> None:
    H.add_user(factory, username="admin", is_admin=True)
    body = {
        "name": "Gold",
        "price": "50000.00",
        "max_monitors": 20,
        "ssl_check_enabled": True,
        "min_interval_minutes": 2,
        "duration_days": 30,
    }
    assert client.post("/api/admin/plans", json=body, headers=H.auth_header("admin")).status_code == 201
    # Case-insensitive duplicate name -> 400.
    dup = {**body, "name": "gold"}
    assert client.post("/api/admin/plans", json=dup, headers=H.auth_header("admin")).status_code == 400


def test_admin_create_plan_out_of_bounds_400(factory, client) -> None:
    H.add_user(factory, username="admin", is_admin=True)
    body = {
        "name": "Bad",
        "price": "50000.00",
        "max_monitors": 0,  # below the 1..100000 bound
        "ssl_check_enabled": True,
        "min_interval_minutes": 2,
        "duration_days": 30,
    }
    resp = client.post("/api/admin/plans", json=body, headers=H.auth_header("admin"))
    assert resp.status_code == 400


def test_admin_listings_empty_is_200(factory, client) -> None:
    H.add_user(factory, username="admin", is_admin=True)
    assert client.get("/api/admin/transactions", headers=H.auth_header("admin")).json() == []
