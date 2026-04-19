"""Tests for the alerter: decision logic, message builders, and dispatch.

Covers the optional property and unit test sub-tasks of Task 4:

* Property 6  - down-alert decision      (Req 5.1, 5.3, 5.4)
* Property 8  - SSL-warning decision     (Req 6.1, 6.3)
* Property 7  - down-alert message body  (Req 5.2)
* Property 9  - SSL-warning message body (Req 6.2)
* Property 10 - dispatch never raises    (Req 5.5, 7.3)
* Unit        - Telegram request shape   (Req 7.1, 7.2)

Network I/O is replaced with in-memory fakes/mocks so the logic is exercised
cheaply and deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import alerter
from alerter import (
    SSL_ALERT_SUPPRESSION,
    SSL_WARNING_THRESHOLD_DAYS,
    build_down_message,
    build_ssl_message,
    decide_alerts,
    send_telegram_alert,
)


@dataclass
class FakeMonitor:
    """Minimal stand-in for a Monitor ORM row used by the alerter."""

    name: str = "Example"
    url: str = "https://example.com"
    notify_on_failure: bool = True


@dataclass
class FakeResult:
    """Minimal stand-in for a CheckResult ORM row used by the alerter."""

    is_up: bool = True
    status_code: Optional[int] = 200
    checked_at: datetime = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    error_message: Optional[str] = None
    ssl_days_remaining: Optional[int] = None


_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

# A datetime strategy producing timezone-aware UTC timestamps near _NOW.
_offsets = st.integers(min_value=0, max_value=60 * 24 * 30)  # up to ~30 days
_past_datetimes = _offsets.map(lambda mins: _NOW - timedelta(minutes=mins))


# ---------------------------------------------------------------------------
# Property 6: Down-alert decision
# ---------------------------------------------------------------------------
# Feature: uptime-guardian, Property 6: Down-alert decision
@settings(max_examples=50)
@given(
    prev_up=st.booleans(),
    prev_exists=st.booleans(),
    curr_up=st.booleans(),
    notify=st.booleans(),
    cooldown_minutes=st.integers(min_value=1, max_value=240),
    last_down_alert_at=st.one_of(st.none(), _past_datetimes),
)
def test_property_6_down_alert_decision(
    prev_up: bool,
    prev_exists: bool,
    curr_up: bool,
    notify: bool,
    cooldown_minutes: int,
    last_down_alert_at: Optional[datetime],
) -> None:
    """send_down is true iff: previous existed and was up, the new result is
    down, notify_on_failure is true, and the last down alert is outside the
    cooldown window.

    Validates: Requirements 5.1, 5.3, 5.4
    """
    monitor = FakeMonitor(notify_on_failure=notify)
    current = FakeResult(is_up=curr_up, status_code=200 if curr_up else 500)
    previous = FakeResult(is_up=prev_up) if prev_exists else None

    send_down, _ = decide_alerts(
        current_result=current,
        previous_result=previous,
        monitor=monitor,
        last_down_alert_at=last_down_alert_at,
        last_ssl_alert_at=None,
        now=_NOW,
        cooldown_minutes=cooldown_minutes,
    )

    cooldown_elapsed = (
        last_down_alert_at is None
        or (_NOW - last_down_alert_at) >= timedelta(minutes=cooldown_minutes)
    )
    expected = (
        (not curr_up)
        and prev_exists
        and prev_up
        and notify
        and cooldown_elapsed
    )
    assert send_down is expected


# ---------------------------------------------------------------------------
# Property 8: SSL-warning decision
# ---------------------------------------------------------------------------
# Feature: uptime-guardian, Property 8: SSL-warning decision
@settings(max_examples=50)
@given(
    days=st.one_of(st.none(), st.integers(min_value=-5, max_value=120)),
    last_ssl_alert_at=st.one_of(st.none(), _past_datetimes),
)
def test_property_8_ssl_warning_decision(
    days: Optional[int],
    last_ssl_alert_at: Optional[datetime],
) -> None:
    """send_ssl is true iff ssl_days_remaining is below 14 and the last SSL
    alert is more than 24 hours before now.

    Validates: Requirements 6.1, 6.3
    """
    monitor = FakeMonitor()
    current = FakeResult(ssl_days_remaining=days)

    _, send_ssl = decide_alerts(
        current_result=current,
        previous_result=None,
        monitor=monitor,
        last_down_alert_at=None,
        last_ssl_alert_at=last_ssl_alert_at,
        now=_NOW,
        cooldown_minutes=10,
    )

    suppression_elapsed = (
        last_ssl_alert_at is None
        or (_NOW - last_ssl_alert_at) >= SSL_ALERT_SUPPRESSION
    )
    expected = (
        days is not None
        and days < SSL_WARNING_THRESHOLD_DAYS
        and suppression_elapsed
    )
    assert send_ssl is expected


# ---------------------------------------------------------------------------
# Property 7: Down-alert message content
# ---------------------------------------------------------------------------
# Feature: uptime-guardian, Property 7: Down-alert message content
@settings(max_examples=50)
@given(
    name=st.text(min_size=1, max_size=40),
    url=st.text(min_size=1, max_size=60),
    status_code=st.one_of(st.none(), st.integers(min_value=100, max_value=599)),
    error=st.text(min_size=1, max_size=60),
    offset=st.integers(min_value=0, max_value=60 * 24 * 365),
)
def test_property_7_down_message_content(
    name: str,
    url: str,
    status_code: Optional[int],
    error: str,
    offset: int,
) -> None:
    """build_down_message contains the name, URL, status, UTC timestamp, and
    error description.

    Validates: Requirements 5.2
    """
    checked_at = _NOW - timedelta(minutes=offset)
    monitor = FakeMonitor(name=name, url=url)
    result = FakeResult(
        is_up=False,
        status_code=status_code,
        checked_at=checked_at,
        error_message=error,
    )

    message = build_down_message(monitor, result)

    assert name in message
    assert url in message
    if status_code is None:
        assert "Connection failed" in message
    else:
        assert str(status_code) in message
    assert error in message
    assert checked_at.strftime("%Y-%m-%d %H:%M:%S UTC") in message
    assert "UTC" in message


# ---------------------------------------------------------------------------
# Property 9: SSL-warning message content
# ---------------------------------------------------------------------------
# Feature: uptime-guardian, Property 9: SSL-warning message content
@settings(max_examples=50)
@given(
    name=st.text(min_size=1, max_size=40),
    url=st.text(min_size=1, max_size=60),
    days=st.integers(min_value=0, max_value=13),
)
def test_property_9_ssl_message_content(
    name: str, url: str, days: int
) -> None:
    """build_ssl_message contains the name, the days remaining, and the URL.

    Validates: Requirements 6.2
    """
    monitor = FakeMonitor(name=name, url=url)
    result = FakeResult(ssl_days_remaining=days)

    message = build_ssl_message(monitor, result)

    assert name in message
    assert url in message
    assert str(days) in message


# ---------------------------------------------------------------------------
# Property 10: Telegram dispatch never raises
# ---------------------------------------------------------------------------
class _RaisingClient:
    """Fake httpx.AsyncClient whose post() always raises the given exception."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def __aenter__(self) -> "_RaisingClient":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def post(self, *args: object, **kwargs: object) -> object:
        raise self._exc


