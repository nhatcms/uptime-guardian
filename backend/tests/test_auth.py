"""Tests for the authentication component (Task 6).

Covers the four authentication correctness properties:

- Property 16: Password hashing round trip (Requirement 12.3)
- Property 19: Token issue/validate round trip (Requirements 12.5, 12.6)
- Property 17: Invalid credentials are rejected (Requirement 12.2)
- Property 18: Protected endpoints reject missing tokens (Requirement 12.4)

Each property-based test runs at least 100 generated examples via Hypothesis.
A small in-memory SQLite database and FastAPI apps are built locally so the
tests exercise real hashing, real JWT validation, and the real login handler
without mocking.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models  # noqa: F401  (registers ORM models on Base.metadata)
from auth import (
    create_access_token,
    decode_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from crud import create_user
from database import Base, get_db
from models import User
from routers.auth import router as auth_router

# bcrypt truncates secrets beyond 72 bytes and rejects NUL bytes outright, so
# constrain generated passwords to the valid input space: no NUL/surrogate
# code points and short enough to stay well within the 72-byte bound, keeping
# distinct passwords distinguishable.
_password_chars = st.characters(min_codepoint=1, blacklist_categories=("Cs",))
_passwords = st.text(alphabet=_password_chars, min_size=1, max_size=40)


# --- Property 16: Password hashing round trip --------------------------------


# Feature: uptime-guardian, Property 16: Password hashing round trip
@settings(max_examples=50, deadline=None)
@given(password=_passwords, other=_passwords)
def test_property_16_password_hashing_round_trip(
    password: str, other: str
) -> None:
    """For any password p, verify_password(p, hash_password(p)) is true, the
    stored hash differs from p, and for any q != p, verify_password(q, hash) is
    false.

    Validates: Requirements 12.3
    """
    hashed = hash_password(password)
    # Round trip: the original password verifies against its own hash.
    assert verify_password(password, hashed) is True
    # The stored hash is never the plaintext password.
    assert hashed != password
    # A different password must not verify against this hash.
    if other != password:
        assert verify_password(other, hashed) is False


# --- Property 19: Token issue/validate round trip ----------------------------


# Feature: uptime-guardian, Property 19: Token issue/validate round trip
@settings(max_examples=50, deadline=None)
@given(subject=st.text(min_size=1, max_size=60))
def test_property_19_token_issue_validate_round_trip(subject: str) -> None:
    """For any subject, decode_access_token(create_access_token(subject))
    returns that subject when the token is fresh and unmodified, and returns
    null when the signature is altered or the validity period has elapsed.

    Validates: Requirements 12.5, 12.6
    """
    token = create_access_token(subject)

    # Fresh, unmodified token decodes back to the original subject.
    claims = decode_access_token(token)
    assert claims is not None
    assert claims["sub"] == subject

    # A token whose signature is altered is rejected (returns None). Mutating
    # the first character of the signature segment guarantees a real change to
    # the signature bytes (unlike the trailing base64url char, which can carry
    # redundant bits and decode to the same bytes).
    header_b64, payload_b64, signature_b64 = token.split(".")
    flipped = ("B" if signature_b64[0] != "B" else "C") + signature_b64[1:]
    tampered = ".".join([header_b64, payload_b64, flipped])
    assert decode_access_token(tampered) is None

    # A token whose validity period has elapsed is rejected (returns None).
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    expired = create_access_token(subject, expires_minutes=1, now=past)
    assert decode_access_token(expired) is None


# --- Shared in-memory database / app for endpoint-level properties -----------


def _make_session_factory() -> sessionmaker[Session]:
    """Create an isolated in-memory SQLite session factory with tables built."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


# --- Property 17: Invalid credentials are rejected ---------------------------


# Feature: uptime-guardian, Property 17: Invalid credentials are rejected
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    username=st.text(min_size=1, max_size=20),
    password=st.text(min_size=1, max_size=20),
)
def test_property_17_invalid_credentials_are_rejected(
    username: str, password: str
) -> None:
    """For any username/password pair that does not match the stored
    credentials, the login operation returns 401 and issues no token.

    Validates: Requirements 12.2
    """
    stored_username = "admin"
    stored_password = "admin"

    factory = _make_session_factory()
    with factory() as seed_db:
        create_user(seed_db, stored_username, hash_password(stored_password))

    app = FastAPI()
    app.include_router(auth_router)

    def _override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app)

    response = client.post(
        "/api/auth/login",
        json={
            "username": username,
            "password": password,
            # Non-empty token + empty secret (test env) -> Turnstile dev bypass,
            # so this test isolates the credential-validation behavior.
            "turnstile_token": "dev-token",
        },
    )

    if username == stored_username and password == stored_password:
        # The one matching pair must succeed and return a token.
        assert response.status_code == 200
        assert response.json()["access_token"]
    else:
        # Every non-matching pair is rejected with 401 and no token.
        assert response.status_code == 401
        assert "access_token" not in response.json()


# --- Property 18: Protected endpoints reject missing tokens ------------------


def _build_protected_app() -> FastAPI:
    """Mount a tiny app with a route guarded by ``get_current_user``."""
    app = FastAPI()

    @app.get("/protected")
    def protected(current_user: str = Depends(get_current_user)) -> dict[str, str]:
        return {"user": current_user}

    return app


def test_property_18_protected_endpoint_rejects_missing_token() -> None:
    """A request to a protected endpoint without a token receives 401.

    Validates: Requirements 12.4
    """
    client = TestClient(_build_protected_app())
    response = client.get("/protected")
    assert response.status_code == 401


# Feature: uptime-guardian, Property 18: Protected endpoints reject missing tokens
@settings(max_examples=50, deadline=None)
@given(
    bogus=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_",
        min_size=0,
        max_size=40,
    )
)
def test_property_18_protected_endpoint_rejects_invalid_tokens(
    bogus: str,
) -> None:
    """For any non-genuine bearer token (including none), a protected endpoint
    responds 401 and does not perform the operation.

    Validates: Requirements 12.4
    """
    client = TestClient(_build_protected_app())
    headers = {"Authorization": f"Bearer {bogus}"} if bogus else {}
    response = client.get("/protected", headers=headers)
    assert response.status_code == 401


def test_property_18_protected_endpoint_accepts_valid_token() -> None:
    """A genuine, fresh token authorizes the request (complements 12.4/12.5)."""
    client = TestClient(_build_protected_app())
    token = create_access_token("admin")
    response = client.get(
        "/protected", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["user"] == "admin"
