"""/v4/complaints: the complaint desk (review item 4; app/agents/complaints.py)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import complaints as desk
from app.core.params import active_params
from app.platform.db.session import get_session
from app.platform.errors import api_error
from app.platform.security import current_user, find_user_by_email, require_roles
from app.platform.tables import BuComplaint, BuUser

router = APIRouter(prefix="/complaints", tags=["v4-complaints"])
_officers = require_roles("officer", "admin")


class ComplaintIn(BaseModel):
    category: Literal["rejection", "limit", "fees", "debit", "data", "other"]
    text: str = Field(min_length=1, max_length=2000)
    application_id: str | None = Field(default=None, max_length=40)
    loan_id: str | None = Field(default=None, max_length=40)
    # Staff logging a complaint taken by the hotline or email: the borrower's email and the channel.
    channel: Literal["app", "hotline", "email"] = "app"
    seller_email: str | None = Field(default=None, max_length=254)


class AnswerIn(BaseModel):
    outcome: Literal["upheld", "changed", "reopened"]
    text: str = Field(min_length=1, max_length=2000)


class ExtendIn(BaseModel):
    days: int = Field(ge=1, le=10)
    note: str = Field(min_length=1, max_length=300)


def _staff(user: BuUser) -> bool:
    return user.role in ("officer", "admin")


@router.post("", status_code=201)
def create(body: ComplaintIn, user: BuUser = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    if _staff(user):
        seller = find_user_by_email(session, (body.seller_email or "").strip().lower())
        if seller is None or seller.role != "seller" or body.channel == "app":
            raise api_error(400, "VALIDATION_ERROR", "Cán bộ ghi khiếu nại qua tổng đài/email cần email người vay.",
                            {"field": "seller_email"})
        c = desk.open_complaint(session, seller, category=body.category, text=body.text, channel=body.channel,
                                application_id=body.application_id, loan_id=body.loan_id, logged_by=user)
    elif user.role == "seller":
        c = desk.open_complaint(session, user, category=body.category, text=body.text, channel="app",
                                application_id=body.application_id, loan_id=body.loan_id)
    else:
        raise api_error(403, "FORBIDDEN", "Vai trò này không gửi khiếu nại.")
    session.commit()
    return desk.view(c, _staff(user))


@router.get("")
def list_complaints(status: str | None = None, user: BuUser = Depends(current_user),
                    session: Session = Depends(get_session)) -> dict:
    stmt = select(BuComplaint).order_by(BuComplaint.answer_due)
    if user.role == "seller":
        stmt = stmt.where(BuComplaint.seller_user_id == user.id)
    elif not _staff(user):
        raise api_error(403, "FORBIDDEN", "Không có quyền xem khiếu nại.")
    if status:
        stmt = stmt.where(BuComplaint.status == status)
    items = [desk.view(c, _staff(user)) for c in session.scalars(stmt)]
    p = active_params(session)
    return {"items": items, "channel": p["contract"]["complaint_channel"],
            "deadlines": {k: p["complaint"][k] for k in ("ack_days", "answer_days", "max_days")}}


@router.get("/{complaint_id}")
def get_one(complaint_id: str, user: BuUser = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    c = session.get(BuComplaint, complaint_id)
    if c is None or (not _staff(user) and c.seller_user_id != user.id):
        raise api_error(404, "NOT_FOUND", "Không tìm thấy khiếu nại.")
    return desk.view(c, _staff(user))


@router.post("/{complaint_id}/assign")
def assign(complaint_id: str, user: BuUser = Depends(_officers), session: Session = Depends(get_session)) -> dict:
    c = desk.assign(session, complaint_id, user)
    session.commit()
    return desk.view(c, True)


@router.post("/{complaint_id}/extend")
def extend(complaint_id: str, body: ExtendIn, user: BuUser = Depends(_officers),
           session: Session = Depends(get_session)) -> dict:
    c = desk.extend(session, complaint_id, user, body.days, body.note)
    session.commit()
    return desk.view(c, True)


@router.post("/{complaint_id}/answer")
def answer(complaint_id: str, body: AnswerIn, user: BuUser = Depends(_officers),
           session: Session = Depends(get_session)) -> dict:
    c = desk.answer(session, complaint_id, user, body.outcome, body.text)
    session.commit()
    return desk.view(c, True)
