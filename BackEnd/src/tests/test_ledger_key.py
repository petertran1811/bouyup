"""The ledger HMAC key: process environment first, then the .env file (settings); fail closed outside dev/test."""

from __future__ import annotations

import pytest

from app.platform import ledger_key
from app.platform.config import settings


def test_key_from_env_file_when_the_process_has_none(monkeypatch):
    monkeypatch.delenv("CREDIT_LEDGER_KEY", raising=False)
    monkeypatch.setattr(settings, "app_env", "demo")
    monkeypatch.setattr(settings, "credit_ledger_key", "k" * 64)
    assert ledger_key.resolve_key() == "k" * 64
    monkeypatch.setenv("CREDIT_LEDGER_KEY", "e" * 64)  # the environment wins
    assert ledger_key.resolve_key() == "e" * 64


def test_missing_or_public_key_fails_closed_outside_dev(monkeypatch):
    monkeypatch.delenv("CREDIT_LEDGER_KEY", raising=False)
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "credit_ledger_key", "")
    with pytest.raises(ledger_key.LedgerKeyMissing):
        ledger_key.resolve_key()
    monkeypatch.setattr(settings, "credit_ledger_key", ledger_key.DEV_DEFAULT_KEY)
    with pytest.raises(ledger_key.LedgerKeyMissing):
        ledger_key.resolve_key()
    monkeypatch.setattr(settings, "app_env", "dev")
    assert ledger_key.resolve_key() == ledger_key.DEV_DEFAULT_KEY
