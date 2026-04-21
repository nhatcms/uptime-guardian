"""Cloudflare Turnstile server-side verification (multi-tenant SaaS).

Provides :func:`verify_token`, used by the register and login routers to verify
a client-supplied Turnstile token before any credential work (Requirements 11,
12). The function never raises: every transport failure, timeout, or non-200
response maps to :attr:`TurnstileResult.UNAVAILABLE` so callers can translate
outcomes to HTTP status codes (FAILED -> 400, UNAVAILABLE -> 503).

When ``turnstile_secret_key`` is empty (local development), any non-empty token
is accepted (documented dev-only bypass); a real secret must be configured in
production.

Feature: saas-multi-tenant.
Requirements traceability: 11.1, 11.2, 11.3, 11.4, 12.1, 12.2, 12.3, 12.4.
"""

from __future__ import annotations

import enum
import logging
from typing import Optional

import httpx

from config import TURNSTILE_TIMEOUT_SECONDS, load_settings

logger = logging.getLogger(__name__)


class TurnstileResult(enum.Enum):
    """Outcome of a Turnstile verification attempt."""

    SUCCESS = "success"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


async def verify_token(token: Optional[str]) -> TurnstileResult:
    """Verify a Turnstile token with Cloudflare (Requirements 11, 12).

    Outcomes:

    * empty/missing/whitespace token        -> FAILED      (caller -> 400)
    * dev mode (empty secret), non-empty token -> SUCCESS
    * siteverify success flag true           -> SUCCESS
    * siteverify success flag false          -> FAILED      (caller -> 400)
    * timeout / network error / non-200      -> UNAVAILABLE  (caller -> 503)

    Never raises: transport failures are caught and mapped to UNAVAILABLE. The
    request is bounded by the 10-second Turnstile timeout (Requirements 11.1,
    11.4, 12.1, 12.4).
    """
    if token is None or not token.strip():
        return TurnstileResult.FAILED

    settings = load_settings()
    secret = settings.turnstile_secret_key
    if not secret:
        # Dev-only bypass: no secret configured, so accept any non-empty token.
        return TurnstileResult.SUCCESS

    try:
        async with httpx.AsyncClient(
            timeout=TURNSTILE_TIMEOUT_SECONDS
        ) as client:
            response = await client.post(
                settings.turnstile_verify_url,
                data={"secret": secret, "response": token},
            )
    except httpx.HTTPError as exc:
        # Includes timeouts, connection errors, etc. (Requirements 11.4, 12.4).
        logger.warning("Turnstile verification unavailable: %s", exc)
        return TurnstileResult.UNAVAILABLE

    if response.status_code != 200:
        logger.warning(
            "Turnstile verification returned HTTP %s", response.status_code
        )
        return TurnstileResult.UNAVAILABLE

    try:
        payload = response.json()
    except ValueError:
        logger.warning("Turnstile verification returned a non-JSON body")
        return TurnstileResult.UNAVAILABLE

    if payload.get("success") is True:
        return TurnstileResult.SUCCESS
    return TurnstileResult.FAILED
