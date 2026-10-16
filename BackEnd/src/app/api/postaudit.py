"""/v4 post-audit (Agent 5) and parameter versions (contract §6).

Officers may run the audit and see proposals; only an admin approves one."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform.errors import api_error
from app.agents import agent5_postaudit as postaudit
from app.platform.security import require_roles
from app.platform.tables import BuProposal, BuReport, BuUser
from app.platform.db.session import get_session

router = APIRouter(tags=["v4-postaudit"])

_STAFF = ("officer", "admin")


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=1000)


@router.post("/postaudit/run")
def run_postaudit(
    user: BuUser = Depends(require_roles(*_STAFF)),
    session: Session = Depends(get_session),
) -> dict:
    report, proposals = postaudit.run(session, user)
    session.commit()
    return {"report": report.data, "proposals": [postaudit.proposal_view(p) for p in proposals]}


@router.get("/postaudit/reports")
def list_reports(
    _: BuUser = Depends(require_roles(*_STAFF)),
    session: Session = Depends(get_session),
) -> dict:
    rows = session.scalars(select(BuReport).order_by(BuReport.at.desc()).limit(50))
    return {"items": [r.data for r in rows]}


@router.get("/postaudit/proposals")
def list_proposals(
    status: str | None = None,
    _: BuUser = Depends(require_roles(*_STAFF)),
    session: Session = Depends(get_session),
) -> dict:
    stmt = select(BuProposal).order_by(BuProposal.id)
    if status:
        stmt = stmt.where(BuProposal.status == status)
    return {"items": [postaudit.proposal_view(p) for p in session.scalars(stmt)]}


@router.post("/postaudit/proposals/{proposal_id}/decision")
def decide_proposal(
    proposal_id: str,
    body: DecisionIn,
    user: BuUser = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> dict:
    proposal = session.get(BuProposal, proposal_id)
    if proposal is None:
        raise api_error(404, "NOT_FOUND", "Không tìm thấy đề xuất.")
    version = postaudit.decide(session, proposal, user, body.decision, body.note)
    session.commit()
    return {
        "proposal": postaudit.proposal_view(proposal),
        "params_version": version.version if version else None,
        "params": postaudit.params_view(session),
    }


@router.get("/params")
def get_params(
    _: BuUser = Depends(require_roles(*_STAFF)),
    session: Session = Depends(get_session),
) -> dict:
    return postaudit.params_view(session)
