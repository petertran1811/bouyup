"""Create the BuoyUp tables (safe to call repeatedly) or drop and recreate them (tests, resets)."""

from __future__ import annotations

from app.platform.db.session import engine
from app.platform.db.tables import Base

import app.platform.tables  # noqa: F401,E402  (registers the BuoyUp tables on Base)


def init_db() -> None:
    """Create any missing table. Safe to call repeatedly."""
    Base.metadata.create_all(bind=engine)


def reset_db() -> None:
    """Drop and recreate every table (tests and demo resets)."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
