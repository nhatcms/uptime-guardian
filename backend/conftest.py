"""Pytest configuration: ensure the backend package modules are importable.

Adds the backend directory (this file's directory) to ``sys.path`` so tests can
``import config`` and the other top-level backend modules directly.
"""

import os
import sys

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Provide safe defaults for the required configuration values so that modules
# which load Settings at import time (e.g. database.py) can be imported during
# tests without a real .env present. setdefault never overrides a value that is
# already set in the real environment. test_config.py clears these per-test via
# monkeypatch, so its missing-field assertions remain unaffected.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-bot-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat-id")
os.environ.setdefault("AUTH_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
