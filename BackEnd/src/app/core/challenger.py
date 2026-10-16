"""Agent 3's challenger model (review item 2, 16/10/2026).

Agent 3 must not be the same reasoning on the same numbers as Agent 2. Next to the deterministic
ruleset it runs this model: a logistic risk score trained separately (``scripts/train_challenger.py``)
on a feature set that shares no feature with what Agent 2 and the decision core score with
(``AGENT2_FEATURES``: the B6 scorecard and the B3/B4/B5/B8 inputs). Its features are behavioural
and plan-consistency signals: price declared vs invoices, supplier links and history, inventory
declared vs tax returns, the latest sales spike, the B2B share of sales and the seller statements'
deviation from tax.

The model file (``models/challenger_v1.json``) carries its feature list, coefficients, training
metadata and a hash; it is trained on synthetic labelled data for the demo (``simulated``), to be
retrained on the banks' repayment labels. Inference is plain Python so the decision core needs no
numerical library.
"""

from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

MODEL_PATH = Path(__file__).resolve().parent / "models" / "challenger_v1.json"

# What Agent 2 and the decision core score with (B6 scorecard + B3/B4/B5/B8 inputs).
AGENT2_FEATURES = frozenset({
    "late_max_days_24m", "inquiries_3m", "debt_to_inflow", "interbank_score", "store_rating",
    "months_with_sales", "cv_monthly", "gross_margin", "monthly_avg_12m", "growth_3m", "prudence",
    "platform_fee", "unit_price_used", "plan_value", "need", "customer_group", "type_cap",
})
# The challenger's own features: none of them is an Agent 2 feature (tests/test_arbitration.py).
CHALLENGER_FEATURES = (
    "price_deviation", "supplier_linked", "supplier_new", "inventory_ratio", "sales_spike_ratio",
    "b2b_sales_share", "statement_deviation",
)


@lru_cache(maxsize=1)
def model() -> dict[str, Any]:
    raw = MODEL_PATH.read_bytes()
    out = json.loads(raw)
    out["hash"] = "sha256:" + hashlib.sha256(raw).hexdigest()
    if tuple(out["features"]) != CHALLENGER_FEATURES:
        raise RuntimeError("challenger model features do not match CHALLENGER_FEATURES")
    return out


# Training ranges (scripts/train_challenger.py): inputs are clipped so the model never extrapolates.
_RANGE = {"price_deviation": (0.0, 1.5), "inventory_ratio": (0.0, 4.0), "sales_spike_ratio": (0.0, 6.0),
          "b2b_sales_share": (0.0, 1.0), "statement_deviation": (0.0, 1.0)}
# A flag an officer confirmed means the matching claim was checked by a person: no longer an anomaly.
_CONFIRMED_BY = {"RISK_INVENTORY_HIGH": ("inventory_ratio", 1.0), "RISK_SUPPLIER_LINKED": ("supplier_linked", 0.0),
                 "RISK_STATEMENT_MISMATCH": ("statement_deviation", 0.0)}


def features(doc: dict[str, Any]) -> dict[str, float]:
    """The challenger's inputs from Agent 1's tool results and the plan (no B6/B8 number)."""
    raw = _raw_features(doc)
    for f in (doc.get("verification") or {}).get("flags") or []:
        if f.get("code") in _CONFIRMED_BY and f.get("resolved_by") == "officer":
            name, value = _CONFIRMED_BY[f["code"]]
            raw[name] = value
    return {k: round(min(max(v, _RANGE[k][0]), _RANGE[k][1]), 4) if k in _RANGE else v for k, v in raw.items()}


def _raw_features(doc: dict[str, Any]) -> dict[str, float]:
    data = (doc.get("internal") or {}).get("data") or {}
    tax, rev = data.get("tax") or {}, data.get("revenue") or {}
    plan = {k: v for k, v in (doc.get("plan") or {}).items() if k not in ("suggested", "submitted")}
    invoice = tax.get("invoice_unit_price_3m")
    supplier = (data.get("suppliers") or {}).get(plan.get("supplier") or "", {})
    inventory_est = float(tax.get("inventory_estimate") or 0)
    statements = ((doc.get("verification") or {}).get("derived") or {}).get("statements") or {}
    return {
        "price_deviation": round(max(0.0, float(plan["price"]) / float(invoice) - 1), 4) if plan.get("price") and invoice else 0.0,
        "supplier_linked": 1.0 if supplier.get("linked") else 0.0,
        "supplier_new": 1.0 if plan.get("supplier") and not supplier.get("invoice_history", True) else 0.0,
        "inventory_ratio": round(float(plan.get("inventory") or 0) / inventory_est, 4) if inventory_est else 0.0,
        "sales_spike_ratio": float(rev.get("spike_ratio") or 0.0),
        "b2b_sales_share": float(tax.get("b2b_sales_share") or 0.0),
        "statement_deviation": float(statements.get("deviation") or 0.0),
    }


def score(feats: dict[str, float], m: dict[str, Any] | None = None) -> dict[str, Any]:
    """Probability of default from the logistic model, with each feature's contribution (log-odds)."""
    m = m or model()
    z = float(m["intercept"])
    contrib = {}
    for name in CHALLENGER_FEATURES:
        x = (float(feats.get(name, 0.0)) - m["mean"][name]) / m["std"][name]
        contrib[name] = round(m["coef"][name] * x, 4)
        z += m["coef"][name] * x
    pd = 1 / (1 + math.exp(-z))
    return {"pd": round(pd, 4), "contributions": contrib, "model": m["version"], "model_hash": m["hash"],
            "simulated": bool(m.get("simulated"))}


def verdict(params: dict[str, Any], pd: float) -> str:
    """``approve`` below ``challenger.smaller_at``, ``smaller`` below ``challenger.escalate_at``, else ``escalate``."""
    c = params["challenger"]
    if pd >= float(c["escalate_at"]):
        return "escalate"
    if pd >= float(c["smaller_at"]):
        return "smaller"
    return "approve"
