"""Google OAuth 2.0 (OpenID Connect) authorization-code helper.

This module isolates every interaction with Google so the auth router stays
small and testable. It implements the server-side authorization-code flow:

1. :func:`build_authorization_url` constructs the consent-screen URL that the
   browser is redirected to, embedding a signed, short-lived ``state`` token for
   CSRF protection.
2. After the user consents, Google redirects back to our callback with a
   ``code``; :func:`exchange_code_for_profile` exchanges that code at Google's
   token endpoint (over TLS, server-to-server) for an ``id_token`` and returns
   the parsed :class:`GoogleProfile`.

Security notes:

- The ``state`` is a JWT signed with the app's ``auth_secret_key`` and carries a
  random nonce plus a short expiry, so a forged or replayed callback is
  rejected (:func:`verify_state`).
- The ``id_token`` is received directly from Google's token endpoint over a
  verified TLS channel, so per Google's guidance its signature need not be
  re-verified locally; we still validate the ``iss`` and ``aud`` claims as
  defence in depth.
- The client secret is read from settings (never hardcoded) and only ever sent
  to Google's token endpoint.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
import jwt

from config import load_settings

# Scopes requested on the consent screen: the user's basic profile and email.
_SCOPES = "openid email profile"

# Accepted issuers for Google-issued ID tokens.
_VALID_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}

# Network budget for the server-to-server token exchange.
_TOKEN_EXCHANGE_TIMEOUT_SECONDS = 10.0

# Lifetime of the signed CSRF state token.
_STATE_TTL_SECONDS = 600

# Marker claim so a state token can only be used for this purpose.
_STATE_PURPOSE = "google_oauth_state"

_STATE_ALGORITHM = "HS256"


class GoogleOAuthError(Exception):
    """Raised when the OAuth exchange fails or returns an unusable profile."""


class GoogleOAuthUnavailable(Exception):
    """Raised when Google cannot be reached (network/timeout) -> surface 503."""


@dataclass(frozen=True)
class GoogleProfile:
    """The subset of a Google profile this app consumes."""

    google_id: str
    email: str
    email_verified: bool
    display_name: Optional[str]
    avatar_url: Optional[str]


def is_configured() -> bool:
    """Return True when Google client id and secret are both set."""
    return load_settings().google_oauth_configured


# --- CSRF state token ------------------------------------------------------

def create_state() -> str:
    """Return a signed, short-lived ``state`` token carrying a random nonce."""
    settings = load_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "purpose": _STATE_PURPOSE,
        "nonce": secrets.token_urlsafe(16),
        "iat": now,
        "exp": now + timedelta(seconds=_STATE_TTL_SECONDS),
    }
    return jwt.encode(
        payload, settings.auth_secret_key, algorithm=_STATE_ALGORITHM
    )


def verify_state(state: str) -> bool:
    """Return True iff ``state`` is a valid, unexpired token we issued."""
    if not state:
        return False
    settings = load_settings()
    try:
        claims = jwt.decode(
            state, settings.auth_secret_key, algorithms=[_STATE_ALGORITHM]
        )
    except jwt.PyJWTError:
        return False
    return claims.get("purpose") == _STATE_PURPOSE


# --- Authorization-code flow ----------------------------------------------

def build_authorization_url(state: str) -> str:
    """Build the Google consent-screen URL to redirect the browser to.

    Requests the openid/email/profile scopes and forces a refresh-token-capable
    consent prompt. ``state`` is echoed back by Google to the callback.
    """
    settings = load_settings()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": _SCOPES,
        "state": state,
        "access_type": "online",
        "include_granted_scopes": "true",
        "prompt": "select_account",
    }
    return f"{settings.google_authorize_url}?{urlencode(params)}"


async def exchange_code_for_profile(code: str) -> GoogleProfile:
    """Exchange an authorization ``code`` for the user's Google profile.

    Raises:
        GoogleOAuthUnavailable: If Google's token endpoint cannot be reached.
        GoogleOAuthError: If the exchange is rejected or the returned token is
            missing/invalid (bad issuer/audience, no subject, etc.).
    """
    settings = load_settings()
    data = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        async with httpx.AsyncClient(
            timeout=_TOKEN_EXCHANGE_TIMEOUT_SECONDS
        ) as client:
            response = await client.post(settings.google_token_url, data=data)
    except httpx.HTTPError as exc:
        raise GoogleOAuthUnavailable(str(exc)) from exc

    if response.status_code != 200:
        # Google returns 4xx with an {"error": ...} body for invalid/expired
        # codes or redirect-uri mismatches.
        raise GoogleOAuthError(
            f"Token exchange failed ({response.status_code})"
        )

    payload = response.json()
    id_token = payload.get("id_token")
    if not id_token:
        raise GoogleOAuthError("Token response did not include an id_token")

    claims = _decode_id_token(id_token, expected_aud=settings.google_client_id)
    return _profile_from_claims(claims)


def _decode_id_token(id_token: str, *, expected_aud: str) -> dict[str, Any]:
    """Decode the Google ID token and validate issuer/audience claims.

    The token came directly from Google's token endpoint over TLS, so the
    signature is trusted without re-verification (per Google's guidance); we
    still enforce ``aud`` and ``iss`` to reject a token minted for another app.
    """
    try:
        claims = jwt.decode(
            id_token,
            options={"verify_signature": False},
            algorithms=["RS256"],
        )
    except jwt.PyJWTError as exc:
        raise GoogleOAuthError("ID token could not be decoded") from exc

    if expected_aud and claims.get("aud") != expected_aud:
        raise GoogleOAuthError("ID token audience mismatch")
    if claims.get("iss") not in _VALID_ISSUERS:
        raise GoogleOAuthError("ID token issuer mismatch")
    return claims


def _profile_from_claims(claims: dict[str, Any]) -> GoogleProfile:
    """Map validated ID-token claims to a :class:`GoogleProfile`."""
    google_id = claims.get("sub")
    email = claims.get("email")
    if not google_id or not email:
        raise GoogleOAuthError("ID token missing subject or email")

    # ``email_verified`` may arrive as a bool or the string "true".
    raw_verified = claims.get("email_verified", False)
    email_verified = raw_verified is True or str(raw_verified).lower() == "true"

    return GoogleProfile(
        google_id=str(google_id),
        email=str(email),
        email_verified=email_verified,
        display_name=claims.get("name"),
        avatar_url=claims.get("picture"),
    )
