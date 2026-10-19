"""Seller services after the loan, phase A = P0 (SELLER_SERVICES_PLAN §3, 17/10/2026):
the notification centre, the confirmation before money leaves, expense groups, the WeBank outflow webhook."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from app.agents.notify import SELLER_ADDRESS
from app.core import cashflow
from app.platform.config import settings
from app.platform.db.session import session_scope
from app.platform.tables import BuLoan, BuSellerReport
from tests import lc
from tests.conftest import login

ACCOUNT = lc.SIGN["webank_account"]


def _signed(client, path: str, body: dict, secret: str = "s3cret"):
    raw = json.dumps(body).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post(path, content=raw, headers={"Content-Type": "application/json", "X-WeBank-Signature": sig})


def _notices(client, h) -> dict:
    return lc.ok(client.get("/v4/me/notices", headers=h))


# --- 3.1 notification centre ------------------------------------------------------------------

def test_notices_merge_loans_applications_and_reports_then_read(bu_client, as_seller):
    loan = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    with session_scope() as s:
        user_id = s.get(BuLoan, loan["id"]).seller_user_id
        s.add(BuSellerReport(id="srp_test1", seller_user_id=user_id, kind="month", period="2026-10",
                             data={"summary_line": "Tháng 10 bạn bán được khoảng 166.700 tệ."}))
    out = _notices(bu_client, as_seller)
    items = out["items"]
    assert {i["scope"] for i in items} == {"loan", "application", "report"}
    kinds = {i["kind"] for i in items}
    assert {"decision", "limit_approved", "disbursed", "month"} <= kinds, kinds
    assert out["unread"] == len(items) and all(i["read_at"] is None for i in items)
    assert [i["at"] for i in items] == sorted((i["at"] for i in items), reverse=True)
    for i in items:
        assert i["title"] and i["text"] and i["level"] in ("info", "warn", "danger")
    limit = next(i for i in items if i["kind"] == "limit_approved")
    assert limit["action"] == {"view": "apply", "id": loan["application_id"]} and "hạn mức" in limit["text"]
    report = next(i for i in items if i["scope"] == "report")
    assert report["action"] == {"view": "report", "id": "srp_test1"} and "166.700" in report["text"]
    disbursed = next(i for i in items if i["kind"] == "disbursed")
    assert disbursed["action"] == {"view": "loan", "id": loan["id"]}
    # New sentences call the seller "bạn" (notify.SELLER_ADDRESS), never "chị".
    assert SELLER_ADDRESS == "bạn" and not any("chị" in i["text"].lower().split() for i in items)

    picked = [disbursed["id"], limit["id"], report["id"]]
    after = lc.ok(bu_client.post("/v4/me/notices/read", headers=as_seller, json={"ids": picked}))
    assert after["unread"] == out["unread"] - 3
    again = {i["id"]: i for i in _notices(bu_client, as_seller)["items"]}
    assert all(again[x]["read_at"] for x in picked)
    assert lc.ok(bu_client.post("/v4/me/notices/read", headers=as_seller, json={"all": True}))["unread"] == 0
    # Reading is not an update of the case: the loan view still lists the notice, now with read_at kept in the doc.
    with session_scope() as s:
        assert all(n.get("read_at") for n in s.get(BuLoan, loan["id"]).doc["notices"])


def test_notices_are_for_sellers_only(bu_client, as_seller, as_officer):
    lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    assert bu_client.get("/v4/me/notices", headers=as_officer).status_code == 403
    assert bu_client.post("/v4/me/notices/read", headers=as_officer, json={"all": True}).status_code == 403


def test_data_request_reaches_the_seller(bu_client, as_seller):
    app = lc.offered(bu_client, as_seller)
    bu_client.post(f"/v4/applications/{app['id']}/messages", headers=as_seller,
                   json={"text": "Em có hóa đơn mới với nhà cung cấp, gửi thế nào?"})
    items = _notices(bu_client, as_seller)["items"]
    req = next(i for i in items if i["kind"] == "data_request")
    assert req["scope"] == "application" and req["title"] == "Cần bổ sung chứng từ"
    assert req["action"]["view"] == "apply" and req["action"]["id"] == app["id"]
    assert "hóa đơn" in req["text"] and "bạn" in req["text"]
    # The same open request is reused: no second notice.
    bu_client.post(f"/v4/applications/{app['id']}/messages", headers=as_seller,
                   json={"text": "Em gửi thêm chứng từ hóa đơn nữa"})
    assert sum(1 for i in _notices(bu_client, as_seller)["items"] if i["kind"] == "data_request") == 1


def test_escalation_decision_is_a_notice(bu_client, as_seller):
    app = lc.answer_all(bu_client, as_seller, lc.start(bu_client, as_seller, "notes"))
    assert app["status"] == "escalated", app["status"]
    decision = next(i for i in _notices(bu_client, as_seller)["items"] if i["kind"] == "decision")
    assert decision["level"] == "warn" and "cán bộ" in decision["text"]


# --- 3.2 confirmation before money leaves --------------------------------------------------------

def test_minimum_and_prepay_need_confirmation(bu_client, as_seller):
    loan = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    url = f"/v4/loans/{loan['id']}"
    for path, body in (("/minimum", None), ("/minimum", {"confirm": False}), ("/prepay", None),
                       ("/prepay", {"amount": 1_000}), ("/prepay", {"confirm": False, "amount": 1_000})):
        r = bu_client.post(url + path, headers=as_seller, **({"json": body} if body is not None else {}))
        assert r.status_code == 400 and r.json()["error"]["code"] == "CONFIRM_REQUIRED", (path, body, r.text)
    after = lc.ok(bu_client.get(url, headers=as_seller))
    assert after["account"]["balance"] == loan["account"]["balance"] and not after["repayments"]
    assert after["schedule"][0]["choice"] is None
    # A face check that was never done is refused.
    bad = bu_client.post(url + "/prepay", headers=as_seller,
                         json={"confirm": True, "method": "face", "face_verify_id": "nope", "amount": 1_000})
    assert bad.status_code == 400 and bad.json()["error"]["details"]["field"] == "face_verify_id"
    lc.ok(bu_client.post(url + "/minimum", headers=as_seller, json={"confirm": True, "method": "otp"}))
    out = lc.ok(bu_client.post(url + "/prepay", headers=as_seller, json={"confirm": True, "method": "otp", "amount": 1_000}))
    assert out["prepay"]["paid"] == 1_000 and out["schedule"][0]["choice"] == "minimum"


# --- 3.3 expense groups, outflows ----------------------------------------------------------------

@pytest.mark.parametrize("transfer, group", [
    ({"kind": "supplier"}, "goods"),
    ({"kind": "other", "memo": "Nhập hàng xưởng may Quảng Châu"}, "goods"),
    ({"kind": "other", "memo": "货款", "payee": {"kind": "company", "name": "广州服装厂"}}, "goods"),
    ({"kind": "other", "memo": "Thanh toán", "payee": {"kind": "supplier", "name": "Xưởng A"}}, "goods"),
    ({"kind": "other", "memo": "Phí sàn tháng 10"}, "platform"),
    ({"kind": "other", "memo": "平台佣金"}, "platform"),
    ({"kind": "other", "memo": "Quảng cáo Douyin", "payee": {"name": "巨量引擎"}}, "marketing"),
    ({"kind": "other", "memo": "Facebook ads"}, "marketing"),
    ({"kind": "other", "memo": "快递费 10月"}, "logistics"),
    ({"kind": "other", "memo": "Thuê kho tháng 10"}, "logistics"),
    ({"kind": "other", "memo": "Lương cộng tác viên", "payee": {"kind": "individual", "name": "Trần Mỹ"}}, "staff"),
    ({"kind": "other", "memo": "工资"}, "staff"),
    ({"kind": "other", "memo": "Nộp thuế khoán quý 3"}, "tax"),
    ({"kind": "staff"}, "staff"),
    ({"kind": "marketing"}, "marketing"),
    ({"kind": "other", "memo": "Chuyển khoản"}, "other"),
    ({"kind": "other", "memo": "Khoản thanh toán chung"}, "other"),  # "khoản" is not "kho"
    ({"kind": "other", "memo": "Trả góp", "payee": {"kind": "bank"}}, None),
    ({"kind": "personal"}, None),
    ({"kind": "securities"}, None),
    ({"kind": "real_estate"}, None),
    ({"group": "tax", "kind": "supplier"}, "tax"),
])
def test_classify_into_six_groups(transfer, group):
    assert cashflow.classify(transfer) == group
    assert cashflow.EXPENSE_GROUPS == ("goods", "platform", "marketing", "logistics", "staff", "tax")
    assert set(cashflow.GROUP_LABELS) == {*cashflow.EXPENSE_GROUPS, "other"}


def test_month_summary_estimates_the_platform_fee():
    doc = {"account": {"inflows": [{"on": "2026-10-03", "amount": 9_500}, {"on": "2026-09-30", "amount": 999}],
                       "transfers": [{"on": "2026-10-04", "amount": 3_000, "kind": "supplier"},
                                     {"on": "2026-10-05", "amount": 1_000, "kind": "other", "memo": "Lương"},
                                     {"on": "2026-10-06", "amount": 2_000, "kind": "personal"}]}}
    out = cashflow.month_summary([doc], [{"at": "2026-10-10T00:00:00", "swept": 700}], "2026-10")
    by = {g["key"]: g["amount"] for g in out["groups"]}
    assert out["inflow"] == 9_500 and out["platform_fee"] == 500 and out["platform_fee_estimated"]
    assert by == {"goods": 3_000, "platform": 500, "marketing": 0, "logistics": 0, "staff": 1_000, "tax": 0}
    assert out["non_business"] == 2_000 and out["repay"] == 700 and out["expenses"] == 4_500


def test_simulated_transfer_kinds_old_and_new(bu_client, as_seller):
    loan = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    url = f"/v4/loans/{loan['id']}/simulate-transfer"
    old = lc.ok(bu_client.post(url, headers=as_seller, json={"amount": 1_000, "kind": "supplier"}))
    new = lc.ok(bu_client.post(url, headers=as_seller, json={"amount": 500, "kind": "staff"}))
    assert old["transfer"]["group"] == "goods" and new["transfer"]["group"] == "staff"
    assert new["account"]["balance"] == loan["account"]["balance"] - 1_500
    assert bu_client.post(url, headers=as_seller, json={"amount": 1, "kind": "casino"}).status_code in (400, 422)


def test_webank_outflow_is_signed_grouped_and_idempotent(bu_client, as_seller, monkeypatch):
    monkeypatch.setattr(settings, "webank_webhook_secret", "s3cret")
    loan = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    body = {"account_number": ACCOUNT, "amount": 4_200, "transfer_id": "wb-out-0001",
            "payee": {"kind": "platform", "name": "巨量引擎"}, "memo": "Quảng cáo Douyin tháng 10"}
    first = _signed(bu_client, "/v4/webank/outflows", body)
    assert first.status_code == 200, first.text
    assert first.json()["recorded"] is True and first.json()["transfer"]["group"] == "marketing"
    assert first.json()["balance"] == loan["account"]["balance"] - 4_200
    again = _signed(bu_client, "/v4/webank/outflows", body)
    assert again.status_code == 200 and again.json()["recorded"] is False
    assert again.json()["balance"] == first.json()["balance"]  # never counted twice
    # Refused without WeBank's signature (or a WeBank bank user).
    assert _signed(bu_client, "/v4/webank/outflows", {**body, "transfer_id": "wb-out-2"}, "wrong").status_code == 401
    assert bu_client.post("/v4/webank/outflows", json={**body, "transfer_id": "wb-out-3"}, headers=as_seller).status_code == 401
    webank = login(bu_client, "webank@buoyup.vn")
    assert bu_client.post("/v4/webank/outflows", headers=webank,
                          json={**body, "transfer_id": "wb-out-4", "amount": 100, "memo": "快递费",
                                "payee": {"kind": "company", "name": "顺丰"}}).status_code == 200
    assert _signed(bu_client, "/v4/webank/outflows", {**body, "account_number": "999999"}).status_code == 404
    assert _signed(bu_client, "/v4/webank/outflows",
                   {**body, "transfer_id": "wb-out-5", "amount": 10_000_000}).status_code == 400
    bank = lc.ok(bu_client.get("/v4/me/bank", headers=as_seller))
    moves = {m["id"]: m for m in bank["movements"]}
    assert moves["wb-out-0001"]["kind"] == "out" and moves["wb-out-0001"]["amount"] == -4_200
    assert moves["wb-out-0001"]["group"] == "marketing" and moves["wb-out-4"]["group"] == "logistics"
    with session_scope() as s:  # only the mirrored balance moved: no repayment, no payout
        doc = s.get(BuLoan, loan["id"]).doc
        assert doc["account"]["balance"] == loan["account"]["balance"] - 4_300
        assert doc["transfer_ids"].count("wb-out-0001") == 1


@pytest.mark.seed_loan
def test_demo_spending_feed_records_grouped_expenses(bu_client, as_seller, monkeypatch):
    """By business day since 18/10/2026: twelve days moved with the feed on, 0–2 expenses a day."""
    from datetime import date, timedelta

    monkeypatch.setattr(settings, "platform_payout_feed", True)
    loan = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    start = date.fromisoformat(loan["clock"])
    lc.advance(bu_client, as_seller, loan, (start + timedelta(days=12)).isoformat())
    with session_scope() as s:
        acc = s.get(BuLoan, loan["id"]).doc["account"]
    spent = [t for t in acc["transfers"] if t["id"].startswith("spend:")]
    assert spent, "the feed spends something over twelve days"
    assert all(t["group"] == "staff" for t in spent)  # the Lan statement: salaries (repayments skipped)
    for m in {t["on"][:7] for t in spent}:
        month_in = sum(i["amount"] for i in acc["inflows"] if i["on"][:7] == m)
        month_out = sum(t["amount"] for t in acc["transfers"] if t["on"][:7] == m)
        assert month_out <= 0.70 * month_in
    assert len({t["id"] for t in acc["transfers"]}) == len(acc["transfers"])
