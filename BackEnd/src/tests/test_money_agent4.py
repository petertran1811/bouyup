"""Agent 4: escrow and payout, the loan, due-date debits, prepayment, closing, monitoring.

Loans come from the real loan circle (Stages 1–4 over HTTP: offer, choice, contract) and are paid
out by calling Agent 4's ``disburse`` directly, so these tests exercise Agent 4 itself rather than
the HTTP sign step. Chị Lan's default loan: 150.000 tệ, 6 months, instalments, due day 10; banks
WEBANK 40 / CMB 30 / ICBC 30 → 60.000 / 45.000 / 45.000; 100.000 to her WeBank business account,
50.000 straight to the supplier.
"""

from __future__ import annotations

import secrets
from datetime import date, timedelta
from typing import Any
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents import contract as contract_mod
from app.agents import agent4a_payout
from app.agents.agent4b_monitor import prepay, simulate_inflow, simulate_transfer, tick
from app.platform import capabilities


def disburse(session, app_row):
    """Agent 4a's payout as the orchestrator runs it (role agent4a, grant issued at signing)."""
    with capabilities.acting("agent4a"):
        return agent4a_payout.disburse(session, app_row)
from app.banks.split import split_largest_remainder, validate_split
from app.blockchain import chain
from app.core.params import active_params
from app.platform.db.session import session_scope
from app.platform.tables import (BuAlert, BuApplication, BuBank, BuLoan, BuLoanShare, BuRepayment, BuWithdrawal,
                                 save_json)
from tests import lc
from tests.conftest import DEMO_PASSWORD

LAN = "lan@buoyup.vn"
CHOICE = {"amount": 150_000, "tenor_m": 6, "method": "installment", "due_day": 10}


def seller_headers(client: TestClient, email: str = LAN) -> dict[str, str]:
    """Log a seller in; a seller other than the demo ones is registered first."""
    for password in (DEMO_PASSWORD, "abc12345"):
        r = client.post("/v4/auth/login", json={"email": email, "password": password})
        if r.status_code == 200:
            return {"Authorization": "Bearer " + r.json()["token"]}
    r = client.post("/v4/auth/register", json={"email": email, "password": "abc12345",
                                               "display_name": email.split("@")[0], "accept_terms": True})
    assert r.status_code < 300, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _selected_app(email: str, choice: dict[str, Any]) -> str:
    """Stages 1–4 for ``email`` up to the issued contract (not signed). Returns the application id."""
    from app.main import app

    client = TestClient(app)
    h = seller_headers(client, email)
    offered = lc.offered(client, h)
    selected = lc.select(client, h, offered, **choice)
    lc.contract(client, h, selected)
    return selected["id"]


def make_lan_app(session, email: str = LAN, choice: dict[str, Any] | None = None, **overrides: Any) -> BuApplication:
    """A signed application (status "signed", bank limits reserved, contract on the chain) that Agent 4
    has not paid out yet. ``overrides`` replace top-level doc keys after signing."""
    app_id = _selected_app(email, {**CHOICE, **(choice or {})})
    row = session.get(BuApplication, app_id)
    session.refresh(row)
    doc = dict(row.doc)
    doc["contract"] = {**doc["contract"], "issued_at": "2020-01-01T00:00:00Z"}  # reading time is over
    with mock.patch("app.agents.agent4a_payout.disburse_or_queue"):  # Agent 4a is called by the test
        contract_mod.sign(session, row, doc, active_params(session), dict(lc.SIGN))
    assert row.status == "signed" and row.loan_id is None
    if overrides:
        doc = dict(row.doc)
        doc.update(overrides)
        save_json(row, "doc", doc)
    session.flush()
    return row


def disburse_lan(email: str = LAN, choice: dict[str, Any] | None = None, **overrides: Any) -> tuple[str, str]:
    """Create, sign and disburse chị Lan's loan; returns (application_id, loan_id)."""
    with session_scope() as session:
        app_row = make_lan_app(session, email, choice, **overrides)
        loan = disburse(session, app_row)
        return app_row.id, loan.id


def other_seller() -> str:
    """A second borrower (one loan at a time per borrower, POL-07)."""
    return f"shop-{secrets.token_hex(3)}@shop.vn"


