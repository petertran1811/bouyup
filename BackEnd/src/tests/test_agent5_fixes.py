"""Agent 5 against docs/agents/agent5_hau_kiem.md: gaps fixed on 14/10/2026 (AGENT45_FIXES.md)."""

from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy import select

from app.agents import agent4b_monitor as a4
from app.agents import agent5_postaudit as postaudit
from app.core.params import active_params
from app.platform.db.session import session_scope
from app.platform.db.tables import utcnow
from app.agents.agent5_llm import AGENT5_SYSTEM
from app.platform.llm.base import LLMUnavailable
from app.platform.llm.gemini import set_provider
from app.platform.llm.messages import AgentStep
from app.platform.tables import BuChainEntry, BuProposal
from tests.test_ruleset_postaudit import seed_gate_loans


def call(name: str, **args: Any) -> AgentStep:
    return AgentStep(type="tool_call", tool_name=name, arguments=args)


def final(text: str) -> AgentStep:
    return AgentStep(type="final", text=text)


class OpsProvider:
    """Scripted Agent 5 model; every other prompt falls back to code."""

    name = "openai_compat"
    model = "fake"

    def __init__(self, *, agent5: list[AgentStep] | None = None) -> None:
        self.agent5 = list(agent5 or [])

    def available(self) -> bool:
        return True

    async def next_step(self, *, system_prompt: str, history: list, tools: list[dict]) -> AgentStep:
        if system_prompt == AGENT5_SYSTEM and self.agent5:
            return self.agent5.pop(0)
        raise LLMUnavailable("no script")

    async def generate_text(self, **_: Any) -> str:
        raise LLMUnavailable("no script")

    async def generate_structured(self, **_: Any) -> Any:
        raise LLMUnavailable("no script")


