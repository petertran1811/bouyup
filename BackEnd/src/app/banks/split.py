"""Bank catalog logic (B12): who may fund a loan and how it is split.

``eligible_banks`` is called by Agent 3 (bank policies) and Agent 4 (split).
Shares are handled in basis points (1 bp = 0.01 %) so "two decimals, total
exactly 100.00 %" is checked on integers, never on floats.

Split rule (deterministic, documented for the bank contracts):
1. candidates = eligible banks; banks where the seller declared a receiving
   account come first (declaration order), then by remaining limit, then code;
2. use as many banks as possible, at most ``floor(1 / largest min_share)`` and never
   more than 3, keeping the first candidate when any set with it fits; among sets of
   the same size, the first in candidate order that fits;
3. every bank gets the minimum share; the rest goes to the banks in candidate
   order (the lead bank first), each up to its cap;
4. a bank's cap is the smallest of: its ``max_share`` (percent of the loan), its
   ``max_share_amount`` (most it funds in one loan) and its remaining limit; its part
   must also reach ``min_share_amount``. A set that cannot fit is skipped.
Chị Lan (CN, hạng C, 139.900, khai WeBank + CMB): WEBANK 40 / CMB 30 / ICBC 30.

The caps, the rate band, the tenor and the store rules come from the bank catalog of
the BuoyUp Chain service once it is synced (``chain_sync``); in local mode the seed
policies have none of them, so only rule 1–3 and the remaining limit apply.
"""

from __future__ import annotations

from datetime import date
from itertools import combinations
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform.tables import BuBank
from app.platform.db.tables import utcnow

GRADES = "ABCDE"
MASTER_CODE = "MASTER"
MAX_BANKS = 3
BP_TOTAL = 10_000


def vn_number(value: float | int) -> str:
    """139900 -> '139.900' (Vietnamese thousands separator)."""
    return f"{int(round(value)):,}".replace(",", ".")


def remaining_limit(bank: BuBank) -> int:
    return max(0, int(bank.limit_total) - int(bank.limit_used))


def catalog(session: Session, region: str | None = None) -> list[BuBank]:
    """Every real bank (the MASTER key row is excluded), optionally one region."""
    stmt = select(BuBank).where(BuBank.code != MASTER_CODE).order_by(BuBank.region, BuBank.code)
    if region:
        stmt = stmt.where(BuBank.region == region)
    return list(session.scalars(stmt))


def get_bank(session: Session, code: str) -> BuBank | None:
    if not code or code.upper() == MASTER_CODE:
        return None
    return session.get(BuBank, code.upper())


def grade_ok(grade: str, min_grade: str) -> bool:
    if grade not in GRADES or min_grade not in GRADES:
        return False
    return GRADES.index(grade) <= GRADES.index(min_grade)


def min_share_bp(bank: BuBank, params: dict[str, Any] | None = None) -> int:
    platform = float(((params or {}).get("banks") or {}).get("min_share", 0.30))
    own = float((bank.policy or {}).get("min_share", platform))
    return int(round(max(platform, own) * BP_TOTAL))


def _months_between(start: str | None, end: date) -> int | None:
    try:
        d = date.fromisoformat(str(start)[:10])
    except (TypeError, ValueError):
        return None
    return (end.year - d.year) * 12 + end.month - d.month - (1 if end.day < d.day else 0)


def seller_terms(doc: dict[str, Any], option: dict[str, Any] | None = None,
                 today: date | None = None) -> dict[str, Any]:
    """What bank rules about the shop and the loan need: store rating, store age in
    months, loan length in days (grace + tenor). ``None`` when unknown (rule skipped)."""
    stores = doc.get("stores") or []
    rating = next((s.get("rating") for s in stores if s.get("rating") is not None), None)
    opened = next((s.get("opened") for s in stores if s.get("opened")), None)
    if option is None:
        offer = doc.get("offer") or {}
        wanted = (doc.get("decision") or {}).get("option_id") or (doc.get("proposal") or {}).get("option_id")
        option = next((o for o in offer.get("options") or [] if o.get("id") == wanted), None) or offer.get("card")
    tenor_days = None
    if option and option.get("tenor_m"):
        tenor_days = int(option.get("grace_days") or 0) + int(option["tenor_m"]) * 30
    return {"rating": float(rating) if rating is not None else None,
            "store_age_months": _months_between(opened, today or utcnow().date()),
            "tenor_days": tenor_days}


