"""Agent 5 · báo cáo cho người bán (SELLER_SERVICES_PLAN §6, việc 5–9, 17/10/2026).

Monthly, quarterly, yearly and closing reports on the seller's WeBank business account, plus the yearly
reminder to register a business (individual sellers only). Everything is computed by code from what BuoyUp
already holds:

- ``BuLoan.doc.account.inflows / transfers`` (money in, money out with its expense group, ``core.cashflow``),
  ``BuRepayment`` (what the standing order collected, with its simulated day), the schedule;
- the application's ``internal.data``: tax-filed ``revenue.monthly_12m``, the store's platform fee, ``borrower_type``,
  the offer's block B8 (seed stage) for the "next time" line;
- ``doc["store_snapshots"]`` written monthly by Agent 4b (§6.3) for the quarterly rating / returns trend.

Only reads and writes reports. Nothing here calls ``_collect``, ``_pay_banks``, ``prepay`` or
``change_receiving_account``; :func:`run_due` runs as ``capabilities.acting("agent5")`` (no debit, no payout),
so a call to a money function would raise. A model may rewrite the 3-sentence summary once, through the number
filter of Agent 2 (``blocked``) plus a check of "50,000"-style thousands; otherwise the template stands.

Each report is fingerprinted on the chain (``chain.record(session, seller_user_id, "seller_report", data)``) and
logged (``events.log`` kind ``seller_report``). One row per (seller, kind, period): a re-run with the same facts
writes nothing; with new facts (a late webhook) it overwrites the row and records the new hash.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.agent4b_monitor import clock, parse_date, _repaid_on, _tax_month
from app.blockchain import chain
from app.core import cashflow, legal
from app.core.algorithm import floor_to
from app.banks.split import vn_number
from app.core.params import active_params
from app.platform import capabilities, events
from app.platform.db.tables import utcnow
from app.platform.tables import BuApplication, BuLoan, BuRepayment, BuSellerReport

KINDS = ("month", "quarter", "year", "closing", "registration")
MAX_BACKFILL_MONTHS = 12  # a seller with a long history gets at most this many monthly reports at once
UNAVAILABLE_STORE = "Chưa đủ dữ liệu đánh giá và hoàn hàng từ sàn"
PLATFORM_NAMES = {"douyin": "Douyin", "taobao": "Taobao", "tmall": "Tmall", "jd": "JD", "pinduoduo": "Pinduoduo",
                  "kuaishou": "Kuaishou", "xiaohongshu": "Xiaohongshu"}
# Keys that are not facts: two builds with the same facts are the same report.
_VOLATILE = ("summary", "summary_source", "hash", "chain_tx", "report_id")

SUMMARY_SYSTEM = (
    "Bạn là Agent 5 của BuoyUp. Viết lại đoạn tóm tắt báo cáo kinh doanh cho người bán thành đúng 3 câu tiếng Việt, "
    "gọi người bán là 'bạn', giọng thân thiện, dễ hiểu. Chỉ dùng các con số có trong dữ liệu JSON, viết số kiểu "
    "Việt Nam (166.700), không thêm số mới, không hứa hẹn cho vay, không nêu mã nội bộ. Chỉ trả về đoạn văn."
)


# --- small helpers ----------------------------------------------------------------------------------

def _n(x: Any) -> str:
    return vn_number(int(round(float(x or 0))))


def _pct(x: float | None) -> str:
    return f"{round(float(x) * 100)} %" if x is not None else "?"


def _signed_pct(x: float | None) -> str:
    if x is None:
        return ""
    v = round(float(x) * 100)
    return f"{'+' if v > 0 else '−' if v < 0 else '±'}{abs(v)} %"


def _month_add(month: str, k: int) -> str:
    y, m = int(month[:4]), int(month[5:7]) - 1 + k
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


def _month_end(month: str) -> date:
    return date.fromisoformat(_month_add(month, 1) + "-01") - timedelta(days=1)


def _months(first: str, last: str) -> list[str]:
    out, m = [], first
    while m <= last and len(out) < 400:
        out.append(m)
        m = _month_add(m, 1)
    return out


def quarter_of(month: str) -> str:
    return f"{month[:4]}-Q{(int(month[5:7]) - 1) // 3 + 1}"


def quarter_months(quarter: str) -> list[str]:
    q = int(quarter[-1])
    return [f"{quarter[:4]}-{(q - 1) * 3 + i:02d}" for i in (1, 2, 3)]


def _month_name(month: str) -> str:
    return f"tháng {int(month[5:7])}"


def _day(value: Any) -> date | None:
    return parse_date(value)


# --- what the seller has ----------------------------------------------------------------------------

class _Seller:
    """Everything the reports read for one seller, loaded once per build."""

    def __init__(self, session: Session, user_id: str) -> None:
        self.user_id = user_id
        self.loans = list(session.scalars(select(BuLoan).where(BuLoan.seller_user_id == user_id)
                                          .order_by(BuLoan.created_at)))
        self.apps = list(session.scalars(select(BuApplication).where(BuApplication.seller_user_id == user_id)
                                         .order_by(BuApplication.updated_at.desc())))
        ids = [ln.id for ln in self.loans]
        self.repayments = list(session.scalars(select(BuRepayment).where(BuRepayment.loan_id.in_(ids)))) if ids else []
        # the latest application with the data Agent 1 read (tax revenue, platform fee, goods mix)
        self.app = next((a for a in self.apps if ((a.doc or {}).get("internal") or {}).get("data")), None)
        self.app_doc = (self.app.doc or {}) if self.app else {}
        self.data = (self.app_doc.get("internal") or {}).get("data") or {}
        self.currency = self.loans[-1].currency if self.loans else str(self.app_doc.get("currency") or "CNY")

    @property
    def docs(self) -> list[dict[str, Any]]:
        return [ln.doc or {} for ln in self.loans]

    def application_id(self) -> str:
        if self.loans:
            return self.loans[-1].application_id
        return self.app.id if self.app else "system"

    def platform(self) -> str:
        return str((self.data.get("store") or {}).get("platform")
                   or (((self.app_doc.get("stores") or [{}])[0]) or {}).get("platform") or "douyin")

    def fee(self) -> float:
        tax = self.data.get("tax") or {}
        if isinstance(tax.get("platform_fee"), (int, float)) and 0 < tax["platform_fee"] < 0.5:
            return float(tax["platform_fee"])
        return cashflow.fee_rate(tax, self.platform())

    def tax_month(self, month: str) -> int | None:
        return _tax_month(self.app_doc, month)

    def first_month(self) -> str | None:
        starts = [str((ln.doc or {}).get("start_date") or "")[:7] for ln in self.loans if (ln.doc or {}).get("start_date")]
        return min(starts) if starts else None

    def loan_active_in(self, month: str) -> BuLoan | None:
        """The loan running during ``month`` (latest started), for its forecast."""
        out = None
        for ln in self.loans:
            d = ln.doc or {}
            start = str(d.get("start_date") or "")[:7]
            closed = str(d.get("closed_on") or "")[:7]
            if start and start <= month and (not closed or closed >= month):
                out = ln
        return out

    def repaid(self) -> list[dict[str, Any]]:
        """Repayments with their simulated day and parts (penalty, interest, principal)."""
        out = []
        for r in self.repayments:
            detail = next((x for x in (r.split or []) if isinstance(x, dict) and "kind" in x), {})
            out.append({"loan_id": r.loan_id, "at": _repaid_on(r), "swept": int(r.swept or 0), "ts": r.at,
                        "interest": int(detail.get("interest") or 0), "penalty": int(detail.get("penalty") or 0),
                        "principal": int(detail.get("principal") or 0), "kind": detail.get("kind")})
        return out


def _movements(seller: _Seller) -> list[tuple[str, str, str, int]]:
    """Every movement of the business account: (simulated day, real timestamp, kind, signed amount), in order."""
    out: list[tuple[str, str, str, int]] = []
    for ln in seller.loans:
        doc = ln.doc or {}
        acc = doc.get("account") or {}
        start = str(doc.get("start_date") or "")
        if start:
            out.append((start, ln.created_at.isoformat() if ln.created_at else "", "loan",
                        int((doc.get("payee") or {}).get("to_account") or doc.get("amount") or 0)))
        out += [(str(i.get("on") or ""), str(i.get("at") or ""), "in", int(i.get("amount") or 0))
                for i in acc.get("inflows") or []]
        out += [(str(t.get("on") or ""), str(t.get("at") or ""), "out", -int(t.get("amount") or 0))
                for t in acc.get("transfers") or []]
    out += [(r["at"], r["ts"].isoformat() if isinstance(r["ts"], datetime) else str(r["ts"] or ""), "repay", -r["swept"])
            for r in seller.repaid()]
    return sorted((m for m in out if m[0]), key=lambda m: (m[0][:10], m[1].rstrip("Z")))


def _cash(seller: _Seller, month: str) -> dict[str, Any]:
    """Opening / closing / lowest balance of the business account in ``month`` (replayed from the movements)."""
    balance = 0
    opening = None
    lowest, lowest_on = None, None
    sums = {"in": 0, "loan": 0, "repay": 0, "out": 0}
    for on, _ts, kind, amount in _movements(seller):
        m = on[:7]
        if m > month:
            break
        if m == month and opening is None:
            opening = balance
        balance += amount
        if m == month:
            sums[kind] += abs(amount)
            if lowest is None or balance < lowest:
                lowest, lowest_on = balance, on[:10]
    if opening is None:
        opening = balance
    if opening > 0 and (lowest is None or opening < lowest):
        lowest, lowest_on = opening, month + "-01"
    return {"opening": opening, "in": sums["in"], "loan_in": sums["loan"], "repay": sums["repay"], "out": sums["out"],
            "closing": balance, "lowest": lowest if lowest is not None else balance, "lowest_on": lowest_on}


def _loan_at(seller: _Seller, month: str) -> dict[str, Any]:
    """The loans as they stood at the end of ``month`` (principal still owed, the next instalment after it)."""
    end = _month_end(month)
    outstanding, next_due, status = 0, None, None
    paid_principal: dict[str, int] = {}
    for r in seller.repaid():
        if r["at"] and r["at"] <= end.isoformat():
            paid_principal[r["loan_id"]] = paid_principal.get(r["loan_id"], 0) + r["principal"]
    for ln in seller.loans:
        d = ln.doc or {}
        start = _day(d.get("start_date"))
        if start is None or start > end:
            continue
        closed = _day(d.get("closed_on"))
        if closed is not None and closed <= end:
            status = status or "closed"
            continue
        status = "active"
        outstanding += max(0, int(d.get("amount") or 0) - paid_principal.get(ln.id, 0))
        row = next((r for r in d.get("schedule") or [] if str(r.get("due_date") or "") > end.isoformat()), None)
        if row and (next_due is None or row["due_date"] < next_due["date"]):
            next_due = {"date": row["due_date"], "amount": int(row.get("payment_est") or 0), "k": row.get("k")}
    paid = sum(r["swept"] for r in seller.repaid() if r["at"][:7] == month)
    return {"outstanding": outstanding, "paid_this_month": paid, "next_due": next_due, "status": status or "none"}


def coverage(session: Session, user_id: str, month: str, seller: _Seller | None = None) -> dict[str, Any]:
    """Việc 9: how much of the store's revenue in ``month`` reached the WeBank business account
    (``cashflow.coverage``: against the tax-filed revenue, else the loan's forecast, else ``basis: "none"``)."""
    seller = seller or _Seller(session, user_id)
    webank_in = sum(int(i.get("amount") or 0) for d in seller.docs for i in (d.get("account") or {}).get("inflows") or []
                    if str(i.get("on") or "")[:7] == month)
    loan = seller.loan_active_in(month)
    forecast = int((loan.doc or {}).get("forecast_monthly") or 0) if loan is not None else 0
    cov = cashflow.coverage(webank_in, seller.tax_month(month), forecast)
    cov["month"] = month
    return cov


def coverage_note(cov: dict[str, Any], what: str = "doanh thu của cửa hàng") -> str:
    if cov.get("share") is None:
        return "Chưa có tờ khai thuế hay dự báo doanh thu cho kỳ này: báo cáo chỉ tính được tiền hàng về WeBank."
    basis = {"tax": "theo tờ khai thuế", "forecast": "so với doanh thu dự báo trong hồ sơ vay"}.get(
        cov["basis"], "theo tờ khai thuế và doanh thu dự báo trong hồ sơ vay")
    if cov["share"] >= 0.995:
        return f"Báo cáo tính được toàn bộ {what} ({basis})."
    return (f"Báo cáo tính được {_pct(cov['share'])} {what} ({basis}); phần còn lại về tài khoản khác, "
            "BuoyUp không thấy.")


def _fee_note(seller: _Seller) -> str:
    name = PLATFORM_NAMES.get(seller.platform().lower(), seller.platform())
    return f"Phí sàn ước tính theo biểu phí {round(seller.fee() * 100, 1):g} % của {name}."


# --- one month -----------------------------------------------------------------------------------------

def _month_core(seller: _Seller, month: str, params: dict[str, Any]) -> dict[str, Any]:
    reps = [{"at": r["at"], "swept": r["swept"]} for r in seller.repaid()]
    summ = cashflow.month_summary(seller.docs, reps, month, seller.fee())
    cov = coverage(None, seller.user_id, month, seller)  # type: ignore[arg-type]
    prev = coverage(None, seller.user_id, _month_add(month, -1), seller)  # type: ignore[arg-type]
    estimate = int(cov.get("estimate") or 0)
    # Month on month only between two tax-filed months: a forecast is not a sale (no invented trend).
    prev_est = int(prev.get("estimate") or 0) if prev.get("basis") == "tax" else 0
    vs_prev = round(estimate / prev_est - 1, 4) if cov["basis"] == "tax" and estimate and prev_est else None
    cash = _cash(seller, month)
    loan = _loan_at(seller, month)
    flags = []
    dsr_max = float(params["early_warning"].get("dsr_max", 0.20))
    if loan["paid_this_month"] and estimate:
        ratio = loan["paid_this_month"] / estimate
        if ratio > dsr_max:
            flags.append(f"Tiền trả nợ bằng {_pct(ratio)} doanh thu ước tính (trên {_pct(dsr_max)} là nặng)")
    if summ["unclassified"]:
        flags.append(f"Có {_n(summ['unclassified'])} tệ chi chưa phân loại")
    if summ["non_business"]:
        flags.append(f"{_n(summ['non_business'])} tệ chuyển ra ngoài hoạt động kinh doanh (không tính là chi phí)")
    if loan["next_due"] and cash["closing"] < loan["next_due"]["amount"]:
        flags.append(f"Số dư cuối tháng thấp hơn kỳ trả {_n(loan['next_due']['amount'])} tệ ngày "
                     f"{_dm(loan['next_due']['date'])}")
    return {
        "coverage": cov,
        "sales": {"webank_in": int(cov["webank_in"]), "tax_revenue": cov.get("tax_revenue"),
                  "estimate": estimate or None, "basis": cov["basis"], "vs_prev": vs_prev},
        "expenses": {"groups": summ["groups"], "total": summ["expenses"], "unclassified": summ["unclassified"],
                     "non_business": summ["non_business"], "platform_fee": summ["platform_fee"],
                     "platform_fee_rate": summ["platform_fee_rate"], "platform_fee_estimated": True},
        "cash": cash, "loan": loan, "flags": flags,
    }


def _dm(value: Any) -> str:
    d = _day(value)
    return d.strftime("%d/%m") if d else str(value)


def _top_group(groups: list[dict[str, Any]]) -> dict[str, Any] | None:
    top = max(groups, key=lambda g: g["amount"], default=None)
    return top if top and top["amount"] > 0 else None


def _month_summary_text(month: str, core: dict[str, Any]) -> str:
    s, cash, cov = core["sales"], core["cash"], core["coverage"]
    name = _month_name(month).capitalize()
    if s["basis"] == "tax":
        first = f"{name} bạn bán được khoảng {_n(s['estimate'])} tệ"
        if s["vs_prev"] is not None:
            first += f" ({_signed_pct(s['vs_prev'])} so {_month_name(_month_add(month, -1))})"
        first += "."
    elif s["basis"] == "forecast":
        first = (f"{name} tiền hàng về WeBank {_n(s['webank_in'])} tệ, bằng {_pct(cov['share'])} doanh thu dự báo "
                 f"trong hồ sơ vay ({_n(cov['revenue'])} tệ).")
    elif s["webank_in"]:
        first = f"{name} tiền hàng về WeBank {_n(s['webank_in'])} tệ."
    else:
        first = f"{name} BuoyUp chưa thấy tiền hàng nào về tài khoản WeBank."
    top = _top_group(core["expenses"]["groups"])
    repay = int(cash.get("repay") or 0)
    if top:
        second = f"Chi lớn nhất là {top['label'][0].lower() + top['label'][1:]} {_n(top['amount'])} tệ"
        second += f"; trả nợ BuoyUp {_n(repay)} tệ." if repay else "."
    else:
        second = (f"Tháng này bạn trả nợ BuoyUp {_n(repay)} tệ, chưa ghi nhận khoản chi kinh doanh nào." if repay
                  else "Tháng này chưa ghi nhận khoản chi kinh doanh nào.")
    third = f"Cuối tháng tài khoản WeBank còn {_n(cash['closing'])} tệ"
    if cash.get("lowest_on") and cash["lowest"] < cash["closing"]:
        third += f", thấp nhất {_n(cash['lowest'])} tệ hôm {_dm(cash['lowest_on'])}"
    return f"{first} {second} {third}."


def build_month(session: Session, user_id: str, month: str, seller: _Seller | None = None) -> dict[str, Any]:
    """Việc 5 (+ việc 9 in ``coverage`` / ``notes[0]``): the month's sales, expenses by group, cash and loan."""
    seller = seller or _Seller(session, user_id)
    params = active_params(session)
    core = _month_core(seller, month, params)
    data = {"kind": "month", "period": month, "currency": seller.currency, **core,
            "notes": [coverage_note(core["coverage"]), _fee_note(seller)], "level": "info", "simulated": True}
    data["summary"], data["summary_source"] = _month_summary_text(month, core), "template"
    return data


# --- several months (quarter, year, closing) ------------------------------------------------------------

def _aggregate(seller: _Seller, months: list[str], params: dict[str, Any]) -> dict[str, Any]:
    cores = [(m, _month_core(seller, m, params)) for m in months]
    groups = {g: 0 for g in cashflow.EXPENSE_GROUPS}
    for _m, c in cores:
        for g in c["expenses"]["groups"]:
            groups[g["key"]] += int(g["amount"])
    total = sum(groups.values())
    webank_in = sum(c["sales"]["webank_in"] for _m, c in cores)
    known = [c for _m, c in cores if c["coverage"]["basis"] != "none"]
    revenue = sum(int(c["coverage"]["revenue"] or 0) for c in known)
    seen_in = sum(c["sales"]["webank_in"] for c in known)
    bases = {c["coverage"]["basis"] for c in known}
    cov = ({"share": round(min(1.0, seen_in / revenue), 4) if revenue else None,
            "basis": bases.pop() if len(bases) == 1 else "mixed",
            "webank_in": webank_in, "revenue": revenue, "months_known": len(known)}
           if known else {"share": None, "basis": "none", "webank_in": webank_in, "revenue": None, "months_known": 0})
    by_month = [{"month": m, "in": c["cash"]["in"], "loan_in": c["cash"]["loan_in"], "repay": c["cash"]["repay"],
                 "out": c["cash"]["out"], "estimate": c["sales"]["estimate"], "closing": c["cash"]["closing"]}
                for m, c in cores]
    lows = [(c["cash"]["lowest"], c["cash"]["lowest_on"]) for _m, c in cores if c["cash"]["lowest_on"]]
    low = min(lows, default=(cores[-1][1]["cash"]["closing"] if cores else 0, None))
    cash = {"opening": cores[0][1]["cash"]["opening"] if cores else 0,
            "in": sum(b["in"] for b in by_month), "loan_in": sum(b["loan_in"] for b in by_month),
            "repay": sum(b["repay"] for b in by_month), "out": sum(b["out"] for b in by_month),
            "closing": cores[-1][1]["cash"]["closing"] if cores else 0, "lowest": low[0], "lowest_on": low[1]}
    estimate = sum(int(c["sales"]["estimate"] or 0) for _m, c in cores)
    return {
        "months": months, "coverage": cov,
        "sales": {"webank_in": webank_in, "tax_revenue": sum(int(c["sales"]["tax_revenue"] or 0) for _m, c in cores) or None,
                  "tax_months": sum(1 for _m, c in cores if c["coverage"]["basis"] == "tax"),
                  "estimate": estimate or None, "basis": cov["basis"]},
        "expenses": {"groups": [{"key": k, "label": cashflow.GROUP_LABELS[k], "amount": v,
                                 "share": round(v / total, 4) if total else 0.0} for k, v in groups.items()],
                     "total": total, "unclassified": sum(c["expenses"]["unclassified"] for _m, c in cores),
                     "non_business": sum(c["expenses"]["non_business"] for _m, c in cores),
                     "platform_fee": sum(c["expenses"]["platform_fee"] for _m, c in cores),
                     "platform_fee_estimated": True},
        "cash": cash, "by_month": by_month, "loan": cores[-1][1]["loan"] if cores else None,
        "flags": [f"{_month_name(m).capitalize()}: {f}" for m, c in cores for f in c["flags"]][:8],
    }


def _snapshots(seller: _Seller, upto: str) -> list[dict[str, Any]]:
    by_month: dict[str, dict[str, Any]] = {}
    for d in seller.docs:
        for s in d.get("store_snapshots") or []:
            if str(s.get("month") or "") <= upto:
                by_month[str(s["month"])] = s
    return [by_month[k] for k in sorted(by_month)]


def _store_trend(seller: _Seller, upto: str) -> dict[str, Any]:
    """Rating and returns from the monthly snapshots: only with at least two of them, never invented."""
    snaps = _snapshots(seller, upto)
    if len(snaps) < 2:
        return {"unavailable": UNAVAILABLE_STORE, "snapshots": len(snaps)}
    first, last = snaps[0], snaps[-1]
    out: dict[str, Any] = {"snapshots": len(snaps), "from": first["month"], "to": last["month"]}
    if first.get("rating") is not None and last.get("rating") is not None:
        out["rating"] = {"from": first["rating"], "to": last["rating"],
                         "change": round(float(last["rating"]) - float(first["rating"]), 2)}
    else:
        out["rating"] = {"unavailable": "chưa có"}
    if first.get("returns_rate") is not None and last.get("returns_rate") is not None:
        out["returns"] = {"from": first["returns_rate"], "to": last["returns_rate"],
                          "change": round(float(last["returns_rate"]) - float(first["returns_rate"]), 4)}
    else:
        out["returns"] = {"unavailable": "Sàn chưa cung cấp tỷ lệ hoàn hàng (chưa có)"}
    return out


def build_quarter(session: Session, user_id: str, quarter: str, seller: _Seller | None = None) -> dict[str, Any]:
    """Việc 6: the quarter's totals, the revenue trend over its 3 months, how long the cash lasts, the store."""
    seller = seller or _Seller(session, user_id)
    params = active_params(session)
    months = quarter_months(quarter)
    agg = _aggregate(seller, months, params)
    # The trend only from tax-filed months (a forecast is the plan, not a sale): never invented.
    points = [{"month": m, "amount": seller.tax_month(m)} for m in months if seller.tax_month(m)]
    if len(points) >= 2:
        change = round(points[-1]["amount"] / points[0]["amount"] - 1, 4) if points[0]["amount"] else None
        direction = "▲" if (change or 0) > 0.005 else "▼" if (change or 0) < -0.005 else "="
        trend = {"revenue": {"months": points, "direction": direction, "change": change}}
    else:
        trend = {"revenue": {"months": points,
                             "unavailable": "Chưa đủ 2 tháng có tờ khai thuế trong quý để nói xu hướng doanh thu"}}
    avg_out = agg["cash"]["out"] / 3.0
    runway: Any = round(agg["cash"]["closing"] / avg_out, 1) if avg_out > 0 else "∞"
    store = _store_trend(seller, months[-1])
    qlabel = f"Quý {quarter[-1]}/{quarter[:4]}"
    notes = [coverage_note(agg["coverage"]), _fee_note(seller)]
    if store.get("unavailable"):
        notes.append(store["unavailable"] + ": cần ít nhất 2 lần đọc trang cửa hàng hằng tháng.")
    data = {"kind": "quarter", "period": quarter, "currency": seller.currency, **agg, "trend": trend,
            "runway_months": runway, "store": store, "notes": notes, "level": "info", "simulated": True}
    s = agg["sales"]
    if s["tax_months"] == len(months):
        first = f"{qlabel} bạn bán được khoảng {_n(s['tax_revenue'])} tệ"
    elif s["tax_months"]:
        first = (f"{qlabel} tiền hàng về WeBank {_n(s['webank_in'])} tệ; tờ khai thuế có {s['tax_months']}/3 tháng, "
                 f"khoảng {_n(s['tax_revenue'])} tệ")
    else:
        first = f"{qlabel} tiền hàng về WeBank {_n(s['webank_in'])} tệ"
    tr = trend["revenue"]
    if tr.get("direction") and tr.get("change") is not None:
        first += (f" ({tr['direction']} {abs(round(tr['change'] * 100))} % từ {_month_name(points[0]['month'])} đến "
                  f"{_month_name(points[-1]['month'])})")
    top = _top_group(agg["expenses"]["groups"])
    second = (f"Chi lớn nhất là {top['label'][0].lower() + top['label'][1:]} {_n(top['amount'])} tệ." if top
              else "Quý này chưa ghi nhận khoản chi kinh doanh nào.")
    third = f"Cuối quý tài khoản WeBank còn {_n(agg['cash']['closing'])} tệ"
    third += (f", đủ chi khoảng {str(runway).replace('.', ',')} tháng theo mức chi của quý." if runway != "∞"
              else "; quý này không có khoản chi nào từ tài khoản.")
    data["summary"], data["summary_source"] = f"{first}. {second} {third}", "template"
    return data


def _b8(seller: _Seller) -> dict[str, Any]:
    for a in seller.apps:
        b8 = (((a.doc or {}).get("offer") or {}).get("blocks") or {}).get("B8")
        if b8:
            return b8
    return {}


def _next_time(seller: _Seller, params: dict[str, Any]) -> dict[str, Any]:
    """"Lần sau vay bao nhiêu": from block B8 of the latest offer (no new computation): its computed limit
    times the next seed ratio, within the type cap."""
    b8 = _b8(seller)
    if not b8:
        return {"text": "Khi cần vốn lần sau, bạn nộp hồ sơ cập nhật để BuoyUp tính lại hạn mức.", "limit": None}
    seed = b8.get("seed") or {}
    steps = [float(x) for x in (params.get("seed") or {}).get("ratio") or [1.0]]
    stage = int(seed.get("stage") or 0)
    now = float(seed.get("ratio", steps[min(stage, len(steps) - 1)]))
    nxt = steps[min(stage + 1, len(steps) - 1)]
    computed = int(b8.get("computed") or b8.get("limit") or 0)
    caps = [int(x) for x in (b8.get("type_cap"), b8.get("group_cap")) if isinstance(x, (int, float)) and x > 0]
    months = int(params["seed"].get("min_webank_months") or 3)
    share = float(params["seed"].get("min_inflow_share") or 0.8)
    if nxt > now and computed:
        limit = int(floor_to(min([computed * nxt, *caps]), 100))
        return {"limit": limit, "ratio_now": now, "ratio_next": nxt, "computed": computed, "source": "offer.blocks.B8",
                "text": f"Nếu {months} tháng tới tiền hàng về WeBank ≥ {round(share * 100)} %, hạn mức lần sau có thể "
                        f"tới {_n(limit)} tệ."}
    limit = int(b8.get("limit") or 0)
    return {"limit": limit or None, "ratio_now": now, "ratio_next": nxt, "computed": computed, "source": "offer.blocks.B8",
            "text": (f"Hạn mức lần này là {_n(limit)} tệ; lần sau BuoyUp tính lại theo hồ sơ cập nhật của bạn."
                     if limit else "Khi cần vốn lần sau, bạn nộp hồ sơ cập nhật để BuoyUp tính lại hạn mức.")}


def _loan_summary(seller: _Seller, loan: BuLoan) -> dict[str, Any]:
    d = loan.doc or {}
    reps = [r for r in seller.repaid() if r["loan_id"] == loan.id]
    start = _day(d.get("start_date"))
    end = _day(d.get("closed_on")) or clock(d)
    late_rows = sum(1 for r in d.get("schedule") or [] if r.get("status") in ("overdue", "paid_late"))
    return {"loan_id": loan.id, "amount": int(d.get("amount") or 0), "rate": d.get("rate"),
            "status": loan.status, "start_date": d.get("start_date"), "closed_on": d.get("closed_on"),
            "days": (end - start).days if start and end else None,
            "total_interest": sum(r["interest"] for r in reps), "total_penalty": sum(r["penalty"] for r in reps),
            "total_paid": sum(r["swept"] for r in reps), "max_interest": int(d.get("max_interest") or 0),
            "late_instalments": late_rows, "max_overdue_days": int(d.get("max_overdue_days") or 0)}


def _before_after(seller: _Seller, loan: BuLoan) -> dict[str, Any]:
    """3 months before the disbursement vs the 3 months from it: tax-filed revenue and money in on WeBank."""
    start = str((loan.doc or {}).get("start_date") or "")[:7]
    if not start:
        return {"unavailable": "Không rõ ngày giải ngân"}

    def side(months: list[str]) -> dict[str, Any]:
        tax = [seller.tax_month(m) for m in months]
        webank = sum(int(i.get("amount") or 0) for d in seller.docs for i in (d.get("account") or {}).get("inflows") or []
                     if str(i.get("on") or "")[:7] in months)
        return {"months": months, "revenue": sum(t for t in tax if t) if all(tax) else None,
                "revenue_months_known": sum(1 for t in tax if t), "webank_in": webank}

    before = side([_month_add(start, -k) for k in (3, 2, 1)])
    after = side([_month_add(start, k) for k in (0, 1, 2)])
    out = {"disbursed": start, "before": before, "after": after}
    if before["revenue"] and after["revenue"]:
        out["revenue_change"] = round(after["revenue"] / before["revenue"] - 1, 4)
    else:
        out["revenue_change"] = None
        out["note"] = "Chưa có tờ khai thuế đủ 3 tháng mỗi bên: chỉ so được tiền hàng về WeBank."
    if before["webank_in"] == 0:
        out["note_webank"] = "Trước khi vay, BuoyUp chưa theo dõi tài khoản WeBank của bạn."
    return out


def build_year(session: Session, user_id: str, year: str | int, closing_loan_id: str | None = None,
               seller: _Seller | None = None) -> dict[str, Any]:
    """Việc 7: the year (Jan–Dec), or on closing a loan (``closing_loan_id``) the loan's life up to 12 months:
    totals, before/after the disbursement, the loan summary (real interest, days, late instalments), next time."""
    seller = seller or _Seller(session, user_id)
    params = active_params(session)
    loan = None
    if closing_loan_id:
        loan = next((ln for ln in seller.loans if ln.id == closing_loan_id), None)
        if loan is None:
            raise ValueError(f"loan {closing_loan_id} not found for {user_id}")
        d = loan.doc or {}
        first = str(d.get("start_date") or "")[:7]
        last = str(d.get("closed_on") or clock(d).isoformat())[:7]
        months = _months(max(first, _month_add(last, -11)), last)
        kind, period = "closing", loan.id
    else:
        months = [f"{int(year):04d}-{m:02d}" for m in range(1, 13)]
        kind, period = "year", str(year)
        in_year = [ln for ln in seller.loans if str((ln.doc or {}).get("start_date") or "")[:4] == str(year)]
        loan = in_year[-1] if in_year else (seller.loans[-1] if seller.loans else None)
    agg = _aggregate(seller, months, params)
    data: dict[str, Any] = {"kind": kind, "period": period, "currency": seller.currency, **agg,
                            "before_after": _before_after(seller, loan) if loan is not None else {"unavailable": "Chưa có khoản vay"},
                            "loan_summary": _loan_summary(seller, loan) if loan is not None else None,
                            "loans": [_loan_summary(seller, ln) for ln in seller.loans
                                      if str((ln.doc or {}).get("start_date") or "")[:7] <= months[-1]
                                      and str((ln.doc or {}).get("closed_on") or "9999")[:7] >= months[0]],
                            "next_time": _next_time(seller, params),
                            "notes": [coverage_note(agg["coverage"]), _fee_note(seller)],
                            "level": "info", "simulated": True}
    ls = data["loan_summary"]
    if kind == "closing" and ls:
        late = ("không trễ kỳ nào" if not ls["late_instalments"] and not ls["max_overdue_days"]
                else f"trễ {ls['late_instalments']} kỳ, lâu nhất {ls['max_overdue_days']} ngày")
        first_s = (f"Bạn đã tất toán khoản vay {_n(ls['amount'])} tệ sau {ls['days']} ngày, tổng lãi thật "
                   f"{_n(ls['total_interest'])} tệ, {late}.")
    else:
        s = agg["sales"]
        first_s = (f"Năm {period} tờ khai thuế ghi khoảng {_n(s['tax_revenue'])} tệ doanh thu ({s['tax_months']} tháng); "
                   f"tiền hàng về WeBank {_n(s['webank_in'])} tệ." if s["tax_revenue"]
                   else f"Năm {period} tiền hàng về WeBank {_n(s['webank_in'])} tệ.")
    ba = data["before_after"]
    if ba.get("revenue_change") is not None:
        second_s = (f"Doanh thu 3 tháng sau giải ngân {_signed_pct(ba['revenue_change'])} so 3 tháng trước "
                    f"({_n(ba['before']['revenue'])} → {_n(ba['after']['revenue'])} tệ).")
    elif ba.get("after"):
        second_s = f"3 tháng đầu sau giải ngân, tiền hàng về WeBank {_n(ba['after']['webank_in'])} tệ."
    else:
        second_s = f"Tiền trả nợ trong kỳ {_n(agg['cash']['repay'])} tệ."
    data["summary"], data["summary_source"] = f"{first_s} {second_s} {data['next_time']['text']}", "template"
    return data


# --- việc 8: the registration reminder -------------------------------------------------------------------

def _ytd(seller: _Seller, as_of: date) -> tuple[int, str]:
    year, upto = str(as_of.year), as_of.strftime("%Y-%m")
    rows = ((seller.data.get("revenue") or {}).get("monthly_12m") or [])
    ytd = sum(int(r.get("amount") or 0) for r in rows if str(r.get("month") or "")[:4] == year
              and str(r.get("month"))[:7] <= upto)
    if ytd > 0:
        return ytd, "tax"
    webank = sum(int(i.get("amount") or 0) for d in seller.docs for i in (d.get("account") or {}).get("inflows") or []
                 if str(i.get("on") or "")[:4] == year)
    share = (((seller.app_doc.get("verification") or {}).get("derived") or {}).get("history") or {}).get("webank_share_of_tax")
    if webank and isinstance(share, (int, float)) and share > 0:
        return int(round(webank / min(1.0, float(share)))), "webank_coverage"
    return webank, "webank"


def registration_check(session: Session, user_id: str, as_of: date, seller: _Seller | None = None) -> dict[str, Any] | None:
    """Việc 8: an individual seller (not a household business, not a company) whose revenue this year reached
    ``individual_registration_warn_share`` × ``individual_registration_threshold`` is told once a year that
    above the threshold she must register (LAW-REG-01, citations checked verbatim). ``None`` otherwise."""
    seller = seller or _Seller(session, user_id)
    if seller.app is None or seller.app_doc.get("borrower_type") != "individual":
        return None
    year = str(as_of.year)
    if session.scalar(select(BuSellerReport.id).where(BuSellerReport.seller_user_id == user_id,
                                                      BuSellerReport.kind == "registration",
                                                      BuSellerReport.period == year)):
        return None
    params = active_params(session)
    threshold = int(params["legal"]["individual_registration_threshold"])
    warn = float(params["legal"]["individual_registration_warn_share"])
    ytd, basis = _ytd(seller, as_of)
    if ytd < threshold * warn:
        return None
    caps = params["product"]["type_cap"]
    cites = legal.citations("LAW-REG-01", as_of)
    ok = bool(cites) and all(c["verified"] and c["effective"] for c in cites)
    over = ytd > threshold
    first = f"Doanh thu năm nay của bạn khoảng {_n(ytd)} tệ{f', đã vượt {_n(threshold)} tệ' if over else ''}."
    if ok:
        law = (f"Theo Điều 8 Quy định giám sát giao dịch trực tuyến (2021), bán hàng qua mạng với doanh thu năm "
               f"trên {_n(threshold)} tệ phải đăng ký kinh doanh.")
    else:
        law = (f"Cá nhân bán hàng qua mạng có doanh thu năm trên {_n(threshold)} tệ thường phải đăng ký kinh doanh; "
               "bạn hỏi cơ quan quản lý thị trường nơi cư trú để chắc chắn.")
    third = (f"Đăng ký xong, hạn mức BuoyUp cho hộ kinh doanh tới {_n(caps['individual_business'])} tệ thay vì "
             f"{_n(caps['individual'])}.")
    notes = ["Doanh thu tính theo tờ khai thuế từ đầu năm." if basis == "tax"
             else "Chưa có tờ khai thuế năm nay: doanh thu ước từ tiền hàng về WeBank chia độ phủ đã biết."
             if basis == "webank_coverage" else "Chưa có tờ khai thuế năm nay: chỉ tính tiền hàng về WeBank."]
    notes.append("Doanh thu mọi cửa hàng của bạn (trên một hay nhiều sàn) được cộng chung khi so với ngưỡng.")
    notes.append("Căn cứ đã kiểm nguyên văn trong kho văn bản luật của BuoyUp: "
                 + "; ".join(dict.fromkeys(c["law"] for c in cites if c["verified"])) + "."
                 if ok else "BuoyUp chưa kiểm được nguyên văn điều luật nên không trích dẫn.")
    # For staff (not shown as a note): why the citation differs from the plan's.
    legal_note = ("Kế hoạch nêu Điều 50 市场主体登记管理条例实施细则 (2022); văn bản đó chưa có trong corpus.json (không có "
                  "nguồn trong docs/agents/TQ) nên không thêm. Ngưỡng nguyên văn \"年交易额累计不超过10万元\" có trong "
                  "NETTRADE-2021#8 (网络交易监督管理办法, áp dụng ECOM-2018#10): quy tắc LAW-REG-01 trích hai điều này.")
    return {"kind": "registration", "period": year, "currency": seller.currency, "as_of": as_of.isoformat(),
            "ytd": ytd, "ytd_basis": basis, "threshold": threshold, "warn_share": warn,
            "warn_at": int(threshold * warn), "over": over, "rule": "LAW-REG-01",
            "citations": cites if ok else [], "type_cap": {"individual": caps["individual"],
                                                            "individual_business": caps["individual_business"]},
            "notes": notes, "legal_note": legal_note, "level": "warn", "simulated": True,
            "summary": f"{first} {law} {third}", "summary_source": "template"}


# --- the optional model rewrite ------------------------------------------------------------------------

_THOUSANDS_COMMA = re.compile(r"\d{1,3}(?:,\d{3})+(?!\d)")


def _allowed(data: dict[str, Any]) -> set[float]:
    from app.agents.agent2_advise import _walk

    out: set[float] = set()
    _walk({k: v for k, v in data.items() if k not in _VOLATILE}, out)
    _walk(data.get("summary"), out)  # every figure of the template (percent, days, months)
    for v in list(out):
        if v == int(v):
            out.add(float(int(v)))
    return out


def numbers_ok(text: str, allowed: set[float]) -> bool:
    """Agent 2's filter plus "50,000"-style thousands (which it reads as 50.0)."""
    from app.agents.agent2_advise import blocked

    if blocked(text, allowed):
        return False
    return all(float(tok.replace(",", "")) in allowed for tok in _THOUSANDS_COMMA.findall(text))


def _rewrite(data: dict[str, Any]) -> None:
    """One try at a friendlier summary; the template stands unless every figure is one of the report's."""
    from app.agents import llm_tools
    from app.platform.guards import forbidden_phrases

    prov = llm_tools.provider()
    if prov is None:
        return
    facts = {k: v for k, v in data.items() if k not in _VOLATILE and k not in ("citations",)}
    facts["template"] = data["summary"]
    try:
        draft = llm_tools.run_sync(prov.generate_text(system_prompt=SUMMARY_SYSTEM,
                                                      user_input=json.dumps(facts, ensure_ascii=False)[:12000])).strip()
    except Exception:  # noqa: BLE001 - the template stands
        return
    if draft and len(draft) <= 700 and numbers_ok(draft, _allowed(data)) and not forbidden_phrases(draft, "intake"):
        data["summary"], data["summary_source"] = draft, "llm"


# --- storing ---------------------------------------------------------------------------------------------

def _facts(data: dict[str, Any] | None) -> str:
    return json.dumps({k: v for k, v in (data or {}).items() if k not in _VOLATILE}, ensure_ascii=False,
                      sort_keys=True, default=str)


def store(session: Session, seller: _Seller, data: dict[str, Any], use_model: bool = True) -> tuple[BuSellerReport, bool]:
    """Write (or overwrite) the report of (seller, kind, period). Same facts as stored → nothing written."""
    kind, period = data["kind"], str(data["period"])
    row = session.scalar(select(BuSellerReport).where(BuSellerReport.seller_user_id == seller.user_id,
                                                      BuSellerReport.kind == kind, BuSellerReport.period == period))
    if row is not None and _facts(row.data) == _facts(json.loads(json.dumps(data, default=str))):
        return row, False
    if use_model:
        _rewrite(data)
    existed = row is not None
    report_id = row.id if row is not None else "srp_" + secrets.token_hex(8)
    data["report_id"] = report_id
    entry = chain.record(session, seller.user_id, "seller_report", data)
    data["hash"], data["chain_tx"] = entry.fingerprint, entry.tx
    if row is None:
        row = BuSellerReport(id=report_id, seller_user_id=seller.user_id, kind=kind, period=period)
        session.add(row)
    row.data, row.hash, row.chain_tx, row.at = data, entry.fingerprint, entry.tx, utcnow()
    events.log(session, seller.application_id(), "agent5", "seller_report",
               f"Agent 5 lập báo cáo {kind} {period} cho người bán",
               {"report_id": report_id, "seller_user_id": seller.user_id, "kind": kind, "period": period,
                "chain_tx": entry.tx, "updated": existed}, entry.fingerprint)
    session.flush()
    return row, True


# --- what is due --------------------------------------------------------------------------------------------

def _seller_as_of(seller: _Seller, as_of: date) -> date:
    """The seller's own date: never before the clock of her loans (the demo moves a loan's clock forward)."""
    days = [as_of] + [parse_date((ln.doc or {}).get("clock")) or as_of for ln in seller.loans]
    return max(days)


def due_periods(seller: _Seller, as_of: date) -> list[tuple[str, str, str | None]]:
    """(kind, period, closing loan) of every report due on ``as_of``: complete months / quarters / years with a
    loan running (the last MAX_BACKFILL_MONTHS months at most), one closing report per closed loan."""
    first = seller.first_month()
    if first is None:
        return []
    this_month = as_of.strftime("%Y-%m")
    closes = [str((ln.doc or {}).get("closed_on") or "")[:7] for ln in seller.loans]
    open_loans = any(ln.status != "closed" for ln in seller.loans)
    last_active = this_month if open_loans else max([c for c in closes if c] or [this_month])
    months = [m for m in _months(first, _month_add(this_month, -1)) if m <= last_active][-MAX_BACKFILL_MONTHS:]
    out: list[tuple[str, str, str | None]] = [("month", m, None) for m in months]
    quarters = sorted({quarter_of(m) for m in months})
    out += [("quarter", q, None) for q in quarters if quarter_months(q)[-1] < this_month]
    years = sorted({m[:4] for m in months})
    out += [("year", y, None) for y in years if y < str(as_of.year)]
    out += [("closing", ln.id, ln.id) for ln in seller.loans if ln.status == "closed" and (ln.doc or {}).get("closed_on")]
    return out


def run_for(session: Session, user_id: str, as_of: date, use_model: bool = True,
            commit_each: bool = False) -> list[BuSellerReport]:
    """Every report due for one seller. Existing past periods are kept; the latest month / quarter / year and the
    closing report are rebuilt and rewritten only when their facts changed."""
    with capabilities.acting("agent5"):
        seller = _Seller(session, user_id)
        day = _seller_as_of(seller, as_of)
        existing = {(r.kind, r.period) for r in session.scalars(
            select(BuSellerReport).where(BuSellerReport.seller_user_id == user_id))}
        due = due_periods(seller, day)
        latest: dict[str, str] = {}
        for kind, period, _l in due:
            latest[kind] = max(latest.get(kind, ""), period)
        made: list[BuSellerReport] = []
        for kind, period, loan_id in due:
            if (kind, period) in existing and kind != "closing" and period != latest.get(kind):
                continue
            if kind == "month":
                data = build_month(session, user_id, period, seller)
            elif kind == "quarter":
                data = build_quarter(session, user_id, period, seller)
            elif kind == "year":
                data = build_year(session, user_id, period, seller=seller)
            else:
                data = build_year(session, user_id, day.year, closing_loan_id=loan_id, seller=seller)
            row, changed = store(session, seller, data, use_model)
            if changed:
                made.append(row)
                if commit_each:
                    session.commit()
        reg = registration_check(session, user_id, day, seller)
        if reg is not None:
            row, changed = store(session, seller, reg, use_model)
            if changed:
                made.append(row)
        return made


def sellers(session: Session) -> list[str]:
    """Sellers with a loan, or with an individual application Agent 1 read (for the registration reminder)."""
    ids = set(session.scalars(select(BuLoan.seller_user_id).distinct()))
    for a in session.scalars(select(BuApplication).where(BuApplication.status != "withdrawn")):
        doc = a.doc or {}
        if doc.get("borrower_type") == "individual" and ((doc.get("internal") or {}).get("data")):
            ids.add(a.seller_user_id)
    return sorted(ids)


def run_due(session: Session, as_of: date, user_ids: list[str] | None = None,
            use_model: bool = True) -> list[BuSellerReport]:
    """Called by the autopilot (``loop.run_reports``) and the demo's simulate-advance: every report due."""
    made: list[BuSellerReport] = []
    for uid in (user_ids if user_ids is not None else sellers(session)):
        made += run_for(session, uid, as_of, use_model)
    return made


# --- views ----------------------------------------------------------------------------------------------------

def title_of(r: BuSellerReport) -> str:
    if r.kind == "month":
        return f"Báo cáo tháng {int(r.period[5:7])}/{r.period[:4]}"
    if r.kind == "quarter":
        return f"Báo cáo quý {r.period[-1]}/{r.period[:4]}"
    if r.kind == "year":
        return f"Báo cáo năm {r.period}"
    if r.kind == "closing":
        return "Báo cáo tất toán khoản vay"
    return f"Nhắc đăng ký kinh doanh {r.period}"


def _iso(dt: Any) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def report_brief(r: BuSellerReport) -> dict[str, Any]:
    data = r.data or {}
    cov = data.get("coverage") or {}
    return {"id": r.id, "kind": r.kind, "period": r.period, "title": title_of(r), "at": _iso(r.at),
            "read_at": _iso(r.read_at), "level": data.get("level") or "info",
            "summary": data.get("summary") or "", "coverage_share": cov.get("share"),
            "chain_tx": r.chain_tx}


def report_view(r: BuSellerReport) -> dict[str, Any]:
    return {**report_brief(r), "seller_user_id": r.seller_user_id, "hash": r.hash,
            "data": {k: v for k, v in (r.data or {}).items() if k not in ("hash", "chain_tx", "report_id")}}


def _sort_key(r: BuSellerReport) -> tuple[str, str]:
    return (_iso(r.at) or "", r.period)


def list_for(session: Session, user_id: str) -> list[BuSellerReport]:
    rows = list(session.scalars(select(BuSellerReport).where(BuSellerReport.seller_user_id == user_id)))
    return sorted(rows, key=_sort_key, reverse=True)
