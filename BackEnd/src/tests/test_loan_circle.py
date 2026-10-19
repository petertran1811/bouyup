"""Loan circle (docs/BuoyUp loan circle .docx, team decisions 14/10/2026), Stages 1–10 over HTTP."""

from __future__ import annotations

from datetime import date, timedelta

from app.data_sources import sources
from app.platform.db.session import session_scope
from app.platform.tables import BuApplication, BuBank, BuChainEntry, save_json
from tests import lc
from tests.conftest import login


def _kinds(app_id: str) -> list[str]:
    from sqlalchemy import select

    with session_scope() as s:
        return [e.kind for e in s.scalars(select(BuChainEntry).where(BuChainEntry.case_id == app_id)
                                          .order_by(BuChainEntry.seq))]


# --- Stage 1–2 -------------------------------------------------------------------------------

def test_consent_needs_all_three_boxes(bu_client, as_seller):
    c, h = bu_client, as_seller
    app = lc.ok(c.post("/v4/applications", headers=h, json={"store_urls": [sources.demo_url("lan")]}))
    lc.ok(c.post(f"/v4/applications/{app['id']}/identity", headers=h, json={"cccd": True, "face": True}))
    r = c.post(f"/v4/applications/{app['id']}/consent", headers=h, json={"scopes": lc.BOXES[:2]})
    assert r.status_code == 400 and r.json()["error"]["details"]["missing"] == [lc.BOXES[2]]
    app = lc.ok(c.post(f"/v4/applications/{app['id']}/consent", headers=h, json={"scopes": lc.BOXES, "method": "otp"}))
    assert app["status"] == "consented" and app["consent"]["sign_method"] == "otp"
    assert {s["key"] for s in app["consent"]["scopes"]} == set(lc.BOXES)


def test_borrower_type_must_match_registry(bu_client, as_seller):
    app = lc.ok(bu_client.post("/v4/applications", headers=as_seller, json={
        "borrower_type": "company", "store_urls": [sources.demo_url("lan")]}))
    assert app["status"] == "rejected"


def test_lan_limit_and_parallel_banks(bu_client, as_seller):
    app = lc.offered(bu_client, as_seller)
    offer = app["offer"]
    assert offer["limit"] == 200_000 and offer["binding_cap"] == "type_cap"  # hộ kinh doanh ≤ 200.000
    assert offer["tenors"] == [3, 6, 12] and offer["rate"] == 0.10 and offer["expires_at"]
    syn = app["syndicate"]
    assert syn["status"] == "approved" and not syn["reduced"]
    assert [(s["bank"], s["pct"]) for s in syn["split"]] == [("WEBANK", 0.4), ("CMB", 0.3), ("ICBC", 0.3)]
    assert "rounds" not in syn  # the borrower sees the result, not each bank's answer
    assert app["next_action"]["key"] == "select"
    assert {"gate_decision", "syndicate"} <= set(_kinds(app["id"]))


def test_electronics_single_partner_30_70(bu_client, as_seller):
    app = lc.offered(bu_client, as_seller, "electronics")
    split = [s["bank"] for s in app["syndicate"]["split"]]
    # CMB and CCB do not lend to electronics; ICBC does, and Bank of China when it answers in time.
    assert split[0] == "WEBANK" and "ICBC" in split and not {"CMB", "CCB"} & set(split)


def test_nobank_retries_then_rejects(bu_client, as_seller, as_officer):
    app = lc.answer_all(bu_client, as_seller, lc.start(bu_client, as_seller, "nobank"))
    assert app["status"] == "rejected" and app["decision"]["by"] == "orchestrator"
    full = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    rounds = full["syndicate"]["rounds"]
    assert len(rounds) == 3 and rounds[1]["amount"] < rounds[0]["amount"] and not any(r["agreed"] for r in rounds)
    boc = next(x for x in rounds[0]["responses"] if x["bank"] == "BOC")
    assert boc["decision"] in ("timeout", "decline")  # grade D: declined, or late (after 30 s counts as a decline)
    # Grade D is under WeBank's own floor too, so it does not lend alone either.
    assert "solo" not in full["syndicate"] and full["syndicate"]["solo_blocked"]["reason"]


