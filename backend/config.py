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

# External-service timing budgets (Requirements 11.1, 12.1, 13.2).
# Cloudflare Turnstile server-side verification must complete within 10 seconds;
# any attempt exceeding this is treated as the service being unavailable (503).
TURNSTILE_TIMEOUT_SECONDS: float = 10.0
# SePay QR payment-reference construction is pure string work and must stay well
# under the 3-second initiation budget; the constant documents that budget.
QR_GENERATION_BUDGET_SECONDS: float = 3.0


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

    # --- Cloudflare Turnstile (server-side verification) -------------------
    # Secret key used to verify Turnstile tokens with Cloudflare. When left
    # empty (the default), verification runs in dev-only bypass mode where any
    # non-empty token is accepted; a real secret must be configured in
    # production (Requirements 11.1, 12.1). Never hardcoded.
    turnstile_secret_key: str = ""
    turnstile_verify_url: str = (
        "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    )

    # --- SePay payment gateway --------------------------------------------
    # API key SePay sends on webhook calls via the "Authorization: Apikey <key>"
    # header; an empty value disables API-key verification (dev only).
    sepay_api_key: str = ""
    # Shared secret for the optional HMAC-SHA256 webhook verification mode.
    sepay_webhook_secret: str = ""
    # Receiving bank account details encoded into the VietQR payment image.
    sepay_bank_code: str = ""
    sepay_account_number: str = ""
    # Base URL of SePay's dynamic VietQR image endpoint.
    sepay_qr_base_url: str = "https://qr.sepay.vn/img"

    # --- Google OAuth 2.0 (Sign in with Google) ---------------------------
    # OAuth client credentials from the Google Cloud Console
    # (APIs & Services -> Credentials -> OAuth 2.0 Client ID, type "Web
    # application"). When either id or secret is empty the Google login routes
    # respond with 503 so the feature degrades gracefully; never hardcoded.
    google_client_id: str = ""
    google_client_secret: str = ""
    # The redirect/callback URI registered as an "Authorized redirect URI" in
    # the Google console. Must point at the backend callback route below.
    google_redirect_uri: str = (
        "http://localhost:8000/api/auth/google/callback"
    )
    # Base URL of the SPA the backend redirects back to after the OAuth dance,
    # carrying the issued token (or an error code) in the URL.
    frontend_base_url: str = "http://localhost:5173"
    # Discovery endpoints (overridable for testing); these are Google's stable
    # OAuth 2.0 / OpenID Connect endpoints.
    google_authorize_url: str = (
        "https://accounts.google.com/o/oauth2/v2/auth"
    )
    google_token_url: str = "https://oauth2.googleapis.com/token"

    # --- Plan seeding ------------------------------------------------------
    # Name of the default free Plan seeded on first run (Requirement 1.8).
    free_plan_name: str = "Free"

    @property
    def google_oauth_configured(self) -> bool:
        """True when both Google client id and secret are present."""
        return bool(self.google_client_id and self.google_client_secret)

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
