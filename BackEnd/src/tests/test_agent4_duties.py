"""T5: manual withdrawals, key rotation, regions, use-of-funds, AML-LTR/POL-05 duties."""

from __future__ import annotations

import copy
from datetime import timedelta

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import select

from app.core import legal
from app.blockchain import withdrawals
from app.agents import agent3_control as control
from app.agents.agent4b_monitor import tick
from app.core.params import active_params
from app.platform.tables import BuAlert, BuApplication, BuBank, BuChainEntry, BuLoan, BuParams, BuWithdrawal, save_json
from app.platform.db.session import session_scope
from app.platform.db.tables import utcnow
from tests import lc
from tests.test_money_agent4 import disburse_lan, other_seller

BODY = {"requestId": "manual-0001", "user": "U-102938", "account": "6222020200112233", "amount": 100_000,
        "currency": "CNY", "region": "CN", "province": "CN-GD",
        "split": [{"bank": "WEBANK", "pct": 0.6}, {"bank": "CMB", "pct": 0.4}],
        "reason": "Agent 4 lỗi sau khi duyệt; chi thủ công theo phiếu TICKET-4471"}


def set_param(path: list[str], value) -> None:
    with session_scope() as s:
        row = s.scalar(select(BuParams).where(BuParams.active.is_(True)))
        params = copy.deepcopy(row.params)
        node = params
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = value
        save_json(row, "params", params)


def test_manual_withdrawal_roles_validation_and_idempotency(bu_client, as_seller, as_webank, as_officer, as_admin):
    url = "/v4/withdrawals/manual"
    assert bu_client.post(url, headers=as_seller, json=BODY).status_code == 403
    assert bu_client.post(url, headers=as_webank, json=BODY).status_code == 403
    r = bu_client.post(url, headers=as_officer, json=BODY)
    assert r.status_code == 201, r.text
    wd = r.json()
    assert wd["reason"] == BODY["reason"] and wd["requester"].startswith("staff:") and wd["province"] == "CN-GD"
    assert [(s["bank"], s["pct"], s["amount"]) for s in wd["shares"]] == [("WEBANK", 0.6, 60_000), ("CMB", 0.4, 40_000)]
    assert bu_client.post(url, headers=as_officer, json=BODY).json()["id"] == wd["id"]  # replay
    conflict = bu_client.post(url, headers=as_officer, json={**BODY, "amount": 100_100})
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "CONFLICT"
    bad_total = {**BODY, "requestId": "m2", "split": [{"bank": "WEBANK", "pct": 0.5}, {"bank": "CMB", "pct": 0.4}]}
    r = bu_client.post(url, headers=as_admin, json=bad_total)
    assert r.status_code == 400 and any("100,00%" in p for p in r.json()["error"]["details"]["problems"])
    decimals = {**BODY, "requestId": "m3", "split": [{"bank": "WEBANK", "pct": 0.65555}, {"bank": "CMB", "pct": 0.34445}]}
    assert bu_client.post(url, headers=as_admin, json=decimals).status_code == 400
    foreign = {**BODY, "requestId": "m4", "split": [{"bank": "WEBANK", "pct": 0.6}, {"bank": "VCB", "pct": 0.4}]}
    assert bu_client.post(url, headers=as_admin, json=foreign).status_code == 400
    assert bu_client.post(url, headers=as_admin, json={**BODY, "requestId": "m5", "currency": "VND"}).status_code == 400
    assert bu_client.post(url, headers=as_admin, json={**BODY, "requestId": "m6", "province": "Mars"}).status_code == 400
    assert bu_client.post(url, headers=as_admin, json={**BODY, "requestId": "m7", "reason": ""}).status_code == 400
    demo = {**BODY, "requestId": "demo-1", "demo": True, "amount": 60_000}
    r = bu_client.post(url, headers=as_admin, json=demo)
    assert r.status_code == 400 and r.json()["error"]["details"]["max"] == 50_000
    r = bu_client.post(url, headers=as_admin, json={**demo, "amount": 40_000, "province": "Quảng Đông"})
    assert r.status_code == 201 and r.json()["requester"] == "DEMO" and r.json()["province"] == "CN-GD"
    with session_scope() as s:
        assert s.get(BuBank, "WEBANK").limit_used == 0  # a manual payout is not a loan

    listed = bu_client.get("/v4/withdrawals", headers=as_officer).json()["items"]
    assert {i["id"] for i in listed} >= {wd["id"]} and all(not i["locked"] for i in listed)
    assert bu_client.get("/v4/withdrawals", headers=as_webank).status_code == 403
    check = bu_client.get(f"/v4/withdrawals/{wd['id']}/verify", headers=as_officer).json()
    assert check["ok"] and check["merkle_ok"] and check["fingerprints_ok"] and check["split_total_pct"] == 100.0
    assert check["amounts_ok"] and [n["holds"] for n in check["nodes"]] == [True] * 4
    assert bu_client.get("/v4/withdrawals/WD-NONE/verify", headers=as_officer).status_code == 404


