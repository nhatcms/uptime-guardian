"""API tests for the monitor and results routers (Task 9.3).

Exercises the ``/api/monitors`` and ``/api/results`` endpoints end-to-end with
FastAPI's ``TestClient`` over an isolated in-memory SQLite database. The
``get_db`` dependency is overridden to use that database, and authentication is
satisfied by issuing a genuine token via :func:`auth.create_access_token` and
sending it in the ``Authorization`` header (the real ``get_current_user``
dependency runs unmodified, so the 401 path is also exercised).

Network access is avoided by monkeypatching ``checker.check_monitor`` on the
monitors router so the check-now endpoint never performs real I/O.

Covered behaviors: POST 201, POST invalid URL -> 422, POST persistence failure
-> 500, list-with-latest, GET 404, PUT update, DELETE 204 then 404, check-now
persists a result, results list, stats, and 401 when no token is supplied.

Requirements traceability: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 4.5, 8.1, 8.2,
12.4.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models  # noqa: F401  (registers ORM models on Base.metadata)
from auth import create_access_token
from database import Base, get_db
from models import CheckResult, Monitor
from routers.monitors import router as monitors_router
from routers.results import router as results_router


def _make_session_factory() -> sessionmaker[Session]:
    """Create an isolated in-memory SQLite session factory with tables built."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def factory() -> sessionmaker[Session]:
    """Yield a fresh in-memory session factory for one test."""
    return _make_session_factory()


@pytest.fixture()
def app(factory: sessionmaker[Session]) -> FastAPI:
    """Build a FastAPI app mounting both routers with ``get_db`` overridden."""
    application = FastAPI()
    application.include_router(monitors_router)
    application.include_router(results_router)

    def _override_get_db() -> Iterator[Session]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    application.dependency_overrides[get_db] = _override_get_db
    return application


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    """Return an Authorization header carrying a genuine bearer token."""
    token = create_access_token("admin")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    """Return a TestClient for the configured app."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_network_initial_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid real network I/O for the immediate check run on monitor creation.

    Creating a monitor now performs an immediate check (so its first status is
    reported right away). Patch ``check_monitor`` on the router module to return
    a deterministic "up" result instead of hitting the network. Individual tests
    may override this patch as needed.
    """
    import routers.monitors as monitors_module

    async def _fake_initial_check(monitor: object) -> CheckResult:
        return CheckResult(
            monitor_id=getattr(monitor, "id", None),
            is_up=True,
            status_code=200,
            response_time_ms=1.0,
            ssl_valid=None,
            ssl_days_remaining=None,
            error_message=None,
        )

    monkeypatch.setattr(monitors_module, "check_monitor", _fake_initial_check)


