"""Multi-bank tenant isolation (cross-bank IDOR).

One partner bank must never read, modify, or sign for another bank's catalog entry,
policy, encryption key, portfolio, withdrawals, or approval packet. The platform
MASTER key row must never be exposed through the bank catalog.

Scoring: PASS == isolation held (403 / 404 / empty). FAIL == bank A reached bank B.
"""
from __future__ import annotations

import pytest

from conftest import DEMO, login

# Real pipeline helpers from the backend's own suite (BackEnd/src/tests, on sys.path).
from tests.test_pipeline_flow import offered
from tests.test_agent4_duties import set_param


@pytest.mark.easy
def test_api_e3_bank_cannot_read_other_banks_detail(bu_client):
    """API-E3: WeBank cannot read CMB's full catalog entry, and MASTER stays hidden."""
    webank = login(bu_client, DEMO["webank"])
    # Its own entry is visible...
    assert bu_client.get("/v4/banks/WEBANK", headers=webank).status_code == 200
    # ...another bank's detail is forbidden...
    assert bu_client.get("/v4/banks/CMB", headers=webank).status_code == 403
    assert bu_client.get("/v4/banks/ICBC", headers=webank).status_code == 403
    # ...and the platform master key row is never a readable bank (admin included).
    admin = login(bu_client, DEMO["admin"])
    assert bu_client.get("/v4/banks/MASTER", headers=webank).status_code in (403, 404)
    assert bu_client.get("/v4/banks/MASTER", headers=admin).status_code == 404
    codes = {b["code"] for b in bu_client.get("/v4/banks", headers=webank).json()["items"]}
    assert "MASTER" not in codes
    # The reduced list view must not leak another bank's amounts/limits to WeBank.
    view = {b["code"]: b for b in bu_client.get("/v4/banks", headers=webank).json()["items"]}
    assert "limit_used" in view["WEBANK"] and "limit_used" not in view["CMB"]


@pytest.mark.medium
def test_api_m3_bank_cannot_write_other_banks_policy_or_key(bu_client):
    """API-M3: WeBank cannot edit CMB's policy or rotate CMB's public key; CMB is untouched."""
    webank = login(bu_client, DEMO["webank"])
    admin = login(bu_client, DEMO["admin"])
    before = bu_client.get("/v4/banks/CMB", headers=admin).json()
    # Cross-bank policy write and key rotation are forbidden.
    assert bu_client.put("/v4/banks/CMB/policy", json={"max_rate": 0.2}, headers=webank).status_code == 403
    assert bu_client.put("/v4/banks/CMB/policy", json={"min_grade": "E"}, headers=webank).status_code == 403
    rotate = "11" * 32  # 64 hex chars (shape-valid X25519 key)
    assert bu_client.put("/v4/banks/CMB/public-key", json={"public_key": rotate},
                         headers=webank).status_code == 403
    # CMB's policy and key are unchanged after the blocked attempts.
    after = bu_client.get("/v4/banks/CMB", headers=admin).json()
    assert after["policy"] == before["policy"]
    assert after["public_key"] == before["public_key"]


@pytest.mark.medium
def test_api_m4_bank_portfolio_is_tenant_scoped(bu_client):
    """API-M4: a bank's portfolio/withdrawals show only its own share, never another bank's."""
    seller = login(bu_client, DEMO["seller"])
    app = offered(bu_client, seller)
    done = bu_client.post(f"/v4/applications/{app['id']}/accept", headers=seller,
                          json={"option_id": "full"}).json()
    assert done["status"] == "disbursed", done["status"]

    webank = login(bu_client, DEMO["webank"])
    vcb = login(bu_client, "vcb@buoyup.vn")  # a bank that funded nothing here

    wshares = bu_client.get("/v4/bank/portfolio", headers=webank).json()["shares"]
    assert wshares and all("amount" in s for s in wshares)
    wds = bu_client.get("/v4/bank/withdrawals", headers=webank).json()["items"]
    # WeBank sees only its own slice; CMB's share amount (41970) must not leak into its view.
    assert wds and all(w.get("my_piece") for w in wds)
    assert "41970" not in str(wds)

    # VCB funded nothing: it must see an empty portfolio and no withdrawals.
    assert bu_client.get("/v4/bank/portfolio", headers=vcb).json()["shares"] == []
    assert bu_client.get("/v4/bank/withdrawals", headers=vcb).json()["items"] == []


@pytest.mark.hard
def test_api_h2_bank_cannot_sign_another_banks_approval(bu_client):
    """API-H2: with sign-off on, CMB cannot sign WeBank's approval packet (cross-bank IDOR)."""
    set_param(["banks", "require_signoff"], True)
    seller = login(bu_client, DEMO["seller"])
    app = offered(bu_client, seller)
    approved = bu_client.post(f"/v4/applications/{app['id']}/accept", headers=seller,
                              json={"option_id": "full"}).json()
    assert approved["status"] == "approved", approved["status"]

    webank = login(bu_client, DEMO["webank"])
    cmb = login(bu_client, DEMO["cmb"])
    pending = bu_client.get("/v4/bank/approvals?status=pending", headers=webank).json()["items"]
    webank_item = next(i for i in pending if i["application_id"] == app["id"])

    # CMB tries to sign the approval that belongs to WeBank's share -> must be 404.
    r = bu_client.post(f"/v4/bank/approvals/{webank_item['id']}/sign", headers=cmb,
                       json={"decision": "sign"})
    assert r.status_code == 404, f"CMB signed WeBank's packet: {r.status_code} {r.text}"
    # A fabricated approval id is likewise rejected, not 500.
    assert bu_client.post("/v4/bank/approvals/ba_deadbeef/sign", headers=cmb,
                          json={"decision": "sign"}).status_code == 404

    # WeBank's own approval is still pending (CMB's attempt changed nothing).
    still = bu_client.get("/v4/bank/approvals?status=pending", headers=webank).json()["items"]
    assert any(i["id"] == webank_item["id"] for i in still)
