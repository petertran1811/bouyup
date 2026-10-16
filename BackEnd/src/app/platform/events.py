"""Application trace: one row per agent/gate/officer action (GET /trace)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform.tables import BuEvent
from app.platform.db.tables import utcnow

ACTORS = ("agent1", "agent2", "agent3", "gate", "agent4", "agent5", "code", "officer", "seller", "system")


def log(
    session: Session,
    application_id: str,
    actor: str,
    kind: str,
    summary: str,
    payload: dict[str, Any] | None = None,
    hash_: str = "",
) -> BuEvent:
    event = BuEvent(
        application_id=application_id, actor=actor, kind=kind, summary=summary,
        payload=payload or {}, hash=hash_, at=utcnow(),
    )
    session.add(event)
    session.flush()
    return event


def event_public(event: BuEvent) -> dict[str, Any]:
    return {
        "at": event.at.isoformat() + "Z", "actor": event.actor, "kind": event.kind,
        "summary": event.summary, "hash": event.hash, "payload": event.payload,
    }


def for_application(session: Session, application_id: str) -> list[BuEvent]:
    return list(session.scalars(
        select(BuEvent).where(BuEvent.application_id == application_id).order_by(BuEvent.id)
    ))
