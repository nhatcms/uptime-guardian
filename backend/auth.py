"""Authentication logic for Uptime Guardian.

This module holds the pure authentication primitives plus the FastAPI
dependency used to protect data routes:

- Password hashing/verification with passlib bcrypt (Requirement 12.3).
- Signed JWT issue/validate (HS256) with ``sub`` and ``exp`` claims
  (Requirements 12.5, 12.6).
- ``get_current_user`` dependency that rejects missing, malformed, tampered,
  or expired tokens with HTTP 401 (Requirements 12.4, 12.6).

The signing secret is read from ``Settings.auth_secret_key`` (loaded from the
``.env`` file / environment); no secret is hardcoded (Requirement 9.1).

Requirements traceability: 12.3, 12.4, 12.5, 12.6.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext

from config import load_settings

# JWT signing algorithm. HS256 is symmetric and uses ``auth_secret_key``.
ALGORITHM: str = "HS256"

# Default token lifetime in minutes when the caller does not specify one.
DEFAULT_EXPIRE_MINUTES: int = 60

# Password hashing context. ``deprecated="auto"`` lets passlib flag and upgrade
# legacy hashes transparently if the scheme list ever changes.
_pwd_context: CryptContext = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Extracts a bearer token from the ``Authorization`` header. ``auto_error`` is
# disabled so a missing header yields ``None`` (handled as 401 below) rather
# than FastAPI's default 403/401 behavior, keeping the rejection consistent.
_oauth2_scheme: OAuth2PasswordBearer = OAuth2PasswordBearer(
    tokenUrl="api/auth/login", auto_error=False
)


def _get_secret() -> str:
    """Return the JWT signing secret from settings (never hardcoded)."""
    return load_settings().auth_secret_key


def hash_password(password: str) -> str:
    """Return a secure bcrypt hash of ``password`` (Requirement 12.3)."""
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Return ``True`` if ``password`` matches ``password_hash``.

    Returns ``False`` instead of raising if the stored hash is malformed or
    uses an unknown scheme, so a corrupt record cannot crash the login path.
    """
    try:
        return _pwd_context.verify(password, password_hash)
    except (ValueError, TypeError):
        return False


def create_access_token(
    subject: str,
    expires_minutes: int = DEFAULT_EXPIRE_MINUTES,
    now: Optional[datetime] = None,
) -> str:
    """Issue a signed JWT for ``subject`` (Requirement 12.5).

    The token carries the ``sub`` claim (the subject) and an ``exp`` claim set
    ``expires_minutes`` minutes after ``now`` (defaults to the current UTC
    time). It is signed with HS256 using the configured secret.

    Args:
        subject: The token subject (the authenticated username).
        expires_minutes: Token lifetime in minutes from ``now``.
        now: Issue time; defaults to the current UTC time. Injectable for tests.

    Returns:
        The encoded JWT as a string.
    """
    issued_at = now or datetime.now(timezone.utc)
    expire = issued_at + timedelta(minutes=expires_minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "exp": expire,
        "iat": issued_at,
    }
    return jwt.encode(payload, _get_secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """Validate ``token`` and return its claims, or ``None`` if invalid.

    The token signature is verified and the ``exp`` claim is enforced. A token
    with an invalid signature, an elapsed validity period, or any other decode
    error yields ``None`` rather than raising (Requirement 12.6).

    Args:
        token: The encoded JWT to validate.

    Returns:
        The decoded claims dict on success, otherwise ``None``.
    """
    try:
        return jwt.decode(token, _get_secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


def get_current_user(
    token: Optional[str] = Depends(_oauth2_scheme),
) -> str:
    """FastAPI dependency that authorizes a request and returns the subject.

    Raises HTTP 401 when the bearer token is missing, malformed, tampered, or
    expired (Requirements 12.4, 12.6). On success, returns the username carried
    in the token's ``sub`` claim.

    Args:
        token: The bearer token extracted from the ``Authorization`` header.

    Returns:
        The authenticated subject (username).

    Raises:
        HTTPException: With status 401 when no valid token is presented.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_error
    claims = decode_access_token(token)
    if claims is None:
        raise credentials_error
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise credentials_error
    return subject
