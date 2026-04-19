"""SQLAlchemy ORM models for Uptime Guardian.

Defines the ``Monitor``, ``CheckResult``, and ``User`` tables using the
SQLAlchemy 2.0 typed ``Mapped`` / ``mapped_column`` style. A ``Monitor`` owns
many ``CheckResult`` rows; deleting a monitor cascades to its results both at
the ORM level (``cascade="all, delete-orphan"``) and at the database level
(``ondelete="CASCADE"`` on the foreign key, enforced for SQLite via the
``PRAGMA foreign_keys=ON`` listener in ``database.py``).

Requirements traceability: 1.1, 1.7, 10.1.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC time (used for auto timestamps)."""
    return datetime.now(timezone.utc)


class Monitor(Base):
    """A configured monitoring target."""

    __tablename__ = "monitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
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


class User(Base):
    """The single account record used to authenticate to the system."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, index=True
    )
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
