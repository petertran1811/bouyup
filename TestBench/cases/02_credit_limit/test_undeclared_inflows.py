"""Credit-limit category — attack family (a)/(d): inflating the limit with money that
lands in an UNDECLARED bank account, or declaring accounts the seller does not own.

KEY INVARIANT (Agent 1 §3 / profiles.py): every cash-flow metric that feeds the limit
(monthly average, campaign totals, inflow_20d, growth) must be computed ONLY over the
bank accounts the seller declared and consented. Inflows to accounts the seller did not
declare must NOT raise any of those metrics, and therefore must NOT raise the limit.

Each test asserts that SECURE outcome (metric/limit unchanged by undeclared inflows).
A FAIL here is a real finding: undeclared money inflated the limit.
"""
from __future__ import annotations

import copy

import pytest

from conftest import DEMO, login

from app.core import algorithm
from app.core.params import DEFAULT_PARAMS
from app.data_sources import profiles, sources

SCOPES = ["inflows", "tax", "credit", "fate", "sweep"]
DECLARED_ACCOUNT = [{"bank": "WeBank", "tail": "8826"}]  # the one account lan actually declares


# -- helpers -----------------------------------------------------------------

def _undeclared_id(raw: dict) -> str:
    """The id of a bank account present in the dossier but NOT declared by the seller."""
    for a in raw["seller"]["accounts"]:
        if not a["declared"]:
            return a["id"]
    raise AssertionError("fixture has no undeclared account")


def _facts(derived: dict, supplier: str = "SUP-0091") -> dict:
    return {"credit": derived["credit"], "inflows": derived["inflows"], "tax": derived["tax"],
            "fate": derived["fate"]["value"], "rating": derived["store"]["rating"],
            "platform": derived["store"]["platform"], "industry": derived["store"]["industry"],
            "supplier": sources.supplier_info(derived, supplier), "event_days": sources.EVENT_DAYS["11.11"]}


# -- (a) metric-level invariant ----------------------------------------------

@pytest.mark.medium
def test_credit_m1_undeclared_inflow_not_in_inflow_20d(bu_client):
    """CREDIT-M1: inflow_20d must ignore money paid into an undeclared account."""
    raw = copy.deepcopy(profiles.load("lan"))
    before = profiles.derive(raw)["inflows"]["inflow_20d"]
    und = _undeclared_id(raw)
    # One fat payout, inside the 20-day window (as_of 2026-10-12), to the UNDECLARED account.
    raw["bank_statement"]["inflows"].append(["2026-10-05T10:00", 500_000, und])
    after = profiles.derive(raw)["inflows"]["inflow_20d"]
    assert after == before, (f"undeclared inflow raised inflow_20d {before} -> {after}: "
                             "cash-flow metric counts money outside the declared accounts")


@pytest.mark.medium
def test_credit_m2_undeclared_inflow_not_in_monthly_avg(bu_client):
    """CREDIT-M2: monthly_avg_12m must ignore money paid into an undeclared account."""
    raw = copy.deepcopy(profiles.load("lan"))
    before = profiles.derive(raw)["inflows"]["monthly_avg_12m"]
    und = _undeclared_id(raw)
    # Payout inside a complete prior month (within the 12-month window) to the UNDECLARED account.
    raw["bank_statement"]["inflows"].append(["2026-06-15T10:00", 600_000, und])
    after = profiles.derive(raw)["inflows"]["monthly_avg_12m"]
    assert after == before, (f"undeclared inflow raised monthly_avg_12m {before} -> {after}: "
                             "the 12-month average sums undeclared accounts too")


# -- (a) end-to-end limit inflation ------------------------------------------

def _inject_undeclared(raw: dict) -> None:
    """A campaign of payouts, all to the UNDECLARED account, across every window a metric reads."""
    und = _undeclared_id(raw)
    inj = []
    for day in range(24, 31):           # 20-day window -> inflow_20d
        inj.append([f"2026-09-{day:02d}T10:00", 200_000, und])
    for day in range(1, 15):            # 11.11 2025 peak window -> last_campaign / two_peak_avg
        inj.append([f"2025-11-{day:02d}T10:00", 100_000, und])
    for m in range(1, 10):              # complete recent months -> monthly_avg / growth
        inj.append([f"2026-{m:02d}-15T10:00", 150_000, und])
    raw["bank_statement"]["inflows"] += inj


