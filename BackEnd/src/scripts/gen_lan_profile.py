"""Generate chị Lan's raw demo dossier: app/buoyup/profiles/lan.json.

The file holds what the data partners would return for her (store page, business
registry, 26 months of platform payouts on two bank accounts, outgoing transfers,
tax invoices, credit report, FATE score). Agent 1 derives every figure it uses
from these rows (app/buoyup/profiles.py); nothing in the file is a pre-computed
metric. The generator is deterministic (fixed seed) and checks its own output
against the figures in agent1_xac_minh.md §6, so a rerun reproduces the file.

    .venv/bin/python scripts/gen_lan_profile.py
"""
from __future__ import annotations

import calendar
import json
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "app" / "data_sources" / "profiles" / "lan.json"
AS_OF = date(2026, 10, 12)
WEBANK, CMB = "WEBANK-8826", "CMB-1203"
rng = random.Random(58812)

# Monthly platform payouts (CNY). Oct 2025..Sep 2026 is the 12-month window:
# total 2,000,400 (avg 166,700), Q3 2026 / Q3 2025 = 466,800 / 389,000 = 1.20,
# Sep 2026 / avg(Mar..Aug 2026) = 1.10, coefficient of variation 0.445.
MONTHLY = {
    (2024, 8): 28_000, (2024, 9): 52_000, (2024, 10): 70_000, (2024, 11): 165_000, (2024, 12): 90_000,
    (2025, 1): 85_000, (2025, 2): 60_000, (2025, 3): 88_000, (2025, 4): 95_000, (2025, 5): 110_000,
    (2025, 6): 210_000, (2025, 7): 120_000, (2025, 8): 128_000, (2025, 9): 141_000,
    (2025, 10): 150_000, (2025, 11): 276_870, (2025, 12): 151_730,
    (2026, 1): 125_000, (2026, 2): 78_000, (2026, 3): 118_000, (2026, 4): 126_000, (2026, 5): 148_000,
    (2026, 6): 360_000, (2026, 7): 136_000, (2026, 8): 142_000, (2026, 9): 188_800,
}
# Fixed sub-month totals: the 11.11 2025 window (25/10..23/11) is 52,000 + 248,000 = 300,000;
# the last 20 days (23/09..12/10/2026) are 50,800 + 60,300 = 111,100.
SEGMENTS = {
    (2025, 10): [(1, 24, 98_000), (25, 31, 52_000)],
    (2025, 11): [(1, 23, 248_000), (24, 30, 28_870)],
    (2026, 9): [(1, 22, 138_000), (23, 30, 50_800)],
}
PARTIAL_OCT_2026 = 60_300
FIRST_DAY = date(2024, 8, 2)
EVENTS = [(11, 11), (6, 18)]


def _bump(d: date) -> float:
    w = 1.0 + (0.25 if d.weekday() >= 4 else 0.0)
    for m, day in EVENTS:
        peak = date(d.year, m, day)
        gap = (d - peak).days
        if -10 <= gap <= 3:
            w *= 2.2 if gap >= -3 else 1.5
    return w


def _spread(days: list[date], total: int) -> list[tuple[date, int]]:
    weights = [_bump(d) * rng.lognormvariate(0, 0.35) for d in days]
    s = sum(weights)
    amounts = [int(total * w / s) for w in weights]
    amounts[weights.index(max(weights))] += total - sum(amounts)
    return list(zip(days, amounts))


def payouts() -> list[list]:
    rows: list[tuple[date, int]] = []
    for (y, m), total in MONTHLY.items():
        last = calendar.monthrange(y, m)[1]
        for lo, hi, amount in SEGMENTS.get((y, m), [(1, last, total)]):
            days = [date(y, m, d) for d in range(lo, hi + 1) if date(y, m, d) >= FIRST_DAY]
            rows += _spread(days, amount)
    rows += _spread([date(2026, 10, d) for d in range(1, AS_OF.day + 1)], PARTIAL_OCT_2026)
    # Lan withdraws some Sunday settlements to her older CMB card, which she did not declare at
    # first. Inside the 12-month window CMB gets exactly 13% of sales (260,052).
    target, cmb = round(0.13 * 2_000_400), 0
    out = []
    for d, amount in rows:
        in_window = date(2025, 10, 1) <= d <= date(2026, 9, 30)
        sunday = d.weekday() == 6
        account = CMB if sunday and (not in_window or cmb + amount <= target) else WEBANK
        if in_window and account == CMB:
            cmb += amount
        out.append([f"{d.isoformat()}T{rng.randint(8, 11):02d}:{rng.randint(0, 59):02d}", amount, account])
    gap = target - cmb
    if gap:
        donor = next(r for r in reversed(out) if r[2] == WEBANK and r[1] > gap + 1000
                     and "2026-01-01" <= r[0][:10] <= "2026-09-30" and date.fromisoformat(r[0][:10]).weekday() == 6)
        donor[1] -= gap
        out.insert(out.index(donor) + 1, [donor[0][:11] + "14:05", gap, CMB])
    return out


