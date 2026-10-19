"""/v4/me/bank: "Ngân hàng của tôi" (review 17/10/2026): the seller's WeBank business account as BuoyUp
sees it: card, balance, recent money in and out, and every loan with what is still owed.

Read-only. The account lives at WeBank (core banking); BuoyUp only holds what passed through the loans
it serviced, so before the first disbursement the account is not known yet (``account: null``).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.agent4b_monitor import _repaid_on, clock, due_amount, next_row, owed_now, today
from app.core import cashflow
from app.core.cashflow import GROUP_LABELS
from app.core.params import active_params
from app.data_sources import profiles
from app.platform.db.session import get_session
from app.platform.security import require_roles
from app.platform.tables import BuApplication, BuLoan, BuRepayment, BuUser

router = APIRouter(prefix="/me", tags=["v4-my-bank"])
_sellers = require_roles("seller")


def _card(number: str | None) -> dict[str, Any] | None:
    digits = "".join(ch for ch in str(number or "") if ch.isdigit())
    if len(digits) < 6:
        return None
    return {"bank": "WeBank", "kind": "Thẻ ghi nợ tài khoản kinh doanh", "masked": f"6222 •••• •••• {digits[-4:]}",
            "account_masked": "•••• " + digits[-4:], "simulated": True}


@router.get("/bank")
def my_bank(user: BuUser = Depends(_sellers), session: Session = Depends(get_session)) -> dict:
    loans = list(session.scalars(select(BuLoan).where(BuLoan.seller_user_id == user.id).order_by(BuLoan.created_at.desc())))
    latest = loans[0] if loans else None
    account = None
    movements: list[dict[str, Any]] = []
    for ln in loans:
        acc = (ln.doc or {}).get("account") or {}
        # Every movement has a stable id: the app shows a notification for ids it has not seen yet.
        movements += [{"id": i.get("id") or f"{ln.id}:in:{n}", "on": i.get("on"), "at": i.get("at"), "kind": "in",
                       "label": f"Tiền hàng {i['source']}" if i.get("source") else "Tiền hàng về",
                       "amount": int(i.get("amount") or 0), "balance_after": i.get("balance_after")}
                      for n, i in enumerate(acc.get("inflows") or [])]
        movements += [{"id": t.get("id") or f"{ln.id}:out:{n}", "on": t.get("on"), "at": t.get("at"), "kind": "out",
                       "label": t.get("memo") or t.get("label") or "Chi", "amount": -int(t.get("amount") or 0),
                       "group": t.get("group"), "group_label": GROUP_LABELS.get(t.get("group") or "", None),
                       "balance_after": t.get("balance_after")}
                      for n, t in enumerate(acc.get("transfers") or [])]
        movements += [{"id": r.id, "on": _repaid_on(r), "at": r.at.isoformat() + "Z", "kind": "repay",
                       "label": "Trích trả nợ BuoyUp", "amount": -int(r.swept)}
                      for r in session.scalars(select(BuRepayment).where(BuRepayment.loan_id == ln.id))]
        payee = (ln.doc or {}).get("payee") or {}
        movements.append({"id": ln.id, "on": (ln.doc or {}).get("start_date"),
                          "at": ln.created_at.isoformat() + "Z" if ln.created_at else None, "kind": "loan",
                          "label": "Giải ngân khoản vay BuoyUp",
                          "amount": int(payee.get("to_account") or ln.doc.get("amount") or 0)})
    if latest is not None:
        acc = (latest.doc or {}).get("account") or {}
        account = {"bank": "WeBank", "number_masked": "•••• " + str(acc.get("number") or "")[-4:],
                   "balance": int(acc.get("balance") or 0), "currency": latest.currency,
                   "inflow_total": int(acc.get("inflow_total") or 0), "card": _card(acc.get("number")),
                   "receiving_platform_payouts": bool(((latest.doc or {}).get("receiving_account") or {}).get("locked"))}
    items = []
    for ln in loans:
        d = ln.doc or {}
        nr = next_row(d)
        due, due_min = due_amount(d, active_params(session), nr) if nr and "interest_to" in d else (
            int((nr or {}).get("payment_est") or 0), False)
        items.append({"id": ln.id, "status": ln.status, "amount": int(d.get("amount") or 0), "currency": ln.currency,
                      "rate": d.get("rate"), "tenor_m": d.get("tenor_m"), "start_date": d.get("start_date"),
                      "final_due_date": d.get("final_due_date"), "principal_outstanding": int(d.get("principal_outstanding") or 0),
                      "repaid": int(ln.repaid or 0), "owed_now": owed_now(d),
                      "next_due": {"date": nr["due_date"], "amount": due, "minimum": due_min} if nr else None})
    offer_app = session.scalar(select(BuApplication).where(BuApplication.seller_user_id == user.id,
                                                           BuApplication.status.in_(("offered", "selected")))
                               .order_by(BuApplication.updated_at.desc()).limit(1))
    offer = ((offer_app.doc or {}).get("offer") or {}) if offer_app else {}
    movements = sorted((m for m in movements if m["on"]), key=lambda m: (m["on"], m.get("at") or ""), reverse=True)
    month = max((m["on"][:7] for m in movements), default="")
    month_in = sum(m["amount"] for m in movements if m["kind"] == "in" and m["on"][:7] == month)
    month_out = -sum(m["amount"] for m in movements if m["kind"] in ("out", "repay") and m["on"][:7] == month)
    movements = movements[:60]
    coverage = None
    if month and loans:  # việc 9: how much of this month's revenue reached WeBank ("≈ 45 % doanh thu của bạn")
        from app.agents.agent5_seller_reports import coverage as month_coverage

        cov = month_coverage(session, user.id, month)
        coverage = {k: cov.get(k) for k in ("share", "basis", "month")} if cov.get("share") is not None else None
    return {"account": account, "loans": items, "movements": movements,
            "open_limit": {"application_id": offer_app.id, "limit": offer.get("limit"), "expires_at": offer.get("expires_at")}
            if offer_app and offer.get("limit") else None,
            "totals": {"outstanding": sum(i["principal_outstanding"] for i in items if i["status"] in ("active", "overdue")),
                       "active_loans": sum(1 for i in items if i["status"] in ("active", "overdue")),
                       "month": month, "month_in": month_in, "month_out": month_out, "coverage": coverage},
            "simulated": True}


def _profile_mix(name: Any) -> list[dict[str, Any]]:
    """Applications made before goods_mix existed: recompute it from the demo profile they came from."""
    try:
        return profiles.scenario(str(name)).get("goods_mix") or [] if name else []
    except (FileNotFoundError, KeyError, ValueError):
        return []


def _goods(mix: list[dict[str, Any]], revenue_12m: int) -> list[dict[str, Any]]:
    """Revenue per item over 12 months, estimated by each item's share of purchases (no item-level sales
    invoices); items under 1% of purchases are folded into "Khác", shown only when it reaches 1% itself."""
    total = sum(r["cost"] for r in mix)
    if not total:
        return []
    rows, other = [], 0
    for r in mix:
        if r["cost"] / total < 0.01:
            other += r["cost"]
        else:
            rows.append({"item": r["item"], "share": round(r["cost"] / total, 4), "qty": r.get("qty", 0),
                         "revenue_est": round(revenue_12m * r["cost"] / total)})
    if other / total >= 0.01:
        rows.append({"item": "Khác", "share": round(other / total, 4), "qty": 0,
                     "revenue_est": round(revenue_12m * other / total)})
    return rows


def _business_moves(seller: Any, last_day: date) -> list[dict[str, Any]]:
    """Every movement of the business account on its business day (``on``), never its wall-clock time:
    disbursements (the loan's start day), sales money in, transfers out, debits for BuoyUp (the day in the
    repayment's detail ``as_of``) and the demo top-ups made to settle a sample loan. Days after ``last_day``
    are left out (no future)."""
    out: list[dict[str, Any]] = []
    for ln in seller.loans:
        doc = ln.doc or {}
        acc = doc.get("account") or {}
        if doc.get("start_date"):
            out.append({"on": str(doc["start_date"])[:10], "at": ln.created_at.isoformat() if ln.created_at else "",
                        "loan_id": ln.id, "kind": "loan", "amount": int((doc.get("payee") or {}).get("to_account") or doc.get("amount") or 0)})
        out += [{"on": str(i.get("on") or "")[:10], "at": str(i.get("at") or ""), "loan_id": ln.id, "kind": "in",
                 "amount": int(i.get("amount") or 0)} for i in acc.get("inflows") or []]
        out += [{"on": str(t.get("on") or "")[:10], "at": str(t.get("at") or ""), "loan_id": ln.id, "kind": "out",
                 "amount": -int(t.get("amount") or 0)} for t in acc.get("transfers") or []]
        fallback = str(doc.get("closed_on") or doc.get("clock") or doc.get("start_date") or "")[:10]
        out += [{"on": str(t.get("on") or fallback)[:10], "at": str(t.get("at") or ""), "loan_id": ln.id, "kind": "topup",
                 "amount": int(t.get("amount") or 0)} for t in acc.get("demo_topups") or []]
    out += [{"on": r["at"][:10], "at": r["ts"].isoformat() if isinstance(r["ts"], datetime) else str(r["ts"] or ""),
             "loan_id": r["loan_id"], "kind": "repay", "amount": -int(r["swept"])} for r in seller.repaid()]
    end = last_day.isoformat()
    # Same day: money in before the debits and the spending of that day, as the day's settlement runs first.
    rank = {"loan": 0, "topup": 1, "in": 2, "repay": 3, "out": 4}
    return sorted((m for m in out if m["on"] and m["on"] <= end),
                  key=lambda m: (m["on"], rank[m["kind"]], m["at"].rstrip("Z")))


@router.get("/stats")
def my_stats(month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
                                       description="Tháng xem số dư cuối ngày (YYYY-MM); mặc định tháng hiện tại"),
             user: BuUser = Depends(_sellers), session: Session = Depends(get_session)) -> dict:
    """Thống kê (17/10/2026; one time frame since 18/10/2026): the seller's own movement, for the four charts.

    Every series sits on the same frame: the 12 months ending with the current month (the clock of the
    latest loan, today without a loan); money is placed on its business day (``on``; a debit on the ``as_of``
    of its repayment detail), never on the wall-clock time it was recorded.

    - ``revenue_12m``: the 12 months, each with ``tax`` (the tax filing Agent 1 read, ``None`` when not filed),
      ``webank_in`` (sales money that reached WeBank that month; ``None`` before any loan), ``estimate`` and
      ``basis`` (``cashflow.coverage``: tax-filed revenue, else the loan's forecast, never below what reached
      WeBank), ``share`` (WeBank coverage) and ``amount`` (= ``estimate``, kept for older readers);
    - ``webank_by_month``: the same 12 months: ``in`` (sales money), ``loan`` (disbursed), ``repay``, ``out``
      (spending), ``topup``;
    - ``balance_daily``: the end-of-day balance for every day of ``month`` (default the current month) up to
      today (``None`` before the first disbursement), with the day's movements and the due dates of the month;
      ``months_available`` lists the months that can be shown. The balance is the account "Ngân hàng của tôi"
      shows: on each day the loans open that day (between loans, the latest one), replayed from their movements;
    - ``kpi``: the four figures at the top, on the same frame (``revenue`` of the current month or the latest
      month with a figure, ``top_item``, ``webank_in`` of the current month, ``balance`` at the end of today);
    - ``goods``: revenue per item over the same 12 months (``goods_period``), split by each item's share of
      the purchase invoices;
    - ``month_bridge``: the current month's opening balance → + money in → − repayments → − spending → closing;
    - ``balance``: every movement with the balance after it (business-day order, last 60), as before;
    - ``schedule``: principal and interest of every instalment of the open (or latest) loan.
    """
    from app.agents import agent5_seller_reports as reports

    seller = reports._Seller(session, user.id)
    loans = seller.loans
    latest = loans[-1] if loans else None
    today_ = clock(latest.doc or {}) if latest is not None else today()
    current = today_.isoformat()[:7]
    months = [reports._month_add(current, k) for k in range(-11, 1)]
    moves = _business_moves(seller, today_)

    # Balance replay, day by day.
    deltas: dict[str, dict[str, int]] = {}
    for m in moves:
        d = deltas.setdefault(m["on"], {"in": 0, "out": 0, "repay": 0, "loan": 0, "topup": 0})
        d[m["kind"]] += abs(m["amount"])
    first_on = moves[0]["on"] if moves else None

    def closing(upto: str) -> int:  # every loan's account summed, at the end of day ``upto`` (legacy fields)
        return sum(m["amount"] for m in moves if m["on"] <= upto)

    # The balance shown (chart 3 and its KPI) is the account "Ngân hàng của tôi" shows: on a day, the account
    # of the loans open that day (disbursed, not closed before it); between loans, the latest one. A sample loan
    # settled by "Làm mới khoản vay mẫu" keeps its own leftover, which the next loan's account does not carry.
    # (A demo loan's clock may have run ahead of the real date: once a newer loan is disbursed, a settled
    # one no longer counts, whatever its closing day.)
    spans = []
    for ln in loans:  # in order of creation
        doc = ln.doc or {}
        if doc.get("start_date"):
            spans.append((ln.id, str(doc["start_date"])[:10], str(doc.get("closed_on") or "")[:10] or None))

    def live(day: str) -> set[str]:
        started = [(n, sp) for n, sp in enumerate(spans) if sp[1] <= day]
        if not started:
            return set()
        newest = started[-1][0]  # still open, or the newest disbursed (a settled one only while it is the newest)
        return {lid for n, (lid, _start, closed) in started if closed is None or n == newest}

    def account_on(day: str) -> int | None:
        ids = live(day)
        return sum(m["amount"] for m in moves if m["on"] <= day and m["loan_id"] in ids) if ids else None

    by_month = {mo: {"in": 0, "loan": 0, "repay": 0, "out": 0, "topup": 0} for mo in months}
    for m in moves:
        if m["on"][:7] in by_month:
            by_month[m["on"][:7]][m["kind"]] += abs(m["amount"])

    # Revenue: the same 12 months, tax filing beside the money that reached WeBank.
    revenue = []
    for mo in months:
        tax = seller.tax_month(mo)
        loan = seller.loan_active_in(mo)
        forecast = int((loan.doc or {}).get("forecast_monthly") or 0) if loan is not None else 0
        webank = by_month[mo]["in"] if loan is not None or by_month[mo]["in"] else None
        cov = cashflow.coverage(webank, tax, forecast)
        estimate = cov.get("estimate") if (tax or forecast or webank) else None
        revenue.append({"month": mo, "tax": tax, "webank_in": webank, "forecast": forecast or None,
                        "estimate": int(estimate) if estimate else None, "basis": cov["basis"] if estimate else "none",
                        "share": cov.get("share") if webank is not None else None,
                        "amount": int(estimate) if estimate else None})
    known = [r for r in revenue if r["estimate"]]
    kpi_rev = next((r for r in reversed(revenue) if r["estimate"]), None)
    change = None
    if kpi_rev is not None:  # month on month only between two tax-filed months (a forecast is not a sale)
        i = revenue.index(kpi_rev)
        prev = revenue[i - 1] if i else None
        if prev and kpi_rev["basis"] == "tax" and prev["basis"] == "tax" and prev["estimate"]:
            change = round(kpi_rev["estimate"] / prev["estimate"] - 1, 4)

    # Goods: the 12 months of the revenue chart, by each item's share of the purchase invoices.
    mix: list[dict[str, Any]] = []
    for a in seller.apps:
        data = (((a.doc or {}).get("internal") or {}).get("data") or {})
        if (data.get("revenue") or {}).get("monthly_12m"):
            mix = data.get("goods_mix") or _profile_mix(data.get("profile"))
            break
    goods_total = sum(r["estimate"] for r in known)
    goods = _goods(mix, goods_total)

    # End-of-day balance of the month shown.
    available = []
    if first_on:
        mo = first_on[:7]
        while mo <= current and len(available) < 400:
            available.append(mo)
            mo = reports._month_add(mo, 1)
    shown = month if month in available else (available[-1] if available else None)
    balance_daily = None
    if shown:
        end = reports._month_end(shown)
        days_in = end.day
        last = min(end, today_)
        days = []
        for k in range(1, last.day + 1):
            on = f"{shown}-{k:02d}"
            d = deltas.get(on, {"in": 0, "out": 0, "repay": 0, "loan": 0, "topup": 0})
            days.append({"date": on, "balance": account_on(on), **d})
        dues = []
        for ln in loans:
            closed_on = str((ln.doc or {}).get("closed_on") or "")[:10]
            for r in (ln.doc or {}).get("schedule") or []:
                due_on = str(r.get("due_date") or "")[:10]
                if due_on[:7] == shown and r.get("status") != "prepaid" and not (closed_on and due_on > closed_on):
                    dues.append({"date": r["due_date"], "k": r.get("k"), "amount": int(r.get("payment_est") or 0),
                                 "status": r.get("status"), "loan_id": ln.id})
        i = available.index(shown)
        balance_daily = {"month": shown, "days_in_month": days_in, "today": today_.isoformat(), "days": days,
                         "dues": sorted(dues, key=lambda x: x["date"]),
                         "prev": available[i - 1] if i else None,
                         "next": available[i + 1] if i + 1 < len(available) else None}

    # The old movement-by-movement replay and the month bridge (current month).
    balance, series = 0, []
    for m in moves:
        balance += m["amount"]
        series.append({"at": m["on"], "kind": m["kind"], "amount": m["amount"], "balance": balance})
    cur = by_month[current]
    opening = closing((date.fromisoformat(current + "-01") - timedelta(days=1)).isoformat())
    bridge = {"month": current, "opening": opening, "in": cur["in"] + cur["loan"] + cur["topup"], "repay": cur["repay"],
              "out": cur["out"], "closing": balance} if moves else None
    open_loan = next((ln for ln in reversed(loans) if ln.status in ("active", "overdue")), latest)
    schedule = [{"k": r["k"], "due_date": r["due_date"], "principal": int(r.get("principal") or 0),
                 "interest": int(r.get("interest_est") or 0), "status": r.get("status")}
                for r in ((open_loan.doc or {}).get("schedule") or [])] if open_loan else []
    top = goods[0] if goods else None
    kpi = {"month": current,
           "revenue": {"month": kpi_rev["month"], "amount": kpi_rev["estimate"], "basis": kpi_rev["basis"],
                       "change": change} if kpi_rev else None,
           "top_item": {"item": top["item"], "share": top["share"]} if top else None,
           "webank_in": {"month": current, "amount": cur["in"]} if loans else None,
           "balance": {"on": today_.isoformat(), "amount": account_on(today_.isoformat())} if moves else None}
    return {"currency": seller.currency, "window": {"from": months[0], "to": current, "today": today_.isoformat()},
            "revenue_12m": revenue, "revenue_change": change, "kpi": kpi,
            "webank_by_month": [{"month": mo, **by_month[mo]} for mo in months],
            "balance_daily": balance_daily, "months_available": available,
            "balance": series[-60:], "month_bridge": bridge, "goods": goods,
            "goods_period": {"from": known[0]["month"], "to": known[-1]["month"], "months": len(known),
                             "total": goods_total} if known else None,
            "schedule": schedule, "loan_id": open_loan.id if open_loan else None, "simulated": True}
