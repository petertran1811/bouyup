"""Agent 4b · Giám sát khoản vay (loan circle, Stages 6–9) and the standing order that collects it.

Review item 3 (16/10/2026): monitoring runs for the whole life of the loan with low privilege, so it
holds no power to pay out (that is Agent 4a, :mod:`app.agents.agent4a_payout`, which this module never
imports). Within :func:`tick` the debits run as the borrower's standing order at WeBank (core banking,
simulated here; role ``standing_order``) and everything else (early warning, use of funds, reminders,
notices, the banks' report) runs as ``agent4b``: read-only for money (:mod:`app.platform.capabilities`).

Everything here is deterministic code (no LLM decides money). Functions ``flush``; the API layer commits.

- :func:`simulate_inflow` / :func:`simulate_transfer` — Stage 6: money in and out of the business
  account (platform payouts in; transfers out are watched for securities, real estate and large
  personal transfers).
- :func:`tick` — Stages 7–8 each day: on the due date the account is debited (penalty → interest →
  principal, interest by actual days), the money is passed to the banks pro rata to what each is
  owed; reminders 7 days and 1 day before; 3 days of grace then penalty interest; 30 days overdue →
  credit bureau report and the 2/3-majority note; a daily status report to the banks.
- :func:`choose_minimum`, :func:`prepay` — Stage 8: the minimum payment (instalment method only,
  tenor ≥ 3, at most 2 periods in a row) and free prepayment with interest only for the days used.
- Stage 9: fully repaid → closed, reported to the bureau, Agent 5 is told.
"""

from __future__ import annotations

import math
import secrets
import threading
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from app.blockchain import chain
from app.blockchain.chain_remote import ChainUnavailable
from app.blockchain.withdrawals import create_withdrawal, reference_code
from app.banks.split import split_largest_remainder, vn_number
from app.core import algorithm
from app.core.params import active_params
from app.data_sources import consent as consent_mod
from app.data_sources import sources
from app.platform import capabilities, events
from app.platform.config import settings
from app.platform.db.tables import utcnow
from app.platform.errors import api_error
from app.platform.tables import (BuAlert, BuApplication, BuAutoSwitch, BuBank, BuChainOutbox, BuLoan, BuLoanShare,
                                 BuRepayment, save_json)

OPEN_STATUSES = ("active", "overdue")
CATEGORY_KEYS = ("thời trang", "mỹ phẩm", "tạp hóa", "điện tử")
_GROUP_TO_CATEGORY = {"quần áo": "thời trang", "điện tử": "điện tử", "thực phẩm đóng gói": "tạp hóa",
                      "thực phẩm rời": "tạp hóa"}
TRANSFER_KINDS = {"supplier": "Trả nhà cung cấp", "personal": "Chuyển tài khoản cá nhân",
                  "securities": "Chuyển tài khoản chứng khoán", "real_estate": "Đặt cọc / mua bất động sản",
                  "other": "Chi khác cho kinh doanh"}
MISUSE_KINDS = ("securities", "real_estate")

# Every read-modify-write of a loan's JSON doc (monitoring, inflows, seller actions) runs under
# this lock, so the background monitor never writes back a stale doc over a request's change.
LOAN_LOCK = threading.RLock()


# --- small helpers -----------------------------------------------------------

def today() -> date:
    return utcnow().date()


def parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def clock(doc: dict[str, Any]) -> date:
    """The loan's own date: the last day Agent 4 processed (the demo moves it forward), never before today."""
    c = parse_date(doc.get("clock"))
    return max(c, today()) if c else today()


def category_of(doc: dict[str, Any]) -> str:
    """Prudence segment (thời trang, mỹ phẩm, …) from the application doc."""
    texts = [str(doc.get("category") or ""), str((doc.get("plan") or {}).get("group") or "")]
    texts += [str(s.get("category") or "") for s in doc.get("stores") or []]
    for text in texts:
        low = text.lower()
        if low in _GROUP_TO_CATEGORY:
            return _GROUP_TO_CATEGORY[low]
        for key in CATEGORY_KEYS:
            if key in low:
                return key
    return "khác"


def group_key(category: str, tier: int) -> str:
    """Auto-approval group (C12, [INFER]): industry segment × tier, e.g. ``thời trang|t2``."""
    return f"{category}|t{int(tier)}"


def _n(x: float) -> str:
    return vn_number(x)


def penalty_rate(params: dict[str, Any], rate: float) -> float:
    """Penalty interest on the overdue amount: 1.5 × the contract rate, never above the 24 % cap."""
    return round(min(rate * float(params["repay"]["penalty_mult"]), float(params["legal"]["rate_cap"])), 4)


def _arrears(doc: dict[str, Any]) -> dict[str, Any]:
    return doc.setdefault("arrears", {"penalty": 0, "interest": 0, "principal": 0, "since": None, "penalty_to": None})


def owed_now(doc: dict[str, Any]) -> int:
    a = _arrears(doc)
    return int(a["penalty"]) + int(a["interest"]) + int(a["principal"])


def overdue_days(doc: dict[str, Any], as_of: date) -> int:
    since = parse_date(_arrears(doc).get("since"))
    return max(0, (as_of - since).days) if since and owed_now(doc) > 0 else 0


def next_row(doc: dict[str, Any]) -> dict[str, Any] | None:
    return next((r for r in doc.get("schedule") or [] if r["status"] == "upcoming"), None)


def _monitor_seed(doc: dict[str, Any]) -> dict[str, Any]:
    derived = (doc.get("verification") or {}).get("derived") or {}
    store = (doc.get("stores") or [{}])[0] or {}
    return {"monthly_sales": int(derived.get("monthly_avg_12m") or 0), "rating": float(store.get("rating") or 0.0),
            "new_inquiry": False,
            "fate_baseline": int((doc.get("internal") or {}).get("fate_value") or derived.get("interbank_score") or 2)}


