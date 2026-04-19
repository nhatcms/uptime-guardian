"""Tests for the checker module (HTTP + SSL health checking).

Contains the property-based tests for Properties 1-5 (status classification,
SSL day computation, SSL failure containment, request-failure results, and
non-HTTPS null SSL fields) plus unit/smoke tests for the HTTP client timeout,
response-time recording, and the unsaved-result invariant.

Network and transport I/O are replaced with in-memory fakes (httpx
``MockTransport``) and patched socket calls so the tests exercise pure logic
without real network access.
"""

from __future__ import annotations

import asyncio
import socket
import ssl
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest import mock

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import checker
from checker import (
    HTTP_TIMEOUT_SECONDS,
    check_monitor,
    classify_status,
    compute_ssl_days_remaining,
    perform_ssl_check,
)
from models import CheckResult, Monitor


# --- Test helpers ----------------------------------------------------------


def _make_monitor(url: str, monitor_id: Optional[int] = 1) -> Monitor:
    """Build an in-memory Monitor (not attached to any session)."""
    return Monitor(
        id=monitor_id,
        name="test",
        url=url,
        is_active=True,
        check_interval_minutes=5,
        notify_on_failure=True,
    )


def _run_check_with_handler(
    monitor: Monitor, handler: Any, captured: Optional[dict[str, Any]] = None
) -> CheckResult:
    """Run ``check_monitor`` with httpx routed through a MockTransport.

    ``handler(request)`` returns an ``httpx.Response`` or raises to simulate a
    transport failure. ``captured`` (if provided) receives the kwargs passed to
    ``httpx.AsyncClient`` so callers can assert on the configured timeout.
    """
    real_client_cls = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        if captured is not None:
            captured.update(kwargs)
        return real_client_cls(*args, transport=transport, **kwargs)

    with mock.patch.object(httpx, "AsyncClient", new=factory):
        return asyncio.run(check_monitor(monitor))


# --- Property 1: Status code classification --------------------------------


# Feature: uptime-guardian, Property 1: Status code classification
@settings(max_examples=50)
@given(status_code=st.integers(min_value=-1000, max_value=1000))
def test_property_1_status_code_classification(status_code: int) -> None:
    """classify_status is true iff the code is in 200-299 inclusive.

    Validates: Requirements 2.3, 2.4
    """
    assert classify_status(status_code) == (200 <= status_code < 300)


def test_classify_status_none_is_down() -> None:
    """A None status code (connection failure) classifies as down."""
    assert classify_status(None) is False


# --- Property 3: SSL days remaining computation ----------------------------


# Feature: uptime-guardian, Property 3: SSL days remaining computation
@settings(max_examples=50)
@given(
    now=st.datetimes(
        min_value=datetime(2000, 1, 1), max_value=datetime(2100, 1, 1)
    ),
    days=st.integers(min_value=0, max_value=3650),
)
def test_property_3_ssl_days_remaining_computation(
    now: datetime, days: int
) -> None:
    """compute_ssl_days_remaining(now + d days, now) == d, and the validity
    rule marks the certificate valid exactly when d is positive.

    Validates: Requirements 3.1, 3.2
    """
    not_after = now + timedelta(days=days)
    result = compute_ssl_days_remaining(not_after, now)
    assert result == days
    # ssl_valid in perform_ssl_check is (days_remaining > 0).
    assert (result > 0) == (days > 0)


# --- Property 4: SSL failure is contained ----------------------------------


# Feature: uptime-guardian, Property 4: SSL failure is contained
@settings(max_examples=50, deadline=None)
@given(
    failure=st.sampled_from(
        [
            socket.timeout("timed out"),
            socket.gaierror("name resolution failed"),
            ConnectionRefusedError("refused"),
            OSError("network unreachable"),
            ssl.SSLError("handshake failure"),
            ssl.SSLCertVerificationError("certificate verify failed"),
            ValueError("bad value"),
            RuntimeError("boom"),
            Exception(""),
        ]
    ),
)
def test_property_4_ssl_failure_is_contained(failure: BaseException) -> None:
    """Any SSL/connection failure yields (False, 0) without raising.

    Validates: Requirements 3.3
    """
    with mock.patch.object(
        socket, "create_connection", side_effect=failure
    ):
        ssl_valid, days_remaining = perform_ssl_check("example.com", 443)
    assert ssl_valid is False
    assert days_remaining == 0


