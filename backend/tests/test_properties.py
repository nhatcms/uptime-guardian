"""Property-based tests for Uptime Guardian.

Each test corresponds to exactly one numbered correctness property from the
design document and is tagged accordingly. Properties are added next to the
code they validate as their owning tasks are implemented.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from config import (
    DEFAULT_ALERT_COOLDOWN_MINUTES,
    DEFAULT_CHECK_INTERVAL_MINUTES,
    Settings,
)

# Required fields needed to construct Settings without touching the environment.
_REQUIRED: dict[str, str] = {
    "telegram_bot_token": "test_token",
    "telegram_chat_id": "test_chat",
    "auth_secret_key": "test_secret",
}


def _make_settings(**overrides: object) -> Settings:
    """Build Settings with required fields, ignoring any ambient `.env`."""
    return Settings(_env_file=None, **{**_REQUIRED, **overrides})  # type: ignore[arg-type]


# Strategy for values that are NOT positive integers: zero, negatives,
# fractional floats, non-numeric strings, and floats that are not whole.
_invalid_numeric = st.one_of(
    st.integers(max_value=0),
    st.floats(min_value=-1000, max_value=1000).filter(
        lambda f: not (f == f and float(f).is_integer() and f > 0)
    ),
    st.text(max_size=8).filter(lambda s: not s.strip().lstrip("-").isdigit()),
)


# Feature: uptime-guardian, Property 15: Configuration falls back on invalid values
@settings(max_examples=50)
@given(bad_interval=_invalid_numeric, bad_cooldown=_invalid_numeric)
def test_property_15_config_falls_back_on_invalid_values(
    bad_interval: object, bad_cooldown: object
) -> None:
    """For any non-positive or non-integer interval/cooldown value, Settings
    yields the corresponding default (5 or 10).

    Validates: Requirements 9.4
    """
    cfg = _make_settings(
        check_interval_minutes=bad_interval,
        alert_cooldown_minutes=bad_cooldown,
    )
    assert cfg.check_interval_minutes == DEFAULT_CHECK_INTERVAL_MINUTES
    assert cfg.alert_cooldown_minutes == DEFAULT_ALERT_COOLDOWN_MINUTES


# Feature: uptime-guardian, Property 15: Configuration falls back on invalid values
@settings(max_examples=50)
@given(good_interval=st.integers(min_value=1, max_value=10_000),
       good_cooldown=st.integers(min_value=1, max_value=10_000))
def test_property_15_valid_values_are_preserved(
    good_interval: int, good_cooldown: int
) -> None:
    """Positive integer values are preserved unchanged (complements 9.4).

    Validates: Requirements 9.4
    """
    cfg = _make_settings(
        check_interval_minutes=good_interval,
        alert_cooldown_minutes=good_cooldown,
    )
    assert cfg.check_interval_minutes == good_interval
    assert cfg.alert_cooldown_minutes == good_cooldown