def _due(loan_id: str, k: int = 1) -> date:
    with session_scope() as session:
        return date.fromisoformat(session.get(BuLoan, loan_id).doc["schedule"][k - 1]["due_date"])


# --- Stage 2 bank side (the syndicate replaced the B12 split) ---------------------------------------

def test_bank_hard_rules_and_own_decision(bu_client, as_seller):
    from app.banks import syndicate

    app = lc.offered(bu_client, as_seller)
    with session_scope() as session:
        doc = session.get(BuApplication, app["id"]).doc
        case = syndicate._case(doc, doc["offer"])  # what each bank receives about chị Lan
    assert case["grade"] == "B" and case["borrower_type"] == "individual_business" and case["tenor_max"] == 12
    with session_scope() as session:
        params = active_params(session)
        bank = {code: session.get(BuBank, code) for code in ("WEBANK", "CMB", "BOC", "CCB", "GZRCB")}
        # A local bank only lends in its own province; the room and budget are checked before asking.
        assert "địa phương" in syndicate.hard_rule_problem(bank["GZRCB"], province="CN-ZJ", share=60_000, params=params)
        assert syndicate.hard_rule_problem(bank["CMB"], province="CN-GD", share=60_000, params=params) is None
        assert "ngân sách" in syndicate.hard_rule_problem(bank["CMB"], province="CN-GD", share=3_000_001,
                                                          params=params)
        bank["CMB"].active = False
        assert "tạm dừng" in syndicate.hard_rule_problem(bank["CMB"], province="CN-GD", share=60_000, params=params)
        # Each bank decides with its own policy, and answers in its own time.
        assert syndicate.bank_decides(bank["CMB"], case, 200_000)["decision"] == "approve"
        assert syndicate.bank_decides(bank["CMB"], {**case, "industry": "điện tử"}, 200_000)["decision"] == "decline"
        assert syndicate.bank_decides(bank["GZRCB"], case, 200_000)["reason"] == "Chỉ nhận hạng A trở lên"
        assert "50.000" in syndicate.bank_decides(bank["CCB"], case, 40_000)["reason"]
        # Bank of China is slow: 26 s × a steady 0,6–1,4 factor per case, so it misses the 30 s window on some cases.
        times = [syndicate.bank_decides(bank["BOC"], {**case, "case_id": f"APP-{i}"}, 200_000)["ms"] for i in range(40)]
        assert min(times) < 30_000 < max(times)
        assert syndicate.bank_decides(bank["BOC"], {**case, "case_id": "APP-1"}, 200_000)["ms"] == \
            syndicate.bank_decides(bank["BOC"], {**case, "case_id": "APP-1"}, 200_000)["ms"]


def test_reserve_at_signing_takes_room_and_budget(bu_client):
    from app.banks import syndicate

    split = [{"bank": "WEBANK", "pct": 0.4, "role": "lead"}, {"bank": "CMB", "pct": 0.3}, {"bank": "ICBC", "pct": 0.3}]
    with session_scope() as session:
        legs = syndicate.reserve_at_signing(session, split, 100_001)
        assert [(x["bank"], x["amount"]) for x in legs] == [("WEBANK", 40_001), ("CMB", 30_000), ("ICBC", 30_000)]
        assert all(x["contract_id"].startswith(f"BU-{x['bank']}-") for x in legs)
        assert session.get(BuBank, "CMB").limit_used == 30_000
        assert syndicate.budget_left(session.get(BuBank, "CMB")) == 3_000_000 - 30_000


def test_validate_split_rejects_bad_splits(bu_client):
    with session_scope() as session:
        assert validate_split(session, region="CN", amount=100000, shares=[
            {"bank": "WEBANK", "pct": 0.6}, {"bank": "CMB", "pct": 0.3}])  # 90 %
        assert validate_split(session, region="CN", amount=100000, shares=[
            {"bank": "WEBANK", "pct": 0.745}, {"bank": "CMB", "pct": 0.255}])  # below min share
        assert validate_split(session, region="CN", amount=100000, shares=[
            {"bank": "WEBANK", "pct": 0.70001}, {"bank": "CMB", "pct": 0.29999}])  # 3 decimals
        assert validate_split(session, region="CN", amount=100000, shares=[{"bank": "VCB", "pct": 1.0}])
        assert validate_split(session, region="CN", amount=100000, shares=[{"bank": "MASTER", "pct": 1.0}])
        assert validate_split(session, region="CN", amount=100000, shares=[
            {"bank": "WEBANK", "pct": 0.4}, {"bank": "CMB", "pct": 0.3}, {"bank": "ICBC", "pct": 0.3}]) == []


