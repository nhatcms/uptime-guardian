"""Check history and statistics router (multi-tenant SaaS).

Read-only endpoints under ``/api/results``, scoped to the authenticated
Tenant_User's monitors. Requesting results/stats for a monitor owned by another
tenant (or one that does not exist) yields an identical 404 with no data
(Requirements 4.6, 4.7). Unauthenticated requests are rejected with 401.

Feature: saas-multi-tenant.
Requirements traceability: 4.6, 4.7, 8.1, 8.2, 8.3, 8.4, 12.4.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas import CheckResultOut, StatsOut
from tenancy import get_current_tenant_user, get_owned_monitor_or_404

router = APIRouter(prefix="/api/results", tags=["results"])


@router.get("/", response_model=list[CheckResultOut])
def list_results(
    monitor_id: int = Query(..., description="Monitor identifier"),
    limit: int = Query(100, gt=0, description="Maximum number of results"),
    user: User = Depends(get_current_tenant_user),
    db: Session = Depends(get_db),
) -> list[CheckResultOut]:
    """Return up to ``limit`` recent results for an owned monitor, newest first.

    Validates: Requirements 4.6, 4.7, 8.1
    """
    import crud  # lazy import to avoid import-order coupling

    get_owned_monitor_or_404(db, user, monitor_id)
    results = crud.get_results(db, monitor_id, limit=limit)
    return [CheckResultOut.model_validate(result) for result in results]


@router.get("/stats", response_model=StatsOut)
def get_stats(
    monitor_id: int = Query(..., description="Monitor identifier"),
    hours: int = Query(24, gt=0, description="Window size in hours"),
    user: User = Depends(get_current_tenant_user),
    db: Session = Depends(get_db),
) -> StatsOut:
    """Return aggregate statistics for an owned monitor over the last ``hours``.

    Validates: Requirements 4.6, 4.7, 8.2, 8.3, 8.4
    """
    import crud  # lazy import to avoid import-order coupling

    get_owned_monitor_or_404(db, user, monitor_id)
    results = crud.get_results_in_window(db, monitor_id, hours)
    return crud.compute_stats(results)