def test_smaller_limit_is_sent_to_banks(bu_client, as_seller):
    app = lc.offered(bu_client, as_seller, "noevid")
    assert app["decision"]["option_id"] == "step70" and app["offer"]["limit"] == 140_000
    assert app["decision"]["reason"]["fix"]


def test_company_officer_approval_then_banks(bu_client, as_seller, as_officer):
    app = lc.answer_all(bu_client, as_seller, lc.start(bu_client, as_seller, "company"))
    assert app["status"] == "escalated"
    app = lc.ok(bu_client.post(f"/v4/officer/applications/{app['id']}/decision", headers=as_officer,
                               json={"decision": "approve", "option_id": "full", "note": "Đã xác minh chủ sở hữu"}))
    assert app["status"] == "offered" and app["offer"]["tenors"] == [3, 6, 12, 24, 36]
    app = lc.select(bu_client, as_seller, app, tenor_m=24)
    ct = lc.contract(bu_client, as_seller, app)
    assert ct["needs"]["guarantee"] is True
    r = lc.sign(bu_client, as_seller, app, guarantee=False)
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "guarantee"


def test_statement_mismatch_goes_to_officer(bu_client, as_seller):
    months = sources.SCENARIOS["lan"][3]["revenue"]["monthly_12m"][-3:]
    st = [{"month": m["month"], "revenue": m["amount"] * 2, "cost": 0} for m in months]
    app = lc.start(bu_client, as_seller, "lan", statements=st)
    assert app["status"] == "escalated"
    assert any(f["code"] == "RISK_STATEMENT_MISMATCH" for f in app["verification"]["flags"])


# --- Stage 3–5 ----------------------------------------------------------------------------------

def test_choice_validation_and_quote(bu_client, as_seller):
    c, h = bu_client, as_seller
    app = lc.offered(c, h)
    url = f"/v4/applications/{app['id']}/select"
    for body, field in (({"amount": 200_100, "tenor_m": 12}, "amount"), ({"amount": 50_000, "tenor_m": 24}, "tenor_m"),
                        ({"amount": 50_000, "tenor_m": 6, "due_day": 29}, "due_day")):
        r = c.post(url, headers=h, json=body)
        assert r.status_code == 400 and r.json()["error"]["details"]["field"] == field
    q = lc.ok(c.post(f"/v4/applications/{app['id']}/quote", headers=h,
                     json={"amount": 60_000, "tenor_m": 6, "method": "revenue", "due_day": 5}))
    assert q["fees"] == 0 and q["method"] == "revenue" and 0 < q["revenue_rate"] <= app["offer"]["blocks"]["B5"]["sweep_usable"]
    assert len(q["schedule"]) <= 6 and sum(r["principal"] for r in q["schedule"]) == 60_000


def test_contract_reading_time_and_signing(bu_client, as_seller, as_officer):
    c, h = bu_client, as_seller
    app = lc.select(c, h, lc.offered(c, h), amount=150_000, tenor_m=6)
    assert app["status"] == "selected"
    ct = lc.contract(c, h, app)
    assert ct["fees"] == 0 and ct["penalty_rate"] == 0.15 and ct["read_seconds"] == 20
    assert ct["payee"] == {"kind": "split", "to_account": 100_000, "to_supplier": 50_000,
                           "supplier": app["plan"]["supplier"]}
    assert ct["complaint_channel"] and len(ct["banks"]) == 3 and sum(b["amount"] for b in ct["banks"]) == 150_000
    r = c.post(f"/v4/applications/{app['id']}/sign", headers=h, json=lc.SIGN)
    assert r.status_code == 400 and r.json()["error"]["code"] == "READ_TIME"
    r = lc.sign(c, h, app, supplier_account=None)
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "supplier_account"
    with session_scope() as s:
        before = {b.code: b.limit_used for b in s.query(BuBank)}
    app = lc.ok(lc.sign(c, h, app))
    assert app["status"] == "disbursed" and app["contract"]["sign_method"] == "face"
    assert {"contract_signed", "escrow_funded", "disbursement"} <= set(_kinds(app["id"]))
    with session_scope() as s:
        after = {b.code: b.limit_used for b in s.query(BuBank)}
    assert after["WEBANK"] - before["WEBANK"] == 60_000 and after["CMB"] - before["CMB"] == 45_000
    loan = lc.ok(c.get(f"/v4/loans/{app['loan_id']}", headers=h))
    assert loan["account"]["balance"] == 100_000 and loan["payee"]["to_supplier"] == 50_000
    assert [s["amount"] for s in loan["shares"]] == [60_000, 45_000, 45_000]
    assert len(loan["schedule"]) == 6 and loan["principal_outstanding"] == 150_000
    flow = lc.ok(c.get(f"/v4/applications/{app['id']}/flow", headers=as_officer))
    assert flow["matches"] is True and flow["b12"]["legs"]


