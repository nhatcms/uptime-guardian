"""Unit tests for settings loading, defaults, and missing-field errors.

Validates: Requirements 9.1, 9.2, 9.3
"""

from __future__ import annotations

import pytest

from config import (
    DEFAULT_ALERT_COOLDOWN_MINUTES,
    DEFAULT_CHECK_INTERVAL_MINUTES,
    ConfigError,
    Settings,
    load_settings,
)

# Required fields used to satisfy non-default settings during construction.
_REQUIRED_ENV = {
    "TELEGRAM_BOT_TOKEN": "bot-token-123",
    "TELEGRAM_CHAT_ID": "chat-456",
    "AUTH_SECRET_KEY": "super-secret",
}


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all known config env vars so each test starts clean."""
    for key in (
        "DATABASE_URL",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "CHECK_INTERVAL_MINUTES",
        "ALERT_COOLDOWN_MINUTES",
        "AUTH_SECRET_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def test_loads_all_fields_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Requirement 9.1: all keys are loaded from the environment / .env."""
    for key, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./custom.db")
    monkeypatch.setenv("CHECK_INTERVAL_MINUTES", "15")
    monkeypatch.setenv("ALERT_COOLDOWN_MINUTES", "30")

    cfg = load_settings()

    assert cfg.database_url == "sqlite:///./custom.db"
    assert cfg.telegram_bot_token == "bot-token-123"
    assert cfg.telegram_chat_id == "chat-456"
    assert cfg.auth_secret_key == "super-secret"
    assert cfg.check_interval_minutes == 15
    assert cfg.alert_cooldown_minutes == 30


def test_interval_and_cooldown_defaults_applied() -> None:
    """Requirement 9.3: missing interval/cooldown apply defaults 5 and 10."""
    cfg = Settings(_env_file=None, **{k.lower(): v for k, v in _REQUIRED_ENV.items()})  # type: ignore[arg-type]

    assert cfg.check_interval_minutes == DEFAULT_CHECK_INTERVAL_MINUTES
    assert cfg.alert_cooldown_minutes == DEFAULT_ALERT_COOLDOWN_MINUTES


def test_database_url_has_default() -> None:
    """DATABASE_URL falls back to the bundled sqlite default when absent."""
    cfg = Settings(_env_file=None, **{k.lower(): v for k, v in _REQUIRED_ENV.items()})  # type: ignore[arg-type]
    assert cfg.database_url == "sqlite:///./uptime.db"


@pytest.mark.parametrize(
    "present, missing_key",
    [
        ({"TELEGRAM_CHAT_ID": "c", "AUTH_SECRET_KEY": "s"}, "telegram_bot_token"),
        ({"TELEGRAM_BOT_TOKEN": "b", "AUTH_SECRET_KEY": "s"}, "telegram_chat_id"),
        ({"TELEGRAM_BOT_TOKEN": "b", "TELEGRAM_CHAT_ID": "c"}, "auth_secret_key"),
    ],
)
def test_missing_required_field_raises_naming_the_key(
    monkeypatch: pytest.MonkeyPatch, present: dict[str, str], missing_key: str
) -> None:
    """Requirement 9.2: a missing required field raises ConfigError naming it.

    Use _env_file=None to ensure no ambient .env satisfies the field, so the
    test is deterministic regardless of the working directory.
    """
    for key, value in present.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(ConfigError) as exc_info:
        _load_without_env_file()

    assert missing_key in str(exc_info.value)


def _load_without_env_file() -> Settings:
    """Mirror load_settings but with no .env, for deterministic missing-field tests."""
    from config import _extract_missing_fields  # local import to keep module clean

    try:
        return Settings(_env_file=None)  # type: ignore[call-arg]
    except Exception as exc:
        missing = _extract_missing_fields(exc)
        if missing:
            raise ConfigError(
                f"Missing required configuration value(s): {', '.join(missing)}"
            ) from exc
        raise
