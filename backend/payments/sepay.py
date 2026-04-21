"""SePay client helpers: QR reference, reference codes, webhook verification.

All functions are pure or local (no outbound HTTP), so QR construction stays
well within the 3-second initiation budget (Requirement 13.2) and webhook
verification is deterministic and testable.

Security: :func:`verify_webhook` is the authenticity gate for the only
non-JWT endpoint. It compares the configured API key (``Authorization: Apikey
<key>``) or an HMAC-SHA256 of the raw request body, both in constant time
(Requirements 14.1, 14.2). Secrets come from configuration, never code.

Feature: saas-multi-tenant.
Requirements traceability: 13.2, 14.1, 14.2, 15.5.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from decimal import Decimal
from typing import Mapping
from urllib.parse import urlencode

from config import load_settings
from models import Plan

# Prefix applied to every generated payment reference code.
_REFERENCE_PREFIX = "NCMS"

# Header names accepted for the HMAC-SHA256 signature mode.
_HMAC_SIGNATURE_HEADERS = ("x-signature", "x-sepay-signature")


def _format_amount(amount: Decimal) -> str:
    """Format a money amount for the VietQR URL.

    VND transfers are whole numbers; render an integral value without a decimal
    point and otherwise preserve two decimal places.
    """
    if amount == amount.to_integral_value():
        return str(int(amount))
    return f"{amount:.2f}"


def build_qr_reference(plan: Plan, reference_code: str) -> str:
    """Build a dynamic VietQR image URL encoding the amount and reference code.

    The ``des`` (description) field carries the reference code, which SePay
    echoes back in its webhook so the payment can be matched (Requirement 13.2).
    Pure string construction; performs no network I/O.
    """
    settings = load_settings()
    query = urlencode(
        {
            "acc": settings.sepay_account_number,
            "bank": settings.sepay_bank_code,
            "amount": _format_amount(plan.price),
            "des": reference_code,
        }
    )
    return f"{settings.sepay_qr_base_url}?{query}"


def generate_reference_code(user_id: int, plan_id: int) -> str:
    """Return a globally-unique, URL-safe payment reference code.

    Uniqueness is provided by a random UUID encoded in base32; the value is
    additionally protected by the UNIQUE constraint on
    ``transactions.reference_code`` (Requirement 15.5). The user/plan ids are
    accepted for interface symmetry and potential tracing but are not required
    for uniqueness.
    """
    token = (
        base64.b32encode(uuid.uuid4().bytes).decode("ascii").rstrip("=")
    )
    return f"{_REFERENCE_PREFIX}{token}"


def _check_api_key(headers: Mapping[str, str], api_key: str) -> bool:
    """Constant-time check of the ``Authorization: Apikey <key>`` header."""
    auth = _get_header(headers, "authorization")
    if not auth:
        return False
    scheme, _, value = auth.partition(" ")
    if scheme.lower() != "apikey" or not value:
        return False
    return hmac.compare_digest(value.strip(), api_key)


def _check_hmac(
    headers: Mapping[str, str], raw_body: bytes, secret: str
) -> bool:
    """Constant-time check of an HMAC-SHA256 signature over the raw body."""
    supplied = None
    for name in _HMAC_SIGNATURE_HEADERS:
        supplied = _get_header(headers, name)
        if supplied:
            break
    if not supplied:
        return False
    expected = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(supplied.strip().lower(), expected.lower())


def _get_header(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive header lookup that tolerates plain dict or Headers."""
    # Starlette Headers is already case-insensitive; a plain dict is not.
    try:
        value = headers.get(name)  # type: ignore[call-arg]
    except TypeError:  # pragma: no cover - defensive
        value = None
    if value is not None:
        return value
    lowered = name.lower()
    for key, val in headers.items():
        if key.lower() == lowered:
            return val
    return None


def verify_webhook(headers: Mapping[str, str], raw_body: bytes) -> bool:
    """Verify a SePay webhook request is authentic (Requirements 14.1, 14.2).

    Accepts the request when the configured API key matches the
    ``Authorization: Apikey`` header, or when the configured HMAC secret
    validates the signature over the raw body. When neither an API key nor an
    HMAC secret is configured, verification is disabled and the request is
    accepted (documented dev-only behavior). Returns ``False`` on any mismatch.
    """
    settings = load_settings()
    api_key = settings.sepay_api_key
    secret = settings.sepay_webhook_secret

    if not api_key and not secret:
        # Dev-only: no verification configured.
        return True

    if api_key and _check_api_key(headers, api_key):
        return True
    if secret and _check_hmac(headers, raw_body, secret):
        return True
    return False
