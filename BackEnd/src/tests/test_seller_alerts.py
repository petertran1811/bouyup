"""Seller alerts after the loan, phase B (SELLER_SERVICES_PLAN §5 việc 2–4, §6.3, 17/10/2026):
the shortfall forecast before a due date, the debt-service ratio on the estimated revenue, the notice right
after a large spend, the monthly store snapshot. Agent 4b only reads and tells: no money moves."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select

from app.agents import agent4b_monitor as agent4
from app.core import cashflow
from app.platform import capabilities
from app.platform.db.session import session_scope
from app.platform.tables import BuApplication, BuLoan, BuRepayment, save_json
from tests import lc


def _loan(client, h) -> dict:
    return lc.loan_for(client, h, amount=60_000, tenor_m=3)


def _get(client, h, loan_id: str) -> dict:
    return lc.ok(client.get(f"/v4/loans/{loan_id}", headers=h))


def _kind(view: dict, kind: str) -> list[dict]:
    return [n for n in view["notices"] if n["kind"] == kind]


def _spend(client, h, loan_id: str, amount: int, kind: str = "supplier") -> dict:
    return lc.ok(client.post(f"/v4/loans/{loan_id}/simulate-transfer", headers=h,
                             json={"amount": amount, "kind": kind, "note": "nhập vải"}))


def _due(loan: dict, k: int = 1) -> date:
    return date.fromisoformat(loan["schedule"][k - 1]["due_date"])


def test_forecast_shortfall_fires_7_days_before(bu_client, as_seller):
    loan = _loan(bu_client, as_seller)
    payment = loan["schedule"][0]["payment_est"]
    _spend(bu_client, as_seller, loan["id"], 56_000)  # balance 4.000, nothing comes in afterwards
    due = _due(loan)
    view = lc.advance(bu_client, as_seller, loan, (due - timedelta(days=8)).isoformat())
    assert not _kind(view, "shortfall_forecast")
    view = lc.advance(bu_client, as_seller, loan, (due - timedelta(days=7)).isoformat())
    sent = _kind(view, "shortfall_forecast")
    assert len(sent) == 1 and sent[0]["level"] == "warn"
    text = sent[0]["text"]
    assert text.startswith(f"Còn 7 ngày đến kỳ 1 ({due.strftime('%d/%m')}): phải trả {agent4._n(payment)} tệ.")
    assert "Số dư 4.000 tệ" in text and "thiếu khoảng" in text and "trả tối thiểu" in text
    # The reminder of the same day does not repeat "Số dư chưa đủ".
    reminder = [r["text"] for r in view["reminders"] if r["text"].startswith("Còn 7 ngày")]
    assert reminder and "Số dư chưa đủ" not in reminder[0]
    view = lc.advance(bu_client, as_seller, loan, (due - timedelta(days=6)).isoformat())
    assert len(_kind(view, "shortfall_forecast")) == 1
    view = lc.advance(bu_client, as_seller, loan, (due - timedelta(days=3)).isoformat())
    assert len(_kind(view, "shortfall_forecast")) == 2
    # The notification centre links it to the loan, with its title.
    item = next(i for i in lc.ok(bu_client.get("/v4/me/notices", headers=as_seller))["items"]
                if i["kind"] == "shortfall_forecast")
    assert item["title"] == "Có thể thiếu tiền kỳ tới" and item["action"]["view"] == "loan"
    assert item["action"]["secondary"]["open"] == "minimum"  # shown, never chosen for the seller
    with session_scope() as s:
        doc = s.get(BuLoan, loan["id"]).doc
        assert "shortfall_forecast:1:7" in doc["sent_alerts"] and "shortfall_forecast:1:3" in doc["sent_alerts"]


def test_no_forecast_when_balance_and_inflows_cover(bu_client, as_seller):
    loan = _loan(bu_client, as_seller)  # 60.000 on the account covers the first payment
    view = lc.advance(bu_client, as_seller, loan, (_due(loan) - timedelta(days=3)).isoformat())
    assert not _kind(view, "shortfall_forecast")


def _set_tax(app_id: str, months: dict[str, int]) -> None:
    with session_scope() as s:
        row = s.get(BuApplication, app_id)
        doc = dict(row.doc)
        internal = dict(doc["internal"])
        data = dict(internal["data"])
        revenue = dict(data["revenue"])
        revenue["monthly_12m"] = [m for m in revenue["monthly_12m"] if m["month"] not in months] + [
            {"month": k, "amount": v} for k, v in months.items()]
        data["revenue"], internal["data"], doc["internal"] = revenue, data, internal
        save_json(row, "doc", doc)


def _first_of_next(d: date) -> date:
    return (d.replace(day=1) + timedelta(days=32)).replace(day=1)


def test_dsr_notice_uses_tax_base(bu_client, as_seller, as_officer):
    loan = _loan(bu_client, as_seller)
    due1, due2 = _due(loan, 1), _due(loan, 2)
    m1, m2 = due1.strftime("%Y-%m"), due2.strftime("%Y-%m")
    # Month 1: 7.437 reached WeBank, 166.700 on the tax filings → ~12 %: no alert (WeBank alone would say 275 %).
    # Month 2: tax 60.000 → ~34 % > 20 %: alert.
    _set_tax(loan["application_id"], {m1: 166_700, m2: 60_000})
    lc.advance(bu_client, as_seller, loan, due1.replace(day=5).isoformat() if due1.day > 5 else due1.isoformat())
    lc.ok(bu_client.post(f"/v4/loans/{loan['id']}/simulate-inflow", headers=as_seller, json={"amount": 7_437}))
    view = lc.advance(bu_client, as_seller, loan, _first_of_next(due1).isoformat())
    assert not _kind(view, "dsr_high")
    with session_scope() as s:
        dsr = s.get(BuLoan, loan["id"]).doc["dsr"]
    assert dsr["month"] == m1 and dsr["revenue_base"] == 166_700 and not dsr["high"]
    assert dsr["coverage"]["basis"] == "tax" and dsr["coverage"]["share"] == round(7_437 / 166_700, 4)
    view = lc.advance(bu_client, as_seller, loan, _first_of_next(due2).isoformat())
    sent = _kind(view, "dsr_high")
    assert len(sent) == 1 and sent[0]["level"] == "warn"
    text = sent[0]["text"]
    assert "%" in text and "Trên 20 % là mức BuoyUp coi là nặng" in text and "60.000 tệ" in text
    assert "% doanh thu này" in text  # how much of the revenue BuoyUp could count
    staff = _get(bu_client, as_officer, loan["id"])
    assert any(s["key"] == "dsr_high" and s["weight"] == 0.0 for s in staff["early_warning"]["signals"])
    # Once a month: a later round of the same month does not repeat it.
    view = lc.advance(bu_client, as_seller, loan, (_first_of_next(due2) + timedelta(days=2)).isoformat())
    assert len(_kind(view, "dsr_high")) == 1


def test_coverage_basis():
    assert cashflow.coverage(7_437, 166_700, 150_000) == {
        "share": 0.0446, "basis": "tax", "webank_in": 7_437, "tax_revenue": 166_700, "revenue": 166_700,
        "estimate": 166_700}
    assert cashflow.coverage(200_000, 166_700)["share"] == 1.0
    assert cashflow.coverage(50_000, None, 100_000)["basis"] == "forecast"
    none = cashflow.coverage(0, None, 0)
    assert none["basis"] == "none" and none["share"] is None


def test_spend_below_due_immediate(bu_client, as_seller):
    loan = _loan(bu_client, as_seller)
    payment = loan["schedule"][0]["payment_est"]
    out = _spend(bu_client, as_seller, loan["id"], 30_000)  # 30.000 left ≥ the payment: nothing to say
    assert not _kind(out, "spend_below_due")
    out = _spend(bu_client, as_seller, loan["id"], 26_000)
    sent = _kind(out, "spend_below_due")
    assert len(sent) == 1
    assert sent[0]["text"] == (f"Bạn vừa chi 26.000 tệ (Trả nhà cung cấp). Số dư còn 4.000 tệ, thấp hơn "
                               f"{agent4._n(payment)} tệ phải trả ngày {_due(loan).strftime('%d/%m')}. "
                               "Nhớ để tiền hàng về WeBank trước ngày đó.")
    assert len(_kind(_get(bu_client, as_seller, loan["id"]), "spend_below_due")) == 1
    # Once per period: another large spend below the payment in the same period says nothing new.
    lc.ok(bu_client.post(f"/v4/loans/{loan['id']}/simulate-inflow", headers=as_seller, json={"amount": 10_000}))
    _spend(bu_client, as_seller, loan["id"], 8_000)
    assert len(_kind(_get(bu_client, as_seller, loan["id"]), "spend_below_due")) == 1


def test_store_snapshot_monthly(bu_client, as_seller):
    loan = _loan(bu_client, as_seller)
    start = date.fromisoformat(loan["clock"])
    lc.advance(bu_client, as_seller, loan, (start + timedelta(days=1)).isoformat())
    with session_scope() as s:
        assert not s.get(BuLoan, loan["id"]).doc.get("store_snapshots")
    first = _first_of_next(start)
    lc.advance(bu_client, as_seller, loan, (first + timedelta(days=3)).isoformat())
    with session_scope() as s:
        snaps = s.get(BuLoan, loan["id"]).doc["store_snapshots"]
    assert len(snaps) == 1
    assert snaps[0]["month"] == first.strftime("%Y-%m") and snaps[0]["rating"] == 4.6
    assert snaps[0]["returns_rate"] is None and "followers" in snaps[0]


def test_alerts_never_move_money(bu_client, as_seller, monkeypatch):
    loan = _loan(bu_client, as_seller)
    _spend(bu_client, as_seller, loan["id"], 60_000)  # empty account: nothing can be collected
    roles: list[str | None] = []
    real_collect, real_pay = agent4._collect, agent4._pay_banks

    def collect(*a, **kw):
        roles.append(capabilities.current())
        return real_collect(*a, **kw)

    def pay(*a, **kw):
        roles.append(capabilities.current())
        return real_pay(*a, **kw)

    monkeypatch.setattr(agent4, "_collect", collect)
    monkeypatch.setattr(agent4, "_pay_banks", pay)
    start = date.fromisoformat(loan["clock"])
    view = lc.advance(bu_client, as_seller, loan, (start + timedelta(days=40)).isoformat())
    assert _kind(view, "shortfall_forecast") and _kind(view, "spend_below_due")
    assert roles and set(roles) == {"standing_order"}  # only the standing order in service(), never Agent 4b
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(BuRepayment).where(BuRepayment.loan_id == loan["id"])) == 0


def test_minimum_choice_drives_reminder_forecast_and_next_due(bu_client, as_seller):
    """Phase E (lỗi 2): once the seller chose "chỉ trả tối thiểu" for period k, the next-due figure, the
    reminder and the shortfall forecast all quote the minimum, labelled, never the full instalment."""
    loan = _loan(bu_client, as_seller)
    full = loan["schedule"][0]["payment_est"]
    url = f"/v4/loans/{loan['id']}"
    minimum = loan["minimum"]["quote"]["payment"]
    assert minimum < full
    lc.ok(bu_client.post(url + "/minimum", headers=as_seller, json={"confirm": True, "method": "otp"}))
    view = _get(bu_client, as_seller, loan["id"])
    assert view["next_due"]["minimum_payment"] == minimum and view["next_due"]["payment_est"] == full
    bank = lc.ok(bu_client.get("/v4/me/bank", headers=as_seller))
    assert bank["loans"][0]["next_due"] == {"date": loan["schedule"][0]["due_date"], "amount": minimum, "minimum": True}
    _spend(bu_client, as_seller, loan["id"], 59_000)  # balance 1.000 < the minimum
    view = lc.advance(bu_client, as_seller, loan, (_due(loan) - timedelta(days=7)).isoformat())
    reminder = next(r["text"] for r in view["reminders"] if r["text"].startswith("Còn 7 ngày"))
    assert f"khoảng {agent4._n(minimum)} (trả tối thiểu)." in reminder and agent4._n(full) not in reminder
    sent = _kind(view, "shortfall_forecast")
    assert len(sent) == 1 and f"phải trả {agent4._n(minimum)} tệ (trả tối thiểu)." in sent[0]["text"]
    assert agent4._n(full) not in sent[0]["text"]
