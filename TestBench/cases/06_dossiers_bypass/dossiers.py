"""50 loan dossiers for the bypass bench (17/10/2026).

Built from the team's four standard dossiers (Backend_CCCD/chuan_ho_so: fashion, cosmetics, grocery,
electronics; figures converted from VND to CNY at 3.600 VND/CNY) and laid onto BuoyUp's data model. Each
dossier is one seller: an honest one checks the system grants the right limit; a dishonest one tries to
get money it should not (inflated figures, hidden prohibited goods, someone else's identity, abuse of the
flow). Difficulty 1 (anyone can try it) to 5 (needs knowledge of the rules or several steps).

``expect`` is the SECURE outcome; the bench passes when the system ends there.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable

from app.data_sources import sources

VND_PER_CNY = 3600

# The four standard dossiers (chuan_ho_so/caN_*/csv): monthly net receipts, rating, margin, the planned item.
ARCHETYPES: dict[str, dict[str, Any]] = {
    "thoi_trang": {"label": "Thời trang (Shop A · Anh Thư)", "monthly_vnd": 100_000_000, "rating": 4.5, "margin": 0.38,
                   "industry": "thời trang", "category": "Thời trang nữ", "group": "quần áo",
                   "item": "Áo thun nữ cổ tròn", "qty": 5000, "price_vnd": 80_000, "event": "11.11"},
    "my_pham": {"label": "Mỹ phẩm (Shop B · Hà Linh)", "monthly_vnd": 520_000_000, "rating": 4.8, "margin": 0.45,
                "industry": "mỹ phẩm", "category": "Mỹ phẩm", "group": "khác", "group_other": "mỹ phẩm dưỡng da",
                "item": "Serum dưỡng ẩm 30ml", "qty": 400, "price_vnd": 420_000, "event": "11.11"},
    "tap_hoa": {"label": "Tạp hóa (Shop C · Cô Ba)", "monthly_vnd": 85_000_000, "rating": 4.6, "margin": 0.22,
                "industry": "tạp hóa", "category": "Tạp hóa", "group": "thực phẩm đóng gói",
                "item": "Gạo ST25 túi 5kg", "qty": 220, "price_vnd": 318_000, "event": "Tết"},
    "linh_kien": {"label": "Linh kiện (Shop D · Đức Minh)", "monthly_vnd": 150_000_000, "rating": 4.2, "margin": 0.18,
                  "industry": "điện tử", "category": "Điện tử", "group": "điện tử",
                  "item": "RAM DDR4 16GB", "qty": 100, "price_vnd": 1_525_500, "event": "11.11"},
}


def _cny(vnd: float) -> int:
    return round(vnd / VND_PER_CNY)


def profile(arch: str, *, scale: float = 1.0, **overrides: Any) -> dict[str, Any]:
    """Scenario data (the shape sources.py serves) for one seller of an archetype."""
    a = ARCHETYPES[arch]
    d = copy.deepcopy(sources.SCENARIOS["lan"][3])
    base = d["revenue"]["monthly_avg_12m"]
    monthly = _cny(a["monthly_vnd"]) * scale
    k = monthly / base
    rev = d["revenue"]
    rev["monthly_12m"] = [{"month": m["month"], "amount": round(m["amount"] * k)} for m in rev["monthly_12m"]]
    rev["monthly_avg_12m"] = round(sum(m["amount"] for m in rev["monthly_12m"]) / 12)
    rev["last_peak"] = round(rev["last_peak"] * k)
    price = round(_cny(a["price_vnd"]) * 1.0, 2)
    d["tax"].update(invoice_unit_price_3m=price, gross_margin=a["margin"],
                    inventory_estimate=round(d["tax"]["inventory_estimate"] * k))
    d["credit"]["monthly_installments"] = round(d["credit"]["monthly_installments"] * k)
    d["store"].update(rating=a["rating"], industry=a["industry"], category=a["category"])
    d["plan"].update(event=a["event"], item=a["item"], group=a["group"], qty=a["qty"], price=price, supplier="",
                     brand="", auth="", inventory=round(d["plan"]["inventory"] * k * 0.5),
                     own_capital=round(d["plan"]["own_capital"] * k * 0.5), group_other=a.get("group_other", ""))
    for dotted, value in overrides.items():
        node = d
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    return d


_REGISTERED: dict[str, str] = {}


def register(key: str, data: dict[str, Any], label: str) -> str:
    """Add a dossier as a demo store (a shop id of its own); returns its link."""
    if key not in _REGISTERED:
        shop_id = str(59000 + len(_REGISTERED) + 1)
        data = copy.deepcopy(data)
        if data["store"].get("reg_no"):
            data["store"]["reg_no"] = f"92440106TB{shop_id}"
            data["entity_match"] = data.get("entity_match", True)
        sources.SCENARIOS[key] = (shop_id, label, "testbench", data)
        sources._BY_SHOP_ID[shop_id] = key
        if data["store"].get("reg_no"):
            sources._BY_REG_NO[data["store"]["reg_no"]] = key
        _REGISTERED[key] = shop_id
    return sources.demo_url(key)


@dataclass
class Dossier:
    id: str
    title: str
    arch: str
    difficulty: int                     # 1 easy … 5 hard
    kind: str                           # "trung thực" | "khai gian" | "lạm dụng luồng"
    technique: str                      # how the seller tries to cheat (or "—")
    expect: str                         # secure outcome, in words
    data: dict[str, Any]
    borrower_type: str = "individual_business"
    run: Callable[..., dict[str, Any]] | None = None   # set in test_dossiers.py
    params: dict[str, Any] = field(default_factory=dict)
