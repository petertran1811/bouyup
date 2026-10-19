"""Put the old demo settlement payouts on business days (18/10/2026). Demo only; idempotent.

Before 18/10/2026 the demo feed (app/autopilot/settlement.py) credited "one day of sales" every
PLATFORM_PAYOUT_MINUTES, all booked on the loan's clock, so a loan could hold dozens of payouts on one day
(ids ``"<platform>:<loan_id>:<n>"``) and its spending feed dozens of expenses (``"spend:<loan_id>:<n>:<i>"``).
The statistics place money on its business day, so those show as a wall of money on a single date.

For every loan with such items this script re-dates them, in their order (n, then i), on consecutive days from
the disbursement day (``start_date``), one per day. A loan's days stop at its horizon (``closed_on`` for a closed
loan, its stored ``clock`` otherwise; never a future day): when there are more items than days, they are spread
evenly over the days there are (several on a day, still in order). Only ``on`` changes: amounts, ids, the
balance, ``BuRepayment`` rows and the chain are untouched, so totals stay the same. ``settled_through`` /
``spent_through`` are set to the last day used, so the new feed carries on from the next day without crediting a
day twice. A loan done once is marked (``doc.feed_rebased``) and skipped on the next run.

    cd BackEnd/src && DATABASE_URL=sqlite:////path/to/buoyup.db ../.venv/bin/python scripts/rebase_demo_inflows.py [--dry-run]

Refuses to run unless APP_ENV is dev, demo or test.
"""
from __future__ import annotations

import argparse
import copy
import os
import re
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)  # DATABASE_URL and .env are relative to the backend folder

from sqlalchemy import select  # noqa: E402

from app.platform.config import settings  # noqa: E402
from app.platform.db.session import session_scope  # noqa: E402
from app.platform.db.tables import utcnow  # noqa: E402
from app.platform.tables import BuLoan, save_json  # noqa: E402


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def spread(count: int, start: date, horizon: date) -> list[date]:
    """``count`` days in order: consecutive from ``start``; spread evenly when they would pass ``horizon``."""
    days = max(1, (horizon - start).days + 1)
    if count <= days:
        return [start + timedelta(days=k) for k in range(count)]
    return [start + timedelta(days=(k * days) // count) for k in range(count)]


def rebase_loan(doc: dict[str, Any], loan_id: str) -> dict[str, Any] | None:
    """Re-date the legacy feed items of one loan doc in place; the summary, or None when there is nothing to do."""
    if doc.get("feed_rebased"):
        return None
    start = _day(doc.get("start_date"))
    if start is None:
        return None
    horizon = max(start, _day(doc.get("closed_on")) or _day(doc.get("clock")) or start)
    acc = doc.get("account") or {}
    pay = re.compile(r"^[A-Za-z0-9_-]+:" + re.escape(loan_id) + r":(\d+)$")
    out = re.compile(r"^spend:" + re.escape(loan_id) + r":(\d+):(\d+)$")
    ins = sorted(((int(m.group(1)), i) for i in acc.get("inflows") or [] if (m := pay.match(str(i.get("id") or "")))),
                 key=lambda x: x[0])
    outs = sorted(((int(m.group(1)), int(m.group(2)), t) for t in acc.get("transfers") or []
                   if (m := out.match(str(t.get("id") or "")))), key=lambda x: (x[0], x[1]))
    if not ins and not outs:
        return None
    before = Counter(str(i.get("on")) for _n, i in ins)
    total_in = sum(int(i.get("amount") or 0) for _n, i in ins)
    in_days = spread(len(ins), start, horizon)
    for (_n, item), d in zip(ins, in_days):
        item["on"] = d.isoformat()
    out_days = spread(len(outs), start, horizon)
    for (_n, _i, item), d in zip(outs, out_days):
        item["on"] = d.isoformat()
    if in_days:
        doc["settled_through"] = max(in_days[-1], _day(doc.get("settled_through")) or in_days[-1]).isoformat()
    if out_days or "spend_runs" in doc:
        last = out_days[-1] if out_days else (in_days[-1] if in_days else start)
        doc["spent_through"] = max(last, _day(doc.get("spent_through")) or last).isoformat()
    summary = {"inflows": len(ins), "inflow_total": total_in, "transfers": len(outs),
               "days_before": len(before), "days_after": len(set(in_days)),
               "from": in_days[0].isoformat() if in_days else None, "to": in_days[-1].isoformat() if in_days else None,
               "horizon": horizon.isoformat(), "at": utcnow().isoformat() + "Z"}
    doc["feed_rebased"] = summary
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="in tóm tắt, không ghi")
    args = parser.parse_args(argv)
    if settings.app_env not in ("dev", "demo", "test"):
        raise SystemExit(f"Chỉ chạy ở môi trường demo (APP_ENV hiện là {settings.app_env}).")
    changed = skipped = 0
    with session_scope() as session:
        for loan in session.scalars(select(BuLoan).order_by(BuLoan.created_at)):
            doc = dict(loan.doc or {})
            if doc.get("feed_rebased"):
                skipped += 1
                print(f"{loan.id} [{loan.status}] đã phân bố trước đó: bỏ qua")
                continue
            doc = copy.deepcopy(doc)
            balance = int((doc.get("account") or {}).get("balance") or 0)
            summary = rebase_loan(doc, loan.id)
            if summary is None:
                continue
            assert int((doc.get("account") or {}).get("balance") or 0) == balance
            changed += 1
            total = f"{summary['inflow_total']:,}".replace(",", ".")
            print(f"{loan.id} [{loan.status}] {summary['inflows']} khoản tiền hàng (tổng {total}, không đổi), "
                  f"{summary['transfers']} khoản chi: {summary['days_before']} ngày → {summary['days_after']} ngày "
                  f"({summary['from']} … {summary['to']}, giới hạn {summary['horizon']})")
            if not args.dry_run:
                save_json(loan, "doc", doc)
        if args.dry_run:
            session.rollback()
    print(f"{'(thử, không ghi) ' if args.dry_run else ''}{changed} khoản vay phân bố lại, {skipped} đã làm trước đó.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