def _create_loan(session: Session, app_row: BuApplication, doc: dict[str, Any], loan_id: str,
                 contract: dict[str, Any], withdrawal_id: str, params: dict[str, Any]) -> BuLoan:
    existing = session.scalar(select(BuLoan).where(BuLoan.application_id == app_row.id).limit(1))
    if existing is not None:  # one loan per application, whatever path got here first
        raise api_error(409, "CONFLICT", "Hồ sơ đã có khoản vay; không giải ngân lần hai.", {"loan_id": existing.id})
    monitor = _monitor_seed(doc)
    start = today()
    category = category_of(doc)
    offer = doc.get("offer") or {}
    payee = contract["payee"]
    rows = [{"k": r["k"], "due_date": r["due_date"], "principal": r["principal"], "interest_est": r["interest"],
             "payment_est": r["payment"], "status": "upcoming", "choice": None} for r in contract["schedule"]]
    loan_doc = {
        **{k: contract[k] for k in ("amount", "rate", "apr", "tenor_m", "method", "method_label", "due_day",
                                    "revenue_rate", "first_due_date", "final_due_date", "total_interest",
                                    "total_due")},
        "max_interest": contract["total_interest"], "start_date": start.isoformat(), "clock": start.isoformat(),
        "contract_id": contract["id"], "contract_hash": contract.get("hash"), "penalty_rate": contract["penalty_rate"],
        "schedule": rows, "interest_to": start.isoformat(), "principal_outstanding": contract["amount"],
        "arrears": {"penalty": 0, "interest": 0, "principal": 0, "since": None, "penalty_to": None},
        "prudent": int(((offer.get("blocks") or {}).get("B4") or {}).get("prudent") or 0),
        "account": {"bank": "WeBank", "number": contract.get("webank_account"),
                    "balance": int(payee["to_account"]), "inflow_total": 0, "period_inflow": 0, "transfers": [],
                    "inflows": []},
        "payee": payee, "legs": contract["legs"],
        "grade": offer.get("grade"), "risk_group": offer.get("group"), "category": category,
        "tier": int(app_row.tier), "auto_group": group_key(category, int(app_row.tier)),
        "borrower_type": doc.get("borrower_type"), "event": (doc.get("plan") or {}).get("event") or "",
        "forecast": int(((offer.get("blocks") or {}).get("B4") or {}).get("prudent") or 0) * int(contract["tenor_m"]),
        "forecast_monthly": int(((offer.get("blocks") or {}).get("B4") or {}).get("forecast") or 0),
        "sweep_usable": float(((offer.get("blocks") or {}).get("B5") or {}).get("sweep_usable") or 0.0),
        "inflow_total": 0, "overdue_days": 0, "max_overdue_days": 0, "bureau": [], "majority": None,
        "monitor": monitor, "fate": {"baseline": monitor["fate_baseline"], "current": monitor["fate_baseline"], "at": None},
        "early_warning": {"score": 0.0, "level": "green", "signals": []},
        "reminders": [], "notices": [], "bank_report": None,
        "use_of_funds": {
            "status": "pending" if doc.get("plan") else "not_applicable",
            "due": (start + timedelta(days=int(params["use_of_funds"]["days"]))).isoformat(),
            "checked_at": None, "supplier": payee.get("supplier") or (doc.get("plan") or {}).get("supplier")},
        "receiving_account": {"bank": "WeBank", "number": contract.get("webank_account"), "locked": True},
    }
    loan = BuLoan(id=loan_id, application_id=app_row.id, seller_user_id=app_row.seller_user_id, status="active",
                  currency=str(doc.get("currency") or "CNY"), doc=loan_doc, repaid=0, outstanding=contract["amount"],
                  withdrawal_id=withdrawal_id, created_at=utcnow(), updated_at=utcnow())
    session.add(loan)
    for leg in contract["legs"]:  # the limit was reserved at signing (syndicate.reserve_at_signing)
        session.add(BuLoanShare(loan_id=loan_id, bank_code=leg["bank"], pct=leg["pct"], amount=leg["amount"],
                                repaid=0, contract_id=leg["contract_id"]))
    push_notice(loan_doc, _notice("info", f"Đã giải ngân {_n(contract['amount'])} {loan.currency}. Kỳ trả đầu ngày "
                                          f"{_vn_date(contract['first_due_date'])}, khoảng {_n(rows[0]['payment_est'])}. "
                                          "Chị để tiền hàng về tài khoản kinh doanh WeBank để hệ thống tự trích đúng hạn."))
    session.flush()
    return loan


def reserve_limit(session: Session, code: str, amount: int) -> None:
    """Atomically take ``amount`` from a bank's limit; refuse if it would exceed it."""
    result = session.execute(
        update(BuBank)
        .where(BuBank.code == code, BuBank.limit_used + amount <= BuBank.limit_total)
        .values(limit_used=BuBank.limit_used + amount)
        .execution_options(synchronize_session="fetch")
    )
    if result.rowcount != 1:
        raise api_error(400, "INVALID_STATE", f"{code}: vượt hạn mức còn lại, không giải ngân được.")


def release_limit(session: Session, code: str, amount: int) -> None:
    """Atomically give ``amount`` back to a bank's limit (never below zero)."""
    session.execute(
        update(BuBank)
        .where(BuBank.code == code)
        .values(limit_used=case((BuBank.limit_used >= amount, BuBank.limit_used - amount), else_=0))
        .execution_options(synchronize_session="fetch")
    )


def _set_app_status(app_row: BuApplication, status: str, *, loan_id: str | None = None) -> None:
    app_row.status = status
    if loan_id is not None:
        app_row.loan_id = loan_id
    app_row.updated_at = utcnow()


# --- money movements -----------------------------------------------------------

def loan_shares(session: Session, loan_id: str) -> list[BuLoanShare]:
    return list(session.scalars(select(BuLoanShare).where(BuLoanShare.loan_id == loan_id).order_by(BuLoanShare.id)))


MAX_NOTICES = 20


def push_notice(doc: dict[str, Any], notice: dict[str, Any]) -> None:
    """Newest first, at most MAX_NOTICES; a question the seller has not answered is never dropped."""
    notices = [notice, *(doc.get("notices") or [])]
    keep = [n for n in notices if n.get("question") and not n.get("answer")]
    rest = [n for n in notices if n not in keep][:max(0, MAX_NOTICES - len(keep))]
    doc["notices"] = sorted(keep + rest, key=lambda n: n.get("at") or "", reverse=True)


def _notice(level: str, text: str, kind: str = "info") -> dict[str, Any]:
    return {"id": "nt_" + secrets.token_hex(6), "at": utcnow().isoformat() + "Z", "level": level, "kind": kind,
            "text": text, "source": "code", "answer": None}


def _vn_date(value: Any) -> str:
    d = parse_date(value)
    return d.strftime("%d/%m/%Y") if d else str(value)


def _pay_banks(session: Session, loan: BuLoan, doc: dict[str, Any], amount: int, breakdown: dict[str, int],
               kind: str, as_of: date) -> None:
    """Pass a collected amount to the banks pro rata to their share of the loan (each bank is owed
    its share of every part: they funded the same loan in fixed proportions)."""
    capabilities.require("debit")
    shares = loan_shares(session, loan.id)
    parts = split_largest_remainder(amount, [round(s.pct * 10_000) for s in shares])
    split = [{"bank": s.bank_code, "amount": a} for s, a in zip(shares, parts)]
    for share, part in zip(shares, parts):
        share.repaid = int(share.repaid) + part
    repayment_id = "rp_" + secrets.token_hex(8)
    entry = chain.record(session, loan.application_id, "repayment", {
        "loan_id": loan.id, "repayment_id": repayment_id, "kind": kind, "amount": amount, "breakdown": breakdown,
        "split": split, "as_of": as_of.isoformat()})
    session.add(BuRepayment(id=repayment_id, loan_id=loan.id, inflow=amount, swept=amount,
                            split=[*split, {"kind": kind, **breakdown, "as_of": as_of.isoformat()}],
                            chain_tx=entry.tx, at=utcnow()))
    loan.repaid = int(loan.repaid) + amount
    app_row = session.get(BuApplication, loan.application_id)
    if app_row is not None and app_row.status == "disbursed":
        _set_app_status(app_row, "repaying")
    events.log(session, loan.application_id, "agent4", "repayment",
               f"Thu {_n(amount)} ({kind}): lãi phạt {_n(breakdown['penalty'])}, lãi {_n(breakdown['interest'])}, "
               f"gốc {_n(breakdown['principal'])}; chia các ngân hàng theo tỷ lệ",
               {"loan_id": loan.id, "split": split}, entry.fingerprint)


