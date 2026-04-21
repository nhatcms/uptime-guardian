"""Shared test helpers for building a full multi-tenant API app in tests.

Not a test module (no ``test_`` prefix), so pytest does not collect it. Provides
an in-memory session factory, a full FastAPI app mounting every router plus the
public ``/api/plans`` endpoint, and small auth helpers.

Feature: saas-multi-tenant.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterator, Optional

from fastapi import Depends, FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models  # noqa: F401  (registers ORM models)
import plans as plans_module
from auth import create_access_token, hash_password
from database import Base, get_db
from models import Plan, User
from schemas import PlanOut


def make_factory() -> sessionmaker:
    """Create an isolated in-memory SQLite session factory with tables built."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def build_full_app(factory: sessionmaker) -> FastAPI:
    """Build a FastAPI app mounting all routers, with ``get_db`` overridden."""
    from routers.admin import router as admin_router
    from routers.auth import router as auth_router
    from routers.monitors import router as monitors_router
    from routers.payments import router as payments_router
    from routers.results import router as results_router
    from routers.settings import router as settings_router

    import crud

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(monitors_router)
    app.include_router(results_router)
    app.include_router(settings_router)
    app.include_router(payments_router)
    app.include_router(admin_router)

    @app.get("/api/plans", response_model=list[PlanOut])
    def _public_plans(db: Session = Depends(get_db)) -> list[PlanOut]:
        return [PlanOut.model_validate(p) for p in crud.get_plans(db)]

    def _override_get_db() -> Iterator[Session]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    return app


def seed_free_plan(factory: sessionmaker) -> int:
    """Seed the Free Plan and return its id."""
    with factory() as db:
        plan = plans_module.seed_free_plan(db)
        return plan.id


def add_paid_plan(
    factory: sessionmaker,
    *,
    name: str = "Pro",
    price: Decimal = Decimal("100000.00"),
    max_monitors: int = 10,
    ssl: bool = True,
    min_interval: int = 1,
    duration_days: int = 30,
) -> int:
    """Create a paid plan and return its id."""
    with factory() as db:
        plan = Plan(
            name=name,
            price=price,
            max_monitors=max_monitors,
            ssl_check_enabled=ssl,
            min_interval_minutes=min_interval,
            duration_days=duration_days,
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)
        return plan.id


def add_user(
    factory: sessionmaker,
    *,
    username: str,
    is_admin: bool = False,
    plan_id: Optional[int] = None,
    password: str = "pw",
    email: Optional[str] = None,
) -> int:
    """Create a user and return its id."""
    with factory() as db:
        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            is_admin=is_admin,
            plan_id=plan_id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id


def auth_header(username: str) -> dict[str, str]:
    """Return an Authorization header carrying a genuine token for ``username``."""
    return {"Authorization": f"Bearer {create_access_token(username)}"}
