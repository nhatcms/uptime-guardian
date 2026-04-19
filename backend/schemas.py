"""Pydantic v2 schemas for the Uptime Guardian API layer.

These models define request/response shapes for the REST API. ``*Out`` schemas
set ``from_attributes=True`` so they serialize directly from ORM objects.
``MonitorCreate`` and ``MonitorUpdate`` validate that supplied URLs are proper
http/https URLs; invalid URLs raise a validation error that surfaces as HTTP
422 at the API layer (Requirement 1.2).

Requirements traceability: 1.1, 1.2, 8.2, 12.1.
"""

from __future__ import annotations

from datetime import datetime
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
    """Credentials submitted to the login endpoint."""

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    """Auth token issued on successful login."""

    access_token: str
    token_type: str = "bearer"