# Feature: uptime-guardian, Property 10: Telegram dispatch never raises
@settings(max_examples=50, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    exc=st.sampled_from(
        [
            httpx.ConnectError("boom"),
            httpx.TimeoutException("slow"),
            httpx.HTTPError("generic"),
            ValueError("malformed response"),
            RuntimeError("arbitrary"),
        ]
    )
)
@pytest.mark.asyncio
async def test_property_10_dispatch_never_raises(
    exc: Exception, monkeypatch: pytest.MonkeyPatch
) -> None:
    """For any outbound failure mode, send_telegram_alert returns without
    propagating an exception.

    Validates: Requirements 5.5, 7.3
    """

    def _factory(*args: object, **kwargs: object) -> _RaisingClient:
        return _RaisingClient(exc)

    monkeypatch.setattr(alerter.httpx, "AsyncClient", _factory)

    # Must complete without raising.
    await send_telegram_alert("hello")


@pytest.mark.asyncio
async def test_dispatch_swallows_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure loading Settings is also swallowed (Req 5.5, 7.3)."""

    def _boom() -> object:
        raise RuntimeError("no config")

    monkeypatch.setattr(alerter, "load_settings", _boom)
    await send_telegram_alert("hello")


# ---------------------------------------------------------------------------
# Unit: Telegram request shape (Property 4.7)
# ---------------------------------------------------------------------------
class _RecordingClient:
    """Fake httpx.AsyncClient that records the post() call arguments."""

    last_url: Optional[str] = None
    last_json: Optional[dict] = None

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> "_RecordingClient":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def post(self, url: str, json: dict, **kwargs: object) -> object:
        _RecordingClient.last_url = url
        _RecordingClient.last_json = json

        class _Resp:
            def raise_for_status(self) -> None:
                return None

        return _Resp()


@pytest.mark.asyncio
async def test_telegram_request_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """The dispatch posts to the bot-token URL with chat_id, text, and HTML
    parse_mode in the body.

    Validates: Requirements 7.1, 7.2
    """
    _RecordingClient.last_url = None
    _RecordingClient.last_json = None
    monkeypatch.setattr(alerter.httpx, "AsyncClient", _RecordingClient)

    settings_obj = alerter.load_settings()
    await send_telegram_alert("the message")

    assert _RecordingClient.last_url is not None
    assert settings_obj.telegram_bot_token in _RecordingClient.last_url
    assert _RecordingClient.last_url.endswith("/sendMessage")

    body = _RecordingClient.last_json
    assert body is not None
    assert body["chat_id"] == settings_obj.telegram_chat_id
    assert body["text"] == "the message"
    assert body["parse_mode"] == "HTML"
