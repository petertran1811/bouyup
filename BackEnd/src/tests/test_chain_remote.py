"""T1: remote BuoyUp Chain adapter (httpx.MockTransport stands in for fs.buoyup.app)."""

from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from app.blockchain import chain_remote
from app.blockchain import withdrawals
from app.blockchain.chain_remote import ChainUnavailable, RemoteChain
from app.platform.tables import BuApplication, BuChainEntry, BuChainOutbox, BuLoan, BuWithdrawal
from app.data_sources import sources
from app.platform.config import settings
from app.platform.db.session import session_scope
from tests import lc


def _sign(client, h, app: dict) -> dict:
    """Stage 3–4 with the suggested amount: select, open the contract, sign (Agent 4 pays out)."""
    app = lc.select(client, h, app)
    lc.contract(client, h, app)
    return lc.ok(lc.sign(client, h, app))


def _consented(client, h) -> dict:
    """Lan up to the plan, ready for ``/verify`` (Agents 1–3 and the banks)."""
    app = lc.ok(client.post("/v4/applications", headers=h, json={
        "tier": 2, "borrower_type": "individual_business", "store_urls": [sources.demo_url("lan")]}))
    lc.ok(client.post(f"/v4/applications/{app['id']}/identity", headers=h, json={"cccd": True, "face": True}))
    app = lc.ok(client.post(f"/v4/applications/{app['id']}/consent", headers=h, json={"scopes": lc.BOXES}))
    return lc.ok(client.put(f"/v4/applications/{app['id']}/plan", headers=h, json=app["plan"]["suggested"]))


