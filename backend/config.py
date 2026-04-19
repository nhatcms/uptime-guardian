"""Application configuration for Uptime Guardian.

Settings are loaded from a `.env` file (or the process environment) via
pydantic-settings. Required values that are absent at startup raise a
configuration error that identifies the missing field. Interval and cooldown
values that are not positive integers fall back to their defaults.

Requirements traceability: 9.1, 9.2, 9.3, 9.4.
"""

from __future__ import annotations

from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Default values applied when interval/cooldown are missing or invalid.
DEFAULT_CHECK_INTERVAL_MINUTES: int = 5
DEFAULT_ALERT_COOLDOWN_MINUTES: int = 10


class ConfigError(RuntimeError):
    """Raised at startup when a required configuration value is missing."""


class Settings(BaseSettings):
    """Runtime configuration loaded from the environment / `.env` file.

    Required fields (no default): ``telegram_bot_token``, ``telegram_chat_id``,
    ``auth_secret_key``. A missing required field raises :class:`ConfigError`
    naming the absent key (Requirement 9.2).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = "sqlite:///./uptime.db"
    telegram_bot_token: str
    telegram_chat_id: str
    check_interval_minutes: int = DEFAULT_CHECK_INTERVAL_MINUTES
    alert_cooldown_minutes: int = DEFAULT_ALERT_COOLDOWN_MINUTES
    auth_secret_key: str
    # Comma-separated list of browser origins allowed to call the API.
    # Use "*" to allow any origin (handy for self-hosted LAN access where the
    # dashboard is reached via an IP address rather than localhost).
    cors_allow_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parsed list of allowed origins from ``cors_allow_origins``."""
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def cors_allow_all(self) -> bool:
        """True when any origin is permitted (``cors_allow_origins`` is "*")."""
        return "*" in self.cors_origins_list

    @field_validator("check_interval_minutes", mode="before")
    @classmethod
    def _validate_check_interval(cls, value: Any) -> int:
        """Coerce a non-positive / non-integer interval to its default."""
        return _coerce_positive_int(value, DEFAULT_CHECK_INTERVAL_MINUTES)

    @field_validator("alert_cooldown_minutes", mode="before")
    @classmethod
    def _validate_alert_cooldown(cls, value: Any) -> int:
        """Coerce a non-positive / non-integer cooldown to its default."""
        return _coerce_positive_int(value, DEFAULT_ALERT_COOLDOWN_MINUTES)


def _coerce_positive_int(value: Any, default: int) -> int:
    """Return ``value`` as a positive int, or ``default`` if it is not one.

    Accepts ints and clean integer-valued strings (e.g. ``"15"``). Any value
    that is missing, non-numeric, fractional, zero, or negative falls back to
    ``default`` (Requirement 9.4). Booleans are rejected since ``bool`` is a
    subclass of ``int`` but is not a meaningful interval value.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value if value > 0 else default
    if isinstance(value, float):
        # Only accept whole-number floats (e.g. 5.0); reject fractions.
        if value.is_integer() and value > 0:
            return int(value)
        return default
    if isinstance(value, str):
        text = value.strip()
        try:
            parsed = int(text)
        except (ValueError, TypeError):
            return default
        return parsed if parsed > 0 else default
    return default


def load_settings() -> Settings:
    """Load and validate :class:`Settings`.

    Raises:
        ConfigError: If a required field is missing, naming the absent key.
    """
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception as exc:  # pydantic.ValidationError or others
        missing = _extract_missing_fields(exc)
        if missing:
            joined = ", ".join(missing)
            raise ConfigError(
                f"Missing required configuration value(s): {joined}"
            ) from exc
        raise


def _extract_missing_fields(exc: Exception) -> list[str]:
    """Extract the names of required-but-missing fields from a validation error."""
    missing: list[str] = []
    errors = getattr(exc, "errors", None)
    if callable(errors):
        for err in errors():
            if err.get("type") == "missing":
                loc = err.get("loc", ())
                if loc:
                    missing.append(str(loc[-1]))
    return missing
