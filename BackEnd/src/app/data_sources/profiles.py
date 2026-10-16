"""Raw demo dossiers and the code that turns them into Agent 1's figures.

A dossier (profiles/<name>.json, made by scripts/gen_lan_profile.py) holds what the
data partners return: the store page, the business registry, platform payouts and
outgoing transfers per bank account, tax invoices, the credit report and the FATE
score. ``derive`` computes every quantity in agent1_xac_minh.md §3 ("Đại lượng tính
ra từ dòng tiền và thuế") from those rows, so the numbers the agents reason about
come from data, not from constants.
"""
from __future__ import annotations

import calendar
import json
import statistics
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent / "profiles"

# Event windows on the payout side: presale opens 17 days before the event and the
# platform settles within 12 days after it [Đặt tay]. 11.11 is the annual peak season.
EVENTS = {"11.11": (11, 11), "6.18": (6, 18)}
PEAK_EVENT = "11.11"
WINDOW_BEFORE, WINDOW_AFTER = 17, 12
GROWTH_CLAMP = (-0.30, 0.50)


@lru_cache(maxsize=None)
def load(name: str) -> dict[str, Any]:
    return json.loads((_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _month(d: date, back: int) -> tuple[int, int]:
    n = d.year * 12 + d.month - 1 - back
    return n // 12, n % 12 + 1


def _back3(d: date) -> date:
    y, m = _month(d, 3)
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _window(event: str, year: int) -> tuple[date, date]:
    m, d = EVENTS[event]
    day = date(year, m, d)
    return day - timedelta(days=WINDOW_BEFORE), day + timedelta(days=WINDOW_AFTER)


# Inflow figures that depend on which accounts are counted. Agent 1 §3: every figure is read
# from the accounts the seller declared (and consented to); an account declared later swaps
# these in (sources.include_hidden_accounts).
VOLUME_KEYS = ("first_inflow", "months_with_inflow", "peak_seasons", "monthly_avg_12m", "last_campaign",
               "two_peak_avg", "growth_3m", "inflow_20d", "cv_monthly", "spike_ratio", "monthly_12m")


def _volume(inflows: list[tuple[datetime, int, str]], as_of: date) -> dict[str, Any]:
    """Store age, campaigns, averages and growth over the given payout rows only."""
    by_month: dict[tuple[int, int], int] = {}
    for at, amount, _acc in inflows:
        by_month[(at.year, at.month)] = by_month.get((at.year, at.month), 0) + amount

    last12 = [_month(as_of, k) for k in range(12, 0, -1)]          # 12 complete months, oldest first
    m12 = [by_month.get(k, 0) for k in last12]
    total12 = sum(m12)

    def window_sum(lo: date, hi: date) -> int:
        return sum(a for at, a, _ in inflows if lo <= at.date() <= hi)

    first = min(at for at, _a, _c in inflows).date()
    # Completed event windows the store traded through, oldest first: (event, start, end).
    windows = sorted(((ev, *_window(ev, y)) for ev in EVENTS for y in range(first.year, as_of.year + 1)
                      if first <= _window(ev, y)[0] and _window(ev, y)[1] < as_of), key=lambda w: w[2])
    peaks = [w for w in windows if w[0] == PEAK_EVENT]
    recent_q = [by_month.get(_month(as_of, k), 0) for k in (3, 2, 1)]
    year_ago = [by_month.get(_month(as_of, k + 12), 0) for k in (3, 2, 1)]
    growth = sum(recent_q) / sum(year_ago) - 1 if sum(year_ago) else 0.0
    prev6 = [by_month.get(_month(as_of, k), 0) for k in range(7, 1, -1)]
    return {
        "first_inflow": first.isoformat(),
        "months_with_inflow": sum(1 for k in by_month if k < _month(as_of, 0)),
        "peak_seasons": len(peaks),
        "monthly_avg_12m": round(total12 / 12),
        "last_campaign": window_sum(*peaks[-1][1:]) if peaks else 0,
        "two_peak_avg": round(sum(window_sum(*w[1:]) for w in windows[-2:]) / 2) if len(windows) >= 2 else 0,
        "growth_3m": round(min(max(growth, GROWTH_CLAMP[0]), GROWTH_CLAMP[1]), 2),
        "inflow_20d": window_sum(as_of - timedelta(days=19), as_of),
        "cv_monthly": round(statistics.pstdev(m12) / (total12 / 12), 3) if total12 else 0.0,
        "spike_ratio": round(m12[-1] / (sum(prev6) / 6), 2) if sum(prev6) else 0.0,
        "monthly_12m": [{"month": f"{y}-{m:02d}", "amount": by_month.get((y, m), 0)} for y, m in last12],
    }


def tax_revenue(tax: dict[str, Any], as_of: date) -> dict[str, Any]:
    """Loan circle: revenue comes from the seller's own tax filings (sales invoices by month), never
    from another bank or the platform. Same quantities the old cash-flow block gave."""
    by_month: dict[tuple[int, int], int] = {}
    for s in tax["sales_invoices"]:
        key = (int(s["month"][:4]), int(s["month"][5:7]))
        by_month[key] = by_month.get(key, 0) + int(s["amount"])
    last12 = [_month(as_of, k) for k in range(12, 0, -1)]
    m12 = [by_month.get(k, 0) for k in last12]
    total12 = sum(m12)
    recent_q = [by_month.get(_month(as_of, k), 0) for k in (3, 2, 1)]
    year_ago = [by_month.get(_month(as_of, k + 12), 0) for k in (3, 2, 1)]
    growth = sum(recent_q) / sum(year_ago) - 1 if sum(year_ago) else 0.0
    prev6 = [by_month.get(_month(as_of, k), 0) for k in range(7, 1, -1)]
    done = [k for k in by_month if k < _month(as_of, 0) and by_month[k] > 0]
    first = min(done) if done else None
    peaks = sorted(k for k in done if k[1] == 11)
    return {
        "source": "tax", "first_sale_month": f"{first[0]}-{first[1]:02d}" if first else None,
        "months_with_sales": len(done), "peak_seasons": len(peaks),
        "monthly_avg_12m": round(total12 / 12),
        "growth_3m": round(min(max(growth, GROWTH_CLAMP[0]), GROWTH_CLAMP[1]), 2),
        "cv_monthly": round(statistics.pstdev(m12) / (total12 / 12), 3) if total12 else 0.0,
        "spike_ratio": round(m12[-1] / (sum(prev6) / 6), 2) if sum(prev6) else 0.0,
        "last_peak": by_month.get(peaks[-1], 0) if peaks else 0,
        "monthly_12m": [{"month": f"{y}-{m:02d}", "amount": by_month.get((y, m), 0)} for y, m in last12],
        "as_of": as_of.isoformat(),
    }


def derive(raw: dict[str, Any]) -> dict[str, Any]:
    """Scenario data in the shape sources.py serves to the agents."""
    as_of = date.fromisoformat(raw["as_of"])
    accounts = raw["seller"]["accounts"]
    declared = {a["id"] for a in accounts if a["declared"]}
    inflows = [(datetime.fromisoformat(at), amount, acc) for at, amount, acc in raw["bank_statement"]["inflows"]]
    on_declared = [row for row in inflows if row[2] in declared]
    by_month: dict[tuple[int, int], int] = {}
    for at, amount, _acc in inflows:
        by_month[(at.year, at.month)] = by_month.get((at.year, at.month), 0) + amount

    last12 = [_month(as_of, k) for k in range(12, 0, -1)]          # 12 complete months, oldest first
    total12 = sum(by_month.get(k, 0) for k in last12)
    w_lo, w_hi = date(*last12[0], 1), date(*_month(as_of, 0), 1) - timedelta(days=1)

    def in_12m(d: date) -> bool:
        return w_lo <= d <= w_hi

    tax = raw["tax"]
    sales12 = sum(s["amount"] for s in tax["sales_invoices"] if (int(s["month"][:4]), int(s["month"][5:])) in last12)
    b2b12 = sum(s["amount"] for s in tax["sales_invoices"]
                if s["buyer_type"] != "individual" and (int(s["month"][:4]), int(s["month"][5:])) in last12)
    to_declared = sum(a for at, a, acc in inflows if in_12m(at.date()) and acc in declared)
    hidden = sum(a for at, a, acc in inflows if in_12m(at.date()) and acc not in declared)

    pay_times = sorted(at for at, _a, _c in inflows)
    to_people: dict[str, int] = {}
    for t in raw["bank_statement"]["outflows"]:
        at = datetime.fromisoformat(t["at"])
        if t["to"]["kind"] != "individual" or not in_12m(at.date()):
            continue
        if any(timedelta(0) <= at - p <= timedelta(hours=24) for p in pay_times if p.date() >= at.date() - timedelta(days=1)):
            to_people[t["to"]["id"]] = to_people.get(t["to"]["id"], 0) + t["amount"]

    store = raw["store_page"]
    plan_item = raw["plan_draft"]["item"]
    q3 = [_month(as_of, k) for k in (3, 2, 1)]
    item_lines = [p for p in tax["purchase_invoices"]
                  if p["item"] == plan_item and (int(p["date"][:4]), int(p["date"][5:7])) in q3]
    purchases12 = [p for p in tax["purchase_invoices"] if in_12m(date.fromisoformat(p["date"]))]

    credit = raw["credit_report"]
    installments = sum(a.get("monthly_payment", 0) for a in credit["accounts"] if a["status"] == "current")
    volume = _volume(on_declared or inflows, as_of)
    monthly_avg = volume["monthly_avg_12m"]
    hidden_accounts = [{"bank": a["bank"], "tail": a["tail"],
                        "share": round(sum(x for at, x, acc in inflows if in_12m(at.date()) and acc == a["id"])
                                       / sales12, 4) if sales12 else 0.0}
                       for a in accounts if not a["declared"] and any(acc == a["id"] for _at, _x, acc in inflows)]

    # Loan circle: every revenue figure (and the debt ratio) comes from tax, never from bank inflows.
    revenue = tax_revenue(raw["tax"], as_of)
    return {
        "store": {"platform": store["platform"], "entity": store["operator"], "reg_no": store["reg_no"],
                  "rating": store["rating"], "category": store["category"], "category_code": store["category_code"],
                  "industry": store["industry"], "licenses": list(store["licenses_shown"]),
                  "province": store["province"], "opened": store.get("opened")},
        "registry": {"exists": True, "status": raw["registry"]["status"], "registered": raw["registry"]["registered"],
                     "type": raw["registry"]["type"],
                     "beneficial_owner_verified": raw["registry"]["beneficial_owner_verified"]},
        "entity_match": store["operator"] == raw["registry"]["name"] and store["reg_no"] == raw["registry"]["reg_no"],
        "inflows": {
            **volume,
            "to_declared_accounts_vs_tax_sales": round(to_declared / sales12, 2) if sales12 else 0.0,
            "hidden_account_share": round(hidden / sales12, 2) if sales12 else 0.0,
            "hidden_accounts": hidden_accounts,
            # The same figures once every account paid into is declared (after RISK_INFLOW_GAP).
            "with_hidden": _volume(inflows, as_of),
            "undeclared_platforms": [],
            "pass_through": {"share_to_individuals_24h": round(sum(to_people.values()) / total12, 2) if total12 else 0.0,
                             "distinct_individuals": len(to_people)},
            "as_of": raw["as_of"],
        },
        "tax": {
            "invoice_unit_price_3m": round(sum(p["amount"] for p in item_lines) / sum(p["qty"] for p in item_lines))
            if item_lines else None,
            "gross_margin": round(1 - sum(p["amount"] for p in purchases12) / sales12, 2) if sales12 else 0.0,
            "platform_fee": tax["platform_fee_schedule"][store["platform"]][store["category_code"]],
            "suppliers": sorted({p["supplier"] for p in purchases12}),
            "employees_declared": len(tax["payroll"]["employees"]),
            "inventory_estimate": tax["returns"][-1]["inventory_end"],
            "b2b_sales_share": round(b2b12 / sales12, 2) if sales12 else 0.0,
        },
        "credit": {
            "late_max_days_24m": max((d for a in credit["accounts"] for d in a["days_late_24m"]), default=0),
            "late_12m": sum(1 for a in credit["accounts"] for d in a["days_late_24m"][-12:] if d > 0),
            "inquiries_3m": sum(1 for q in credit["inquiries"] if _back3(as_of) < date.fromisoformat(q["date"]) <= as_of),
            "debt_to_inflow": round(installments / revenue["monthly_avg_12m"], 2) if revenue["monthly_avg_12m"] else 0.0,
            "monthly_installments": installments,
            "active_npl": any(a["status"] == "npl" for a in credit["accounts"]),
            "defaulted_within_24m": any(a["status"] == "default" for a in credit["accounts"]),
            "has_credit_elsewhere": bool(credit["accounts"]),
            "network_history": "none",
        },
        "revenue": revenue,
        "fate": {"value": raw["interbank"]["value"], "run_id": raw["interbank"]["run_id"],
                 "coverage": raw["interbank"].get("coverage")},
        "suppliers": json.loads(json.dumps(raw["suppliers"])),
        "plan": dict(raw["plan_draft"]),
        "notes_base": raw["notes_base"],
        "injected": False,
        "rationale_evidence": True,
        "profile": raw["profile"],
    }


def scenario(name: str) -> dict[str, Any]:
    return derive(load(name))


def seller_hint(name: str) -> dict[str, Any]:
    """What the seller of a demo dossier would type in: her store link and her declared account."""
    raw = load(name)
    acc = next(a for a in raw["seller"]["accounts"] if a["declared"])
    return {"profile": name, "store_url": raw["store_page"]["url"],
            "accounts": [{"bank": acc["bank"], "tail": acc["tail"]}]}


def hint_for_email(email: str) -> dict[str, Any] | None:
    for path in sorted(_DIR.glob("*.json")):
        if load(path.stem)["seller"]["email"] == email:
            return seller_hint(path.stem)
    return None
