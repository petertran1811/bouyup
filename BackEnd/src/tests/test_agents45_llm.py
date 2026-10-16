"""Agent 4 and Agent 5 through a scripted model: what the model may decide, and the code guards.

Loan circle: the banks' shares come from the syndicate round (40/30/30 or 30/70), never from a model;
Agent 4's model only words the seller notice. Loans are made over HTTP (tests/lc.py)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.agents import agent4_llm as llm_agent4
from app.agents import agent5_postaudit as postaudit
from app.agents.agent4_llm import NOTICE_SYSTEM
from app.agents.agent5_llm import AGENT5_SYSTEM
from app.platform.db.session import session_scope
from app.platform.llm.base import LLMUnavailable
from app.platform.llm.gemini import set_provider
from app.platform.llm.messages import AgentStep
from app.platform.tables import BuApplication, BuLoan, BuLoanShare
from tests import lc


def call(name: str, **args: Any) -> AgentStep:
    return AgentStep(type="tool_call", tool_name=name, arguments=args)


def final(text: str) -> AgentStep:
    return AgentStep(type="final", text=text)


class OpsProvider:
    name = "openai_compat"
    model = "fake"

    def __init__(self, *, agent5: list[AgentStep] | None = None, notice: str | None = None) -> None:
        self.agent5, self.notice = list(agent5 or []), notice
        self.systems: list[str] = []

    def available(self) -> bool:
        return True

    async def next_step(self, *, system_prompt: str, history: list, tools: list[dict]) -> AgentStep:
        self.systems.append(system_prompt)
        if system_prompt == AGENT5_SYSTEM and self.agent5:
            return self.agent5.pop(0)
        raise LLMUnavailable("no script")

    async def generate_text(self, *, system_prompt: str, user_input: str) -> str:
        if system_prompt == NOTICE_SYSTEM and self.notice is not None:
            return self.notice
        raise LLMUnavailable("no script")

    async def generate_structured(self, **_: Any) -> Any:
        raise LLMUnavailable("no script")


def shares(loan_id: str) -> dict[str, float]:
    with session_scope() as s:
        return {sh.bank_code: sh.pct for sh in s.scalars(select(BuLoanShare).where(BuLoanShare.loan_id == loan_id))}


def misuse_red(client, h, loan: dict[str, Any]) -> dict[str, Any]:
    """A securities transfer from the business account (misuse, red), then one day of monitoring."""
    lc.ok(client.post(f"/v4/loans/{loan['id']}/simulate-transfer", headers=h,
                      json={"amount": 1_000, "kind": "securities"}))
    return lc.advance(client, h, loan, (date.fromisoformat(loan["clock"]) + timedelta(days=1)).isoformat())


def test_agent4_model_cannot_change_the_bank_split(bu_client, as_seller):
    # The model has no split tool any more: with a model configured the shares are still the
    # syndicate's 40/30/30 for Lan (WEBANK/CMB/ICBC).
    c, h = bu_client, as_seller
    app = lc.offered(c, h)  # Agent 3 already reviewed; the model is there for Agent 4's part
    set_provider(OpsProvider(notice="không dùng"))
    app = lc.select(c, h, app, amount=60_000, tenor_m=6)
    lc.contract(c, h, app)
    app = lc.ok(lc.sign(c, h, app))
    loan = lc.ok(c.get(f"/v4/loans/{app['loan_id']}", headers=h))
    assert shares(loan["id"]) == {"WEBANK": 0.4, "CMB": 0.3, "ICBC": 0.3}
    assert [s["amount"] for s in loan["shares"]] == [24_000, 18_000, 18_000]
    with session_scope() as s:
        assert "agent4_split" not in s.get(BuApplication, loan["application_id"]).doc


def test_agent4_notice_and_seller_answer(bu_client, as_seller, as_officer):
    loan = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    set_provider(OpsProvider(notice="BuoyUp thấy có giao dịch không đúng mục đích kinh doanh. Cán bộ sẽ liên hệ chị."))
    loan = misuse_red(bu_client, as_seller, loan)
    red = next(n for n in loan["notices"] if n["level"] == "red")
    assert red["text"].startswith("BuoyUp thấy có giao dịch") and red["question"] is None
    assert "source" not in red  # staff-only field
    # A yellow notice asks the cause with fixed choices; the seller answers once.
    with session_scope() as s:
        row = s.get(BuLoan, loan["id"])
        notice = llm_agent4.write_notice(row, dict(row.doc), "yellow", [{"key": "use_of_funds"}], "al_x")
        assert notice["source"] == "llm" and notice["question"]["choices"][0]["key"] == "seasonal"
        row.doc = {**row.doc, "notices": [notice, *row.doc["notices"]]}
    url = f"/v4/loans/{loan['id']}/notices/{notice['id']}/answer"
    assert bu_client.post(url, json={"choice": "bogus"}, headers=as_seller).status_code == 400
    assert bu_client.post(url, json={"choice": "invoice_pending"}, headers=as_officer).status_code == 403
    r = bu_client.post(url, json={"choice": "invoice_pending", "note": "Hóa đơn về tuần sau"}, headers=as_seller)
    assert r.status_code == 200 and r.json()["notices"][0]["answer"]["label"] == "Đã nhập hàng, hóa đơn chưa về"
    assert bu_client.post(url, json={"choice": "seasonal"}, headers=as_seller).status_code == 409
    staff = bu_client.get(f"/v4/loans/{loan['id']}", headers=as_officer).json()["notices"][0]
    assert staff["source"] == "llm" and staff["answer"]["note"] == "Hóa đơn về tuần sau"
    red_staff = next(n for n in bu_client.get(f"/v4/loans/{loan['id']}", headers=as_officer).json()["notices"]
                     if n["level"] == "red")
    assert red_staff["source"] == "llm"


def test_agent4_notice_with_invented_number_uses_template(bu_client, as_seller):
    loan = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    set_provider(OpsProvider(notice="Chị cần trả ngay 77.777 tệ."))
    with session_scope() as s:
        row = s.get(BuLoan, loan["id"])
        notice = llm_agent4.write_notice(row, dict(row.doc), "red", [{"key": "overdue"}], "al_y")
    assert notice["source"] == "template" and "quá hạn" in notice["text"] and "77.777" not in notice["text"]


def test_agent5_model_summary_and_guarded_proposals(bu_client, as_officer, as_admin, monkeypatch):
    # The approval workflow runs on the 20-row synthetic sample; the sample-size gate (30, Agent 5 §6)
    # has its own test in test_agent5_fixes.py.
    monkeypatch.setattr(postaudit, "MIN_SAMPLE", 20)
    set_provider(OpsProvider(agent5=[
        call("get_report"),
        call("propose_change", param="rates.A", to_value=0.09, evidence_ref="findings", why="x"),
        call("propose_change", param="gate.auto_limit", to_value=1, evidence_ref="cohort", why="giảm mạnh"),
        call("propose_change", param="prudence.thời trang", to_value=0.6, evidence_ref="findings", why="trùng"),
        call("propose_change", param="flags.inventory_mult", to_value=1.4, evidence_ref="rule_stats",
             why="Siết cờ tồn kho khai cao"),
        final("Ngành thời trang dưới mục tiêu nên code đã đề xuất hạ hệ số; em đề nghị siết flags.inventory_mult từ 1.5 "
              "xuống 1.4."),
    ]))
    body = bu_client.post("/v4/postaudit/run", headers=as_officer).json()
    params = {p["param"]: p for p in body["proposals"]}
    assert "rates.A" not in params and "gate.auto_limit" not in params
    assert params["flags.inventory_mult"]["to"] == 1.4
    assert params["flags.inventory_mult"]["evidence"].startswith("[Agent 5 · mô hình]")
    assert sum(p["param"] == "prudence.thời trang" for p in body["proposals"]) == 1  # only the code one
    summary = body["report"]["summary"]
    assert summary["source"] == "llm" and "1.4" in summary["text"]
    assert summary["proposals"] == [params["flags.inventory_mult"]["id"]]
    # A human still has to approve, and the proposer cannot approve their own run.
    url = f"/v4/postaudit/proposals/{params['flags.inventory_mult']['id']}/decision"
    assert bu_client.post(url, json={"decision": "approve"}, headers=as_officer).status_code == 403
    assert bu_client.post(url, json={"decision": "approve", "note": "ok"}, headers=as_admin).status_code == 200


def test_agent5_summary_with_unknown_number_is_dropped(bu_client, as_officer):
    set_provider(OpsProvider(agent5=[call("get_report"), final("Tỷ lệ nợ xấu là 42%.")]))
    body = bu_client.post("/v4/postaudit/run", headers=as_officer).json()
    assert body["report"]["summary"] is None


def test_agent5_bounds_and_seller_sees_no_internal_signals(bu_client, as_seller, as_officer):
    from app.agents.agent5_llm import out_of_bounds
    from app.core.params import DEFAULT_PARAMS

    assert out_of_bounds(DEFAULT_PARAMS, "prudence.thời trang", 1.19)  # a ratio stays in (0, 1]
    assert out_of_bounds(DEFAULT_PARAMS, "flags.inventory_mult", 0)
    assert out_of_bounds(DEFAULT_PARAMS, "scorecard.grades.B", 88)  # above A (85)
    assert out_of_bounds(DEFAULT_PARAMS, "scorecard.grades.C", 60) is None
    assert out_of_bounds(DEFAULT_PARAMS, "gate.auto_limit", 400_000) is None
    loan = misuse_red(bu_client, as_seller, lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6))
    seller = bu_client.get(f"/v4/loans/{loan['id']}", headers=as_seller).json()["early_warning"]
    assert seller["level"] == "red" and seller["signals"]
    assert set(seller) == {"level", "signals"} and all(set(x) == {"text"} for x in seller["signals"])
    staff = bu_client.get(f"/v4/loans/{loan['id']}", headers=as_officer).json()["early_warning"]
    assert "score" in staff and staff["signals"][0]["weight"] >= 0


def test_agent4_retry_that_no_longer_passes_goes_to_officer(bu_client, as_seller, monkeypatch):
    """The chain was down at signing, so the payout waits in the outbox; before the retry the
    borrower withdrew consent. The retry must not pay and must not stay silently pending."""
    from app.agents import agent4a_payout as a4a
    from app.agents import agent4b_monitor as a4
    from app.blockchain.chain_remote import ChainUnavailable
    from app.platform.tables import BuChainOutbox

    c, h = bu_client, as_seller
    app = lc.select(c, h, lc.offered(c, h), amount=60_000, tenor_m=6)
    lc.contract(c, h, app)

    def chain_down(session, app_row):
        raise ChainUnavailable("chain down")

    monkeypatch.setattr(a4a, "disburse", chain_down)
    app = lc.ok(lc.sign(c, h, app))
    monkeypatch.undo()
    assert app["status"] == "signed" and not app.get("loan_id")
    lc.ok(c.post(f"/v4/applications/{app['id']}/consent/revoke", headers=h))
    with session_scope() as s:
        row = s.scalar(select(BuChainOutbox).where(BuChainOutbox.case_id == app["id"],
                                                   BuChainOutbox.kind == "disburse"))
        a4a.disburse_pending(s, row)
        app_row = s.get(BuApplication, app["id"])
        assert row.status == "failed" and app_row.status == "escalated" and not app_row.loan_id
