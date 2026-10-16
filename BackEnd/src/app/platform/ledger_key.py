"""HMAC key of the local ledger (blocks of the simulated chain are keyed with it).

Read from ``CREDIT_LEDGER_KEY`` at call time. Outside dev/test an unset key, or the public
dev default, fails closed: with a key anyone can read in the repo, the HMAC would let them
forge a consistent chain.
"""

from __future__ import annotations

import logging
import os

from app.platform.config import settings

# Public in the repository, so it proves nothing: allowed only in dev/test.
DEV_DEFAULT_KEY = "dev-only-ledger-key-change-me"
_KEY_ENV = "CREDIT_LEDGER_KEY"
_LENIENT_ENVS = frozenset({"dev", "test"})
_log = logging.getLogger("sellergraph.ledger")


class LedgerKeyMissing(RuntimeError):
    """Raised when no usable HMAC key is configured outside dev/test."""


def resolve_key() -> str:
    """The HMAC key, read from ``CREDIT_LEDGER_KEY`` at call time.

    Outside dev/test an unset key, or the public dev default, raises
    ``LedgerKeyMissing``: with a key anyone can read in the repo, the HMAC
    would let them forge a consistent chain, so we fail closed.
    """
    key = os.environ.get(_KEY_ENV) or settings.credit_ledger_key or ""  # env var, else the .env file
    if (not key or key == DEV_DEFAULT_KEY) and settings.app_env.lower() not in _LENIENT_ENVS:
        raise LedgerKeyMissing(
            f"{_KEY_ENV} is unset or the public dev default while APP_ENV={settings.app_env!r}; "
            "set it to a secret, e.g. python -c 'import secrets;print(secrets.token_hex(32))'"
        )
    return key or DEV_DEFAULT_KEY


def check_key_configured() -> None:
    """Startup check: raise in production when misconfigured, warn once in dev."""
    key = resolve_key()
    if key == DEV_DEFAULT_KEY:
        _log.warning("%s is not set: using the public dev key (APP_ENV=%s)", _KEY_ENV, settings.app_env)
