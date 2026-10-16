"""T8: rule set and bank policies on chain, independent review. T9: Agent 5 extensions."""

from __future__ import annotations

from app.agents import agent5_postaudit as postaudit

import secrets
from datetime import timedelta

from sqlalchemy import select

from app.core import legal
from app.platform.seed import seed_buoyup
from app.platform.tables import BuApplication, BuChainEntry, BuLoan, BuUser
from app.platform.db.session import session_scope
from app.platform.db.tables import utcnow
from tests.lc import offered


def test_ruleset_anchored_once_and_tamper_detected(bu_client, as_officer):
    seed_buoyup()  # a restart with the same rules does not anchor again
    params = bu_client.get("/v4/params", headers=as_officer).json()
    assert params["ruleset"]["hash"] == legal.RULESET_HASH == params["ruleset"]["anchored_hash"]
    assert params["ruleset"]["version"] == "rules-v1.2" and params["ruleset"]["chain_tx"].startswith("0x")
    with session_scope() as s:
        entries = list(s.scalars(select(BuChainEntry).where(BuChainEntry.case_id == "system",
                                                            BuChainEntry.kind == "ruleset")))
        assert len(entries) == 1
        assert ["EVENT-01", "code", "escalate", []] in entries[0].payload["rules"]
    assert bu_client.get("/v4/chain/cases/system/verify", headers=as_officer).json()["ok"] is True
    with session_scope() as s:
        entry = s.scalar(select(BuChainEntry).where(BuChainEntry.kind == "ruleset"))
        entry.payload = {**entry.payload, "rules": entry.payload["rules"][:-1]}
    broken = bu_client.get("/v4/chain/cases/system/verify", headers=as_officer).json()
    assert broken["ok"] is False and broken["reason"] == "fingerprint"


def test_bank_policy_versions_on_chain(bu_client, as_webank, as_officer):
    r = bu_client.put("/v4/banks/WEBANK/policy", headers=as_webank, json={"min_grade": "B"})
    assert r.status_code == 200 and r.json()["policy_chain_tx"].startswith("0x")
    with session_scope() as s:
        entry = s.scalar(select(BuChainEntry).where(BuChainEntry.kind == "bank_policy"))
        assert entry.payload["before"]["min_grade"] == "C" and entry.payload["after"]["min_grade"] == "B"
    assert bu_client.get("/v4/chain/cases/system/verify", headers=as_officer).json()["ok"] is True


def test_runner_cannot_approve_own_postaudit(bu_client, as_admin, monkeypatch):
    # The approval workflow runs on the 20-row synthetic sample; the sample-size gate (30, Agent 5 §6)
    # has its own test in test_agent5_fixes.py.
    monkeypatch.setattr(postaudit, "MIN_SAMPLE", 20)
    run = bu_client.post("/v4/postaudit/run", headers=as_admin).json()
    prop = run["proposals"][0]
    r = bu_client.post(f"/v4/postaudit/proposals/{prop['id']}/decision", headers=as_admin, json={"decision": "approve"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"


def seed_gate_loans(n: int, *, bad: bool) -> None:
    """Loans of gate-approved applications (event 12.12 so EVENT-01 stays quiet). A bad loan is
    120 days overdue on its instalments (Agent 4 keeps ``overdue_days`` on the loan)."""
    today = utcnow().date()
    final = today - timedelta(days=120) if bad else today + timedelta(days=60)
    with session_scope() as s:
        # Another seller's loans: Lan's own history would make her group 4 (POL-02) or busy (POL-07).
        seller = s.scalar(select(BuUser).where(BuUser.email == "seed-seller@buoyup.vn"))
        if seller is None:
            seller = BuUser(id="usr_" + secrets.token_hex(6), email="seed-seller@buoyup.vn", password_hash="x",
                            display_name="Seed seller", role="seller", active=True)
            s.add(seller)
            s.flush()
        for _ in range(n):
            app_id = "app_" + secrets.token_hex(6)
            s.add(BuApplication(id=app_id, code="APP-SEED-" + secrets.token_hex(3), seller_user_id=seller.id,
                                status="disbursed", tier=2, doc={"decision": {"by": "gate", "kind": "approve"}}))
            s.add(BuLoan(id="loan_" + secrets.token_hex(6), application_id=app_id, seller_user_id=seller.id,
                         status="overdue" if bad else "active", currency="CNY", repaid=0, outstanding=145_496,
                         doc={"amount": 139_900, "total_due": 145_496, "grade": "B", "category": "điện tử",
                              "tier": 2, "event": "12.12", "final_due_date": final.isoformat(), "forecast": 0,
                              "overdue_days": 120 if bad else 0, "max_overdue_days": 120 if bad else 0}))


def test_report_extensions_and_auto_limit_proposal(bu_client, as_seller, as_officer, as_admin):
    seed_gate_loans(5, bad=True)
    lan = offered(bu_client, as_seller)
    assert lan["offer"]["limit"] == 200_000
    body = bu_client.post("/v4/postaudit/run", headers=as_officer).json()
    report = body["report"]
    assert report["persuaded_wrong"] == 0 and report["citation_rejected"] == []
    # Agent 3 reviews before the banks are asked: Lan's offered case already counts (RISK-04 in phase 1).
    assert report["a2_a3_disagreement"] == {"rate": 1.0, "cases": 1, "disagree": 1, "band": [0.05, 0.6], "flag": True}
    assert report["a2_a3_disagreement_rate"] == 1.0 and isinstance(report["legal_rule_hits"], list)
    prop = next(p for p in body["proposals"] if p["param"] == "gate.auto_limit")
    assert (prop["from"], prop["to"], prop["status"]) == (500_000, 400_000, "pending")
    assert "100% nợ xấu trên 5 khoản" in prop["evidence"]
    grade = next(p for p in body["proposals"] if p["param"] == "scorecard.grades.B")
    assert (grade["from"], grade["to"]) == (70, 75)
    rerun = bu_client.post("/v4/postaudit/run", headers=as_officer).json()["proposals"]
    assert not any(p["param"] == "gate.auto_limit" for p in rerun)  # one pending proposal per parameter
    assert bu_client.get("/v4/params", headers=as_officer).json()["params"]["gate"]["auto_limit"] == 500_000
    r = bu_client.post(f"/v4/postaudit/proposals/{prop['id']}/decision", headers=as_admin,
                       json={"decision": "approve", "note": "Hội đồng rủi ro đồng ý"})
    assert r.status_code == 200 and r.json()["params_version"] == "v4.1"
    params = bu_client.get("/v4/params", headers=as_officer).json()
    assert params["params"]["gate"]["auto_limit"] == 400_000 and params["chain_tx"].startswith("0x")
    assert bu_client.get("/v4/chain/verify", headers=as_admin).json()["ok"] is True
    again = offered(bu_client, as_seller)
    assert again["status"] == "offered" and again["offer"]["limit"] == 200_000  # still under the new auto limit


def test_disagreement_counts_phase1(bu_client, as_seller, as_officer):
    for scenario in ("lan", "noevid"):
        offered(bu_client, as_seller, scenario)  # Agent 3 reviewed both before the limit went to the banks
    report = bu_client.post("/v4/postaudit/run", headers=as_officer).json()["report"]
    stat = report["a2_a3_disagreement"]
    # Both phase-1 verdicts are "smaller" (RISK-04) while Agent 2 proposed "full".
    assert stat["cases"] == 2 and stat["disagree"] == 2 and stat["rate"] == 1.0 and stat["flag"] is True
    assert {"rule": "POL-05", "hits": 2} in report["legal_rule_hits"]
