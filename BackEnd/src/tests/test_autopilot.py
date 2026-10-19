"""Agents 4 and 5 run on their own (app/buoyup/autopilot.py)."""

from __future__ import annotations

from app.agents import agent5_postaudit as postaudit

from sqlalchemy import select

from app.autopilot import loop as autopilot
from app.platform.tables import BuEvent, BuLoan, BuReport
from app.platform.db.session import session_scope
from tests import lc
from tests.test_money_agent4 import disburse_lan, other_seller


def _overdue(loan_id: str, days: int = 8) -> str:
    """Empty the business account; returns the day ``days`` after the first due date (red from 7)."""
    from datetime import date, timedelta

    from app.agents.agent4b_monitor import simulate_transfer

    with session_scope() as s:
        loan = s.get(BuLoan, loan_id)
        simulate_transfer(s, loan, int(loan.doc["account"]["balance"]), "supplier")
        return (date.fromisoformat(loan.doc["schedule"][0]["due_date"]) + timedelta(days=days)).isoformat()


def test_autopilot_is_off_in_tests_and_status_is_staff_only(bu_client, as_seller, as_officer):
    assert autopilot.enabled() is False
    assert bu_client.get("/v4/autopilot/status", headers=as_seller).status_code == 403
    body = bu_client.get("/v4/autopilot/status", headers=as_officer).json()
    assert body["enabled"] is False and body["agent4"]["interval_seconds"] == 300


def test_agent4_round_assesses_every_open_loan(bu_client, as_seller):
    _, loan_id = disburse_lan()
    out = autopilot.run_agent4("schedule")
    assert out["loans"] >= 1 and out["last_reason"] == "schedule" and out["error"] is None
    with session_scope() as s:
        ew = s.get(BuLoan, loan_id).doc["early_warning"]
        assert ew["at"] and ew["level"] == "green"
        assert s.scalar(select(BuEvent).where(BuEvent.kind == "autopilot_run")) is not None
    assert bu_client.get(f"/v4/loans/{loan_id}", headers=as_seller).json()["monitored_at"] == ew["at"]


def test_agent5_runs_then_skips_when_nothing_changed(bu_client):
    disburse_lan()
    first = autopilot.run_agent5("schedule")
    assert first["report_id"] and first["skipped"] is None
    with session_scope() as s:
        report = s.get(BuReport, first["report_id"])
        assert report.data["requested_by"] == "agent5:auto"
    second = autopilot.run_agent5("schedule")
    assert second["skipped"] and second["report_id"] == first["report_id"]


def test_paying_off_marks_agent5_due(bu_client, as_seller):
    _, loan_id = disburse_lan()
    autopilot._agent5_due.update(at=None, reason=None)
    lc.ok(bu_client.post(f"/v4/loans/{loan_id}/simulate-inflow", headers=as_seller, json={"amount": 60_000}))
    r = bu_client.post(f"/v4/loans/{loan_id}/prepay", headers=as_seller, json={"confirm": True})
    assert r.json()["status"] == "closed"
    assert autopilot._agent5_due["reason"] == "khoản vay tất toán"
    autopilot._agent5_due.update(at=None, reason=None)


def test_agent5_auto_proposals_can_be_approved_by_any_admin(bu_client, as_admin, monkeypatch):
    # The approval workflow runs on the 20-row synthetic sample; the sample-size gate (30, Agent 5 §6)
    # has its own test in test_agent5_fixes.py.
    monkeypatch.setattr(postaudit, "MIN_SAMPLE", 20)
    disburse_lan()
    rid = autopilot.run_agent5("schedule")["report_id"]
    props = [p for p in bu_client.get("/v4/postaudit/proposals", headers=as_admin).json()["items"]
             if p.get("report_id", rid) == rid and p["status"] == "pending"]
    assert props, "the synthetic backtest always proposes a prudence change"
    r = bu_client.post(f"/v4/postaudit/proposals/{props[0]['id']}/decision", headers=as_admin,
                       json={"decision": "reject", "note": "chưa đủ dữ liệu"})
    assert r.status_code == 200, r.text


def test_monitor_queues_notices_outside_the_transaction(bu_client, as_officer, as_seller):
    from app.agents import agent4_llm as llm_agent4
    from app.agents.agent4_llm import NOTICE_SYSTEM
    from app.platform.db.session import session_scope as scope

    calls: list[bool] = []
    real = llm_agent4.write_notice

    def spy(loan, doc, level, signals, alert_id, use_model=True):
        # No transaction may be open on the loan while the model drafts: a write must go through.
        with scope() as s:
            s.get(BuLoan, loan_id).repaid = s.get(BuLoan, loan_id).repaid
        calls.append(use_model)
        return real(loan, doc, level, signals, alert_id, use_model=use_model)

    _, loan_id = disburse_lan()
    late = _overdue(loan_id)
    llm_agent4.write_notice = spy
    try:
        r = bu_client.post("/v4/monitoring/tick", headers=as_officer, json={"as_of": late})
    finally:
        llm_agent4.write_notice = real
    assert r.status_code == 200 and calls == [True]
    notices = bu_client.get(f"/v4/loans/{loan_id}", headers=as_seller).json()["notices"]
    assert notices[0]["level"] == "red" and NOTICE_SYSTEM  # template text (no model in tests)


def test_round_shares_one_model_budget(bu_client, monkeypatch):
    from app.agents import agent4b_monitor as d

    late = [_overdue(disburse_lan(other_seller() if i else "lan@buoyup.vn")[1]) for i in range(3)][0]
    monkeypatch.setattr(d, "NOTICE_MODEL_BUDGET", 2)
    seen: list[bool] = []
    real = d.deliver_notices

    def spy(pending, budget=None):
        seen.append(budget[0] if budget else None)
        return real(pending, budget)

    monkeypatch.setattr(d, "deliver_notices", spy)
    monkeypatch.setattr(d, "today", lambda: __import__("datetime").date.fromisoformat(late))
    autopilot.run_agent4("schedule")
    assert seen == [2]  # one budget for the whole round, not one per loan
