"""Algorithm B1–B9 on chị Lan's numbers (loan circle), slider options, and the legal rule loader."""

from __future__ import annotations

import copy
from datetime import date

import pytest

from app.core import algorithm
from app.core import legal
from app.data_sources import sources
from app.core.params import DEFAULT_PARAMS

HKD = "individual_business"


def _facts(scenario: str = "lan", supplier: str = "SUP-0091", **extra) -> dict:
    """Agent 1's tool results for the scenario: tax revenue, tax, credit, FATE, store, supplier."""
    d = copy.deepcopy(sources.SCENARIOS[scenario][3])
    return {"credit": d["credit"], "revenue": d["revenue"], "tax": d["tax"], "fate": d["fate"]["value"],
            "rating": d["store"]["rating"], "industry": d["store"]["industry"],
            "supplier": sources.supplier_info(d, supplier), **extra}


def _sheet(plan=None, borrower_type: str = HKD, params=DEFAULT_PARAMS, tier: int = 2, penalties: int = 0,
           **facts) -> dict:
    plan = sources.SCENARIOS["lan"][3]["plan"] if plan is None and tier == 2 else plan
    return algorithm.compute_sheet(params, borrower_type=borrower_type, plan=plan, facts=_facts(**facts),
                                   penalties=penalties, tier=tier)


@pytest.fixture()
def sheet() -> dict:
    return _sheet()


def test_lan_blocks(sheet):
    b = sheet["blocks"]
    assert b["B3"]["unit_price_used"] == 62 and b["B3"]["need"] == 210_000
    assert b["B4"] == {"forecast": 200_040, "prudent": 140_028, "growth_used": 0.2, "prudence": 0.7}
    assert b["B5"] == {"sweep_cap": 0.6316, "sweep_usable": 0.63}
    assert b["B6"] == {"score": 80, "grade_before": "B", "grade": "B"}
    assert b["B7"]["rate"] == 0.10
    # 140.028 × 12 × 0,63 ÷ (1 + 0,10 × 12 ÷ 12) = 962.374; 1,5 × 166.700 = 250.050; hộ kinh doanh 200.000.
    assert {k: b["B8"][k] for k in ("affordability", "group_cap", "type_cap", "binding_cap", "limit", "suggested")} \
        == {"affordability": 962_374, "group_cap": 250_050, "type_cap": 200_000,
            "binding_cap": "type_cap", "limit": 200_000, "suggested": 200_000}
    assert b["B8"]["computed"] == 200_000 and b["B8"]["seed"]["ratio"] == 1.0
    assert b["B9"]["tenors"] == [3, 6, 12] and b["B9"]["tenor_max"] == 12
    assert b["B9"]["revenue_rate_max_tenor"] == 0.14 and b["B9"]["methods"] == ["installment", "revenue"]
    assert sheet["group"] == 2 and sheet["requested"] == 400_000 and sheet["limit"] == 200_000


def test_lan_options(sheet):
    opts = {o["id"]: o for o in sheet["options"]}
    assert [o["id"] for o in sheet["options"]] == ["full", "step70", "step50"]
    assert (opts["full"]["amount"], opts["full"]["max_interest"], opts["full"]["total_due"]) == (200_000, 10_833, 210_833)
    assert (opts["step70"]["amount"], opts["step70"]["total_due"]) == (140_000, 147_583)
    assert (opts["step50"]["amount"], opts["step50"]["total_due"]) == (100_000, 105_417)
    assert all(o["rate"] == 0.10 and o["tenor_m"] == 12 for o in opts.values())


def test_lan_reason_codes(sheet):
    codes = [(r["code"], r["impact"]) for r in sheet["reason_codes"]]
    assert codes == [("PRICE_FROM_INVOICE", -90_000), ("INVENTORY_AND_OWN_CAPITAL", -100_000), ("TYPE_CAP", -10_000)]
    assert 400_000 + sum(i for _c, i in codes) == 200_000


def test_penalty_downgrades_rate_not_limit_and_statements_raise_prudence():
    c = _sheet(penalties=1)
    assert (c["grade"], c["rate"], c["limit"]) == ("C", 0.12, 200_000)
    verified = _sheet(statements_verified=True)
    assert verified["blocks"]["B4"]["prudence"] == 0.75 and verified["blocks"]["B4"]["prudent"] == 150_030


def test_company_has_long_tenors_and_group_cap_binds():
    s = _sheet(borrower_type="company")
    assert s["tenors"] == [3, 6, 12, 24, 36] and s["tenor_max"] == 36
    assert (s["limit"], s["binding_cap"], s["suggested"]) == (250_000, "group_cap", 210_000)
    assert [o["amount"] for o in s["options"]] == [250_000, 175_000, 125_000]


