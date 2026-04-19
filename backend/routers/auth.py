"""Authentication router for Uptime Guardian.

Exposes ``POST /api/auth/login``: it validates the submitted credentials
against the stored ``User`` and, on success, issues a signed JWT
(Requirement 12.1). Credentials that do not match yield HTTP 401 and no token
(Requirement 12.2).

Requirements traceability: 12.1, 12.2.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth import create_access_token, verify_password
from database import get_db
from schemas import LoginRequest, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Authenticate a user and return an access token.

    ``crud`` is imported lazily inside the handler so this module does not
    depend on ``crud`` at import time (it is authored concurrently and may not
    be importable when this router module is first loaded).

    Args:
        payload: The submitted username and password.
        db: Database session dependency.

    Returns:
        A :class:`TokenResponse` carrying a freshly issued bearer token.

    Raises:
        HTTPException: With status 401 when the credentials do not match.
    """
    import crud  # lazy import to avoid import-order coupling

    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid username or password",
    )

    user = crud.get_user_by_username(db, payload.username)
    if user is None:
        raise invalid_credentials
    if not verify_password(payload.password, user.password_hash):
        raise invalid_credentials

    token = create_access_token(subject=user.username)
    return TokenResponse(access_token=token)
