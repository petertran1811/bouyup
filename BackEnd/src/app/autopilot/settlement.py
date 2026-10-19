"""Platform settlement feed (demo stand-in, 17/10/2026; by business day since 18/10/2026).

In production the platforms (Douyin, Taobao, …) settle the seller's sales into the WeBank business
account and WeBank notifies BuoyUp through ``POST /v4/webank/inflows``. Without those systems, this job
plays the platform, through the same code path as the webhook. Enabled only with ``PLATFORM_PAYOUT_FEED=true``.

**One payout per business day.** Every open loan receives exactly one payout for each day of its life, booked
on that day (``on``), with the deterministic id ``"<platform>:<loan_id>:<YYYY-MM-DD>"`` (re-running never
credits a day twice). Each run of :func:`settle` catches up the days from the day after the last one settled
(``doc.settled_through``; the disbursement day for a new loan) to the loan's clock, never past it: no future
day is settled. ``PLATFORM_PAYOUT_MINUTES`` only paces how often the autopilot runs the job; it does not change
the amounts. ``POST /loans/{id}/simulate-advance`` settles each day it moves through, before Agent 4's tick of
that day, so a due date has that day's money to collect.

The day's payout (:func:`day_amount`)::

    amount(d) = M × s × season(month of d) × week(weekday of d) × noise(loan, d) / days_in_month(d)

- ``M``: the store's monthly revenue forecast in the loan (``doc.forecast_monthly``, block B4; else ``prudent``);
- ``s``: the share of the store's revenue known to reach the WeBank account, net of the platform fee
  (:func:`webank_share`): the share Agent 1 measured on earlier loans
  (``verification.derived.history.webank_share_of_tax``), else the share of tax-filed sales that reached the
  declared accounts on the bank statement (``internal.data.inflows.to_declared_accounts_vs_tax_sales``), else
  ``1 − platform fee`` (all sales settle to WeBank, the fee kept back);
- ``season``: a light seasonality from the store's own tax-filed months:
  ``1 + 0.3 × (revenue of that calendar month ÷ 12-month average − 1)``, kept within 0.85–1.25 (1 without data);
- ``week``: the weekly rhythm (Monday 0.90 … Saturday 1.15, Sunday 1.05; mean 1);
- ``noise``: a steady ±15 % per (loan, day) from a hash, so the same day always gets the same amount.

So a month's payouts add up to about ``M × s`` (× its season): the month's money in matches the store's revenue
as far as WeBank sees it, and the "Tiền hàng về WeBank" bars sit beside the tax-filed revenue in the statistics.

:func:`spend` (SELLER_SERVICES_PLAN §3.3) plays WeBank's outflow notifications, also by business day: for each
day settled, 0–2 business expenses taken in turn from the demo dossier's bank statement
(``bank_statement.outflows``, e.g. "Lương cộng tác viên"), booked on that day, keeping the month's spending at
most 70 % of the month's money in. It goes through ``webank.debit`` like ``POST /v4/webank/outflows``: only the
mirrored balance goes down.
"""

from __future__ import annotations

import calendar
import hashlib
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import agent4b_monitor as agent4
from app.core import cashflow
from app.data_sources import profiles
from app.platform.config import settings
from app.platform.db.tables import utcnow
from app.platform.tables import BuApplication, BuLoan, save_json

PLATFORM_NAMES = {"douyin": "Douyin", "taobao": "Taobao", "tmall": "Tmall", "jd": "JD", "pinduoduo": "Pinduoduo",
                  "kuaishou": "Kuaishou"}
WEEKDAY = (0.90, 0.92, 0.95, 0.98, 1.05, 1.15, 1.05)  # Monday … Sunday; mean 1
SEASON_DAMPING, SEASON_MIN, SEASON_MAX = 0.3, 0.85, 1.25
NOISE = 0.15


