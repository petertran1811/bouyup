"""HTTP tests for loans, portfolio, banks, bank portal, chain, post-audit, admin."""

from __future__ import annotations

from datetime import date, timedelta

from app.agents import agent5_postaudit as postaudit

import pytest
from fastapi import HTTPException

from app.blockchain import withdrawals
from app.agents.agent4b_monitor import release_limit, reserve_limit
from app.banks.split import split_largest_remainder
from app.platform.tables import BuBank, BuChainEntry, BuLoan, BuWithdrawal, save_json
from app.platform.db.session import session_scope
from tests.conftest import login
from tests import lc
from tests.test_money_agent4 import disburse_lan, other_seller


def _contract_id(loan_id: str, bank: str) -> str:
    with session_scope() as s:
        return next(leg["contract_id"] for leg in s.get(BuLoan, loan_id).doc["legs"] if leg["bank"] == bank)


def test_loan_endpoints_and_inflow(bu_client, as_seller, as_officer, as_webank):
    app_id, loan_id = disburse_lan()
    items = bu_client.get("/v4/loans", headers=as_seller).json()["items"]
    assert [i["id"] for i in items] == [loan_id]
    assert items[0]["shares"][0] == {"bank": "WEBANK", "name": "WeBank", "pct": 0.4, "amount": 60_000,
                                      "repaid": 0, "contract_id": _contract_id(loan_id, "WEBANK"),
                                      "outstanding": 60_000}
    r = bu_client.post(f"/v4/loans/{loan_id}/simulate-inflow", json={"amount": 50000}, headers=as_seller)
    assert r.status_code == 200, r.text
    loan = r.json()
    # Nothing is due yet: the payout stays in the business account until the due date.
    assert loan["repayments"] == [] and loan["account"]["balance"] == 150_000 and loan["inflow_total"] == 50_000
    first = loan["schedule"][0]
    loan = lc.advance(bu_client, as_seller, loan, first["due_date"])
    days = (date.fromisoformat(first["due_date"]) - date.fromisoformat(loan["start_date"])).days
    paid = 25_000 + round(150_000 * 0.10 * days / 365)
    assert loan["repayments"][0]["amount"] == paid and loan["repayments"][0]["detail"]["kind"] == "due"
    assert loan["repayments"][0]["split"] == [{"bank": b, "amount": a} for b, a in
                                              zip(("WEBANK", "CMB", "ICBC"), split_largest_remainder(paid, [4, 3, 3]))]
    assert loan["outstanding"] == 125_000 and loan["repayments"][0]["chain_tx"].startswith("0x")
    assert bu_client.get(f"/v4/loans/{loan_id}", headers=as_webank).status_code == 403  # banks use /bank/*
    assert bu_client.post(f"/v4/loans/{loan_id}/simulate-inflow", json={"amount": 0},
                          headers=as_seller).status_code == 400
    other = bu_client.post("/v4/auth/register", json={"email": "x@shop.vn", "password": "abc12345",
                                                      "display_name": "X", "accept_terms": True}).json()
    other_h = {"Authorization": "Bearer " + other["token"]}
    assert bu_client.get(f"/v4/loans/{loan_id}", headers=other_h).status_code == 403
    assert bu_client.get("/v4/loans", headers=other_h).json()["items"] == []
    assert bu_client.get(f"/v4/loans/{loan_id}", headers=as_officer).status_code == 200


def test_tick_alerts_and_ack(bu_client, as_officer, as_seller):
    _, loan_id = disburse_lan()
    assert bu_client.post("/v4/monitoring/tick", json={}, headers=as_seller).status_code == 403
    loan = lc.ok(bu_client.post(f"/v4/loans/{loan_id}/simulate-transfer", headers=as_seller,
                                json={"amount": 100_000, "kind": "supplier"}))
    late = date.fromisoformat(loan["schedule"][0]["due_date"]) + timedelta(days=8)
    r = bu_client.post("/v4/monitoring/tick", json={"as_of": late.isoformat()}, headers=as_officer)
    assert r.status_code == 200, r.text
    alerts = r.json()["alerts"]
    assert alerts[0]["level"] == "red" and not alerts[0]["acked"] and r.json()["checked"] == 1
    listed = bu_client.get("/v4/alerts", headers=as_officer).json()["items"]
    assert listed[0]["id"] == alerts[0]["id"]
    ack = bu_client.post(f"/v4/alerts/{alerts[0]['id']}/ack", headers=as_officer).json()
    assert ack["acked"] is True


