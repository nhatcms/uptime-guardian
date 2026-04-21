"""Administrative console router (multi-tenant SaaS).

Plan management plus read-only user/transaction listings under ``/api/admin``,
all behind :func:`require_admin` (403 for non-admins, 401 unauthenticated;
Requirements 17.7, 18.6, 18.7).

Plan create/update validate bounds and case-insensitive name uniqueness,
returning 400 with the offending field (Requirement 17.2). Plan deletion is
blocked with 409 when subscribers exist (Requirement 17.6). User and
transaction listings are capped at 100 rows, support empty lists, and never
expose credential fields (Requirements 18.1-18.5).

Feature: saas-multi-tenant.
Requirements traceability: 17.1-17.7, 18.1-18.6.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from database import get_db
from models import User
from plans import resolve_active_plan
from schemas import (
    AdminTransactionOut,
    AdminUserOut,
    PlanCreate,
    PlanOut,
    PlanUpdate,
)
from tenancy import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _validation_error_to_400(exc: ValidationError) -> HTTPException:
    """Map a Pydantic ValidationError to a 400 naming the first bad field."""
    errors = exc.errors()
    field = str(errors[0]["loc"][-1]) if errors else "unknown"
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Invalid value for field '{field}'",
    )


@router.get("/plans", response_model=list[PlanOut])
def list_plans(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[PlanOut]:
    """Return all plans (Requirement 17.4)."""
    import crud

    return [PlanOut.model_validate(p) for p in crud.get_plans(db)]


@router.post("/plans", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(
    payload: dict[str, Any] = Body(...),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> PlanOut:
    """Create a plan, returning 400 on bounds/duplicate-name violations.

    Validates: Requirements 17.1, 17.2
    """
    import crud

    try:
        data = PlanCreate(**payload)
    except ValidationError as exc:
        raise _validation_error_to_400(exc) from exc

    if crud.get_plan_by_name_ci(db, data.name) is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A plan with that name already exists",
        )
    return PlanOut.model_validate(crud.create_plan(db, data))


@router.put("/plans/{plan_id}", response_model=PlanOut)
def update_plan(
    plan_id: int,
    payload: dict[str, Any] = Body(...),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> PlanOut:
    """Update an existing plan, retaining subscriber associations.

    Validates: Requirements 17.2, 17.3
    """
    import crud

    plan = crud.get_plan(db, plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found"
        )

    try:
        data = PlanUpdate(**payload)
    except ValidationError as exc:
        raise _validation_error_to_400(exc) from exc

    if data.name is not None:
        clash = crud.get_plan_by_name_ci(db, data.name)
        if clash is not None and clash.id != plan_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A plan with that name already exists",
            )
    return PlanOut.model_validate(crud.update_plan(db, plan, data))


@router.delete("/plans/{plan_id}")
def delete_plan(
    plan_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Delete a plan with no subscribers; 409 when subscribers exist.

    Validates: Requirements 17.5, 17.6
    """
    import crud

    plan = crud.get_plan(db, plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found"
        )
    if crud.count_plan_subscribers(db, plan_id) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Plan has active subscribers and cannot be deleted",
        )
    crud.delete_plan(db, plan)
    return {"status": "deleted"}


@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AdminUserOut]:
    """Return up to 100 users with username, email, and active plan name only.

    Never exposes credential fields (Requirement 18.2).

    Validates: Requirements 18.1, 18.2, 18.4, 18.5
    """
    import crud

    out: list[AdminUserOut] = []
    for user in crud.list_users(db):
        plan = resolve_active_plan(db, user)
        out.append(
            AdminUserOut(
                username=user.username,
                email=user.email,
                plan_name=plan.name,
            )
        )
    return out


@router.get("/transactions", response_model=list[AdminTransactionOut])
def list_transactions(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AdminTransactionOut]:
    """Return up to 100 transactions with user, plan, amount, and status.

    Validates: Requirements 18.3, 18.4, 18.5
    """
    import crud

    out: list[AdminTransactionOut] = []
    for txn in crud.list_transactions(db):
        out.append(
            AdminTransactionOut(
                user=txn.user.username if txn.user else str(txn.user_id),
                plan=txn.plan.name if txn.plan else str(txn.plan_id),
                amount=txn.amount,
                status=txn.status,
            )
        )
    return out