def _collect(session: Session, loan: BuLoan, doc: dict[str, Any], as_of: date, kind: str) -> int:
    """Debit the business account for what is due (penalty → interest → principal). The standing
    order's move: refused while Agent 4b (monitoring) acts."""
    capabilities.require("debit")
    a = _arrears(doc)
    account = doc["account"]
    take = min(int(account["balance"]), owed_now(doc))
    if take <= 0:
        return 0
    left = take
    breakdown = {}
    for part in ("penalty", "interest", "principal"):
        x = min(left, int(a[part]))
        a[part] = int(a[part]) - x
        breakdown[part] = x
        left -= x
    account["balance"] = int(account["balance"]) - take
    doc["principal_outstanding"] = int(doc["principal_outstanding"]) - breakdown["principal"]
    loan.outstanding = int(doc["principal_outstanding"])
    _pay_banks(session, loan, doc, take, breakdown, kind, as_of)
    if owed_now(doc) == 0:
        a["since"], a["penalty_to"] = None, None
        doc["overdue_days"] = 0  # max_overdue_days keeps the history (Stage 10)
        for r in doc["schedule"]:
            if r["status"] == "overdue":
                r["status"] = "paid_late"
    return take


def _accrue_penalty(doc: dict[str, Any], params: dict[str, Any], as_of: date) -> None:
    """After the grace days, penalty interest on the overdue interest and principal, by actual days."""
    a = _arrears(doc)
    since = parse_date(a.get("since"))
    base = int(a["interest"]) + int(a["principal"])
    if since is None or base <= 0:
        return
    start = since + timedelta(days=int(params["repay"]["grace_days"]))
    frm = max(parse_date(a.get("penalty_to")) or start, start)
    if as_of > frm:
        a["penalty"] = int(a["penalty"]) + algorithm.interest_for(base, float(doc["penalty_rate"]), (as_of - frm).days)
        a["penalty_to"] = as_of.isoformat()


def _spread(rows: list[dict[str, Any]], amount: int) -> None:
    """Spread ``amount`` of principal over the remaining rows (the last one takes the remainder)."""
    if not rows or amount <= 0:
        return
    each = amount // len(rows)
    for r in rows:
        r["principal"] = int(r["principal"]) + each
    rows[-1]["principal"] = int(rows[-1]["principal"]) + amount - each * len(rows)


def _replan(doc: dict[str, Any]) -> None:
    """After a prepayment: the principal not yet due is spread again over the remaining periods."""
    upcoming = [r for r in doc["schedule"] if r["status"] == "upcoming"]
    if not upcoming:
        return
    open_principal = int(doc["principal_outstanding"]) - int(_arrears(doc)["principal"])
    for r in upcoming:
        r["principal"] = 0
    _spread(upcoming, max(0, open_principal))


def _process_due(session: Session, loan: BuLoan, doc: dict[str, Any], params: dict[str, Any],
                 row: dict[str, Any]) -> None:
    """One due date: interest by actual days on the principal owed, the period's principal by the
    method (or the minimum the borrower chose), then the automatic debit."""
    d = parse_date(row["due_date"])
    prev = parse_date(doc["interest_to"]) or d
    a = _arrears(doc)
    interest = algorithm.interest_for(int(doc["principal_outstanding"]), float(doc["rate"]), max(0, (d - prev).days))
    doc["interest_to"] = d.isoformat()
    open_principal = int(doc["principal_outstanding"]) - int(a["principal"])
    later = [r for r in doc["schedule"] if r["status"] == "upcoming" and r["k"] > row["k"]]
    amount, tenor = int(doc["amount"]), int(doc["tenor_m"])
    if not later:
        principal = open_principal
    elif doc["method"] == "installment":
        principal = min(open_principal, int(row["principal"]))
        if row.get("choice") == "minimum":
            minimum = min(principal, math.ceil(float(params["repay"]["min_principal_share"]) * amount / tenor))
            _spread(later, principal - minimum)
            principal = minimum
    else:
        revenue = int(doc["account"].get("period_inflow", 0))
        pay = max(algorithm.min_payment(params, amount, tenor, interest),
                  round(float(doc.get("revenue_rate") or 0) * revenue))
        principal = min(open_principal, max(0, pay - interest))
        row["revenue_base"] = revenue
    doc["account"]["period_inflow"] = 0
    a["interest"] = int(a["interest"]) + interest
    a["principal"] = int(a["principal"]) + principal
    row.update(interest=interest, principal_due=principal, amount_due=interest + principal,
               processed_on=d.isoformat())
    paid = _collect(session, loan, doc, d, "minimum" if row.get("choice") == "minimum" else "due")
    row["paid"] = paid
    if owed_now(doc) > 0:
        row["status"] = "overdue"
        a["since"] = a.get("since") or d.isoformat()
        push_notice(doc, _notice("warn", f"Kỳ {row['k']} ngày {_vn_date(d)}: tài khoản chỉ đủ trích {_n(paid)}, còn thiếu "
                                         f"{_n(owed_now(doc))}. Chị nộp thêm trong {params['repay']['grace_days']} ngày "
                                         "ân hạn để không bị tính lãi phạt.", "overdue"))
    else:
        row["status"] = "minimum" if row.get("choice") == "minimum" else "paid"
        push_notice(doc, _notice("info", f"Kỳ {row['k']} ngày {_vn_date(d)}: đã trích {_n(paid)} (lãi {_n(interest)} cho "
                                         f"{(d - prev).days} ngày, gốc {_n(principal)}). Dư nợ gốc còn "
                                         f"{_n(doc['principal_outstanding'])}.", "due"))


def _maybe_close(session: Session, loan: BuLoan, doc: dict[str, Any], as_of: date) -> None:
    if int(doc["principal_outstanding"]) > 0 or owed_now(doc) > 0:
        return
    from app.autopilot import loop as autopilot

    autopilot.mark_agent5_due("khoản vay tất toán")  # a real outcome for the post-audit
    loan.status = "closed"
    doc["closed_at"] = utcnow().isoformat() + "Z"
    doc["closed_on"] = as_of.isoformat()
    doc["early_warning"] = {"score": 0.0, "level": "green", "signals": []}
    for r in doc["schedule"]:
        if r["status"] == "upcoming":
            r["status"] = "prepaid"
    for share in loan_shares(session, loan.id):
        release_limit(session, share.bank_code, int(share.amount))
    for alert in session.scalars(select(BuAlert).where(BuAlert.loan_id == loan.id, BuAlert.acked.is_(False))):
        alert.acked = True
    _report_bureau(session, loan, doc, "closed", as_of)
    doc["receiving_account"] = {**(doc.get("receiving_account") or {}), "locked": False}
    push_notice(doc, _notice("info", "Chị đã trả hết khoản vay. BuoyUp đã báo trung tâm thông tin tín dụng. Từ giờ chị "
                                     "có thể đổi tài khoản nhận tiền hàng; khi cần vốn, chị vay lại với hồ sơ cập nhật.",
                             "closed"))
    app_row = session.get(BuApplication, loan.application_id)
    if app_row is not None:
        _set_app_status(app_row, "closed")


