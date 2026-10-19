"""/v4/demo: helpers that only exist in a demo environment (APP_ENV dev/demo/test).

``POST /v4/demo/reset-my-loans`` ("Làm mới khoản vay mẫu"): POL-07 allows one loan at a time, so after a seller
borrowed through one demo "Gian hàng mẫu" every other sample store is rejected with POL-07. Instead of bending
that rule, this settles the seller's open loans that were opened from sample stores the normal way: a free
prepayment (``agent4b_monitor.prepay``: interest for the days used, the partner banks paid back, the credit
bureau told, the loan closed). When the simulated WeBank business account holds less than the payoff, the gap
is credited first as a demo top-up, kept apart from the sales inflows (``account.demo_topups``) so it never
counts as sales money for the seed loan. Sample applications waiting at "selected" are withdrawn (as
``DELETE /v4/applications/{id}``). Everything is logged (``demo_reset`` events) and anchored on the chain
(``demo_reset`` entries); nothing is deleted. Loans from the seller's own (non-sample) stores are never touched.
"""

from __future__ import annotations

import copy
import secrets
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import agent4b_monitor as agent4
from app.api import views
from app.blockchain import chain
from app.core.params import active_params
from app.data_sources import sources
from app.platform import events
from app.platform.db.session import get_session
from app.platform.db.tables import utcnow
from app.platform.errors import api_error
from app.platform.security import require_roles
from app.platform.tables import BuApplication, BuLoan, BuUser, save_json

router = APIRouter(prefix="/demo", tags=["v4-demo"])

_sellers = require_roles("seller")
OPEN_APP_STATUSES = ("selected",)


def _demo_only() -> None:
    if not sources.is_demo_env():
        raise api_error(404, "NOT_FOUND", "Chức năng này không khả dụng ở môi trường hiện tại.")


def _sample_loans(session: Session, user: BuUser) -> list[tuple[BuLoan, BuApplication | None, bool]]:
    """Open loans of the seller: (loan, application, opened from a sample store)."""
    out = []
    for loan in session.scalars(select(BuLoan).where(BuLoan.seller_user_id == user.id,
                                                     BuLoan.status.in_(agent4.OPEN_STATUSES))):
        app_row = session.get(BuApplication, loan.application_id)
        out.append((loan, app_row, bool(app_row is not None and sources.is_demo_sample(app_row.scenario))))
    return out


def _payoff(session: Session, loan: BuLoan) -> int:
    """What the free prepayment would take today (overdue + interest for the days used + principal)."""
    doc = copy.deepcopy(loan.doc or {})
    day = agent4.clock(doc)
    agent4._accrue_penalty(doc, active_params(session), day)
    return int(agent4.prepay_quote(doc, day)["total"])


def _plan(session: Session, user: BuUser) -> dict[str, Any]:
    loans = []
    for loan, app_row, sample in _sample_loans(session, user):
        loans.append({"loan_id": loan.id, "application_id": loan.application_id,
                      "application": app_row.code if app_row else None,
                      "scenario": app_row.scenario if app_row else None, "status": loan.status,
                      "outstanding": int(loan.outstanding), "payoff": _payoff(session, loan),
                      "balance": int(((loan.doc or {}).get("account") or {}).get("balance") or 0),
                      "sample": sample})
    apps = [{"application_id": a.id, "application": a.code, "scenario": a.scenario, "status": a.status}
            for a in session.scalars(select(BuApplication).where(BuApplication.seller_user_id == user.id,
                                                                 BuApplication.status.in_(OPEN_APP_STATUSES)))
            if sources.is_demo_sample(a.scenario) and not a.loan_id]
    return {"loans": loans, "applications": apps}


@router.get("/reset-my-loans")
def reset_preview(user: BuUser = Depends(_sellers), session: Session = Depends(get_session)) -> dict:
    """What the reset would do (for the button: show it when ``needed``)."""
    _demo_only()
    plan = _plan(session, user)
    needed = any(x["sample"] for x in plan["loans"]) or bool(plan["applications"])
    return {"needed": needed, **plan,
            "blocking_real_loans": [x for x in plan["loans"] if not x["sample"]], "simulated": True}


@router.post("/reset-my-loans")
def reset_my_loans(user: BuUser = Depends(_sellers), session: Session = Depends(get_session)) -> dict:
    _demo_only()
    settled, kept, withdrawn = [], [], []
    with agent4.LOAN_LOCK:
        for loan, app_row, sample in _sample_loans(session, user):
            session.refresh(loan)
            if not sample:
                kept.append({"loan_id": loan.id, "status": loan.status,
                             "why": "Khoản vay từ cửa hàng của bạn (không phải gian hàng mẫu): tự tất toán ở trang Khoản vay."})
                continue
            need = _payoff(session, loan)
            doc = copy.deepcopy(loan.doc or {})
            account = doc.setdefault("account", {})
            topup = max(0, need - int(account.get("balance") or 0))
            if topup:
                account["balance"] = int(account.get("balance") or 0) + topup
                account["demo_topups"] = (account.get("demo_topups") or [])[-49:] + [{
                    "id": "demo_" + secrets.token_hex(6), "amount": topup, "at": utcnow().isoformat() + "Z",
                    "on": agent4.clock(doc).isoformat(),
                    "why": "Làm mới khoản vay mẫu: nạp tiền để tất toán"}]
                save_json(loan, "doc", doc)
                session.flush()
            result = agent4.prepay(session, loan, None)
            payload = {"loan_id": loan.id, "application": app_row.code if app_row else None,
                       "scenario": app_row.scenario if app_row else None, "paid": result["paid"],
                       "interest": result["interest"], "principal": result["principal"], "topup": topup,
                       "status": loan.status, "simulated": True}
            entry = chain.record(session, loan.application_id, "demo_reset", payload)
            events.log(session, loan.application_id, "seller", "demo_reset",
                       f"Làm mới khoản vay mẫu: tất toán {result['paid']:,} (nạp thêm {topup:,})"
                       .replace(",", "."), {"loan_id": loan.id, "topup": topup}, hash_=entry.fingerprint)
            settled.append({**payload, "chain_tx": entry.tx})
        for row in session.scalars(select(BuApplication).where(BuApplication.seller_user_id == user.id,
                                                               BuApplication.status.in_(OPEN_APP_STATUSES))):
            if row.loan_id or not sources.is_demo_sample(row.scenario):
                continue
            doc = copy.deepcopy(row.doc or {})
            before = row.status
            doc["withdrawn"] = {"at": views.now_iso(), "status_before": before, "by": "demo_reset"}
            entry = chain.record(session, row.id, "application_withdrawn",
                                 {"application": row.code, "status_before": before, "by": "demo_reset"})
            doc["withdrawn"]["chain_tx"] = entry.tx
            events.log(session, row.id, "seller", "withdrawn",
                       f"Làm mới khoản vay mẫu: rút hồ sơ mẫu đang chờ ký (trạng thái trước: {before})",
                       hash_=entry.fingerprint)
            views.store(row, doc, "withdrawn")
            withdrawn.append({"application_id": row.id, "application": row.code, "status_before": before})
        session.commit()
    return {"settled": settled, "withdrawn": withdrawn, "kept": kept,
            "open_loans_left": sum(1 for _ in _sample_loans(session, user)), "simulated": True}