def test_largest_remainder():
    assert split_largest_remainder(100, [1, 1, 1]) == [34, 33, 33]
    assert split_largest_remainder(31500, [4000, 3000, 3000]) == [12600, 9450, 9450]
    assert split_largest_remainder(26110, [4000, 3000, 3000]) == [10444, 7833, 7833]
    assert sum(split_largest_remainder(7, [3333, 3333, 3334])) == 7


# --- Stage 5: escrow, payout, the loan ---------------------------------------------------------

def test_disburse_lan_creates_loan_withdrawal_and_chain(bu_client):
    app_id, loan_id = disburse_lan()
    with session_scope() as session:
        app_row = session.get(BuApplication, app_id)
        loan = session.get(BuLoan, loan_id)
        shares = session.scalars(select(BuLoanShare).where(BuLoanShare.loan_id == loan_id)).all()
        wd = session.get(BuWithdrawal, loan.withdrawal_id)
        assert app_row.status == "disbursed" and app_row.loan_id == loan_id
        assert loan.outstanding == 150_000 and loan.status == "active"
        assert loan.doc["principal_outstanding"] == 150_000 and len(loan.doc["schedule"]) == 6
        assert loan.doc["account"]["balance"] == 100_000  # the rest went straight to the supplier
        assert loan.doc["payee"]["to_supplier"] == 50_000 and loan.doc["payee"]["supplier"] == "SUP-0091"
        assert [(s.bank_code, s.amount) for s in shares] == [("WEBANK", 60_000), ("CMB", 45_000), ("ICBC", 45_000)]
        assert session.get(BuBank, "WEBANK").limit_used == 60_000  # reserved at signing, once
        assert wd.request_id == "disburse:" + app_id and len(wd.piece_fingerprints) == 4
        assert wd.loan_id == loan_id
        kinds = [e.kind for e in chain.case_entries(session, app_id)]
        assert kinds.index("contract_signed") < kinds.index("escrow_funded") < kinds.index("disbursement")
        assert chain.verify_case(session, app_id)["ok"]
        assert chain.verify_all(session)["ok"]
        # idempotent: a second call returns the same loan
        assert disburse(session, app_row).id == loan_id
        assert session.get(BuBank, "WEBANK").limit_used == 60_000


def test_small_loan_goes_to_the_account_only(bu_client):
    _, loan_id = disburse_lan(choice={"amount": 80_000, "tenor_m": 3})
    with session_scope() as session:
        doc = session.get(BuLoan, loan_id).doc
        assert doc["payee"]["to_account"] == 80_000 and not doc["payee"]["to_supplier"]
        assert doc["account"]["balance"] == 80_000


def test_unsigned_contract_is_not_paid(bu_client):
    app_id = _selected_app(LAN, CHOICE)
    with session_scope() as session, pytest.raises(Exception) as exc:
        disburse(session, session.get(BuApplication, app_id))
    assert exc.value.status_code == 400 and exc.value.detail["code"] == "INVALID_STATE"


# --- Stages 7–9: due-date debit, prepayment, closing --------------------------------------------

