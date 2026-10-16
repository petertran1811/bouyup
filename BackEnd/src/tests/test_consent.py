"""T2: signed consent (the three loan-circle boxes), expiry, revocation, LAW-01 and the FATE gate."""

from __future__ import annotations

import copy
from datetime import timedelta

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest
from sqlalchemy import select

from app.data_sources import consent as consent_mod
from app.data_sources import sources
from app.agents.agent4b_monitor import tick
from app.platform.tables import BuApplication, BuBank, BuChainEntry, BuLoan, save_json
from app.platform.config import settings
from app.platform.db.session import session_scope
from app.platform.db.tables import utcnow
from tests import lc

BOXES = lc.BOXES


def identified(client, h) -> str:
    r = client.post("/v4/applications", headers=h, json={"tier": 2, "borrower_type": "individual_business",
                                                         "store_urls": [sources.demo_url("lan")]})
    app_id = r.json()["id"]
    assert client.post(f"/v4/applications/{app_id}/identity", headers=h,
                       json={"cccd": True, "face": True}).json()["status"] == "identified"
    return app_id


def keypair() -> tuple[Ed25519PrivateKey, str]:
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    return key, pub


def edit_doc(app_id: str, fn) -> None:
    with session_scope() as s:
        row = s.get(BuApplication, app_id)
        doc = copy.deepcopy(row.doc)
        fn(doc)
        save_json(row, "doc", doc)


def _sign(key: Ed25519PrivateKey, pub: str, message: str) -> dict:
    return {"alg": "ed25519", "public_key": pub, "sig": key.sign(message.encode()).hex()}


def test_seller_signed_consent(bu_client, as_seller):
    c, h = bu_client, as_seller
    app_id = identified(c, h)
    draft = c.post(f"/v4/applications/{app_id}/consent/draft", headers=h, json={"scopes": BOXES}).json()
    doc = draft["document"]
    assert draft["alg"] == "ed25519" and doc["scopes"] == BOXES and doc["accounts"] == []
    assert set(draft["boxes"]) == set(BOXES)
    assert draft["message"].encode() == consent_mod.message(doc)
    key, pub = keypair()
    good = _sign(key, pub, draft["message"])
    bad = {**good, "sig": key.sign(b"something else").hex()}
    r = c.post(f"/v4/applications/{app_id}/consent", headers=h, json={"scopes": BOXES, "signature": bad})
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "signature"
    # A new draft replaces the old one: a signature over the old document no longer counts.
    draft2 = c.post(f"/v4/applications/{app_id}/consent/draft", headers=h, json={"scopes": BOXES}).json()
    r = c.post(f"/v4/applications/{app_id}/consent", headers=h, json={"scopes": BOXES, "signature": good})
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "signature"
    good = _sign(key, pub, draft2["message"])
    doc = draft2["document"]
    app = c.post(f"/v4/applications/{app_id}/consent", headers=h,
                 json={"scopes": BOXES, "signature": good, "method": "otp"}).json()
    consent = app["consent"]
    assert app["status"] == "consented" and consent["signature"]["simulated"] is False
    assert consent["id"] == doc["consent_id"] and consent["expires_at"] == doc["expires_at"]
    assert consent["sign_method"] == "otp"
    assert consent_mod.valid(consent, "credit_inquiry") and consent_mod.problem(consent, consent_mod.DATA_SCOPES) is None
    with session_scope() as s:
        entry = s.scalar(select(BuChainEntry).where(BuChainEntry.case_id == app_id, BuChainEntry.kind == "consent"))
        assert entry.payload["signature"]["sig"] == good["sig"] and entry.payload["simulated_signature"] is False