def _report_bureau(session: Session, loan: BuLoan, doc: dict[str, Any], kind: str, as_of: date) -> None:
    """Report to the credit information center (PBOC): 30 days overdue, or the loan closed."""
    payload = {"loan_id": loan.id, "kind": kind, "as_of": as_of.isoformat(),
               "principal_outstanding": int(doc["principal_outstanding"]), "overdue_days": overdue_days(doc, as_of),
               "max_overdue_days": int(doc.get("max_overdue_days") or 0)}
    entry = chain.record(session, loan.application_id, "bureau_report", payload)
    doc.setdefault("bureau", []).append({**payload, "tx": entry.tx})
    events.log(session, loan.application_id, "agent4", "bureau_report",
               {"overdue_30": f"Quá hạn {payload['overdue_days']} ngày: báo trung tâm thông tin tín dụng",
                "closed": "Tất toán: báo trung tâm thông tin tín dụng (đã trả hết)"}[kind],
               {"loan_id": loan.id}, entry.fingerprint)


def _majority(session: Session, loan: BuLoan, params: dict[str, Any]) -> dict[str, Any]:
    """Collection steps after 30 days are decided by banks holding at least 2/3 of what is owed."""
    shares = sorted(loan_shares(session, loan.id), key=lambda s: -s.pct)
    need = float(params["repay"]["majority"])
    group, total = [], 0.0
    for s in shares:
        group.append(s.bank_code)
        total += s.pct
        if total >= need - 1e-9:
            break
    return {"banks": group, "share": round(total, 4), "need": need,
            "text": f"Các bước xử lý nợ do nhóm ngân hàng nắm {round(total * 100)}% dư nợ quyết định "
                    f"({', '.join(group)}; cần ≥ {round(need * 100, 2):g}%)"}


# --- Stage 6: the business account ---------------------------------------------------

def simulate_inflow(session: Session, loan: BuLoan, amount: int, payout_id: str | None = None) -> BuLoan:
    """A platform payout reaches the WeBank business account. Money arriving while something is due
    is debited at once. A payout id already processed is skipped (never counted twice)."""
    if loan.status not in OPEN_STATUSES:
        raise api_error(400, "INVALID_STATE", "Khoản vay đã tất toán.")
    if amount <= 0:
        raise api_error(400, "VALIDATION_ERROR", "Số tiền về phải lớn hơn 0.", {"field": "amount"})
    doc = dict(loan.doc or {})
    seen = list(doc.get("payout_ids") or [])
    if payout_id:
        if payout_id in seen:
            events.log(session, loan.application_id, "agent4", "payout_duplicate",
                       f"Payout {payout_id} đã xử lý: bỏ qua", {"loan_id": loan.id})
            return loan
        doc["payout_ids"] = seen[-200:] + [payout_id]
    day = clock(doc)
    account = doc["account"]
    account["balance"] = int(account["balance"]) + amount
    account["inflow_total"] = int(account.get("inflow_total", 0)) + amount
    account["period_inflow"] = int(account.get("period_inflow", 0)) + amount
    account["inflows"] = (account.get("inflows") or [])[-49:] + [{"on": day.isoformat(), "amount": amount}]
    doc["inflow_total"] = account["inflow_total"]
    events.log(session, loan.application_id, "agent4", "inflow",
               f"Tiền hàng về tài khoản kinh doanh WeBank {_n(amount)}; số dư {_n(account['balance'])}",
               {"loan_id": loan.id})
    if owed_now(doc) > 0:
        _accrue_penalty(doc, active_params(session), day)
        _collect(session, loan, doc, day, "overdue")
        if owed_now(doc) == 0:
            loan.status = "active"
    _maybe_close(session, loan, doc, day)
    loan.updated_at = utcnow()
    save_json(loan, "doc", doc)
    session.flush()
    return loan


def simulate_transfer(session: Session, loan: BuLoan, amount: int, kind: str, note: str = "") -> dict[str, Any]:
    """Money leaves the business account. Securities and real estate are a misuse of a business
    loan (red); a transfer to a personal account above 30 % of the loan is flagged (yellow)."""
    if loan.status not in OPEN_STATUSES:
        raise api_error(400, "INVALID_STATE", "Khoản vay đã tất toán.")
    if kind not in TRANSFER_KINDS:
        raise api_error(400, "VALIDATION_ERROR", "Loại giao dịch không hợp lệ.", {"field": "kind"})
    doc = dict(loan.doc or {})
    account = doc["account"]
    if amount <= 0 or amount > int(account["balance"]):
        raise api_error(400, "VALIDATION_ERROR", "Số tiền phải lớn hơn 0 và không vượt số dư.", {"field": "amount"})
    params = active_params(session)
    day = clock(doc)
    account["balance"] = int(account["balance"]) - amount
    flag = None
    if kind in MISUSE_KINDS:
        flag = {"key": "misuse", "level": "red", "text": f"{TRANSFER_KINDS[kind]} từ tài khoản kinh doanh: dùng vốn sai mục đích"}
    elif kind == "personal" and amount > float(params["repay"]["large_personal_transfer"]) * int(doc["amount"]):
        flag = {"key": "large_personal", "level": "yellow",
                "text": "Chuyển lớn sang tài khoản cá nhân (trên 30% khoản vay)"}
    item = {"on": day.isoformat(), "amount": amount, "kind": kind, "label": TRANSFER_KINDS[kind],
            "note": note.strip()[:120], "flag": flag}
    account["transfers"] = (account.get("transfers") or [])[-49:] + [item]
    events.log(session, loan.application_id, "agent4", "transfer_flag" if flag else "transfer",
               f"{TRANSFER_KINDS[kind]} {_n(amount)}" + (f" → {flag['text']}" if flag else ""),
               {"loan_id": loan.id, "kind": kind, "hidden_from_seller": bool(flag)})
    if flag:
        doc.setdefault("flags", []).append({**flag, "on": day.isoformat()})
        alert = _raise_alert(session, loan, {"level": flag["level"], "signals": [
            {"key": flag["key"], "weight": 0.0, "text": flag["text"]}]})
        if flag["level"] == "red":
            from app.autopilot import loop as autopilot

            autopilot.mark_agent5_due("dùng vốn sai mục đích")
            entry = chain.record(session, loan.application_id, "misuse_flag", {"loan_id": loan.id, **item})
            item["chain_tx"] = entry.tx
        item["alert_id"] = alert.id
    loan.updated_at = utcnow()
    save_json(loan, "doc", doc)
    session.flush()
    return item