def _hash(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


def webank_share(app_doc: dict[str, Any] | None) -> tuple[float, str]:
    """``(s, basis)``: the share of the store's revenue that reaches the WeBank account (see the module doc)."""
    app_doc = app_doc or {}
    hist = (((app_doc.get("verification") or {}).get("derived") or {}).get("history") or {})
    share = hist.get("webank_share_of_tax")
    if isinstance(share, (int, float)) and share > 0:
        return min(1.0, float(share)), "history"
    data = ((app_doc.get("internal") or {}).get("data") or {})
    stated = (data.get("inflows") or {}).get("to_declared_accounts_vs_tax_sales")
    if isinstance(stated, (int, float)) and stated > 0:
        return min(1.0, float(stated)), "statement"
    tax = data.get("tax") or {}
    fee = float(tax["platform_fee"]) if isinstance(tax.get("platform_fee"), (int, float)) and 0 < tax["platform_fee"] < 0.5 \
        else cashflow.DEFAULT_PLATFORM_FEE
    return 1.0 - fee, "fee"


def season(app_doc: dict[str, Any] | None, month: int) -> float:
    """Light seasonality of calendar month ``month`` (1–12) from the store's tax-filed months; 1 without data."""
    rows = (((((app_doc or {}).get("internal") or {}).get("data") or {}).get("revenue") or {}).get("monthly_12m")) or []
    amounts = {int(str(r.get("month"))[5:7]): int(r.get("amount") or 0) for r in rows if str(r.get("month") or "")[5:7]}
    avg = sum(amounts.values()) / len(amounts) if amounts else 0
    if not avg or not amounts.get(month):
        return 1.0
    return min(SEASON_MAX, max(SEASON_MIN, 1 + SEASON_DAMPING * (amounts[month] / avg - 1)))


def day_amount(loan: BuLoan, day: date, app_doc: dict[str, Any] | None = None) -> int:
    """The payout of business day ``day`` (formula in the module doc); deterministic in (loan, day)."""
    doc = loan.doc or {}
    monthly = int(doc.get("forecast_monthly") or doc.get("prudent") or 0)
    share, _basis = webank_share(app_doc)
    noise = 1 - NOISE + (_hash(f"{loan.id}:{day.isoformat()}") % 1001) / 1000 * 2 * NOISE
    days = calendar.monthrange(day.year, day.month)[1]
    return max(1, round(monthly * share * season(app_doc, day.month) * WEEKDAY[day.weekday()] * noise / days))


def _first_day(doc: dict[str, Any], mark: str, legacy_count: str | None) -> date:
    """The first business day not handled yet: the day after ``doc[mark]``; for a loan fed before 18/10/2026
    (one payout per run, counted in ``legacy_count``) as many days after the disbursement as payouts were made;
    else the disbursement day."""
    start = agent4.parse_date(doc.get("start_date")) or agent4.today()
    done = agent4.parse_date(doc.get(mark))
    if done is not None:
        return max(start, done + timedelta(days=1))
    if legacy_count and int(doc.get(legacy_count) or 0) > 0:
        return start + timedelta(days=int(doc[legacy_count]))
    return start


def _horizon(doc: dict[str, Any], through: date | None) -> date:
    """The last day to handle: ``through`` (simulate-advance: the day about to be ticked, at most the day after
    the clock), else the loan's clock. Never a day in the loan's future."""
    clk = agent4.clock(doc)
    return min(through, clk + timedelta(days=1)) if through is not None else clk


def _due(doc: dict[str, Any], mark: str, now: datetime, through: date | None) -> bool:
    """The autopilot path runs at most every ``PLATFORM_PAYOUT_MINUTES`` per loan; an explicit day always runs."""
    if through is not None:
        return True
    last = doc.get(mark)
    every = timedelta(minutes=max(1, int(settings.platform_payout_minutes)))
    return not (last and now - datetime.fromisoformat(str(last).rstrip("Z")) < every)


def _open_loans(session: Session, loan_ids: list[str] | None) -> list[BuLoan]:
    stmt = select(BuLoan).where(BuLoan.status.in_(agent4.OPEN_STATUSES))
    if loan_ids is not None:
        stmt = stmt.where(BuLoan.id.in_(loan_ids))
    return list(session.scalars(stmt.order_by(BuLoan.created_at)))


def _app_doc(session: Session, loan: BuLoan) -> dict[str, Any]:
    app = session.get(BuApplication, loan.application_id) if loan.application_id else None
    return (app.doc or {}) if app else {}


def settle(session: Session, now: datetime | None = None, *, through: date | None = None,
           loan_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Credit every open loan (or ``loan_ids``) one payout per business day not settled yet, up to its clock
    (or ``through``). Returns one result per day credited."""
    from app.api.webank import credit

    now = now or utcnow()
    out = []
    for loan in _open_loans(session, loan_ids):
        doc = loan.doc or {}
        if not _due(doc, "settled_at", now, through):
            continue
        app_doc = _app_doc(session, loan)
        platform = ((app_doc.get("stores") or [{}])[0].get("platform") or "") or "douyin"
        source = PLATFORM_NAMES.get(platform, platform)
        day, last = _first_day(doc, "settled_through", "settlements"), _horizon(doc, through)
        while day <= last and loan.status in agent4.OPEN_STATUSES:
            result = credit(session, loan, day_amount(loan, day, app_doc), f"{platform}:{loan.id}:{day.isoformat()}",
                            source, on=day)
            doc = dict(loan.doc or {})
            doc["settled_through"] = day.isoformat()
            save_json(loan, "doc", doc)
            session.flush()
            out.append({"loan_id": loan.id, "on": day.isoformat(), **result})
            day += timedelta(days=1)
        if loan.status in agent4.OPEN_STATUSES:
            doc = dict(loan.doc or {})
            doc["settled_at"] = now.isoformat() + "Z"
            save_json(loan, "doc", doc)
    session.flush()
    return out


SPEND_SHARE_MAX = 0.70  # the demo never spends more than 70 % of the month's money in
DEMO_PROFILE = "lan"


def _expense_pool(app_doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Business expenses of the dossier's bank statement (demo profile), oldest first."""
    name = str((((app_doc.get("internal") or {}).get("data") or {}).get("profile")) or DEMO_PROFILE)
    try:
        raw = profiles.load(name)
    except (FileNotFoundError, KeyError, ValueError):
        raw = profiles.load(DEMO_PROFILE)
    pool = []
    for t in (raw.get("bank_statement") or {}).get("outflows") or []:
        to = t.get("to") or {}
        item = {"amount": int(t.get("amount") or 0), "memo": str(t.get("memo") or ""),
                "payee": {"kind": str(to.get("kind") or ""), "name": str(to.get("name") or "")}}
        if item["amount"] > 0 and cashflow.classify({"kind": "other", **item}) is not None:
            pool.append(item)
    return pool


def spend(session: Session, now: datetime | None = None, *, through: date | None = None,
          loan_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """For every business day not handled yet (up to the clock, or ``through``): 0–2 of the dossier's usual
    expenses, booked on that day, the month's spending kept within 70 % of the month's money in."""
    from app.api.webank import debit

    now = now or utcnow()
    out = []
    for loan in _open_loans(session, loan_ids):
        doc = loan.doc or {}
        if not _due(doc, "spent_at", now, through):
            continue
        pool = _expense_pool(_app_doc(session, loan))
        idx = int(doc.get("spend_index") or 0)
        # A loan fed before 18/10/2026 (``spend_runs``) starts at its clock: its earlier runs were all one day.
        legacy = "spend_runs" in doc and not doc.get("spent_through")
        day = agent4.clock(doc) if legacy else _first_day(doc, "spent_through", None)
        last = _horizon(doc, through)
        while day <= last and loan.status in agent4.OPEN_STATUSES:
            count = _hash(f"{loan.id}:spend:{day.isoformat()}") % 3 if pool else 0
            month = day.isoformat()[:7]
            for i in range(count):
                acc = (loan.doc or {}).get("account") or {}
                month_in = sum(int(x.get("amount") or 0) for x in acc.get("inflows") or [] if str(x.get("on"))[:7] == month)
                month_out = sum(int(x.get("amount") or 0) for x in acc.get("transfers") or [] if str(x.get("on"))[:7] == month)
                item = pool[idx % len(pool)]
                if month_out + item["amount"] > SPEND_SHARE_MAX * month_in or item["amount"] > int(acc.get("balance") or 0):
                    break
                result = debit(session, loan, item["amount"], f"spend:{loan.id}:{day.isoformat()}:{i}", item["payee"],
                               item["memo"], source="demo", on=day)
                idx += 1
                out.append({"loan_id": loan.id, "on": day.isoformat(), **result})
            session.refresh(loan)
            doc = dict(loan.doc or {})
            doc["spent_through"], doc["spend_index"] = day.isoformat(), idx
            save_json(loan, "doc", doc)
            session.flush()
            day += timedelta(days=1)
        doc = dict(loan.doc or {})
        doc["spent_at"] = now.isoformat() + "Z"
        save_json(loan, "doc", doc)
    session.flush()
    return out
