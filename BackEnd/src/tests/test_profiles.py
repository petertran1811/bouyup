"""Chị Lan's raw dossier: every Agent 1 figure is computed from rows, and matches agent1 §6."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select

from app.data_sources import profiles
from app.data_sources import sources
from app.platform.tables import BuApplication, BuLoan, BuUser
from app.platform.config import settings
from app.platform.db.session import session_scope
from tests.conftest import login

ROOT = Path(__file__).resolve().parents[1]  # BackEnd/src


def test_lan_figures_come_from_raw_rows():
    """Loan circle: revenue is read from her tax filings (sales invoices), never from bank inflows."""
    d = profiles.derive(profiles.load("lan"))
    rev = d["revenue"]
    assert (rev["source"], rev["first_sale_month"], rev["months_with_sales"], rev["peak_seasons"]) == \
        ("tax", "2024-08", 26, 2)
    assert (rev["monthly_avg_12m"], rev["growth_3m"], rev["cv_monthly"], rev["spike_ratio"]) == (166700, 0.2, 0.445, 1.1)
    assert rev["last_peak"] == 276870 and len(rev["monthly_12m"]) == 12
    assert sum(m["amount"] for m in rev["monthly_12m"]) == 12 * 166700
    assert d["tax"] == {"invoice_unit_price_3m": 62, "gross_margin": 0.4, "platform_fee": 0.05,
                        "suppliers": ["SUP-0091"], "employees_declared": 6, "inventory_estimate": 36000,
                        "b2b_sales_share": 0.0}
    assert {k: d["credit"][k] for k in ("late_max_days_24m", "late_12m", "inquiries_3m", "monthly_installments")} == \
        {"late_max_days_24m": 0, "late_12m": 0, "inquiries_3m": 2, "monthly_installments": 25005}
    assert d["store_matches_registry"] is True and d["fate"]["value"] == 3
    assert sources.SCENARIOS["lan"][3]["revenue"]["monthly_avg_12m"] == 166700
    assert sources.pull_revenue(sources.SCENARIOS["lan"][3]) == sources.SCENARIOS["lan"][3]["revenue"]


def test_bank_accounts_do_not_change_the_revenue():
    """No accounts are declared any more: which bank the platform paid into leaves the tax figures alone."""
    raw = copy.deepcopy(profiles.load("lan"))
    before = profiles.derive(raw)
    raw["seller"]["accounts"][1]["declared"] = True
    after = profiles.derive(raw)
    assert after["revenue"] == before["revenue"] and after["tax"] == before["tax"]


def test_debt_ratio_is_over_tax_revenue():
    raw = copy.deepcopy(profiles.load("lan"))
    d = profiles.derive(raw)
    assert d["credit"]["debt_to_inflow"] == round(25005 / d["revenue"]["monthly_avg_12m"], 2) == 0.15
    raw["seller"]["accounts"][1]["declared"] = True
    assert profiles.derive(raw)["credit"]["debt_to_inflow"] == d["credit"]["debt_to_inflow"]


def test_changing_raw_rows_changes_the_figures():
    raw = copy.deepcopy(profiles.load("lan"))
    raw["credit_report"]["accounts"][0]["days_late_24m"][-1] = 45
    raw["seller"]["accounts"][1]["declared"] = True
    # Pay the six staff a second time inside 24 hours of a payout: 4% more to individuals.
    extra = [dict(t) for t in raw["bank_statement"]["outflows"] if t["to"]["kind"] == "individual"]
    raw["bank_statement"]["outflows"] += extra
    d = profiles.derive(raw)
    assert d["credit"]["late_max_days_24m"] == 45 and d["credit"]["late_12m"] == 1
    assert d["inflows"]["to_declared_accounts_vs_tax_sales"] == 1.0
    assert d["inflows"]["pass_through"]["share_to_individuals_24h"] == 0.08


def test_me_prefills_lan_store_and_account(bu_client):
    me = bu_client.get("/v4/auth/me", headers=login(bu_client, "lan@buoyup.vn")).json()
    assert me["demo_profile"] == {"profile": "lan", "store_url": sources.demo_url("lan"),
                                  "accounts": [{"bank": "WeBank", "tail": "8826"}]}
    assert "demo_profile" not in bu_client.get("/v4/auth/me", headers=login(bu_client, "officer@buoyup.vn")).json()


def test_me_has_no_demo_profile_outside_demo_env(bu_client, monkeypatch):
    headers = login(bu_client, "lan@buoyup.vn")
    monkeypatch.setattr(settings, "app_env", "production")
    assert "demo_profile" not in bu_client.get("/v4/auth/me", headers=headers).json()


def test_inquiries_window_is_three_calendar_months_up_to_as_of():
    raw = copy.deepcopy(profiles.load("lan"))
    raw["as_of"] = "2026-07-31"
    raw["credit_report"]["inquiries"] = [{"date": "2026-04-29", "by": "X"}, {"date": "2026-04-30", "by": "X"},
                                         {"date": "2026-05-01", "by": "X"}, {"date": "2026-08-01", "by": "X"}]
    assert profiles.derive(raw)["credit"]["inquiries_3m"] == 1


def _reset_module():
    spec = importlib.util.spec_from_file_location("reset_demo_seller", ROOT / "scripts" / "reset_demo_seller.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_reset_demo_seller_archives_only_lan_and_closes_open_loans(bu_client, monkeypatch):
    with session_scope() as s:
        lan = s.scalar(select(BuUser).where(BuUser.email == "lan@buoyup.vn"))
        s.add(BuApplication(id="app_t1", code="T-1", seller_user_id=lan.id, status="disbursed", tier=2,
                            scenario="lan", doc={}, loan_id="loan_t1"))
        s.add(BuLoan(id="loan_t1", application_id="app_t1", seller_user_id=lan.id, status="active",
                     doc={}, outstanding=139900))
        s.add(BuApplication(id="app_t2", code="T-2", seller_user_id="someone-else", status="offered", tier=2,
                            scenario="lan", doc={}))
    mod = _reset_module()
    assert mod.reset("lan@buoyup.vn") == 1
    with session_scope() as s:
        archive = s.scalar(select(BuUser).where(BuUser.email == "lan-archive@buoyup.vn"))
        assert archive is not None and archive.active is False
        assert s.get(BuApplication, "app_t1").seller_user_id == archive.id
        assert s.get(BuApplication, "app_t2").seller_user_id == "someone-else"
        loan = s.get(BuLoan, "loan_t1")
        assert (loan.seller_user_id, loan.status) == (archive.id, "closed")
        assert loan.doc["archived_demo"]["outstanding"] == 139900
    with pytest.raises(SystemExit):
        mod.reset("officer@buoyup.vn")
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(SystemExit):
        mod.reset("lan@buoyup.vn")