def test_bank_key_rotation(bu_client, as_webank, as_seller, as_admin):
    key = X25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                serialization.NoEncryption()).hex()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    with session_scope() as s:
        old_private = s.get(BuBank, "WEBANK").private_key_demo
    assert bu_client.put("/v4/banks/WEBANK/public-key", headers=as_seller, json={"public_key": public}).status_code == 403
    assert bu_client.put("/v4/banks/CMB/public-key", headers=as_webank, json={"public_key": public}).status_code == 403
    assert bu_client.put("/v4/banks/WEBANK/public-key", headers=as_webank, json={"public_key": "zz"}).status_code == 400
    r = bu_client.put("/v4/banks/WEBANK/public-key", headers=as_webank, json={"public_key": public})
    assert r.status_code == 200 and r.json()["public_key"] == public
    assert [k["retired_at"] is None for k in r.json()["keys"]] == [False, True]
    _, loan_id = disburse_lan()
    with session_scope() as s:
        wd = s.get(BuWithdrawal, s.get(BuLoan, loan_id).withdrawal_id)
        assert withdrawals.decrypt(wd, private)["opened"] == ["summary", "WEBANK"]
        assert withdrawals.decrypt(wd, old_private)["opened"] == []
        kinds = set(s.scalars(select(BuChainEntry.kind)))
    assert "bank_key" not in kinds  # rotation is not visible on the chain
    items = bu_client.get("/v4/bank/withdrawals", headers=as_webank).json()["items"]
    assert items[0]["locked"] is True  # the server does not hold the new private key


def test_regions_and_province(bu_client, as_seller, as_officer):
    regions = {r["code"]: r for r in bu_client.get("/v4/regions", headers=as_seller).json()["regions"]}
    assert regions["CN"]["currency"] == "CNY" and {"code": "CN-GD", "name": "Quảng Đông"} in regions["CN"]["provinces"]
    assert [p["name"] for p in regions["VN"]["provinces"]][:3] == ["Hà Nội", "TP. Hồ Chí Minh", "Hải Phòng"]
    app = lc.offered(bu_client, as_seller)
    assert app["stores"][0]["province"] == "CN-GD"
    app = lc.select(bu_client, as_seller, app, amount=150_000, tenor_m=6)
    lc.contract(bu_client, as_seller, app)
    done = lc.ok(lc.sign(bu_client, as_seller, app))
    with session_scope() as s:
        wd = s.get(BuWithdrawal, s.get(BuLoan, done["loan_id"]).withdrawal_id)
        master = s.get(BuBank, "MASTER").private_key_demo
        summary = withdrawals.decrypt(wd, master)["pieces"]["summary"]
    assert summary["province"] == "CN-GD" and summary["amount"] == 150_000


def test_use_of_funds_check(bu_client, as_officer):
    # 150.000: 50.000 paid straight to SUP-0091, which invoices the borrower → use of funds proven.
    _, ok_loan = disburse_lan()
    # 80.000 (all to the business account) for a plan with SUP-0137 (linked to the seller): no invoice proves
    # the use of funds.
    plan = {"event": "11.11", "item": "Áo khoác nữ", "group": "quần áo", "supplier": "SUP-0137"}
    _, bad_loan = disburse_lan(other_seller(), choice={"amount": 80_000, "tenor_m": 3}, plan=plan)
    day = utcnow().date() + timedelta(days=16)
    with session_scope() as s:
        tick(s, day)
    with session_scope() as s:
        assert s.get(BuLoan, ok_loan).doc["use_of_funds"]["status"] == "ok"
        uof = s.get(BuLoan, bad_loan).doc["use_of_funds"]
        assert uof["status"] == "missing" and uof["supplier"] == "SUP-0137" and uof["checked_at"] == day.isoformat()
        alert = s.scalar(select(BuAlert).where(BuAlert.loan_id == bad_loan))
        assert alert.level == "yellow" and alert.signals[-1]["key"] == "use_of_funds"
        assert s.scalar(select(BuAlert).where(BuAlert.loan_id == ok_loan)) is None
    loan = bu_client.get(f"/v4/loans/{bad_loan}", headers=as_officer).json()
    assert loan["use_of_funds"]["status"] == "missing"


def test_aml_ltr_threshold_by_payee_type_and_duties(bu_client, as_seller, as_officer):
    app = lc.offered(bu_client, as_seller)
    with session_scope() as s:
        row = s.get(BuApplication, app["id"])
        doc = copy.deepcopy(row.doc)
        params = copy.deepcopy(active_params(s))
    option = {**doc["offer"]["options"][0], "amount": 150_000}  # 100.000 to the account, 50.000 to the supplier
    assert control.payee_type(doc) == "individual"  # hộ kinh doanh
    with session_scope() as s:
        row = s.get(BuApplication, app["id"])
        rules = control.evaluate_rules(params, row, doc, option)
        assert rules["AML-LTR-01"]["ok"] is True and rules["POL-05"]["ok"] is False
        params["legal"]["ltr_threshold"] = {"organization": 2_000_000, "individual": 100_000}
        assert control.evaluate_rules(params, row, doc, option)["AML-LTR-01"]["ok"] is False  # account leg
        params["legal"]["ltr_threshold"] = {"organization": 50_000, "individual": 500_000}
        assert control.evaluate_rules(params, row, doc, option)["AML-LTR-01"]["ok"] is False  # supplier leg
        company = copy.deepcopy(doc)
        company["internal"]["data"]["registry"]["type"] = "company"
        assert control.payee_type(company) == "organization"
    assert legal.pol05_applies(1, "A", 10_000_001) and not legal.pol05_applies(1, "A", 10_000_000)
    app = lc.select(bu_client, as_seller, app, amount=150_000, tenor_m=6)
    lc.contract(bu_client, as_seller, app)
    done = lc.ok(lc.sign(bu_client, as_seller, app))
    with session_scope() as s:
        entry = s.scalar(select(BuChainEntry).where(BuChainEntry.case_id == app["id"],
                                                    BuChainEntry.kind == "disbursement"))
        assert {"code": "POL-05", "action": "Bắt buộc trả nhà cung cấp SUP-0091"} in entry.payload["duties"]
        assert entry.payload["to_supplier"] == 50_000
    assert done["status"] == "disbursed"