def change_receiving_account(session: Session, loan: BuLoan, bank: str, number: str) -> dict[str, Any]:
    """Stage 9: after the loan is closed the borrower may receive platform payouts elsewhere."""
    doc = dict(loan.doc or {})
    if loan.status != "closed":
        raise api_error(400, "INVALID_STATE", "Chỉ đổi tài khoản nhận tiền hàng sau khi tất toán.")
    doc["receiving_account"] = {"bank": bank.strip(), "number": number.strip(), "locked": False,
                                "changed_at": utcnow().isoformat() + "Z"}
    save_json(loan, "doc", doc)
    events.log(session, loan.application_id, "seller", "receiving_account",
               f"Đổi tài khoản nhận tiền hàng sang {bank.strip()}", {"loan_id": loan.id})
    return doc["receiving_account"]


# --- Stage 8: minimum payment, prepayment -----------------------------------------------

def minimum_allowed(doc: dict[str, Any], params: dict[str, Any]) -> tuple[bool, str]:
    rp = params["repay"]
    row = next_row(doc)
    if doc.get("method") != "installment":
        return False, "Trả tối thiểu chỉ áp dụng cho hình thức trả góp cố định."
    if int(doc["tenor_m"]) < int(rp["min_tenor_m"]):
        return False, f"Trả tối thiểu cần kỳ hạn từ {rp['min_tenor_m']} tháng."
    if row is None or row["k"] == int(doc["tenor_m"]):
        return False, "Kỳ cuối phải trả đủ."
    if row.get("choice") == "minimum":
        return False, "Kỳ này đã chọn trả tối thiểu."
    before = [r for r in doc["schedule"] if r["k"] < row["k"]][-int(rp["min_max_consecutive"]):]
    if len(before) == int(rp["min_max_consecutive"]) and all(r.get("choice") == "minimum" for r in before):
        return False, f"Không được trả tối thiểu quá {rp['min_max_consecutive']} kỳ liên tiếp."
    if owed_now(doc) > 0:
        return False, "Chị cần trả hết khoản quá hạn trước."
    return True, ""


def minimum_quote(doc: dict[str, Any], params: dict[str, Any]) -> dict[str, Any] | None:
    row = next_row(doc)
    if row is None:
        return None
    d = parse_date(row["due_date"])
    interest = algorithm.interest_for(int(doc["principal_outstanding"]), float(doc["rate"]),
                                      max(0, (d - parse_date(doc["interest_to"])).days))
    principal = min(int(row["principal"]), math.ceil(float(params["repay"]["min_principal_share"])
                                                     * int(doc["amount"]) / int(doc["tenor_m"])))
    return {"k": row["k"], "due_date": row["due_date"], "interest": interest, "principal": principal,
            "payment": interest + principal, "full_payment": interest + int(row["principal"]),
            "deferred": int(row["principal"]) - principal}


def choose_minimum(session: Session, loan: BuLoan) -> dict[str, Any]:
    doc = dict(loan.doc or {})
    params = active_params(session)
    ok, why = minimum_allowed(doc, params)
    if not ok:
        raise api_error(400, "INVALID_STATE", why)
    quote = minimum_quote(doc, params)
    row = next_row(doc)
    row["choice"] = "minimum"
    push_notice(doc, _notice("info", f"Kỳ {row['k']} chị chọn trả tối thiểu {_n(quote['payment'])} (lãi + 30% gốc kỳ). "
                                     f"Phần gốc {_n(quote['deferred'])} được chia đều cho các kỳ sau; lãi vẫn tính trên "
                                     "dư nợ gốc còn lại.", "minimum"))
    events.log(session, loan.application_id, "seller", "minimum_payment",
               f"Chọn trả tối thiểu kỳ {row['k']}: {_n(quote['payment'])}", {"loan_id": loan.id})
    save_json(loan, "doc", doc)
    return quote


def prepay_quote(doc: dict[str, Any], as_of: date) -> dict[str, Any]:
    """Pay everything today: what is overdue, interest only for the days used since the last due date, the principal."""
    days = max(0, (as_of - (parse_date(doc["interest_to"]) or as_of)).days)
    interest = algorithm.interest_for(int(doc["principal_outstanding"]), float(doc["rate"]), days)
    a = _arrears(doc)
    open_principal = int(doc["principal_outstanding"]) - int(a["principal"])
    return {"as_of": as_of.isoformat(), "overdue": owed_now(doc), "interest_days": days, "interest": interest,
            "principal": open_principal, "total": owed_now(doc) + interest + open_principal, "fee": 0}


def prepay(session: Session, loan: BuLoan, amount: int | None) -> dict[str, Any]:
    """Free prepayment from the business account. ``amount`` None = settle everything."""
    if loan.status not in OPEN_STATUSES:
        raise api_error(400, "INVALID_STATE", "Khoản vay đã tất toán.")
    doc = dict(loan.doc or {})
    params = active_params(session)
    day = clock(doc)
    _accrue_penalty(doc, params, day)
    q = prepay_quote(doc, day)
    want = q["total"] if amount is None else int(amount)
    if want <= 0 or want > int(doc["account"]["balance"]):
        raise api_error(400, "VALIDATION_ERROR", "Số dư tài khoản kinh doanh không đủ cho khoản trả trước này.",
                        {"balance": int(doc["account"]["balance"]), "needed": want})
    want = min(want, q["total"])
    paid_overdue = _collect(session, loan, doc, day, "overdue") if owed_now(doc) else 0
    left = want - paid_overdue
    interest = min(left, q["interest"])
    principal = min(left - interest, int(doc["principal_outstanding"]) - int(_arrears(doc)["principal"]))
    if interest + principal > 0:
        doc["account"]["balance"] = int(doc["account"]["balance"]) - interest - principal
        doc["principal_outstanding"] = int(doc["principal_outstanding"]) - principal
        loan.outstanding = int(doc["principal_outstanding"])
        if interest == q["interest"]:
            doc["interest_to"] = day.isoformat()
        _pay_banks(session, loan, doc, interest + principal, {"penalty": 0, "interest": interest, "principal": principal},
                   "prepay", day)
    _replan(doc)
    push_notice(doc, _notice("info", f"Trả trước {_n(want)} không mất phí: lãi {_n(interest)} cho {q['interest_days']} ngày "
                                     f"đã dùng, gốc {_n(principal)}. Dư nợ gốc còn {_n(doc['principal_outstanding'])}.",
                             "prepay"))
    _maybe_close(session, loan, doc, day)
    if loan.status != "closed" and owed_now(doc) == 0:
        loan.status = "active"
    loan.updated_at = utcnow()
    save_json(loan, "doc", doc)
    session.flush()
    return {"paid": want, "interest": interest, "principal": principal, "overdue": paid_overdue,
            "principal_outstanding": int(doc["principal_outstanding"]), "status": loan.status}


# --- Stage 7: monitoring ------------------------------------------------------------