STAFF = [("NV-01", "Trần Mỹ", 1_400), ("NV-02", "Lý Hoa", 1_200), ("NV-03", "Vương Tú", 1_100),
         ("NV-04", "Trương Bình", 1_068), ("NV-05", "Lưu Phương", 1_000), ("NV-06", "Hoàng Kiệt", 900)]


def transfers(pay: list[list]) -> list[dict]:
    paid_days = {r[0][:10] for r in pay}
    out = []
    d = date(2025, 1, 10)
    while d <= AS_OF:
        day = d
        while day.isoformat() not in paid_days:
            day += timedelta(days=1)
        for code, name, amount in STAFF:
            out.append({"at": f"{day.isoformat()}T15:{rng.randint(0, 59):02d}", "amount": amount,
                        "to": {"kind": "individual", "id": code, "name": name}, "memo": "Lương cộng tác viên"})
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 10)
    d = date(2025, 4, 5)
    while d <= AS_OF:
        out.append({"at": f"{d.isoformat()}T10:00", "amount": 25_005,
                    "to": {"kind": "bank", "id": "CMB-LOAN-2503", "name": "CMB, trả góp khoản vay kinh doanh"},
                    "memo": "Trả góp"})
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 5)
    return out


JACKETS = {(2026, 7): (800, 60), (2026, 8): (1_000, 62), (2026, 9): (1_200, 63)}
OTHER_ITEMS = [("Váy liền", 48, 55), ("Áo len", 52, 60), ("Quần ống rộng", 41, 46), ("Áo sơ mi", 33, 38)]


