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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import crud
import scheduler
from auth import hash_password
from config import load_settings
from database import SessionLocal, init_db
from routers.auth import router as auth_router
from routers.monitors import router as monitors_router
from routers.results import router as results_router

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
        crud.seed_default_monitors(db)
        crud.seed_admin_user(
            db,
            _DEFAULT_ADMIN_USERNAME,
            hash_password(_DEFAULT_ADMIN_PASSWORD),
        )
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

    # Routers already carry their own /api/auth, /api/monitors, /api/results
    # prefixes (Requirements 1.1, 8.1, 12.1).
    app.include_router(auth_router)
    app.include_router(monitors_router)
    app.include_router(results_router)

    return app


app = create_app()
