"""Review 17/10/2026: CCCD OCR at the identity step, personal borrowers, the simplified product (system
tenor, instalments only, the whole loan to the WeBank account), the plan declaration, revenue screenshots,
goods read from free text, and "Ngân hàng của tôi"."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from app.data_sources import consent, sources
from app.platform.config import settings
from tests import lc

DEMO = Path(__file__).resolve().parents[1] / "CCCD" / "data" / "ocr_demo"
VALID_FRONT = DEMO / "china_id_front_valid_demo.png"
BAD_FRONT = DEMO / "china_id_front_demo.png"
BACK = DEMO / "china_id_back_demo.png"


def b64(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def _draft(c, h, scenario="lan", borrower_type="individual_business"):
    return lc.ok(c.post("/v4/applications", headers=h, json={"tier": 2, "borrower_type": borrower_type,
                                                             "store_urls": [sources.demo_url(scenario)]}))


@pytest.fixture()
def strict(monkeypatch):
    monkeypatch.setattr(settings, "cccd_ocr_required", True)
    monkeypatch.setattr(settings, "plan_declaration_required", True)


# --- CCCD ------------------------------------------------------------------------------------------

def test_identity_needs_a_cccd_scan(bu_client, as_seller, strict):
    app = _draft(bu_client, as_seller)
    r = bu_client.post(f"/v4/applications/{app['id']}/identity", headers=as_seller, json={"cccd": True, "face": True})
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "cccd"


def test_valid_card_passes_and_is_never_stored(bu_client, as_seller, as_officer, strict):
    app = _draft(bu_client, as_seller)
    p = f"/v4/applications/{app['id']}"
    front = lc.ok(bu_client.post(p + "/cccd", headers=as_seller, json={"image": b64(VALID_FRONT)}))
    assert front["side"] == "front" and front["fields"]["id_number_validation"]["checksum_valid"] is True
    back = lc.ok(bu_client.post(p + "/cccd", headers=as_seller, json={"image": b64(BACK)}))
    assert back["side"] == "back" and back["scans"] == ["back", "front"]
    a = lc.ok(bu_client.post(p + "/identity", headers=as_seller, json={"cccd": True, "face": True}))
    assert a["status"] == "identified"
    full = bu_client.get(p, headers=as_officer).json()
    card = full["identity"]["card"]
    assert card["checksum_valid"] and card["problems"] == [] and card["id_masked"].startswith("440106")
    assert "1235" in card["id_masked"] and "19900101" not in card["id_masked"]
    assert not any(f["code"] == "RISK_ID_REVIEW" for f in full["verification"]["flags"])
    assert not list(Path(settings.upload_dir).glob(f"{app['id']}/*"))  # the card image is not kept


def test_invalid_card_goes_to_an_officer(bu_client, as_seller, as_officer, strict):
    app = _draft(bu_client, as_seller)
    p = f"/v4/applications/{app['id']}"
    lc.ok(bu_client.post(p + "/cccd", headers=as_seller, json={"image": b64(BAD_FRONT)}))
    lc.ok(bu_client.post(p + "/identity", headers=as_seller, json={"cccd": True, "face": True}))
    full = bu_client.get(p, headers=as_officer).json()
    flag = next(f for f in full["verification"]["flags"] if f["code"] == "RISK_ID_REVIEW")
    assert flag["status"] == "open" and "mặt sau" in flag["note"] and "số CCCD" in flag["note"]


def test_minor_is_refused(bu_client, as_seller, monkeypatch):
    from app.agents import agent1_verify

    real = agent1_verify.cccd_checks
    monkeypatch.setattr(agent1_verify, "cccd_checks", lambda doc, data: {**(real(doc, data) or {}), "under_18": True,
                                                                         "problems": [], "engine": "x", "sides": ["front"],
                                                                         "id_masked": None})
    app = _draft(bu_client, as_seller)
    p = f"/v4/applications/{app['id']}"
    lc.ok(bu_client.post(p + "/cccd", headers=as_seller, json={"image": b64(VALID_FRONT)}))
    a = lc.ok(bu_client.post(p + "/identity", headers=as_seller, json={"cccd": True, "face": True}))
    assert a["status"] == "rejected" and "18 tuổi" in a["verification"]["reason"]["factor"]


def test_garbage_image_is_refused(bu_client, as_seller):
    app = _draft(bu_client, as_seller)
    r = bu_client.post(f"/v4/applications/{app['id']}/cccd", headers=as_seller, json={"image": "aGVsbG8gd29ybGQgaGVsbG8="})
    assert r.status_code == 422


# --- personal borrower -----------------------------------------------------------------------------

@pytest.mark.product_v5
def test_personal_seller_without_registration(bu_client, as_seller):
    app = lc.offered(bu_client, as_seller, "personal", borrower_type="individual")
    o = app["offer"]
    assert app["borrower_type"] == "individual" and o["blocks"]["B8"]["type_cap"] == 50_000
    assert o["limit"] <= 50_000 and o["tenors"] == [3, 6, 12]


def test_household_owner_may_borrow_as_a_person(bu_client, as_seller):
    app = _draft(bu_client, as_seller, "lan", "individual")
    assert app["status"] == "draft" and app["borrower_type"] == "individual"


# --- product v5 ------------------------------------------------------------------------------------

@pytest.mark.product_v5
def test_system_sets_the_tenor_and_only_instalments(bu_client, as_seller):
    app = lc.offered(bu_client, as_seller)
    p = f"/v4/applications/{app['id']}"
    r = bu_client.post(p + "/select", headers=as_seller, json={"amount": 50_000, "tenor_m": 6})
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "tenor_m"
    r = bu_client.post(p + "/select", headers=as_seller, json={"amount": 50_000, "method": "revenue"})
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "method"
    a = lc.ok(bu_client.post(p + "/select", headers=as_seller, json={"amount": 50_000, "due_day": 10}))
    assert a["selection"]["tenor_m"] == 12 and a["selection"]["method"] == "installment"


@pytest.mark.product_v5
@pytest.mark.seed_loan
def test_whole_loan_goes_to_the_webank_account(bu_client, as_seller):
    from app.core.params import DEFAULT_PARAMS

    assert 36 not in DEFAULT_PARAMS["product"]["tenors"]["company"]
    loan = lc.loan_for(bu_client, as_seller)
    assert loan["payee"]["kind"] == "business_account" and loan["payee"]["to_supplier"] == 0


# --- plan: declaration, goods from free text, no supplier ------------------------------------------

def _consented(c, h, scenario="lan"):
    app = _draft(c, h, scenario)
    p = f"/v4/applications/{app['id']}"
    lc.ok(c.post(p + "/identity", headers=h, json={"cccd": True, "face": True}))
    return lc.ok(c.post(p + "/consent", headers=h, json={"scopes": list(consent.CONSENT_BOXES)}))


def test_plan_needs_the_declaration_and_records_it(bu_client, as_seller, monkeypatch):
    monkeypatch.setattr(settings, "plan_declaration_required", True)
    app = _consented(bu_client, as_seller)
    p = f"/v4/applications/{app['id']}"
    plan = {k: v for k, v in app["plan"]["suggested"].items() if k not in ("supplier", "brand", "auth")}
    r = bu_client.put(p + "/plan", headers=as_seller, json=plan)
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "declaration"
    a = lc.ok(bu_client.put(p + "/plan", headers=as_seller, json={**plan, "declaration": True}))
    assert a["plan"]["declaration"]["chain_tx"] and "cam đoan" in a["plan"]["declaration"]["text"]
    a = lc.answer_all(bu_client, as_seller, lc.ok(bu_client.post(p + "/verify", headers=as_seller, json={})))
    assert a["status"] == "offered"  # no supplier declared: the item's own invoices are the supply chain
    assert a["offer"]["blocks"]["B3"]["supplier_factor"] == 1.0


@pytest.mark.parametrize("item,other", [("Phụ kiện", "pod dùng một lần vị xoài"), ("Vape mini", ""),
                                        ("Quà tặng", "电子烟")])
def test_prohibited_goods_hidden_as_other_are_caught(bu_client, as_seller, item, other):
    app = _consented(bu_client, as_seller)
    p = f"/v4/applications/{app['id']}"
    plan = {**app["plan"]["suggested"], "group": "khác", "item": item, "group_other": other}
    lc.ok(bu_client.put(p + "/plan", headers=as_seller, json=plan))
    a = lc.answer_all(bu_client, as_seller, lc.ok(bu_client.post(p + "/verify", headers=as_seller, json={})))
    assert a["status"] == "rejected", a["status"]


def test_classify_goods():
    assert sources.classify_goods("Tinh dầu thuốc lá điện tử") == "dịch thuốc lá điện tử"
    assert sources.classify_goods("Áo khoác nữ") is None
    assert sources.effective_group({"group": "quần áo", "item": "Thuốc kháng sinh"}) == "dược"


# --- revenue screenshots ---------------------------------------------------------------------------

def test_statement_screenshots_are_kept_for_the_officer(bu_client, as_seller, as_officer):
    app = _consented(bu_client, as_seller)
    p = f"/v4/applications/{app['id']}"
    up = bu_client.post(p + "/statement-images", headers=as_seller, json={"image": b64(BACK), "month": "2026-09"})
    assert up.status_code == 201 and up.json()["count"] == 1
    dup = bu_client.post(p + "/statement-images", headers=as_seller, json={"image": b64(BACK)})
    assert dup.status_code == 409
    img = bu_client.get(f"{p}/statement-images/{up.json()['id']}", headers=as_officer)
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    other = bu_client.post("/v4/auth/register", json={"email": "khac@shop.vn", "password": "BuoyUp@2026a",
                                                      "display_name": "Khác", "accept_terms": True}).json()
    h = {"Authorization": "Bearer " + other["token"]}
    assert bu_client.get(f"{p}/statement-images/{up.json()['id']}", headers=h).status_code in (403, 404)


def test_screenshots_that_do_not_show_the_typed_figures_earn_no_bonus(bu_client, as_seller, as_officer):
    app = _consented(bu_client, as_seller)
    p = f"/v4/applications/{app['id']}"
    lc.ok(bu_client.post(p + "/statement-images", headers=as_seller, json={"image": b64(BACK)}))
    months = sources.SCENARIOS["lan"][3]["revenue"]["monthly_12m"][-3:]
    statements = [{"month": m["month"], "revenue": m["amount"]} for m in months]  # match tax exactly
    lc.ok(bu_client.put(p + "/plan", headers=as_seller, json={**app["plan"]["suggested"], "statements": statements}))
    lc.ok(bu_client.post(p + "/verify", headers=as_seller, json={}))
    full = bu_client.get(p, headers=as_officer).json()
    tool = next(t for t in full["verification"]["tool_calls"] if t["tool"] == "check_statement_images")
    assert tool["output"]["supported"] is False
    assert any(f["code"] == "DATA_STATEMENT_UNUSED" for f in full["verification"]["flags"])


# --- my bank ---------------------------------------------------------------------------------------

@pytest.mark.product_v5
def test_my_bank(bu_client, as_seller):
    empty = lc.ok(bu_client.get("/v4/me/bank", headers=as_seller))
    assert empty["account"] is None and empty["loans"] == []
    loan = lc.loan_for(bu_client, as_seller)
    bank = lc.ok(bu_client.get("/v4/me/bank", headers=as_seller))
    assert bank["account"]["card"]["masked"].endswith("2345") and bank["account"]["balance"] == loan["amount"]
    assert bank["loans"][0]["id"] == loan["id"] and bank["totals"]["active_loans"] == 1
    assert any(m["kind"] == "loan" for m in bank["movements"])


# --- delete an application ("Hồ sơ của bạn") ------------------------------------------------------

def test_seller_deletes_an_unfinished_application(bu_client, as_seller, as_officer):
    from app.platform.db.session import session_scope
    from app.platform.tables import BuChainEntry
    from sqlalchemy import select

    app = _draft(bu_client, as_seller)
    listed = bu_client.get("/v4/applications", headers=as_seller).json()["items"]
    assert next(i for i in listed if i["id"] == app["id"])["deletable"] is True
    r = bu_client.delete(f"/v4/applications/{app['id']}", headers=as_seller)
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert app["id"] not in {i["id"] for i in bu_client.get("/v4/applications", headers=as_seller).json()["items"]}
    assert bu_client.get(f"/v4/applications/{app['id']}", headers=as_seller).status_code == 404
    assert bu_client.delete(f"/v4/applications/{app['id']}", headers=as_seller).status_code == 404
    staff = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    assert staff["status"] == "withdrawn"  # kept for audit, visible to staff
    with session_scope() as s:
        kinds = set(s.scalars(select(BuChainEntry.kind).where(BuChainEntry.case_id == app["id"])))
    assert "application_withdrawn" in kinds


def test_application_with_a_loan_cannot_be_deleted(bu_client, as_seller):
    loan = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    items = bu_client.get("/v4/applications", headers=as_seller).json()["items"]
    assert next(i for i in items if i["id"] == loan["application_id"])["deletable"] is False
    r = bu_client.delete(f"/v4/applications/{loan['application_id']}", headers=as_seller)
    assert r.status_code == 400


def test_escalated_application_leaves_the_officer_queue_when_deleted(bu_client, as_seller, as_officer):
    app = lc.start(bu_client, as_seller, "notes")
    assert app["status"] == "escalated"
    lc.ok(bu_client.delete(f"/v4/applications/{app['id']}", headers=as_seller))
    queue = bu_client.get("/v4/officer/queue", headers=as_officer).json()["items"]
    assert app["id"] not in {i["id"] for i in queue}


def test_partial_repayment_from_the_webank_balance(bu_client, as_seller):
    loan = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    before = loan["principal_outstanding"]
    out = lc.ok(bu_client.post(f"/v4/loans/{loan['id']}/prepay", headers=as_seller, json={"confirm": True, "amount": 10_000}))
    assert out["prepay"]["paid"] == 10_000 and out["principal_outstanding"] < before and out["status"] == "active"
    big = bu_client.post(f"/v4/loans/{loan['id']}/prepay", headers=as_seller, json={"confirm": True, "amount": 10_000_000})
    assert big.status_code == 400 and big.json()["error"]["details"]["balance"] < 10_000_000