def test_one_loan_at_a_time(bu_client, as_seller):
    lc.loan_for(bu_client, as_seller)
    app = lc.answer_all(bu_client, as_seller, lc.start(bu_client, as_seller))
    assert app["status"] == "rejected" and "một khoản vay" in app["decision"]["reason"]["law"]


def test_limit_expires_after_7_days(bu_client, as_seller):
    app = lc.offered(bu_client, as_seller)
    with session_scope() as s:
        row = s.get(BuApplication, app["id"])
        doc = dict(row.doc)
        doc["offer"] = {**doc["offer"], "expires_at": "2020-01-01T00:00:00Z"}
        save_json(row, "doc", doc)
    r = bu_client.post(f"/v4/applications/{app['id']}/select", headers=as_seller, json={"amount": 50_000, "tenor_m": 6})
    assert r.status_code == 400 and r.json()["error"]["code"] == "LIMIT_EXPIRED"
    assert bu_client.get(f"/v4/applications/{app['id']}", headers=as_seller).json()["status"] == "expired"


# --- Stage 6–9 ----------------------------------------------------------------------------------

def test_instalment_due_dates_minimum_and_prepay(bu_client, as_seller):
    c, h = bu_client, as_seller
    loan = lc.loan_for(c, h, amount=60_000, tenor_m=6, due_day=10)
    assert loan["account"]["balance"] == 60_000 and loan["method"] == "installment"
    first = loan["schedule"][0]
    loan = lc.ok(c.post(f"/v4/loans/{loan['id']}/minimum", headers=h, json={"confirm": True}))
    q = loan["schedule"][0]
    assert q["choice"] == "minimum"
    loan = lc.advance(c, h, loan, first["due_date"])
    row = loan["schedule"][0]
    days = (date.fromisoformat(first["due_date"]) - date.fromisoformat(loan["start_date"])).days
    assert row["status"] == "minimum" and row["principal_due"] == 3_000  # 30 % of 10.000
    assert row["interest"] == round(60_000 * 0.10 * days / 365)
    assert loan["principal_outstanding"] == 57_000
    # Second minimum in a row is allowed, a third is not.
    loan = lc.ok(c.post(f"/v4/loans/{loan['id']}/minimum", headers=h, json={"confirm": True}))
    loan = lc.advance(c, h, loan, loan["schedule"][1]["due_date"])
    assert loan["minimum"]["allowed"] is False and "2 kỳ" in loan["minimum"]["why"]
    pq = loan["prepay_quote"]
    assert pq["fee"] == 0 and pq["interest"] == 0  # interest charged to the due date just processed
    loan = lc.ok(c.post(f"/v4/loans/{loan['id']}/simulate-inflow", headers=h, json={"amount": 60_000}))
    loan = lc.ok(c.post(f"/v4/loans/{loan['id']}/prepay", headers=h, json={"confirm": True}))
    assert loan["status"] == "closed" and loan["principal_outstanding"] == 0
    assert loan["bureau"][-1]["kind"] == "closed" and loan["receiving_account"]["locked"] is False
    assert sum(s["repaid"] for s in loan["shares"]) == loan["repaid"]
    loan = lc.ok(c.put(f"/v4/loans/{loan['id']}/receiving-account", headers=h, json={"bank": "CMB", "number": "1234567"}))
    assert loan["receiving_account"]["bank"] == "CMB"
    with session_scope() as s:
        assert s.get(BuBank, "CMB").limit_used == 0  # limits released at closing


