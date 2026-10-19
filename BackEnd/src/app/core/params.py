"""Parameter set v4.0 (Bảng tham số). Values tagged in ``ORIGIN``:
TIEN_LE = taken from the source document or a bank precedent (for the loan circle
sections: stated in docs/BuoyUp loan circle .docx); DOI_CHOT = an open point of that
document the team decided on 14/10/2026; DAT_TAY = team choice, not yet validated by data. Agent 5 may only *propose* changes; an
admin approval creates a new version (``bu_params``) anchored on the chain.

Read the active set with :func:`active_params`; never import DEFAULT_PARAMS in
business code (it would ignore approved changes).
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

PARAMS_VERSION = "v4.0"

DEFAULT_PARAMS: dict[str, Any] = {
    "tier1": {
        "lookback_days": 20,
        "advance_rate": 0.80,
        "tenor_m": 1,
        "group_mult": {"1": 1.0, "2": 0.70, "3": 0.50, "4": 0.30},
        "group3_cap": 20_000,
        "industry_return_rate": {"thời trang": 0.08, "mỹ phẩm": 0.06, "tạp hóa": 0.03, "điện tử": 0.05, "khác": 0.06},
    },
    "tier2": {
        "tenor_m": 4,
        "group_cap_mult": {"1": 3.0, "2": 1.5, "3": 0.0, "4": 0.0},
        "absolute_cap": 2_000_000,
        "option_steps": [0.70, 0.50],
        "slider_min": 10_000,
        # Lỗ hổng 1: the v3.1 safety factor 0.85 is OFF in v4 (spec Agent 1–3).
        "safety_factor": 1.0,
        "min_peak_seasons": 2,
    },
    # Loan circle product (docs/BuoyUp loan circle .docx; team decisions 14/10/2026).
    "product": {
        # Review 17/10/2026: personal sellers (no business registration) borrow too; 36 months dropped.
        "tenors": {"individual": [3, 6, 12], "individual_business": [3, 6, 12], "company": [3, 6, 12, 24]},
        "type_cap": {"individual": 50_000, "individual_business": 200_000, "company": 2_000_000},
        # The borrower does not pick the tenor (the system sets the longest one of the type) nor the method
        # (equal-principal instalments only); they pick the amount within the limit and the due day.
        "borrower_picks_tenor": False,
        "methods": ["installment"],
        "min_amount": 10_000,
        "group_cap_mult": {"1": 3.0, "2": 1.5, "3": 0.5, "4": 0.0},
        "option_steps": [0.70, 0.50],
        "first_due_min_days": 15,
        "limit_valid_days": 7,
        "due_day_max": 28,
    },
    "revenue": {"statement_tolerance": 0.15, "statement_reject": 0.30, "statement_bonus": 0.05, "statement_months": 6,
                # Testbench DS-29: typed figures alone earn no bonus (a seller could inflate them up to the 15 %
                # tolerance); screenshots that show the typed figures must back them.
                "bonus_requires_images": True},
    "repay": {
        "min_principal_share": 0.30, "min_max_consecutive": 2, "min_tenor_m": 3,
        "grace_days": 3, "penalty_mult": 1.5, "report_overdue_days": 30, "reminder_days": [7, 1],
        "supplier_direct_threshold": 100_000, "majority": 0.6667, "large_personal_transfer": 0.30,
        # Review 17/10/2026: the whole loan goes to the borrower's WeBank account (no direct supplier part).
        "pay_supplier_direct": False,
        # SELLER_SERVICES_PLAN §5 (Agent 4b, read-only notices): forecast the balance on the due date this many
        # days before it, from the money in / business spending of the last ``forecast_lookback_days``; tell the
        # seller at once when one transfer of at least ``large_spend_share`` × the next payment leaves less than it.
        "forecast_days": [7, 3], "forecast_lookback_days": 30, "large_spend_share": 0.30,
    },
    "syndicate": {
        "lead": "WEBANK", "timeout_s": 30,
        # No partner agreed at any step: WeBank (lead) may lend alone up to ``solo_max`` (its on-chain policy
        # allows a 100 % WeBank split); 0 turns this off and the case is rejected as before.
        "solo_max": 50_000, "split_two": [0.40, 0.30, 0.30], "split_one": [0.30, 0.70],
        "retry_steps": [0.70, 0.50], "concentration_single": 0.25, "concentration_total": 0.50,
    },
    "contract": {"read_seconds": 20, "complaint_channel": "Tổng đài WeBank 95384 · khieunai@buoyup.vn"},
    "scope": {"min_inflow_months": 12, "platforms": ["douyin", "taobao", "tmall", "jd", "pinduoduo", "kuaishou"]},
    "forecast": {"growth_cap": 0.50},
    "prudence": {"thời trang": 0.70, "mỹ phẩm": 0.72, "tạp hóa": 0.80, "điện tử": 0.65, "khác": 0.70},
    "price": {"deviation_flag": 1.2, "no_invoice_haircut": 0.15, "new_supplier_factor": 0.70},
    "scorecard": {
        "grades": {"A": 85, "B": 70, "C": 55, "D": 40},
        "fate_points": {"1": 15, "2": 13, "3": 11, "4": 5, "5": 0},
        "borderline": [40, 43],
        # FATE unanswered (DATA_PARTNER_MISSING): scored as the worst band [Đặt tay].
        "fate_missing": 5,
    },
    "rates": {
        "A": 0.08, "B": 0.10, "C": 0.12, "D": 0.15,
        # B7 floor: rate ≥ cost_of_funds + processing_cost ÷ (avg_balance × tenor/12).
        "cost_of_funds": 0.05, "processing_cost": 50, "avg_balance_share": 0.5,
    },
    "flags": {
        "inflow_gap": 0.95,
        "pass_share": 0.15,
        "pass_people": 20,
        "spike_mult": 3.0,
        "inventory_mult": 1.5,
        "open_days": 3,
    },
    "gate": {
        "auto_limit": 500_000, "risk04_warn": 0.25,
        # Auto-approval kill switch per group (industry × tier): bad loans ÷ disbursed.
        "npl_off_ratio": 0.08, "npl_min_loans": 10, "npl_overdue_days": 90,
    },
    # Loan circle: each partner keeps at least 30 % of a loan; the banks approve in the syndicate round.
    "banks": {"min_share": 0.30},
    "early_warning": {
        "weights": {"sales_low": 0.30, "rating_low": 0.20, "low_balance": 0.15, "new_inquiry": 0.15,
                    "fate_worse": 0.20, "large_personal": 0.20},
        "yellow": 0.2,
        "red": 0.5,
        "sales_mult": 3.0,
        "rating_min": 4.0,
        "shortfall_red": 0.30,
        "overdue_red_days": 7,
        # SELLER_SERVICES_PLAN §5.2: last month's repayments above this share of the estimated revenue → notice.
        "dsr_max": 0.20,
    },
    "payout_days": {"douyin": {"fast": 4, "slow": 10, "rating_threshold": 4.4}},
    "stress": {"event_drop": 0.50, "event_threshold": 0.25, "event_min_loans": 5},
    "consent": {"ttl_days": 90},
    # LAW-02 cap and AML-LTR-01 large-transaction thresholds by payee type (PBOC-LST-2016#5).
    # LAW-REG-01 (SELLER_SERVICES_PLAN §6.2 việc 8): an individual selling online above
    # ``individual_registration_threshold`` a year must register (NETTRADE-2021#8); the seller is told once a year
    # when the year-to-date revenue reaches ``individual_registration_warn_share`` of it.
    "legal": {"rate_cap": 0.24, "ltr_threshold": {"organization": 2_000_000, "individual": 500_000},
              "individual_registration_threshold": 100_000, "individual_registration_warn_share": 0.8},
    "use_of_funds": {"days": 15, "tolerance": 0.10},
    "chat": {"max_per_minute": 12},
    "agent5": {"disagreement_band": [0.05, 0.60], "bad_rate_trigger": 0.10, "min_cohort": 5},
    # Complaints (review item 4): acknowledge within ``ack_days`` working days, answer with reasons within
    # ``answer_days``, at most ``max_days`` when more checks are needed (seller told first); an escalated case
    # gets an officer review date ``review_days`` working days out.
    "complaint": {"ack_days": 1, "answer_days": 5, "max_days": 15, "review_days": 2},
    # Agent 4a's one-off payout grant (review item 3): minutes it stays valid after the contract is signed.
    "payout": {"token_ttl_min": 15},
    # Agent 2 ↔ Agent 3 arbitration (review item 1): at most ``max_rounds`` question/answer rounds; past the
    # cap the more cautious conclusion stands. A disagreement without any level Agent 3 accepts is a rejection.
    "arbitration": {"max_rounds": 2, "on_no_acceptable": "reject"},
    # Agent 3's challenger model (review item 2): its probability of default moves phase 1.
    "challenger": {"smaller_at": 0.30, "escalate_at": 0.60},
    # FATE cold start (review 16/10/2026, item 5): a score built on few bank relationships is "thin";
    # its 15 points come from alternative signals and the limit gets a lower cap.
    "fate": {
        "thin_min_banks": 2,
        "thin_cap_mult": 0.5,
        "thin_cap_abs": 50_000,
        # Alternative signals (B6) when FATE is thin: max points per signal, 15 in total.
        "alt_points": {"invoice_regularity": 5, "supply_chain": 4, "payroll": 3, "registry_age": 3},
    },
    # Seed loan (review item 6): the first loan is a fraction of the computed limit; the fraction grows
    # from the second loan only once real sales money has flowed through the WeBank business account.
    "seed": {
        "ratio": [0.50, 0.75, 1.0],
        "min_webank_months": 3,
        "min_inflow_share": 0.80,
    },
    # Agent 3 explains its decision to the seller (SELLER_SERVICES_PLAN §4): list lengths.
    "explain": {"max_because": 4, "max_improve": 3},
}

ORIGIN: dict[str, str] = {
    "tier1.lookback_days": "TIEN_LE",
    "tier1.advance_rate": "TIEN_LE",
    "tier2.group_cap_mult": "DAT_TAY",
    "prudence": "DAT_TAY",
    "rates.A": "TIEN_LE",
    "rates.D": "TIEN_LE",
    "rates.B": "DAT_TAY",
    "rates.C": "DAT_TAY",
    "flags": "DAT_TAY",
    "gate.auto_limit": "DAT_TAY",
    "banks.min_share": "DAT_TAY",
    "payout_days": "TIEN_LE",
    "stress.event_drop": "TIEN_LE",
    "stress.event_threshold": "DAT_TAY",
    "gate.npl_off_ratio": "DAT_TAY",
    "legal.rate_cap": "DAT_TAY",
    "legal.ltr_threshold": "TIEN_LE",
    "legal.individual_registration_threshold": "TIEN_LE",  # NETTRADE-2021#8: 年交易额累计不超过10万元
    "legal.individual_registration_warn_share": "DAT_TAY",
    "use_of_funds.days": "TIEN_LE",
    "consent.ttl_days": "DAT_TAY",
    "rates.cost_of_funds": "DAT_TAY",
    "product.tenors": "DOI_CHOT",
    "product.borrower_picks_tenor": "DOI_CHOT",
    "product.methods": "DOI_CHOT",
    "repay.pay_supplier_direct": "DOI_CHOT",
    "product.type_cap": "TIEN_LE",
    "product.group_cap_mult": "DAT_TAY",
    "product.first_due_min_days": "DAT_TAY",
    "product.limit_valid_days": "TIEN_LE",
    "revenue": "DAT_TAY",
    "repay.min_principal_share": "TIEN_LE",
    "repay.min_max_consecutive": "TIEN_LE",
    "repay.grace_days": "TIEN_LE",
    "repay.penalty_mult": "DAT_TAY",
    "repay.report_overdue_days": "TIEN_LE",
    "repay.reminder_days": "TIEN_LE",
    "repay.supplier_direct_threshold": "DOI_CHOT",
    "repay.majority": "TIEN_LE",
    "repay.large_personal_transfer": "DAT_TAY",
    "repay.forecast_days": "DAT_TAY",
    "repay.forecast_lookback_days": "DAT_TAY",
    "repay.large_spend_share": "DAT_TAY",
    "early_warning.dsr_max": "DAT_TAY",
    "syndicate": "TIEN_LE",
    "contract.read_seconds": "DAT_TAY",
    "fate": "DAT_TAY",
    "arbitration": "DAT_TAY",
    "payout": "DAT_TAY",
    "complaint": "DAT_TAY",
    "challenger": "DAT_TAY",
    "seed": "DAT_TAY",
}


def with_defaults(params: dict[str, Any], defaults: dict[str, Any] = DEFAULT_PARAMS) -> dict[str, Any]:
    """``params`` with every key it lacks filled from ``defaults`` (recursively).

    A version stored before a parameter existed keeps its own values and gains
    only the missing keys, so older databases keep working after an upgrade."""
    out = copy.deepcopy(params)
    for key, value in defaults.items():
        if key not in out:
            out[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(out[key], dict):
            out[key] = with_defaults(out[key], value)
    return out


def active_params(session: Session) -> dict[str, Any]:
    from app.platform.tables import BuParams

    row = session.scalar(select(BuParams).where(BuParams.active.is_(True)).limit(1))
    return with_defaults(row.params) if row else copy.deepcopy(DEFAULT_PARAMS)


def get_path(params: dict[str, Any], dotted: str) -> Any:
    node: Any = params
    for part in dotted.split("."):
        node = node[part]
    return node


def set_path(params: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    node = params
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value
