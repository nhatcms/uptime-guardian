"""Pydantic v2 schemas for the Uptime Guardian API layer.

These models define request/response shapes for the REST API. ``*Out`` schemas
set ``from_attributes=True`` so they serialize directly from ORM objects.
``MonitorCreate`` and ``MonitorUpdate`` validate that supplied URLs are proper
http/https URLs; invalid URLs raise a validation error that surfaces as HTTP
422 at the API layer (Requirement 1.2).

Requirements traceability: 1.1, 1.2, 8.2, 12.1.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
)

# Adapter used to validate that a string is a well-formed http/https URL while
# keeping the stored/serialized value as a plain ``str``.
_HTTP_URL_ADAPTER: TypeAdapter[AnyHttpUrl] = TypeAdapter(AnyHttpUrl)


def _validate_http_url(value: str) -> str:
    """Validate ``value`` is a proper http/https URL and return it as a string.

    Raises:
        ValueError: If ``value`` is not a valid http/https URL.
    """
    # Raises pydantic.ValidationError (a ValueError subclass) for bad URLs.
    _HTTP_URL_ADAPTER.validate_python(value)
    return value


class MonitorCreate(BaseModel):
    """Payload for creating a new monitor."""

    name: str = Field(min_length=1)
    url: str
    check_interval_minutes: int = Field(default=5, gt=0)

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        return _validate_http_url(value)


class MonitorUpdate(BaseModel):
    """Payload for updating an existing monitor; all fields optional."""

    name: Optional[str] = Field(default=None, min_length=1)
    url: Optional[str] = None
    is_active: Optional[bool] = None
    check_interval_minutes: Optional[int] = Field(default=None, gt=0)

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _validate_http_url(value)


class MonitorOut(BaseModel):
    """A monitor as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    url: str
    is_active: bool
    check_interval_minutes: int
    created_at: datetime
    notify_on_failure: bool


class CheckResultOut(BaseModel):
    """A single check result as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    monitor_id: int
    checked_at: datetime
    status_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    is_up: bool
    ssl_valid: Optional[bool] = None
    ssl_days_remaining: Optional[int] = None
    error_message: Optional[str] = None


class MonitorWithLatest(MonitorOut):
    """A monitor plus its most recent check result (or ``None`` if no checks)."""

    latest: Optional[CheckResultOut] = None


class StatsOut(BaseModel):
    """Aggregate statistics for a monitor over a time window."""

    model_config = ConfigDict(from_attributes=True)

    uptime_percentage: float
    avg_response_time_ms: float
    total_checks: int
    failed_checks: int
    min_response_time_ms: float
    max_response_time_ms: float


class LoginRequest(BaseModel):
    """Credentials submitted to the login endpoint, with a Turnstile token.

    ``turnstile_token`` defaults to empty so that an omitted or empty token is
    rejected by the router with HTTP 400 rather than a 422 validation error
    (Requirement 12.2).
    """

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    turnstile_token: str = ""


class TokenResponse(BaseModel):
    """Auth token issued on successful login."""

    access_token: str
    token_type: str = "bearer"


# --- Shared validators -----------------------------------------------------

# Email format: a non-empty local part and domain separated by a single "@",
# neither containing whitespace or "@" (Requirement 2.10, format local@domain).
# This is intentionally lighter than full RFC 5322 / EmailStr validation so that
# short-but-valid addresses (e.g. "a@b", the 3-char minimum of Requirement 2.3)
# are accepted while malformed values are rejected.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")

# Telegram chat id: an optional leading minus followed by one or more digits,
# 1 to 32 characters total when non-empty (Requirement 10.1).
_TELEGRAM_RE = re.compile(r"^-?\d{1,32}$")


def _validate_email(value: str) -> str:
    """Validate ``value`` matches local-part@domain and is 3-320 chars.

    Raises:
        ValueError: If the email is the wrong length or malformed.
    """
    if not (3 <= len(value) <= 320):
        raise ValueError("email must be between 3 and 320 characters")
    if not _EMAIL_RE.match(value):
        raise ValueError("email must match the format local-part@domain")
    return value


# --- Plan schemas ----------------------------------------------------------

class PlanBase(BaseModel):
    """Shared, bound-checked plan attributes (Requirements 1.1-1.6, 17.1)."""

    name: str = Field(min_length=1, max_length=100)
    # price 0.00 .. 999999.99 (Requirement 1.2).
    price: Decimal = Field(ge=Decimal("0"), le=Decimal("999999.99"))
    # Max_Monitors 1 .. 100000 on the admin create/update path (Requirement 17.1);
    # storage tolerates 0 (Requirement 1.4) but plans are only authored here.
    max_monitors: int = Field(ge=1, le=100_000)
    ssl_check_enabled: bool
    # Min_Interval_Minutes 1 .. 1440 (Requirement 1.3).
    min_interval_minutes: int = Field(ge=1, le=1440)
    # Validity in days granted on purchase; 0 for the free plan.
    duration_days: int = Field(default=0, ge=0, le=3650)


class PlanCreate(PlanBase):
    """Payload for creating a plan (Requirement 17.1)."""


class PlanUpdate(BaseModel):
    """Payload for updating a plan; all fields optional (Requirement 17.3)."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    price: Optional[Decimal] = Field(
        default=None, ge=Decimal("0"), le=Decimal("999999.99")
    )
    max_monitors: Optional[int] = Field(default=None, ge=1, le=100_000)
    ssl_check_enabled: Optional[bool] = None
    min_interval_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    duration_days: Optional[int] = Field(default=None, ge=0, le=3650)


