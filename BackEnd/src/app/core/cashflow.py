"""Business expenses in six groups (SELLER_SERVICES_PLAN §3.3, 17/10/2026).

Money leaving the WeBank business account (``loan.doc.account.transfers``: the seller's own transfers,
the WeBank outflow webhook, the demo spending feed) is put in one of six fixed groups by rules: an explicit
``group``, then the transfer ``kind``, then keywords on the memo / label / payee name (Vietnamese, Chinese,
English). Transfers that are not a business expense (to a personal account, securities, real estate, the
repayment of another loan) are ``None``. What no rule recognises is ``"other"`` (shown "Chưa phân loại").

The platform fee has no transfer of its own: the platform pays out net of it. It is estimated from the
money in with the fee schedule of the store's platform (default 5 %), and reports say it is an estimate.

Read-only and deterministic: used by the monthly / quarterly / yearly seller reports and the debt-service check.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable

EXPENSE_GROUPS = ("goods", "platform", "marketing", "logistics", "staff", "tax")  # fixed order
OTHER_GROUP = "other"
GROUP_LABELS = {"goods": "Hàng hóa và nguyên liệu", "platform": "Chi phí trên sàn", "marketing": "Tiếp thị ngoài sàn",
                "logistics": "Vận chuyển và kho bãi", "staff": "Nhân sự và vận hành", "tax": "Thuế và phí kinh doanh",
                OTHER_GROUP: "Chưa phân loại"}
NON_BUSINESS_KINDS = ("personal", "securities", "real_estate")
DEFAULT_PLATFORM_FEE = 0.05

# Checked in this order; the first group whose pattern matches wins. Short Vietnamese words use word
# boundaries ("kho" must not match "khoản").
_NOT_EXPENSE = re.compile(r"trả góp|trả nợ|还款|还贷|repay|instal?ment|chứng khoán|bất động sản|证券|房产", re.I)
_KEYWORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("staff", re.compile(r"lương|thưởng|nhân viên|cộng tác viên|工资|薪|社保|salary|payroll|wage", re.I)),
    ("marketing", re.compile(r"quảng cáo|tiếp thị|推广|广告|巨量|千川|直通车|\bads?\b|advert|marketing|kol|livestream",
                             re.I)),
    ("logistics", re.compile(r"vận chuyển|giao hàng|\bkho\b|kho bãi|快递|物流|仓|运费|shipping|logistic|courier|"
                             r"warehouse|freight", re.I)),
    ("platform", re.compile(r"phí sàn|hoa hồng sàn|佣金|平台|技术服务费|commission|platform fee", re.I)),
    ("tax", re.compile(r"thuế|lệ phí|税|tax", re.I)),
    ("goods", re.compile(r"nhập hàng|nguyên liệu|bao bì|xưởng|nhà cung cấp|进货|货款|采购|供应商|面料|supplier|"
                         r"purchase|inventory|material", re.I)),
)


def _text(transfer: dict[str, Any]) -> str:
    payee = transfer.get("payee") or {}
    return " ".join(str(x) for x in (transfer.get("memo"), transfer.get("note"), payee.get("name"),
                                      transfer.get("label") if transfer.get("kind") != "other" else "") if x)


def classify(transfer: dict[str, Any]) -> str | None:
    """The expense group of one transfer out, ``"other"`` when unknown, ``None`` when it is not a
    business expense (personal, securities, real estate, repaying another loan)."""
    group = transfer.get("group")
    if group in EXPENSE_GROUPS or group == OTHER_GROUP:
        return str(group)
    kind = str(transfer.get("kind") or "")
    if kind in NON_BUSINESS_KINDS:
        return None
    if kind == "supplier":
        return "goods"
    if kind in EXPENSE_GROUPS:
        return kind
    text = _text(transfer)
    if _NOT_EXPENSE.search(text):
        return None
    for key, pattern in _KEYWORDS:
        if pattern.search(text):
            return key
    payee_kind = str((transfer.get("payee") or {}).get("kind") or "")
    if payee_kind == "supplier":
        return "goods"
    return OTHER_GROUP


def platform_fee(inflow_net: int, fee: float = DEFAULT_PLATFORM_FEE) -> int:
    """The fee the platform kept before paying ``inflow_net`` out: net × fee / (1 − fee)."""
    fee = min(max(float(fee), 0.0), 0.5)
    return round(int(inflow_net) * fee / (1 - fee)) if inflow_net > 0 and fee > 0 else 0


def fee_rate(tax_data: dict[str, Any] | None, platform: str | None) -> float:
    """The store's platform fee from ``tax.platform_fee_schedule`` (first rate listed), else 5 %."""
    schedule = ((tax_data or {}).get("platform_fee_schedule") or {}).get(str(platform or "")) or {}
    rates = [float(v) for v in schedule.values() if isinstance(v, (int, float))] if isinstance(schedule, dict) else []
    return rates[0] if rates else DEFAULT_PLATFORM_FEE


