"""Train Agent 3's challenger model (app/core/challenger.py) and write app/core/models/challenger_v1.json.

Kept outside the request path: the server only reads the JSON. For the demo the labels are
SYNTHETIC (no bank has shared repayment outcomes yet); the file says so (``simulated: true``) and
must be retrained on the partner banks' repayment labels before any real lending.

    python scripts/train_challenger.py            # from BackEnd/src; deterministic (seed 20261016)

Synthetic world: plan-consistency and behaviour signals drive default risk, the way a credit
analyst reads them (price declared far above invoices, a supplier linked to the seller, inventory
claims above tax returns, a sudden sales spike, B2B-heavy sales, screenshots that disagree with tax).
Logistic regression by plain gradient descent on standardised features; holdout AUC reported.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.challenger import CHALLENGER_FEATURES, MODEL_PATH

SEED = 20261016
N = 6000


def synth(rng: np.random.Generator, n: int) -> tuple[np.ndarray, np.ndarray]:
    price_dev = np.clip(rng.gamma(1.2, 0.08, n), 0, 1.5)
    linked = (rng.random(n) < 0.06).astype(float)
    new_sup = (rng.random(n) < 0.20).astype(float)
    inv_ratio = np.clip(rng.lognormal(0.0, 0.35, n), 0, 4)
    spike = np.clip(rng.lognormal(0.0, 0.30, n), 0, 6)
    b2b = np.clip(rng.beta(1.2, 6.0, n), 0, 1)
    st_dev = np.where(rng.random(n) < 0.35, np.clip(rng.gamma(1.0, 0.07, n), 0, 1), 0.0)
    x = np.column_stack([price_dev, linked, new_sup, inv_ratio, spike, b2b, st_dev])
    # Hidden truth (unknown to the learner): log-odds of default.
    z = (-3.1 + 3.0 * price_dev + 1.6 * linked + 0.5 * new_sup + 0.9 * (inv_ratio - 1)
         + 0.8 * (spike - 1) + 1.2 * b2b + 3.5 * st_dev)
    y = (rng.random(n) < 1 / (1 + np.exp(-z))).astype(float)
    return x, y


def fit(x: np.ndarray, y: np.ndarray, steps: int = 4000, lr: float = 0.3, l2: float = 1e-3) -> tuple[np.ndarray, float]:
    w, b = np.zeros(x.shape[1]), 0.0
    for _ in range(steps):
        p = 1 / (1 + np.exp(-(x @ w + b)))
        w -= lr * (x.T @ (p - y) / len(y) + l2 * w)
        b -= lr * float(np.mean(p - y))
    return w, b


def auc(y: np.ndarray, s: np.ndarray) -> float:
    order = np.argsort(s)
    ranks = np.empty(len(s))
    ranks[order] = np.arange(1, len(s) + 1)
    pos = y == 1
    return float((ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * (~pos).sum()))


def main() -> None:
    rng = np.random.default_rng(SEED)
    x, y = synth(rng, N)
    cut = int(N * 0.8)
    mean, std = x[:cut].mean(axis=0), x[:cut].std(axis=0) + 1e-9
    w, b = fit((x[:cut] - mean) / std, y[:cut])
    holdout = auc(y[cut:], ((x[cut:] - mean) / std) @ w + b)
    model = {
        "version": "challenger-v1",
        "simulated": True,
        "note": "Huấn luyện trên dữ liệu tổng hợp (mô phỏng) để trình diễn; phải huấn luyện lại trên nhãn trả nợ thật.",
        "trained_on": {"rows": cut, "holdout_rows": N - cut, "seed": SEED, "default_rate": round(float(y.mean()), 4),
                       "holdout_auc": round(holdout, 4)},
        "features": list(CHALLENGER_FEATURES),
        "mean": {f: round(float(m), 6) for f, m in zip(CHALLENGER_FEATURES, mean)},
        "std": {f: round(float(s), 6) for f, s in zip(CHALLENGER_FEATURES, std)},
        "coef": {f: round(float(c), 6) for f, c in zip(CHALLENGER_FEATURES, w)},
        "intercept": round(b, 6),
    }
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_PATH.write_text(json.dumps(model, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {MODEL_PATH} · holdout AUC {holdout:.3f} · default rate {y.mean():.3f}")


if __name__ == "__main__":
    main()