def test_portfolio_stress(bu_client, as_officer, as_seller):
    _, loan_id = disburse_lan()
    assert bu_client.get("/v4/portfolio", headers=as_seller).status_code == 403
    data = bu_client.get("/v4/portfolio", headers=as_officer).json()
    total_due = bu_client.get(f"/v4/loans/{loan_id}", headers=as_officer).json()["total_due"]
    assert data["kpis"]["loans_active"] == 1 and data["kpis"]["disbursed_total"] == 150_000
    assert data["kpis"]["outstanding"] == 150_000 and data["kpis"]["overdue_amount"] == 0
    event = data["by_event"][0]
    # 63 % usable × 50 % drop × prudent revenue over 6 months still covers the 150.000 loan.
    assert event["event"] == "11.11" and event["exposure"] == total_due and event["shortfall_50pct"] == 0
    assert {b["bank"]: b["share_pct"] for b in data["by_bank"]} == {"WEBANK": 0.4, "CMB": 0.3, "ICBC": 0.3}


def test_public_stats(bu_client):
    from app.api.loans import public_stats

    disburse_lan()
    with session_scope() as session:
        stats = public_stats(session)
    assert stats["banks"] == 11 and stats["loans_active"] == 1 and stats["disbursed_total"] == 150_000


def test_banks_visibility_and_policy(bu_client, as_seller, as_webank, as_admin):
    seller_view = bu_client.get("/v4/banks", headers=as_seller).json()["items"]
    assert len(seller_view) == 11 and set(seller_view[0]) == {"code", "name", "region"}
    bank_view = {b["code"]: b for b in bu_client.get("/v4/banks", headers=as_webank).json()["items"]}
    assert "limit_used" in bank_view["WEBANK"] and "limit_used" not in bank_view["CMB"]
    assert "MASTER" not in bank_view
    assert bu_client.get("/v4/banks/CMB", headers=as_webank).status_code == 403
    assert bu_client.get("/v4/banks/MASTER", headers=as_admin).status_code == 404
    assert bu_client.put("/v4/banks/CMB/policy", json={"max_rate": 0.2}, headers=as_webank).status_code == 403
    r = bu_client.put("/v4/banks/WEBANK/policy", json={"min_grade": "B", "tiers": [2]}, headers=as_webank)
    assert r.status_code == 200 and r.json()["policy"]["min_grade"] == "B"
    for bad in ({"min_share": 0.2}, {"tiers": [3]}, {"min_grade": "F"}, {"min_amount": -1},
                {"excluded_groups": ["vũ khí"]}, {"min_amount": 5_000_000, "max_amount": 10}):
        assert bu_client.put("/v4/banks/WEBANK/policy", json=bad, headers=as_admin).status_code == 400, bad


def test_bank_portal_sees_only_own_piece(bu_client, as_webank):
    _, loan_id = disburse_lan()
    portfolio = bu_client.get("/v4/bank/portfolio", headers=as_webank).json()
    assert [s["amount"] for s in portfolio["shares"]] == [60_000]
    wds = bu_client.get("/v4/bank/withdrawals", headers=as_webank).json()["items"]
    assert len(wds) == 1 and wds[0]["my_piece"] == {"pct": 0.4, "amount": 60_000,
                                                    "contract_id": _contract_id(loan_id, "WEBANK")}
    assert wds[0]["summary"]["amount"] == 150_000 and wds[0]["fingerprint_ok"] is True
    assert "45000" not in str(wds) and _contract_id(loan_id, "CMB") not in str(wds)
    vcb = login(bu_client, "vcb@buoyup.vn")
    assert bu_client.get("/v4/bank/withdrawals", headers=vcb).json()["items"] == []
    assert bu_client.get("/v4/bank/portfolio", headers=vcb).json()["shares"] == []


