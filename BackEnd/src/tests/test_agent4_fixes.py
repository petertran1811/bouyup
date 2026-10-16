"""Agent 4 against docs/agents/agent4_giai_ngan_thu_no.md: gaps fixed on 14/10/2026 (AGENT45_FIXES.md)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.agents import agent4a_payout as a4a
from app.agents import agent4b_monitor as a4
from app.blockchain import chain
from app.platform import capabilities
from app.data_sources import sources
from app.platform.db.session import session_scope
from app.platform.db.tables import utcnow
from app.platform.tables import BuApplication, BuChainOutbox, BuLoan, BuRepayment
from tests import lc
from tests.test_money_agent4 import disburse_lan, make_lan_app


# --- §3.4 / §6: the same payout id is never counted twice -------------------------------------

def test_duplicate_payout_id_is_counted_once(bu_client, as_seller):
    _, loan_id = disburse_lan()
    url = f"/v4/loans/{loan_id}/simulate-inflow"
    lc.ok(bu_client.post(f"/v4/loans/{loan_id}/simulate-transfer", headers=as_seller,
                         json={"amount": 100_000, "kind": "supplier"}))
    loan = lc.ok(bu_client.get(f"/v4/loans/{loan_id}", headers=as_seller))
    loan = lc.advance(bu_client, as_seller, loan, loan["schedule"][0]["due_date"])
    owed = loan["owed_now"]
    assert loan["status"] == "overdue" and owed > 20_000
    # Money arriving while something is overdue is debited at once, once per payout id.
    first = lc.ok(bu_client.post(url, headers=as_seller, json={"amount": 10_000, "payout_id": "DY-PO-771"}))
    again = lc.ok(bu_client.post(url, headers=as_seller, json={"amount": 10_000, "payout_id": "DY-PO-771"}))
    assert first["repaid"] == again["repaid"] == 10_000 and again["owed_now"] == owed - 10_000
    assert again["inflow_total"] == 10_000
    with session_scope() as s:
        assert len(s.scalars(select(BuRepayment).where(BuRepayment.loan_id == loan_id)).all()) == 1
    other = lc.ok(bu_client.post(url, headers=as_seller, json={"amount": 10_000, "payout_id": "DY-PO-772"}))
    assert other["repaid"] == 20_000 and other["inflow_total"] == 20_000
    assert bu_client.post(url, headers=as_seller, json={"amount": 1, "payout_id": "bad id!"}).status_code == 400


# --- §3.5: every debit is explained to the seller -------------------------------------------

def test_each_debit_is_explained(bu_client, as_seller):
    _, loan_id = disburse_lan()
    loan = lc.ok(bu_client.get(f"/v4/loans/{loan_id}", headers=as_seller))
    assert "150.000" in loan["notices"][0]["text"]  # the payout notice
    loan = lc.advance(bu_client, as_seller, loan, loan["schedule"][0]["due_date"])
    row = loan["schedule"][0]
    text = next(n["text"] for n in loan["notices"] if n["kind"] == "due")
    assert text.startswith("Kỳ 1") and f"đã trích {row['paid']:,}".replace(",", ".") in text
    assert "gốc 25.000" in text and "Dư nợ gốc còn 125.000" in text


def test_push_notice_never_drops_an_open_question():
    doc = {"notices": [{"id": "q", "at": "2026-01-01", "question": {"text": "?"}, "answer": None}]}
    for i in range(30):
        a4.push_notice(doc, {"id": f"n{i}", "at": f"2026-02-{i + 1:02d}", "level": "info"})
    assert len(doc["notices"]) == a4.MAX_NOTICES and any(n["id"] == "q" for n in doc["notices"])


# --- §3.2: the payout step re-checks the automatic limit ---------------------------------------

def test_large_amount_needs_an_officer_at_payout(bu_client):
    big = {"kind": "approve", "option_id": "full", "amount": 600_000, "by": "gate"}
    with pytest.raises(HTTPException) as exc:
        disburse_lan(decision=big)
    assert exc.value.status_code == 400 and "cán bộ" in exc.value.detail["message"]


# --- §3.1: last check before the payout --------------------------------------------------------

def test_payee_account_swapped_after_signing_is_not_paid(bu_client):
    with session_scope() as s:
        app_row = make_lan_app(s)
        doc = dict(app_row.doc)
        # "the supplier changed its account" after the contract was signed
        doc["contract"] = {**doc["contract"], "payee": {**doc["contract"]["payee"], "supplier_account": "99990000"}}
        app_row.doc = doc
        assert a4a.disburse_or_queue(s, app_row) is None
        assert app_row.status == "escalated" and app_row.loan_id is None
        assert app_row.doc["escalation"]["why"] == "SUPPLIER_CHECK_FAILED"
        assert app_row.doc["escalation"]["detail"]["account_match"] is False
        assert s.scalar(select(BuLoan).where(BuLoan.application_id == app_row.id)) is None


def _signed_with_supplier(s, supplier: str) -> BuApplication:
    """A contract signed (and anchored) with ``supplier`` as the payee of the part above 100.000."""
    app_row = make_lan_app(s)
    doc = dict(app_row.doc)
    payee = {**doc["contract"]["payee"], "supplier": supplier}
    doc["contract"] = {**doc["contract"], "payee": payee}
    app_row.doc = doc
    chain.record(s, app_row.id, "contract_signed", {"payee": payee})
    return app_row


def test_linked_supplier_is_not_paid(bu_client):
    with session_scope() as s:
        app_row = _signed_with_supplier(s, "SUP-0137")
        assert a4a.disburse_or_queue(s, app_row) is None
        detail = app_row.doc["escalation"]["detail"]
        assert detail["account_match"] is True and detail["linked_to_seller"] is True and detail["ok"] is False


def test_supplier_without_invoices_is_not_paid(bu_client):
    with session_scope() as s:
        app_row = _signed_with_supplier(s, "SUP-9999")
        check = a4a.check_before_payout(s, app_row, app_row.doc)
        assert check["exists"] is False and check["ok"] is False


def test_revoked_consent_stops_the_payout(bu_client):
    with session_scope() as s:
        app_row = make_lan_app(s)
        doc = dict(app_row.doc)
        doc["consent"] = {**doc["consent"], "revoked_at": utcnow().isoformat() + "Z"}
        app_row.doc = doc
        check = a4a.check_before_payout(s, app_row, doc)
        assert check["consent"] == "revoked" and check["ok"] is False
        assert a4a.disburse_or_queue(s, app_row) is None and app_row.status == "escalated"


# --- §3.2 "từ chối giải ngân lần hai" ----------------------------------------------------------

def test_second_loan_for_an_application_is_refused(bu_client):
    app_id, loan_id = disburse_lan()
    with session_scope() as s:
        app_row = s.get(BuApplication, app_id)
        app_row.loan_id = None  # a second path that did not see the first loan
        # The one-off grant was used by the first payout: without a new one 4a cannot pay at all.
        with capabilities.acting("agent4a"), pytest.raises(a4a.PayoutNotAuthorized):
            a4a.disburse(s, app_row)
        # Even with a fresh grant, the one-loan-per-application guard refuses.
        a4a.issue_grant(s, app_row, by="test")
        with capabilities.acting("agent4a"), pytest.raises(HTTPException) as exc:
            a4a.disburse(s, app_row)
        assert exc.value.status_code == 409 and exc.value.detail["details"]["loan_id"] == loan_id


# --- §6: a payout the outbox gives up on goes to an officer -------------------------------------

def test_failed_payout_in_outbox_escalates(bu_client):
    with session_scope() as s:
        app_row = make_lan_app(s)
        row = BuChainOutbox(case_id=app_row.id, kind="disburse", payload={"application_id": app_row.id},
                            status="failed", attempts=20, last_error="rejected", created_at=utcnow(),
                            updated_at=utcnow())
        s.add(row)
        s.flush()
        a4a.disburse_failed(s, row)
        assert app_row.status == "escalated" and app_row.doc["escalation"]["why"] == "DISBURSE_FAILED"


# --- use of funds never reads another seller's data -----------------------------------------------

def test_use_of_funds_without_data_is_unverifiable_not_ok(bu_client):
    # 80.000 goes to the business account only (a supplier payee without data would not pass the last check).
    _, loan_id = disburse_lan(choice={"amount": 80_000, "tenor_m": 3}, internal={"data": None})
    with session_scope() as s:
        loan = s.get(BuLoan, loan_id)
        doc = dict(loan.doc)
        params = a4.active_params(s)
        early = a4.check_use_of_funds(s, loan, doc, params, utcnow().date(), None)
        assert early is None and doc["use_of_funds"]["status"] == "pending"
        late = a4.check_use_of_funds(s, loan, doc, params, utcnow().date() + timedelta(days=16), None)
        assert doc["use_of_funds"]["status"] == "unverifiable" and late["key"] == "use_of_funds"


# --- B11: FATE is re-asked, not derived from the shortfall ----------------------------------------

class FixedFate:
    def __init__(self, value):
        self.value = value

    def score(self, consent, seller_ref):
        if self.value is None:
            raise sources.SourceUnavailable("down")
        return {"value": self.value, "source": "fate", "run_id": "t"}


def test_fate_worse_comes_from_a_real_rescore(bu_client):
    _, loan_id = disburse_lan()  # under the borrower's 3-box consent from Stage 1
    day = utcnow().date() + timedelta(days=1)
    try:
        sources.set_fate_source(FixedFate(5))
        with session_scope() as s:
            a4.tick(s, day, loan_ids=[loan_id])
        with session_scope() as s:
            loan = s.get(BuLoan, loan_id)
            assert loan.doc["fate"]["baseline"] == 3 and loan.doc["fate"]["current"] == 5
            assert "fate_worse" in {x["key"] for x in loan.doc["early_warning"]["signals"]}
        sources.set_fate_source(FixedFate(None))  # FATE down: the last value stays
        with session_scope() as s:
            a4.tick(s, day, loan_ids=[loan_id])
        with session_scope() as s:
            assert s.get(BuLoan, loan_id).doc["fate"]["current"] == 5
    finally:
        sources.set_fate_source(None)