def test_demo_signature_and_production_refusal(bu_client, as_seller, monkeypatch):
    c, h = bu_client, as_seller
    app_id = identified(c, h)
    app = c.post(f"/v4/applications/{app_id}/consent", headers=h, json={"scopes": BOXES}).json()
    sig = app["consent"]["signature"]
    assert sig["simulated"] is True and consent_mod.verify_signature(app["consent"]["signed"], sig)
    ttl = (consent_mod._parse(app["consent"]["expires_at"]) - consent_mod._parse(app["consent"]["signed_at"])).days
    assert ttl == 90
    other = identified(c, h)
    monkeypatch.setattr(settings, "app_env", "production")
    r = c.post(f"/v4/applications/{other}/consent", headers=h, json={"scopes": BOXES})
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "signature"


def test_tampered_consent_fails_verification(bu_client, as_seller):
    c, h = bu_client, as_seller
    app_id = identified(c, h)
    app = c.post(f"/v4/applications/{app_id}/consent", headers=h, json={"scopes": BOXES}).json()
    tampered = copy.deepcopy(app["consent"])
    tampered["signed"]["scopes"] = BOXES[:2]
    assert consent_mod.problem(tampered) == "signature"
    sneaked = copy.deepcopy(app["consent"])
    sneaked["accounts"].append({"bank": "BOC", "tail": "0000"})  # an account the signed document does not name
    assert consent_mod.problem(sneaked) == "accounts"
    dropped = copy.deepcopy(app["consent"])
    dropped["scopes"] = dropped["scopes"][:2]
    assert consent_mod.problem(dropped, consent_mod.DATA_SCOPES) == "scope"
    edit_doc(app_id, lambda d: d["consent"]["signed"].update(scopes=BOXES[:2]))
    r = c.put(f"/v4/applications/{app_id}/plan", headers=h, json=app["plan"]["suggested"])
    assert r.status_code == 200
    r = c.post(f"/v4/applications/{app_id}/verify", headers=h, json={})
    assert r.status_code == 400 and r.json()["error"]["details"]["consent"] == "signature"


def test_revoked_consent_blocks_data_tools_and_payout(bu_client, as_seller, as_officer):
    c, h = bu_client, as_seller
    # Before verification: no authorized-data tool runs.
    app_id = identified(c, h)
    app = c.post(f"/v4/applications/{app_id}/consent", headers=h, json={"scopes": BOXES}).json()
    c.put(f"/v4/applications/{app_id}/plan", headers=h, json=app["plan"]["suggested"])
    app = c.post(f"/v4/applications/{app_id}/consent/revoke", headers=h).json()
    assert app["consent"]["revoked_at"] and app["next_action"]["key"] == "consent"
    assert c.post(f"/v4/applications/{app_id}/consent/revoke", headers=h).status_code == 400
    r = c.post(f"/v4/applications/{app_id}/verify", headers=h, json={})
    assert r.status_code == 400 and r.json()["error"]["details"]["consent"] == "revoked"
    tools = [t["tool"] for t in c.get(f"/v4/applications/{app_id}", headers=h).json()["verification"]["tool_calls"]]
    assert "pull_revenue" not in tools
    trace = c.get(f"/v4/applications/{app_id}/trace", headers=as_officer).json()
    assert any(e["kind"] == "consent_revoked" for e in trace["chain"])
    # Re-consent keeps the status and plan, then verification runs.
    app = c.post(f"/v4/applications/{app_id}/consent", headers=h, json={"scopes": BOXES}).json()
    assert app["status"] == "consented" and app["plan"]["submitted"] and not app["consent"]["revoked_at"]
    assert c.post(f"/v4/applications/{app_id}/verify", headers=h, json={}).json()["status"] == "offered"

    # After the limit is approved: revoked consent → no choice, no signature until a new consent.
    offer = lc.offered(c, h)
    c.post(f"/v4/applications/{offer['id']}/consent/revoke", headers=h)
    r = c.post(f"/v4/applications/{offer['id']}/select", headers=h, json={"amount": 60_000, "tenor_m": 6})
    assert r.status_code == 400 and r.json()["error"]["details"]["consent"] == "revoked"
    c.post(f"/v4/applications/{offer['id']}/consent", headers=h, json={"scopes": BOXES})
    assert lc.select(c, h, offer, amount=60_000, tenor_m=6)["status"] == "selected"


