"""SQLAlchemy ORM models for the multi-tenant NCMS Monitor platform.

Defines the ``Plan``, ``User`` (Tenant_User), ``Monitor``, ``CheckResult``, and
``Transaction`` tables using the SQLAlchemy 2.0 typed ``Mapped`` /
``mapped_column`` style.

Ownership and cascade behavior:

- A ``User`` owns many ``Monitor`` rows via the non-null ``Monitor.user_id``
  foreign key, which carries ``ON DELETE CASCADE`` so deleting a user removes
  its monitors (Requirement 3.1, 3.3).
- A ``Monitor`` owns many ``CheckResult`` rows; deleting a monitor cascades to
  its results both at the ORM level (``cascade="all, delete-orphan"``) and at
  the database level (``ondelete="CASCADE"``), enforced for SQLite via the
  ``PRAGMA foreign_keys=ON`` listener in ``database.py``.
- A ``User`` subscribes to a ``Plan`` via the nullable ``User.plan_id`` foreign
  key (``ON DELETE SET NULL`` so plan deletion never deletes users).
- ``Transaction`` rows reference ``user_id``/``plan_id`` for audit reporting and
  are not cascaded by user deletion.

Requirements traceability: 1.1-1.6, 2.1, 2.6-2.8, 3.1, 15.1-15.3, 15.5.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC time (used for auto timestamps)."""
    return datetime.now(timezone.utc)


class Plan(Base):
    """A subscription tier defining price and per-user feature limits.

    ``name`` carries a database-level unique constraint; case-insensitive
    uniqueness (Requirement 1.6) is additionally enforced at the application
    layer. ``duration_days`` is the validity granted when the plan is purchased
    (0 for the free plan, which never expires).
    """

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, index=True
    )
    # price 0..999999.99 (Requirement 1.2): 6 integer digits + 2 decimals.
    price: Mapped[Decimal] = mapped_column(
        Numeric(precision=8, scale=2), nullable=False, default=Decimal("0")
    )
    max_monitors: Mapped[int] = mapped_column(Integer, nullable=False)
    ssl_check_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    min_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    subscribers: Mapped[List["User"]] = relationship(
        "User", back_populates="plan"
    )


class User(Base):
    """A Tenant_User: an isolated account owning monitors and a subscription."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, index=True
    )
    # email is nullable at the column level so that an existing single-user
    # database can be migrated before an address is supplied; uniqueness is
    # enforced via the unique index (SQLite permits multiple NULLs).
    email: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, unique=True, index=True
    )
    # Nullable because accounts created purely via Google OAuth have no local
    # password; password login is simply unavailable for those users until they
    # set one. Local (form) accounts always carry a bcrypt hash here.
    password_hash: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    # --- Google OAuth identity fields -------------------------------------
    # The Google account's stable subject identifier ("sub" claim). Unique and
    # nullable: NULL for accounts that have never signed in with Google.
    google_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, unique=True, index=True
    )
    # Profile picture URL provided by Google (or set elsewhere); optional.
    avatar_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # True once the email has been verified — always true for Google logins
    # because Google has already verified the address.
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    plan_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("plans.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    plan_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    plan: Mapped[Optional["Plan"]] = relationship(
        "Plan", back_populates="subscribers"
    )
    monitors: Mapped[List["Monitor"]] = relationship(
        "Monitor",
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Monitor(Base):
    """A configured monitoring target owned by exactly one Tenant_User."""

    __tablename__ = "monitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    check_interval_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    notify_on_failure: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    owner: Mapped["User"] = relationship("User", back_populates="monitors")
    results: Mapped[List["CheckResult"]] = relationship(
        "CheckResult",
        back_populates="monitor",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class CheckResult(Base):
    """A persisted record of a single check for a monitor."""

    __tablename__ = "check_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_time_ms: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    is_up: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ssl_valid: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    ssl_days_remaining: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    monitor: Mapped["Monitor"] = relationship(
        "Monitor", back_populates="results"
    )


class Transaction(Base):
    """A persisted SePay payment attempt/confirmation for a plan upgrade.

    ``reference_code`` is the unique payment reference encoded into the QR and
    echoed back by SePay's webhook; its uniqueness (Requirement 15.5) is backed
    by the database unique constraint. ``status`` is one of ``pending``,
    ``completed``, or ``failed`` (Requirement 15.3).
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    plan_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("plans.id"), nullable=False, index=True
    )
    # amount 0.01..999999999.99 (Requirement 15.2): up to 9 integer digits.
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", index=True
    )
    reference_code: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

    user: Mapped["User"] = relationship("User")
    plan: Mapped["Plan"] = relationship("Plan")
