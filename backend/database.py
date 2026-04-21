"""Database engine, session factory, and declarative base for Uptime Guardian.

Provides a synchronous SQLAlchemy 2.0 engine built from ``Settings.database_url``,
a ``SessionLocal`` sessionmaker, the declarative ``Base`` that ORM models extend,
a ``get_db`` FastAPI dependency, and ``init_db`` to create all tables.

For SQLite, foreign-key enforcement is off by default; an event listener issues
``PRAGMA foreign_keys=ON`` on every new connection so that ``ON DELETE CASCADE``
constraints are honored (Requirement 1.7). ``check_same_thread`` is disabled so
the connection may be shared across threads (FastAPI / scheduler).

Requirements traceability: 10.1.
"""

from __future__ import annotations

from typing import Any, Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry

from config import load_settings


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


def _make_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine for ``database_url``.

    SQLite connections need ``check_same_thread=False`` so the same connection
    can be used across threads, and a pragma listener to enable foreign keys.
    """
    connect_args: dict[str, Any] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    new_engine = create_engine(
        database_url,
        connect_args=connect_args,
        future=True,
    )

    if database_url.startswith("sqlite"):

        @event.listens_for(new_engine, "connect")
        def _sqlite_on_connect(
            dbapi_connection: DBAPIConnection,
            connection_record: ConnectionPoolEntry,
        ) -> None:
            """Configure each SQLite connection for the multi-tenant workload.

            - Enable ``ON DELETE CASCADE`` enforcement (Requirement 1.7 / 3.3).
            - Disable pysqlite's implicit transaction handling so SQLAlchemy
              controls ``BEGIN``; combined with the ``begin`` listener below
              this lets us emit ``BEGIN IMMEDIATE`` to serialize the
              count-then-insert monitor-creation window (Requirement 5.4).
            - Set a busy timeout so a writer waits for the reserved lock instead
              of failing immediately with "database is locked".
            """
            # Let SQLAlchemy emit BEGIN explicitly (pysqlite "autocommit"-style).
            dbapi_connection.isolation_level = None
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        @event.listens_for(new_engine, "begin")
        def _sqlite_begin_immediate(conn: Any) -> None:
            """Begin every transaction with an immediate reserved write lock.

            ``BEGIN IMMEDIATE`` acquires the reserved lock at transaction start
            so two concurrent monitor creations cannot both read ``count ==
            max - 1`` before either inserts (Requirement 5.4). Writers that find
            the lock held wait up to the configured busy timeout.
            """
            conn.exec_driver_sql("BEGIN IMMEDIATE")

    return new_engine


# Module-level settings, engine, and session factory used by the application.
settings = load_settings()
engine: Engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a session and closes it afterward."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables registered on ``Base.metadata`` if they do not exist.

    Models are imported here (not at module top level) so they register their
    mappings on ``Base.metadata`` before ``create_all`` runs, while avoiding a
    circular import between this module and ``models``.
    """
    import models  # noqa: F401  (import for side effect: registers ORM models)

    Base.metadata.create_all(bind=engine)