_SIGNAL_TEXT = {
    "sales_low": "Doanh số tháng thấp hơn {mult:g} lần khoản trả tháng",
    "rating_low": "Điểm cửa hàng dưới {rating:g}",
    "low_balance": "Số dư tài khoản kinh doanh chưa đủ cho kỳ trả sắp tới",
    "new_inquiry": "Có tra cứu tín dụng mới ở nơi khác",
    "fate_worse": "Điểm FATE chấm lại xấu đi",
    "large_personal": "Chuyển lớn sang tài khoản cá nhân",
}


def assess(loan: BuLoan, params: dict[str, Any], as_of: date, fate_allowed: bool = True,
           fate_score: int | None = None) -> dict[str, Any]:
    """Early warning for one loan: weighted signals, then hard levels (misuse, overdue)."""
    ew = params["early_warning"]
    doc = loan.doc or {}
    weights = ew["weights"]
    monitor = doc.get("monitor") or {}
    row = next_row(doc)
    monthly_due = int(row["payment_est"]) if row else 0
    baseline = int((doc.get("fate") or {}).get("baseline", 2))
    last = int((doc.get("fate") or {}).get("current", baseline))
    fate_current = int(fate_score) if fate_allowed and fate_score is not None else last
    days_to_due = (parse_date(row["due_date"]) - as_of).days if row else 999
    recent = [f for f in doc.get("flags") or [] if (as_of - (parse_date(f.get("on")) or as_of)).days <= 30]
    fired = {
        "sales_low": monthly_due > 0 and int(monitor.get("monthly_sales", 0)) < ew["sales_mult"] * monthly_due,
        "rating_low": float(monitor.get("rating", 5.0)) < ew["rating_min"],
        "low_balance": row is not None and 0 <= days_to_due <= 7 and int(doc["account"]["balance"]) < monthly_due,
        "new_inquiry": bool(monitor.get("new_inquiry")),
        "fate_worse": fate_current > baseline,
        "large_personal": any(f["key"] == "large_personal" for f in recent),
    }
    args = {"mult": ew["sales_mult"], "rating": ew["rating_min"]}
    signals = [{"key": k, "weight": float(weights.get(k, 0.0)), "text": _SIGNAL_TEXT[k].format(**args)}
               for k, on in fired.items() if on]
    score = round(sum(s["weight"] for s in signals), 2)
    level = "red" if score >= ew["red"] else "yellow" if score >= ew["yellow"] else "green"
    days = overdue_days(doc, as_of)
    if owed_now(doc) > 0:  # a debit that failed today is already overdue, even at day 0
        signals.append({"key": "overdue", "weight": 0.0,
                        "text": f"Quá hạn {days} ngày" if days else "Kỳ trả hôm nay chưa trích đủ"})
        level = "red" if days >= ew["overdue_red_days"] else ("yellow" if level == "green" else level)
    if any(f["key"] == "misuse" for f in recent):
        signals.append({"key": "misuse", "weight": 0.0, "text": "Dùng vốn sai mục đích (chứng khoán / bất động sản)"})
        level = "red"
    return {"score": score, "level": level, "signals": signals, "overdue_days": days, "fate": fate_current}


def _reminders(doc: dict[str, Any], params: dict[str, Any], as_of: date) -> list[str]:
    row = next_row(doc)
    if row is None:
        return []
    left = (parse_date(row["due_date"]) - as_of).days
    if left not in [int(x) for x in params["repay"]["reminder_days"]]:
        return []
    balance = int(doc["account"]["balance"])
    text = (f"Còn {left} ngày đến kỳ {row['k']} ({_vn_date(row['due_date'])}): khoảng {_n(row['payment_est'])}. "
            f"Số dư tài khoản kinh doanh {_n(balance)}.")
    if balance < int(row["payment_est"]):
        text += " Số dư chưa đủ, chị nộp thêm trước ngày trả."
    return [text]


def _bank_report(session: Session, loan: BuLoan, doc: dict[str, Any], as_of: date) -> dict[str, Any]:
    """The daily status every partner bank sees for its share."""
    principal = int(doc["principal_outstanding"])
    return {"as_of": as_of.isoformat(), "status": loan.status, "principal_outstanding": principal,
            "overdue": owed_now(doc), "overdue_days": overdue_days(doc, as_of),
            "banks": [{"bank": s.bank_code, "pct": s.pct, "outstanding": round(principal * s.pct), "repaid": s.repaid}
                      for s in loan_shares(session, loan.id)]}


def service(session: Session, loan: BuLoan, as_of: date, params: dict[str, Any]) -> None:
    """Bring one loan to ``as_of``: every due date on or before it, debits, penalty, 30-day report."""
    doc = dict(loan.doc or {})
    if loan.status not in OPEN_STATUSES:
        return
    for row in list(doc["schedule"]):
        if row["status"] == "upcoming" and parse_date(row["due_date"]) <= as_of:
            _accrue_penalty(doc, params, parse_date(row["due_date"]))
            _process_due(session, loan, doc, params, row)
    _accrue_penalty(doc, params, as_of)
    if owed_now(doc) > 0:
        _collect(session, loan, doc, as_of, "overdue")
    days = overdue_days(doc, as_of)
    doc["overdue_days"] = days
    doc["max_overdue_days"] = max(int(doc.get("max_overdue_days") or 0), days)
    if days >= int(params["repay"]["report_overdue_days"]) and not any(b["kind"] == "overdue_30" for b in doc["bureau"]):
        _report_bureau(session, loan, doc, "overdue_30", as_of)
        doc["majority"] = _majority(session, loan, params)
        push_notice(doc, _notice("danger", f"Khoản vay quá hạn {days} ngày và đã được báo trung tâm thông tin tín dụng. "
                                           "Chị liên hệ WeBank để thống nhất cách trả.", "bureau"))
    loan.status = "overdue" if owed_now(doc) > 0 else "active"
    _maybe_close(session, loan, doc, as_of)
    doc["clock"] = max(clock(doc), as_of).isoformat()
    save_json(loan, "doc", doc)


def _raise_alert(session: Session, loan: BuLoan, result: dict[str, Any]) -> BuAlert:
    text = "; ".join(s["text"] for s in result["signals"]) or "Cảnh báo sớm"
    alert = session.scalar(select(BuAlert).where(
        BuAlert.loan_id == loan.id, BuAlert.level == result["level"], BuAlert.acked.is_(False)))
    if alert is None:
        alert = BuAlert(id="al_" + secrets.token_hex(8), loan_id=loan.id, level=result["level"], acked=False)
        session.add(alert)
        events.log(session, loan.application_id, "agent4", "alert",
                   f"Cảnh báo {'đỏ' if result['level'] == 'red' else 'vàng'}: {text}",
                   {"loan_id": loan.id, "alert_id": alert.id})
    save_json(alert, "signals", result["signals"])
    alert.text = text
    alert.at = utcnow()
    return alert


