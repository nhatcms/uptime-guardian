"""SePay payment service: initiation and webhook confirmation.

Session-driven, HTTP-free logic for the payment lifecycle:

- :func:`initiate_payment` creates (or returns the existing) pending
  transaction for a paid plan and builds its QR reference (Requirement 13).
- :func:`apply_webhook_confirmation` matches a webhook to a pending transaction
  by reference code, verifies the amount, idempotently completes it, and
  upgrades the owner's plan (Requirement 14, 15.4, 15.6).

Webhook authenticity (signature/API key) is verified by the router via
:func:`payments.sepay.verify_webhook` before this service is invoked.

Feature: saas-multi-tenant.
Requirements traceability: 13.1, 13.3, 13.4, 13.5, 14.3-14.7, 15.4, 15.6.
"""

from __future__ import annotations

import enum
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import crud
from models import Plan, Transaction, User
from payments.sepay import generate_reference_code
from schemas import SepayWebhookIn

# Reference codes are an uppercase-alphanumeric token; used to extract a
# candidate code embedded in a longer transfer memo.
_REFERENCE_TOKEN_RE = re.compile(r"[A-Z0-9]{8,}")


class PlanNotFoundError(Exception):
    """Raised when payment initiation targets a non-existent plan (404)."""


class PlanNotPayableError(Exception):
    """Raised when payment initiation targets a free (price 0) plan (400)."""


class WebhookOutcome(enum.Enum):
    """Result of applying a webhook confirmation, mapped to HTTP by the router."""

    COMPLETED = "completed"          # pending + amount match -> upgraded (200)
    ALREADY_COMPLETED = "unchanged"  # replay of a completed tx (200)
    AMOUNT_MISMATCH = "amount"       # valid sig, wrong amount (400)
    NO_MATCH = "no_match"            # no transaction matched (404)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def initiate_payment(db: Session, user: User, plan_id: int) -> Transaction:
    """Create or return a pending transaction for ``user`` on ``plan_id``.

    Raises :class:`PlanNotFoundError` (404) for a missing plan and
    :class:`PlanNotPayableError` (400) for a free plan. When a pending
    transaction already exists for this user+plan it is returned unchanged so
    at most one pending transaction exists (Requirement 13.5).
    """
    plan = crud.get_plan(db, plan_id)
    if plan is None:
        raise PlanNotFoundError(f"plan {plan_id} not found")
    if plan.price <= 0:
        raise PlanNotPayableError(f"plan {plan_id} is not payable")

    existing = crud.get_pending_transaction(db, user.id, plan_id)
    if existing is not None:
        return existing

    # Create with a unique reference code; retry on the rare collision so the
    # uniqueness invariant (Requirement 15.5) is upheld without surfacing errors.
    for _ in range(5):
        reference = generate_reference_code(user.id, plan_id)
        try:
            return crud.create_transaction(
                db,
                user_id=user.id,
                plan_id=plan_id,
                amount=plan.price,
                reference_code=reference,
            )
        except IntegrityError:  # pragma: no cover - collision is astronomically rare
            db.rollback()
            continue
    raise RuntimeError("could not allocate a unique payment reference code")


def _match_transaction(
    db: Session, payload: SepayWebhookIn
) -> Optional[Transaction]:
    """Find the transaction referenced by the webhook payload, or ``None``.

    Tries the explicit ``code``/``referenceCode`` fields first, then extracts
    candidate reference tokens from the free-form ``content`` memo.
    """
    candidates: list[str] = []
    for field in (payload.code, payload.reference_code, payload.content):
        if field:
            candidates.append(field.strip())
    if payload.content:
        candidates.extend(_REFERENCE_TOKEN_RE.findall(payload.content.upper()))

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        txn = crud.get_transaction_by_reference(db, candidate)
        if txn is not None:
            return txn
    return None


def apply_webhook_confirmation(
    db: Session, payload: SepayWebhookIn
) -> WebhookOutcome:
    """Apply a (signature-verified) payment confirmation (Requirement 14).

    Outcomes:

    * no matching transaction        -> NO_MATCH         (404; 14.6, 15.6)
    * matched + already completed     -> ALREADY_COMPLETED (200; 14.5 idempotent)
    * matched pending, amount differs -> AMOUNT_MISMATCH  (400; 14.7, unchanged)
    * matched pending, amount equals  -> COMPLETED        (200; 14.3, 14.4)

    On COMPLETED the transaction is marked completed and the owner's plan is set
    with ``plan_expires_at = now + plan.duration_days`` (Requirement 14.4).
    """
    txn = _match_transaction(db, payload)
    if txn is None:
        return WebhookOutcome.NO_MATCH

    if txn.status == "completed":
        # Idempotent replay: leave transaction and user plan unchanged (14.5).
        return WebhookOutcome.ALREADY_COMPLETED

    if payload.transfer_amount != txn.amount:
        # Valid signature but wrong amount: change nothing (14.7).
        return WebhookOutcome.AMOUNT_MISMATCH

    # Complete the transaction and upgrade the owner's plan (14.3, 14.4).
    plan = crud.get_plan(db, txn.plan_id)
    user = db.get(User, txn.user_id)
    now = _utcnow()
    txn.status = "completed"
    if user is not None and plan is not None:
        user.plan_id = plan.id
        user.plan_expires_at = now + timedelta(days=plan.duration_days)
    db.commit()
    return WebhookOutcome.COMPLETED
