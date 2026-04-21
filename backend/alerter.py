"""Alert decision logic and Telegram dispatch for Uptime Guardian.

This module separates pure alert-decision and message-formatting logic from the
single I/O boundary (``send_telegram_alert``). The pure functions are exercised
by property-based tests; the dispatch function catches every exception, logs
it, and never raises into the caller so a failed alert can never break a check
cycle.

Decision rules (Requirements 5.1, 5.3, 5.4, 6.1, 6.3):

* A *down* alert fires only on an up -> down transition for a monitor with
  ``notify_on_failure`` enabled, and only when the alert cooldown window has
  elapsed since the last down alert.
* An *SSL* warning fires only when ``ssl_days_remaining`` is below the 14-day
  threshold and at least 24 hours have elapsed since the last SSL warning, both
  measured against absolute timestamps.

Requirements traceability: 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 7.1, 7.2,
7.3.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, Protocol

import httpx

from config import load_settings

logger = logging.getLogger(__name__)

# The certificate-expiry threshold (in days) below which an SSL warning fires.
SSL_WARNING_THRESHOLD_DAYS: int = 14
# Minimum gap between successive SSL warnings for the same monitor.
SSL_ALERT_SUPPRESSION = timedelta(hours=24)
# Telegram Bot API base; the bot token is interpolated into the path.
_TELEGRAM_API_BASE = "https://api.telegram.org"
# Per-request timeout (seconds) for the outbound Telegram call.
_TELEGRAM_TIMEOUT_SECONDS = 10.0


class _MonitorLike(Protocol):
    """Structural type for the monitor fields the alerter reads."""

    name: str
    url: str
    notify_on_failure: bool


class _ResultLike(Protocol):
    """Structural type for the check-result fields the alerter reads."""

    is_up: bool
    status_code: Optional[int]
    checked_at: datetime
    error_message: Optional[str]
    ssl_days_remaining: Optional[int]


def decide_alerts(
    current_result: _ResultLike,
    previous_result: Optional[_ResultLike],
    monitor: _MonitorLike,
    last_down_alert_at: Optional[datetime],
    last_ssl_alert_at: Optional[datetime],
    now: datetime,
    cooldown_minutes: int,
) -> tuple[bool, bool]:
    """Decide whether to send a down alert and/or an SSL warning.

    Args:
        current_result: The freshly produced check result.
        previous_result: The immediately preceding check result, or ``None`` if
            this is the monitor's first check.
        monitor: The monitor being checked (read for ``notify_on_failure``).
        last_down_alert_at: Timestamp of the last down alert, or ``None``.
        last_ssl_alert_at: Timestamp of the last SSL warning, or ``None``.
        now: The current time used for cooldown / suppression comparisons.
        cooldown_minutes: The down-alert cooldown window in minutes.

    Returns:
        A ``(send_down, send_ssl)`` tuple of booleans.
    """
    send_down = _decide_down_alert(
        current_result=current_result,
        previous_result=previous_result,
        monitor=monitor,
        last_down_alert_at=last_down_alert_at,
        now=now,
        cooldown_minutes=cooldown_minutes,
    )
    send_ssl = _decide_ssl_alert(
        current_result=current_result,
        last_ssl_alert_at=last_ssl_alert_at,
        now=now,
    )
    return send_down, send_ssl


def _decide_down_alert(
    current_result: _ResultLike,
    previous_result: Optional[_ResultLike],
    monitor: _MonitorLike,
    last_down_alert_at: Optional[datetime],
    now: datetime,
    cooldown_minutes: int,
) -> bool:
    """Return ``True`` iff a site-down alert should be dispatched.

    Requires an up -> down transition (Requirement 5.1), ``notify_on_failure``
    enabled (Requirement 5.4), and the cooldown window elapsed (Requirement
    5.3).
    """
    if current_result.is_up:
        return False
    if previous_result is None or not previous_result.is_up:
        return False
    if not monitor.notify_on_failure:
        return False
    if last_down_alert_at is None:
        return True
    cooldown = timedelta(minutes=cooldown_minutes)
    return (now - last_down_alert_at) >= cooldown


def _decide_ssl_alert(
    current_result: _ResultLike,
    last_ssl_alert_at: Optional[datetime],
    now: datetime,
) -> bool:
    """Return ``True`` iff an SSL-expiry warning should be dispatched.

    Requires ``ssl_days_remaining`` below the 14-day threshold (Requirement
    6.1) and at least 24 hours since the last SSL warning (Requirement 6.3).
    """
    days = current_result.ssl_days_remaining
    if days is None or days >= SSL_WARNING_THRESHOLD_DAYS:
        return False
    if last_ssl_alert_at is None:
        return True
    return (now - last_ssl_alert_at) >= SSL_ALERT_SUPPRESSION


def build_down_message(monitor: _MonitorLike, result: _ResultLike) -> str:
    """Build the HTML site-down Telegram message (Requirement 5.2).

    Includes the monitor name and URL, the status (the numeric code, or
    "Connection failed" when there is no code), the check timestamp in UTC, and
    the error description.
    """
    if result.status_code is None:
        status = "Connection failed"
    else:
        status = str(result.status_code)
    error = result.error_message or "N/A"
    checked_at = _format_utc(result.checked_at)
    return (
        f"🔴 <b>SITE DOWN</b>: {monitor.name}\n"
        f"🌐 URL: {monitor.url}\n"
        f"❌ Status: {status}\n"
        f"⏱ Checked at: {checked_at}\n"
        f"💬 Error: {error}"
    )


def build_ssl_message(monitor: _MonitorLike, result: _ResultLike) -> str:
    """Build the HTML SSL-warning Telegram message (Requirement 6.2).

    Includes the monitor name, the number of days remaining, and the URL.
    """
    days = result.ssl_days_remaining
    return (
        f"⚠️ <b>SSL WARNING</b>: {monitor.name}\n"
        f"🔒 Certificate expires in {days} days\n"
        f"🌐 {monitor.url}"
    )


def _format_utc(moment: datetime) -> str:
    """Render a datetime as a UTC timestamp string for message bodies."""
    return moment.strftime("%Y-%m-%d %H:%M:%S UTC")


async def send_telegram_alert(message: str, chat_id: Optional[str]) -> None:
    """POST ``message`` to the Telegram sendMessage endpoint for ``chat_id``.

    The alert is delivered only to the supplied ``chat_id`` — the owning
    Tenant_User's Telegram chat id — and never to any other tenant (Requirement
    9.1). When ``chat_id`` is empty, unset, or whitespace, the dispatch is
    skipped and the reason is logged (Requirement 9.2).

    The bot token is read from :class:`Settings`; the request carries the chat
    id, the text, and ``parse_mode`` HTML. Any failure (configuration, network,
    timeout, or non-success response) is logged and swallowed within the
    10-second timeout so a failed alert never breaks a check cycle (Requirements
    9.3, 9.4).
    """
    if chat_id is None or not str(chat_id).strip():
        logger.info(
            "Skipping Telegram alert: missing Telegram_Chat_Id for recipient"
        )
        return
    try:
        settings = load_settings()
        url = (
            f"{_TELEGRAM_API_BASE}/bot{settings.telegram_bot_token}/sendMessage"
        )
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
        }
        async with httpx.AsyncClient(
            timeout=_TELEGRAM_TIMEOUT_SECONDS
        ) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
    except Exception:  # noqa: BLE001 - alerts must never break a check cycle
        logger.exception("Failed to dispatch Telegram alert")
