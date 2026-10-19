"""The settlement feed by business day and the statistics on one time frame (18/10/2026).

Owner's review: the four charts did not line up, the balance chart ran on wall-clock minutes ("19:00"), the
sales money did not move the balance day by day. Now: one payout per business day (``on`` = that day,
id ``<platform>:<loan>:<YYYY-MM-DD>``), simulate-advance settles each day before its tick, and /v4/me/stats
puts every chart on the same 12 months with an end-of-day balance per day of the month shown.
"""

from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.platform.config import settings
from app.platform.db.session import session_scope
from app.platform.db.tables import utcnow
from app.platform.tables import BuLoan, BuRepayment, save_json
from tests import lc


def _doc(loan_id: str) -> dict:
    with session_scope() as s:
        return dict(s.get(BuLoan, loan_id).doc)


def _set(loan_id: str, **fields) -> None:
    with session_scope() as s:
        row = s.get(BuLoan, loan_id)
        save_json(row, "doc", {**row.doc, **fields})


def _days(start: date, n: int) -> list[str]:
    return [(start + timedelta(days=k)).isoformat() for k in range(n)]


@pytest.mark.seed_loan
def test_one_payout_per_business_day_caught_up_to_the_clock_never_beyond(bu_client, as_seller):
    from app.api.webank import credit
    from app.autopilot import settlement

    loan = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    start = date.fromisoformat(loan["start_date"])
    with session_scope() as s:
        first = settlement.settle(s)
        again = settlement.settle(s, utcnow() + timedelta(hours=1))  # same day: nothing more
    assert [r["on"] for r in first] == [start.isoformat()] and again == []
    _set(loan["id"], clock=(start + timedelta(days=3)).isoformat())  # the loan's clock moved three days
    with session_scope() as s:
        caught = settlement.settle(s, utcnow() + timedelta(hours=2))
        none = settlement.settle(s, utcnow() + timedelta(hours=3))
    assert [r["on"] for r in caught] == _days(start + timedelta(days=1), 3) and none == []
    inflows = _doc(loan["id"])["account"]["inflows"]
    assert [i["on"] for i in inflows] == _days(start, 4)  # one a day, nothing after the clock
    assert [i["id"] for i in inflows] == [f"douyin:{loan['id']}:{d}" for d in _days(start, 4)]
    with session_scope() as s:  # the same payout id again: never credited twice
        row = s.get(BuLoan, loan["id"])
        balance = row.doc["account"]["balance"]
        assert credit(s, row, 999, inflows[0]["id"], "Douyin")["credited"] is False
        assert row.doc["account"]["balance"] == balance
        # deterministic in (loan, day)
        assert settlement.day_amount(row, start, settlement._app_doc(s, row)) == inflows[0]["amount"]


def test_day_amount_follows_the_month_the_week_and_the_coverage():
    from app.autopilot import settlement

    app_doc = {"internal": {"data": {"inflows": {"to_declared_accounts_vs_tax_sales": 0.8}}}}
    loan = SimpleNamespace(id="loan_x", doc={"forecast_monthly": 300_000})
    assert settlement.webank_share(app_doc) == (0.8, "statement")
    hist = {"verification": {"derived": {"history": {"webank_share_of_tax": 0.6}}}, **app_doc}
    assert settlement.webank_share(hist) == (0.6, "history")
    assert settlement.webank_share({})[1] == "fee"
    month = [date(2026, 3, d) for d in range(1, 32)]
    total = sum(settlement.day_amount(loan, d, app_doc) for d in month)
    assert 0.93 * 300_000 * 0.8 <= total <= 1.07 * 300_000 * 0.8  # a month ≈ forecast × WeBank share
    days = [date(2026, 1, 5) + timedelta(days=k) for k in range(26 * 7)]  # half a year of Mondays … Sundays
    by = {w: [settlement.day_amount(loan, d, app_doc) for d in days if d.weekday() == w] for w in range(7)}
    avg = {w: sum(v) / len(v) for w, v in by.items()}
    assert avg[5] > avg[4] > avg[0] and avg[6] > avg[1]  # weekend above the week
    tax = {"internal": {"data": {"revenue": {"monthly_12m": [{"month": f"2025-{m:02d}", "amount": 100 if m != 11 else 300}
                                                             for m in range(1, 13)]}}}}
    assert 1.0 < settlement.season(tax, 11) <= 1.25 and 0.85 <= settlement.season(tax, 3) < 1.0