def test_perform_ssl_check_invalid_cert_contained() -> None:
    """An empty/missing certificate is treated as a contained failure."""

    class _FakeSSock:
        def __enter__(self) -> "_FakeSSock":
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def getpeercert(self) -> dict[str, Any]:
            return {}

    class _FakeSock:
        def __enter__(self) -> "_FakeSock":
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

    class _FakeContext:
        def wrap_socket(self, sock: Any, server_hostname: str) -> _FakeSock:
            return _FakeSSock()

    with mock.patch.object(
        socket, "create_connection", return_value=_FakeSock()
    ), mock.patch.object(
        ssl, "create_default_context", return_value=_FakeContext()
    ):
        ssl_valid, days_remaining = perform_ssl_check("example.com", 443)
    assert ssl_valid is False
    assert days_remaining == 0


# --- Property 2: Request failures produce a failed result ------------------


# Feature: uptime-guardian, Property 2: Request failures produce a failed result
@settings(max_examples=50, deadline=None)
@given(
    exc=st.sampled_from(
        [
            httpx.ConnectError("connection failed"),
            httpx.ConnectTimeout("connect timed out"),
            httpx.ReadTimeout("read timed out"),
            httpx.PoolTimeout("pool timed out"),
            httpx.ReadError("read error"),
            RuntimeError("unexpected failure"),
            ValueError("bad"),
        ]
    ),
)
def test_property_2_request_failures_produce_failed_result(
    exc: Exception,
) -> None:
    """Any transport exception yields status_code None, is_up False, and a
    non-empty error_message.

    Validates: Requirements 2.5
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    monitor = _make_monitor("https://example.com")
    result = _run_check_with_handler(monitor, handler)

    assert result.status_code is None
    assert result.is_up is False
    assert result.error_message is not None
    assert len(result.error_message) > 0


# --- Property 5: Non-HTTPS monitors have null SSL fields -------------------


# Feature: uptime-guardian, Property 5: Non-HTTPS monitors have null SSL fields
@settings(max_examples=50, deadline=None)
@given(
    host=st.from_regex(r"[a-z][a-z0-9]{0,20}\.(com|net|org)", fullmatch=True),
    status_code=st.integers(min_value=200, max_value=599),
)
def test_property_5_non_https_has_null_ssl_fields(
    host: str, status_code: int
) -> None:
    """A non-HTTPS monitor URL leaves ssl_valid and ssl_days_remaining null.

    Validates: Requirements 3.4
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code)

    monitor = _make_monitor(f"http://{host}")
    result = _run_check_with_handler(monitor, handler)

    assert result.ssl_valid is None
    assert result.ssl_days_remaining is None


# --- Task 3.7: unit / smoke tests ------------------------------------------


def test_client_timeout_is_ten_seconds() -> None:
    """The httpx client is configured with a 10.0s timeout (Requirement 2.1)."""
    assert HTTP_TIMEOUT_SECONDS == 10.0

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    captured: dict[str, Any] = {}
    monitor = _make_monitor("http://example.com")
    _run_check_with_handler(monitor, handler, captured=captured)

    assert captured.get("timeout") == 10.0


def test_response_time_recorded_and_non_negative() -> None:
    """response_time_ms is recorded and non-negative on a successful check.

    Validates: Requirements 2.2
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    monitor = _make_monitor("http://example.com")
    result = _run_check_with_handler(monitor, handler)

    assert result.response_time_ms is not None
    assert result.response_time_ms >= 0.0
    assert result.is_up is True
    assert result.status_code == 200


def test_check_result_is_unsaved() -> None:
    """check_monitor returns an unsaved CheckResult (no id assigned).

    Validates: Requirements 2.6
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    monitor = _make_monitor("http://example.com")
    result = _run_check_with_handler(monitor, handler)

    assert isinstance(result, CheckResult)
    # An unsaved ORM object has no primary key assigned (not flushed/committed).
    assert result.id is None
    # And it is not associated with any session.
    from sqlalchemy import inspect as sa_inspect

    assert sa_inspect(result).session is None
