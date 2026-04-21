"""Application entrypoint for Uptime Guardian.

Wires the FastAPI application together: enables CORS for the Vite dev origin,
includes the auth/monitors/results routers (each of which carries its own
``/api/...`` prefix), and manages the application lifecycle via a lifespan
context manager.

Lifecycle (Requirement 10):

- **Startup** creates the database schema with :func:`init_db`. A failure there
  is allowed to propagate so the app does not serve requests on a broken schema
  (Requirements 10.1, 10.2). After the tables exist, the two example monitors
  and the default admin user are seeded idempotently (Requirements 10.3, 10.4),
  and the scheduler is started (Requirement 4.1).
- **Shutdown** stops the scheduler and its jobs (Requirement 10.5).

Requirements traceability: 1.1, 8.1, 10.1, 10.2, 10.3, 10.4, 10.5, 12.1.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Final

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

import crud
import scheduler
from auth import hash_password
from config import load_settings
from database import SessionLocal, get_db, init_db
from routers.admin import router as admin_router
from routers.auth import router as auth_router
from routers.monitors import router as monitors_router
from routers.payments import router as payments_router
from routers.results import router as results_router
from routers.settings import router as settings_router
from schemas import PlanOut

logger = logging.getLogger(__name__)

# Default first-run admin credentials (Requirement 10.4). The spec mandates a
# seeded "admin"/"admin" account; the password is stored only as a bcrypt hash,
# never in plaintext. These are intentional MVP defaults, not a hardcoded
# secret, and are expected to be changed by the operator after first login.
_DEFAULT_ADMIN_USERNAME: Final[str] = "admin"
_DEFAULT_ADMIN_PASSWORD: Final[str] = "admin"


def _seed_initial_data() -> None:
    """Seed the example monitors and the admin user on first run.

    Both seeding operations are idempotent: they insert only when their table
    is empty, so repeated startups never create duplicates (Requirements 10.3,
    10.4). A fresh session is used and always closed.
    """
    db = SessionLocal()
    try:
        admin = crud.seed_admin_user(
            db,
            _DEFAULT_ADMIN_USERNAME,
            hash_password(_DEFAULT_ADMIN_PASSWORD),
        )
        # Seed the example monitors owned by the admin user so every monitor
        # has an owner (Requirement 3.1). Ordering matters: the admin must
        # exist before its monitors are created.
        crud.seed_default_monitors(db, admin.id)
    finally:
        db.close()


def _run_migration() -> None:
    """Run the idempotent single-user -> multi-tenant migration at startup.

    Reads the legacy global Telegram chat id from ``Settings.telegram_chat_id``
    and logs the resulting :class:`MigrationOutcome` (Requirements 23.5, 23.7).
    """
    import migration

    settings = load_settings()
    db = SessionLocal()
    try:
        result = migration.migrate(
            db, global_telegram_chat_id=settings.telegram_chat_id
        )
        logger.info("Data migration outcome: %s", result.outcome.value)
        if result.error:
            logger.error("Data migration error: %s", result.error)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown for the application.

    On startup: create tables (propagating failures so a broken schema halts
    startup), seed initial data, and start the scheduler. On shutdown: stop the
    scheduler.
    """
    # Create the schema. If this raises, the exception propagates and startup
    # halts so the app never serves on a broken schema (Requirements 10.1, 10.2).
    init_db()

    # Promote any legacy single-user database to the multi-tenant model
    # (Requirement 23). Idempotent: a no-op on already-migrated or fresh DBs.
    _run_migration()

    # Seed example monitors and the admin user (idempotent; Requirements 10.3, 10.4).
    _seed_initial_data()

    # Start scheduled polling (Requirement 4.1).
    scheduler.start()
    logger.info("Uptime Guardian started: schema ready, data seeded, scheduler running")

    try:
        yield
    finally:
        # Stop all scheduled jobs on shutdown (Requirement 10.5).
        scheduler.shutdown()
        logger.info("Uptime Guardian stopped: scheduler shut down")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance."""
    app = FastAPI(title="Uptime Guardian", lifespan=lifespan)

    # Allow the Vue dashboard to call the API with credentials. Origins are
    # configurable via CORS_ALLOW_ORIGINS in .env so the dashboard can be
    # reached over the LAN by IP, not just localhost (Requirement 12.1 / design
    # CORS). Setting CORS_ALLOW_ORIGINS="*" permits any origin; because
    # credentials are allowed, that case is implemented with an
    # allow-any-origin regex (the "*" literal is invalid with credentials).
    settings = load_settings()
    if settings.cors_allow_all:
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=".*",
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Routers already carry their own /api/... prefixes.
    app.include_router(auth_router)
    app.include_router(monitors_router)
    app.include_router(results_router)
    app.include_router(settings_router)
    app.include_router(payments_router)
    app.include_router(admin_router)

    @app.get("/api/plans", response_model=list[PlanOut], tags=["plans"])
    def list_public_plans(db=Depends(get_db)) -> list[PlanOut]:
        """Public pricing endpoint for the landing page (Requirement 19.1).

        Returns all plans (empty list if none); requires no authentication.
        """
        return [PlanOut.model_validate(p) for p in crud.get_plans(db)]

    return app


app = create_app()