def _month_of(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()[:7]
    return str(value or "")[:7]


def month_summary(loan_docs: Iterable[dict[str, Any]], repayments: Iterable[Any], month: str,
                  fee: float = DEFAULT_PLATFORM_FEE) -> dict[str, Any]:
    """Money in and out of the business account in ``month`` ("YYYY-MM") over the given loans:
    expenses by group (platform fee estimated from the money in), non-business transfers apart,
    repayments to BuoyUp apart (they are debt service, not an expense)."""
    sums = {k: 0 for k in (*EXPENSE_GROUPS, OTHER_GROUP)}
    inflow = non_business = 0
    for doc in loan_docs:
        account = (doc or {}).get("account") or {}
        inflow += sum(int(i.get("amount") or 0) for i in account.get("inflows") or [] if _month_of(i.get("on")) == month)
        for t in account.get("transfers") or []:
            if _month_of(t.get("on")) != month:
                continue
            group = classify(t)
            if group is None:
                non_business += int(t.get("amount") or 0)
            else:
                sums[group] += int(t.get("amount") or 0)
    fee_estimate = platform_fee(inflow, fee)
    sums["platform"] += fee_estimate
    repay = 0
    for r in repayments:
        at = r.get("at") if isinstance(r, dict) else getattr(r, "at", None)
        amount = r.get("swept") if isinstance(r, dict) else getattr(r, "swept", 0)
        if _month_of(at) == month:
            repay += int(amount or 0)
    total = sum(sums[k] for k in EXPENSE_GROUPS)
    groups = [{"key": k, "label": GROUP_LABELS[k], "amount": sums[k],
               "share": round(sums[k] / total, 4) if total else 0.0} for k in EXPENSE_GROUPS]
    return {"month": month, "inflow": inflow, "groups": groups, "expenses": total, "unclassified": sums[OTHER_GROUP],
            "non_business": non_business, "repay": repay, "platform_fee": fee_estimate,
            "platform_fee_rate": fee, "platform_fee_estimated": True}


def coverage(webank_in_month: int | float | None, tax_revenue_month: int | float | None,
             forecast_monthly: int | float | None = None) -> dict[str, Any]:
    """How much of the store's revenue BuoyUp sees on the WeBank business account (SELLER_SERVICES_PLAN §6.2,
    việc 9). ``share = min(1, webank_in / revenue)`` against the month's tax-filed revenue (``basis: "tax"``),
    else the loan's forecast monthly revenue (``basis: "forecast"``); without either ``basis: "none"`` and
    ``share: None``. ``estimate`` is the revenue the figure stands on (never below what reached WeBank), the
    denominator of the debt-service check (§5.2)."""
    webank_in = max(0, int(webank_in_month or 0))
    tax = int(tax_revenue_month or 0)
    forecast = int(forecast_monthly or 0)
    if tax > 0:
        basis, revenue = "tax", tax
    elif forecast > 0:
        basis, revenue = "forecast", forecast
    else:
        return {"share": None, "basis": "none", "webank_in": webank_in, "tax_revenue": None, "revenue": None,
                "estimate": webank_in or None}
    return {"share": round(min(1.0, webank_in / revenue), 4), "basis": basis, "webank_in": webank_in,
            "tax_revenue": tax if basis == "tax" else None, "revenue": revenue, "estimate": max(webank_in, revenue)}
