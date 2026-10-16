"""/v4/officer: escalated-case queue and the officer's decision (contract section 5)."""

from __future__ import annotations

import copy
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api import views
from app.agents import agent3_control as control
from app.api.applications import load, out
from app.core.params import active_params
from app.platform.errors import api_error
from app.platform.security import require_roles
from app.platform.tables import BuApplication, BuUser
from app.platform.db.session import get_session
from app.platform.db.tables import utcnow

router = APIRouter(prefix="/officer", tags=["v4-officer"])
_officers = require_roles("officer", "admin")


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "smaller_offer", "continue"]
    option_id: str | None = Field(default=None, max_length=60)
    note: str = Field(default="", max_length=1000)


def _why(app_row: BuApplication) -> str:
    doc = app_row.doc or {}
    if app_row.status == "needs_answer":
        return next((f["code"] for f in doc["verification"]["flags"] if f["status"] == "open"), "RISK-01")
    return (doc.get("escalation") or {}).get("why") or "AGENT3"


@router.get("/queue")
def queue(user: BuUser = Depends(_officers), session: Session = Depends(get_session)) -> dict:
    """Escalated cases, plus cases waiting on a seller answer past the open-flag deadline."""
    days = active_params(session)["flags"]["open_days"]
    overdue = utcnow() - timedelta(days=days)
    rows = session.scalars(
        select(BuApplication).where(or_(
            BuApplication.status == "escalated",
            (BuApplication.status == "needs_answer") & (BuApplication.updated_at <= overdue),
        )).order_by(BuApplication.updated_at)
    )
    items = []
    for r in rows:
        item = views.summary_view(r, session.get(BuUser, r.seller_user_id))
        item["why"] = _why(r)
        items.append(item)
    return {"items": items}


@router.post("/applications/{app_id}/decision")
def decide(app_id: str, body: DecisionIn, user: BuUser = Depends(_officers),
           session: Session = Depends(get_session)) -> dict:
    app_row = load(session, app_id, user)
    doc = copy.deepcopy(app_row.doc)
    control.officer_decision(session, app_row, doc, active_params(session), user, body.decision,
                             body.option_id, body.note)
    session.commit()
    return out(session, app_row, user)


@router.post("/applications/{app_id}/reauthorize-payout")
def reauthorize_payout(app_id: str, user: BuUser = Depends(_officers),
                       session: Session = Depends(get_session)) -> dict:
    """Review item 3: a payout whose one-off grant expired (or failed) runs again only when an officer
    grants Agent 4a a new one; the escalation is cleared when the payout goes through."""
    from app.agents import agent4a_payout

    app_row = load(session, app_id, user)
    if not ((app_row.doc or {}).get("contract") or {}).get("signed_at"):
        raise api_error(400, "INVALID_STATE", "Hồ sơ chưa ký hợp đồng.")
    loan = agent4a_payout.reauthorize(session, app_row, user.id)
    if loan is not None:
        doc = copy.deepcopy(app_row.doc)
        doc["escalation"] = None
        views.store(app_row, doc)
    session.commit()
    return out(session, app_row, user)
