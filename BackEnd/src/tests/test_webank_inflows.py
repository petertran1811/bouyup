"""Money reaching the WeBank account (17/10/2026): the core-banking webhook and the demo settlement feed."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from app.platform.config import settings
from app.platform.db.session import session_scope
from tests import lc
from tests.conftest import login

ACCOUNT = lc.SIGN["webank_account"]


def _signed(client, body: dict, secret: str = "s3cret"):
    raw = json.dumps(body).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post("/v4/webank/inflows", content=raw,
                       headers={"Content-Type": "application/json", "X-WeBank-Signature": sig})


def test_signed_inflow_is_credited_once_and_shown_in_my_bank(bu_client, as_seller, monkeypatch):
    monkeypatch.setattr(settings, "webank_webhook_secret", "s3cret")
    loan = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    body = {"account_number": ACCOUNT, "amount": 12_340, "payout_id": "douyin:abc:1", "source": "Douyin"}
    first = _signed(bu_client, body)
    assert first.status_code == 200 and first.json()["credited"] is True
    again = _signed(bu_client, body)
    assert again.status_code == 200 and again.json()["balance"] == first.json()["balance"]  # idempotent
    bank = lc.ok(bu_client.get("/v4/me/bank", headers=as_seller))
    move = next(m for m in bank["movements"] if m["id"] == "douyin:abc:1")
    assert move["kind"] == "in" and move["amount"] == 12_340 and move["label"] == "Tiền hàng Douyin"
    assert bank["totals"]["month_in"] >= 12_340 and bank["loans"][0]["id"] == loan["id"]


def test_unsigned_or_wrong_role_is_refused(bu_client, as_seller, monkeypatch):
    monkeypatch.setattr(settings, "webank_webhook_secret", "s3cret")
    lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    body = {"account_number": ACCOUNT, "amount": 1000, "payout_id": "xx:1"}
    assert _signed(bu_client, body, secret="wrong").status_code == 401
    assert bu_client.post("/v4/webank/inflows", json=body, headers=as_seller).status_code == 401
    webank = login(bu_client, "webank@buoyup.vn")
    assert bu_client.post("/v4/webank/inflows", json=body, headers=webank).status_code == 200
    cmb = login(bu_client, "cmb@buoyup.vn")
    assert bu_client.post("/v4/webank/inflows", json={**body, "payout_id": "xx:2"}, headers=cmb).status_code == 401


def test_unknown_account_is_404(bu_client, monkeypatch):
    monkeypatch.setattr(settings, "webank_webhook_secret", "s3cret")
    assert _signed(bu_client, {"account_number": "999999", "amount": 1, "payout_id": "yy:1"}).status_code == 404


@pytest.mark.seed_loan
def test_settlement_feed_credits_one_day_of_sales(bu_client, as_seller, monkeypatch):
    """One payout per business day (18/10/2026; tests/test_stats_daily.py has the catch-up and the advance)."""
    from app.autopilot import settlement

    loan = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    with session_scope() as s:
        first = settlement.settle(s)
        again = settlement.settle(s)  # the day is settled already: nothing
    assert len(first) == 1 and first[0]["loan_id"] == loan["id"] and again == []
    assert first[0]["on"] == loan["clock"]
    bank = lc.ok(bu_client.get("/v4/me/bank", headers=as_seller))
    move = next(m for m in bank["movements"] if m["kind"] == "in")
    assert move["label"] == "Tiền hàng Douyin" and 0 < move["amount"] < 20_000
    assert move["id"] == f"douyin:{loan['id']}:{loan['clock']}" and move["on"] == loan["clock"]


@pytest.mark.seed_loan
def test_stats_replay_the_balance_and_the_month_bridge(bu_client, as_seller, monkeypatch):
    monkeypatch.setattr(settings, "webank_webhook_secret", "s3cret")
    loan = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    _signed(bu_client, {"account_number": ACCOUNT, "amount": 8_000, "payout_id": "douyin:st:1", "source": "Douyin"})
    lc.ok(bu_client.post(f"/v4/loans/{loan['id']}/prepay", headers=as_seller, json={"confirm": True, "amount": 5_000}))
    s = lc.ok(bu_client.get("/v4/me/stats", headers=as_seller))
    bank = lc.ok(bu_client.get("/v4/me/bank", headers=as_seller))
    assert len(s["revenue_12m"]) == 12 and s["schedule"] and s["loan_id"] == loan["id"]
    assert s["balance"][-1]["balance"] == bank["account"]["balance"]  # the replay ends at the real balance
    b = s["month_bridge"]
    assert b["opening"] + b["in"] - b["repay"] - b["out"] == b["closing"] == bank["account"]["balance"]
    # Revenue per item (18/10/2026): shares of the purchase invoices, largest first, splitting the 12-month revenue.
    g = s["goods"]
    assert g and g[0]["share"] >= g[-1]["share"] and 0.99 <= sum(r["share"] for r in g) <= 1.0001
    # 18/10/2026: the goods split the revenue of the same 12 months as the revenue chart
    total = sum(r["amount"] or 0 for r in s["revenue_12m"])  # items under 1% (packaging) are left out
    assert 0.99 * total <= sum(r["revenue_est"] for r in g) <= total + len(g)
