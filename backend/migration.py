"""Idempotent single-user -> multi-tenant data migration (multi-tenant SaaS).

Promotes a legacy single-user NCMS Monitor database to the multi-tenant model
in one all-or-nothing transaction (Requirement 23):

1. Ensure the new ``users``/``monitors`` columns exist (idempotent
   ``ALTER TABLE ADD COLUMN`` guarded by ``PRAGMA table_info``) and that the
   ``plans``/``transactions``/``schema_migrations`` tables exist.
2. Seed the Free Plan (Requirement 23.5).
3. Promote the existing single user to ``is_admin=True`` on the Free Plan,
   copying the legacy global Telegram chat id when present (Requirements 23.2,
   23.3, 23.4).
4. Back-fill every monitor's ``user_id`` to that user without touching any
   other monitor field, including the zero-monitor case (Requirement 23.1).

A ``schema_migrations`` marker row makes the migration idempotent: a second run
makes no further changes and reports ``ALREADY_MIGRATED`` (Requirement 23.7).
Any failure rolls back the whole transaction and reports ``FAILED`` leaving all
existing data unchanged (Requirement 23.6).

Run as ``python -m migration`` to migrate the configured database.

Feature: saas-multi-tenant.
Requirements traceability: 23.1, 23.2, 23.3, 23.4, 23.5, 23.6, 23.7.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

import plans as plans_module
from models import Monitor, User

logger = logging.getLogger(__name__)

# Marker identifying this migration in the schema_migrations table.
_MIGRATION_MARKER = "saas-multi-tenant"

# New columns to add to legacy tables, as (table, column, column_definition).
_NEW_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("users", "email", "email VARCHAR"),
    ("users", "telegram_chat_id", "telegram_chat_id VARCHAR"),
    ("users", "plan_id", "plan_id INTEGER"),
    ("users", "plan_expires_at", "plan_expires_at DATETIME"),
    ("users", "is_admin", "is_admin BOOLEAN NOT NULL DEFAULT 0"),
    ("users", "created_at", "created_at DATETIME"),
    ("monitors", "user_id", "user_id INTEGER"),
)


class MigrationOutcome(enum.Enum):
    """Result of a migration attempt."""

    MIGRATED = "migrated"
    ALREADY_MIGRATED = "already_migrated"
    FAILED = "failed"


@dataclass
class MigrationResult:
    """The outcome of :func:`migrate` plus an optional error description."""

    outcome: MigrationOutcome
    error: Optional[str] = None


def _table_exists(db: Session, table: str) -> bool:
    row = db.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
        {"t": table},
    ).first()
    return row is not None


def _column_exists(db: Session, table: str, column: str) -> bool:
    if not _table_exists(db, table):
        return False
    rows = db.execute(text(f"PRAGMA table_info({table})")).all()
    return any(r[1] == column for r in rows)


def _ensure_columns(db: Session) -> None:
    """Add any missing new columns to legacy ``users``/``monitors`` tables."""
    for table, column, definition in _NEW_COLUMNS:
        if _table_exists(db, table) and not _column_exists(db, table, column):
            db.execute(text(f"ALTER TABLE {table} ADD COLUMN {definition}"))


def _ensure_marker_table(db: Session) -> None:
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "name VARCHAR PRIMARY KEY, applied_at DATETIME)"
        )
    )


def _already_migrated(db: Session) -> bool:
    _ensure_marker_table(db)
    row = db.execute(
        text("SELECT name FROM schema_migrations WHERE name=:n"),
        {"n": _MIGRATION_MARKER},
    ).first()
    return row is not None


def migrate(
    db: Session, *, global_telegram_chat_id: Optional[str] = None
) -> MigrationResult:
    """Run the idempotent single-user -> multi-tenant migration (Requirement 23).

    Returns a :class:`MigrationResult`. ``ALREADY_MIGRATED`` when the marker is
    present (no changes); ``MIGRATED`` on success; ``FAILED`` with an error
    string on any exception (the transaction is rolled back, leaving existing
    data unchanged).
    """
    # Ensure the new schema (tables + columns) exists before inspecting state.
    from database import Base  # local import to avoid import cycle

    try:
        Base.metadata.create_all(bind=db.get_bind())
        _ensure_marker_table(db)
        _ensure_columns(db)
        db.commit()
    except Exception as exc:  # pragma: no cover - schema prep failure
        db.rollback()
        logger.exception("Migration schema preparation failed")
        return MigrationResult(MigrationOutcome.FAILED, str(exc))

    if _already_migrated(db):
        return MigrationResult(MigrationOutcome.ALREADY_MIGRATED)

    try:
        # Seed the default Free Plan (Requirement 23.5).
        free_plan = plans_module.seed_free_plan(db)

        # Promote the existing single user, if any (Requirements 23.2-23.4).
        user = db.scalars(select(User).order_by(User.id)).first()
        if user is not None:
            user.is_admin = True
            if user.plan_id is None:
                user.plan_id = free_plan.id
            user.plan_expires_at = None
            if global_telegram_chat_id and global_telegram_chat_id.strip():
                user.telegram_chat_id = global_telegram_chat_id.strip()

            # Back-fill ownership of every monitor lacking an owner without
            # changing any other field (Requirement 23.1).
            db.execute(
                text(
                    "UPDATE monitors SET user_id = :uid WHERE user_id IS NULL"
                ),
                {"uid": user.id},
            )

        # Record the idempotency marker (Requirement 23.7).
        db.execute(
            text(
                "INSERT INTO schema_migrations (name, applied_at) "
                "VALUES (:n, CURRENT_TIMESTAMP)"
            ),
            {"n": _MIGRATION_MARKER},
        )
        db.commit()
        return MigrationResult(MigrationOutcome.MIGRATED)
    except Exception as exc:
        db.rollback()
        logger.exception("Migration failed; rolled back")
        return MigrationResult(MigrationOutcome.FAILED, str(exc))


def main() -> None:  # pragma: no cover - CLI entry point
    """CLI entry point: migrate the configured database."""
    logging.basicConfig(level=logging.INFO)
    from config import load_settings
    from database import SessionLocal, init_db

    init_db()
    settings = load_settings()
    db = SessionLocal()
    try:
        result = migrate(
            db, global_telegram_chat_id=settings.telegram_chat_id
        )
        logger.info("Migration outcome: %s", result.outcome.value)
        if result.error:
            logger.error("Migration error: %s", result.error)
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover
    main()