class PlanOut(BaseModel):
    """A plan as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    price: Decimal
    max_monitors: int
    ssl_check_enabled: bool
    min_interval_minutes: int
    duration_days: int


# --- Auth schemas ----------------------------------------------------------

class RegisterRequest(BaseModel):
    """Registration payload with a Turnstile token (Requirement 11).

    ``turnstile_token`` defaults to empty so an omitted/empty token is rejected
    by the router with HTTP 400 rather than a 422 validation error (Req 11.3).
    """

    username: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1)
    turnstile_token: str = ""

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str) -> str:
        return _validate_email(value)


# --- Settings / dashboard schemas ------------------------------------------

class TelegramUpdate(BaseModel):
    """Payload to set or clear the Tenant_User's Telegram chat id.

    An empty string clears the stored value (Requirement 10.3). A non-empty
    value must be a numeric id optionally prefixed with a single minus sign and
    at most 32 characters (Requirements 10.1, 10.4).
    """

    telegram_chat_id: str = ""

    @field_validator("telegram_chat_id")
    @classmethod
    def _check_chat_id(cls, value: str) -> str:
        if value == "":
            return value
        if not _TELEGRAM_RE.match(value):
            raise ValueError(
                "telegram_chat_id must be a numeric id (optionally prefixed "
                "with '-') of at most 32 characters"
            )
        return value


class ActivePlanOut(BaseModel):
    """The Tenant_User's currently active plan limits (Requirement 21.1)."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    price: Decimal
    max_monitors: int
    min_interval_minutes: int
    ssl_check_enabled: bool
    duration_days: int


class DashboardSettingsOut(BaseModel):
    """Dashboard settings payload (Requirements 10.2, 21.1-21.4).

    Includes the requesting user's identity (username, email, is_admin) so the
    frontend can hydrate its auth profile and admin guard (Requirement 22.5)
    without a separate endpoint. Credential fields are never included.
    """

    username: str
    email: Optional[str] = None
    is_admin: bool = False
    telegram_chat_id: Optional[str] = None
    plan: ActivePlanOut
    monitors_used: int
    monitors_total: int
    plan_expires_at: Optional[datetime] = None


# --- Payment schemas -------------------------------------------------------

class PaymentInitiateRequest(BaseModel):
    """Payload to initiate a SePay payment for a selected plan."""

    plan_id: int


class PaymentInitiateOut(BaseModel):
    """Pending-transaction details and QR reference for a payment."""

    reference_code: str
    qr_url: str
    amount: Decimal
    status: str
    plan_id: int


class SepayWebhookIn(BaseModel):
    """SePay native webhook payload (Requirement 14).

    SePay sends camelCase keys; ``populate_by_name`` plus aliases let us accept
    them while exposing snake_case attributes. Only the fields needed for
    matching and amount verification are modeled; extras are ignored.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    transfer_amount: Decimal = Field(alias="transferAmount")
    # The transfer memo carries our reference code; SePay echoes it in either
    # ``content`` or ``code`` depending on configuration.
    content: Optional[str] = None
    code: Optional[str] = Field(default=None, alias="code")
    transfer_type: Optional[str] = Field(default=None, alias="transferType")
    reference_code: Optional[str] = Field(default=None, alias="referenceCode")
    gateway: Optional[str] = None


# --- Admin listing schemas -------------------------------------------------

class AdminUserOut(BaseModel):
    """A user row for the admin listing: identity + plan only, no credentials.

    Deliberately excludes ``password_hash`` and any reset token so credential
    fields can never appear in a listing response (Requirement 18.2).
    """

    username: str
    email: Optional[str] = None
    plan_name: Optional[str] = None


class AdminTransactionOut(BaseModel):
    """A transaction row for the admin listing (Requirement 18.3)."""

    user: str
    plan: str
    amount: Decimal
    status: str