def check_use_of_funds(session: Session, loan: BuLoan, doc: dict[str, Any], params: dict[str, Any],
                       as_of: date, data: dict[str, Any] | None) -> dict[str, Any] | None:
    """WCLOAN-2024#10 (lỗ hổng 7): within ``use_of_funds.days`` of disbursement a
    purchase invoice from the supplier must match the amount (± tolerance). Returns a
    yellow signal when the deadline passed without one."""
    uof = dict(doc.get("use_of_funds") or {})
    if uof.get("status") != "pending":
        return None
    if not data:
        # No tax data on this case: nothing can prove the use of funds. Never fall back to another
        # seller's data set (it used to read the Lan demo case and could mark "ok" wrongly).
        uof["checked_at"] = as_of.isoformat()
        if as_of > (parse_date(uof.get("due")) or as_of):
            uof["status"] = "unverifiable"
            events.log(session, loan.application_id, "agent4", "use_of_funds",
                       "Không có dữ liệu hóa đơn để kiểm dùng vốn: cần cán bộ kiểm", {"loan_id": loan.id})
        doc["use_of_funds"] = uof
        if uof["status"] == "unverifiable":
            return {"key": "use_of_funds", "weight": 0.0,
                    "text": "Không có dữ liệu hóa đơn để kiểm việc dùng vốn", "rule": "WCLOAN-2024#10"}
        return None
    out = sources.pull_tax_data(data, "purchase_invoices",
                                supplier=uof.get("supplier"), amount=int(doc.get("amount", 0)))
    uof["checked_at"] = as_of.isoformat()
    uof["invoiced"] = out["invoiced"]
    tolerance = float(params["use_of_funds"]["tolerance"])
    if out["invoiced"] >= int(doc.get("amount", 0)) * (1 - tolerance):
        uof["status"] = "ok"
    elif as_of > (parse_date(uof.get("due")) or as_of):
        uof["status"] = "missing"
        events.log(session, loan.application_id, "agent4", "use_of_funds",
                   "Quá hạn kiểm tra dùng vốn: chưa thấy hóa đơn mua hàng khớp khoản giải ngân",
                   {"loan_id": loan.id, "supplier": uof.get("supplier")})
    doc["use_of_funds"] = uof
    if uof["status"] == "missing":
        return {"key": "use_of_funds", "weight": 0.0,
                "text": "Chưa có hóa đơn mua hàng chứng minh dùng vốn đúng mục đích", "rule": "WCLOAN-2024#10"}
    return None


NOTICE_MODEL_BUDGET = 5


def _notify_seller(session: Session, loan: BuLoan, doc: dict[str, Any], result: dict[str, Any],
                   alert: BuAlert, budget: list[int]) -> None:
    """Agent 4 tells the seller (plain words; yellow asks the cause) when the alert level changes.
    One tick lets the model write at most NOTICE_MODEL_BUDGET notices (one try each, short timeout
    in the provider) so a large portfolio never holds the transaction on model calls."""
    from app.agents import agent4_llm as llm_agent4

    use_model = budget[0] > 0
    budget[0] -= 1
    notice = llm_agent4.write_notice(loan, doc, result["level"], result["signals"], alert.id, use_model=use_model)
    push_notice(doc, notice)
    save_json(loan, "doc", doc)
    events.log(session, loan.application_id, "agent4", "seller_notice",
               f"Agent 4 báo người bán ({'mô hình' if notice['source'] == 'llm' else 'mẫu'}): {notice['text'][:120]}",
               {"loan_id": loan.id, "alert_id": alert.id, "notice_id": notice["id"]})


def deliver_notices(pending: list[dict[str, Any]], budget: list[int] | None = None) -> int:
    """Write queued seller notices: the model drafts outside any transaction, then a short
    locked transaction re-reads the loan and appends the notice. Returns how many were sent."""
    from app.autopilot import loop as autopilot
    from app.agents import agent4_llm as llm_agent4
    from app.platform.db.session import session_scope

    budget = budget if budget is not None else [NOTICE_MODEL_BUDGET]
    sent = 0
    for item in pending:
        with session_scope() as session:
            loan = session.get(BuLoan, item["loan_id"])
            if loan is None:
                continue
            snap = SimpleNamespace(outstanding=loan.outstanding, repaid=loan.repaid, currency=loan.currency)
            doc_now = dict(loan.doc or {})
        use_model = budget[0] > 0
        budget[0] -= 1
        notice = llm_agent4.write_notice(snap, doc_now, item["level"], item["signals"], item["alert_id"],  # type: ignore[arg-type]
                                         use_model=use_model)
        with LOAN_LOCK, session_scope() as session:
            loan = session.get(BuLoan, item["loan_id"])
            if loan is None:
                continue
            doc = dict(loan.doc or {})
            push_notice(doc, notice)
            save_json(loan, "doc", doc)
            events.log(session, loan.application_id, "agent4", "seller_notice",
                       f"Agent 4 báo người bán ({'mô hình' if notice['source'] == 'llm' else 'mẫu'}): "
                       f"{notice['text'][:120]}",
                       {"loan_id": loan.id, "alert_id": item["alert_id"], "notice_id": notice["id"]})
        if item["level"] == "red":
            autopilot.mark_agent5_due("cảnh báo đỏ")
        sent += 1
    return sent


def answer_notice(session: Session, loan: BuLoan, notice_id: str, choice: str, note: str) -> dict[str, Any]:
    from app.agents.agent4_llm import CAUSE_CHOICES

    doc = dict(loan.doc or {})
    notices = [dict(n) for n in doc.get("notices") or []]
    target = next((n for n in notices if n["id"] == notice_id), None)
    if target is None or not target.get("question"):
        raise api_error(404, "NOT_FOUND", "Không tìm thấy câu hỏi này.")
    if target.get("answer"):
        raise api_error(409, "CONFLICT", "Chị đã trả lời câu hỏi này.")
    label = next((c["label"] for c in CAUSE_CHOICES if c["key"] == choice), None)
    if label is None:
        raise api_error(400, "VALIDATION_ERROR", "Lựa chọn không hợp lệ.", {"field": "choice"})
    target["answer"] = {"choice": choice, "label": label, "note": note.strip()[:300], "at": utcnow().isoformat() + "Z"}
    doc["notices"] = notices
    save_json(loan, "doc", doc)
    events.log(session, loan.application_id, "seller", "notice_answer", f"Người bán trả lời Agent 4: {label}",
               {"loan_id": loan.id, "alert_id": target.get("alert_id"), "choice": choice, "note": note.strip()[:300]})
    return target


def is_bad_loan(loan: BuLoan, params: dict[str, Any], as_of: date) -> bool:
    """NPL for the auto-approval switch: overdue ≥ ``gate.npl_overdue_days``, red, or written off."""
    doc = loan.doc or {}
    if loan.status == "closed":
        return bool(doc.get("written_off"))
    level = (doc.get("early_warning") or {}).get("level")
    return (int(doc.get("overdue_days") or 0) >= int(params["gate"]["npl_overdue_days"]) or level == "red"
            or bool(doc.get("written_off")))