def test_stopped_payout_releases_bank_limits(bu_client, as_seller, as_officer):
    c, h = bu_client, as_seller
    with session_scope() as s:
        before = {b.code: b.limit_used for b in s.query(BuBank)}
    offer = lc.offered(c, h)
    app = lc.select(c, h, offer, amount=60_000, tenor_m=6)
    lc.contract(c, h, app)
    # A payout stopped by the check before the money moves gives the banks' room back.
    from app.agents import agent4a_payout as a4a
    from app.agents import agent4b_monitor as a4

    real = a4a.check_before_payout
    a4a.check_before_payout = lambda *a, **k: {"ok": False, "consent": "revoked"}
    try:
        app = lc.ok(lc.sign(c, h, app))
    finally:
        a4a.check_before_payout = real
    assert app["status"] == "escalated" and app["loan_id"] is None
    full = c.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    assert full["escalation"]["why"] == "CONSENT_INVALID" and full["contract"]["released_at"]
    with session_scope() as s:
        assert {b.code: b.limit_used for b in s.query(BuBank)} == before


def test_expired_consent(bu_client, as_seller, as_officer):
    c, h = bu_client, as_seller
    app = lc.offered(c, h)
    past = (utcnow() - timedelta(days=1)).isoformat(timespec="seconds") + "Z"
    edit_doc(app["id"], lambda d: d["consent"].update(expires_at=past))
    fresh = c.get(f"/v4/applications/{app['id']}", headers=h).json()
    assert consent_mod.problem(fresh["consent"]) == "expired" and fresh["next_action"]["key"] == "consent"
    r = c.post(f"/v4/applications/{app['id']}/select", headers=h, json={"amount": 60_000, "tenor_m": 6})
    assert r.status_code == 400 and r.json()["error"]["details"]["consent"] == "expired"


def test_answers_need_valid_consent(bu_client, as_seller):
    c, h = bu_client, as_seller
    app_id = identified(c, h)
    app = c.post(f"/v4/applications/{app_id}/consent", headers=h, json={"scopes": BOXES}).json()
    plan = dict(app["plan"]["suggested"])
    declared = plan["inventory"]
    plan["inventory"] = declared * 100 + 1_000_000  # far above the estimate from invoices → a question
    c.put(f"/v4/applications/{app_id}/plan", headers=h, json=plan)
    app = c.post(f"/v4/applications/{app_id}/verify", headers=h, json={}).json()
    assert app["status"] == "needs_answer"
    assert [q["flag"] for q in app["verification"]["questions"]] == ["RISK_INVENTORY_HIGH"]
    c.post(f"/v4/applications/{app_id}/consent/revoke", headers=h)
    answer = {"flag": "RISK_INVENTORY_HIGH", "choice": "fix", "inventory": declared}
    r = c.post(f"/v4/applications/{app_id}/answers", headers=h, json=answer)
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_STATE"
    assert r.json()["error"]["details"]["consent"] == "revoked"
    c.post(f"/v4/applications/{app_id}/consent", headers=h, json={"scopes": BOXES})
    app = lc.ok(c.post(f"/v4/applications/{app_id}/answers", headers=h, json=answer))
    assert app["status"] == "offered"
    assert consent_mod.problem(app["consent"], consent_mod.DATA_SCOPES) is None


def test_tick_skips_fate_rescore_without_consent(bu_client, as_seller):
    loan = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    app_id, loan_id = loan["application_id"], loan["id"]
    edit_doc(app_id, lambda d: d["consent"].update(revoked_at=utcnow().isoformat() + "Z"))
    with session_scope() as s:
        tick(s, utcnow().date() + timedelta(days=70))
    with session_scope() as s:
        fate = s.get(BuLoan, loan_id).doc["fate"]
        assert fate["skipped"] == "consent" and fate["current"] == fate["baseline"]
