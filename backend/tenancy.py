"""Tenant resolution and isolation dependencies (multi-tenant SaaS).

FastAPI dependencies that turn the verified JWT subject into a Tenant_User row
and enforce ownership/admin boundaries:

- :func:`get_current_tenant_user` resolves the authenticated username to a
  ``User`` row (401 if it cannot be resolved).
- :func:`require_admin` permits only ``is_admin`` users (403 otherwise).
- :func:`get_owned_monitor_or_404` returns a monitor only when it is owned by
  the requesting user, raising an identical 404 for "not found" and "owned by
  another tenant" so resource existence cannot be enumerated.

Feature: saas-multi-tenant.
Requirements traceability: 3.5, 3.6, 4.4, 4.5, 4.7, 17.7, 18.6, 18.7.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Monitor, User


def get_current_tenant_user(
    subject: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the JWT subject to a Tenant_User row, or raise HTTP 401.

    The :func:`get_current_user` dependency already rejects missing/invalid
    tokens with 401; this additionally rejects a well-formed token whose subject
    does not resolve to a stored user (Requirements 3.6, 10.5, 18.7).
    """
    import crud  # lazy import to avoid import-order coupling

    user = crud.get_user_by_username(db, subject)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_admin(
    user: User = Depends(get_current_tenant_user),
) -> User:
    """Allow only Admin_Users; otherwise raise HTTP 403 (Req 17.7, 18.6)."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges are required",
        )
    return user


def get_owned_monitor_or_404(
    db: Session, user: User, monitor_id: int
) -> Monitor:
    """Return the monitor iff it exists AND is owned by ``user``.

    Raises HTTP 404 with an identical body for both the "does not exist" and
    "owned by another tenant" cases so the two are indistinguishable
    (Requirements 4.4, 4.5, 4.7).
    """
    import crud  # lazy import to avoid import-order coupling

    monitor = crud.get_owned_monitor(db, user.id, monitor_id)
    if monitor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found"
        )
    return monitor
