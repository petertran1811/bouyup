"""Shapes an application for the API (contract section 3) and keeps the doc helpers.

Officers and admins see the full document. Sellers get the reduced view the
contract requires: no Agent 3 phases 0/1, no resolved concerns, no legal
results, no internal values, no AML flags or ``llm_notes``.
"""

from __future__ import annotations

import copy
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.blockchain import chain
from app.data_sources import consent as consent_mod
from app.platform import events
from app.platform.tables import BuApplication, BuUser, save_json
from app.platform.db.tables import utcnow

AML_FLAGS = ("RISK_PASS_THROUGH",)
# The seller answers the transfers question under a neutral key (AML secrecy).
QUESTION_ALIASES = {"RISK_PASS_THROUGH": "Q_TRANSFERS"}


def now_iso() -> str:
    return utcnow().isoformat() + "Z"


def today() -> date:
    return utcnow().date()


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def store(app_row: BuApplication, doc: dict[str, Any], status: str | None = None) -> None:
    """Persist the document (JSON columns only through ``save_json``) and touch ``updated_at``."""
    if status is not None:
        app_row.status = status
    save_json(app_row, "doc", doc)
    app_row.updated_at = utcnow()


def is_aml_code(code: str) -> bool:
    return code.startswith("AML-") or code in AML_FLAGS


_RECONSENT = ("consented", "needs_answer", "verified", "offered", "selected", "escalated")


def _next_action(app_row: BuApplication, doc: dict[str, Any]) -> dict[str, str]:
    s = app_row.status
    if s in _RECONSENT and consent_mod.blocked_reason(doc.get("consent")):
        return {"key": "consent", "label": "Ký lại ủy quyền"}
    if s == "draft":
        return {"key": "identity", "label": "Quét CCCD và khuôn mặt"}
    if s == "identified":
        return {"key": "consent", "label": "Ký ủy quyền"}
    if s == "consented":
        plan = doc.get("plan") or {}
        if app_row.tier == 2 and not plan.get("submitted"):
            return {"key": "plan", "label": "Gửi kế hoạch vay (ảnh doanh thu tùy chọn)"}
        return {"key": "verify", "label": "Chạy xác minh"}
    if s == "verifying":
        return {"key": "verify", "label": "Chạy xác minh"}
    if s == "needs_answer":
        return {"key": "answer", "label": "Trả lời câu hỏi xác minh"}
    if s in ("verified", "in_control"):
        return {"key": "wait_banks", "label": "Chờ kiểm soát và các ngân hàng duyệt hạn mức"}
    if s == "offered":
        return {"key": "select", "label": "Chọn số tiền và ngày trả"}
    if s == "selected":
        return {"key": "sign", "label": "Đọc bảng chi phí, hợp đồng và ký"}
    if s == "signed":
        return {"key": "wait_payout", "label": "Chờ các ngân hàng chuyển vốn vào tài khoản trung gian"}
    if s == "escalated":
        return {"key": "wait_officer", "label": "Chờ cán bộ tín dụng xem hồ sơ"}
    if s == "expired":
        return {"key": "reapply", "label": "Hạn mức hết hiệu lực; nộp hồ sơ mới"}
    if s in ("disbursed", "repaying", "closed"):
        return {"key": "view_loan", "label": "Xem khoản vay"}
    return {"key": "none", "label": "Không còn bước nào"}


def _seller_verification(v: dict[str, Any] | None) -> dict[str, Any] | None:
    if v is None:
        return None
    v = copy.deepcopy(v)
    v.pop("llm_notes", None)
    v["flags"] = [f for f in v.get("flags", []) if not is_aml_code(f["code"])]
    for q in v.get("questions", []):
        q["flag"] = QUESTION_ALIASES.get(q["flag"], q["flag"])
    v.get("derived", {}).pop("pass_through", None)
    v["tool_calls"] = [seller_tool_call(t) for t in v.get("tool_calls", [])]
    return v