@pytest.mark.hard
def test_credit_h1_undeclared_inflow_does_not_inflate_tier2_limit(bu_client):
    """CREDIT-H1: Tier-2 limit must not rise when extra money goes to an undeclared account."""
    base_raw = copy.deepcopy(profiles.load("lan"))
    plan = profiles.derive(base_raw)["plan"]
    base_amount = algorithm.compute_sheet(DEFAULT_PARAMS, tier=2, plan=plan,
                                           facts=_facts(profiles.derive(base_raw)), penalties=0)["amount"]
    hot_raw = copy.deepcopy(profiles.load("lan"))
    _inject_undeclared(hot_raw)
    hot_amount = algorithm.compute_sheet(DEFAULT_PARAMS, tier=2, plan=plan,
                                          facts=_facts(profiles.derive(hot_raw)), penalties=0)["amount"]
    assert hot_amount == base_amount, (f"Tier-2 limit inflated {base_amount} -> {hot_amount} using "
                                       "inflows to an undeclared account")


@pytest.mark.hard
def test_credit_h2_undeclared_inflow_does_not_inflate_tier1_limit(bu_client):
    """CREDIT-H2: Tier-1 advance must not rise when extra money goes to an undeclared account."""
    base_amount = algorithm.compute_sheet(DEFAULT_PARAMS, tier=1, plan=None,
                                           facts=_facts(profiles.derive(copy.deepcopy(profiles.load("lan")))),
                                           penalties=0)["amount"]
    hot_raw = copy.deepcopy(profiles.load("lan"))
    _inject_undeclared(hot_raw)
    hot_amount = algorithm.compute_sheet(DEFAULT_PARAMS, tier=1, plan=None,
                                          facts=_facts(profiles.derive(hot_raw)), penalties=0)["amount"]
    assert hot_amount == base_amount, (f"Tier-1 advance inflated {base_amount} -> {hot_amount} using "
                                       "inflows to an undeclared account")


# -- (d) declaring an account you do not own, through the gap answer ----------

@pytest.mark.easy
def test_credit_e1_declaring_unowned_account_does_not_inflate_offer(bu_client):
    """CREDIT-E1: answering the inflow-gap with an arbitrary account must not raise the limit."""
    h = login(bu_client, DEMO["seller"])
    app_id = bu_client.post("/v4/applications", headers=h,
                            json={"tier": 2, "store_urls": [sources.demo_url("lan")]}).json()["id"]
    bu_client.post(f"/v4/applications/{app_id}/identity", headers=h, json={"cccd": True, "face": True})
    rc = bu_client.post(f"/v4/applications/{app_id}/consent", headers=h,
                        json={"scopes": SCOPES, "accounts": DECLARED_ACCOUNT})
    bu_client.put(f"/v4/applications/{app_id}/plan", headers=h, json=dict(rc.json()["plan"]["suggested"]))
    app = bu_client.post(f"/v4/applications/{app_id}/verify", headers=h, json={}).json()
    assert app["status"] == "needs_answer"
    # Declare a bank account the seller does not own, with no ownership proof, to "add" its inflows.
    app = bu_client.post(f"/v4/applications/{app_id}/answers", headers=h,
                         json={"flag": "RISK_INFLOW_GAP", "choice": "other_bank",
                               "account": {"bank": "GhostBank", "tail": "0000"}}).json()
    assert app["status"] == "offered"
    card = app["offer"]["card"]
    # The limit stays at the cash-flow cap computed from the DECLARED data; it is not pushed
    # toward the 400.000 requested just because another account was named.
    assert card["amount"] == 139_900 and card["amount"] < app["offer"]["requested"], \
        f"declaring an unowned account moved the limit to {card['amount']}"
