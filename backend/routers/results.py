"""Check history and statistics router for Uptime Guardian.

Exposes read-only endpoints under ``/api/results``. Every route depends on
:func:`get_current_user`, so a request without a valid Auth_Token is rejected
with HTTP 401 before any handler logic runs (Requirement 12.4).

Endpoints:

- ``GET /?monitor_id=&limit=`` returns the most recent check results for a
  monitor, newest first, up to ``limit`` records (Requirement 8.1).
- ``GET /stats?monitor_id=&hours=`` returns aggregate statistics over the last
  ``hours`` for a monitor; an empty window yields all-zero counts without error
  (Requirements 8.2, 8.3, 8.4).

``crud`` is imported lazily inside each handler so this module does not couple
to ``crud`` at import time, matching the auth router convention.

Requirements traceability: 8.1, 8.2, 8.3, 8.4, 12.4.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from schemas import CheckResultOut, StatsOut

router = APIRouter(
    prefix="/api/results",
    tags=["results"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/", response_model=list[CheckResultOut])
def list_results(
    monitor_id: int = Query(..., description="Monitor identifier"),
    limit: int = Query(100, gt=0, description="Maximum number of results"),
    db: Session = Depends(get_db),
) -> list[CheckResultOut]:
    """Return up to ``limit`` recent results for a monitor, newest first.

    Validates: Requirements 8.1
    """
    import crud  # lazy import to avoid import-order coupling

    results = crud.get_results(db, monitor_id, limit=limit)
    return [CheckResultOut.model_validate(result) for result in results]


@router.get("/stats", response_model=StatsOut)
def get_stats(
    monitor_id: int = Query(..., description="Monitor identifier"),
    hours: int = Query(24, gt=0, description="Window size in hours"),
    db: Session = Depends(get_db),
) -> StatsOut:
    """Return aggregate statistics for a monitor over the last ``hours``.

    Statistics are computed from the results within the requested window. When
    the window contains no results, all-zero values are returned without error
    (Requirement 8.4).

    Validates: Requirements 8.2, 8.3, 8.4
    """
    import crud  # lazy import to avoid import-order coupling

    results = crud.get_results_in_window(db, monitor_id, hours)
    return crud.compute_stats(results)
