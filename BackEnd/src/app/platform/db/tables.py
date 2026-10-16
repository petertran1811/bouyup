"""Declarative base and the single clock of the app.

All timestamps are stored as *naive UTC*. SQLite drops tzinfo on read, so mixing aware and
naive values would break every comparison; ``utcnow()`` is the single source of truth.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase


def utcnow() -> datetime:
    """Naive UTC timestamp - use this everywhere instead of datetime.now()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass
