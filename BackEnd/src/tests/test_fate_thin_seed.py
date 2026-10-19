"""Review items 5 and 6 (16/10/2026): a thin FATE signal and the seed loan.

Thin FATE: a score resting on fewer than ``fate.thin_min_banks`` partner banks keeps its place in the
scorecard but its 15 points come from alternative signals, and B8 adds a lower cap. Seed loan: the
first loan is ``seed.ratio[0]`` of the computed limit; it steps up only when a good loan was repaid
and the WeBank business account showed the sales money the tax figures claim.
"""

from __future__ import annotations

import copy

import pytest

from app.core import algorithm
from app.core.params import DEFAULT_PARAMS
from app.data_sources import sources
from app.platform.db.session import session_scope
from app.platform.tables import BuLoan, save_json
from tests import lc

HKD = "individual_business"


def _facts(scenario: str = "lan", **extra) -> dict:
    d = copy.deepcopy(sources.SCENARIOS[scenario][3])
    return {"credit": d["credit"], "revenue": d["revenue"], "tax": d["tax"], "fate": d["fate"]["value"],
            "rating": d["store"]["rating"], "industry": d["store"]["industry"],
            "supplier": sources.supplier_info(d, "SUP-0091"), **extra}


def _params(ratio: list[float] | None = None) -> dict:
    p = copy.deepcopy(DEFAULT_PARAMS)
    p["seed"]["ratio"] = ratio or [0.50, 0.75, 1.0]
    return p


ALT = {"invoice_months_12m": 12, "suppliers_with_history": 2, "employees_declared": 6, "registry_age_m": 41}


# --- item 5: thin FATE -------------------------------------------------------------------------------

def test_fate_state_and_coverage_parsing():
    from app.agents.agent1_verify import fate_state

    p = DEFAULT_PARAMS
    assert fate_state(p, {"value": None}) == "missing"
    assert fate_state(p, {"value": 3, "coverage": None}) == "ok"  # older FATE service: behaviour as before
    assert fate_state(p, {"value": 3, "coverage": {"banks": 1, "months": 6}}) == "thin"
    assert fate_state(p, {"value": 3, "coverage": {"banks": 2, "months": 6}}) == "ok"
    assert sources.parse_coverage({"banks": 4}) is None and sources.parse_coverage("x") is None


def test_alt_points_replace_fate_points():
    pts = algorithm.fate_alt_points(DEFAULT_PARAMS, ALT)
    assert pts == {"invoice_regularity": 5, "supply_chain": 4, "payroll": 3, "registry_age": 3}
    assert sum(algorithm.fate_alt_points(DEFAULT_PARAMS, {}).values()) == 0
    sheet = algorithm.compute_sheet(_params([1.0, 1.0, 1.0]), borrower_type=HKD, plan=None,
                                    facts=_facts(fate_state="thin", fate_alt=ALT), tier=2)
    assert sheet["fate_mode"] == "alt" and sheet["points"]["fate"] == 15
    assert sheet["blocks"]["B6"]["fate_alt"] == pts


def test_thin_fate_cap_binds():
    # Chị Lan's revenue 166.700/month: MIN(0,5 × 166.700, 50.000) = 50.000.
    sheet = algorithm.compute_sheet(_params([1.0, 1.0, 1.0]), borrower_type=HKD, plan=None,
                                    facts=_facts(fate_state="thin", fate_alt=ALT), tier=2)
    assert sheet["blocks"]["B8"]["thin_fate_cap"] == 50_000
    assert sheet["binding_cap"] == "thin_fate_cap" and sheet["limit"] == 50_000
    normal = algorithm.compute_sheet(_params([1.0, 1.0, 1.0]), borrower_type=HKD, plan=None, facts=_facts(), tier=2)
    assert "thin_fate_cap" not in normal["blocks"]["B8"] and normal["limit"] == 200_000