def test_overdue_grace_penalty_and_bureau(bu_client, as_seller, as_officer):
    c, h = bu_client, as_seller
    loan = lc.loan_for(c, h, amount=60_000, tenor_m=6, due_day=10)
    r = c.put(f"/v4/loans/{loan['id']}/receiving-account", headers=h, json={"bank": "CMB", "number": "1234567"})
    assert r.status_code == 400  # locked until the loan is closed
    loan = lc.ok(c.post(f"/v4/loans/{loan['id']}/simulate-transfer", headers=h,
                        json={"amount": 60_000, "kind": "supplier"}))
    due = date.fromisoformat(loan["schedule"][0]["due_date"])
    loan = lc.advance(c, h, loan, (due + timedelta(days=3)).isoformat())
    assert loan["status"] == "overdue" and loan["arrears"]["penalty"] == 0  # still in the 3 grace days
    loan = lc.advance(c, h, loan, (due + timedelta(days=30)).isoformat())
    assert loan["arrears"]["penalty"] > 0 and loan["overdue_days"] == 30
    assert loan["bureau"][0]["kind"] == "overdue_30"
    assert loan["majority"]["banks"] == ["WEBANK", "CMB"] and loan["majority"]["share"] == 0.7
    staff = lc.ok(c.get(f"/v4/loans/{loan['id']}", headers=as_officer))
    assert staff["early_warning"]["level"] == "red" and staff["bank_report"]["overdue_days"] == 30
    owed = loan["owed_now"]
    loan = lc.ok(c.post(f"/v4/loans/{loan['id']}/simulate-inflow", headers=h, json={"amount": owed}))
    assert loan["owed_now"] == 0 and loan["status"] == "active" and loan["schedule"][0]["status"] == "paid_late"
    # Stage 10: a borrower once 30 days overdue is group 4 next time.
    loan = lc.ok(c.post(f"/v4/loans/{loan['id']}/simulate-inflow", headers=h, json={"amount": 70_000}))
    lc.ok(c.post(f"/v4/loans/{loan['id']}/prepay", headers=h, json={"confirm": True}))
    app = lc.answer_all(c, h, lc.start(c, h))
    assert app["status"] == "rejected" and "nhóm khách hàng 4" in app["decision"]["reason"]["law"]


def test_revenue_method_follows_inflows(bu_client, as_seller):
    c, h = bu_client, as_seller
    loan = lc.loan_for(c, h, amount=60_000, tenor_m=6, method="revenue")
    assert loan["method"] == "revenue" and loan["minimum"]["allowed"] is False
    rr = loan["revenue_rate"]
    loan = lc.ok(c.post(f"/v4/loans/{loan['id']}/simulate-inflow", headers=h, json={"amount": 100_000}))
    loan = lc.advance(c, h, loan, loan["schedule"][0]["due_date"])
    row = loan["schedule"][0]
    assert row["revenue_base"] == 100_000
    assert row["amount_due"] == max(round(rr * 100_000), row["interest"] + 3_000)