def test_chain_endpoints_and_tamper(bu_client, as_seller, as_officer, as_admin, as_webank):
    app_id, _ = disburse_lan()
    wd = bu_client.get("/v4/chain/withdrawals", headers=as_seller).json()["items"][0]
    assert wd["pieces"] == 4 and "WEBANK" not in str(wd)
    assert bu_client.get(f"/v4/chain/withdrawals/{wd['id']}", headers=as_seller).json()["slots"] == 4
    assert bu_client.post(f"/v4/chain/withdrawals/{wd['id']}/decrypt", json={},
                          headers=as_seller).status_code == 403
    mine = bu_client.post(f"/v4/chain/withdrawals/{wd['id']}/decrypt", json={}, headers=as_webank).json()
    assert mine["opened"] == ["summary", "WEBANK"]
    everything = bu_client.post(f"/v4/chain/withdrawals/{wd['id']}/decrypt", json={}, headers=as_admin).json()
    assert len(everything["opened"]) == 4
    keys = {k["code"]: k for k in bu_client.get("/v4/chain/keys", headers=as_admin).json()["items"]}
    boc = bu_client.post(f"/v4/chain/withdrawals/{wd['id']}/decrypt",
                         json={"private_key_hex": keys["BOC"]["private_key_hex"]}, headers=as_admin).json()
    assert boc == {"id": wd["id"], "opened": [], "pieces": {}, "fingerprints_ok": None,
                   "message": "Khóa này không mở được ô nào"}
    assert bu_client.get("/v4/chain/keys", headers=as_officer).status_code == 403
    assert bu_client.get("/v4/chain/status", headers=as_seller).json()["height"] >= 1
    assert bu_client.get("/v4/chain/blocks?limit=5", headers=as_seller).status_code == 200

    assert bu_client.get(f"/v4/chain/cases/{app_id}/verify", headers=as_officer).json()["ok"] is True
    assert bu_client.get("/v4/chain/verify", headers=as_admin).json()["ok"] is True
    assert bu_client.get("/v4/chain/verify", headers=as_officer).status_code == 403
    with session_scope() as session:
        entry = session.query(BuChainEntry).filter(BuChainEntry.case_id == app_id).first()
        entry.payload = {**entry.payload, "loan_id": "loan_forged"}
    broken = bu_client.get(f"/v4/chain/cases/{app_id}/verify", headers=as_officer).json()
    assert broken["ok"] is False and broken["broken_at"] == entry.seq
    assert app_id in bu_client.get("/v4/chain/verify", headers=as_admin).json()["broken_cases"]


def test_postaudit_flow(bu_client, as_officer, as_admin, monkeypatch):
    # The approval workflow runs on the 20-row synthetic sample; the sample-size gate (30, Agent 5 §6)
    # has its own test in test_agent5_fixes.py.
    monkeypatch.setattr(postaudit, "MIN_SAMPLE", 20)
    run = bu_client.post("/v4/postaudit/run", headers=as_officer)
    assert run.status_code == 200, run.text
    body = run.json()
    finding = next(f for f in body["report"]["findings"] if f["segment"] == "thời trang")
    assert finding["value"] < 0.80
    prop = next(p for p in body["proposals"] if p["param"] == "prudence.thời trang")
    assert prop["from"] == 0.70 and prop["to"] < 0.70 and prop["status"] == "pending"
    url = f"/v4/postaudit/proposals/{prop['id']}/decision"
    assert bu_client.post(url, json={"decision": "approve"}, headers=as_officer).status_code == 403
    r = bu_client.post(url, json={"decision": "approve", "note": "Hội đồng rủi ro đồng ý"}, headers=as_admin)
    assert r.status_code == 200, r.text
    assert r.json()["params_version"] == "v4.1"
    params = bu_client.get("/v4/params", headers=as_officer).json()
    assert params["version"] == "v4.1" and params["params"]["prudence"]["thời trang"] == prop["to"]
    assert [h["active"] for h in params["history"]] == [True, False]
    assert bu_client.post(url, json={"decision": "reject"}, headers=as_admin).status_code == 400
    rerun = bu_client.post("/v4/postaudit/run", headers=as_officer).json()
    assert not any(p["param"] == "prudence.thời trang" for p in rerun["proposals"])
    assert bu_client.get("/v4/chain/verify", headers=as_admin).json()["ok"] is True