@pytest.mark.seed_loan
def test_simulate_advance_settles_each_day_before_the_tick(bu_client, as_seller, monkeypatch):
    monkeypatch.setattr(settings, "platform_payout_feed", True)
    loan = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    start = date.fromisoformat(loan["clock"])
    to = start + timedelta(days=50)
    view = lc.advance(bu_client, as_seller, loan, to.isoformat())
    doc = _doc(loan["id"])
    acc = doc["account"]
    assert [i["on"] for i in acc["inflows"]] == _days(start, 51)  # every day once, up to the new clock
    # the demo spending: 0–2 a day, on the day, within 70 % of the month's money in
    spent = [t for t in acc["transfers"] if t["id"].startswith("spend:")]
    assert spent and all(start.isoformat() <= t["on"] <= to.isoformat() for t in spent)
    assert max(sum(1 for t in spent if t["on"] == d) for d in _days(start, 51)) <= 2
    for m in {d[:7] for d in _days(start, 51)}:
        assert sum(t["amount"] for t in spent if t["on"][:7] == m) <= 0.70 * sum(
            i["amount"] for i in acc["inflows"] if i["on"][:7] == m)
    # the first instalment was collected on its due day, from the money of the days before
    due = view["schedule"][0]["due_date"]
    assert view["schedule"][0]["status"] == "paid"
    assert any((r["detail"] or {}).get("as_of") == due for r in view["repayments"])

    stats = lc.ok(bu_client.get("/v4/me/stats", headers=as_seller))
    bank = lc.ok(bu_client.get("/v4/me/bank", headers=as_seller))
    bd = stats["balance_daily"]
    assert bd["month"] == to.isoformat()[:7] and len(bd["days"]) == to.day and bd["days"][-1]["date"] == to.isoformat()
    assert stats["kpi"]["balance"] == {"on": to.isoformat(), "amount": bank["account"]["balance"]}
    assert bd["days"][-1]["balance"] == bank["account"]["balance"]
    # the balance moves day by day (money in every day)
    shown = lc.ok(bu_client.get(f"/v4/me/stats?month={due[:7]}", headers=as_seller))["balance_daily"]
    values = [d["balance"] for d in shown["days"] if d["balance"] is not None]
    assert len(set(values)) >= len(values) - 1
    day = next(d for d in shown["days"] if d["date"] == due)
    assert day["repay"] > 0 and day["in"] > 0 and any(x["date"] == due for x in shown["dues"])
    prev = next(d for d in shown["days"] if d["date"] == (date.fromisoformat(due) - timedelta(days=1)).isoformat())
    assert day["balance"] == prev["balance"] + day["in"] - day["out"] - day["repay"]


@pytest.mark.seed_loan
def test_stats_share_one_twelve_month_frame(bu_client, as_seller, monkeypatch):
    monkeypatch.setattr(settings, "platform_payout_feed", True)
    loan = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    start = date.fromisoformat(loan["clock"])
    to = start + timedelta(days=40)
    lc.advance(bu_client, as_seller, loan, to.isoformat())
    s = lc.ok(bu_client.get("/v4/me/stats", headers=as_seller))
    months = [r["month"] for r in s["revenue_12m"]]
    assert len(months) == 12 and months[-1] == to.isoformat()[:7] and len(set(months)) == 12
    for a, b in zip(months, months[1:]):  # consecutive months
        assert (date.fromisoformat(a + "-01") + timedelta(days=32)).isoformat()[:7] == b
    assert [w["month"] for w in s["webank_by_month"]] == months
    assert s["window"] == {"from": months[0], "to": months[-1], "today": to.isoformat()}
    inflows = _doc(loan["id"])["account"]["inflows"]
    for r, w in zip(s["revenue_12m"], s["webank_by_month"]):
        money_in = sum(i["amount"] for i in inflows if i["on"][:7] == r["month"])
        assert w["in"] == money_in
        if r["month"] >= start.isoformat()[:7]:
            assert r["webank_in"] == money_in and r["estimate"] >= money_in and r["basis"] in ("tax", "forecast")
        else:
            assert r["webank_in"] is None and (r["estimate"] is None or r["basis"] == "tax")
        assert r["amount"] == r["estimate"]
    assert s["webank_by_month"][months.index(start.isoformat()[:7])]["loan"] == 60_000
    k = s["kpi"]
    assert k["webank_in"] == {"month": months[-1], "amount": s["webank_by_month"][-1]["in"]}
    assert k["revenue"]["amount"] == next(r["estimate"] for r in reversed(s["revenue_12m"]) if r["estimate"])
    total = sum(r["estimate"] or 0 for r in s["revenue_12m"])
    assert s["goods_period"]["total"] == total and abs(sum(g["revenue_est"] for g in s["goods"]) - total) <= 0.01 * total
    # month switch: the disbursement month (days before the loan: no balance), an unknown month, a bad one
    assert s["months_available"][0] == start.isoformat()[:7] and s["months_available"][-1] == months[-1]
    first = lc.ok(bu_client.get(f"/v4/me/stats?month={start.isoformat()[:7]}", headers=as_seller))["balance_daily"]
    assert first["month"] == start.isoformat()[:7] and first["prev"] is None
    assert all(d["balance"] is None for d in first["days"] if d["date"] < start.isoformat())
    assert next(d for d in first["days"] if d["date"] == start.isoformat())["balance"] > 0
    if start.month != to.month:
        assert len(first["days"]) == first["days_in_month"] and first["next"]
    other = lc.ok(bu_client.get("/v4/me/stats?month=1999-01", headers=as_seller))["balance_daily"]
    assert other["month"] == months[-1] and other["next"] is None
    assert bu_client.get("/v4/me/stats?month=2026-13", headers=as_seller).status_code == 400  # VALIDATION_ERROR


