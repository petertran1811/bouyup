"""Retrieval quality on tests/rag_eval.json: recall@1/3/5 and MRR@10 per mode (bm25, dense, hybrid).

    cd BackEnd/src && ../.venv/bin/python scripts/eval_rag.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import rag  # noqa: E402

CASES = json.loads((Path(__file__).resolve().parents[1] / "tests" / "rag_eval.json").read_text(encoding="utf-8"))


def evaluate(use: str) -> dict:
    r1 = r3 = r5 = mrr = 0.0
    misses = []
    for c in CASES:
        ids = [h["article_id"] for h in rag.search(c["q"], k=10, use=use)]
        rank = next((i + 1 for i, a in enumerate(ids) if a in c["gold"]), None)
        r1 += rank == 1; r3 += bool(rank and rank <= 3); r5 += bool(rank and rank <= 5)
        mrr += 1 / rank if rank else 0
        if not rank or rank > 5:
            misses.append((c["q"], ids[:3]))
    n = len(CASES)
    return {"mode": use, "n": n, "recall@1": round(r1 / n, 3), "recall@3": round(r3 / n, 3),
            "recall@5": round(r5 / n, 3), "mrr@10": round(mrr / n, 3), "misses": misses}


if __name__ == "__main__":
    modes = ["bm25"] + (["dense", "hybrid"] if rag.index().dense_ready() else [])
    for m in modes:
        res = evaluate(m)
        print({k: v for k, v in res.items() if k != "misses"})
        for q, ids in res["misses"]:
            print("   miss:", q, "→", ids)
