"""Loan circle, Stage 2 (bank side): the orchestrator sends the case to the partner banks in parallel.

docs/BuoyUp loan circle .docx:
- the orchestrator picks partners whose appetite fits, in the right territory, with monthly budget and
  concentration room left, and sends the application to all of them at once;
- each bank runs its own credit inquiry and decides with its own system; it must answer within 30
  seconds, a late answer counts as a decline; first come, first in;
- two partners agree → the split is fixed at 40/30/30 with WeBank as the lead; only one → WeBank 30,
  partner 70; none → a lower limit or a rejection. Team decision (14/10/2026): WeBank does not lend
  alone; the orchestrator retries at 70 % and 50 % of the limit, then rejects;
- an approved limit is valid for 7 days; a partner's concentration room is only used when the
  borrower signs the contract.

Hard rules checked here (before asking a bank): partner on the whitelist; a local bank only lends in
its own province; the partner's joint-lending balance with this platform stays within 25 % of its
tier-1 capital and 50 % of its total loans (CBIRC rules on joint internet loans); monthly budget left.
Each partner keeps at least 30 % of a loan (40/30/30 or 30/70). The rate (= total annual cost, no fee)
is within 24 % (LAW-02, Agent 3).

Bank decisions are simulated from each bank's catalog policy (``response_ms`` is the bank's answer
time); a real deployment replaces :func:`bank_decides` with a call to the bank's system.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.blockchain import chain
from app.banks.split import GRADES, catalog, grade_ok, remaining_limit, vn_number
from app.core.algorithm import floor_to
from app.platform import events
from app.platform.db.tables import utcnow
from app.platform.tables import BuBank, save_json


def _month_key() -> str:
    return utcnow().strftime("%Y-%m")


def budget_left(bank: BuBank) -> int | None:
    policy = bank.policy or {}
    budget = policy.get("monthly_budget")
    if budget is None:
        return None
    used = int((policy.get("budget_used") or {}).get(_month_key(), 0))
    return max(0, int(budget) - used)


def joint_balance(bank: BuBank) -> int:
    """What this partner currently funds through BuoyUp (its outstanding joint loans)."""
    return int(bank.limit_used)


def hard_rule_problem(bank: BuBank, *, province: str, share: int, params: dict[str, Any]) -> str | None:
    """Why the orchestrator may not send the case to this partner for ``share`` yuan, else None."""
    policy = bank.policy or {}
    syn = params["syndicate"]
    if not bank.active:
        return "Ngân hàng đang tạm dừng nhận khoản mới"
    if not policy.get("whitelisted", True):
        return "Không có trong danh sách trắng đối tác"
    local = policy.get("local_province")
    if local and local != province:
        return f"Ngân hàng địa phương ({local}) không cho vay ngoài địa bàn"
    tier1 = policy.get("tier1_capital")
    if tier1 and joint_balance(bank) + share > syn["concentration_single"] * int(tier1):
        return f"Vượt trần tập trung: dư nợ hợp tác quá {syn['concentration_single'] * 100:.0f}% vốn cấp một"
    total = policy.get("total_loans")
    if total and joint_balance(bank) + share > syn["concentration_total"] * int(total):
        return f"Vượt trần: dư nợ hợp tác quá {syn['concentration_total'] * 100:.0f}% tổng dư nợ"
    left = budget_left(bank)
    if left is not None and left < share:
        return "Hết ngân sách tháng cho kênh hợp tác"
    if remaining_limit(bank) < share:
        return "Hết hạn mức hợp tác còn lại"
    return None


def vn_decimal(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def max_tenor_m(policy: dict[str, Any]) -> int:
    """Longest tenor a bank lends (its own setting, or the chain catalog's maxTenorDays)."""
    months = int(policy.get("max_tenor_m", 36))
    if policy.get("max_tenor_days"):
        months = min(months, int(policy["max_tenor_days"]) // 30)
    return months


def bank_decides(bank: BuBank, case: dict[str, Any], amount: int) -> dict[str, Any]:
    """The bank's own credit decision (simulated from its policy) and its answer time."""
    policy = bank.policy or {}
    ms = int(policy.get("response_ms", 2000))
    reason = None
    if not grade_ok(case["grade"], str(policy.get("min_grade", "C"))):
        reason = f"Chỉ nhận hạng {policy.get('min_grade', 'C')} trở lên"
    elif amount < int(policy.get("min_amount", 0)):
        reason = f"Khoản vay tối thiểu {vn_number(int(policy['min_amount']))} {bank.currency}"
    elif policy.get("max_amount") and amount > int(policy["max_amount"]):
        reason = f"Khoản vay tối đa {vn_number(int(policy['max_amount']))} {bank.currency}"
    elif case["industry"] in (policy.get("exclude_industries") or []):
        reason = f"Không cho vay ngành {case['industry']}"
    elif case["borrower_type"] not in (policy.get("borrower_types") or ["individual_business", "company"]):
        reason = "Không cho vay loại người vay này"
    elif case["late_max_days_24m"] > int(policy.get("max_late_days", 30)):
        reason = "Báo cáo tín dụng có trễ hạn vượt mức ngân hàng chấp nhận"
    elif policy.get("min_store_rating") and case["rating"] < float(policy["min_store_rating"]):
        reason = f"Điểm cửa hàng dưới {vn_decimal(float(policy['min_store_rating']))}"
    elif policy.get("min_store_age_months") and case["store_age_m"] < int(policy["min_store_age_months"]):
        reason = f"Cửa hàng hoạt động chưa đủ {policy['min_store_age_months']} tháng"
    elif policy.get("max_rate") and case["rate"] > float(policy["max_rate"]):
        reason = "Lãi suất của hồ sơ vượt trần lãi của ngân hàng"
    elif case["tenor_min"] > max_tenor_m(policy):
        reason = "Kỳ hạn ngắn nhất của sản phẩm dài hơn mức tối đa của ngân hàng"
    return {"decision": "decline" if reason else "approve", "reason": reason or "Đồng ý cấp vốn", "ms": ms}


def _case(doc: dict[str, Any], offer: dict[str, Any]) -> dict[str, Any]:
    data = (doc.get("internal") or {}).get("data") or {}
    return {"grade": offer["grade"], "industry": (data.get("store") or {}).get("industry") or "khác",
            "borrower_type": doc.get("borrower_type") or "individual_business",
            "late_max_days_24m": int((data.get("credit") or {}).get("late_max_days_24m") or 0),
            "tenor_max": int(offer["tenor_max"]), "tenor_min": min(offer.get("tenors") or [offer["tenor_max"]]),
            "rate": float(offer.get("rate") or 0),
            "rating": float((data.get("store") or {}).get("rating") or 0),
            "store_age_m": int((data.get("revenue") or {}).get("months_with_sales") or 0)}


def ask_banks(session: Session, doc: dict[str, Any], params: dict[str, Any], amount: int) -> list[dict[str, Any]]:
    """One parallel round: every partner of the region, hard rules first, then the bank's answer."""
    syn = params["syndicate"]
    timeout_ms = int(syn["timeout_s"]) * 1000
    min_share = floor_to(amount * float(params["banks"]["min_share"]), 1)
    case = _case(doc, doc["offer"])
    out = []
    for bank in catalog(session, doc.get("region") or "CN"):
        if bank.code == syn["lead"]:
            continue
        row = {"bank": bank.code, "name": bank.name}
        problem = hard_rule_problem(bank, province=str(doc.get("province") or ""), share=min_share, params=params)
        if problem:
            out.append({**row, "decision": "not_sent", "reason": problem, "ms": None})
            continue
        answer = bank_decides(bank, case, amount)
        if answer["ms"] > timeout_ms:
            answer = {"decision": "timeout", "reason": f"Không trả lời trong {syn['timeout_s']} giây: coi như từ chối",
                      "ms": answer["ms"]}
        out.append({**row, **answer})
    return sorted(out, key=lambda r: (r["ms"] is None, r["ms"] or 0, r["bank"]))


def _split(params: dict[str, Any], lead: str, agreed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    syn = params["syndicate"]
    if len(agreed) >= 2:
        pcts = syn["split_two"]
        banks = [lead, agreed[0]["bank"], agreed[1]["bank"]]
    else:
        pcts = syn["split_one"]
        banks = [lead, agreed[0]["bank"]]
    return [{"bank": b, "pct": float(p), "role": "lead" if b == lead else "partner"} for b, p in zip(banks, pcts)]


def run(session: Session, app_row: Any, doc: dict[str, Any], params: dict[str, Any], amount: int) -> dict[str, Any]:
    """Rounds at the limit, then 70 % and 50 % of it. Returns the syndicate record (stored in the doc
    and anchored on the chain). ``status`` is "approved" or "no_partner"."""
    syn = params["syndicate"]
    lead_code = syn["lead"]
    lead = session.get(BuBank, lead_code)
    amounts = [amount] + [floor_to(amount * s, 100) for s in syn["retry_steps"]]
    amounts = [a for i, a in enumerate(amounts) if a >= int(params["product"]["min_amount"]) and a not in amounts[:i]]
    rounds: list[dict[str, Any]] = []
    result: dict[str, Any] = {"status": "no_partner", "lead": lead_code, "rounds": rounds}
    for amt in amounts:
        responses = ask_banks(session, doc, params, amt)
        agreed = [r for r in responses if r["decision"] == "approve"]
        rounds.append({"amount": amt, "responses": responses, "agreed": [r["bank"] for r in agreed]})
        for r in responses:
            if r["decision"] in ("approve", "decline"):
                events.log(session, app_row.id, "bank", "bank_answer",
                           f"{r['name']} tự tra cứu tín dụng và {'đồng ý' if r['decision'] == 'approve' else 'từ chối'} "
                           f"sau {r['ms'] / 1000:.1f} giây", {"bank": r["bank"], "amount": amt, "hidden_from_seller": True})
        if not agreed:
            continue
        if len(agreed) == 1:  # the single partner takes 70 %: its rules are checked again at that share
            bank = session.get(BuBank, agreed[0]["bank"])
            share70 = floor_to(amt * float(syn["split_one"][1]), 1)
            problem = hard_rule_problem(bank, province=str(doc.get("province") or ""), share=share70, params=params)
            if problem:
                rounds[-1]["single_partner_blocked"] = problem
                continue
        if lead is None or not lead.active:
            break
        split = _split(params, lead_code, agreed)
        names = {b.code: b.name for b in catalog(session, doc.get("region") or "CN")}
        for s in split:
            s["name"] = names.get(s["bank"], s["bank"])
        expires = utcnow() + timedelta(days=int(params["product"]["limit_valid_days"]))
        # Every lender of the loan must accept its tenor: the borrower only sees tenors all of them lend.
        tenor_cap = min(max_tenor_m((session.get(BuBank, s["bank"]).policy or {})) for s in split)
        result = {"status": "approved", "lead": lead_code, "rounds": rounds, "limit": amt, "split": split,
                  "reduced": amt < amount, "approved_at": utcnow().isoformat() + "Z", "tenor_cap": tenor_cap,
                  "expires_at": expires.isoformat() + "Z", "id": "SYN-" + secrets.token_hex(4)}
        break
    entry = chain.record(session, app_row.id, "syndicate", {k: v for k, v in result.items()})
    result["hash"], result["chain_tx"] = entry.fingerprint, entry.tx
    events.log(session, app_row.id, "orchestrator", "syndicate",
               ("Các ngân hàng duyệt song song: " + ", ".join(f"{s['name']} {s['pct'] * 100:.0f}%" for s in result["split"])
                + (f" (hạn mức giảm còn {vn_number(result['limit'])})" if result.get("reduced") else ""))
               if result["status"] == "approved" else "Không ngân hàng đối tác nào đồng ý, kể cả ở hạn mức thấp hơn",
               {"status": result["status"], "rounds": len(rounds)}, entry.fingerprint)
    return result


def release_at_stop(session: Session, legs: list[dict[str, Any]], signed_at: str | None) -> None:
    """Undo :func:`reserve_at_signing` when the payout is stopped (the loan never existed)."""
    from app.agents.agent4b_monitor import release_limit

    month = str(signed_at or "")[:7] or _month_key()
    for leg in legs:
        release_limit(session, leg["bank"], int(leg["amount"]))
        bank = session.get(BuBank, leg["bank"])
        if bank is None:
            continue
        policy = dict(bank.policy or {})
        used = dict(policy.get("budget_used") or {})
        used[month] = max(0, int(used.get(month, 0)) - int(leg["amount"]))
        policy["budget_used"] = used
        save_json(bank, "policy", policy)
    session.flush()


def reserve_at_signing(session: Session, split: list[dict[str, Any]], amount: int) -> list[dict[str, Any]]:
    """Stage 4: concentration and budget are only used when the borrower signs. Returns the legs with
    integer amounts (largest remainder) and the contract id of each bank."""
    from app.agents.agent4b_monitor import reserve_limit
    from app.banks.split import split_largest_remainder

    parts = split_largest_remainder(amount, [round(s["pct"] * 10_000) for s in split])
    legs = []
    for s, part in zip(split, parts):
        bank = session.get(BuBank, s["bank"])
        reserve_limit(session, s["bank"], part)
        policy = dict(bank.policy or {})
        used = dict(policy.get("budget_used") or {})
        used[_month_key()] = int(used.get(_month_key(), 0)) + part
        policy["budget_used"] = used
        save_json(bank, "policy", policy)
        legs.append({"bank": s["bank"], "name": s.get("name", s["bank"]), "pct": s["pct"], "amount": part,
                     "contract_id": f"BU-{s['bank']}-{utcnow():%Y}-{secrets.token_hex(3).upper()}",
                     "role": s.get("role", "partner")})
    session.flush()
    return legs


__all__ = ["run", "ask_banks", "hard_rule_problem", "bank_decides", "reserve_at_signing", "GRADES"]