def seller_tool_call(tc: dict[str, Any]) -> dict[str, Any]:
    tc = copy.deepcopy(tc)
    if isinstance(tc.get("output"), dict):
        tc["output"].pop("pass_through", None)
    return tc


def _seller_syndicate(syn: dict[str, Any] | None) -> dict[str, Any] | None:
    """The borrower sees the result (banks, shares, limit, expiry), not each bank's answer."""
    if syn is None:
        return None
    return {k: syn.get(k) for k in ("status", "limit", "split", "reduced", "approved_at", "expires_at", "hash")}


def _seller_control(c: dict[str, Any] | None) -> dict[str, Any] | None:
    if c is None:
        return None
    out: dict[str, Any] = {}
    if c.get("phase2"):
        # The debate itself (rounds, questions, answers) is staff-only, like phase 1.
        p2 = {k: v for k, v in c["phase2"].items()
              if k not in ("resolved", "ask", "change_rule", "rounds", "cap_reached", "no_acceptable_level")}
        out["phase2"] = p2
    if c.get("gate"):
        out["gate"] = {"decision": c["gate"]["decision"]}
    return out


def _seller_decision(d: dict[str, Any] | None) -> dict[str, Any] | None:
    """SELLER_SERVICES_PLAN §4: the seller reads Agent 3's explanation (headline, reasons, what to do)
    without the internal pointers (``ref``); staff see the decision as stored."""
    if not d or not isinstance(d.get("explanation"), dict):
        return d
    from app.agents.agent3_control import template_wording

    d = copy.deepcopy(d)
    exp = d["explanation"] = template_wording(d["explanation"])
    exp.pop("template", None)
    exp["because"] = [{"text": b.get("text")} for b in exp.get("because") or []]
    exp["improve"] = [{"text": i.get("text"), "action": i.get("action")} for i in exp.get("improve") or []]
    return d


def _seller_offer(offer: dict[str, Any] | None) -> dict[str, Any] | None:
    from app.agents.agent2_advise import seller_offer

    return seller_offer(offer)


def demo_sample(app_row: BuApplication) -> bool:
    """A case opened from one of the demo "Gian hàng mẫu" links, in a demo environment."""
    from app.data_sources import sources

    return sources.is_demo_sample(app_row.scenario)


def application_view(app_row: BuApplication, seller: BuUser | None, viewer: BuUser,
                     review_days: int = 2) -> dict[str, Any]:
    doc = app_row.doc or {}
    full = viewer.role in ("officer", "admin")
    verification = doc.get("verification")
    control = doc.get("control")
    if full:
        verification = copy.deepcopy(verification)
        if verification is not None:
            verification["llm_notes"] = (doc.get("internal") or {}).get("llm_notes", "")
    else:
        verification = _seller_verification(verification)
        control = _seller_control(control)
    out = {
        "id": app_row.id, "code": app_row.code, "status": app_row.status, "tier": app_row.tier,
        "created_at": iso(app_row.created_at), "updated_at": iso(app_row.updated_at),
        "seller": {"id": app_row.seller_user_id, "display_name": seller.display_name if seller else ""},
        "region": doc.get("region"), "currency": doc.get("currency"), "category": doc.get("category"),
        "stores": doc.get("stores", []), "identity": doc.get("identity"), "consent": doc.get("consent"),
        # HANDOVER 16.7: the store connection the case was made from (how ownership was proven).
        "shop_connection": doc.get("shop_connection"),
        "plan": doc.get("plan"), "verification": verification,
        "offer": doc.get("offer") if full else _seller_offer(doc.get("offer")),
        "proposal": doc.get("proposal"), "control": control,
        "decision": doc.get("decision") if full else _seller_decision(doc.get("decision")),
        "payee": doc.get("payee"), "human_request": doc.get("human_request"),
        "data_requests": doc.get("data_requests"),
        "loan_id": app_row.loan_id, "borrower_type": doc.get("borrower_type"),
        # 18/10/2026: a registered household business borrowing as "Cá nhân" (allowed, lower cap) is told why.
        "borrower_type_hint": doc.get("borrower_type_hint"),
        # A case made from a "Gian hàng mẫu" link in the demo (scenario data): the demo reset applies to it.
        "demo_sample": demo_sample(app_row),
        "statements": doc.get("statements"),
        "syndicate": doc.get("syndicate") if full else _seller_syndicate(doc.get("syndicate")),
        "selection": doc.get("selection"), "contract": doc.get("contract"),
        "next_action": _next_action(app_row, doc), "simulated": True,
        # Review 17/10/2026: the CCCD fields the OCR read (never the image) and the revenue screenshots.
        "cccd_scans": {side: {k: s.get(k) for k in ("side", "fields", "warnings", "at")}
                       for side, s in (doc.get("cccd_scans") or {}).items()} or None,
        "statement_images": [{k: i.get(k) for k in ("id", "month", "at", "ocr_read", "bytes")}
                             for i in doc.get("statement_images") or []],
    }
    escalation = doc.get("escalation") or {}
    if app_row.status == "escalated" and escalation.get("at"):
        out["expected_review_at"] = _review_date(escalation["at"], review_days)
    if full:
        out["escalation"] = doc.get("escalation")
        out["scenario"] = app_row.scenario
    return out