class FakeChain:
    """Minimal BuoyUp Chain service: anchors, withdrawals (idempotent by requestId), status."""

    def __init__(self) -> None:
        self.anchors: list[dict] = []
        self.withdrawals: dict[str, dict] = {}
        self.payouts = 0
        self.fail_anchor_kinds: set[str] = set()
        self.fail_withdrawals = False
        self.requests: list[tuple[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        assert request.headers.get("authorization") == "Bearer tok"
        path = request.url.path
        if request.method == "POST" and path == "/v1/audit/anchors":
            body = json.loads(request.content)
            if body["kind"] in self.fail_anchor_kinds:
                return httpx.Response(502, json={"error": {"kind": "chain", "message": "node down"}})
            self.anchors.append(body)
            n = len(self.anchors)
            return httpx.Response(201, json={"subject": body["subject"], "index": n, "kind": body["kind"],
                                             "contentHash": body["contentHash"], "head": "0x" + "ab" * 32,
                                             "tx": {"txHash": f"0x{n:064x}", "blockNumber": 100 + n}})
        if request.method == "POST" and path == "/v1/withdrawals":
            if self.fail_withdrawals:
                return httpx.Response(502, json={"error": {"kind": "payout_failed", "message": "treasury down"}})
            body = json.loads(request.content)
            existing = self.withdrawals.get(body["requestId"])
            if existing is not None:
                return httpx.Response(200, json={**existing, "replayed": True})
            self.payouts += 1
            wid = f"WD-REMOTE{self.payouts:08d}"
            record = {
                "withdrawalId": wid, "status": "paid_out", "amount": body["amount"], "currency": body["currency"],
                "region": body["region"], "province": body["province"], "request": body,
                "legs": [{"bank": b, "percent": p, "amount": body["amount"] * p // 100} for b, p in body["bankSplit"].items()],
                "onChain": {"withdrawalId": wid, "root": "0x" + "11" * 32, "commitments": ["0x" + "22" * 32] * 4,
                            "pieces": 4, "slots": 4, "envelopeBytes": 3500, "blockNumber": 77,
                            "txHash": "0x" + "33" * 32},
                "chain": {"backend": "fisco-bcos", "sealedBy": "node2", "confirmedNodes": 4, "totalNodes": 4},
            }
            self.withdrawals[body["requestId"]] = record
            return httpx.Response(201, json=record)
        if request.method == "GET" and path.endswith("/verify") and path.startswith("/v1/withdrawals/"):
            return httpx.Response(200, json={"valid": True, "checks": [
                {"name": "root_matches_commitments", "ok": True}, {"name": "ratios_total_100", "ok": True},
                {"name": "pieces_match_commitments", "ok": True}, {"name": "recorded_on_chain", "ok": True},
                {"name": "amounts_total", "ok": True}],
                "chain": {"confirmations": [{"node": f"node{i}", "confirmed": True} for i in range(4)]}})
        if request.method == "GET" and path.startswith("/v1/audit/anchors/") and path.endswith("/verify"):
            subject = path.split("/")[4]
            return httpx.Response(200, json={"valid": True, "records": sum(a["subject"] == subject for a in self.anchors),
                                             "head": "0x" + "ab" * 32, "brokenAt": None})
        if request.method == "GET" and path == "/v1/chain":
            return httpx.Response(200, json={
                "chain": {"backend": "fisco-bcos", "blockNumber": 120, "groupId": 1,
                          "contracts": {"AuditTrail": "0xaa", "WithdrawalLedger": "0xbb"}},
                "nodes": [{"name": f"node{i}", "online": i != 3, "sealer": True, "blockNumber": 120} for i in range(4)]})
        return httpx.Response(404, json={"error": {"kind": "not_found", "message": path}})


@pytest.fixture()
def remote(monkeypatch, bu_client):
    fake = FakeChain()
    monkeypatch.setattr(settings, "buoyup_chain_backend", "remote")
    chain_remote.set_remote(RemoteChain("http://chain.test", "tok", transport=httpx.MockTransport(fake.handler)))
    yield fake
    chain_remote.set_remote(None)


def test_remote_success_path(bu_client, as_seller, as_officer, as_admin, remote):
    app = _sign(bu_client, as_seller, lc.offered(bu_client, as_seller))
    assert app["status"] == "disbursed", app
    kinds = [a["kind"] for a in remote.anchors]
    assert {"application", "agent_io", "algorithm_output", "credit_memo", "risk_challenge", "decision_package"} <= set(kinds)
    assert all(a["subject"] == app["id"] and a["contentHash"].startswith("0x") for a in remote.anchors)
    sent = remote.withdrawals[f"disburse:{app['id']}"]["request"]
    assert sent["amount"] == 20_000_000 and sent["currency"] == "CNY" and sent["province"] == "CN-GD"
    assert sent["bankSplit"] == {"WEBANK": 40.0, "CMB": 30.0, "ICBC": 30.0}
    assert sent["actor"]["type"] == "agent" and sent["actor"]["agentId"] == "agent-4"
    with session_scope() as s:
        loan = s.get(BuLoan, app["loan_id"])
        assert loan.withdrawal_id == "WD-REMOTE00000001"
        row = s.get(BuWithdrawal, loan.withdrawal_id)
        assert withdrawals.is_remote(row) and row.tx == "0x" + "33" * 32 and row.block == 77
        assert {o.status for o in s.scalars(select(BuChainOutbox))} == {"sent"}
    trace = bu_client.get(f"/v4/applications/{app['id']}/trace", headers=as_officer).json()
    seal = next(e for e in trace["chain"] if e["kind"] == "agent3_phase1_seal")
    assert seal["remote"]["status"] == "sent" and seal["remote"]["tx"].startswith("0x")
    status = bu_client.get("/v4/chain/status", headers=as_admin).json()
    assert status["mode"] == "remote" and status["simulated"] is False and status["height"] == 120
    assert [n["status"] for n in status["nodes"]] == ["up", "up", "up", "down"] and status["hash_alg"] == "keccak256"
    verify = bu_client.get(f"/v4/chain/cases/{app['id']}/verify", headers=as_officer).json()
    assert verify["ok"] is True and verify["remote"]["records"] == len(remote.anchors)
    wd = bu_client.get(f"/v4/chain/withdrawals/{loan.withdrawal_id}", headers=as_admin).json()
    assert wd["simulated"] is False and wd["pieces"] == 4 and wd["remote"]["sealedBy"] == "node2"
    checked = bu_client.get(f"/v4/withdrawals/{loan.withdrawal_id}/verify", headers=as_officer).json()
    assert checked["ok"] is True and checked["split_total_pct"] == 100.0 and len(checked["nodes"]) == 4


def test_remote_seal_failure_blocks_phase2(bu_client, as_seller, as_officer, remote):
    app = _consented(bu_client, as_seller)
    remote.fail_anchor_kinds = {"risk_challenge"}
    r = bu_client.post(f"/v4/applications/{app['id']}/verify", headers=as_seller, json={})
    assert r.status_code == 503 and r.json()["error"]["code"] == "CHAIN_UNAVAILABLE"
    assert "node down" in r.json()["error"]["message"]
    after = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    assert after["status"] == "consented" and after["control"] is None and after["loan_id"] is None
    with session_scope() as s:
        kinds = set(s.scalars(select(BuChainEntry.kind).where(BuChainEntry.case_id == app["id"])))
    assert not kinds & {"agent3_phase1_seal", "agent3_conclusion", "gate_decision", "syndicate"}
    # The chain is back: the same case runs through to the banks.
    remote.fail_anchor_kinds = set()
    assert lc.ok(bu_client.post(f"/v4/applications/{app['id']}/verify", headers=as_seller, json={}))["status"] == "offered"


def test_non_critical_anchor_failure_goes_to_outbox(bu_client, as_seller, as_admin, remote):
    remote.fail_anchor_kinds = {"agent_io"}
    app = lc.offered(bu_client, as_seller)
    with session_scope() as s:
        pending = list(s.scalars(select(BuChainOutbox).where(BuChainOutbox.status == "pending")))
        assert [p.kind for p in pending] == ["verification"]
    remote.fail_anchor_kinds = set()
    out = bu_client.post("/v4/chain/outbox/flush", headers=as_admin).json()
    assert out["processed"] == 1 and out["counts"]["pending"] == 0 and out["items"][0]["status"] == "sent"
    assert bu_client.post("/v4/chain/outbox/flush", headers=as_seller).status_code == 403
    assert app["status"] == "offered"


def test_withdrawal_down_queues_then_retries_without_double_pay(bu_client, as_seller, as_officer, as_admin, remote):
    app = lc.offered(bu_client, as_seller)
    remote.fail_withdrawals = True
    app = _sign(bu_client, as_seller, app)
    assert app["status"] == "signed" and app["loan_id"] is None
    items = bu_client.get("/v4/chain/outbox?status=pending", headers=as_admin).json()["items"]
    assert [i["kind"] for i in items] == ["disburse"]
    bu_client.post("/v4/chain/outbox/flush", headers=as_admin)  # still down: stays pending
    assert remote.payouts == 0
    remote.fail_withdrawals = False
    out = bu_client.post("/v4/chain/outbox/flush", headers=as_admin).json()
    assert out["counts"]["pending"] == 0
    after = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    assert after["status"] == "disbursed" and after["loan_id"]
    assert bu_client.post("/v4/chain/outbox/flush", headers=as_admin).json()["processed"] == 0
    assert remote.payouts == 1


def test_same_request_id_returns_same_remote_withdrawal(bu_client, remote):
    def create(session):
        return withdrawals.create_withdrawal(
            session, request_id="manual-7", amount=1000, currency="CNY", region="CN", province="CN-GD",
            user="U1", account="6222", payout_ref="p", requester="staff:usr_x",
            shares=[{"bank": "WEBANK", "pct": 1.0, "amount": 1000, "contract_id": "c"}], reason="test")

    # First call pays, then the local transaction is lost (crash before commit).
    with pytest.raises(RuntimeError), session_scope() as s:
        first = create(s).id
        raise RuntimeError("crash after the remote payout")
    with session_scope() as s:
        assert s.get(BuWithdrawal, first) is None
        again = create(s)
        assert again.id == first and again.envelope["replayed"] is True
    with session_scope() as s:
        assert create(s).id == first  # local idempotency, no remote call
    assert remote.payouts == 1


def test_unreachable_or_unconfigured_fails_clearly(bu_client, as_admin, monkeypatch):
    monkeypatch.setattr(settings, "buoyup_chain_backend", "remote")

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    chain_remote.set_remote(RemoteChain("http://chain.test", "tok", transport=httpx.MockTransport(down)))
    try:
        r = bu_client.get("/v4/chain/status", headers=as_admin)
        assert r.status_code == 503 and r.json()["error"]["code"] == "CHAIN_UNAVAILABLE"
        assert "http://chain.test" in r.json()["error"]["message"]
        assert bu_client.get("/v4/regions", headers=as_admin).status_code == 503
    finally:
        chain_remote.set_remote(None)
    monkeypatch.setattr(settings, "buoyup_chain_url", "")
    with pytest.raises(ChainUnavailable) as err:
        chain_remote.get_remote()
    assert err.value.kind == "not_configured"
    r = bu_client.get("/v4/chain/status", headers=as_admin)
    assert r.status_code == 503 and r.json()["error"]["details"]["kind"] == "not_configured"


def test_local_mode_is_default(bu_client, as_admin):
    assert settings.buoyup_chain_backend == "local"
    status = bu_client.get("/v4/chain/status", headers=as_admin).json()
    assert status["mode"] == "local" and status["simulated"] is True and status["hash_alg"].startswith("sha3")
    with session_scope() as s:
        assert s.scalar(select(BuChainOutbox.id)) is None
        assert s.scalar(select(BuApplication.id)) is None


def test_remote_seal_is_retried_once(bu_client, as_seller, as_officer, remote):
    """Agent 3 §6 "thử lại": a seal anchor that fails once and then succeeds lets phase 2 open."""
    class FailOnce(set):
        failed = 0

        def __contains__(self, kind: object) -> bool:
            if kind == "risk_challenge" and not self.failed:
                self.failed += 1
                return True
            return False

    app = _consented(bu_client, as_seller)
    remote.fail_anchor_kinds = once = FailOnce()
    done = lc.ok(bu_client.post(f"/v4/applications/{app['id']}/verify", headers=as_seller, json={}))
    assert once.failed == 1 and done["status"] == "offered"
    gate = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()["control"]["gate"]
    assert gate["conditions"][3]["ok"] is True  # seal on chain, anchor sent, before the conclusion
