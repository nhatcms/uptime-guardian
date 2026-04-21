"""Unit tests for Cloudflare Turnstile verification (Task 4.2).

Stubs the HTTP layer to cover the SUCCESS / FAILED / UNAVAILABLE branch mapping
and the dev-mode bypass, without any network access.

Feature: saas-multi-tenant.
Requirements traceability: 11.2, 11.4, 12.3, 12.4.
"""

from __future__ import annotations

from typing import Optional

import httpx
import pytest

import turnstile
from turnstile import TurnstileResult, verify_token


class _FakeResponse:
    """Minimal stand-in for an httpx.Response."""

    def __init__(
        self, status_code: int, payload: Optional[dict] = None, bad_json: bool = False
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self._bad_json = bad_json

    def json(self) -> dict:
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


class _FakeClient:
    """Async-context-manager stand-in for httpx.AsyncClient."""

    def __init__(
        self,
        response: Optional[_FakeResponse] = None,
        exc: Optional[Exception] = None,
    ) -> None:
        self._response = response
        self._exc = exc

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def post(self, url: str, data: Optional[dict] = None) -> _FakeResponse:
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


def _patch_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: Optional[_FakeResponse] = None,
    exc: Optional[Exception] = None,
) -> None:
    """Patch turnstile.httpx.AsyncClient to return a configured fake client."""

    def _factory(*args: object, **kwargs: object) -> _FakeClient:
        return _FakeClient(response=response, exc=exc)

    monkeypatch.setattr(turnstile.httpx, "AsyncClient", _factory)


@pytest.fixture()
def _real_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure a non-empty Turnstile secret so the real verify path runs."""
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "test-secret")


async def test_empty_token_is_failed() -> None:
    """An empty/missing token maps to FAILED (Requirements 11.3, 12.2)."""
    assert await verify_token("") == TurnstileResult.FAILED
    assert await verify_token(None) == TurnstileResult.FAILED
    assert await verify_token("   ") == TurnstileResult.FAILED


async def test_dev_mode_bypass_accepts_nonempty_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no secret configured, any non-empty token is SUCCESS (dev bypass)."""
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "")
    assert await verify_token("anything") == TurnstileResult.SUCCESS


async def test_success_flag_true_is_success(
    monkeypatch: pytest.MonkeyPatch, _real_secret: None
) -> None:
    """A 200 response with success=true maps to SUCCESS (Requirement 11.1)."""
    _patch_client(monkeypatch, response=_FakeResponse(200, {"success": True}))
    assert await verify_token("tok") == TurnstileResult.SUCCESS


async def test_success_flag_false_is_failed(
    monkeypatch: pytest.MonkeyPatch, _real_secret: None
) -> None:
    """A 200 response with success=false maps to FAILED (Req 11.2, 12.3)."""
    _patch_client(monkeypatch, response=_FakeResponse(200, {"success": False}))
    assert await verify_token("tok") == TurnstileResult.FAILED


async def test_non_200_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, _real_secret: None
) -> None:
    """A non-200 response maps to UNAVAILABLE (Requirements 11.4, 12.4)."""
    _patch_client(monkeypatch, response=_FakeResponse(503, {}))
    assert await verify_token("tok") == TurnstileResult.UNAVAILABLE


async def test_network_error_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, _real_secret: None
) -> None:
    """A transport error maps to UNAVAILABLE (Requirements 11.4, 12.4)."""
    _patch_client(monkeypatch, exc=httpx.ConnectError("boom"))
    assert await verify_token("tok") == TurnstileResult.UNAVAILABLE


async def test_timeout_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, _real_secret: None
) -> None:
    """A timeout maps to UNAVAILABLE (Requirements 11.4, 12.4)."""
    _patch_client(monkeypatch, exc=httpx.TimeoutException("slow"))
    assert await verify_token("tok") == TurnstileResult.UNAVAILABLE


async def test_non_json_body_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, _real_secret: None
) -> None:
    """A 200 response with a non-JSON body maps to UNAVAILABLE."""
    _patch_client(monkeypatch, response=_FakeResponse(200, bad_json=True))
    assert await verify_token("tok") == TurnstileResult.UNAVAILABLE