def _review_date(at: str, review_days: int) -> str | None:
    """Review item 4: an escalated case shows when an officer will have looked (``complaint.review_days``
    working days after the escalation)."""
    from app.agents.complaints import add_working_days

    try:
        start = datetime.fromisoformat(str(at).rstrip("Z"))
    except ValueError:
        return None
    return add_working_days(start, review_days).isoformat() + "Z"


def summary_view(app_row: BuApplication, seller: BuUser | None) -> dict[str, Any]:
    doc = app_row.doc or {}
    offer = doc.get("offer") or {}
    full = {"amount": offer["limit"]} if offer.get("limit") else None
    flags = (doc.get("verification") or {}).get("flags", [])
    stores = doc.get("stores") or [{}]
    return {
        "id": app_row.id, "code": app_row.code, "status": app_row.status, "tier": app_row.tier,
        "seller_name": seller.display_name if seller else "", "store_entity": stores[0].get("entity"),
        "amount_requested": doc.get("requested"), "amount_offered": full["amount"] if full else None,
        "grade": offer.get("grade"), "updated_at": iso(app_row.updated_at),
        "flags_open": sum(1 for f in flags if f["status"] == "open"),
        "deletable": not app_row.loan_id and app_row.status not in (
            "verifying", "in_control", "signed", "disbursed", "repaying", "closed", "withdrawn"),
    }


_SELLER_SAFE_ACTORS = ("agent1", "agent2", "seller", "system", "agent4", "agent4a", "agent4b", "code", "complaints")


def trace_view(session: Session, app_row: BuApplication, viewer: BuUser) -> dict[str, Any]:
    full = viewer.role in ("officer", "admin")
    tool_calls = ((app_row.doc or {}).get("verification") or {}).get("tool_calls", [])
    evs = events.for_application(session, app_row.id)
    entries = chain.public_entries(session, chain.case_entries(session, app_row.id))
    if full:
        return {"tool_calls": tool_calls, "events": [events.event_public(e) for e in evs], "chain": entries,
                "simulated": True}
    seller_events = []
    for e in evs:
        if e.payload.get("hidden_from_seller"):
            continue
        summary = e.summary if e.actor in _SELLER_SAFE_ACTORS else _GENERIC_SUMMARY.get(e.actor, "Đã ghi nhận")
        seller_events.append({"at": iso(e.at), "actor": e.actor, "kind": e.kind, "summary": summary,
                              "hash": e.hash})
    return {"tool_calls": [seller_tool_call(t) for t in tool_calls], "events": seller_events,
            "chain": entries, "simulated": True}


_GENERIC_SUMMARY = {
    "agent3": "Agent 3 kiểm soát độc lập; kết luận đã niêm phong trên chuỗi",
    "gate": "Cổng phê duyệt kiểm năm điều kiện",
    "officer": "Cán bộ tín dụng đã xem hồ sơ",
}