def test_thin_scenario_end_to_end(bu_client, as_seller, as_officer):
    app = lc.offered(bu_client, as_seller, "thin")
    full = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    flags = {f["code"]: f for f in full["verification"]["flags"]}
    assert flags["DATA_FATE_THIN"]["status"] == "resolved_by_check" and flags["DATA_FATE_THIN"]["evidence_tool_call"]
    assert "DATA_PARTNER_MISSING" not in flags
    assert full["offer"]["binding_cap"] == "thin_fate_cap" and full["offer"]["limit"] == 50_000
    # Not blocked from auto-approval: the cap is the safeguard, RISK-02 stays for a missing score.
    assert full["status"] == "offered"


# --- item 6: seed loan ----------------------------------------------------------------------------------

def test_seed_ratio_steps():
    p = _params()
    assert algorithm.seed_ratio(p, None)["ratio"] == 0.50
    held = algorithm.seed_ratio(p, {"good_loans": 1, "webank_confirmed": False})
    assert held["ratio"] == 0.50 and held["held_back"] is True
    assert algorithm.seed_ratio(p, {"good_loans": 1, "webank_confirmed": True})["ratio"] == 0.75
    assert algorithm.seed_ratio(p, {"good_loans": 5, "webank_confirmed": True})["ratio"] == 1.0


def test_seed_cap_on_the_sheet():
    sheet = algorithm.compute_sheet(_params(), borrower_type=HKD, plan=None, facts=_facts(), tier=2)
    b8 = sheet["blocks"]["B8"]
    assert b8["computed"] == 200_000 and b8["limit"] == 100_000 and sheet["binding_cap"] == "seed_cap"
    assert [o["amount"] for o in sheet["options"]] == [100_000, 70_000, 50_000]
    code = next(r for r in sheet["reason_codes"] if r["code"] == "SEED_LOAN")
    assert code["impact"] == -100_000 and "50%" in code["text"]


def _add_webank_months(loan_id: str, months: list[str], amount: int) -> None:
    with session_scope() as s:
        loan = s.get(BuLoan, loan_id)
        doc = dict(loan.doc)
        account = dict(doc["account"])
        account["inflows"] = [{"on": f"{m}-15", "amount": amount} for m in months]
        doc["account"] = account
        save_json(loan, "doc", doc)


@pytest.mark.seed_loan
def test_first_loan_is_a_seed_loan(bu_client, as_seller):
    app = lc.offered(bu_client, as_seller)
    offer = app["offer"]
    assert offer["limit"] == 100_000 and offer["binding_cap"] == "seed_cap"
    assert offer["blocks"]["B8"]["computed"] == 200_000 and offer["blocks"]["B8"]["seed"]["stage"] == 0


@pytest.mark.seed_loan
def test_second_loan_waits_for_webank_money(bu_client, as_seller, as_officer):
    loan = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    lc.ok(bu_client.post(f"/v4/loans/{loan['id']}/prepay", headers=as_seller, json={"confirm": True}))
    app = lc.offered(bu_client, as_seller)
    full = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    flags = {f["code"]: f for f in full["verification"]["flags"]}
    assert flags["RISK_INFLOW_GAP"]["status"] == "resolved_by_check"
    assert full["offer"]["limit"] == 100_000 and full["offer"]["blocks"]["B8"]["seed"]["good_loans"] == 1


@pytest.mark.seed_loan
def test_second_loan_steps_up_with_webank_money(bu_client, as_seller, as_officer):
    loan = lc.loan_for(bu_client, as_seller, amount=60_000, tenor_m=6)
    lc.ok(bu_client.post(f"/v4/loans/{loan['id']}/prepay", headers=as_seller, json={"confirm": True}))
    # Three months of sales money ≥ 80 % of the 166.700 tax revenue reached the WeBank account.
    _add_webank_months(loan["id"], ["2026-07", "2026-08", "2026-09"], 140_000)
    app = lc.offered(bu_client, as_seller)
    full = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    assert "RISK_INFLOW_GAP" not in {f["code"] for f in full["verification"]["flags"]}
    seed = full["offer"]["blocks"]["B8"]["seed"]
    assert seed == {"ratio": 0.75, "stage": 1, "good_loans": 1, "webank_confirmed": True}
    assert full["offer"]["limit"] == 150_000