def test_admin_users(bu_client, as_admin, as_officer):
    assert bu_client.get("/v4/admin/users", headers=as_officer).status_code == 403
    users = bu_client.get("/v4/admin/users", headers=as_admin).json()["items"]
    assert any(u["email"] == "admin@buoyup.vn" and u["active"] for u in users)
    base = {"email": "bidv@buoyup.vn", "password": "BidvPartner2026", "display_name": "BIDV", "role": "bank"}
    assert bu_client.post("/v4/admin/users", json=base, headers=as_admin).status_code == 400  # no bank_code
    assert bu_client.post("/v4/admin/users", json={**base, "bank_code": "MASTER"},
                          headers=as_admin).status_code == 400
    for weak in ("weak", "Bidv2026x", "abcdefghijklm", "1234567890123"):  # staff: ≥12, letters + digits
        assert bu_client.post("/v4/admin/users", json={**base, "bank_code": "BIDV", "password": weak},
                              headers=as_admin).status_code == 400, weak
    r = bu_client.post("/v4/admin/users", json={**base, "bank_code": "bidv"}, headers=as_admin)
    assert r.status_code == 201 and r.json()["user"]["bank_code"] == "BIDV"
    assert bu_client.post("/v4/admin/users", json={**base, "bank_code": "BIDV"},
                          headers=as_admin).status_code == 409
    new_id = r.json()["user"]["id"]
    bidv = login(bu_client, "bidv@buoyup.vn", "BidvPartner2026")
    off = bu_client.patch(f"/v4/admin/users/{new_id}", json={"active": False}, headers=as_admin)
    assert off.status_code == 200 and off.json()["user"]["active"] is False
    assert bu_client.get("/v4/auth/me", headers=bidv).status_code == 401
    me = bu_client.get("/v4/auth/me", headers=as_admin).json()["user"]["id"]
    assert bu_client.patch(f"/v4/admin/users/{me}", json={"active": False}, headers=as_admin).status_code == 400
    audit = bu_client.get("/v4/admin/audit", headers=as_admin).json()["items"]
    assert audit[0]["kind"] == "user_updated"


def test_http_end_to_end_lan(bu_client, as_seller, as_officer):
    """Full loan circle through the API: store link → offer → choice → contract → signature → loan →
    due-date debit → prepayment → closed, every step anchored on the chain."""
    app = lc.offered(bu_client, as_seller)
    assert app["offer"]["limit"] == 200_000
    app = lc.select(bu_client, as_seller, app, amount=150_000, tenor_m=6)
    lc.contract(bu_client, as_seller, app)
    app = lc.ok(lc.sign(bu_client, as_seller, app))
    assert app["status"] == "disbursed", app.get("status")
    loan = bu_client.get(f"/v4/loans/{app['loan_id']}", headers=as_seller).json()
    assert loan["amount"] == 150_000 and loan["principal_outstanding"] == 150_000
    assert sorted((s["bank"], s["pct"]) for s in loan["shares"]) == [("CMB", 0.3), ("ICBC", 0.3), ("WEBANK", 0.4)]
    loan = lc.advance(bu_client, as_seller, loan, loan["schedule"][0]["due_date"])
    assert loan["schedule"][0]["status"] == "paid" and loan["repayments"][0]["amount"] == loan["schedule"][0]["paid"]
    loan = lc.ok(bu_client.post(f"/v4/loans/{loan['id']}/simulate-inflow", json={"amount": 60_000},
                                headers=as_seller))
    loan = lc.ok(bu_client.post(f"/v4/loans/{loan['id']}/prepay", json={}, headers=as_seller))
    assert loan["status"] == "closed" and loan["repaid"] == sum(s["repaid"] for s in loan["shares"])
    assert bu_client.get(f"/v4/applications/{app['id']}", headers=as_seller).json()["status"] == "closed"
    assert bu_client.get(f"/v4/chain/cases/{app['id']}/verify", headers=as_officer).json()["ok"] is True


def _register(client, email: str) -> dict[str, str]:
    r = client.post("/v4/auth/register", json={"email": email, "password": "abc12345",
                                               "display_name": "Shop", "accept_terms": True})
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_verify_detects_reencrypted_withdrawal(bu_client, as_admin):
    """Attacker rewrites a withdrawal with new amounts and a self-consistent root/tx."""
    disburse_lan()
    with session_scope() as session:
        wd = session.query(BuWithdrawal).one()
        master = session.get(BuBank, "MASTER").public_key
        record = withdrawals.build_record(wd.id, [{"piece": "summary", "amount": 999999}], [(master, [0])])
        save_json(wd, "envelope", record["envelope"])
        save_json(wd, "piece_fingerprints", record["piece_fingerprints"])
        wd.merkle_root = record["merkle_root"]
        wd.tx = withdrawals.withdrawal_tx(wd.id, record["merkle_root"], record["envelope"])
        wid = wd.id
    result = bu_client.get("/v4/chain/verify", headers=as_admin).json()
    assert result["ok"] is False and result["broken_withdrawals"] == [wid]


