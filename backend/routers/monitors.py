"""Monitor management router for Uptime Guardian.

Exposes CRUD and an on-demand check endpoint under ``/api/monitors``. Every
route depends on :func:`get_current_user`, so a request without a valid
Auth_Token is rejected with HTTP 401 before any handler logic runs
(Requirements 12.4, 12.5).

Endpoints:

- ``GET /`` lists all monitors, each with its latest check result embedded
  (Requirement 1.3).
- ``POST /`` creates a monitor and returns 201; an invalid URL surfaces as 422
  via the ``MonitorCreate`` schema validation (Requirements 1.1, 1.2); a
  persistence failure surfaces as 500 (Requirement 1.3 / error handling).
- ``GET /{id}`` returns a monitor with its latest result embedded, or 404 when
  the monitor does not exist (Requirements 1.4, 1.5).
- ``PUT /{id}`` applies updates and returns the updated monitor, or 404
  (Requirement 1.6).
- ``DELETE /{id}`` deletes the monitor and its results, returning 204, or 404
  (Requirement 1.7).
- ``POST /{id}/check-now`` triggers an immediate check, persists the result,
  and returns it, or 404 (Requirement 4.5).

``crud`` is imported lazily inside each handler so this module does not couple
to ``crud`` at import time, matching the auth router convention.

Requirements traceability: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 4.5, 12.4, 12.5.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from auth import get_current_user
from checker import check_monitor
from database import get_db
from models import Monitor
from schemas import (
    CheckResultOut,
    MonitorCreate,
    MonitorOut,
    MonitorUpdate,
    MonitorWithLatest,
)

# Number of most recent check results embedded in the single-monitor detail
# response (Requirement 1.4 / design endpoint table).
_DETAIL_RESULT_LIMIT: int = 50


class MonitorDetail(MonitorWithLatest):
    """A monitor with its latest result and its 50 most recent results.

    Returned by ``GET /{id}`` so the detail view receives the monitor, the
    embedded latest result, and the recent check history in a single response
    (Requirement 1.4, design endpoint table "Monitor + last 50 results").
    """

    results: list[CheckResultOut] = []

router = APIRouter(
    prefix="/api/monitors",
    tags=["monitors"],
    dependencies=[Depends(get_current_user)],
)


def _to_with_latest(db: Session, monitor: Monitor) -> MonitorWithLatest:
    """Serialize ``monitor`` as a :class:`MonitorWithLatest` with its latest result.

    Reads the most recent check result for the monitor (or ``None`` when the
    monitor has never been checked) and embeds it in the response model
    (Requirements 1.3, 1.4).
    """
    import crud  # lazy import to avoid import-order coupling

    payload = MonitorWithLatest.model_validate(monitor)
    latest = crud.get_latest_result(db, monitor.id)
    payload.latest = (
        CheckResultOut.model_validate(latest) if latest is not None else None
    )
    return payload


@router.get("/", response_model=list[MonitorWithLatest])
def list_monitors(db: Session = Depends(get_db)) -> list[MonitorWithLatest]:
    """Return all monitors, each with its latest check result embedded.

    Validates: Requirements 1.3
    """
    import crud  # lazy import to avoid import-order coupling

    monitors = crud.get_monitors(db)
    return [_to_with_latest(db, monitor) for monitor in monitors]


@router.post(
    "/", response_model=MonitorWithLatest, status_code=status.HTTP_201_CREATED
)
async def create_monitor(
    payload: MonitorCreate,
    db: Session = Depends(get_db),
) -> MonitorWithLatest:
    """Create a new monitor, check it immediately, and return it with HTTP 201.

    The ``MonitorCreate`` schema validates the URL, so a malformed URL is
    rejected with HTTP 422 before this handler runs (Requirement 1.2). A
    database error during persistence is caught and surfaced as HTTP 500
    (Requirement 1.3 error handling).

    After persisting the monitor, an immediate check is run and its result is
    saved so the very first status is reported right away rather than waiting
    for the first scheduled poll (Requirement 4.5). The monitor is also
    registered with the scheduler so recurring checks begin without a restart
    (Requirement 4.3). The created monitor is returned with its latest result
    embedded.

    Validates: Requirements 1.1, 1.2, 4.3, 4.5
    """
    import crud  # lazy import to avoid import-order coupling

    try:
        monitor = crud.create_monitor(db, payload)
    except Exception as exc:  # persistence failure -> 500
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist monitor",
        ) from exc

    # Run an immediate check so the new monitor reports a result right away
    # instead of staying "pending" until the first scheduled poll.
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

    # Register the monitor with the scheduler so recurring checks begin without
    # requiring an application restart (Requirement 4.3).
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
    db: Session = Depends(get_db),
) -> MonitorDetail:
    """Return a single monitor with its 50 most recent results, or 404.

    Embeds the latest check result and the 50 most recent check results
    (newest first) for the monitor, or responds with HTTP 404 when no monitor
    with ``monitor_id`` exists (Requirements 1.4, 1.5).

    Validates: Requirements 1.4, 1.5
    """
    import crud  # lazy import to avoid import-order coupling

    monitor = crud.get_monitor(db, monitor_id)
    if monitor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found"
        )

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
    db: Session = Depends(get_db),
) -> MonitorOut:
    """Apply updates to an existing monitor and return it, or 404 if missing.

    Validates: Requirements 1.6
    """
    import crud  # lazy import to avoid import-order coupling

    monitor = crud.update_monitor(db, monitor_id, payload)
    if monitor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found"
        )
    return MonitorOut.model_validate(monitor)


@router.delete("/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_monitor(
    monitor_id: int,
    db: Session = Depends(get_db),
) -> Response:
    """Delete a monitor and all of its results, or 404 if missing.

    Validates: Requirements 1.7
    """
    import crud  # lazy import to avoid import-order coupling

    deleted = crud.delete_monitor(db, monitor_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{monitor_id}/check-now", response_model=CheckResultOut)
async def check_now(
    monitor_id: int,
    db: Session = Depends(get_db),
) -> CheckResultOut:
    """Trigger an immediate check for a monitor and persist the result.

    Returns the persisted :class:`CheckResultOut`, or HTTP 404 when the monitor
    does not exist. The check itself is performed by :func:`check_monitor`
    (which never raises for transport failures) and the resulting unsaved
    record is persisted via ``crud.create_check_result`` (Requirement 4.5).

    Validates: Requirements 4.5
    """
    import crud  # lazy import to avoid import-order coupling

    monitor = crud.get_monitor(db, monitor_id)
    if monitor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found"
        )

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
