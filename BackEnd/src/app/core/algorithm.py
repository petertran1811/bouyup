"""Fixed credit algorithm (loan circle). Pure functions: same inputs, same numbers.

Loan circle (docs/BuoyUp loan circle .docx): the decision core computes the maximum limit, the rate
and the longest tenor; the borrower then picks an amount within the limit, a tenor, one of two
repayment methods and a monthly due day. Revenue comes from tax invoices (plus seller statements
the agent verified), never from another bank or from the platform.

Blocks: B1 customer group · B3 capital need (plan; advisory, "vay vừa đủ") · B4 prudent monthly
revenue · B5 cost-share cap · B6 scorecard and grade · B7 rate by grade (≤ legal cap) · B8 limit
(affordability over the longest tenor, group cap, borrower-type cap) · B9 repayment (schedules for
equal-principal instalments and revenue-based payments, interest by actual days).

Money is integer yuan; rates and ratios are decimals. Python's round() (half-even) is used on
purpose: the browser demo reproduces it.

Chị Lan (hộ kinh doanh, tax revenue 166.700/month, growth 20%, grade B 10%): prudent revenue
140.028/month; caps affordability 962.374 · group 250.050 · type 200.000 → limit 200.000.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

GRADES = ("A", "B", "C", "D", "E")
OPTION_LABELS = {"full": "Hạn mức đầy đủ", "step70": "Phương án 70%", "step50": "Phương án 50%"}
METHODS = ("installment", "revenue")
METHOD_LABELS = {"installment": "Trả góp cố định theo tháng", "revenue": "Trả theo doanh thu"}

# B6 scorecard: (indicator, bands as (lower bound inclusive, points)), checked top-down.
_SCORE_BANDS: dict[str, list[tuple[float, int]]] = {
    "rating": [(4.7, 10), (4.4, 8), (4.0, 5), (-math.inf, 0)],
    "age_m": [(36, 10), (24, 8), (12, 5), (-math.inf, 0)],
    "gross_margin": [(0.35, 10), (0.20, 7), (0.10, 4), (-math.inf, 0)],
    "monthly_avg": [(500_000, 5), (150_000, 4), (50_000, 2), (-math.inf, 0)],
}

INDUSTRY_BY_CATEGORY = {"Thời trang nữ": "thời trang", "Thời trang": "thời trang", "Mỹ phẩm": "mỹ phẩm",
                        "Tạp hóa": "tạp hóa", "Điện tử": "điện tử"}


def floor_to(value: float, step: int) -> int:
    return int(math.floor(value / step + 1e-9) * step)


def floor_pct(x: float) -> float:
    return math.floor(x * 100 + 1e-9) / 100


def ceil_pct(x: float) -> float:
    return math.ceil(x * 100 - 1e-9) / 100


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    days_in_month = [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28,
                     31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(d.day, days_in_month))


def fmt_num(n: float) -> str:
    """Vietnamese number format: 139900 -> '139.900', 0.5 -> '0,5'."""
    if float(n).is_integer():
        return f"{int(n):,}".replace(",", ".")
    return f"{n}".replace(".", ",")


# --- B1 -------------------------------------------------------------------

def customer_group(credit: dict[str, Any]) -> int:
    """1 good history in the network · 2 credit elsewhere · 3 never borrowed · 4 late/default."""
    if credit.get("late_max_days_24m", 0) >= 30 or credit.get("defaulted_within_24m") or credit.get("active_npl") \
            or credit.get("network_history") == "bad":
        return 4
    if credit.get("network_history") == "good":
        return 1
    if credit.get("has_credit_elsewhere"):
        return 2
    return 3


# --- B3: the plan's capital need (what "vay vừa đủ" means) --------------------

def capital_need(params: dict[str, Any], plan: dict[str, Any], invoice_price: float | None,
                 supplier: dict[str, Any]) -> dict[str, Any]:
    declared = plan["price"]
    gap = invoice_price is None
    ref = declared * (1 - params["price"]["no_invoice_haircut"]) if gap else invoice_price
    price_used = min(declared, ref)
    if supplier.get("linked"):
        factor = 0.0
    elif not supplier.get("invoice_history"):
        factor = params["price"]["new_supplier_factor"]
    else:
        factor = 1.0
    plan_value = round(plan["qty"] * price_used * factor)
    deductions = plan["inventory"] + plan["own_capital"] + plan.get("other_loans", 0)
    return {"price_declared": declared, "unit_price_used": price_used, "supplier_factor": factor,
            "plan_value": plan_value, "need": max(0, plan_value - deductions),
            "requested": round(plan["qty"] * declared), "data_source_gap": gap}


# --- B4, B5 -----------------------------------------------------------------

def prudent_revenue(params: dict[str, Any], revenue: dict[str, Any], industry: str,
                    statements_verified: bool = False) -> dict[str, Any]:
    """Monthly revenue the loan can lean on: tax average × (1 + growth, capped) × prudence factor;
    verified seller statements add ``revenue.statement_bonus`` to the factor (a higher limit)."""
    growth = min(revenue["growth_3m"], params["forecast"]["growth_cap"])
    forecast = round(revenue["monthly_avg_12m"] * (1 + growth))
    prudence = params["prudence"].get(industry, params["prudence"]["khác"])
    if statements_verified:
        prudence = round(prudence + params["revenue"]["statement_bonus"], 4)
    return {"growth_used": growth, "forecast": forecast, "prudence": prudence, "prudent": round(forecast * prudence)}


def sweep_cap(gross_margin: float, platform_fee: float) -> dict[str, float]:
    """B5: the cost-of-goods share of each yuan of revenue: the most a repayment may take."""
    cap = (1 - gross_margin) / (1 - platform_fee)
    return {"sweep_cap": round(cap, 4), "sweep_usable": floor_pct(cap)}


# --- B6, B7 -----------------------------------------------------------------

def _band(name: str, value: float) -> int:
    return next(points for lower, points in _SCORE_BANDS[name] if value >= lower)


def scorecard(params: dict[str, Any], *, credit: dict[str, Any], fate: int, rating: float,
              age_m: int, cv: float, gross_margin: float, monthly_avg: float) -> dict[str, int]:
    late = credit.get("late_max_days_24m", 0)
    inq = credit.get("inquiries_3m", 0)
    debt = credit.get("debt_to_inflow", 0.0)
    return {
        "late": 20 if late == 0 else (10 if late < 30 else 0),
        "inquiries": 10 if inq <= 1 else (6 if inq <= 3 else (3 if inq <= 5 else 0)),
        "debt": 10 if debt < 0.10 else (6 if debt < 0.30 else (3 if debt < 0.60 else 0)),
        "fate": int(params["scorecard"]["fate_points"][str(fate)]),
        "rating": _band("rating", rating),
        "age": _band("age_m", age_m),
        "volatility": 10 if cv < 0.25 else (7 if cv < 0.5 else (3 if cv < 0.8 else 0)),
        "gross_margin": _band("gross_margin", gross_margin),
        "monthly_avg": _band("monthly_avg", monthly_avg),
    }


def fate_alt_points(params: dict[str, Any], alt: dict[str, Any]) -> dict[str, int]:
    """B6 when FATE is thin: the 15 FATE points come from signals the scorecard does not already use
    (tax invoices every month, a real supply chain, declared payroll, age of the business registration)."""
    cap = params["fate"]["alt_points"]
    months = int(alt.get("invoice_months_12m") or 0)
    suppliers = int(alt.get("suppliers_with_history") or 0)
    employees = int(alt.get("employees_declared") or 0)
    reg_m = int(alt.get("registry_age_m") or 0)
    return {
        "invoice_regularity": int(cap["invoice_regularity"]) if months >= 12 else
        (round(cap["invoice_regularity"] * 0.6) if months >= 10 else (round(cap["invoice_regularity"] * 0.2) if months >= 8 else 0)),
        "supply_chain": int(cap["supply_chain"]) if suppliers >= 2 else (round(cap["supply_chain"] / 2) if suppliers == 1 else 0),
        "payroll": int(cap["payroll"]) if employees >= 3 else (round(cap["payroll"] * 2 / 3) if employees >= 1 else 0),
        "registry_age": int(cap["registry_age"]) if reg_m >= 36 else
        (round(cap["registry_age"] * 2 / 3) if reg_m >= 24 else (round(cap["registry_age"] / 3) if reg_m >= 12 else 0)),
    }


def seed_ratio(params: dict[str, Any], history: dict[str, Any] | None) -> dict[str, Any]:
    """Seed loan: ``seed.ratio[k]`` of the computed limit, k = good closed loans with BuoyUp (capped at the
    last step). From the second loan the step rises only when the WeBank business account showed
    real sales money: ≥ ``seed.min_webank_months`` months averaging ≥ ``seed.min_inflow_share`` of
    the tax revenue. Without it the loan stays a seed loan."""
    steps = [float(x) for x in params["seed"]["ratio"]]
    h = history or {}
    good = int(h.get("good_loans") or 0)
    confirmed = bool(h.get("webank_confirmed"))
    stage = min(good, len(steps) - 1) if confirmed else 0
    return {"stage": stage, "ratio": steps[stage], "good_loans": good, "webank_confirmed": confirmed,
            "held_back": good > 0 and not confirmed}


def grade_of(params: dict[str, Any], score: int) -> str:
    for grade in ("A", "B", "C", "D"):
        if score >= params["scorecard"]["grades"][grade]:
            return grade
    return "E"


def apply_penalties(grade: str, downgrades: int, hard_e: bool) -> str:
    if hard_e:
        return "E"
    return GRADES[min(len(GRADES) - 1, GRADES.index(grade) + downgrades)]


def rate_floor(params: dict[str, Any], amount: int, tenor_m: int, cost_of_funds: float) -> float:
    """B7 floor: cost of funds + processing cost ÷ (average balance × tenor in years)."""
    avg_balance = amount * float(params["rates"]["avg_balance_share"])
    if avg_balance <= 0 or tenor_m <= 0:
        return cost_of_funds
    return round(cost_of_funds + float(params["rates"]["processing_cost"]) / (avg_balance * tenor_m / 12), 4)


# --- B9: schedules -------------------------------------------------------------------

def tenors_for(params: dict[str, Any], borrower_type: str) -> list[int]:
    p = params["product"]
    return list(p["tenors"].get(borrower_type) or p["tenors"]["individual_business"])


def first_due_date(params: dict[str, Any], start: date, due_day: int) -> date:
    """The due day of the next month; if that is closer than ``product.first_due_min_days``, the
    month after [Đặt tay]."""
    first = add_months(date(start.year, start.month, 1), 1).replace(day=min(due_day, 28))
    if (first - start).days < int(params["product"]["first_due_min_days"]):
        first = add_months(first, 1)
    return first


def due_dates(params: dict[str, Any], start: date, due_day: int, tenor_m: int) -> list[date]:
    first = first_due_date(params, start, due_day)
    return [add_months(first, k) for k in range(tenor_m)]


def interest_for(outstanding: float, rate: float, days: int) -> int:
    """Interest on the outstanding principal for the actual number of days (year of 365)."""
    return round(outstanding * rate * days / 365)


def min_payment(params: dict[str, Any], amount: int, tenor_m: int, interest: int) -> int:
    """Interest of the period plus ``repay.min_principal_share`` of one equal-principal instalment."""
    return interest + math.ceil(params["repay"]["min_principal_share"] * amount / tenor_m)


def revenue_rate(params: dict[str, Any], amount: int, rate: float, tenor_m: int, prudent: float,
                 sweep_usable: float) -> float:
    """Share of last month's revenue for the revenue-based method: enough to repay principal and
    (flat upper bound of) interest within the tenor on the prudent revenue, at most the B5 cap."""
    total = amount + round(amount * rate * tenor_m / 12)
    need = ceil_pct(total / (prudent * tenor_m)) if prudent > 0 else sweep_usable
    return min(need, sweep_usable)


def schedule(params: dict[str, Any], *, amount: int, rate: float, tenor_m: int, method: str, start: date,
             due_day: int, prudent: float = 0.0, sweep_usable: float = 0.0) -> dict[str, Any]:
    """Projected schedule. Instalment: equal principal + interest by actual days on the outstanding.
    Revenue: each month the larger of the minimum and ``rate_rev × projected revenue`` (the prudent
    monthly revenue), never more than what is owed; the last period settles the rest."""
    dates = due_dates(params, start, due_day, tenor_m)
    rows: list[dict[str, Any]] = []
    outstanding, prev = amount, start
    base = amount // tenor_m
    rr = revenue_rate(params, amount, rate, tenor_m, prudent, sweep_usable) if method == "revenue" else None
    for k, d in enumerate(dates, start=1):
        days = (d - prev).days
        interest = interest_for(outstanding, rate, days)
        last = k == tenor_m
        if method == "installment":
            principal = outstanding if last else min(outstanding, base)
        else:
            minimum = min_payment(params, amount, tenor_m, interest)
            pay = max(minimum, round((rr or 0) * prudent))
            principal = outstanding if last else min(outstanding, max(0, pay - interest))
        rows.append({"k": k, "due_date": d.isoformat(), "days": days, "principal": principal, "interest": interest,
                     "payment": principal + interest, "outstanding_after": outstanding - principal})
        outstanding -= principal
        prev = d
        if outstanding <= 0:
            break
    total_interest = sum(r["interest"] for r in rows)
    return {"amount": amount, "rate": rate, "apr": rate, "tenor_m": tenor_m, "method": method,
            "method_label": METHOD_LABELS[method], "due_day": due_day, "revenue_rate": rr,
            "first_due_date": rows[0]["due_date"] if rows else None,
            "final_due_date": dates[-1].isoformat(), "rows": rows, "total_interest": total_interest,
            "total_due": amount + total_interest, "fees": 0,
            "first_payment": rows[0]["payment"] if rows else 0,
            "min_payment_first": min_payment(params, amount, tenor_m, rows[0]["interest"]) if rows else 0}


# --- B8: the limit, and the sheet ---------------------------------------------------------

def limit_caps(params: dict[str, Any], *, prudent: float, sweep_usable: float, rate: float, tenor_max: int,
               monthly_avg: float, group: int, borrower_type: str, fate_thin: bool = False,
               seed: dict[str, Any] | None = None) -> dict[str, Any]:
    """B8: the smallest of affordability over the longest tenor (cost share of the prudent revenue,
    flat interest upper bound), the group cap and the borrower-type cap (hộ kinh doanh 200.000);
    a thin FATE signal adds ``MIN(fate.thin_cap_mult × monthly revenue, fate.thin_cap_abs)``.
    The seed ratio then scales that computed limit (first loan 50 %)."""
    p = params["product"]
    affordability = prudent * tenor_max * sweep_usable / (1 + rate * tenor_max / 12)
    group_cap = round(p["group_cap_mult"][str(group)] * monthly_avg)
    type_cap = int(p["type_cap"].get(borrower_type, p["type_cap"]["company"]))
    caps: dict[str, float] = {"affordability": affordability, "group_cap": group_cap, "type_cap": type_cap}
    if fate_thin:
        caps["thin_fate_cap"] = min(round(float(params["fate"]["thin_cap_mult"]) * monthly_avg),
                                    int(params["fate"]["thin_cap_abs"]))
    binding = min(caps, key=lambda k: caps[k])
    computed = floor_to(max(0.0, caps[binding]), 100)
    ratio = float((seed or {}).get("ratio", 1.0))
    limit = computed
    if ratio < 1.0:
        # Never below the product minimum when the computed limit reaches it (testbench DS-07: a small
        # seller with a thin FATE signal would otherwise never get a first loan to build history with).
        limit = max(floor_to(computed * ratio, 100), min(computed, int(params["product"]["min_amount"])))
        binding = "seed_cap"
    return {"caps": caps, "binding": binding, "computed": computed, "seed_ratio": ratio, "limit": limit}


def option(oid: str, amount: int, *, rate: float, tenor_m: int) -> dict[str, Any]:
    """A limit option shown with its default terms: the longest tenor, equal-principal instalments
    (flat estimate; the exact schedule depends on the start date and due day)."""
    est_interest = round(amount * rate * (tenor_m + 1) / 24)  # equal principal: average balance ≈ half
    return {"id": oid, "amount": amount, "rate": rate, "tenor_m": tenor_m, "max_interest": est_interest,
            "total_due": amount + est_interest, "monthly_principal": amount // tenor_m if tenor_m else amount,
            "label": OPTION_LABELS.get(oid, "Mức người vay chọn")}


def _reason_codes(b3: dict[str, Any] | None, limit: int, binding: str, requested: int | None,
                  need: int | None, seed: dict[str, Any] | None = None, computed: int | None = None,
                  fate_thin: bool = False, caps: dict[str, float] | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if b3:
        price_cut = round(b3["qty"] * (b3["price_declared"] - b3["unit_price_used"]))
        if price_cut > 0:
            out.append({"code": "PRICE_FROM_INVOICE", "impact": -price_cut, "block": "B3",
                        "text": f"Giá nhập tính theo hóa đơn {fmt_num(b3['unit_price_used'])} tệ "
                                f"thay vì {fmt_num(b3['price_declared'])} tệ"})
        supplier_cut = round(b3["qty"] * b3["unit_price_used"]) - b3["plan_value"]
        if supplier_cut > 0:
            out.append({"code": "SUPPLIER_FACTOR", "impact": -supplier_cut, "block": "B3",
                        "text": "Phần hàng của nhà cung cấp chưa có hóa đơn với chị được tính giảm"})
        own = b3["deductions"]
        if own > 0:
            out.append({"code": "INVENTORY_AND_OWN_CAPITAL", "impact": -own, "block": "B3",
                        "text": "Trừ tồn kho, vốn tự có và khoản vay khác cho kế hoạch"})
    texts = {"affordability": "Khả năng trả từ doanh thu dự báo thận trọng trong kỳ hạn dài nhất",
             "group_cap": "Trần theo nhóm khách hàng", "type_cap": "Trần của hộ kinh doanh vay trực tuyến",
             "thin_fate_cap": "Dữ liệu liên ngân hàng còn ít: hạn mức có trần thấp hơn cho đến khi có thêm lịch sử"}
    base = need if need is not None else requested
    seed_cut = bool(seed) and float(seed.get("ratio", 1.0)) < 1.0 and computed is not None and computed > limit
    if (base is None or base <= limit) and not seed_cut:
        return out
    # B8 step by step, so the impacts add up from the need to the limit: the lowest cap, then the
    # thin-FATE cap, then the seed-loan fraction (explained even without a plan, i.e. no need).
    caps = caps or {}
    level = base if base is not None else (computed or 0)
    others = {k: v for k, v in caps.items() if k != "thin_fate_cap"}
    if others and base is not None:
        key = min(others, key=lambda k: others[k])
        lowest = floor_to(max(0.0, others[key]), 100)
        if lowest < level and key in texts:
            out.append({"code": key.upper(), "impact": -(level - lowest), "block": "B8", "text": texts[key]})
            level = lowest
    thin = caps.get("thin_fate_cap")
    if fate_thin and thin is not None and floor_to(thin, 100) < level:
        out.append({"code": "THIN_FATE_CAP", "impact": -(level - floor_to(thin, 100)), "block": "B8",
                    "text": texts["thin_fate_cap"]})
        level = floor_to(thin, 100)
    if seed_cut:
        pct = round(float(seed["ratio"]) * 100)
        why = ("chưa có đủ tiền bán hàng về tài khoản WeBank để nâng" if seed.get("held_back")
               else "hạn mức tăng khi chị trả tốt và tiền bán hàng về tài khoản WeBank đều đặn")
        out.append({"code": "SEED_LOAN", "impact": -(computed - limit), "block": "B8",
                    "text": f"Khoản vay mồi: {pct}% hạn mức tính được ({fmt_num(computed)} tệ); {why}"})
    elif not others and binding in texts and base is not None:  # older callers without the caps
        out.append({"code": binding.upper(), "impact": -(base - limit), "block": "B8", "text": texts[binding]})
    return out


def compute_sheet(params: dict[str, Any], *, borrower_type: str, plan: dict[str, Any] | None,
                  facts: dict[str, Any], penalties: int = 0, tier: int = 2) -> dict[str, Any]:
    """Limit sheet for one application. ``facts`` gathers Agent 1's tool results: revenue (tax),
    tax, credit, fate, rating, industry, supplier, statements_verified."""
    credit, revenue, tax = facts["credit"], facts["revenue"], facts["tax"]
    group = customer_group(credit)
    points = scorecard(params, credit=credit, fate=facts["fate"], rating=facts["rating"],
                       age_m=revenue["months_with_sales"], cv=revenue["cv_monthly"],
                       gross_margin=tax["gross_margin"], monthly_avg=revenue["monthly_avg_12m"])
    fate_thin = facts.get("fate_state") == "thin"
    alt_points = fate_alt_points(params, facts.get("fate_alt") or {}) if fate_thin else None
    if alt_points is not None:
        points["fate"] = sum(alt_points.values())
    seed = seed_ratio(params, facts.get("history"))
    score = sum(points.values())
    grade_before = grade_of(params, score)
    hard_e = credit.get("late_max_days_24m", 0) >= 90 or bool(credit.get("defaulted_within_24m"))
    grade = apply_penalties(grade_before, penalties, hard_e)
    rate = params["rates"].get(grade)  # E has no rate: reject instead of pricing up
    b5 = sweep_cap(tax["gross_margin"], tax["platform_fee"])
    tenors = tenors_for(params, borrower_type)
    sheet: dict[str, Any] = {
        "tier": tier, "borrower_type": borrower_type, "group": group, "score": score, "points": points,
        "grade_before": grade_before, "grade": grade, "rate": rate, "tenors": tenors, "tenor_max": max(tenors),
        "borderline": params["scorecard"]["borderline"][0] <= score < params["scorecard"]["borderline"][1],
        "fate_mode": "alt" if fate_thin else "fate",
        "blocks": {"B5": b5, "B6": {"score": score, "grade_before": grade_before, "grade": grade,
                                    **({"fate_alt": alt_points} if alt_points is not None else {})},
                   "B7": {"rate": rate}},
    }
    if rate is None:
        sheet.update(options=[], amount=0, limit=0, binding_cap="grade_e", reason_codes=[], requested=None,
                     need=None, suggested=0)
        return sheet
    b3 = None
    requested = need = None
    if plan:
        supplier = facts.get("supplier") or {"linked": False, "invoice_history": True}
        c = capital_need(params, plan, tax.get("invoice_unit_price_3m"), supplier)
        b3 = {**c, "qty": plan["qty"],
              "deductions": plan["inventory"] + plan["own_capital"] + plan.get("other_loans", 0)}
        requested, need = c["requested"], c["need"]
        sheet["blocks"]["B3"] = {k: c[k] for k in ("unit_price_used", "price_declared", "plan_value", "need",
                                                   "supplier_factor")}
        sheet["data_source_gap"] = c["data_source_gap"]
    b4 = prudent_revenue(params, revenue, facts["industry"], bool(facts.get("statements_verified")))
    caps = limit_caps(params, prudent=b4["prudent"], sweep_usable=b5["sweep_usable"], rate=rate,
                      tenor_max=sheet["tenor_max"], monthly_avg=revenue["monthly_avg_12m"], group=group,
                      borrower_type=borrower_type, fate_thin=fate_thin, seed=seed)
    limit = caps["limit"] if caps["limit"] >= params["product"]["min_amount"] else 0
    tenor = sheet["tenor_max"]
    options = [option("full", limit, rate=rate, tenor_m=tenor)] if limit > 0 else []
    for step, oid in zip(params["product"]["option_steps"], ("step70", "step50")):
        small = floor_to(limit * step, 100)
        if small >= params["product"]["min_amount"]:
            options.append(option(oid, small, rate=rate, tenor_m=tenor))
    suggested = min(limit, need) if need is not None else limit
    if suggested and suggested < params["product"]["min_amount"]:
        suggested = 0
    sheet.update(
        requested=requested, need=need, prudent=b4["prudent"], amount=limit, limit=limit, suggested=suggested,
        binding_cap=caps["binding"], options=options, tenor_m=tenor,
        reason_codes=_reason_codes(b3, limit, caps["binding"], requested, need, seed=seed,
                                   computed=caps["computed"], fate_thin=fate_thin, caps=caps["caps"]),
        revenue_rate_max_tenor=revenue_rate(params, limit, rate, tenor, b4["prudent"], b5["sweep_usable"])
        if limit else 0.0,
    )
    sheet["blocks"].update({
        "B4": {"forecast": b4["forecast"], "prudent": b4["prudent"], "growth_used": b4["growth_used"],
               "prudence": b4["prudence"]},
        "B8": {"affordability": round(caps["caps"]["affordability"]), "group_cap": caps["caps"]["group_cap"],
               "type_cap": caps["caps"]["type_cap"], "binding_cap": caps["binding"], "limit": limit,
               "suggested": suggested, "computed": caps["computed"],
               "seed": {"ratio": seed["ratio"], "stage": seed["stage"], "good_loans": seed["good_loans"],
                        "webank_confirmed": seed["webank_confirmed"]},
               **({"thin_fate_cap": caps["caps"]["thin_fate_cap"]} if fate_thin else {})},
        "B9": {"tenors": tenors, "tenor_max": tenor, "methods": list(METHODS),
               "revenue_rate_max_tenor": sheet["revenue_rate_max_tenor"],
               "min_principal_share": params["repay"]["min_principal_share"]},
    })
    return sheet


def clamp_amount(params: dict[str, Any], sheet: dict[str, Any], amount: int) -> int:
    """Amount the borrower picks: rounded down to 100 and kept within [min_amount, limit]."""
    limit = int(sheet.get("limit") or 0)
    lo = min(int(params["product"]["min_amount"]), limit)
    return max(lo, min(limit, floor_to(amount, 100)))


def seller_option(params: dict[str, Any], sheet: dict[str, Any], amount: int) -> dict[str, Any]:
    """Slider preview within the limit (no re-approval: the amount is within what the banks approved)."""
    full = next(o for o in sheet["options"] if o["id"] == "full")
    amount = clamp_amount(params, sheet, amount)
    if amount == full["amount"]:
        return full
    return option(f"seller_{amount}", amount, rate=full["rate"], tenor_m=full["tenor_m"])