def test_verify_detects_deleted_withdrawal(bu_client, as_admin):
    disburse_lan()
    with session_scope() as session:
        wd = session.query(BuWithdrawal).one()
        wid = wd.id
        session.delete(wd)
    result = bu_client.get("/v4/chain/verify", headers=as_admin).json()
    assert result["ok"] is False and wid in result["broken_withdrawals"]


def test_verify_detects_edited_case_payload(bu_client, as_admin):
    app_id, _ = disburse_lan()
    assert bu_client.get("/v4/chain/verify", headers=as_admin).json()["ok"] is True
    with session_scope() as session:
        entry = session.query(BuChainEntry).filter(BuChainEntry.case_id == app_id).first()
        entry.payload = {**entry.payload, "merkle_root": "0x00"}
    result = bu_client.get("/v4/chain/verify", headers=as_admin).json()
    assert result["ok"] is False and app_id in result["broken_cases"]


def test_production_keys_not_on_server(bu_client, as_admin, as_webank):
    """With no private key stored (production), decrypt needs a pasted key and the
    bank portal lists withdrawals locked instead of decrypting server-side."""
    disburse_lan()
    with session_scope() as session:
        for bank in session.query(BuBank).all():
            bank.private_key_demo = ""
        wid = session.query(BuWithdrawal).one().id
    for headers in (as_admin, as_webank):
        r = bu_client.post(f"/v4/chain/withdrawals/{wid}/decrypt", json={}, headers=headers)
        assert r.status_code == 400
        assert r.json()["error"]["message"] == "Khóa riêng do ngân hàng tự giữ; dán khóa để giải mã"
    items = bu_client.get("/v4/bank/withdrawals", headers=as_webank).json()["items"]
    assert len(items) == 1 and items[0]["locked"] is True and items[0]["my_piece"] is None


def test_simulate_inflow_hidden_outside_demo(bu_client, as_seller, monkeypatch):
    from app.platform.config import settings

    _, loan_id = disburse_lan()
    monkeypatch.setattr(settings, "app_env", "production")
    r = bu_client.post(f"/v4/loans/{loan_id}/simulate-inflow", json={"amount": 50000}, headers=as_seller)
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_bank_limit_reserve_is_conditional(bu_client):
    with session_scope() as session:
        cmb = session.get(BuBank, "CMB")
        cmb.limit_used = cmb.limit_total - 100
        session.flush()
        with pytest.raises(HTTPException) as exc:
            reserve_limit(session, "CMB", 101)
        assert exc.value.status_code == 400 and exc.value.detail["code"] == "INVALID_STATE"
        reserve_limit(session, "CMB", 100)
        assert session.get(BuBank, "CMB").limit_used == cmb.limit_total
        release_limit(session, "CMB", cmb.limit_total + 5)
        assert session.get(BuBank, "CMB").limit_used == 0


def test_seller_sees_only_own_chain_refs(bu_client, as_seller):
    app_id, _ = disburse_lan()
    other = _register(bu_client, "other@shop.vn")
    own_wds = bu_client.get("/v4/chain/withdrawals", headers=as_seller).json()["items"]
    assert len(own_wds) == 1
    assert bu_client.get("/v4/chain/withdrawals", headers=other).json()["items"] == []
    assert bu_client.get(f"/v4/chain/withdrawals/{own_wds[0]['id']}", headers=other).status_code == 404
    refs_other = {t["ref"] for b in bu_client.get("/v4/chain/blocks?limit=200", headers=other).json()["items"]
                  for t in b["txs"]}
    assert refs_other == {None}
    refs_own = {t["ref"] for b in bu_client.get("/v4/chain/blocks?limit=200", headers=as_seller).json()["items"]
                for t in b["txs"]}
    assert {app_id, own_wds[0]["id"]} <= refs_own and "system" not in refs_own


def test_list_limits(bu_client, as_officer, as_admin, as_webank):
    disburse_lan()
    disburse_lan(other_seller())  # one loan at a time per borrower (POL-07)
    assert len(bu_client.get("/v4/loans?limit=1", headers=as_officer).json()["items"]) == 1
    assert len(bu_client.get("/v4/chain/withdrawals?limit=1", headers=as_officer).json()["items"]) == 1
    assert len(bu_client.get("/v4/bank/withdrawals?limit=1", headers=as_webank).json()["items"]) == 1
    assert len(bu_client.get("/v4/admin/users?limit=2", headers=as_admin).json()["items"]) == 2
    assert bu_client.get("/v4/alerts?limit=500", headers=as_officer).status_code == 400
