"""Engine and session management."""

from __future__ import annotations

import unicodedata
from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.platform.config import settings

_connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    future=True,
)

if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        """WAL lets readers run while a writer holds the lock. A write transaction can hold
        the lock for several seconds (model calls, remote chain anchors), so a second
        writer waits up to 30 s instead of failing with "database is locked"."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()
        # SQLite's lower() is ASCII-only ("Đ" stays "Đ"); searches use this Unicode one.
        dbapi_connection.create_function(
            "ulower", 1, lambda s: unicodedata.normalize("NFC", s).casefold() if isinstance(s, str) else s,
            deterministic=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on failure."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session
