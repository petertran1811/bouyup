"""/v4 loans, monitoring, alerts, portfolio (contract §4, §5 portfolio) and
``public_stats`` for /v4/public/overview. Banks use /v4/bank/* instead."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.platform.errors import api_error
from app.autopilot import loop as autopilot
from app.blockchain import chain
from app.core.stress import stress_shortfall
from app.agents import agent1_verify as verify
from app.agents import agent4b_monitor as agent4
from app.agents.agent4b_monitor import LOAN_LOCK, answer_notice, deliver_notices, OPEN_STATUSES, loan_shares, refresh_auto_switch, simulate_inflow, tick, today
from app.banks.split import MASTER_CODE
from app.core.params import active_params
from app.platform.security import require_roles
from app.platform.tables import BuAlert, BuApplication, BuBank, BuChainBlock, BuLoan, BuRepayment, BuUser
from app.platform.config import settings
from app.platform.audit import logger as audit_logger
from app.platform.db.session import get_session

router = APIRouter(tags=["v4-loans"])

_STAFF = ("officer", "admin")
_APPROVED = ("offered", "selected", "signed", "disbursed", "repaying", "closed", "expired")
_DECIDED = _APPROVED + ("rejected", "escalated", "out_of_scope")
_SIMULATION_ENVS = ("dev", "demo", "test")


class InflowIn(BaseModel):
    amount: int = Field(gt=0, le=1_000_000_000_000)
    # The platform's payout id: the same id is never swept twice (Agent 4 §3.4).
    payout_id: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")


class TransferIn(BaseModel):
    amount: int = Field(gt=0, le=1_000_000_000_000)
    kind: Literal["supplier", "personal", "securities", "real_estate", "other"]
    note: str = Field(default="", max_length=120)


class PrepayIn(BaseModel):
    amount: int | None = Field(default=None, gt=0, le=1_000_000_000_000)  # None: settle everything


class AdvanceIn(BaseModel):
    to: date  # move this loan's clock forward (demo): due dates, debits, penalty, reminders


class AccountIn(BaseModel):
    bank: str = Field(min_length=1, max_length=60)
    number: str = Field(pattern=r"^\d{6,20}$")


class NoticeAnswerIn(BaseModel):
    choice: str = Field(min_length=1, max_length=32)
    note: str = Field(default="", max_length=300)


class TickIn(BaseModel):
    as_of: date | None = None  # simulation date; default today


def _iso(dt: Any) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def alert_view(alert: BuAlert) -> dict[str, Any]:
    return {"id": alert.id, "loan_id": alert.loan_id, "level": alert.level, "signals": alert.signals or [],
            "text": alert.text, "at": _iso(alert.at), "acked": alert.acked}


def _early_warning(doc: dict[str, Any], staff: bool) -> dict[str, Any]:
    """Staff see the B11 score, weights and rule texts; the seller only the level and plain reasons."""
    from app.agents.agent4_llm import SELLER_SIGNAL

    ew = doc.get("early_warning") or {"score": 0.0, "level": "green", "signals": []}
    if staff:
        return ew
    return {"level": ew.get("level", "green"),
            "signals": [{"text": SELLER_SIGNAL[s["key"]]} for s in ew.get("signals", []) if s.get("key") in SELLER_SIGNAL]}


def loan_view(session: Session, loan: BuLoan, viewer: BuUser) -> dict[str, Any]:
    doc = loan.doc or {}
    names = {b.code: b.name for b in session.scalars(select(BuBank))}
    shares = loan_shares(session, loan.id)
    repayments = session.scalars(
        select(BuRepayment).where(BuRepayment.loan_id == loan.id).order_by(BuRepayment.at)).all()
    staff = viewer.role in _STAFF
    alerts = session.scalars(select(BuAlert).where(BuAlert.loan_id == loan.id).order_by(BuAlert.at.desc())).all()
    app_row = session.get(BuApplication, loan.application_id)
    seller = session.get(BuUser, loan.seller_user_id)
    params = active_params(session)
    open_ = loan.status in OPEN_STATUSES
    day = agent4.clock(doc)
    min_ok, min_why = agent4.minimum_allowed(doc, params) if open_ and "schedule" in doc else (False, "")
    account = dict(doc.get("account") or {})
    if not staff:  # the seller sees her own transfers without the monitoring flags
        account["transfers"] = [{k: v for k, v in t.items() if k not in ("flag", "alert_id", "chain_tx")}
                                for t in account.get("transfers") or []]
    return {
        "id": loan.id, "application_id": loan.application_id,
        "application_code": app_row.code if app_row else None,
        "seller_name": seller.display_name if seller else None,
        "status": loan.status, "currency": loan.currency,
        **{k: doc.get(k) for k in ("amount", "rate", "apr", "penalty_rate", "tenor_m", "method", "method_label",
                                   "due_day", "revenue_rate", "start_date", "first_due_date", "final_due_date",
                                   "total_interest", "total_due", "max_interest", "contract_id", "payee", "grade",
                                   "category", "event", "borrower_type", "schedule", "arrears", "principal_outstanding",
                                   "overdue_days", "max_overdue_days", "bureau", "majority", "receiving_account",
                                   "closed_on")},
        "clock": day.isoformat(),
        "owed_now": agent4.owed_now(doc) if "arrears" in doc else 0,
        "account": account,
        "next_due": agent4.next_row(doc) if "schedule" in doc else None,
        "minimum": {"allowed": min_ok, "why": min_why or None,
                    "quote": agent4.minimum_quote(doc, params) if min_ok else None},
        "prepay_quote": agent4.prepay_quote(doc, day) if open_ and "interest_to" in doc else None,
        "shares": [{"bank": s.bank_code, "name": names.get(s.bank_code, s.bank_code), "pct": s.pct,
                    "amount": s.amount, "repaid": s.repaid, "contract_id": s.contract_id,
                    "outstanding": round(int(doc.get("principal_outstanding") or 0) * s.pct)} for s in shares],
        "repaid": loan.repaid, "outstanding": loan.outstanding,
        "inflow_total": doc.get("inflow_total", 0),
        "repayments": [{"id": r.id, "at": _iso(r.at), "amount": r.swept,
                        "split": [x for x in r.split or [] if "bank" in x],
                        "detail": next((x for x in r.split or [] if "kind" in x), None),
                        "chain_tx": r.chain_tx} for r in repayments],
        "withdrawal_id": loan.withdrawal_id,
        "alerts": [alert_view(a) for a in alerts] if staff else [],
        "early_warning": _early_warning(doc, staff),
        "monitored_at": (doc.get("early_warning") or {}).get("at"),  # Agent 4's last automatic check
        "fate": doc.get("fate") if staff else None,
        "bank_report": doc.get("bank_report") if staff else None,
        "reminders": doc.get("reminders") or [],
        # Agent 4's notices to the seller (plain words; yellow ones ask the cause).
        "notices": [{k: n.get(k) for k in ("id", "at", "level", "kind", "text", "question", "answer")}
                    | ({"source": n.get("source"), "alert_id": n.get("alert_id")} if staff else {})
                    for n in doc.get("notices") or []],
        "use_of_funds": doc.get("use_of_funds"),
        "created_at": _iso(loan.created_at), "updated_at": _iso(loan.updated_at),
        "simulated": True,
    }


def _visible_loan(session: Session, loan_id: str, user: BuUser) -> BuLoan:
    loan = session.get(BuLoan, loan_id)
    if loan is None:
        raise api_error(404, "NOT_FOUND", "Không tìm thấy khoản vay.")
    if user.role == "seller" and loan.seller_user_id != user.id:
        raise api_error(403, "FORBIDDEN", "Bạn không có quyền xem khoản vay này.")
    return loan


@router.get("/loans")
def list_loans(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: BuUser = Depends(require_roles("seller", *_STAFF)),
    session: Session = Depends(get_session),
) -> dict:
    stmt = select(BuLoan).order_by(BuLoan.created_at.desc()).limit(limit)
    if user.role == "seller":
        stmt = stmt.where(BuLoan.seller_user_id == user.id)
    if status:
        stmt = stmt.where(BuLoan.status == status)
    return {"items": [loan_view(session, loan, user) for loan in session.scalars(stmt)]}


@router.get("/loans/{loan_id}")
def get_loan(
    loan_id: str,
    user: BuUser = Depends(require_roles("seller", *_STAFF)),
    session: Session = Depends(get_session),
) -> dict:
    return loan_view(session, _visible_loan(session, loan_id, user), user)


@router.post("/loans/{loan_id}/simulate-inflow")
def post_inflow(
    loan_id: str,
    body: InflowIn,
    user: BuUser = Depends(require_roles("seller", *_STAFF)),
    session: Session = Depends(get_session),
) -> dict:
    _simulation()
    with LOAN_LOCK:
        loan = _visible_loan(session, loan_id, user)
        session.refresh(loan)
        loan = simulate_inflow(session, loan, body.amount, body.payout_id)
        session.commit()
    if autopilot.enabled():  # Agent 4 reassesses this loan as soon as money arrives
        try:
            autopilot.assess_loan(loan.id, "tiền về")
        except Exception:  # noqa: BLE001 - the inflow is recorded; the next round reassesses
            audit_logger.warning("agent4_inflow_assess_failed", loan_id=loan.id)
        session.refresh(loan)
    return loan_view(session, loan, user)


def _simulation() -> None:
    if settings.app_env not in _SIMULATION_ENVS:
        raise api_error(404, "NOT_FOUND", "Mô phỏng chỉ có ở môi trường dev/demo.")


@router.post("/loans/{loan_id}/simulate-transfer")
def post_transfer(loan_id: str, body: TransferIn, user: BuUser = Depends(require_roles("seller", *_STAFF)),
                  session: Session = Depends(get_session)) -> dict:
    """Stage 6: money leaves the WeBank business account (watched by Agent 4)."""
    _simulation()
    with LOAN_LOCK:
        loan = _visible_loan(session, loan_id, user)
        session.refresh(loan)
        item = agent4.simulate_transfer(session, loan, body.amount, body.kind, body.note)
        session.commit()
    view = loan_view(session, loan, user)
    if user.role == "seller":
        item = {k: v for k, v in item.items() if k not in ("flag", "alert_id", "chain_tx")}
    return {**view, "transfer": item}


@router.post("/loans/{loan_id}/simulate-advance")
def post_advance(loan_id: str, body: AdvanceIn, user: BuUser = Depends(require_roles("seller", *_STAFF)),
                 session: Session = Depends(get_session)) -> dict:
    """Demo: move this loan's clock to ``to`` (Agent 4 runs every day in between: due dates,
    debits, grace, penalty, reminders, 30-day report)."""
    _simulation()
    pending: list[dict[str, Any]] = []
    with LOAN_LOCK:
        loan = _visible_loan(session, loan_id, user)
        session.refresh(loan)
        start = agent4.clock(loan.doc or {})
        if body.to < start:
            raise api_error(400, "VALIDATION_ERROR", "Ngày mô phỏng phải sau ngày hiện tại của khoản vay.",
                            {"field": "to", "clock": start.isoformat()})
        if (body.to - start).days > 1200:
            raise api_error(400, "VALIDATION_ERROR", "Mỗi lần tiến tối đa 1200 ngày.", {"field": "to"})
        day = start
        while day < body.to and loan.status in OPEN_STATUSES:
            day = min(body.to, day + timedelta(days=1))
            tick(session, day, loan_ids=[loan.id], refresh=False, deferred=pending)
        session.commit()
    deliver_notices(pending)
    session.refresh(loan)
    return loan_view(session, loan, user)


@router.post("/loans/{loan_id}/minimum")
def post_minimum(loan_id: str, user: BuUser = Depends(require_roles("seller")),
                 session: Session = Depends(get_session)) -> dict:
    """Stage 8: pay only the minimum at the next due date (instalment method)."""
    with LOAN_LOCK:
        loan = _visible_loan(session, loan_id, user)
        session.refresh(loan)
        agent4.choose_minimum(session, loan)
        session.commit()
    return loan_view(session, loan, user)


@router.post("/loans/{loan_id}/prepay")
def post_prepay(loan_id: str, body: PrepayIn | None = None, user: BuUser = Depends(require_roles("seller")),
                session: Session = Depends(get_session)) -> dict:
    """Stage 8: free prepayment from the business account (interest only for the days used)."""
    with LOAN_LOCK:
        loan = _visible_loan(session, loan_id, user)
        session.refresh(loan)
        result = agent4.prepay(session, loan, body.amount if body else None)
        session.commit()
    return {**loan_view(session, loan, user), "prepay": result}


@router.put("/loans/{loan_id}/receiving-account")
def put_receiving_account(loan_id: str, body: AccountIn, user: BuUser = Depends(require_roles("seller")),
                          session: Session = Depends(get_session)) -> dict:
    """Stage 9: after closing, the borrower may receive platform payouts at another bank."""
    with LOAN_LOCK:
        loan = _visible_loan(session, loan_id, user)
        agent4.change_receiving_account(session, loan, body.bank, body.number)
        session.commit()
    return loan_view(session, loan, user)


@router.get("/autopilot/status")
def autopilot_status(_: BuUser = Depends(require_roles(*_STAFF))) -> dict:
    """When Agent 4 and Agent 5 last ran on their own, what they found, when they run next."""
    return autopilot.status()


@router.post("/loans/{loan_id}/notices/{notice_id}/answer")
def post_notice_answer(
    loan_id: str,
    notice_id: str,
    body: NoticeAnswerIn,
    user: BuUser = Depends(require_roles("seller")),
    session: Session = Depends(get_session),
) -> dict:
    with LOAN_LOCK:
        loan = _visible_loan(session, loan_id, user)
        session.refresh(loan)  # the latest doc, read under the lock
        answer_notice(session, loan, notice_id, body.choice, body.note)
        session.commit()
    return loan_view(session, loan, user)


@router.post("/monitoring/tick")
def post_tick(
    body: TickIn | None = None,
    _: BuUser = Depends(require_roles(*_STAFF)),
    session: Session = Depends(get_session),
) -> dict:
    as_of = (body.as_of if body else None) or today()
    pending: list[dict[str, Any]] = []
    with LOAN_LOCK:
        alerts = tick(session, as_of, deferred=pending)
        escalated = verify.escalate_overdue(session, active_params(session), as_of)
        checked = session.scalar(select(func.count()).select_from(BuLoan).where(BuLoan.status.in_(OPEN_STATUSES)))
        session.commit()
    deliver_notices(pending)  # model drafts after commit, never inside the transaction
    return {"alerts": [alert_view(a) for a in alerts], "checked": int(checked or 0), "escalated": escalated,
            "simulated": True}


@router.get("/alerts")
def list_alerts(
    acked: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    _: BuUser = Depends(require_roles(*_STAFF)),
    session: Session = Depends(get_session),
) -> dict:
    stmt = select(BuAlert).order_by(BuAlert.at.desc()).limit(limit)
    if acked is not None:
        stmt = stmt.where(BuAlert.acked.is_(acked))
    return {"items": [alert_view(a) for a in session.scalars(stmt)]}


@router.post("/alerts/{alert_id}/ack")
def ack_alert(
    alert_id: str,
    _: BuUser = Depends(require_roles(*_STAFF)),
    session: Session = Depends(get_session),
) -> dict:
    alert = session.get(BuAlert, alert_id)
    if alert is None:
        raise api_error(404, "NOT_FOUND", "Không tìm thấy cảnh báo.")
    alert.acked = True
    session.commit()
    return alert_view(alert)


# --- portfolio ---------------------------------------------------------------

def _approval_rate(session: Session) -> float:
    counts = dict(session.execute(select(BuApplication.status, func.count()).group_by(BuApplication.status)).all())
    decided = sum(n for s, n in counts.items() if s in _DECIDED)
    approved = sum(n for s, n in counts.items() if s in _APPROVED)
    return round(approved / decided, 4) if decided else 0.0


@router.get("/portfolio")
def portfolio(
    _: BuUser = Depends(require_roles(*_STAFF)),
    session: Session = Depends(get_session),
) -> dict:
    loans = list(session.scalars(select(BuLoan)))
    open_loans = [ln for ln in loans if ln.status in OPEN_STATUSES]
    params = active_params(session)
    drop = float(params["stress"]["event_drop"])
    switches = sorted(refresh_auto_switch(session, params), key=lambda r: r.group_key)
    session.commit()
    outstanding = sum(ln.outstanding for ln in open_loans)
    by_bank: dict[str, int] = defaultdict(int)
    by_grade: dict[str, dict[str, int]] = defaultdict(lambda: {"loans": 0, "outstanding": 0})
    by_event: dict[str, dict[str, int]] = defaultdict(lambda: {"loans": 0, "exposure": 0, "shortfall_50pct": 0})
    overdue_total = 0
    for ln in open_loans:
        doc = ln.doc or {}
        for share in loan_shares(session, ln.id):
            by_bank[share.bank_code] += round(share.pct * ln.outstanding)
        overdue_total += agent4.owed_now(doc) if "arrears" in doc else 0
        grade = by_grade[str(doc.get("grade") or "?")]
        grade["loans"] += 1
        grade["outstanding"] += ln.outstanding
        event = by_event[str(doc.get("event") or "khác")]
        event["loans"] += 1
        event["exposure"] += int(doc.get("total_due", 0))
        event["shortfall_50pct"] += stress_shortfall(doc, drop)
    red = session.scalar(select(func.count()).select_from(BuAlert).where(
        BuAlert.level == "red", BuAlert.acked.is_(False))) or 0
    bank_total = sum(by_bank.values())
    return {
        "kpis": {
            "loans_active": len(open_loans), "outstanding": outstanding,
            "disbursed_total": sum(int((ln.doc or {}).get("amount", 0)) for ln in loans),
            "approval_rate": _approval_rate(session),
            "avg_amount": round(sum(int((ln.doc or {}).get("amount", 0)) for ln in loans) / len(loans)) if loans else 0,
            "red_alerts": int(red), "overdue_amount": overdue_total,
            "overdue_loans": sum(1 for ln in open_loans if ln.status == "overdue"),
        },
        "by_bank": [{"bank": code, "outstanding": amt, "share_pct": round(amt / bank_total, 4) if bank_total else 0.0}
                    for code, amt in sorted(by_bank.items(), key=lambda kv: -kv[1])],
        "by_grade": [{"grade": g, **v} for g, v in sorted(by_grade.items())],
        "by_event": [{"event": e, **v, "shortfall_ratio": round(v["shortfall_50pct"] / v["exposure"], 4)
                      if v["exposure"] else 0.0} for e, v in sorted(by_event.items())],
        "stress_drop": drop,
        "auto_approval": [switch_view(r) for r in switches],
        "simulated": True,
    }


def switch_view(row: Any) -> dict[str, Any]:
    return {"group": row.group_key, "enabled": row.enabled, "manual": row.manual, "npl_ratio": row.npl_ratio,
            "loans": row.loans, "bad": row.bad, "reason": row.reason or None, "updated_at": _iso(row.updated_at)}


def public_stats(session: Session) -> dict[str, Any]:
    """Numbers for the public overview (imported by api/public.py)."""
    def count(stmt: Any) -> int:
        return int(session.scalar(stmt) or 0)

    return {
        "sellers": count(select(func.count()).select_from(BuUser).where(BuUser.role == "seller")),
        "applications": count(select(func.count()).select_from(BuApplication)),
        "loans_active": count(select(func.count()).select_from(BuLoan).where(BuLoan.status.in_(OPEN_STATUSES))),
        "disbursed_total": sum(int((d or {}).get("amount", 0)) for d in session.scalars(select(BuLoan.doc))),
        "banks": count(select(func.count()).select_from(BuBank).where(
            BuBank.code != MASTER_CODE, BuBank.active.is_(True))),
        "chain_blocks": count(select(func.count()).select_from(BuChainBlock)),
        "agents": 5,
        "chain_mode": chain.mode(),
    }
