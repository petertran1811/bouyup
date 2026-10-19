"""Generate the raw dossier of the Tmall sample store: app/data_sources/profiles/tmall.json.

THE STORE AND ITS OWNER ARE FICTIONAL. "Nhã Cầm Gia Dụng" (周雅琴, Zhōu Yǎqín), the shop link
https://zhouyaqinjujia.tmall.com/shop/view_shop.htm?shop_id=990072615, the registration number, the
supplier tax ids and every figure below are made up for the sample store list; they do not belong to any
real person, shop or business. Only the link format is Tmall's.

The file holds what the data partners would return (store page, business registry, 43 months of Tmall
payouts on the WeBank account, outgoing transfers with memos in the six expense groups, tax invoices,
credit report, FATE score with its coverage), in the same shape as lan.json. Agent 1 derives every figure
from these rows (app/data_sources/profiles.py). The generator is deterministic (fixed seed) and checks its
own output (store age, peaks, margin, invoice price = plan price, clean credit, grade A) before writing:

    cd BackEnd/src && ../.venv/bin/python scripts/gen_tmall_profile.py
"""
from __future__ import annotations

import calendar
import json
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "app" / "data_sources" / "profiles" / "tmall.json"
AS_OF = date(2026, 10, 12)
WEBANK = "WEBANK-3307"
SHOP_ID = "990072615"
SHOP_URL = f"https://zhouyaqinjujia.tmall.com/shop/view_shop.htm?shop_id={SHOP_ID}"
REG_NO = "92330110MA2HYAQ71K"
OPERATOR = "Hộ kinh doanh Chu Nhã Cầm"
rng = random.Random(990072615)

FIRST_MONTH, LAST_MONTH = (2023, 3), (2026, 9)       # 43 months of sales invoices
FIRST_DAY = date(2023, 3, 6)
# Kitchenware on Tmall: Spring Festival dip, 618 and 11.11 peaks, 12.12 and year-end gifts.
SEASON = {1: 0.92, 2: 0.70, 3: 0.95, 4: 1.00, 5: 1.05, 6: 1.55, 7: 0.95, 8: 0.97, 9: 1.05, 10: 1.08,
          11: 1.85, 12: 1.22}
# Underlying monthly level (CNY) by months since March 2023, linear between anchors.
LEVEL = [(0, 38_000), (10, 100_000), (22, 128_000), (34, 150_000), (42, 165_000)]


def _months() -> list[tuple[int, int]]:
    out, (y, m) = [], FIRST_MONTH
    while (y, m) <= LAST_MONTH:
        out.append((y, m))
        y, m = (y + (m == 12), m % 12 + 1)
    return out


def _level(n: int) -> float:
    for (n0, v0), (n1, v1) in zip(LEVEL, LEVEL[1:]):
        if n <= n1:
            return v0 + (v1 - v0) * (n - n0) / (n1 - n0)
    return LEVEL[-1][1]


MONTHLY = {k: round(_level(i) * SEASON[k[1]] * rng.uniform(0.96, 1.04) / 100) * 100
           for i, k in enumerate(_months())}
PARTIAL_OCT_2026 = 62_400   # 1..12/10/2026, after the last complete month
EVENTS = [(11, 11), (6, 18), (12, 12)]


def _bump(d: date) -> float:
    w = 1.0 + (0.20 if d.weekday() >= 4 else 0.0)
    for m, day in EVENTS:
        gap = (d - date(d.year, m, day)).days
        if -10 <= gap <= 3:
            w *= 2.2 if gap >= -3 else 1.5
    return w


def _spread(days: list[date], total: int) -> list[tuple[date, int]]:
    weights = [_bump(d) * rng.lognormvariate(0, 0.30) for d in days]
    s = sum(weights)
    amounts = [int(total * w / s) for w in weights]
    amounts[weights.index(max(weights))] += total - sum(amounts)
    return list(zip(days, amounts))


def payouts() -> list[list]:
    """Tmall settles the month's sales into the WeBank account, one payout a day (all declared)."""
    rows: list[tuple[date, int]] = []
    for (y, m), total in MONTHLY.items():
        days = [date(y, m, d) for d in range(1, calendar.monthrange(y, m)[1] + 1) if date(y, m, d) >= FIRST_DAY]
        rows += _spread(days, total)
    rows += _spread([date(2026, 10, d) for d in range(1, AS_OF.day + 1)], PARTIAL_OCT_2026)
    return [[f"{d.isoformat()}T{rng.randint(8, 11):02d}:{rng.randint(0, 59):02d}", amount, WEBANK]
            for d, amount in rows]


