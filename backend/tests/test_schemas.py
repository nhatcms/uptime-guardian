"""Unit tests for multi-tenant schema field validators (Task 1.5).

Covers the email-format rule on ``RegisterRequest`` (Requirement 2.10) and the
Telegram_Chat_Id format/length rules on ``TelegramUpdate`` (Requirements 10.1,
10.4): an empty value clears the stored id, while a non-empty value must be a
numeric id optionally prefixed with a single minus sign and at most 32 chars.

Feature: saas-multi-tenant
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas import RegisterRequest, TelegramUpdate


# --- Email format (Requirement 2.10) ---------------------------------------

@pytest.mark.parametrize(
    "email",
    [
        "a@b",  # 3-char minimum still matches local-part@domain
        "user@example.com",
        "first.last@sub.domain.example.com",
        "user+tag@example.org",
    ],
)
def test_register_accepts_valid_emails(email: str) -> None:
    """Well-formed local-part@domain addresses are accepted (Requirement 2.10)."""
    req = RegisterRequest(
        username="alice", email=email, password="pw", turnstile_token="t"
    )
    assert req.email == email


@pytest.mark.parametrize(
    "email",
    [
        "no-at-sign",          # missing "@"
        "@nodomain",           # empty local part
        "nolocal@",            # empty domain
        "two@@example.com",    # malformed
        "has space@example.com",
        "a@",                  # too short / empty domain
    ],
)
def test_register_rejects_malformed_emails(email: str) -> None:
    """Malformed emails raise a validation error naming the email field."""
    with pytest.raises(ValidationError) as exc_info:
        RegisterRequest(
            username="alice", email=email, password="pw", turnstile_token="t"
        )
    assert "email" in {str(e["loc"][-1]) for e in exc_info.value.errors()}


def test_register_rejects_overlong_email() -> None:
    """An email longer than 320 characters is rejected (Requirement 2.3)."""
    long_email = "a" * 320 + "@example.com"
    with pytest.raises(ValidationError):
        RegisterRequest(
            username="alice",
            email=long_email,
            password="pw",
            turnstile_token="t",
        )


# --- Telegram chat id (Requirements 10.1, 10.4) ----------------------------

def test_telegram_empty_value_is_allowed_to_clear() -> None:
    """An empty Telegram_Chat_Id is accepted and clears the value (Req 10.3)."""
    assert TelegramUpdate(telegram_chat_id="").telegram_chat_id == ""
    # Default (omitted) is also empty.
    assert TelegramUpdate().telegram_chat_id == ""


@pytest.mark.parametrize(
    "chat_id",
    [
        "123",
        "-1001234567890",
        "0",
        "1" * 32,        # exactly 32 chars allowed
        "-" + "1" * 31,  # minus + 31 digits == 32 chars
    ],
)
def test_telegram_accepts_valid_ids(chat_id: str) -> None:
    """Numeric ids (optionally minus-prefixed), 1-32 chars, are accepted."""
    assert TelegramUpdate(telegram_chat_id=chat_id).telegram_chat_id == chat_id


@pytest.mark.parametrize(
    "chat_id",
    [
        "abc",            # non-numeric
        "12.5",           # not an integer id
        "1" * 33,         # 33 digits exceeds 32-char limit
        "--1",            # double minus
        "1-2",            # minus not at the start
        " 123",           # leading whitespace
        "+123",           # plus sign not permitted
    ],
)
def test_telegram_rejects_invalid_ids(chat_id: str) -> None:
    """Non-numeric, malformed, or overlong ids raise a validation error."""
    with pytest.raises(ValidationError):
        TelegramUpdate(telegram_chat_id=chat_id)
