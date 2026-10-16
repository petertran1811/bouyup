"""Review item 3 (16/10/2026): Agent 4 split into 4a (payout, once, high privilege) and 4b (monitoring,
for the life of the loan, read-only for money)."""

from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agents import agent4a_payout as a4a
from app.agents import agent4b_monitor as a4b
from app.blockchain import chain
from app.platform import capabilities
from app.platform.db.session import session_scope
from app.platform.db.tables import utcnow
from app.platform.tables import BuApplication, BuChainOutbox, BuLoan, BuPayoutGrant
from tests.conftest import login
from tests.test_money_agent4 import disburse_lan, make_lan_app


def test_monitor_module_never_imports_the_payout_module():
    src = Path(a4b.__file__).read_text(encoding="utf-8")
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    assert not any("agent4a_payout" in n for n in names)
    assert not hasattr(a4b, "disburse") and not hasattr(a4b, "disburse_or_queue")


def test_agent4b_cannot_move_money(bu_client):
    _, loan_id = disburse_lan()
    with session_scope() as s:
        loan = s.get(BuLoan, loan_id)
        doc = dict(loan.doc)
        doc["arrears"] = {**doc["arrears"], "interest": 100}
        with capabilities.acting("agent4b"), pytest.raises(capabilities.CapabilityDenied):
            a4b._collect(s, loan, doc, utcnow().date(), "overdue")
        with capabilities.acting("agent4b"), pytest.raises(capabilities.CapabilityDenied):
            a4b._pay_banks(s, loan, doc, 100, {"interest": 100}, "due", utcnow().date())


def test_payout_needs_the_agent4a_role(bu_client):
    with session_scope() as s:
        app_row = make_lan_app(s)
        with pytest.raises(capabilities.CapabilityDenied):
            a4a.disburse(s, app_row)  # no role: a request or the monitoring loop cannot pay out
        with capabilities.acting("agent4b"), pytest.raises(capabilities.CapabilityDenied):
            a4a.disburse(s, app_row)


def test_grant_is_bound_used_once_and_revoked(bu_client):
    app_id, _ = disburse_lan()
    with session_scope() as s:
        grants = list(s.scalars(select(BuPayoutGrant).where(BuPayoutGrant.application_id == app_id)))
        assert len(grants) == 1 and grants[0].issued_by == "orchestrator"
        assert grants[0].used_at is not None and grants[0].revoked_why == "used"
        assert a4a.live_grant(s, s.get(BuApplication, app_id)) is None
        payload = next(e for e in chain.case_entries(s, app_id) if e.kind == "disbursement").payload
        assert payload["grant"]["id"] == grants[0].id and payload["grant"]["revoked"] == "used"


def test_grant_for_another_payee_is_not_usable(bu_client):
    with session_scope() as s:
        app_row = make_lan_app(s)
        assert a4a.live_grant(s, app_row) is not None
        doc = dict(app_row.doc)
        doc["contract"] = {**doc["contract"], "amount": int(doc["contract"]["amount"]) + 100}
        app_row.doc = doc
        assert a4a.live_grant(s, app_row) is None


def test_expired_grant_goes_to_an_officer_who_reauthorizes(bu_client):
    with session_scope() as s:
        app_row = make_lan_app(s)
        app_id = app_row.id
        for g in s.scalars(select(BuPayoutGrant).where(BuPayoutGrant.application_id == app_id)):
            g.expires_at = utcnow() - timedelta(minutes=1)
        assert a4a.disburse_or_queue(s, app_row) is None
        assert app_row.status == "escalated" and app_row.doc["escalation"]["why"] == "PAYOUT_GRANT_EXPIRED"
        assert app_row.loan_id is None
    officer = login(bu_client, "officer@buoyup.vn")
    r = bu_client.post(f"/v4/officer/applications/{app_id}/reauthorize-payout", headers=officer)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "disbursed" and body["loan_id"] and not body.get("escalation")
    with session_scope() as s:
        issued = [g.issued_by for g in s.scalars(select(BuPayoutGrant).where(BuPayoutGrant.application_id == app_id))]
        assert "orchestrator" in issued and any(x not in ("orchestrator",) for x in issued)


def test_monitoring_loop_never_retries_a_payout(bu_client):
    with session_scope() as s:
        app_row = make_lan_app(s)
        s.add(BuChainOutbox(case_id=app_row.id, kind="disburse", payload={"application_id": app_row.id},
                            status="pending", attempts=1, created_at=utcnow(), updated_at=utcnow()))
        s.flush()
        chain.flush_outbox(s, include_payouts=False)
        row = s.scalar(select(BuChainOutbox).where(BuChainOutbox.case_id == app_row.id))
        assert row.status == "pending" and app_row.loan_id is None
        chain.flush_outbox(s)  # an admin flush: 4a runs once with the live grant
        assert row.status == "sent" and app_row.loan_id


def test_due_date_debit_still_runs_as_the_standing_order(bu_client):
    _, loan_id = disburse_lan()
    with session_scope() as s:
        loan = s.get(BuLoan, loan_id)
        first_due = loan.doc["schedule"][0]["due_date"]
        a4b.tick(s, as_of=a4b.parse_date(first_due), loan_ids=[loan_id], refresh=False)
        row = s.get(BuLoan, loan_id).doc["schedule"][0]
        assert row["status"] in ("paid", "partial", "overdue")
