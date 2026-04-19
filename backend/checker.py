"""HTTP and SSL health checking for Uptime Guardian.

This module contains the :class:`Checker` logic: pure helpers that classify an
HTTP status code and compute SSL certificate expiry, an SSL probe that never
raises, and the asynchronous :func:`check_monitor` entry point that performs a
single check for a monitor and returns an *unsaved* :class:`CheckResult`.

Design notes:

- ``classify_status`` maps a status code to ``is_up`` (True iff 200-299).
- ``compute_ssl_days_remaining`` returns the whole number of days between
  ``now`` and a certificate's ``notAfter`` (may be zero or negative).
- ``perform_ssl_check`` wraps all socket/ssl I/O so any failure yields
  ``(False, 0)`` and never propagates an exception, keeping the HTTP outcome
  intact (Requirement 3.3).
- ``check_monitor`` uses ``httpx.AsyncClient`` with a 10.0s timeout, records the
  elapsed response time in milliseconds, classifies the result, performs the
  SSL check only for ``https`` URLs, and returns an unsaved ``CheckResult``.

Requirements traceability: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4.
"""

from __future__ import annotations

import socket
import ssl
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from models import CheckResult, Monitor

# Request timeout applied to every outbound HTTP check (Requirement 2.1).
HTTP_TIMEOUT_SECONDS: float = 10.0

# Default HTTPS port used when a URL does not specify one (Requirement 3.1).
DEFAULT_HTTPS_PORT: int = 443

# Format of the ``notAfter`` field returned by ``ssl.getpeercert`` (GMT).
_CERT_TIME_FORMAT: str = "%b %d %H:%M:%S %Y %Z"


def classify_status(status_code: int | None) -> bool:
    """Return ``is_up``: True iff ``status_code`` is in the range 200-299.

    A ``None`` status code (connection failure) is treated as down.

    Validates: Requirements 2.3, 2.4
    """
    if status_code is None:
        return False
    return 200 <= status_code < 300


def compute_ssl_days_remaining(not_after: datetime, now: datetime) -> int:
    """Return the whole number of days from ``now`` until ``not_after``.

    The result may be zero (expires within the day) or negative (already
    expired). ``timedelta.days`` truncates toward negative infinity, so an
    exact offset of ``d`` whole days yields exactly ``d``.

    Validates: Requirements 3.1, 3.2
    """
    return (not_after - now).days


def perform_ssl_check(
    host: str,
    port: int = DEFAULT_HTTPS_PORT,
    now: datetime | None = None,
) -> tuple[bool | None, int | None]:
    """Fetch and validate the TLS certificate for ``host``:``port``.

    Connects, performs a validating TLS handshake, parses the certificate's
    ``notAfter`` field, and computes the days remaining. ``ssl_valid`` is True
    when more than zero days remain. Any failure (DNS, connection, handshake,
    certificate validation, parsing) is contained and reported as
    ``(False, 0)``; this function never raises (Requirement 3.3).

    Returns:
        A ``(ssl_valid, ssl_days_remaining)`` tuple.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        context = ssl.create_default_context()
        with socket.create_connection(
            (host, port), timeout=HTTP_TIMEOUT_SECONDS
        ) as sock:
            with context.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()

        if not cert or "notAfter" not in cert:
            # No usable certificate metadata -> treat as a validation failure.
            return False, 0

        not_after = datetime.strptime(
            cert["notAfter"], _CERT_TIME_FORMAT
        ).replace(tzinfo=timezone.utc)

        # Normalize ``now`` to an aware UTC datetime so the subtraction is valid
        # regardless of whether the caller supplied a naive value.
        now_utc = now if now.tzinfo is not None else now.replace(
            tzinfo=timezone.utc
        )

        days_remaining = compute_ssl_days_remaining(not_after, now_utc)
        return days_remaining > 0, days_remaining
    except Exception:
        # Any failure is contained: SSL is reported invalid without aborting
        # the surrounding HTTP check outcome (Requirement 3.3).
        return False, 0


async def check_monitor(monitor: Monitor) -> CheckResult:
    """Perform a single HTTP (and, for HTTPS, SSL) check for ``monitor``.

    Sends an asynchronous GET request with a 10.0s timeout, records the elapsed
    response time in milliseconds, and classifies the response. Connection
    failures, timeouts, and any other request exception produce a result with
    ``status_code=None``, ``is_up=False``, and a populated ``error_message``.

    For ``https`` URLs the certificate is probed via :func:`perform_ssl_check`;
    for non-HTTPS URLs the SSL fields are left ``None`` (Requirement 3.4). The
    returned :class:`CheckResult` is *not* persisted (Requirement 2.6).
    """
    url = monitor.url
    status_code: int | None = None
    response_time_ms: float | None = None
    is_up: bool = False
    error_message: str | None = None
    ssl_valid: bool | None = None
    ssl_days_remaining: int | None = None

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
        response_time_ms = (time.perf_counter() - start) * 1000.0
        status_code = response.status_code
        is_up = classify_status(status_code)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        response_time_ms = (time.perf_counter() - start) * 1000.0
        status_code = None
        is_up = False
        error_message = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # any other request/transport failure
        response_time_ms = (time.perf_counter() - start) * 1000.0
        status_code = None
        is_up = False
        error_message = f"{type(exc).__name__}: {exc}"

    # SSL check applies only to HTTPS URLs; any failure here must not crash the
    # check (perform_ssl_check is already exception-safe, but guard anyway).
    if url.lower().startswith("https://"):
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            port = parsed.port or DEFAULT_HTTPS_PORT
            ssl_valid, ssl_days_remaining = perform_ssl_check(host, port)
        except Exception:
            ssl_valid, ssl_days_remaining = False, 0

    return CheckResult(
        monitor_id=getattr(monitor, "id", None),
        status_code=status_code,
        response_time_ms=response_time_ms,
        is_up=is_up,
        ssl_valid=ssl_valid,
        ssl_days_remaining=ssl_days_remaining,
        error_message=error_message,
    )