def test_due_date_debit_split_and_close(bu_client):
    app_id, loan_id = disburse_lan()
    due = _due(loan_id)
    with session_scope() as session:
        start = date.fromisoformat(session.get(BuLoan, loan_id).doc["start_date"])
        assert tick(session, due - timedelta(days=1)) == []
        assert session.get(BuLoan, loan_id).repaid == 0  # nothing is taken before the due date
    with session_scope() as session:
        tick(session, due)
        loan = session.get(BuLoan, loan_id)
        interest = round(150_000 * 0.10 * (due - start).days / 365)  # actual days, year of 365
        row = loan.doc["schedule"][0]
        assert row["status"] == "paid" and row["interest"] == interest and row["principal_due"] == 25_000
        assert loan.repaid == 25_000 + interest and loan.outstanding == 125_000
        assert loan.doc["account"]["balance"] == 100_000 - 25_000 - interest
        expected = split_largest_remainder(25_000 + interest, [4000, 3000, 3000])
        shares = [s.repaid for s in session.scalars(select(BuLoanShare).where(BuLoanShare.loan_id == loan_id)
                                                    .order_by(BuLoanShare.id))]
        assert shares == expected
        rep = session.scalar(select(BuRepayment).where(BuRepayment.loan_id == loan_id))
        assert rep.swept == 25_000 + interest and rep.chain_tx.startswith("0x")
    with session_scope() as session:
        loan = simulate_inflow(session, session.get(BuLoan, loan_id), 60_000)
        out = prepay(session, loan, None)  # free; interest only for the days used since the due date
        assert out["interest"] == 0 and out["principal"] == 125_000 and out["status"] == "closed"
        assert loan.outstanding == 0 and loan.status == "closed"
        assert session.get(BuApplication, app_id).status == "closed"
        assert session.get(BuBank, "WEBANK").limit_used == 0
        assert loan.doc["bureau"][-1]["kind"] == "closed"
        assert chain.verify_case(session, app_id)["ok"]
    with session_scope() as session, pytest.raises(Exception):
        simulate_inflow(session, session.get(BuLoan, loan_id), 1000)


def test_first_repayment_marks_application_repaying(bu_client):
    app_id, loan_id = disburse_lan()
    with session_scope() as session:
        tick(session, _due(loan_id))
        assert session.get(BuLoan, loan_id).repaid > 0
        assert session.get(BuApplication, app_id).status == "repaying"


def test_partial_prepay_respreads_principal(bu_client):
    _, loan_id = disburse_lan()
    with session_scope() as session:
        loan = session.get(BuLoan, loan_id)
        out = prepay(session, loan, 30_000)
        assert out["interest"] == 0 and out["principal"] == 30_000  # same day as the payout: no interest yet
        rows = loan.doc["schedule"]
        assert loan.doc["principal_outstanding"] == 120_000 and sum(r["principal"] for r in rows) == 120_000
        assert [r["principal"] for r in rows] == [20_000] * 6
        assert loan.status == "active"
        with pytest.raises(Exception) as exc:
            prepay(session, loan, 70_001)  # more than the business account holds
        assert exc.value.status_code == 400


def test_overdue_tick_alerts(bu_client):
    _, loan_id = disburse_lan()
    due = _due(loan_id)
    with session_scope() as session:
        simulate_transfer(session, session.get(BuLoan, loan_id), 100_000, "supplier")  # account emptied
    with session_scope() as session:
        assert tick(session, due + timedelta(days=3)) != []  # overdue, still in grace: yellow
        loan = session.get(BuLoan, loan_id)
        assert loan.status == "overdue" and loan.doc["arrears"]["penalty"] == 0
    with session_scope() as session:
        alerts = tick(session, due + timedelta(days=8))  # overdue ≥ 7 days: red
        red = [a for a in alerts if a.level == "red"]
        assert len(red) == 1
        keys = {s["key"] for s in red[0].signals}
        assert "overdue" in keys
        # FATE is re-asked (scenario value = baseline), not derived from the overdue amount.
        assert "fate_worse" not in keys
        assert session.get(BuLoan, loan_id).doc["arrears"]["penalty"] > 0
    with session_scope() as session:
        assert len(tick(session, due + timedelta(days=9))) == 1  # same open alert updated, not duplicated
        assert len(session.scalars(select(BuAlert).where(BuAlert.level == "red")).all()) == 1


def test_misuse_transfer_raises_red_alert(bu_client):
    app_id, loan_id = disburse_lan()
    with session_scope() as session:
        loan = session.get(BuLoan, loan_id)
        item = simulate_transfer(session, loan, 20_000, "real_estate")
        assert item["flag"]["key"] == "misuse" and item["chain_tx"]
        assert session.get(BuAlert, item["alert_id"]).level == "red"
        small = simulate_transfer(session, loan, 10_000, "personal")  # ≤ 30 % of the loan: not flagged
        assert small["flag"] is None
        with pytest.raises(Exception):
            simulate_transfer(session, loan, 1_000_000, "supplier")  # above the balance
        kinds = [e.kind for e in chain.case_entries(session, app_id)]
        assert "misuse_flag" in kinds
