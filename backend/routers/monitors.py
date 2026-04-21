"""Monitor management router (multi-tenant SaaS).

CRUD plus an on-demand check under ``/api/monitors``, scoped to the
authenticated Tenant_User. Every route resolves the owner via
:func:`get_current_tenant_user` (401 when unauthenticated). Reads/updates/deletes
are restricted to monitors the user owns, returning an identical 404 for
cross-tenant and nonexistent monitors (Requirements 4.4, 4.5, 4.7). Creation
sets the owner from the authenticated user (Requirement 3.2) and enforces the
active plan's monitor-count limit and interval floor (Requirements 5, 6).

Plan-limit / interval / no-plan failures map to 403; an invalid interval value
maps to 400; cross-tenant / missing map to 404.

Feature: saas-multi-tenant.
Requirements traceability: 3.2, 4.1-4.5, 4.7, 5.1-5.3, 6.1-6.6, 12.4.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from checker import check_monitor
from database import get_db
from models import Monitor, User
from plans import (
    IntervalTooLowError,
    InvalidIntervalError,
    NoActivePlanError,
    PlanLimitError,
    enforce_can_create_monitor,
    enforce_interval_for_update,
)
from schemas import (
    CheckResultOut,
    MonitorCreate,
    MonitorOut,
    MonitorUpdate,
    MonitorWithLatest,
)
from tenancy import get_current_tenant_user, get_owned_monitor_or_404

# Number of most recent check results embedded in the single-monitor detail
# response (Requirement 1.4 / design endpoint table).
_DETAIL_RESULT_LIMIT: int = 50


class MonitorDetail(MonitorWithLatest):
    """A monitor with its latest result and its 50 most recent results."""

    results: list[CheckResultOut] = []


router = APIRouter(prefix="/api/monitors", tags=["monitors"])


def _to_with_latest(db: Session, monitor: Monitor) -> MonitorWithLatest:
    """Serialize ``monitor`` as a :class:`MonitorWithLatest` with its latest result."""
    import crud  # lazy import to avoid import-order coupling

    payload = MonitorWithLatest.model_validate(monitor)
    latest = crud.get_latest_result(db, monitor.id)
    payload.latest = (
        CheckResultOut.model_validate(latest) if latest is not None else None
    )
    return payload


@router.get("/", response_model=list[MonitorWithLatest])
def list_monitors(
    user: User = Depends(get_current_tenant_user),
    db: Session = Depends(get_db),
) -> list[MonitorWithLatest]:
    """Return the authenticated user's monitors, each with its latest result.

    Validates: Requirements 4.1, 4.2
    """
    import crud  # lazy import to avoid import-order coupling

    monitors = crud.get_monitors_for_user(db, user.id)
    return [_to_with_latest(db, monitor) for monitor in monitors]


@router.post(
    "/", response_model=MonitorWithLatest, status_code=status.HTTP_201_CREATED
)
async def create_monitor(
    payload: MonitorCreate,
    user: User = Depends(get_current_tenant_user),
    db: Session = Depends(get_db),
) -> MonitorWithLatest:
    """Create a monitor owned by the authenticated user (Requirements 3.2, 5, 6).

    Enforces the active plan's monitor-count limit and interval floor before
    persisting. The count check and the insert run in the same write-locked
    transaction so the limit holds under concurrency (Requirement 5.4).

    Validates: Requirements 3.2, 4.3, 4.5, 5.1, 5.2, 5.3, 6.1, 6.2, 6.6
    """
    import crud  # lazy import to avoid import-order coupling

    try:
        enforce_can_create_monitor(db, user, payload.check_interval_minutes)
    except InvalidIntervalError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except PlanLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Monitor limit reached for your plan "
                f"(maximum {exc.max_monitors})"
            ),
        ) from exc
    except IntervalTooLowError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except NoActivePlanError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active plan is in effect for your account",
        ) from exc

    try:
        monitor = crud.create_monitor(db, payload, user.id)
    except Exception as exc:  # persistence failure -> 500
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist monitor",
        ) from exc

    # Immediate first check so the new monitor reports a status right away.
    try:
        result = await check_monitor(monitor)
        crud.create_check_result(
            db,
            monitor.id,
            is_up=result.is_up,
            status_code=result.status_code,
            response_time_ms=result.response_time_ms,
            ssl_valid=result.ssl_valid,
            ssl_days_remaining=result.ssl_days_remaining,
            error_message=result.error_message,
        )
    except Exception:  # an initial-check failure must not fail creation
        db.rollback()

    if monitor.is_active:
        try:
            import scheduler

            scheduler.register_monitor(monitor)
        except Exception:
            pass

    return _to_with_latest(db, monitor)


@router.get("/{monitor_id}", response_model=MonitorDetail)
def get_monitor(
    monitor_id: int,
    user: User = Depends(get_current_tenant_user),
    db: Session = Depends(get_db),
) -> MonitorDetail:
    """Return one owned monitor with its recent results, or 404.

    Validates: Requirements 4.3, 4.4, 4.5
    """
    import crud  # lazy import to avoid import-order coupling

    monitor = get_owned_monitor_or_404(db, user, monitor_id)
    payload = MonitorDetail.model_validate(monitor)
    latest = crud.get_latest_result(db, monitor.id)
    payload.latest = (
        CheckResultOut.model_validate(latest) if latest is not None else None
    )
    recent = crud.get_results(db, monitor.id, limit=_DETAIL_RESULT_LIMIT)
    payload.results = [CheckResultOut.model_validate(r) for r in recent]
    return payload


@router.put("/{monitor_id}", response_model=MonitorOut)
def update_monitor(
    monitor_id: int,
    payload: MonitorUpdate,
    user: User = Depends(get_current_tenant_user),
    db: Session = Depends(get_db),
) -> MonitorOut:
    """Update an owned monitor, enforcing the interval floor, or 404.

    A requested interval below the active plan minimum is rejected with 403 and
    the stored interval is left unchanged (Requirements 6.3, 6.4).

    Validates: Requirements 4.7, 6.3, 6.4, 6.5, 6.6
    """
    import crud  # lazy import to avoid import-order coupling

    # Ownership first: cross-tenant / missing is an identical 404.
    get_owned_monitor_or_404(db, user, monitor_id)

    if payload.check_interval_minutes is not None:
        try:
            enforce_interval_for_update(db, user, payload.check_interval_minutes)
        except InvalidIntervalError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        except IntervalTooLowError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
            ) from exc
        except NoActivePlanError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No active plan is in effect for your account",
            ) from exc

    monitor = crud.update_owned_monitor(db, user.id, monitor_id, payload)
    if monitor is None:  # pragma: no cover - guarded by the 404 check above
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found"
        )
    return MonitorOut.model_validate(monitor)


@router.delete("/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_monitor(
    monitor_id: int,
    user: User = Depends(get_current_tenant_user),
    db: Session = Depends(get_db),
) -> Response:
    """Delete an owned monitor and its results, or 404.

    Validates: Requirements 4.7
    """
    import crud  # lazy import to avoid import-order coupling

    deleted = crud.delete_owned_monitor(db, user.id, monitor_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{monitor_id}/check-now", response_model=CheckResultOut)
async def check_now(
    monitor_id: int,
    user: User = Depends(get_current_tenant_user),
    db: Session = Depends(get_db),
) -> CheckResultOut:
    """Trigger an immediate check for an owned monitor and persist the result.

    Validates: Requirements 4.4, 4.5
    """
    import crud  # lazy import to avoid import-order coupling

    monitor = get_owned_monitor_or_404(db, user, monitor_id)
    result = await check_monitor(monitor)
    saved = crud.create_check_result(
        db,
        monitor.id,
        is_up=result.is_up,
        status_code=result.status_code,
        response_time_ms=result.response_time_ms,
        ssl_valid=result.ssl_valid,
        ssl_days_remaining=result.ssl_days_remaining,
        error_message=result.error_message,
    )
    return CheckResultOut.model_validate(saved)
