"""Credit-limit category — attack families (b)/(c): pushing the limit by feeding the
plan / what-if / quote / answers endpoints numbers outside the allowed ranges, or
non-finite numbers (negative, zero, overflow, NaN, Infinity).

Secure outcome: every out-of-range or non-finite input is rejected (HTTP 400/422) and
never reaches the algorithm. A FAIL means a malformed number was accepted and could move
the limit.
"""
from __future__ import annotations

import pytest

from conftest import DEMO, login

from app.data_sources import sources

SCOPES = ["inflows", "tax", "credit", "fate", "sweep"]
ACC = [{"bank": "WeBank", "tail": "8826"}]
JSON_CT = {"Content-Type": "application/json"}


def _consented(bu_client, h):
    """Create -> identity -> consent; returns (app_id, suggested_plan)."""
    app_id = bu_client.post("/v4/applications", headers=h,
                            json={"tier": 2, "store_urls": [sources.demo_url("lan")]}).json()["id"]
    bu_client.post(f"/v4/applications/{app_id}/identity", headers=h, json={"cccd": True, "face": True})
    rc = bu_client.post(f"/v4/applications/{app_id}/consent", headers=h,
                        json={"scopes": SCOPES, "accounts": ACC})
    return app_id, dict(rc.json()["plan"]["suggested"])


def _offered(bu_client, h):
    """Drive a full lan application to an offer; returns app_id."""
    app_id, plan = _consented(bu_client, h)
    bu_client.put(f"/v4/applications/{app_id}/plan", headers=h, json=plan)
    bu_client.post(f"/v4/applications/{app_id}/verify", headers=h, json={})
    bu_client.post(f"/v4/applications/{app_id}/answers", headers=h,
                   json={"flag": "RISK_INFLOW_GAP", "choice": "other_bank",
                         "account": {"bank": "CMB", "tail": "1203"}})
    return app_id


# -- (b) plan out of the allowed ranges --------------------------------------

@pytest.mark.easy
def test_credit_e2_plan_negative_own_capital_rejected(bu_client):
    """CREDIT-E2: a negative own_capital in the plan is rejected."""
    h = login(bu_client, DEMO["seller"])
    app_id, plan = _consented(bu_client, h)
    r = bu_client.put(f"/v4/applications/{app_id}/plan", headers=h, json={**plan, "own_capital": -1})
    assert r.status_code in (400, 422), r.text


@pytest.mark.easy
def test_credit_e3_plan_zero_qty_and_over_cap_price_rejected(bu_client):
    """CREDIT-E3: zero/negative qty and an over-cap unit price in the plan are rejected."""
    h = login(bu_client, DEMO["seller"])
    app_id, plan = _consented(bu_client, h)
    for bad in ({"qty": 0}, {"qty": -5}, {"price": -50}, {"price": 2_000_000}, {"qty": 99_999_999_999}):
        r = bu_client.put(f"/v4/applications/{app_id}/plan", headers=h, json={**plan, **bad})
        assert r.status_code in (400, 422), f"{bad} accepted: {r.text}"


# -- (c) what-if / quote: negative, zero, overflow, NaN, Infinity ------------

@pytest.mark.medium
def test_credit_m3_what_if_rejects_out_of_range_numbers(bu_client):
    """CREDIT-M3: what-if rejects negative, zero and overflow numeric inputs."""
    h = login(bu_client, DEMO["seller"])
    app_id = _offered(bu_client, h)
    for bad in ({"own_capital": -1}, {"qty": 0}, {"qty": -5}, {"own_capital": 1_000_000_000_000},
                {"inventory": -1}):
        r = bu_client.post(f"/v4/applications/{app_id}/what-if", headers=h, json=bad)
        assert r.status_code in (400, 422), f"{bad} accepted: {r.text}"


@pytest.mark.medium
def test_credit_m4_what_if_and_quote_reject_nan_and_infinity(bu_client):
    """CREDIT-M4: what-if and quote reject NaN / Infinity numeric payloads."""
    h = login(bu_client, DEMO["seller"])
    app_id = _offered(bu_client, h)
    for raw in ('{"qty": NaN}', '{"own_capital": Infinity}', '{"qty": 1e400}'):
        r = bu_client.post(f"/v4/applications/{app_id}/what-if", headers={**h, **JSON_CT}, content=raw)
        assert r.status_code in (400, 422), f"what-if accepted {raw}: {r.text}"
    for raw in ('{"amount": NaN}', '{"amount": Infinity}', '{"amount": 1e400}'):
        r = bu_client.post(f"/v4/applications/{app_id}/quote", headers={**h, **JSON_CT}, content=raw)
        assert r.status_code in (400, 422), f"quote accepted {raw}: {r.text}"


@pytest.mark.easy
def test_credit_e4_what_if_rejects_unknown_tenor_field(bu_client):
    """CREDIT-E4: what-if rejects an unknown `tenor_m` field (tenor is not seller-tunable)."""
    h = login(bu_client, DEMO["seller"])
    app_id = _offered(bu_client, h)
    r = bu_client.post(f"/v4/applications/{app_id}/what-if", headers=h, json={"tenor_m": 6})
    assert r.status_code in (400, 422), f"what-if accepted tenor override: {r.text}"