def _create_monitor(
    client: TestClient, headers: dict[str, str], **overrides: object
) -> dict:
    """Helper: create a monitor via the API and return the response JSON."""
    payload = {
        "name": "Example",
        "url": "https://example.com",
        "check_interval_minutes": 5,
    }
    payload.update(overrides)
    response = client.post("/api/monitors/", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# --- Authentication --------------------------------------------------------


def test_list_without_token_returns_401(client: TestClient) -> None:
    """A protected endpoint without a token responds 401 (Requirement 12.4)."""
    response = client.get("/api/monitors/")
    assert response.status_code == 401


def test_results_without_token_returns_401(client: TestClient) -> None:
    """The results endpoint without a token responds 401 (Requirement 12.4)."""
    response = client.get("/api/results/", params={"monitor_id": 1})
    assert response.status_code == 401


# --- Create (POST) ---------------------------------------------------------


def test_create_monitor_returns_201(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """POST creates a monitor and returns 201 with defaults (Requirement 1.1)."""
    body = _create_monitor(client, auth_headers, name="Google", url="https://www.google.com")
    assert body["name"] == "Google"
    assert body["url"] == "https://www.google.com"
    assert body["is_active"] is True
    assert body["notify_on_failure"] is True
    assert isinstance(body["id"], int)


def test_create_monitor_invalid_url_returns_422(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """POST with a malformed URL is rejected with 422 (Requirement 1.2)."""
    response = client.post(
        "/api/monitors/",
        json={"name": "Bad", "url": "not-a-url", "check_interval_minutes": 5},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_create_monitor_persistence_failure_returns_500(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A persistence error during create surfaces as 500 (Requirement 1.3)."""
    import crud

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("db is down")

    monkeypatch.setattr(crud, "create_monitor", _boom)

    response = client.post(
        "/api/monitors/",
        json={"name": "X", "url": "https://x.example.com"},
        headers=auth_headers,
    )
    assert response.status_code == 500


# --- List and read (GET) ---------------------------------------------------


def test_list_monitors_embeds_latest_result(
    client: TestClient,
    auth_headers: dict[str, str],
    factory: sessionmaker[Session],
) -> None:
    """GET / returns monitors with the latest check result embedded (Req 1.3)."""
    created = _create_monitor(client, auth_headers)
    monitor_id = created["id"]

    # Insert a check result directly so a "latest" exists to embed.
    with factory() as db:
        db.add(
            CheckResult(
                monitor_id=monitor_id,
                is_up=True,
                status_code=200,
                response_time_ms=12.5,
            )
        )
        db.commit()

    response = client.get("/api/monitors/", headers=auth_headers)
    assert response.status_code == 200
    monitors = response.json()
    assert len(monitors) == 1
    assert monitors[0]["latest"] is not None
    assert monitors[0]["latest"]["status_code"] == 200
    assert monitors[0]["latest"]["is_up"] is True


def test_list_monitors_latest_none_when_no_results(
    client: TestClient,
    auth_headers: dict[str, str],
    factory: sessionmaker[Session],
) -> None:
    """A monitor with no checks reports ``latest`` of None (Requirement 1.3)."""
    # Insert a monitor directly so it has no check results (creating via the
    # API would trigger an immediate check and persist a first result).
    with factory() as db:
        db.add(Monitor(name="Example", url="https://example.com"))
        db.commit()
    response = client.get("/api/monitors/", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()[0]["latest"] is None


def test_get_monitor_returns_monitor(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """GET /{id} returns the requested monitor (Requirement 1.4)."""
    created = _create_monitor(client, auth_headers)
    response = client.get(f"/api/monitors/{created['id']}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_missing_monitor_returns_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """GET /{id} for a missing monitor responds 404 (Requirement 1.5)."""
    response = client.get("/api/monitors/9999", headers=auth_headers)
    assert response.status_code == 404


# --- Update (PUT) ----------------------------------------------------------


def test_update_monitor_applies_changes(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """PUT /{id} applies updates and returns the updated monitor (Req 1.6)."""
    created = _create_monitor(client, auth_headers)
    response = client.put(
        f"/api/monitors/{created['id']}",
        json={"name": "Renamed", "is_active": False, "check_interval_minutes": 15},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed"
    assert body["is_active"] is False
    assert body["check_interval_minutes"] == 15


def test_update_missing_monitor_returns_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """PUT /{id} for a missing monitor responds 404 (Requirement 1.6)."""
    response = client.put(
        "/api/monitors/9999", json={"name": "X"}, headers=auth_headers
    )
    assert response.status_code == 404


# --- Delete (DELETE) -------------------------------------------------------


def test_delete_monitor_returns_204_then_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """DELETE /{id} returns 204, and a second delete responds 404 (Req 1.7)."""
    created = _create_monitor(client, auth_headers)
    monitor_id = created["id"]

    first = client.delete(f"/api/monitors/{monitor_id}", headers=auth_headers)
    assert first.status_code == 204

    second = client.delete(f"/api/monitors/{monitor_id}", headers=auth_headers)
    assert second.status_code == 404


# --- Check now (POST /{id}/check-now) --------------------------------------


def test_check_now_persists_result(
    client: TestClient,
    auth_headers: dict[str, str],
    factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """check-now runs a check, persists it, and returns it (Requirement 4.5).

    ``checker.check_monitor`` is patched on the router module to avoid real
    network access; it returns an unsaved result the endpoint must persist.
    """
    created = _create_monitor(client, auth_headers)
    monitor_id = created["id"]

    async def _fake_check(monitor: object) -> CheckResult:
        return CheckResult(
            monitor_id=monitor_id,
            is_up=True,
            status_code=200,
            response_time_ms=42.0,
            ssl_valid=True,
            ssl_days_remaining=90,
            error_message=None,
        )

    import routers.monitors as monitors_module

    monkeypatch.setattr(monitors_module, "check_monitor", _fake_check)

    response = client.post(
        f"/api/monitors/{monitor_id}/check-now", headers=auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status_code"] == 200
    assert body["is_up"] is True
    assert body["response_time_ms"] == 42.0
    assert isinstance(body["id"], int)

    # The check-now result was actually persisted (in addition to the result
    # produced by the immediate check performed at creation time).
    with factory() as db:
        stored = db.query(CheckResult).filter_by(monitor_id=monitor_id).all()
    assert any(r.response_time_ms == 42.0 for r in stored)


def test_check_now_missing_monitor_returns_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """check-now for a missing monitor responds 404 (Requirement 4.5)."""
    response = client.post("/api/monitors/9999/check-now", headers=auth_headers)
    assert response.status_code == 404


# --- Results list and stats ------------------------------------------------


def test_results_list_returns_recent_results(
    client: TestClient,
    auth_headers: dict[str, str],
    factory: sessionmaker[Session],
) -> None:
    """GET /api/results returns the monitor's results (Requirement 8.1)."""
    with factory() as db:
        monitor = Monitor(name="Example", url="https://example.com")
        db.add(monitor)
        db.commit()
        monitor_id = monitor.id

    with factory() as db:
        for code in (200, 500, 200):
            db.add(
                CheckResult(
                    monitor_id=monitor_id,
                    is_up=code == 200,
                    status_code=code,
                    response_time_ms=10.0,
                )
            )
        db.commit()

    response = client.get(
        "/api/results/",
        params={"monitor_id": monitor_id, "limit": 100},
        headers=auth_headers,
    )
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 3
    assert all(r["monitor_id"] == monitor_id for r in results)


def test_stats_endpoint_computes_window_stats(
    client: TestClient,
    auth_headers: dict[str, str],
    factory: sessionmaker[Session],
) -> None:
    """GET /api/results/stats returns aggregate statistics (Req 8.2, 8.3)."""
    with factory() as db:
        monitor = Monitor(name="Example", url="https://example.com")
        db.add(monitor)
        db.commit()
        monitor_id = monitor.id

    with factory() as db:
        # 3 up, 1 down -> 75% uptime.
        for code, rt in ((200, 10.0), (200, 20.0), (200, 30.0), (500, 40.0)):
            db.add(
                CheckResult(
                    monitor_id=monitor_id,
                    is_up=code == 200,
                    status_code=code,
                    response_time_ms=rt,
                )
            )
        db.commit()

    response = client.get(
        "/api/results/stats",
        params={"monitor_id": monitor_id, "hours": 24},
        headers=auth_headers,
    )
    assert response.status_code == 200
    stats = response.json()
    assert stats["total_checks"] == 4
    assert stats["failed_checks"] == 1
    assert stats["uptime_percentage"] == pytest.approx(75.0)
    assert stats["min_response_time_ms"] == 10.0
    assert stats["max_response_time_ms"] == 40.0


def test_stats_empty_window_returns_zeros(
    client: TestClient,
    auth_headers: dict[str, str],
    factory: sessionmaker[Session],
) -> None:
    """An empty window yields all-zero stats without error (Requirement 8.4)."""
    # Insert a monitor directly so it has no check results (creating via the
    # API would trigger an immediate check and persist a first result).
    with factory() as db:
        monitor = Monitor(name="Example", url="https://example.com")
        db.add(monitor)
        db.commit()
        monitor_id = monitor.id
    response = client.get(
        "/api/results/stats",
        params={"monitor_id": monitor_id, "hours": 24},
        headers=auth_headers,
    )
    assert response.status_code == 200
    stats = response.json()
    assert stats["total_checks"] == 0
    assert stats["failed_checks"] == 0
    assert stats["uptime_percentage"] == 0.0
