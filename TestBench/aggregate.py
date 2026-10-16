#!/usr/bin/env python3
"""Turn Testbench/results/raw_results.jsonl into a pass/fail sheet (CSV + Markdown).

PASS = system resisted the attack (secure). FAIL = attack succeeded (vulnerability).
"""
from __future__ import annotations

import csv
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
RES = HERE / "results"
RAW = RES / "raw_results.jsonl"

CATS = {
    "01_auth_session": "Auth & Session (login, face/ReID, tokens, IDOR)",
    "02_credit_limit": "Credit algorithm & limit inflation (B1–B12, consent)",
    "03_llm_rag_legal": "LLM agents, RAG & legal citations (prompt injection)",
    "04_ledger_disburse": "Ledger & disbursement (FISCO, HMAC, double-pay)",
    "05_api_authz_multibank": "API authz & multi-bank (RBAC, validation, syndicate)",
}
DIFF_ORDER = {"easy": 0, "medium": 1, "hard": 2, "unmarked": 3}


def load() -> list[dict]:
    if not RAW.exists():
        raise SystemExit(f"No results at {RAW}. Run ./run_testbench.sh first.")
    rows = [json.loads(line) for line in RAW.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows.sort(key=lambda r: (r["category"], DIFF_ORDER.get(r["difficulty"], 9), r["case"]))
    return rows


def write_csv(rows: list[dict]) -> None:
    with open(RES / "testbench_sheet.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Category", "Difficulty", "Case", "Result", "Meaning", "Seconds", "NodeID"])
        for r in rows:
            meaning = "resisted (secure)" if r["secure"] else ("ATTACK SUCCEEDED" if r["status"] == "FAIL" else "skipped")
            w.writerow([r["category"], r["difficulty"], r["case"], r["status"], meaning, r["duration_s"], r["nodeid"]])


def write_md(rows: list[dict]) -> None:
    total = len(rows)
    secure = sum(1 for r in rows if r["secure"])
    vulns = [r for r in rows if r["status"] == "FAIL"]
    lines = [
        "# BuoyUp Testbench — pass/fail sheet",
        "",
        f"**{secure}/{total}** attacks resisted · **{len(vulns)}** vulnerabilities found "
        f"({'0 open' if not vulns else str(len(vulns)) + ' OPEN — see below'}).",
        "",
        "> PASS = system resisted the attack (secure). FAIL = attack succeeded (vulnerability).",
        "",
        "## Summary by category",
        "",
        "| Category | Resisted | Vuln | Total |",
        "|---|---:|---:|---:|",
    ]
    for key, label in CATS.items():
        cat = [r for r in rows if r["category"] == key]
        if not cat:
            lines.append(f"| {label} | — | — | 0 |")
            continue
        s = sum(1 for r in cat if r["secure"])
        v = sum(1 for r in cat if r["status"] == "FAIL")
        lines.append(f"| {label} | {s} | {v} | {len(cat)} |")
    lines += ["", "## Summary by difficulty", "", "| Difficulty | Resisted | Vuln | Total |", "|---|---:|---:|---:|"]
    for d in ("easy", "medium", "hard"):
        dd = [r for r in rows if r["difficulty"] == d]
        s = sum(1 for r in dd if r["secure"])
        v = sum(1 for r in dd if r["status"] == "FAIL")
        lines.append(f"| {d} | {s} | {v} | {len(dd)} |")

    if vulns:
        lines += ["", "## ⚠️ Vulnerabilities (attack succeeded — FIX THESE)", "",
                  "| Category | Difficulty | Case | NodeID |", "|---|---|---|---|"]
        for r in vulns:
            lines.append(f"| {r['category']} | {r['difficulty']} | {r['case']} | `{r['nodeid']}` |")

    lines += ["", "## All cases", "", "| Category | Diff | Case | Result |", "|---|---|---|---|"]
    for r in rows:
        badge = "✅ PASS" if r["status"] == "PASS" else ("❌ FAIL" if r["status"] == "FAIL" else "➖ SKIP")
        lines.append(f"| {r['category']} | {r['difficulty']} | {r['case']} | {badge} |")
    (RES / "testbench_sheet.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    rows = load()
    write_csv(rows)
    write_md(rows)
    secure = sum(1 for r in rows if r["secure"])
    vulns = sum(1 for r in rows if r["status"] == "FAIL")
    print(f"Testbench: {len(rows)} cases · {secure} resisted · {vulns} vulnerabilities")
    print(f"  -> {RES/'testbench_sheet.md'}")
    print(f"  -> {RES/'testbench_sheet.csv'}")


if __name__ == "__main__":
    main()