def _rebase_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "rebase_demo_inflows.py"
    spec = importlib.util.spec_from_file_location("rebase_demo_inflows", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.seed_loan
def test_rebase_script_spreads_the_old_feed_over_days(bu_client, as_seller, capsys):
    from app.autopilot import settlement

    loan = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    start = date.fromisoformat(loan["start_date"])
    lid = loan["id"]
    # The old feed: five payouts and three expenses, all booked on the disbursement day; the clock 9 days on.
    with session_scope() as s:
        row = s.get(BuLoan, lid)
        doc = dict(row.doc)
        acc = dict(doc["account"])
        acc["inflows"] = [{"id": f"douyin:{lid}:{n}", "on": start.isoformat(), "amount": 1000 * n, "source": "Douyin",
                           "at": "2026-10-17T04:00:00Z"} for n in range(1, 6)]
        acc["transfers"] = [{"id": f"spend:{lid}:{n}:0", "on": start.isoformat(), "amount": 100, "kind": "other",
                             "memo": "Lương cộng tác viên"} for n in (1, 2, 4)]
        acc["balance"] = int(acc["balance"]) + 15_000 - 300
        doc.update(account=acc, settlements=5, spend_runs=4, clock=(start + timedelta(days=9)).isoformat())
        save_json(row, "doc", doc)
        reps = s.query(BuRepayment).filter(BuRepayment.loan_id == lid).count()
    mod = _rebase_module()
    assert mod.main([]) == 0
    after = _doc(lid)
    assert [i["on"] for i in after["account"]["inflows"]] == _days(start, 5)
    assert [t["on"] for t in after["account"]["transfers"]] == _days(start, 3)
    assert sum(i["amount"] for i in after["account"]["inflows"]) == 15_000
    assert after["account"]["balance"] == acc["balance"] and after["settled_through"] == _days(start, 5)[-1]
    assert mod.main([]) == 0 and _doc(lid)["account"] == after["account"]  # idempotent
    assert "đã phân bố trước đó" in capsys.readouterr().out
    with session_scope() as s:
        assert s.query(BuRepayment).filter(BuRepayment.loan_id == lid).count() == reps
        caught = settlement.settle(s)  # the new feed carries on after the last rebased day, up to the clock
    assert [r["on"] for r in caught] == _days(start + timedelta(days=5), 5)
    # more old payouts than days: spread over the days there are, never past the clock
    assert mod.spread(5, start, start + timedelta(days=1)) == [start, start, start, start + timedelta(days=1),
                                                                 start + timedelta(days=1)]


@pytest.mark.seed_loan
def test_balance_follows_the_account_of_the_current_loan(bu_client, as_seller, monkeypatch):
    """A settled loan keeps its leftover in its own account; from the next loan's disbursement the balance
    shown is the new account, the one "Ngân hàng của tôi" shows (no jump from summing old leftovers)."""
    monkeypatch.setattr(settings, "platform_payout_feed", True)
    first = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    start = date.fromisoformat(first["clock"])
    lc.advance(bu_client, as_seller, first, (start + timedelta(days=20)).isoformat())
    lc.ok(bu_client.post(f"/v4/loans/{first['id']}/prepay", headers=as_seller, json={"confirm": True}))
    assert lc.ok(bu_client.get(f"/v4/loans/{first['id']}", headers=as_seller))["status"] == "closed"
    leftover = _doc(first["id"])["account"]["balance"]
    assert leftover > 0
    second = lc.loan_for(bu_client, as_seller, amount=30_000, tenor_m=3)
    s = lc.ok(bu_client.get("/v4/me/stats", headers=as_seller))
    bank = lc.ok(bu_client.get("/v4/me/bank", headers=as_seller))
    assert bank["loans"][0]["id"] == second["id"]
    assert s["kpi"]["balance"]["amount"] == bank["account"]["balance"] == s["balance_daily"]["days"][-1]["balance"]