def _run(client, h):
    r = client.post("/v4/postaudit/run", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# --- §6/§8: below 30 samples, no proposal -----------------------------------------------------

def test_small_sample_reports_but_does_not_propose(bu_client, as_officer):
    body = _run(bu_client, as_officer)
    fashion = next(f for f in body["report"]["findings"] if f["segment"] == "thời trang")
    assert fashion["sample"] == 20 and fashion["enough_sample"] is False and "Chưa đủ mẫu" in fashion["text"]
    assert fashion["synthetic_samples"] == 20 and fashion["simulated"] is True
    assert not any(p["param"].startswith("prudence.") for p in body["proposals"])


# --- no second pending proposal for the same parameter -----------------------------------------

def test_reruns_do_not_pile_up_prudence_proposals(bu_client, as_officer, monkeypatch):
    monkeypatch.setattr(postaudit, "MIN_SAMPLE", 20)
    _run(bu_client, as_officer)
    _run(bu_client, as_officer)
    with session_scope() as s:
        pending = s.scalars(select(BuProposal).where(BuProposal.param == "prudence.thời trang",
                                                     BuProposal.status == "pending")).all()
        assert len(pending) == 1


# --- §3.3: at most 0,04 per quarter --------------------------------------------------------------

def test_prudence_step_is_capped(bu_client):
    finding = {"segment": "thời trang", "value": 0.5, "current_factor": 0.70, "suggested_factor": 0.55,
               "sample": 40, "own_loans": 40, "synthetic_samples": 0, "enough_sample": True}
    with session_scope() as s:
        [prop] = postaudit._proposals_from(s, [finding], "rep_x")
        assert prop.to_value == 0.66 and "0.04 mỗi quý" in prop.evidence


def test_quarter_cap_holds_across_approvals(bu_client, as_admin, as_officer, monkeypatch):
    monkeypatch.setattr(postaudit, "MIN_SAMPLE", 20)
    body = _run(bu_client, as_officer)
    first = next(p for p in body["proposals"] if p["param"] == "prudence.thời trang")
    url = f"/v4/postaudit/proposals/{first['id']}/decision"
    assert bu_client.post(url, headers=as_admin, json={"decision": "approve", "note": "ok"}).status_code == 200
    moved = round(0.70 - first["to"], 4)
    with session_scope() as s:  # a second change in the same quarter that would exceed 0,04 in total
        report_id = first["report_id"]
        p = BuProposal(id="prop_" + secrets.token_hex(6), report_id=report_id, param="prudence.thời trang",
                       from_value=first["to"], to_value=round(first["to"] - 0.04, 2), status="pending",
                       evidence="test")
        s.add(p)
        pid = p.id
    r = bu_client.post(f"/v4/postaudit/proposals/{pid}/decision", headers=as_admin,
                       json={"decision": "approve", "note": "ok"})
    assert r.status_code == 400 and r.json()["error"]["details"]["moved"] == moved


# --- §3.7: every number in a model proposal comes from the report; prose regenerated once -----

def test_model_reason_with_an_invented_number_is_refused(bu_client, as_officer):
    set_provider(OpsProvider(agent5=[
        call("get_report"),
        call("propose_change", param="scorecard.grades.B", to_value=75, evidence_ref="rule_stats",
             why="Nợ xấu nhóm này đã lên 42%"),
        call("propose_change", param="scorecard.grades.C", to_value=60, evidence_ref="rule_stats",
             why="Hạng C cần chặt hơn"),
        final("Không có đề xuất."),
    ]))
    body = _run(bu_client, as_officer)
    assert not any(p["param"] == "scorecard.grades.B" for p in body["proposals"])
    assert any(p["param"] == "scorecard.grades.C" for p in body["proposals"])  # the same tool, no invented number


def test_summary_with_an_invented_number_is_written_again(bu_client, as_officer):
    set_provider(OpsProvider(agent5=[call("get_report"), final("Tỷ lệ nợ xấu là 42%."),
                                     final("Danh mục ổn; chưa đủ mẫu để đề xuất hệ số mới.")]))
    body = _run(bu_client, as_officer)
    assert body["report"]["summary"]["text"] == "Danh mục ổn; chưa đủ mẫu để đề xuất hệ số mới."


# --- README principle 4: what the council decides on is on the chain ---------------------------

def test_report_hash_covers_proposals_and_decisions(bu_client, as_officer, as_admin, monkeypatch):
    monkeypatch.setattr(postaudit, "MIN_SAMPLE", 20)
    body = _run(bu_client, as_officer)
    prop = next(p for p in body["proposals"] if p["param"] == "prudence.thời trang")
    assert "Chạy song song" in prop["evidence"]
    assert postaudit._shadow_text({"cases": 8, "changed": 8, "amount_delta": -48000}) == (
        " Chạy song song trên 8 hồ sơ gần nhất: 8 hồ sơ đổi hạn mức, tổng thay đổi -48.000 tệ.")
    with session_scope() as s:
        entry = s.scalar(select(BuChainEntry).where(BuChainEntry.kind == "postaudit_report")
                         .order_by(BuChainEntry.seq.desc()).limit(1))
        recorded = {p["id"]: p for p in entry.payload["proposals"]}
        assert recorded[prop["id"]]["to"] == prop["to"] and recorded[prop["id"]]["evidence"] == prop["evidence"]
    bu_client.post(f"/v4/postaudit/proposals/{prop['id']}/decision", headers=as_admin,
                   json={"decision": "reject", "note": "chờ thêm dữ liệu"})
    with session_scope() as s:
        decision = s.scalar(select(BuChainEntry).where(BuChainEntry.kind == "proposal_decision"))
        assert decision.payload["proposal_id"] == prop["id"] and decision.payload["decision"] == "rejected"


# --- §3.2: auto cohort, switch on the chain, officer approvals not counted ---------------------

def test_auto_cohort_and_switch_on_chain(bu_client, as_officer):
    seed_gate_loans(10, bad=True)
    with session_scope() as s:
        a4.refresh_auto_switch(s, active_params(s), utcnow().date())
        entry = s.scalar(select(BuChainEntry).where(BuChainEntry.kind == "auto_switch"))
        assert entry is not None and entry.payload["enabled"] is False
    report = _run(bu_client, as_officer)["report"]
    assert report["auto_cohort"]["loans"] == 10 and report["auto_cohort"]["status"] == "hard"