def max_share_bp(bank: BuBank) -> int:
    return int(round(float((bank.policy or {}).get("max_share", 1.0)) * BP_TOTAL))


def cap_amount(bank: BuBank, amount: int) -> int:
    """Most this bank may fund of a loan of ``amount``."""
    caps = [remaining_limit(bank), amount * max_share_bp(bank) // BP_TOTAL]
    if (bank.policy or {}).get("max_share_amount"):
        caps.append(int(bank.policy["max_share_amount"]))
    return max(0, min(caps))


def _fmt_dec(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def _ineligible_reason(
    bank: BuBank, *, region: str, tier: int, grade: str, amount: int, category: str, rate: float,
    params: dict[str, Any] | None, seller: dict[str, Any] | None = None,
) -> str | None:
    policy = bank.policy or {}
    seller = seller or {}
    if not bank.active:
        return "Ngân hàng đang tạm dừng nhận khoản mới"
    if bank.region != region:
        return f"Khác khu vực (ngân hàng ở {bank.region})"
    if not bank.public_key:
        return "Ngân hàng chưa đăng ký khóa mã hóa"
    if tier not in (policy.get("tiers") or [1, 2]):
        return f"Không nhận khoản vay tầng {tier}"
    min_grade = str(policy.get("min_grade", "C"))
    if not grade_ok(grade, min_grade):
        return f"Chỉ nhận hạng {min_grade} trở lên"
    min_amount = int(policy.get("min_amount", 0))
    if amount < min_amount:
        return f"Khoản vay tối thiểu {vn_number(min_amount)} {bank.currency}"
    max_amount = int(policy.get("max_amount", bank.limit_total))
    if amount > max_amount:
        return f"Khoản vay tối đa {vn_number(max_amount)} {bank.currency}"
    max_rate = float(policy.get("max_rate", 1.0))
    if rate > max_rate + 1e-9:
        return f"Lãi suất {rate * 100:.0f}% vượt trần {max_rate * 100:.0f}% của ngân hàng"
    min_rate = policy.get("min_rate")
    if min_rate is not None and rate < float(min_rate) - 1e-9:
        return f"Lãi suất {rate * 100:g}% thấp hơn sàn {float(min_rate) * 100:g}% của ngân hàng"
    if category and category in (policy.get("excluded_groups") or []):
        return f"Không cấp vốn cho nhóm hàng “{category}”"
    if policy.get("max_tenor_days") and seller.get("tenor_days") and seller["tenor_days"] > int(policy["max_tenor_days"]):
        return f"Kỳ hạn khoảng {seller['tenor_days']} ngày dài hơn mức {int(policy['max_tenor_days'])} ngày ngân hàng nhận"
    if policy.get("min_store_rating") and seller.get("rating") is not None \
            and seller["rating"] < float(policy["min_store_rating"]) - 1e-9:
        return (f"Chỉ nhận cửa hàng điểm từ {_fmt_dec(float(policy['min_store_rating']))} "
                f"(cửa hàng {_fmt_dec(seller['rating'])})")
    if policy.get("min_store_age_months") and seller.get("store_age_months") is not None \
            and seller["store_age_months"] < int(policy["min_store_age_months"]):
        return (f"Chỉ nhận cửa hàng hoạt động từ {int(policy['min_store_age_months'])} tháng "
                f"(cửa hàng {seller['store_age_months']} tháng)")
    if remaining_limit(bank) * BP_TOTAL < amount * min_share_bp(bank, params):
        return "Hạn mức còn lại không đủ cho phần tối thiểu"
    if min_share_bp(bank, params) > max_share_bp(bank) or cap_amount(bank, amount) * BP_TOTAL < amount * min_share_bp(bank, params):
        return "Phần tối thiểu vượt mức ngân hàng nhận cho một khoản"
    if int(policy.get("min_share_amount") or 0) > cap_amount(bank, amount):
        return f"Phần của ngân hàng phải từ {vn_number(int(policy['min_share_amount']))} {bank.currency}"
    return None


def eligible_banks(
    session: Session, *, region: str, tier: int, grade: str, amount: int, category: str, rate: float,
    params: dict[str, Any] | None = None, seller: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Every bank of ``region`` with a Vietnamese reason why it can or cannot fund.

    ``category`` is the goods category (doc.plan.group / doc.category), checked
    against ``excluded_groups``; ``grade`` uses A < B < … < E (A best); ``seller`` is
    :func:`seller_terms` (store rating and age, loan length) for the catalog rules.
    """
    out: list[dict[str, Any]] = []
    for bank in catalog(session, region):
        reason = _ineligible_reason(
            bank, region=region, tier=tier, grade=grade, amount=amount, category=category, rate=rate,
            params=params, seller=seller,
        )
        written = (bank.policy or {}).get("chain") or {}
        out.append({
            "bank": bank.code,
            "name": bank.name,
            **({"policy_version": written.get("version"), "policy_hash": written.get("hash")} if written else {}),
            "eligible": reason is None,
            "reason": reason or (
                f"Đủ điều kiện: hạng {grade}, tầng {tier}, hạn mức còn "
                f"{vn_number(remaining_limit(bank))} {bank.currency}"
            ),
        })
    return out


def _declared_order(bank: BuBank, accounts: list[dict[str, Any]]) -> int:
    for i, account in enumerate(accounts):
        label = str(account.get("bank", "")).strip().lower()
        if label and label in (bank.code.lower(), bank.name.lower()):
            return i
    return len(accounts) + 1


def _fit(banks: list[BuBank], amount: int, params: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    """Minimum share each, the rest to the banks in order up to their caps (rule 3–4);
    None when the set cannot carry the whole amount."""
    # A bank's floor also covers its smallest part (min_share_amount), its cap the most it funds.
    mins = [max(min_share_bp(b, params), -(-int((b.policy or {}).get("min_share_amount") or 0) * BP_TOTAL // amount))
            for b in banks]
    caps = [min(max_share_bp(b), cap_amount(b, amount) * BP_TOTAL // amount) for b in banks]
    for _ in range(BP_TOTAL):  # a rounding unit over a cap: lower that cap by 1 bp and refit
        if sum(mins) > BP_TOTAL or any(m > c for m, c in zip(mins, caps)):
            return None
        shares, rest = list(mins), BP_TOTAL - sum(mins)
        for i in range(len(banks)):
            extra = min(rest, caps[i] - shares[i])
            shares[i] += extra
            rest -= extra
        if rest:
            return None
        amounts = split_largest_remainder(amount, shares)
        over = [i for i, (b, a) in enumerate(zip(banks, amounts)) if a > cap_amount(b, amount)]
        if not over:
            if any(a < int((b.policy or {}).get("min_share_amount") or 0) for b, a in zip(banks, amounts)):
                return None
            return [{"bank": b.code, "name": b.name, "pct": bp / BP_TOTAL, "bp": bp, "amount": a,
                     "contract_id": b.contract_id} for b, bp, a in zip(banks, shares, amounts)]
        for i in over:
            caps[i] -= 1
    return None


def split_largest_remainder(total: int, weights: list[int]) -> list[int]:
    """Split integer ``total`` by integer ``weights`` (largest remainder method).

    Floors every part, then hands the leftover units one by one to the parts
    with the largest fractional remainder (ties: larger weight, then order).
    """
    weight_sum = sum(weights)
    if total <= 0 or weight_sum <= 0:
        return [0 for _ in weights]
    parts = [total * w // weight_sum for w in weights]
    order = sorted(
        range(len(weights)), key=lambda i: (-((total * weights[i]) % weight_sum), -weights[i], i)
    )
    for i in order[: total - sum(parts)]:
        parts[i] += 1
    return parts


def propose_split(
    session: Session, *, eligible: list[dict[str, Any]], amount: int,
    accounts: list[dict[str, Any]] | None = None, params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Deterministic split over the eligible banks (see module docstring); [] when no
    set of banks can carry the amount within their caps. Sets that keep the first
    candidate (the seller's receiving bank) are tried before any set without it."""
    accounts = accounts or []
    banks = [b for row in eligible if row["eligible"] and (b := get_bank(session, row["bank"]))]
    if not banks or amount <= 0:
        return []
    banks.sort(key=lambda b: (_declared_order(b, accounts), -remaining_limit(b), b.code))
    most = min(MAX_BANKS, len(banks), max(1, BP_TOTAL // max(min_share_bp(b, params) for b in banks)))
    sets = [c for size in range(most, 0, -1) for c in combinations(range(len(banks)), size)]
    sets.sort(key=lambda c: (0 not in c, -len(c), c))  # candidate order is kept inside each set
    for chosen in sets:
        split = _fit([banks[i] for i in chosen], amount, params)
        if split:
            return split
    return []


def validate_split(
    session: Session, *, region: str, amount: int, shares: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> list[str]:
    """Vietnamese problems with a split; an empty list means it is valid."""
    problems: list[str] = []
    if not shares:
        return ["Chưa có ngân hàng nào trong phương án chia."]
    total_bp = 0
    seen: set[str] = set()
    for share in shares:
        code = str(share.get("bank", ""))
        pct = float(share.get("pct", 0))
        bp = round(pct * BP_TOTAL)
        if abs(pct * BP_TOTAL - bp) > 1e-6:
            problems.append(f"{code}: tỷ lệ chỉ được tối đa 2 chữ số thập phân (theo phần trăm).")
        total_bp += bp
        if code in seen:
            problems.append(f"{code}: ngân hàng bị lặp.")
        seen.add(code)
        bank = get_bank(session, code)
        if bank is None:
            problems.append(f"{code}: ngân hàng không tồn tại.")
            continue
        if not bank.active or bank.region != region or not bank.public_key:
            problems.append(f"{code}: ngân hàng không hoạt động, khác khu vực hoặc chưa có khóa mã hóa.")
        if bp < min_share_bp(bank, params):
            problems.append(f"{code}: phần dưới mức tối thiểu {min_share_bp(bank, params) / 100:.2f}%.")
        if bp > max_share_bp(bank):
            problems.append(f"{code}: phần vượt mức tối đa {max_share_bp(bank) / 100:.2f}% ngân hàng nhận.")
        share_amount = int(share.get("amount", amount * bp // BP_TOTAL))
        if share_amount > remaining_limit(bank):
            problems.append(f"{code}: vượt hạn mức còn lại {vn_number(remaining_limit(bank))}.")
        elif (bank.policy or {}).get("max_share_amount") and share_amount > int(bank.policy["max_share_amount"]):
            problems.append(f"{code}: vượt mức {vn_number(int(bank.policy['max_share_amount']))} ngân hàng cấp cho "
                            "một khoản.")
        if share_amount < int((bank.policy or {}).get("min_share_amount") or 0):
            problems.append(f"{code}: phần dưới mức tối thiểu {vn_number(int(bank.policy['min_share_amount']))} "
                            "mỗi lệnh.")
    if total_bp != BP_TOTAL:
        problems.append(f"Tổng tỷ lệ phải đúng 100,00% (hiện {total_bp / 100:.2f}%).")
    if "amount" in shares[0] and sum(int(s.get("amount", 0)) for s in shares) != amount:
        problems.append("Tổng số tiền các phần không bằng số tiền giải ngân.")
    return problems


def bank_view(bank: BuBank, *, full: bool = True) -> dict[str, Any]:
    """BANK per the contract. ``full=False`` keeps only the public catalog fields."""
    base = {"code": bank.code, "name": bank.name, "region": bank.region}
    if not full:
        return base
    return {
        **base,
        "currency": bank.currency,
        "active": bank.active,
        "limit_total": bank.limit_total,
        "limit_used": bank.limit_used,
        "limit_remaining": remaining_limit(bank),
        "policy": bank.policy or {},
        "contract_id": bank.contract_id,
        "public_key": bank.public_key,
    }
