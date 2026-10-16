"""Review items 1 and 2 (16/10/2026): Agent 2 ↔ Agent 3 arbitration and Agent 3's independence.

Arbitration: at most ``arbitration.max_rounds`` question/answer rounds, each a ``debate_round`` chain
entry; past the cap the more cautious conclusion stands; a disagreement with no level Agent 3 accepts
is rejected; every gate decision (also escalate and reject) is on the chain.
Independence: the challenger model runs on features Agent 2 never scores with, phase 1 never sees which
option Agent 2 proposed, and production refuses one model for both agents.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.agents import agent2_advise as advise
from app.agents import agent3_control as control
from app.agents import llm_tools
from app.core import challenger
from app.platform.db.session import session_scope
from app.platform.tables import BuChainEntry
from tests import lc


def _chain(case_id: str) -> list[BuChainEntry]:
    with session_scope() as s:
        rows = list(s.scalars(select(BuChainEntry).where(BuChainEntry.case_id == case_id).order_by(BuChainEntry.seq)))
        s.expunge_all()
        return rows


def _full(c, app, officer) -> dict:
    return c.get(f"/v4/applications/{app['id']}", headers=officer).json()


# --- independence ----------------------------------------------------------------------------------

def test_challenger_features_are_disjoint_from_agent2():
    assert not set(challenger.CHALLENGER_FEATURES) & challenger.AGENT2_FEATURES
    m = challenger.model()
    assert m["features"] == list(challenger.CHALLENGER_FEATURES) and m["simulated"] is True
    assert m["hash"].startswith("sha256:") and 0.5 < m["trained_on"]["holdout_auc"] <= 1.0


def test_challenger_is_monotone_on_its_risk_signals():
    base = {f: 0.0 for f in challenger.CHALLENGER_FEATURES} | {"inventory_ratio": 1.0, "sales_spike_ratio": 1.0}
    low = challenger.score(base)["pd"]
    for name, value in (("price_deviation", 0.8), ("supplier_linked", 1.0), ("statement_deviation", 0.5)):
        assert challenger.score({**base, name: value})["pd"] > low


def test_phase1_records_challenger_and_never_sees_the_proposal(bu_client, as_seller, as_officer, monkeypatch):
    seen: dict = {}

    def fake_judge(bundle, tools, calls):
        seen.update(bundle)

    monkeypatch.setattr(llm_tools, "judge", fake_judge)
    app = lc.offered(bu_client, as_seller)
    assert "option" not in seen["offer"] and {o["id"] for o in seen["offer"]["options"]} >= {"full", "step70"}
    p1 = _full(bu_client, app, as_officer)["control"]["phase1"]
    assert p1["challenger"]["model"] == "challenger-v1" and 0 < p1["challenger"]["pd"] < 1
    assert p1["challenger"]["verdict"] == "approve" and p1["independence"]["mode"] == "code"


def test_production_refuses_one_model_for_both_agents(monkeypatch):
    from app.platform.config import settings

    monkeypatch.setattr(llm_tools, "model_independence",
                        lambda: {"agent2": "m", "agent3": "m", "distinct": False, "mode": "llm"})
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(RuntimeError, match="LLM_AGENT3_MODEL_NAME"):
        llm_tools.check_independence_at_startup()
    monkeypatch.setattr(settings, "app_env", "demo")
    llm_tools.check_independence_at_startup()  # demo: recorded in each seal, not refused


def test_challenger_concern_lowers_to_the_level_agent3_accepts(bu_client, as_seller, as_officer, monkeypatch):
    real = challenger.score
    monkeypatch.setattr(challenger, "score", lambda f, m=None: {**real(f, m), "pd": 0.40})
    app = lc.offered(bu_client, as_seller)
    full = _full(bu_client, app, as_officer)
    assert any(c["rule"] == "CHAL-01" and c["level"] == "smaller" for c in full["control"]["phase1"]["concerns"])
    assert full["control"]["gate"]["decision"] == "approve_smaller"
    assert "Kiểm soát độc lập" in full["decision"]["reason"]["factor"]


def test_high_challenger_score_escalates(bu_client, as_seller, as_officer, monkeypatch):
    real = challenger.score
    monkeypatch.setattr(challenger, "score", lambda f, m=None: {**real(f, m), "pd": 0.80})
    app = lc.start(bu_client, as_seller)
    full = _full(bu_client, app, as_officer)
    assert full["status"] == "escalated" and full["escalation"]["why"] == "CHAL-01"


# --- arbitration -----------------------------------------------------------------------------------

def test_agreement_needs_no_round(bu_client, as_seller, as_officer):
    app = lc.offered(bu_client, as_seller)
    p2 = _full(bu_client, app, as_officer)["control"]["phase2"]
    assert p2["verdict"] == "approve" and p2["rounds"] == [] and p2["cap_reached"] is False
    assert "debate_round" not in {e.kind for e in _chain(app["id"])}


def test_code_agent2_without_evidence_stops_after_one_round(bu_client, as_seller, as_officer):
    app = lc.offered(bu_client, as_seller, "noevid")
    full = _full(bu_client, app, as_officer)
    p2 = full["control"]["phase2"]
    assert len(p2["rounds"]) == 1 and p2["cap_reached"] is True and p2["verdict"] == "smaller"
    assert p2["ask"]["answer"]["source"] == "code" and p2["ask"]["valid"] is False
    rounds = [e for e in _chain(app["id"]) if e.kind == "debate_round"]
    assert len(rounds) == 1 and rounds[0].payload["round"] == 1
    assert full["control"]["gate"]["decision"] == "approve_smaller"


def test_second_round_can_settle_the_concern(bu_client, as_seller, as_officer, monkeypatch):
    answers = iter([{"claim": "", "evidence_refs": [], "source": "llm"},
                    {"claim": "Số tiền theo giá hóa đơn", "source": "llm",
                     "evidence_refs": ["sheet.B3.unit_price_used", "sheet.B8.binding_cap"]}])
    monkeypatch.setattr(advise, "answer_challenge", lambda *a, **k: next(answers))
    app = lc.offered(bu_client, as_seller, "noevid")
    p2 = _full(bu_client, app, as_officer)["control"]["phase2"]
    assert [r["round"] for r in p2["rounds"]] == [1, 2] and p2["verdict"] == "approve"
    assert p2["rounds"][1]["asks"][0]["valid"] is True and p2["cap_reached"] is False


def test_cap_reached_keeps_the_more_cautious_conclusion(bu_client, as_seller, as_officer, monkeypatch):
    calls = []

    def stubborn(*a, **k):
        calls.append(1)
        return {"claim": "Tin em đi", "evidence_refs": [f"sheet.B9.x{len(calls)}"], "source": "llm"}

    monkeypatch.setattr(advise, "answer_challenge", stubborn)
    app = lc.offered(bu_client, as_seller, "noevid")
    p2 = _full(bu_client, app, as_officer)["control"]["phase2"]
    assert len(calls) == 2 and len(p2["rounds"]) == 2 and p2["max_rounds"] == 2
    assert p2["cap_reached"] is True and p2["verdict"] == "smaller"


def test_no_acceptable_level_is_rejected_and_recorded(bu_client, as_seller, as_officer, monkeypatch):
    monkeypatch.setattr(control, "_smaller_of", lambda doc, option: None)
    app = lc.start(bu_client, as_seller, "noevid")
    full = _full(bu_client, app, as_officer)
    assert full["status"] == "rejected" and full["control"]["phase2"]["no_acceptable_level"] is True
    assert "khiếu nại" in full["decision"]["reason"]["fix"]
    gate = [e for e in _chain(app["id"]) if e.kind == "gate_decision"]
    assert gate and gate[-1].payload["decision"]["kind"] == "reject" and gate[-1].payload["why"] == "NO_ACCEPTABLE_LEVEL"


def test_escalation_is_on_the_chain(bu_client, as_seller):
    app = lc.start(bu_client, as_seller, "notes")
    gate = [e for e in _chain(app["id"]) if e.kind == "gate_decision"]
    assert gate and gate[-1].payload["decision"]["kind"] == "escalate"