def test_what_if_own_capital():
    plan = {**sources.SCENARIOS["lan"][3]["plan"], "own_capital": 110_000}
    s = _sheet(plan)
    # The need falls to 160.000; the limit is untouched, the suggestion ("vay vừa đủ") follows the need.
    assert (s["need"], s["limit"], s["suggested"], s["binding_cap"]) == (160_000, 200_000, 160_000, "type_cap")


def test_linked_and_new_supplier():
    plan = {**sources.SCENARIOS["lan"][3]["plan"], "supplier": "SUP-0137"}
    s = _sheet(plan, supplier="SUP-0137")
    assert s["need"] == 0 and s["suggested"] == 0 and s["blocks"]["B3"]["supplier_factor"] == 0.0
    plan["supplier"] = "SUP-9999"
    s = _sheet(plan, supplier="SUP-9999")
    assert s["blocks"]["B3"]["plan_value"] == round(5000 * 62 * 0.70) and s["suggested"] == 117_000


@pytest.mark.parametrize("amount,expected_id,total_due", [
    (140_000, "seller_140000", 147_583), (100_000, "seller_100000", 105_417), (120_050, "seller_120000", 126_500),
    (5_000, "seller_10000", 10_542), (500_000, "full", 210_833)])
def test_slider(sheet, amount, expected_id, total_due):
    o = algorithm.seller_option(DEFAULT_PARAMS, sheet, amount)
    assert o["id"] == expected_id and o["total_due"] == total_due
    assert o["rate"] == 0.10 and o["tenor_m"] == 12 and o["amount"] <= sheet["limit"]


def test_tier1_sheet():
    s = _sheet(tier=1)
    assert s["need"] is None and s["limit"] == s["suggested"] == 200_000
    assert s["options"][0]["amount"] == 200_000 and s["options"][0]["tenor_m"] == 12


def test_schedules_installment_and_revenue():
    kw = {"amount": 200_000, "rate": 0.10, "tenor_m": 12, "start": date(2026, 10, 14), "due_day": 10}
    inst = algorithm.schedule(DEFAULT_PARAMS, method="installment", **kw)
    first = inst["rows"][0]
    # 27 days to 10/11 (≥ 15 days), interest by actual days on the outstanding: 200.000 × 10% × 27 ÷ 365.
    assert (first["due_date"], first["days"], first["principal"], first["interest"]) == ("2026-11-10", 27, 16_666, 1_479)
    assert len(inst["rows"]) == 12 and sum(r["principal"] for r in inst["rows"]) == 200_000
    assert inst["rows"][-1]["outstanding_after"] == 0 and inst["total_due"] == 210_613
    assert inst["min_payment_first"] == 1_479 + 5_000  # interest + 30% of one equal instalment
    rev = algorithm.schedule(DEFAULT_PARAMS, method="revenue", prudent=140_028, sweep_usable=0.63, **kw)
    assert rev["revenue_rate"] == 0.14 and rev["rows"][0]["payment"] == round(0.14 * 140_028)
    assert sum(r["principal"] for r in rev["rows"]) == 200_000 and rev["total_interest"] < inst["total_interest"]
    late = algorithm.schedule(DEFAULT_PARAMS, method="installment", **{**kw, "start": date(2026, 10, 30)})
    assert late["first_due_date"] == "2026-12-10"  # 10/11 is only 11 days away


def test_add_months_clamps():
    assert algorithm.add_months(date(2026, 10, 13), 4) == date(2027, 2, 13)
    assert algorithm.add_months(date(2026, 10, 31), 4) == date(2027, 2, 28)


def test_rules_load_and_citations():
    assert legal.DISABLED_RULES == []
    bogus = legal.Rule("LAW-X", "câu trích bịa", "code", "reject", True, (("ECIG-2022#23", "电子烟可以随意销售"),))
    enabled, disabled = legal.load_rules((bogus, *legal.RULES))
    assert disabled[0]["code"] == "LAW-X" and "LAW-X" not in {r.code for r in enabled}
    tm = legal.verify_citation("TM-2026#72", "销售侵犯注册商标专用权的商品", date(2026, 10, 13))
    assert tm["verified"] and not tm["effective"]
    assert legal.verify_citation("TM-2026#72", "销售侵犯注册商标专用权的商品", date(2027, 1, 2))["effective"]
    assert not legal.verify_citation("NOPE#1", "x", date(2026, 10, 13))["verified"]


def test_pol05():
    assert legal.pol05_applies(2, "C") and not legal.pol05_applies(1, "C") and not legal.pol05_applies(2, "B")
