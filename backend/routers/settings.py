"""Dashboard settings router (multi-tenant SaaS).

Endpoints under ``/api/settings`` for the authenticated Tenant_User:

- ``GET /api/settings`` returns the stored Telegram chat id, the active plan
  limits, current active-monitor usage, and the paid-plan expiry (Requirements
  10.2, 21.1-21.4).
- ``PUT /api/settings/telegram`` sets or clears the Telegram chat id with format
  validation (Requirements 10.1, 10.3, 10.4).

Unauthenticated requests are rejected with 401 before any read/write
(Requirement 10.5).

Feature: saas-multi-tenant.
Requirements traceability: 10.1-10.5, 21.1-21.4.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import User
from plans import resolve_active_plan
from schemas import ActivePlanOut, DashboardSettingsOut, TelegramUpdate
from tenancy import get_current_tenant_user

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=DashboardSettingsOut)
def get_settings(
    user: User = Depends(get_current_tenant_user),
    db: Session = Depends(get_db),
) -> DashboardSettingsOut:
    """Return the user's Telegram id, active plan limits, usage, and expiry.

    Validates: Requirements 10.2, 21.1, 21.2, 21.3, 21.4
    """
    import crud  # lazy import to avoid import-order coupling

    plan = resolve_active_plan(db, user)
    monitors = crud.get_monitors_for_user(db, user.id)
    used = sum(1 for m in monitors if m.is_active)
    return DashboardSettingsOut(
        username=user.username,
        email=user.email,
        is_admin=user.is_admin,
        telegram_chat_id=user.telegram_chat_id,
        plan=ActivePlanOut.model_validate(plan),
        monitors_used=used,
        monitors_total=plan.max_monitors,
        plan_expires_at=user.plan_expires_at,
    )


@router.put("/telegram")
def update_telegram(
    payload: TelegramUpdate,
    user: User = Depends(get_current_tenant_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Set or clear the user's Telegram chat id (Requirements 10.1, 10.3, 10.4).

    An empty value clears the stored id; a non-empty value is validated by the
    ``TelegramUpdate`` schema (invalid formats raise 422 before this handler).
    """
    value = payload.telegram_chat_id
    stored = value if value else None
    user.telegram_chat_id = stored
    db.commit()
    return {"telegram_chat_id": stored, "cleared": stored is None}
