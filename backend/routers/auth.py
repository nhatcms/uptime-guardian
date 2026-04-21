"""Authentication router (multi-tenant SaaS).

Exposes ``POST /api/auth/register`` and ``POST /api/auth/login``. Both verify a
Cloudflare Turnstile token before any credential work (Requirements 11, 12):

- Turnstile FAILED (including empty/missing token) -> HTTP 400.
- Turnstile UNAVAILABLE (timeout / unreachable)    -> HTTP 503.
- Turnstile SUCCESS -> proceed.

Registration creates the Tenant_User on the Free Plan with a hashed password
(Requirements 2.5, 11.5); a duplicate username/email yields 409 (Requirement
11.6) and leaves existing records unchanged. Login issues a JWT only after both
Turnstile and credential checks pass; bad credentials yield 401 (Requirement
12.6).

``crud`` is imported lazily inside each handler so this module does not couple
to ``crud`` at import time, matching the existing router convention.

Feature: saas-multi-tenant.
Requirements traceability: 2.5, 2.9, 11.1-11.6, 12.1-12.6.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import plans
from auth import create_access_token, hash_password, verify_password
from database import get_db
from schemas import LoginRequest, RegisterRequest, TokenResponse
from turnstile import TurnstileResult, verify_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _require_turnstile(result: TurnstileResult) -> None:
    """Translate a Turnstile outcome to an HTTP error, or return on SUCCESS.

    FAILED -> 400 (Requirements 11.2, 11.3, 12.2, 12.3); UNAVAILABLE -> 503
    (Requirements 11.4, 12.4). No state has been changed when this raises.
    """
    if result is TurnstileResult.UNAVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification service is unavailable; please try again",
        )
    if result is not TurnstileResult.SUCCESS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bot challenge verification failed",
        )


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Register a Tenant_User after Turnstile verification (Requirement 11).

    Verifies the Turnstile token first, then enforces username/email uniqueness
    (409 on conflict, leaving records unchanged), then creates the user on the
    Free Plan with a hashed password and returns 201.
    """
    import crud  # lazy import to avoid import-order coupling

    _require_turnstile(await verify_token(payload.turnstile_token))

    if crud.get_user_by_username(db, payload.username) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username is already in use",
        )
    if crud.get_user_by_email(db, payload.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already in use",
        )

    free_plan = plans.get_free_plan(db)
    try:
        user = crud.create_tenant_user(
            db,
            username=payload.username,
            email=payload.email,
            password_hash=hash_password(payload.password),
            plan_id=free_plan.id,
        )
    except IntegrityError:
        # A concurrent registration claimed the username/email first.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email is already in use",
        )

    return {"id": user.id, "username": user.username, "email": user.email}


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Authenticate a user after Turnstile verification and issue a JWT.

    Turnstile is verified before credentials are validated (Requirement 12.1).
    Credentials that do not match a stored user yield 401 with no token
    (Requirement 12.6).
    """
    import crud  # lazy import to avoid import-order coupling

    _require_turnstile(await verify_token(payload.turnstile_token))

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
