"""Agent 5's reports to the seller, phase D (SELLER_SERVICES_PLAN §6, việc 5–9, 17/10/2026): the monthly report
with expense groups and coverage, the quarterly report without inventing a store trend, the closing report,
the registration reminder for individual sellers only, one hashed row per period, and no money ever moved."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select

from app.agents import agent4b_monitor as agent4
from app.agents import agent5_seller_reports as reports
from app.autopilot import loop as autopilot
from app.platform import capabilities
from app.platform.db.session import session_scope
from app.platform.tables import BuApplication, BuEvent, BuLoan, BuRepayment, BuSellerReport, BuUser, save_json
from tests import lc


def _loan(client, h) -> dict:
    return lc.loan_for(client, h, amount=60_000, tenor_m=3)


def _first_of_next(d: date) -> date:
    return (d.replace(day=1) + timedelta(days=32)).replace(day=1)


def _set_tax(app_id: str, months: dict[str, int], only: bool = False) -> None:
    with session_scope() as s:
        row = s.get(BuApplication, app_id)
        doc = dict(row.doc)
        internal = dict(doc["internal"])
        data = dict(internal["data"])
        revenue = dict(data["revenue"])
        keep = [] if only else [m for m in revenue["monthly_12m"] if m["month"] not in months]
        revenue["monthly_12m"] = keep + [{"month": k, "amount": v} for k, v in months.items()]
        data["revenue"], internal["data"], doc["internal"] = revenue, data, internal
        save_json(row, "doc", doc)


def _rows(user_id: str, kind: str | None = None) -> list[BuSellerReport]:
    with session_scope() as s:
        stmt = select(BuSellerReport).where(BuSellerReport.seller_user_id == user_id)
        if kind:
            stmt = stmt.where(BuSellerReport.kind == kind)
        rows = list(s.scalars(stmt))
        for r in rows:
            s.expunge(r)
        return rows


def _seller_id(loan: dict) -> str:
    with session_scope() as s:
        return s.get(BuLoan, loan["id"]).seller_user_id


def test_month_report_groups_expenses_and_coverage(bu_client, as_seller):
    loan = _loan(bu_client, as_seller)
    start = date.fromisoformat(loan["clock"])
    month = start.strftime("%Y-%m")
    _set_tax(loan["application_id"], {month: 166_700})
    for i, amount in enumerate((10_000, 12_000, 8_000)):
        lc.ok(bu_client.post(f"/v4/loans/{loan['id']}/simulate-inflow", headers=as_seller,
                             json={"amount": amount, "payout_id": f"po-{i}"}))
    for amount, kind in ((12_000, "supplier"), (3_000, "staff")):
        lc.ok(bu_client.post(f"/v4/loans/{loan['id']}/simulate-transfer", headers=as_seller,
                             json={"amount": amount, "kind": kind, "note": "chi tháng này"}))
    assert not _rows(_seller_id(loan), "month")
    lc.advance(bu_client, as_seller, loan, _first_of_next(start).isoformat())
    listed = lc.ok(bu_client.get("/v4/me/reports", headers=as_seller))["items"]
    item = next(i for i in listed if i["kind"] == "month" and i["period"] == month)
    assert item["title"] == f"Báo cáo tháng {int(month[5:])}/{month[:4]}" and item["read_at"] is None
    view = lc.ok(bu_client.get(f"/v4/me/reports/{item['id']}", headers=as_seller))
    data = view["data"]
    groups = {g["key"]: g["amount"] for g in data["expenses"]["groups"]}
    assert groups["goods"] == 12_000 and groups["staff"] == 3_000
    assert groups["platform"] == round(30_000 * 0.05 / 0.95)  # estimated from the money in
    assert data["coverage"]["basis"] == "tax" and data["coverage"]["share"] == round(30_000 / 166_700, 4)
    assert data["sales"] == {"webank_in": 30_000, "tax_revenue": 166_700, "estimate": 166_700, "basis": "tax",
                             "vs_prev": round(166_700 / 188_800 - 1, 4)}
    assert data["cash"]["opening"] == 0 and data["cash"]["loan_in"] == 60_000 and data["cash"]["in"] == 30_000
    assert data["cash"]["out"] == 15_000 and data["cash"]["closing"] == 75_000
    assert "%" in data["notes"][0] and "tờ khai thuế" in data["notes"][0]
    # The optional model rewrite goes through the number filter: "50,000" and "50.000" are both caught.
    allowed = reports._allowed(data)
    assert reports.numbers_ok(data["summary"], allowed)
    assert not reports.numbers_ok("Bạn bán được 50,000 tệ.", allowed)
    assert not reports.numbers_ok("Bạn bán được 50.000 tệ.", allowed)
    assert data["notes"][1] == "Phí sàn ước tính theo biểu phí 5 % của Douyin."
    assert data["summary"].startswith(f"Tháng {int(month[5:])} bạn bán được khoảng 166.700 tệ (−12 % so tháng")
    assert "Chi lớn nhất là hàng hóa và nguyên liệu 12.000 tệ." in data["summary"]
    assert view["chain_tx"] and view["hash"] and lc.ok(bu_client.get(
        f"/v4/me/reports/{item['id']}", headers=as_seller))["read_at"]
    # In the notification centre: scope "report", opens the report page.
    note = next(n for n in lc.ok(bu_client.get("/v4/me/notices", headers=as_seller))["items"]
                if n["scope"] == "report" and n["id"] == item["id"])
    assert note["action"] == {"view": "report", "id": item["id"]} and note["title"].startswith("Báo cáo tháng")
    assert note["read_at"]  # opened above


def test_quarter_report_says_unavailable_without_snapshots(bu_client, as_seller):
    loan = _loan(bu_client, as_seller)
    start = date.fromisoformat(loan["clock"])
    user_id = _seller_id(loan)
    with session_scope() as s:  # no store snapshot was ever taken for this loan
        row = s.get(BuLoan, loan["id"])
        doc = dict(row.doc)
        doc["store_snapshots"] = []
        save_json(row, "doc", doc)
        q = reports.quarter_of(start.strftime("%Y-%m"))
        data = reports.build_quarter(s, user_id, q)
    assert data["store"]["unavailable"] == "Chưa đủ dữ liệu đánh giá và hoàn hàng từ sàn"
    assert "rating" not in data["store"] and "returns" not in data["store"]
    assert any(n.startswith("Chưa đủ dữ liệu đánh giá") for n in data["notes"])
    assert set(data["trend"]["revenue"]) >= {"months"} and len(data["by_month"]) == 3
    assert data["runway_months"] == "∞" or isinstance(data["runway_months"], float)
    # With two monthly snapshots the rating is reported; returns stay "chưa có" (the source has none).
    with session_scope() as s:
        row = s.get(BuLoan, loan["id"])
        doc = dict(row.doc)
        months = reports.quarter_months(q)
        doc["store_snapshots"] = [{"month": months[0], "rating": 4.6, "followers": 1, "returns_rate": None},
                                  {"month": months[1], "rating": 4.4, "followers": 1, "returns_rate": None}]
        save_json(row, "doc", doc)
        s.flush()
        data = reports.build_quarter(s, user_id, q)
    assert data["store"]["rating"] == {"from": 4.6, "to": 4.4, "change": -0.2}
    assert "unavailable" in data["store"]["returns"]


def test_year_report_on_closing(bu_client, as_seller):
    loan = _loan(bu_client, as_seller)
    user_id = _seller_id(loan)
    out = lc.ok(bu_client.post(f"/v4/loans/{loan['id']}/prepay", headers=as_seller, json={"confirm": True}))
    assert out["status"] == "closed"
    assert user_id in autopilot._reports_due  # Agent 4b asked for the closing report
    autopilot.run_reports("closing", [user_id])
    assert user_id not in autopilot._reports_due
    (row,) = _rows(user_id, "closing")
    assert row.period == loan["id"] and row.chain_tx
    data = row.data
    assert data["loan_summary"]["total_interest"] == 0 and data["loan_summary"]["amount"] == 60_000
    assert data["loan_summary"]["late_instalments"] == 0
    ba = data["before_after"]
    assert ba["before"]["revenue"] == 136_000 + 142_000 + 188_800 and ba["after"]["webank_in"] == 0
    assert data["next_time"]["source"] == "offer.blocks.B8" and data["next_time"]["text"]
    assert data["summary"].startswith("Bạn đã tất toán khoản vay 60.000 tệ sau 0 ngày, tổng lãi thật 0 tệ")
    status = autopilot.status()["reports"]
    assert status["last_reason"] == "closing" and status["interval_seconds"] == 3600


def test_registration_notice_for_individual_only(bu_client, as_seller):
    today = agent4.today()
    year = str(today.year)
    months = {f"{year}-{m:02d}": a for m, a in ((1, 30_000), (2, 25_000), (3, 30_000))}
    # A household business (lan): never told to register.
    lan = lc.offered(bu_client, as_seller)
    _set_tax(lan["id"], months, only=True)
    with session_scope() as s:
        user_id = s.get(BuApplication, lan["id"]).seller_user_id
        assert reports.registration_check(s, user_id, today) is None
        assert reports.run_due(s, today) == []
        s.get(BuApplication, lan["id"]).status = "withdrawn"  # make room for a second dossier of the same seller
    # An individual seller with 85.000 this year (≥ 80 % of 100.000): told once.
    app = lc.answer_all(bu_client, as_seller, lc.start(bu_client, as_seller, "personal", borrower_type="individual"))
    assert app["borrower_type"] == "individual"
    _set_tax(app["id"], months, only=True)
    with session_scope() as s:
        made = reports.run_due(s, today)
        assert [r.kind for r in made] == ["registration"]
    with session_scope() as s:
        assert reports.run_due(s, today) == []  # once a year
    item = next(n for n in lc.ok(bu_client.get("/v4/me/notices", headers=as_seller))["items"] if n["scope"] == "report")
    assert item["kind"] == "registration" and item["level"] == "warn" and item["title"] == "Nhắc đăng ký kinh doanh"
    assert item["text"].startswith("Doanh thu năm nay của bạn khoảng 85.000 tệ.")
    assert "Điều 8" in item["text"] and "200.000 tệ thay vì 50.000" in item["text"]
    (row,) = _rows(user_id, "registration")
    cites = row.data["citations"]
    assert cites and all(c["verified"] and c["effective"] for c in cites)
    assert any("年交易额累计不超过10万元" in c["quote"] for c in cites)


def test_reports_idempotent_and_hashed(bu_client, as_seller):
    loan = _loan(bu_client, as_seller)
    start = date.fromisoformat(loan["clock"])
    user_id = _seller_id(loan)
    first = _first_of_next(start)
    with session_scope() as s:  # the loan's clock moves on (as simulate-advance does), then run_due twice
        row = s.get(BuLoan, loan["id"])
        doc = dict(row.doc)
        doc["clock"] = first.isoformat()
        save_json(row, "doc", doc)
    with session_scope() as s:
        made = reports.run_due(s, first)
        assert [r.kind for r in made] == ["month"]
    (one,) = _rows(user_id, "month")
    with session_scope() as s:
        assert reports.run_due(s, first) == []
    (again,) = _rows(user_id, "month")
    assert one.id == again.id and one.hash == again.hash and again.chain_tx and again.chain_tx.startswith("0x")
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(BuEvent).where(BuEvent.kind == "seller_report")) == 1
    # A late webhook changes the facts: the same row is overwritten with a new hash.
    lc.ok(bu_client.post(f"/v4/loans/{loan['id']}/simulate-transfer", headers=as_seller,
                         json={"amount": 1_000, "kind": "marketing"}))
    with session_scope() as s:  # the transfer above is dated on the loan's clock (next month): month unchanged
        assert reports.run_due(s, first) == []
        row = s.get(BuLoan, loan["id"])
        doc = dict(row.doc)
        acc = dict(doc["account"])
        acc["transfers"] = [{**t, "on": start.isoformat()} for t in acc["transfers"]]
        doc["account"] = acc
        save_json(row, "doc", doc)
    with session_scope() as s:
        assert [r.id for r in reports.run_due(s, first)] == [one.id]
    (third,) = _rows(user_id, "month")
    assert third.hash != one.hash
    # Staff see the seller's reports.
    officer = lc.ok(bu_client.get(f"/v4/officer/sellers/{user_id}/reports",
                                  headers=lc_login(bu_client, "officer@buoyup.vn")))
    assert [i["id"] for i in officer["items"]] == [one.id]


def lc_login(client, email: str) -> dict[str, str]:
    from tests.conftest import login

    return login(client, email)


def test_reports_never_move_money(bu_client, as_seller, monkeypatch):
    loan = _loan(bu_client, as_seller)
    start = date.fromisoformat(loan["clock"])
    with session_scope() as s:
        row = s.get(BuLoan, loan["id"])
        doc = dict(row.doc)
        doc["clock"] = (_first_of_next(_first_of_next(start)) + timedelta(days=95)).isoformat()
        save_json(row, "doc", doc)
    called: list[str | None] = []

    def flag(name: str):
        def fn(*a, **kw):
            called.append(name)
            capabilities.require("debit")  # raises under agent5
        return fn

    monkeypatch.setattr(agent4, "_collect", flag("_collect"))
    monkeypatch.setattr(agent4, "_pay_banks", flag("_pay_banks"))
    monkeypatch.setattr(agent4, "prepay", flag("prepay"))
    roles: list[str | None] = []
    real_store = reports.store

    def store(*a, **kw):
        roles.append(capabilities.current())
        return real_store(*a, **kw)

    monkeypatch.setattr(reports, "store", store)
    with session_scope() as s:
        made = reports.run_due(s, start)
    assert made and {r.kind for r in made} >= {"month", "quarter"}
    assert called == [] and set(roles) == {"agent5"}
    assert capabilities.current() is None
    with capabilities.acting("agent5"):  # the role itself refuses money moves
        for cap in ("debit", "payout"):
            try:
                capabilities.require(cap)
            except capabilities.CapabilityDenied:
                pass
            else:
                raise AssertionError(cap)
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(BuRepayment).where(BuRepayment.loan_id == loan["id"])) == 0
        assert s.get(BuUser, _seller_id(loan)) is not None
