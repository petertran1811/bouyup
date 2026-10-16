"""Bàn khiếu nại · complaint desk (review item 4, 16/10/2026). Code plus people, no model decides.

The cost sheet promises a complaint channel (``contract.complaint_channel``); this is who handles it:

1. **Receive.** A complaint comes from the app, or an officer logs one taken by the hotline or email.
   It gets a code (``KN-…``) and is acknowledged at once (``complaint.ack_days`` working days is the
   commitment for the hotline/email path, the moment an officer logs it).
2. **Give the reasons.** The reasons already recorded for the decision complained about are attached
   immediately: the decision's reason (law, factor, fix) and, when the limit was cut, the B8 reason
   codes. AML cases keep the legally required secrecy and get a neutral text.
3. **Hand to a person.** An officer other than the one who decided reviews it; they keep the
   decision, change it, or reopen the application into the officer queue.
4. **Answer in time.** Answer with reasons within ``complaint.answer_days`` working days; with notice to
   the borrower it may be extended up to ``complaint.max_days``. Past the deadline the complaint is
   escalated to the lead (``status = "escalated"``) by the scheduled round.

Opening and answering go on the chain (``complaint_opened`` / ``complaint_answered``).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.blockchain import chain
from app.core.params import active_params
from app.platform import events
from app.platform.db.tables import utcnow
from app.platform.errors import api_error
from app.platform.tables import BuApplication, BuComplaint, BuLoan, BuUser

CATEGORIES = {"rejection": "Bị từ chối", "limit": "Hạn mức bị giảm", "fees": "Lãi và phí", "debit": "Trích nợ",
              "data": "Dữ liệu cá nhân", "other": "Khác"}
CHANNELS = ("app", "hotline", "email")
OUTCOMES = {"upheld": "Giữ nguyên quyết định", "changed": "Điều chỉnh quyết định", "reopened": "Mở lại hồ sơ để xét lại"}
OPEN = ("acknowledged", "in_review", "escalated")
_HIDDEN = {"law": "Quy định về phòng, chống rửa tiền",
           "factor": "Theo quy định hiện hành, BuoyUp không thể nêu chi tiết lý do của quyết định này.",
           "fix": "Cán bộ sẽ trả lời khiếu nại của chị trong thời hạn cam kết."}


def add_working_days(start: datetime, days: int) -> datetime:
    """``start`` + ``days`` working days (Monday–Friday)."""
    out, left = start, int(days)
    while left > 0:
        out += timedelta(days=1)
        if out.weekday() < 5:
            left -= 1
    return out


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def _reasons(session: Session, app_row: BuApplication | None) -> dict[str, Any]:
    """What was decided and why, as recorded on the application (never recomputed)."""
    if app_row is None:
        return {"decision": None, "reason": None, "reason_codes": [], "hidden": False}
    from app.agents.agent3_control import hidden_reason

    doc = app_row.doc or {}
    decision = doc.get("decision") or {}
    if hidden_reason(doc):
        return {"decision": decision.get("kind"), "reason": dict(_HIDDEN), "reason_codes": [], "hidden": True}
    offer = doc.get("offer") or {}
    codes = [{k: r.get(k) for k in ("code", "text", "impact")} for r in offer.get("reason_codes") or []
             if r.get("block") == "B8" or r.get("code") in ("SEED_LOAN", "THIN_FATE_CAP")]
    reason = decision.get("reason") or (doc.get("verification") or {}).get("reason")
    return {"decision": decision.get("kind"), "decided_at": decision.get("at"), "reason": reason,
            "limit": offer.get("limit"), "requested": doc.get("requested"), "reason_codes": codes, "hidden": False}


def _decided_by(app_row: BuApplication | None) -> str:
    decision = ((app_row.doc or {}).get("decision") or {}) if app_row else {}
    return str(decision.get("officer_id") or decision.get("by") or "")


def _log(c: BuComplaint, who: str, what: str, **extra: Any) -> None:
    c.history = list(c.history or []) + [{"at": _iso(utcnow()), "by": who, "what": what, **extra}]


def open_complaint(session: Session, seller: BuUser, *, category: str, text: str, channel: str = "app",
                   application_id: str | None = None, loan_id: str | None = None,
                   logged_by: BuUser | None = None) -> BuComplaint:
    if category not in CATEGORIES:
        raise api_error(400, "VALIDATION_ERROR", "Loại khiếu nại không hợp lệ.", {"field": "category"})
    if channel not in CHANNELS:
        raise api_error(400, "VALIDATION_ERROR", "Kênh tiếp nhận không hợp lệ.", {"field": "channel"})
    text = (text or "").strip()
    if len(text) < 5:
        raise api_error(400, "VALIDATION_ERROR", "Chị mô tả ngắn nội dung khiếu nại (ít nhất 5 ký tự).", {"field": "text"})
    app_row = session.get(BuApplication, application_id) if application_id else None
    if application_id and (app_row is None or app_row.seller_user_id != seller.id):
        raise api_error(404, "NOT_FOUND", "Không tìm thấy hồ sơ.", {"field": "application_id"})
    if loan_id:
        loan = session.get(BuLoan, loan_id)
        if loan is None or loan.seller_user_id != seller.id:
            raise api_error(404, "NOT_FOUND", "Không tìm thấy khoản vay.", {"field": "loan_id"})
        if app_row is None and loan.application_id:
            app_row = session.get(BuApplication, loan.application_id)
    p = active_params(session)["complaint"]
    now = utcnow()
    c = BuComplaint(id="KN-" + secrets.token_hex(4).upper(), seller_user_id=seller.id,
                    application_id=app_row.id if app_row else None, loan_id=loan_id, category=category,
                    channel=channel, text=text[:2000], status="acknowledged", reasons=_reasons(session, app_row),
                    decided_by=_decided_by(app_row), assigned_to="", created_at=now, ack_at=now,
                    answer_due=add_working_days(now, int(p["answer_days"])),
                    max_due=add_working_days(now, int(p["max_days"])), history=[])
    _log(c, logged_by.id if logged_by else seller.id, "opened", channel=channel)
    session.add(c)
    session.flush()
    case_id = app_row.id if app_row else c.id
    entry = chain.record(session, case_id, "complaint_opened",
                         {"complaint": c.id, "category": category, "channel": channel, "answer_due": _iso(c.answer_due),
                          "text_hash": "sha256:" + hashlib.sha256(c.text.encode()).hexdigest()})
    _log(c, "system", "on_chain", tx=entry.tx)
    events.log(session, case_id, "complaints", "complaint_opened",
               f"Tiếp nhận khiếu nại {c.id} ({CATEGORIES[category]}); trả lời trước {c.answer_due.date().isoformat()}",
               {"complaint": c.id})
    return c


def _get(session: Session, complaint_id: str) -> BuComplaint:
    c = session.get(BuComplaint, complaint_id)
    if c is None:
        raise api_error(404, "NOT_FOUND", "Không tìm thấy khiếu nại.")
    return c


def assign(session: Session, complaint_id: str, officer: BuUser) -> BuComplaint:
    c = _get(session, complaint_id)
    if c.status not in OPEN:
        raise api_error(400, "INVALID_STATE", "Khiếu nại đã được trả lời.")
    if c.decided_by and c.decided_by == officer.id:
        raise api_error(403, "FORBIDDEN", "Cán bộ đã ra quyết định không tự xem xét khiếu nại về chính quyết định đó.")
    c.assigned_to, c.status = officer.id, "in_review" if c.status != "escalated" else c.status
    _log(c, officer.id, "assigned")
    return c


def extend(session: Session, complaint_id: str, officer: BuUser, days: int, note: str) -> BuComplaint:
    c = _get(session, complaint_id)
    if c.assigned_to != officer.id:
        raise api_error(403, "FORBIDDEN", "Chỉ cán bộ đang xem xét khiếu nại được gia hạn.")
    new_due = add_working_days(c.answer_due, max(1, int(days)))
    if new_due > c.max_due:
        raise api_error(400, "VALIDATION_ERROR", "Vượt thời hạn tối đa cho khiếu nại.", {"max_due": _iso(c.max_due)})
    if len(note.strip()) < 5:
        raise api_error(400, "VALIDATION_ERROR", "Ghi lý do gia hạn để báo người vay.", {"field": "note"})
    c.answer_due = new_due
    _log(c, officer.id, "extended", note=note.strip()[:300], answer_due=_iso(new_due))
    return c


def answer(session: Session, complaint_id: str, officer: BuUser, outcome: str, text: str) -> BuComplaint:
    c = _get(session, complaint_id)
    if c.status not in OPEN:
        raise api_error(400, "INVALID_STATE", "Khiếu nại đã được trả lời.")
    if c.assigned_to != officer.id:
        raise api_error(403, "FORBIDDEN", "Nhận xem xét khiếu nại trước khi trả lời.")
    if outcome not in OUTCOMES:
        raise api_error(400, "VALIDATION_ERROR", "Kết quả không hợp lệ.", {"field": "outcome"})
    if len((text or "").strip()) < 10:
        raise api_error(400, "VALIDATION_ERROR", "Câu trả lời cần nêu lý do (ít nhất 10 ký tự).", {"field": "text"})
    now = utcnow()
    c.status, c.outcome, c.answer, c.answered_at = "answered", outcome, text.strip()[:2000], now
    _log(c, officer.id, "answered", outcome=outcome, on_time=now <= c.answer_due)
    app_row = session.get(BuApplication, c.application_id) if c.application_id else None
    if outcome == "reopened" and app_row is not None and app_row.status in ("rejected", "offered", "expired"):
        from app.api.views import store

        doc = dict(app_row.doc or {})
        doc["escalation"] = {"why": "COMPLAINT", "complaint": c.id, "at": _iso(now)}
        store(app_row, doc, "escalated")
    case_id = c.application_id or c.id
    entry = chain.record(session, case_id, "complaint_answered",
                         {"complaint": c.id, "outcome": outcome, "officer": officer.id, "on_time": now <= c.answer_due})
    _log(c, "system", "on_chain", tx=entry.tx)
    events.log(session, case_id, "complaints", "complaint_answered",
               f"Trả lời khiếu nại {c.id}: {OUTCOMES[outcome]}", {"complaint": c.id})
    return c


def sweep_overdue(session: Session, now: datetime | None = None) -> list[BuComplaint]:
    """Scheduled: a complaint past its deadline goes to the lead (``escalated``), once."""
    now = now or utcnow()
    late = list(session.scalars(select(BuComplaint).where(BuComplaint.status.in_(("acknowledged", "in_review")),
                                                         BuComplaint.answer_due < now)))
    for c in late:
        c.status = "escalated"
        _log(c, "system", "escalated_overdue")
        events.log(session, c.application_id or c.id, "complaints", "complaint_overdue",
                   f"Khiếu nại {c.id} quá hạn trả lời: chuyển trưởng nhóm", {"complaint": c.id, "hidden_from_seller": True})
    session.flush()
    return late


def view(c: BuComplaint, staff: bool) -> dict[str, Any]:
    now = utcnow()
    out = {"id": c.id, "category": c.category, "category_label": CATEGORIES.get(c.category, c.category),
           "channel": c.channel, "text": c.text, "status": c.status, "application_id": c.application_id,
           "loan_id": c.loan_id, "reasons": c.reasons, "created_at": _iso(c.created_at), "ack_at": _iso(c.ack_at),
           "answer_due": _iso(c.answer_due), "max_due": _iso(c.max_due), "answered_at": _iso(c.answered_at),
           "outcome": c.outcome or None, "outcome_label": OUTCOMES.get(c.outcome) if c.outcome else None,
           "answer": c.answer or None, "overdue": c.status in OPEN and now > c.answer_due}
    extensions = [h for h in c.history or [] if h.get("what") == "extended"]
    if extensions:
        out["extension_note"] = extensions[-1].get("note")
    if staff:
        out.update(seller_user_id=c.seller_user_id, decided_by=c.decided_by or None, assigned_to=c.assigned_to or None,
                   history=c.history)
    return out
