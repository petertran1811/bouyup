"""Bank catalog from the BuoyUp Chain service (chain_sync) and the capped B12 split."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.blockchain import chain_remote
from app.blockchain import chain_sync
from app.banks.split import eligible_banks, propose_split, seller_terms, validate_split
from app.blockchain.chain_remote import RemoteChain
from app.platform.tables import BuBank, BuChainEntry, BuChainKey
from app.platform.config import settings
from app.platform.db.session import session_scope
from tests import lc
from tests.test_chain_remote import FakeChain

# The service's numbers (minor unit: fen), as published at fs.buoyup.app on 2026-10-14.
LIMITS = {
    "WEBANK": dict(minWithdrawal=50_000, maxSharePercent=100, maxLoanAmount=50_000_000, minAnnualRatePercent=8,
                   maxAnnualRatePercent=15, maxTenorDays=180, minStoreAgeMonths=12, minStoreRating=4, feePercent=0.1),
    "CMB": dict(minWithdrawal=100_000, maxSharePercent=50, maxLoanAmount=60_000_000, minAnnualRatePercent=5.5,
                maxAnnualRatePercent=12, maxTenorDays=180, minStoreAgeMonths=24, minStoreRating=4.7, feePercent=0.12),
    "ICBC": dict(minWithdrawal=500_000, maxSharePercent=60, maxLoanAmount=100_000_000, minAnnualRatePercent=4.5,
                 maxAnnualRatePercent=10, maxTenorDays=365, minStoreAgeMonths=36, minStoreRating=4.6, feePercent=0.08),
    "BOC": dict(minWithdrawal=200_000, maxSharePercent=70, maxLoanAmount=100_000_000, minAnnualRatePercent=4.5,
                maxAnnualRatePercent=11, maxTenorDays=180, minStoreAgeMonths=18, minStoreRating=4.4, feePercent=0.1),
    "CCB": dict(minWithdrawal=100_000, maxSharePercent=70, maxLoanAmount=80_000_000, minAnnualRatePercent=5,
                maxAnnualRatePercent=12, maxTenorDays=120, minStoreAgeMonths=12, minStoreRating=4.5, feePercent=0.1),
}
CREDIT_LINE = {"WEBANK": 5_000_000_000, "CMB": 4_000_000_000, "ICBC": 8_000_000_000, "BOC": 8_000_000_000,
               "CCB": 6_000_000_000}
PUB = {code: f"{i + 1:02x}" * 32 for i, code in enumerate(LIMITS)}
PRIV = {code: f"{i + 0x41:02x}" * 32 for i, code in enumerate(LIMITS)}


class CatalogChain(FakeChain):
    def __init__(self) -> None:
        super().__init__()
        self.policy_version = "2026.10-1"
        self.show_keys = True

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path == "/v1/banks":
            return httpx.Response(200, json={"banks": [{"code": c, "region": "CN", "active": True} for c in LIMITS]})
        if request.method == "GET" and path.startswith("/v1/banks/"):
            code = path.rsplit("/", 1)[1]
            return httpx.Response(200, json={
                "code": code, "region": "CN", "currency": "CNY", "active": True, "contractStatus": "active",
                "limits": LIMITS[code],
                "policy": {"version": self.policy_version, "hash": "0x" + code.encode().hex().ljust(64, "0"),
                           "summary": f"{code} funds e-commerce sellers.", "redFlags": ["Rapid price cuts."],
                           "dealBreakers": ["Counterfeit goods."], "escalateWhen": ["Brand ownership is unclear."]},
                "contract": {"contractNo": f"BU-{code}-2026-01", "creditLine": CREDIT_LINE[code], "hash": "0x" + "c" * 64},
                "encryptionKey": {"publicKey": PUB[code], "activeFrom": "2026-10-10T22:30:14Z"},
                "disclaimer": "Demo data.",
            })
        if request.method == "GET" and path == "/v1/overview":
            secrets = [{"name": "BuoyUp master key", "publicKey": "ee" * 32, "privateKey": "ff" * 32}]
            secrets += [{"name": f"{c} encryption key", "publicKey": PUB[c], "privateKey": PRIV[c]} for c in LIMITS]
            return httpx.Response(200, json={"demoKeysShown": self.show_keys, "secrets": secrets})
        if request.method == "POST" and path == "/explorer/api/decrypt":
            # WeBank's key opens the summary and WeBank's own piece of the last withdrawal.
            sent = list(self.withdrawals.values())[-1]["request"]
            pct = sent["bankSplit"]["WEBANK"]
            return httpx.Response(200, json={"rootMatchesCommitments": True, "readable": [
                {"index": 0, "kind": "summary", "content": {"amount": sent["amount"], "currency": "CNY"},
                 "commitment": "0x" + "22" * 32, "commitmentMatches": True},
                {"index": 1, "kind": "bank_share", "content": {
                    "bank": "WEBANK", "percent": pct, "amount": round(sent["amount"] * pct / 100), "currency": "CNY",
                    "contractNo": "BU-WEBANK-2026-01"},
                 "commitment": "0x" + "22" * 32, "commitmentMatches": True}]})
        return super().handler(request)


@pytest.fixture()
def catalog_chain(monkeypatch, bu_client):
    fake = CatalogChain()
    monkeypatch.setattr(settings, "buoyup_chain_backend", "remote")
    chain_remote.set_remote(RemoteChain("http://chain.test", "tok", transport=httpx.MockTransport(fake.handler)))
    yield fake
    chain_remote.set_remote(None)


def _policy_entries() -> int:
    with session_scope() as s:
        return len(list(s.scalars(select(BuChainEntry).where(BuChainEntry.kind == "bank_policy"))))


def _sync() -> dict:
    with session_scope() as s:
        return chain_sync.sync_catalog(s)


def test_sync_maps_limits_policy_contract_and_keys(catalog_chain):
    out = _sync()
    assert out["ok"] and out["banks"] == 5 and out["keys"] == 5 and out["chain_tx"]
    with session_scope() as s:
        cmb = s.get(BuBank, "CMB")
        p = cmb.policy
        assert (p["max_share"], p["max_share_amount"], p["min_share_amount"]) == (0.5, 600_000, 1_000)
        assert (p["min_rate"], p["max_rate"], p["max_tenor_days"]) == (0.055, 0.12, 180)
        assert (p["min_store_rating"], p["min_store_age_months"]) == (4.7, 24)
        assert p["min_grade"] == "C" and p["min_share"] == 0.30  # BuoyUp's own rules stay
        assert p["chain"]["red_flags"] == ["Rapid price cuts."] and p["chain"]["version"] == "2026.10-1"
        assert cmb.limit_total == 40_000_000 and cmb.contract_id == "BU-CMB-2026-01"
        key = s.get(BuChainKey, "WEBANK")
        assert key.public_key == PUB["WEBANK"] and key.private_key_demo == PRIV["WEBANK"]
        assert s.get(BuChainKey, "MASTER").private_key_demo == "ff" * 32
        assert s.get(BuBank, "WEBANK").public_key != PUB["WEBANK"]  # local records keep the local key
        assert s.get(BuBank, "VCB").active is False  # not in this (CN-only) fake catalog
    # Nothing changed: no second chain entry. A new policy version: one more.
    before = _policy_entries()
    assert _sync()["chain_tx"] is None and _policy_entries() == before
    catalog_chain.policy_version = "2026.11-1"
    assert _sync()["chain_tx"] and _policy_entries() == before + 1


def test_hidden_demo_keys_are_not_stored(catalog_chain):
    catalog_chain.show_keys = False
    _sync()
    with session_scope() as s:
        assert s.get(BuChainKey, "WEBANK").private_key_demo == ""
        assert s.get(BuChainKey, "MASTER") is None


def test_capped_split_for_one_million(catalog_chain):
    """WeBank may fund at most 500.000 of one loan: 1.000.000 over WeBank + CCB is 50/50, not 70/30."""
    _sync()
    with session_scope() as s:
        seller = {"rating": 4.8, "store_age_months": 40, "tenor_days": 120}
        rows = eligible_banks(s, region="CN", tier=2, grade="C", amount=1_000_000, category="thời trang",
                              rate=0.12, seller=seller)
        ok = {r["bank"] for r in rows if r["eligible"]}
        assert ok == {"WEBANK", "CMB", "CCB"}  # ICBC: 12% above its 10% ceiling; BOC: grade B and up
        split = propose_split(s, eligible=rows, amount=1_000_000, accounts=[{"bank": "WeBank"}])
        assert [(x["bank"], x["pct"], x["amount"]) for x in split] == [
            ("WEBANK", 0.4, 400_000), ("CCB", 0.3, 300_000), ("CMB", 0.3, 300_000)]
        only = [r for r in rows if r["bank"] in ("WEBANK", "CCB")]
        split = propose_split(s, eligible=only, amount=1_000_000, accounts=[{"bank": "WeBank"}])
        assert [(x["bank"], x["pct"]) for x in split] == [("WEBANK", 0.5), ("CCB", 0.5)]
        assert validate_split(s, region="CN", amount=1_000_000, shares=split) == []
        bad = [{"bank": "WEBANK", "pct": 0.7, "amount": 700_000}, {"bank": "CCB", "pct": 0.3, "amount": 300_000}]
        assert any("vượt mức 500.000" in p for p in validate_split(s, region="CN", amount=1_000_000, shares=bad))
        alone = [r for r in rows if r["bank"] == "WEBANK"]
        assert propose_split(s, eligible=alone, amount=1_000_000) == []  # 500.000 cap < 1.000.000


def test_store_and_tenor_rules_give_reasons(catalog_chain):
    _sync()
    with session_scope() as s:
        rows = {r["bank"]: r for r in eligible_banks(
            s, region="CN", tier=2, grade="C", amount=300_000, category="thời trang", rate=0.12,
            seller={"rating": 4.6, "store_age_months": 26, "tenor_days": 143})}
    assert rows["WEBANK"]["eligible"] and rows["WEBANK"]["policy_version"] == "2026.10-1"
    assert "4,7" in rows["CMB"]["reason"] and "4,6" in rows["CMB"]["reason"]
    assert "vượt trần 10%" in rows["ICBC"]["reason"]
    assert "143 ngày" in rows["CCB"]["reason"]


def test_lan_end_to_end_on_the_chain_catalog(bu_client, as_seller, as_webank, as_officer, catalog_chain):
    _sync()
    app = lc.offered(bu_client, as_seller)
    with session_scope() as s:
        from app.platform.tables import BuApplication

        terms = seller_terms(s.get(BuApplication, app["id"]).doc)
    assert terms["rating"] == 4.6 and terms["store_age_months"] >= 26 and terms["tenor_days"] == 360  # 12 months
    split = {x["bank"]: x["pct"] for x in app["syndicate"]["split"]}
    app = lc.select(bu_client, as_seller, app)
    lc.contract(bu_client, as_seller, app)
    app = lc.ok(lc.sign(bu_client, as_seller, app))
    assert app["status"] == "disbursed", app
    sent = catalog_chain.withdrawals[f"disburse:{app['id']}"]["request"]
    assert sent["amount"] == 20_000_000 and sent["bankSplit"] == {b: p * 100 for b, p in split.items()}
    assert sent["actor"]["agentId"] == "agent-4" and sent["actor"]["runId"] == f"disburse:{app['id']}"
    items = bu_client.get("/v4/bank/withdrawals", headers=as_webank).json()["items"]
    mine = items[0]["my_piece"]
    # WeBank leads every loan; its piece carries the contract number from the chain catalog.
    assert mine == {"pct": split["WEBANK"], "amount": round(200_000 * split["WEBANK"]),
                    "contract_id": "BU-WEBANK-2026-01"} and not items[0]["locked"]


def test_partner_banks_apply_their_chain_catalog_rules(bu_client, as_seller, as_officer, catalog_chain):
    _sync()
    app = lc.answer_all(bu_client, as_seller, lc.start(bu_client, as_seller))
    full = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    first = {r["bank"]: r for r in full["syndicate"]["rounds"][0]["responses"]}
    assert first["CMB"]["decision"] != "approve" and "4,7" in first["CMB"]["reason"]  # Lan's store: 4.6
    assert first["ICBC"]["decision"] != "approve"  # store 26 months old, ICBC needs 36


def test_sync_endpoint_is_admin_and_remote_only(bu_client, as_admin, as_officer, monkeypatch):
    assert bu_client.post("/v4/chain/sync", headers=as_officer).status_code == 403
    assert bu_client.post("/v4/chain/sync", headers=as_admin).status_code == 400  # local mode


def test_rule_removed_upstream_stops_applying_and_bad_data_changes_nothing(catalog_chain):
    _sync()
    del LIMITS["CMB"]["minStoreRating"]
    try:
        _sync()
        with session_scope() as s:
            assert "min_store_rating" not in s.get(BuBank, "CMB").policy
            assert s.get(BuBank, "CMB").policy["max_share"] == 0.5
        LIMITS["CMB"]["maxSharePercent"] = "lots"  # malformed: the whole sync is refused
        with pytest.raises(chain_remote.ChainUnavailable):
            _sync()
        with session_scope() as s:
            assert s.get(BuBank, "CMB").policy["max_share"] == 0.5
    finally:
        LIMITS["CMB"].update(minStoreRating=4.7, maxSharePercent=50)


def test_a_change_of_limits_alone_is_recorded_on_chain(catalog_chain):
    _sync()
    before = _policy_entries()
    LIMITS["WEBANK"]["maxLoanAmount"] = 40_000_000
    try:
        assert _sync()["chain_tx"] and _policy_entries() == before + 1
    finally:
        LIMITS["WEBANK"]["maxLoanAmount"] = 50_000_000


def test_chain_owned_fields_cannot_be_edited_locally(bu_client, as_admin, catalog_chain):
    _sync()
    r = bu_client.put("/v4/banks/WEBANK/policy", headers=as_admin, json={"max_rate": 0.2})
    assert r.status_code == 400 and r.json()["error"]["details"]["fields"] == ["max_rate"]
    assert bu_client.put("/v4/banks/WEBANK/policy", headers=as_admin, json={"min_grade": "B"}).status_code == 200


def test_min_share_amount_raises_a_floor_instead_of_dropping_the_bank(catalog_chain):
    """15.000 over WeBank + ICBC: ICBC's 30% (4.500) is under its 5.000 minimum, so its floor rises to 33,34%."""
    _sync()
    with session_scope() as s:
        rows = [{"bank": "WEBANK", "eligible": True}, {"bank": "ICBC", "eligible": True}]
        split = propose_split(s, eligible=rows, amount=15_000, accounts=[{"bank": "WeBank"}])
    assert [(x["bank"], x["amount"]) for x in split] == [("WEBANK", 9_999), ("ICBC", 5_001)]


def test_chain_legs_that_differ_from_loan_shares_are_flagged(catalog_chain):
    from app.blockchain import withdrawals

    _sync()
    with session_scope() as s:
        row = withdrawals.create_withdrawal(
            s, request_id="t-legs", amount=1_001, currency="CNY", region="CN", province="CN-GD", user="u",
            account="a", payout_ref="p", requester="agent4",
            shares=[{"bank": "WEBANK", "pct": 0.3333, "amount": 334, "contract_id": "c"},
                    {"bank": "CCB", "pct": 0.6667, "amount": 667, "contract_id": "c"}])
        assert row.envelope["legs_mismatch"]["buoyup_minor"] == {"WEBANK": 33_400, "CCB": 66_700}