# (item, supplier, wholesale price range). The plan item is bought at a fixed 68 in Q3 2026.
PLAN_ITEM, PLAN_PRICE = "Nồi chống dính 28cm", 68
ITEMS = [(PLAN_ITEM, "SUP-2207", 64, 70), ("Chảo gang đúc 32cm", "SUP-2207", 86, 96),
         ("Bộ dao inox 5 món", "SUP-2207", 46, 54), ("Giá inox để gia vị", "SUP-2207", 22, 27),
         ("Thớt gỗ tre kháng khuẩn", "SUP-2231", 18, 23), ("Hộp thủy tinh giữ nhiệt (bộ 3)", "SUP-2231", 27, 32)]
PLAN_LINES = {(2026, 7): 700, (2026, 8): 760, (2026, 9): 820}
SUPPLIER_TAX_ID = {"SUP-2207": "91330784MA2ZQS2207", "SUP-2231": "91350211MA8TRE2231"}
COST_SHARE = 0.61   # purchases ≈ 61 % of sales: gross margin ≈ 39 %


def purchases() -> list[dict]:
    out = []
    for (y, m), sales in MONTHLY.items():
        left = round(COST_SHARE * sales)
        lines = []
        if (y, m) in PLAN_LINES:
            qty = PLAN_LINES[(y, m)]
            lines.append((PLAN_ITEM, "SUP-2207", qty, PLAN_PRICE))
            left -= qty * PLAN_PRICE
        pool = [it for it in ITEMS if not ((y, m) in PLAN_LINES and it[0] == PLAN_ITEM)]
        while left > 0:
            item, sup, lo, hi = rng.choice(pool)
            price = rng.randint(lo, hi)
            qty = min(left // price, rng.randint(150, 700))
            if qty <= 0:
                break
            lines.append((item, sup, qty, price))
            left -= qty * price
        for i, (item, sup, qty, price) in enumerate(lines):
            day = min(2 + 3 * i, calendar.monthrange(y, m)[1])
            out.append({"date": date(y, m, day).isoformat(), "supplier": sup, "seller_tax_id": SUPPLIER_TAX_ID[sup],
                        "item": item, "qty": qty, "unit_price": price, "amount": qty * price})
    return out


STAFF = [("NV-01", "Lục Tĩnh (đóng gói)", 5_600), ("NV-02", "Hà Mẫn (chăm sóc khách)", 5_900),
         ("NV-03", "Tào Dương (chụp ảnh, livestream)", 6_400), ("NV-04", "Phương Lỗi (kho)", 5_300)]
COURIER = {"kind": "company", "id": "LOG-0571", "name": "Công ty chuyển phát nhanh"}
ADS = {"kind": "platform", "id": "ADS-TM", "name": "Tài khoản quảng cáo trên sàn"}
TAX = {"kind": "tax", "id": "TAX-ZJ", "name": "Cục thuế Hàng Châu (qua 银税互动)"}
METAL = {"kind": "supplier", "id": "SUP-2207", "name": "Xưởng nồi chảo inox Vĩnh Khang"}
BAMBOO = {"kind": "supplier", "id": "SUP-2231", "name": "Xưởng đồ tre và thủy tinh Hạ Môn"}
WAREHOUSE = {"kind": "company", "id": "WH-0110", "name": "Kho thuê ngoài Dư Hàng"}
LOAN_PAYMENT = 10_600


def transfers(buys: list[dict]) -> list[dict]:
    """Twelve months of business payments, oldest first (the spending feed takes them in this order):
    small items early in each month, the supplier paid in weekly tranches of the month's invoices."""
    out = []
    month = (2025, 10)
    while date(*month, 1) <= AS_OF:
        y, m = month
        prev = MONTHLY.get((y - (m == 1), (m - 2) % 12 + 1), 0) or MONTHLY[LAST_MONTH]
        by_sup: dict[str, int] = {}
        for p in buys:
            if p["date"][:7] == f"{y}-{m:02d}":
                by_sup[p["supplier"]] = by_sup.get(p["supplier"], 0) + p["amount"]
        if not by_sup:  # October 2026: pay on the September invoices' pattern
            by_sup = {"SUP-2207": round(0.45 * prev), "SUP-2231": round(0.16 * prev)}
        rows = [
            (2, round(0.030 * prev, -1), COURIER, f"Cước 快递 tháng {(m - 2) % 12 + 1} (giao hàng)"),
            (4, round(0.028 * prev, -1), ADS, "Nạp 直通车 quảng cáo gian hàng Tmall"),
            (5, LOAN_PAYMENT, {"kind": "bank", "id": "BOCOM-LOAN-2506", "name": "BOCOM, khoản vay kinh doanh"},
             "Trả góp"),
            (6, round(by_sup["SUP-2207"] / 2), METAL, "Thanh toán 货款 nhập hàng đợt 1"),
            (9, round(0.011 * prev, -1), TAX, "Nộp thuế 增值税 và phụ thu tháng trước"),
        ]
        rows += [(10, amount, {"kind": "individual", "id": code, "name": name}, "Lương nhân viên")
                 for code, name, amount in STAFF]
        rows += [
            (13, by_sup.get("SUP-2231", 0), BAMBOO, "Thanh toán 货款 đồ tre, hộp thủy tinh"),
            (16, round(0.012 * prev, -1), ADS, "Nạp 巨量千川 quảng cáo video ngoài sàn"),
            (18, 6_000, WAREHOUSE, "Thuê kho 仓储 tháng này"),
            (20, by_sup["SUP-2207"] - round(by_sup["SUP-2207"] / 2), METAL, "Thanh toán 货款 nhập hàng đợt 2"),
            (25, round(0.010 * prev, -1), COURIER, "Phí 快递 trả hàng, đổi hàng"),
        ]
        for day, amount, to, memo in rows:
            at = date(y, m, day)
            if at > AS_OF or amount <= 0:
                continue
            out.append({"at": f"{at.isoformat()}T{rng.randint(13, 17):02d}:{rng.randint(0, 59):02d}",
                        "amount": int(amount), "to": dict(to), "memo": memo})
        month = (y + (m == 12), m % 12 + 1)
    return out


def build() -> dict:
    pay = payouts()
    buys = purchases()
    return {
        "profile": "tmall",
        "as_of": AS_OF.isoformat(),
        "note": "Hồ sơ mẫu dựng sẵn. Cửa hàng, chủ cửa hàng, số đăng ký, nhà cung cấp và mọi số liệu đều hư cấu; "
                "chỉ định dạng link là của Tmall. Không phải người hay cửa hàng có thật.",
        "seller": {"name": "Chu Nhã Cầm", "name_hanzi": "周雅琴", "name_pinyin": "Zhōu Yǎqín",
                   "email": "nhacam.tmall@buoyup.vn",
                   "accounts": [{"bank": "WeBank", "tail": "3307", "id": WEBANK, "declared": True}]},
        "store_page": {"platform": "tmall", "shop_id": SHOP_ID, "url": SHOP_URL,
                       "shop_name": "Nhã Cầm Gia Dụng · 雅琴居家厨具", "operator": OPERATOR,
                       "reg_no": REG_NO, "rating": 4.8, "followers": 86_400,
                       "category": "Đồ gia dụng nhà bếp", "category_code": "kitchenware", "industry": "đồ gia dụng",
                       "licenses_shown": [], "province": "CN-ZJ", "opened": "2023-02-20"},
        "registry": {"source": "gsxt.gov.cn", "reg_no": REG_NO, "name": OPERATOR,
                     # The owner's registered name in its Vietnamese reading (as for chị Lan); the Chinese name is
                     # kept apart so the shared sample ID card (示例用户) is "not comparable", not a mismatch.
                     "owner": "Chu Nhã Cầm", "owner_hanzi": "周雅琴", "owner_pinyin": "Zhōu Yǎqín",
                     "type": "individual_business", "status": "active", "registered": "2022-11-08",
                     "address": "Quận Dư Hàng, Hàng Châu, Chiết Giang",
                     "scope": "Bán lẻ đồ dùng nhà bếp, đồ gia dụng qua mạng", "beneficial_owner_verified": True},
        "bank_statement": {"source": "Nền tảng thông tin dòng tiền", "payer": "Công ty thanh toán của Tmall",
                           "columns": ["at", "amount", "account"], "inflows": pay, "outflows": transfers(buys)},
        "tax": {"source": "Thuế, qua 银税互动",
                "sales_invoices": [{"month": f"{y}-{m:02d}", "buyer_type": "individual", "amount": v,
                                    "channel": "Tmall"} for (y, m), v in MONTHLY.items()],
                "purchase_invoices": buys,
                "payroll": {"period": "2026-Q3", "employees": [c for c, _n, _a in STAFF]},
                "returns": [{"period": "2026-Q3", "inventory_end": 42_000}],
                "platform_fee_schedule": {"tmall": {"kitchenware": 0.05}}},
        "credit_report": {"source": "Tổ chức tín dụng thông tin", "as_of": AS_OF.isoformat(),
                          "accounts": [{"lender": "BOCOM", "type": "Vay kinh doanh trả góp", "opened": "2025-06-15",
                                        "amount": 120_000, "monthly_payment": LOAN_PAYMENT, "status": "current",
                                        "days_late_24m": [0] * 16},
                                       {"lender": "CMB", "type": "Thẻ tín dụng", "opened": "2021-04-09",
                                        "limit": 30_000, "status": "current", "days_late_24m": [0] * 24}],
                          "inquiries": [{"date": "2025-06-10", "by": "BOCOM"}, {"date": "2026-03-02", "by": "CMB"},
                                        {"date": "2026-09-24", "by": "WeBank"}],
                          "public_records": []},
        "interbank": {"source": "FATE", "value": 2, "run_id": "fate-run-1007", "coverage": {"banks": 3, "months": 30}},
        "suppliers": {
            "SUP-2207": {"name": "Xưởng nồi chảo inox Vĩnh Khang, có hóa đơn mua vào 3 tháng gần nhất", "linked": False,
                         "invoice_history": True, "lead_days": 6},
            "SUP-2231": {"name": "Xưởng đồ tre và thủy tinh Hạ Môn, có hóa đơn mua vào", "linked": False,
                         "invoice_history": True, "lead_days": 8},
        },
        "plan_draft": {"event": "11.11", "item": PLAN_ITEM, "group": "khác",
                       "group_other": "Đồ gia dụng nhà bếp: nồi, chảo, dao, thớt", "brand": "",
                       "auth": "Tôi là chủ nhãn hiệu", "flavor": None, "qty": 4000, "price": PLAN_PRICE,
                       "supplier": "SUP-2207", "inventory": 30000, "own_capital": 50000, "other_loans": 0},
        "notes_base": "Toàn bộ tiền hàng Tmall về một tài khoản WeBank đã khai; nhà cung cấp có hóa đơn đều đặn.",
    }


def check(data: dict) -> dict:
    """What the sample must show; returns the problems (empty: write the file)."""
    from app.core import algorithm
    from app.core.params import DEFAULT_PARAMS as DEFAULTS
    from app.data_sources import profiles

    got = profiles.derive(data)
    rev, tax, credit = got["revenue"], got["tax"], got["credit"]
    cov = data["interbank"]["coverage"]
    want = {"months_with_sales": rev["months_with_sales"] >= 40, "peak_seasons": rev["peak_seasons"] >= 2,
            "spike_ratio": rev["spike_ratio"] < 1.5, "growth_3m": 0.0 < rev["growth_3m"] < 0.3,
            "monthly_avg_12m": rev["monthly_avg_12m"] >= 150_000,
            "invoice_unit_price_3m": tax["invoice_unit_price_3m"] == PLAN_PRICE,
            "gross_margin": 0.35 <= tax["gross_margin"] <= 0.45,
            "suppliers": tax["suppliers"] == ["SUP-2207", "SUP-2231"],
            "inventory": data["plan_draft"]["inventory"] <= 1.5 * tax["inventory_estimate"],
            "b2b_sales_share": tax["b2b_sales_share"] == 0.0,
            "late": credit["late_max_days_24m"] == 0 and credit["late_12m"] == 0,
            "inquiries_3m": credit["inquiries_3m"] <= 1, "debt_to_inflow": credit["debt_to_inflow"] < 0.10,
            "has_credit_elsewhere": credit["has_credit_elsewhere"], "store_matches_registry": got["store_matches_registry"],
            "goods_mix": 4 <= len(got["goods_mix"]) <= 6,
            "to_declared": got["inflows"]["to_declared_accounts_vs_tax_sales"] == 1.0,
            "fate_coverage": cov["banks"] >= 2 and cov["months"] >= 12}
    bad = {k: v for k, v in want.items() if not v}
    points = algorithm.scorecard(DEFAULTS, credit=credit, fate=got["fate"]["value"], rating=got["store"]["rating"],
                                 age_m=rev["months_with_sales"], cv=rev["cv_monthly"], gross_margin=tax["gross_margin"],
                                 monthly_avg=rev["monthly_avg_12m"])
    grade = algorithm.grade_of(DEFAULTS, sum(points.values()))
    if grade != "A":
        bad["grade"] = (grade, points)
    from app.core.cashflow import classify
    groups = {classify({"kind": "other", "memo": t["memo"], "payee": t["to"]})
              for t in data["bank_statement"]["outflows"]}
    if not {"goods", "marketing", "logistics", "staff", "tax"} <= groups or "other" in groups:
        bad["expense_groups"] = sorted(str(g) for g in groups)
    summary = {"months_with_sales": rev["months_with_sales"], "peak_seasons": rev["peak_seasons"],
               "monthly_avg_12m": rev["monthly_avg_12m"], "growth_3m": rev["growth_3m"], "cv": rev["cv_monthly"],
               "spike": rev["spike_ratio"], "gross_margin": tax["gross_margin"], "debt": credit["debt_to_inflow"],
               "score": sum(points.values()), "grade": grade, "goods": [g["item"] for g in got["goods_mix"]]}
    return {"bad": bad, "summary": summary}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    data = build()
    result = check(data)
    print(result["summary"])
    if result["bad"]:
        raise SystemExit(f"Hồ sơ Tmall chưa đạt, không ghi file: {result['bad']}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    print(f"{OUT}: {OUT.stat().st_size // 1024} KB, {len(data['bank_statement']['inflows'])} khoản tiền về, "
          f"{len(data['bank_statement']['outflows'])} khoản chi.")
