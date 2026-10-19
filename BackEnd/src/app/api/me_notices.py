"""/v4/me/notices: the seller's notification centre (SELLER_SERVICES_PLAN §3.1, 17/10/2026).

One list merged from three sources, newest first (at most 100):

1. ``BuLoan.doc["notices"]`` of every loan of the seller (open or closed): Agent 4's notices, reminders,
   questions → ``scope: "loan"``;
2. ``BuApplication.doc["seller_notices"]`` (``app.agents.notify.push_app_notice``): decisions, the banks'
   limit approval, requests for documents → ``scope: "application"``;
3. ``bu_seller_reports`` (Agent 5's reports) → ``scope: "report"``.

``POST /v4/me/notices/read`` marks items read (``read_at`` on the item itself, or the report's column).
Read-only for money.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.agent4b_monitor import LOAN_LOCK
from app.agents.notify import level_of, title_for
from app.platform.db.session import get_session
from app.platform.db.tables import utcnow
from app.platform.security import require_roles
from app.platform.tables import BuApplication, BuLoan, BuSellerReport, BuUser, save_json

router = APIRouter(prefix="/me", tags=["v4-me-notices"])
_sellers = require_roles("seller")
MAX_ITEMS = 100


class ReadIn(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=200)
    all: bool = False  # mark everything read


def _iso(dt: Any) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def _loan_item(loan: BuLoan, n: dict[str, Any]) -> dict[str, Any]:
    question = n.get("question")
    item = {"id": n.get("id"), "scope": "loan", "loan_id": loan.id, "application_id": loan.application_id,
            "kind": n.get("kind") or "info", "level": level_of(n.get("level")),
            "title": title_for(n.get("kind"), n.get("level"), bool(question and not n.get("answer"))),
            "text": n.get("text") or "", "at": n.get("at"), "read_at": n.get("read_at"),
            "action": n.get("action") or {"view": "loan", "id": loan.id}}
    if question:
        item["question"], item["answer"] = question, n.get("answer")
    return item


def _app_item(app: BuApplication, n: dict[str, Any]) -> dict[str, Any]:
    action = dict(n.get("action") or {}) or None
    if action and action.get("view") == "apply":
        action.setdefault("id", app.id)
    return {"id": n.get("id"), "scope": "application", "application_id": app.id, "application_code": app.code,
            "kind": n.get("kind") or "info", "level": level_of(n.get("level")), "title": title_for(n.get("kind"), n.get("level")),
            "text": n.get("text") or "", "at": n.get("at"), "read_at": n.get("read_at"), "action": action}


def _report_line(r: BuSellerReport) -> str:
    data = r.data or {}
    line = data.get("summary_line") or data.get("summary") or ""
    return str(line).split("\n")[0][:300] or f"Báo cáo {r.period} đã sẵn sàng."


def _report_item(r: BuSellerReport) -> dict[str, Any]:
    data = r.data or {}
    return {"id": r.id, "scope": "report", "report_id": r.id, "kind": r.kind, "level": level_of(data.get("level")),
            "title": title_for(r.kind) + (f" {r.period}" if r.kind in ("month", "quarter", "year") else ""),
            "text": _report_line(r), "at": _iso(r.at), "read_at": _iso(r.read_at),
            "action": {"view": "report", "id": r.id}}


def _rows(session: Session, user: BuUser) -> tuple[list[BuLoan], list[BuApplication], list[BuSellerReport]]:
    loans = list(session.scalars(select(BuLoan).where(BuLoan.seller_user_id == user.id)))
    apps = list(session.scalars(select(BuApplication).where(BuApplication.seller_user_id == user.id,
                                                            BuApplication.status != "withdrawn")))
    reports = list(session.scalars(select(BuSellerReport).where(BuSellerReport.seller_user_id == user.id)))
    return loans, apps, reports


def collect(session: Session, user: BuUser) -> list[dict[str, Any]]:
    """Every notice of the seller, newest first (not truncated)."""
    loans, apps, reports = _rows(session, user)
    items = [_loan_item(ln, n) for ln in loans for n in (ln.doc or {}).get("notices") or [] if n.get("id")]
    items += [_app_item(a, n) for a in apps for n in (a.doc or {}).get("seller_notices") or [] if n.get("id")]
    items += [_report_item(r) for r in reports]
    return sorted(items, key=lambda x: str(x.get("at") or ""), reverse=True)


def _unread(items: list[dict[str, Any]]) -> int:
    return sum(1 for x in items if not x.get("read_at"))


@router.get("/notices")
def my_notices(user: BuUser = Depends(_sellers), session: Session = Depends(get_session)) -> dict:
    items = collect(session, user)
    return {"items": items[:MAX_ITEMS], "unread": _unread(items)}


def _mark(notices: list[dict[str, Any]], wanted: set[str] | None, stamp: str) -> tuple[list[dict[str, Any]], bool]:
    changed = False
    out = []
    for n in notices:
        if not n.get("read_at") and (wanted is None or n.get("id") in wanted):
            n = {**n, "read_at": stamp}
            changed = True
        out.append(n)
    return out, changed


@router.post("/notices/read")
def read_notices(body: ReadIn, user: BuUser = Depends(_sellers), session: Session = Depends(get_session)) -> dict:
    wanted = None if body.all else set(body.ids)
    stamp = utcnow().isoformat() + "Z"
    if wanted is None or wanted:
        with LOAN_LOCK:  # the loan docs are also written by Agent 4's monitor
            loans, apps, reports = _rows(session, user)
            for ln in loans:
                session.refresh(ln)
                doc = dict(ln.doc or {})
                doc["notices"], changed = _mark(list(doc.get("notices") or []), wanted, stamp)
                if changed:
                    save_json(ln, "doc", doc)
            for a in apps:
                doc = dict(a.doc or {})
                doc["seller_notices"], changed = _mark(list(doc.get("seller_notices") or []), wanted, stamp)
                if changed:
                    save_json(a, "doc", doc)  # not views.store: reading is not an update of the case
            for r in reports:
                if r.read_at is None and (wanted is None or r.id in wanted):
                    r.read_at = utcnow()
            session.commit()
    return {"unread": _unread(collect(session, user))}