def test_transfers_are_watched(bu_client, as_seller, as_officer):
    c, h = bu_client, as_seller
    loan = lc.loan_for(c, h, amount=60_000, tenor_m=6)
    r = lc.ok(c.post(f"/v4/loans/{loan['id']}/simulate-transfer", headers=h, json={"amount": 25_000, "kind": "personal"}))
    assert "flag" not in r["transfer"]  # the seller is not told about monitoring flags
    r = lc.ok(c.post(f"/v4/loans/{loan['id']}/simulate-transfer", headers=h, json={"amount": 1_000, "kind": "securities"}))
    alerts = lc.ok(c.get("/v4/alerts", headers=as_officer))["items"]
    assert {a["level"] for a in alerts if a["loan_id"] == loan["id"]} == {"yellow", "red"}
    loan = lc.advance(c, h, loan, (date.fromisoformat(loan["clock"]) + timedelta(days=1)).isoformat())
    staff = lc.ok(c.get(f"/v4/loans/{loan['id']}", headers=as_officer))
    assert staff["early_warning"]["level"] == "red"
    assert any(t["flag"] and t["flag"]["key"] == "misuse" for t in staff["account"]["transfers"])


def test_reminders_before_due(bu_client, as_seller):
    c, h = bu_client, as_seller
    loan = lc.loan_for(c, h, amount=60_000, tenor_m=6)
    due = date.fromisoformat(loan["schedule"][0]["due_date"])
    loan = lc.advance(c, h, loan, (due - timedelta(days=1)).isoformat())
    texts = [r["text"] for r in loan["reminders"]]
    assert any(t.startswith("Còn 7 ngày") for t in texts) and any(t.startswith("Còn 1 ngày") for t in texts)


def test_good_history_raises_group(bu_client, as_seller):
    c, h = bu_client, as_seller
    loan = lc.loan_for(c, h, amount=60_000, tenor_m=6)
    lc.ok(c.post(f"/v4/loans/{loan['id']}/prepay", headers=h, json={"confirm": True}))
    app = lc.offered(c, h)
    assert app["offer"]["group"] == 1


def test_bank_sees_its_syndicate_answers(bu_client, as_seller):
    lc.offered(bu_client, as_seller)
    items = lc.ok(bu_client.get("/v4/bank/syndicate", headers=login(bu_client, "webank@buoyup.vn")))["items"]
    assert items and items[0]["share"]["pct"] == 0.4 and items[0]["result"] == "approved"


def _pause_partners():
    from app.platform.db.session import session_scope
    from app.platform.tables import BuBank

    with session_scope() as session:
        for bank in session.query(BuBank).filter(BuBank.region == "CN", BuBank.code != "WEBANK"):
            bank.active = False


def test_webank_lends_alone_when_no_partner_agrees(bu_client, as_seller, as_officer):
    """18/10/2026: no partner at any step → WeBank alone up to ``syndicate.solo_max`` (50.000), 100 % its share."""
    _pause_partners()
    app = lc.offered(bu_client, as_seller, "lan")
    syn = app["syndicate"]
    assert app["status"] == "offered" and syn["limit"] == 50_000
    assert [(s["bank"], s["pct"]) for s in syn["split"]] == [("WEBANK", 1.0)]
    assert app["offer"]["limit"] == 50_000
    exp = app["decision"]["explanation"]
    assert any("WeBank cho vay một mình" in b["text"] for b in exp["because"])
    # Signing works with a one-bank split: the whole loan is WeBank's share.
    app = lc.select(bu_client, as_seller, app, amount=40_000)
    lc.contract(bu_client, as_seller, app)
    signed = lc.ok(lc.sign(bu_client, as_seller, app))
    loan = lc.ok(bu_client.get(f"/v4/loans/{signed['loan_id']}", headers=as_seller))
    assert signed["status"] == "disbursed" and [(s["bank"], s["amount"]) for s in loan["shares"]] == [("WEBANK", 40_000)]


def test_no_solo_when_switched_off(bu_client, as_seller, monkeypatch):
    import copy

    from app.agents import agent3_control

    real = agent3_control.active_params

    def no_solo(session):
        p = copy.deepcopy(real(session))
        p["syndicate"]["solo_max"] = 0
        return p

    _pause_partners()
    monkeypatch.setattr(agent3_control, "active_params", no_solo)
    app = lc.answer_all(bu_client, as_seller, lc.start(bu_client, as_seller, "lan"))
    assert app["status"] == "rejected" and app["decision"]["by"] == "orchestrator"
