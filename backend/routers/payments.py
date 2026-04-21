"""SePay payments router (multi-tenant SaaS).

Two endpoints under ``/api/payments``:

- ``POST /api/payments/initiate`` (JWT) creates or returns a pending
  transaction and its QR reference for a paid plan (Requirement 13).
- ``POST /api/payments/sepay-webhook`` (signature, no JWT) confirms a payment.
  This is the only endpoint not protected by JWT, so its authenticity is
  verified against the raw request body before any state change (Requirements
  14.1, 14.2) and the paid amount is matched strictly before completion.

Outcome -> HTTP mapping for the webhook: invalid signature -> 401; no matching
transaction -> 404; amount mismatch -> 400; completed/already-completed -> 200.

Feature: saas-multi-tenant.
Requirements traceability: 13.1-13.5, 14.1-14.3, 14.6, 14.7.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from database import get_db
from models import User
from payments.sepay import build_qr_reference, verify_webhook
from payments.service import (
    PlanNotFoundError,
    PlanNotPayableError,
    WebhookOutcome,
    apply_webhook_confirmation,
    initiate_payment,
)
from schemas import PaymentInitiateOut, PaymentInitiateRequest, SepayWebhookIn
from tenancy import get_current_tenant_user

router = APIRouter(prefix="/api/payments", tags=["payments"])


@router.post("/initiate", response_model=PaymentInitiateOut)
def initiate(
    payload: PaymentInitiateRequest,
    user: User = Depends(get_current_tenant_user),
    db: Session = Depends(get_db),
) -> PaymentInitiateOut:
    """Create/return a pending transaction and its QR reference (Requirement 13).

    404 when the plan does not exist; 400 when the plan is free (not payable);
    otherwise returns the (possibly pre-existing) pending transaction.

    Validates: Requirements 13.1, 13.2, 13.3, 13.4, 13.5
    """
    import crud  # lazy import to avoid import-order coupling

    try:
        txn = initiate_payment(db, user, payload.plan_id)
    except PlanNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found"
        ) from exc
    except PlanNotPayableError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Plan is not payable",
        ) from exc

    plan = crud.get_plan(db, txn.plan_id)
    qr_url = build_qr_reference(plan, txn.reference_code)
    return PaymentInitiateOut(
        reference_code=txn.reference_code,
        qr_url=qr_url,
        amount=txn.amount,
        status=txn.status,
        plan_id=txn.plan_id,
    )


@router.post("/sepay-webhook")
async def sepay_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Confirm a SePay payment (signature-verified; Requirement 14).

    The raw body is read for signature verification before parsing. An invalid
    signature is rejected with 401 and nothing is modified (Requirement 14.2).

    Validates: Requirements 14.1, 14.2, 14.3, 14.6, 14.7
    """
    raw_body = await request.body()

    if not verify_webhook(request.headers, raw_body):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    try:
        payload = SepayWebhookIn.model_validate_json(raw_body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed webhook payload",
        ) from exc

    outcome = apply_webhook_confirmation(db, payload)
    if outcome is WebhookOutcome.NO_MATCH:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No matching transaction",
        )
    if outcome is WebhookOutcome.AMOUNT_MISMATCH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Paid amount does not match the transaction amount",
        )
    # COMPLETED or ALREADY_COMPLETED -> 200.
    return {"status": "ok", "result": outcome.value}