def refresh_auto_switch(session: Session, params: dict[str, Any], as_of: date | None = None) -> list[BuAutoSwitch]:
    """Recompute every group's NPL ratio; switch auto-approval off at ``gate.npl_off_ratio``
    once the group has ``gate.npl_min_loans`` loans. Manual (admin) switches keep their state."""
    day = as_of or today()
    stats: dict[str, list[int]] = {}
    # Agent 5 §3.2: the switch watches the loans the gate approved on its own, not officer approvals.
    by = dict(session.execute(select(BuApplication.id, BuApplication.doc)).all())
    for loan in session.scalars(select(BuLoan)):
        if ((by.get(loan.application_id) or {}).get("decision") or {}).get("by") not in (None, "gate"):
            continue
        doc = loan.doc or {}
        key = str(doc.get("auto_group") or group_key(str(doc.get("category") or "khác"), int(doc.get("tier") or 2)))
        row = stats.setdefault(key, [0, 0])
        row[0] += 1
        row[1] += 1 if is_bad_loan(loan, params, day) else 0
    gate = params["gate"]
    rows = {r.group_key: r for r in session.scalars(select(BuAutoSwitch))}
    for key, (loans, bad) in stats.items():
        row = rows.get(key)
        if row is None:
            row = rows[key] = BuAutoSwitch(group_key=key, enabled=True, manual=False, reason="")
            session.add(row)
        ratio = round(bad / loans, 4) if loans else 0.0
        row.loans, row.bad, row.npl_ratio, row.updated_at = loans, bad, ratio, utcnow()
        if row.manual:
            continue
        off = loans >= int(gate["npl_min_loans"]) and ratio >= float(gate["npl_off_ratio"])
        if off != (not row.enabled):
            # Agent 5 §3.2: the switch turning off (or back on) is recorded on the chain.
            entry = chain.record(session, "system", "auto_switch", {
                "group": key, "enabled": not off, "npl_ratio": ratio, "loans": loans, "bad": bad,
                "at": day.isoformat()})
            events.log(session, "system", "agent4", "auto_approval_off" if off else "auto_approval_on",
                       (f"Tắt duyệt tự động nhóm {key}: nợ xấu {ratio * 100:.1f}% trên {loans} khoản" if off
                        else f"Bật lại duyệt tự động nhóm {key}"),
                       {"group": key, "npl_ratio": ratio, "loans": loans}, entry.fingerprint)
        row.enabled = not off
        row.reason = f"Nợ xấu {ratio * 100:.1f}% trên {loans} khoản" if off else ""
    session.flush()
    return list(rows.values())


def auto_approval_enabled(session: Session, params: dict[str, Any], key: str) -> bool:
    refresh_auto_switch(session, params)
    row = session.get(BuAutoSwitch, key)
    return row is None or bool(row.enabled)


def _rescore_fate(app_doc: dict[str, Any], data: dict[str, Any] | None) -> int | None:
    """Ask FATE again (the configured service, else the scenario data). None when it does not answer."""
    if not data or not app_doc.get("consent"):
        return None
    try:
        out = sources.fate_source(data).score(app_doc["consent"], reference_code(
            "fate", ((app_doc.get("stores") or [{}])[0] or {}).get("reg_no") or ""))
    except sources.SourceUnavailable:
        return None
    value = out.get("value")
    return int(value) if value is not None else None


def tick(session: Session, as_of: date | None = None, loan_ids: list[str] | None = None,
         refresh: bool = True, deferred: list[dict[str, Any]] | None = None) -> list[BuAlert]:
    """Each day for every open loan (or only ``loan_ids``): due dates and debits, penalty, 30-day
    report, early warning, FATE re-score (only under a valid consent), use of funds, reminders,
    the banks' status report; then the auto-approval switches (``refresh``). With ``deferred`` the
    seller notices are only queued (no model call inside this transaction)."""
    params = active_params(session)
    day = as_of or today()
    raised: list[BuAlert] = []
    budget = [NOTICE_MODEL_BUDGET]
    stmt = select(BuLoan).where(BuLoan.status.in_(OPEN_STATUSES))
    if loan_ids is not None:
        stmt = stmt.where(BuLoan.id.in_(loan_ids))
    for loan in list(session.scalars(stmt)):
        prev_level = ((loan.doc or {}).get("early_warning") or {}).get("level", "green")
        prev_status = loan.status
        with capabilities.acting("standing_order"):  # core banking executes the signed standing order
            service(session, loan, day, params)
        if loan.status == "closed":
            loan.updated_at = utcnow()
            continue
        with capabilities.acting("agent4b"):  # from here on: read, score, alert, notify; no money moves
            _monitor_one(session, loan, day, params, prev_level, prev_status, raised, deferred, budget)
    session.flush()
    if refresh:
        refresh_auto_switch(session, params, day)
    return raised


def _monitor_one(session: Session, loan: BuLoan, day: date, params: dict[str, Any], prev_level: str,
                 prev_status: str, raised: list[BuAlert], deferred: list[dict[str, Any]] | None,
                 budget: list[int]) -> None:
    """Agent 4b on one loan."""
    app_doc = (session.get(BuApplication, loan.application_id).doc or {}) if loan.application_id else {}
    fate_allowed = consent_mod.blocked_reason(app_doc.get("consent")) is None
    data = (app_doc.get("internal") or {}).get("data")
    result = assess(loan, params, day, fate_allowed, _rescore_fate(app_doc, data) if fate_allowed else None)
    doc = dict(loan.doc or {})
    uof_signal = check_use_of_funds(session, loan, doc, params, day, data)
    if uof_signal is not None:
        result["signals"].append(uof_signal)
        if result["level"] == "green":
            result["level"] = "yellow"
    doc["early_warning"] = {**{k: result[k] for k in ("score", "level", "signals")},
                            "at": utcnow().isoformat() + "Z", "as_of": day.isoformat()}
    doc["fate"] = {**(doc.get("fate") or {}), "current": result["fate"], "at": day.isoformat(),
                   "simulated": not settings.fate_url.strip()}
    if not fate_allowed:
        doc["fate"]["skipped"] = "consent"
    else:
        doc["fate"].pop("skipped", None)
    known = {r["text"] for r in doc.get("reminders") or []}
    stamp = datetime.combine(day, datetime.min.time()).isoformat() + "Z"
    new = [t for t in _reminders(doc, params, day) if t not in known]
    doc["reminders"] = (list(doc.get("reminders") or []) + [{"at": stamp, "text": t} for t in new])[-30:]
    for t in new:
        push_notice(doc, _notice("info", t, "reminder"))
    doc["bank_report"] = _bank_report(session, loan, doc, day)
    save_json(loan, "doc", doc)
    if loan.status != prev_status or result["level"] != prev_level:
        loan.updated_at = utcnow()  # a real change: Agent 5 skips rounds where nothing moved
    if result["level"] in ("yellow", "red"):
        alert = _raise_alert(session, loan, result)
        raised.append(alert)
        if result["level"] != prev_level and deferred is not None:
            deferred.append({"loan_id": loan.id, "level": result["level"], "signals": result["signals"],
                             "alert_id": alert.id})
        elif result["level"] != prev_level:
            _notify_seller(session, loan, doc, result, alert, budget)
            if result["level"] == "red":
                from app.autopilot import loop as autopilot

                autopilot.mark_agent5_due("cảnh báo đỏ")