def purchases() -> list[dict]:
    """Purchase invoices from SUP-0091, 60% of each month's sales; the 12-month window sums to
    exactly 1,200,240 so gross margin is 40%."""
    keys = list(MONTHLY)
    targets = {k: round(0.6 * MONTHLY[k]) for k in keys}
    window = [k for k in keys if (2025, 10) <= k <= (2026, 9)]
    targets[(2026, 9)] += 1_200_240 - sum(targets[k] for k in window)
    out = []
    for (y, m) in keys:
        left = targets[(y, m)]
        lines = []
        if (y, m) in JACKETS:
            qty, price = JACKETS[(y, m)]
            lines.append(("Áo khoác nữ", qty, price))
            left -= qty * price
        while left > 0:
            item, lo, hi = rng.choice(OTHER_ITEMS)
            price = rng.randint(lo, hi)
            qty = min(left // price, rng.randint(300, 900))
            if qty <= 0:
                break
            lines.append((item, qty, price))
            left -= qty * price
        if left:
            lines.append(("Phụ kiện đóng gói", 1, left))
        for i, (item, qty, price) in enumerate(lines):
            day = min(3 + 7 * i, calendar.monthrange(y, m)[1])
            out.append({"date": date(y, m, day).isoformat(), "supplier": "SUP-0091",
                        "seller_tax_id": "91440101MA5CXK0091", "item": item, "qty": qty,
                        "unit_price": price, "amount": qty * price})
    return out


def build() -> dict:
    pay = payouts()
    return {
        "profile": "lan",
        "as_of": AS_OF.isoformat(),
        "note": "Hồ sơ mẫu, dữ liệu dựng cho môi trường demo. Không phải người hay cửa hàng có thật.",
        "seller": {"name": "Lâm Lan", "email": "lan@buoyup.vn",
                   "accounts": [{"bank": "WeBank", "tail": "8826", "id": WEBANK, "declared": True},
                                {"bank": "CMB", "tail": "1203", "id": CMB, "declared": False}]},
        "store_page": {"platform": "douyin", "shop_id": "58812",
                       "url": "https://haohuo.jinritemai.com/views/shop/index?id=58812",
                       "shop_name": "Lan Lan · Thời trang nữ", "operator": "Hộ kinh doanh Lâm Lan",
                       "reg_no": "92440106MA9KLAN58P", "rating": 4.6, "followers": 48_200,
                       "category": "Thời trang nữ", "category_code": "women_apparel", "industry": "thời trang",
                       "licenses_shown": [], "province": "CN-GD", "opened": "2024-07-20"},
        "registry": {"source": "gsxt.gov.cn", "reg_no": "92440106MA9KLAN58P", "name": "Hộ kinh doanh Lâm Lan",
                     "owner": "Lâm Lan", "type": "individual_business", "status": "active",
                     "registered": "2023-05-18", "address": "Quận Hải Châu, Quảng Châu, Quảng Đông",
                     "scope": "Bán lẻ quần áo, phụ kiện thời trang qua mạng", "beneficial_owner_verified": True},
        "bank_statement": {"source": "Nền tảng thông tin dòng tiền", "payer": "Douyin Pay (công ty thanh toán của sàn)",
                           "columns": ["at", "amount", "account"], "inflows": pay, "outflows": transfers(pay)},
        "tax": {"source": "Thuế, qua 银税互动",
                "sales_invoices": [{"month": f"{y}-{m:02d}", "buyer_type": "individual", "amount": v,
                                    "channel": "Douyin"} for (y, m), v in MONTHLY.items()],
                "purchase_invoices": purchases(),
                "payroll": {"period": "2026-Q3", "employees": [c for c, _n, _a in STAFF]},
                "returns": [{"period": "2026-Q3", "inventory_end": 36_000}],
                "platform_fee_schedule": {"douyin": {"women_apparel": 0.05}}},
        "credit_report": {"source": "Tổ chức tín dụng thông tin", "as_of": AS_OF.isoformat(),
                          "accounts": [{"lender": "CMB", "type": "Vay kinh doanh trả góp", "opened": "2025-03-28",
                                        "amount": 300_000, "monthly_payment": 25_005, "status": "current",
                                        "days_late_24m": [0] * 18},
                                       {"lender": "ICBC", "type": "Thẻ tín dụng", "opened": "2023-09-02",
                                        "limit": 20_000, "status": "current", "days_late_24m": [0] * 24}],
                          "inquiries": [{"date": "2025-03-20", "by": "CMB"}, {"date": "2026-08-21", "by": "ICBC"},
                                        {"date": "2026-09-16", "by": "WeBank"}],
                          "public_records": []},
        "interbank": {"source": "FATE", "value": 3, "run_id": "fate-run-0912"},
        "suppliers": {
            "SUP-0091": {"name": "Xưởng may, có hóa đơn mua vào 3 tháng gần nhất", "linked": False,
                         "invoice_history": True, "lead_days": 7},
            "SUP-0137": {"name": "Nhà cung cấp mới", "linked": True, "invoice_history": False, "lead_days": 10},
        },
        "plan_draft": {"event": "11.11", "item": "Áo khoác nữ", "group": "quần áo", "brand": "",
                       "auth": "Tôi là chủ nhãn hiệu", "flavor": None, "qty": 5000, "price": 80,
                       "supplier": "SUP-0091", "inventory": 40000, "own_capital": 60000, "other_loans": 0},
        "notes_base": "Người bán cho biết 13% tiền hàng về tài khoản ở ngân hàng khác; đã khai và ủy quyền thêm.",
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    data = build()
    from app.data_sources import profiles
    got = profiles.derive(data)
    want = {"first_inflow": "2024-08-02", "months_with_inflow": 26, "peak_seasons": 2, "monthly_avg_12m": 166700,
            "last_campaign": 300000, "two_peak_avg": 330000, "growth_3m": 0.20, "inflow_20d": 111100,
            "cv_monthly": 0.445, "spike_ratio": 1.1, "to_declared_accounts_vs_tax_sales": 0.87,
            "hidden_account_share": 0.13}
    bad = {k: (got["inflows"][k], v) for k, v in want.items() if got["inflows"][k] != v}
    pt = got["inflows"]["pass_through"]
    if pt != {"share_to_individuals_24h": 0.04, "distinct_individuals": 6}:
        bad["pass_through"] = pt
    for k, v in {"invoice_unit_price_3m": 62, "gross_margin": 0.40, "inventory_estimate": 36000,
                 "employees_declared": 6, "b2b_sales_share": 0.0, "suppliers": ["SUP-0091"]}.items():
        if got["tax"][k] != v:
            bad[k] = (got["tax"][k], v)
    for k, v in {"late_max_days_24m": 0, "late_12m": 0, "inquiries_3m": 2, "debt_to_inflow": 0.15}.items():
        if got["credit"][k] != v:
            bad[k] = (got["credit"][k], v)
    if bad:
        raise SystemExit(f"Lệch so với agent1 §6, không ghi file: {bad}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    print(f"{OUT}: {OUT.stat().st_size // 1024} KB, {len(data['bank_statement']['inflows'])} khoản tiền về. "
          "Khớp agent1 §6.")
