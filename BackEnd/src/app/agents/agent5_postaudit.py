"""Agent 5 · Hậu kiểm: compare loans with real outcomes, propose parameter changes.

Agent 5 only *proposes*. An admin approval creates a new ``bu_params`` version
(v4.1, v4.2, …), deactivates the previous one and anchors its hash on the
chain (case "system", kind "params").

Prudence backtest (pi-box of core_tech): the prudence factor of a segment is
"the share of the forecast that 80 % of sellers actually reach". For each
segment we pool (a) a synthetic historical sample (labelled simulated) and
(b) this platform's matured loans (closed, or past the final due date), with
ratio = real inflow ÷ forecast. Hit rate = share of ratios ≥ the current
factor; below the 0.80 target → propose the 20th percentile (rounded down to
0.01) as the new factor.
"""

from __future__ import annotations

import json
import math
import secrets
from collections import Counter
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.platform.errors import api_error
from app.blockchain import chain
from app.platform import events
from app.core import legal
from app.agents.agent4b_monitor import is_bad_loan, parse_date, today
from app.core.algorithm import floor_to
from app.core.params import DEFAULT_PARAMS, active_params, get_path, set_path
from app.platform.tables import BuApplication, BuEvent, BuLoan, BuMessage, BuParams, BuProposal, BuReport, BuUser, save_json
from app.platform.db.tables import utcnow

TARGET_HIT_RATE = 0.80
MIN_CHANGE = 0.02
# Agent 5 §6/§8: below this many ratios in a segment, report "chưa đủ mẫu" and propose nothing [Đặt tay].
# ``BUOYUP_AGENT5_MIN_SAMPLE`` (default 30); tests set the module value directly.
MIN_SAMPLE: int | None = None


def min_sample() -> int:
    from app.platform.config import settings

    return int(MIN_SAMPLE if MIN_SAMPLE is not None else settings.buoyup_agent5_min_sample)
# §3.3: a prudence factor moves at most this much per quarter (90 days), all approvals added up [Đặt tay].
MAX_PRUDENCE_STEP = 0.04
STEP_WINDOW_DAYS = 90

# Synthetic backtest sample per segment ([Ví dụ], simulated): real inflow ÷ forecast
# of past campaigns. "thời trang" is deliberately below target at 0.70.
_FASHION_SAMPLE = [0.55, 0.60, 0.63, 0.65, 0.68, 0.71, 0.72, 0.74, 0.78, 0.80,
                   0.83, 0.85, 0.88, 0.90, 0.93, 0.96, 1.00, 1.04, 1.08, 1.15]
_HEALTHY_MULTS = [0.90, 0.95, 0.98, 1.00, 1.02, 1.04, 1.06, 1.08, 1.10, 1.12,
                  1.15, 1.18, 1.20, 1.24, 1.28, 1.32, 1.36, 1.40, 1.45, 1.50]
SYNTHETIC_SAMPLES: dict[str, list[float]] = {
    segment: (_FASHION_SAMPLE if segment == "thời trang"
              else [round(factor * m, 2) for m in _HEALTHY_MULTS])
    for segment, factor in DEFAULT_PARAMS["prudence"].items()
}


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile (q in [0, 1]) of ``values``."""
    data = sorted(values)
    if not data:
        return 0.0
    pos = q * (len(data) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


def _matured_ratios(session: Session) -> dict[str, list[float]]:
    now = today()
    out: dict[str, list[float]] = {}
    for loan in session.scalars(select(BuLoan)):
        doc = loan.doc or {}
        final = parse_date(doc.get("final_due_date"))
        matured = loan.status == "closed" or (final is not None and now > final)
        monthly = int(doc.get("forecast_monthly") or 0)
        start = parse_date(doc.get("start_date"))
        end = parse_date(doc.get("closed_on")) or min(now, final or now)
        if not matured or monthly <= 0 or start is None:
            continue
        # Loan circle: every platform payout goes to the WeBank business account until the loan is
        # closed, so the money that arrived there is the revenue actually achieved over the months observed.
        months = max(1, round((end - start).days / 30.4))
        out.setdefault(str(doc.get("category") or "khác"), []).append(
            round(int(doc.get("inflow_total", 0)) / (monthly * months), 4))
    return out


def backtest_prudence(session: Session, params: dict[str, Any]) -> list[dict[str, Any]]:
    own = _matured_ratios(session)
    findings = []
    for segment, factor in params["prudence"].items():
        ratios = SYNTHETIC_SAMPLES.get(segment, []) + own.get(segment, [])
        if not ratios:
            continue
        hit = sum(1 for r in ratios if r >= factor) / len(ratios)
        p20 = math.floor(round(percentile(ratios, 1 - TARGET_HIT_RATE) * 100, 6)) / 100
        synthetic, real = len(SYNTHETIC_SAMPLES.get(segment, [])), len(own.get(segment, []))
        need = min_sample()
        enough = len(ratios) >= need
        findings.append({
            "metric": "prudent_hit_rate", "segment": segment, "value": round(hit, 2),
            "target": TARGET_HIT_RATE, "current_factor": factor, "suggested_factor": p20,
            "sample": len(ratios), "own_loans": real, "synthetic_samples": synthetic,
            "simulated": synthetic > 0, "enough_sample": enough,
            "text": (f"Ngành {segment}: {hit * 100:.0f}% người bán đạt mức thận trọng {factor:.2f} × dự báo "
                     f"(mục tiêu {TARGET_HIT_RATE * 100:.0f}%); phân vị 20% là {p20:.2f} "
                     f"trên {len(ratios)} mẫu ({real} khoản vay thật, {synthetic} mẫu tổng hợp)."
                     + ("" if enough else f" Chưa đủ mẫu ({len(ratios)}/{need}): không đề xuất.")),
        })
    return findings


def rule_stats(session: Session) -> list[dict[str, Any]]:
    """How often each rule / flag fired across applications (from their docs)."""
    counter: Counter[str] = Counter()
    for doc in session.scalars(select(BuApplication.doc)):
        doc = doc or {}
        for flag in ((doc.get("verification") or {}).get("flags") or []):
            if flag.get("code"):
                counter[str(flag["code"])] += 1
        for result in (((doc.get("control") or {}).get("phase0") or {}).get("results") or []):
            if result.get("code") and result.get("ok") is False:
                counter[str(result["code"])] += 1
        for legal in ((doc.get("control") or {}).get("legal") or []):
            if legal.get("code") and legal.get("ok") is False:
                counter[str(legal["code"])] += 1
    return [{"rule": rule, "fired": n} for rule, n in counter.most_common()]


def manipulation_blocked(session: Session) -> int:
    """Numbers blocked in Agent 2 messages + blocked propose/injection events."""
    numbers = session.scalar(select(func.coalesce(func.sum(BuMessage.blocked_numbers), 0))) or 0
    blocked_events = session.scalar(
        select(func.count()).select_from(BuEvent).where(BuEvent.kind.like("%blocked%"))
    ) or 0
    return int(numbers) + int(blocked_events)


def citation_rejected(session: Session) -> list[dict[str, Any]]:
    """Agent 3 citations dropped by ``legal.verify_citation`` (events ``citation_rejected``), by rule."""
    counter: Counter[str] = Counter()
    for payload in session.scalars(select(BuEvent.payload).where(BuEvent.kind == "citation_rejected")):
        counter[str((payload or {}).get("rule") or "?")] += 1
    return [{"rule": rule, "count": n} for rule, n in counter.most_common()]


def legal_rule_hits(session: Session) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for doc in session.scalars(select(BuApplication.doc)):
        for item in ((doc or {}).get("control") or {}).get("legal") or []:
            if item.get("ok") is False and item.get("code"):
                counter[str(item["code"])] += 1
    return [{"rule": rule, "hits": n} for rule, n in counter.most_common()]


def complaint_stats(session: Session) -> dict[str, Any]:
    """Review item 4: complaints by category and by the decision reason they contest, and how many were
    answered in time. A reason that draws many complaints is a rule worth revisiting."""
    from app.platform.tables import BuComplaint

    rows = list(session.scalars(select(BuComplaint)))
    by_cat: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    answered = on_time = changed = 0
    for c in rows:
        by_cat[c.category] = by_cat.get(c.category, 0) + 1
        reason = ((c.reasons or {}).get("reason") or {}).get("law") or "không có lý do ghi nhận"
        by_reason[reason] = by_reason.get(reason, 0) + 1
        if c.answered_at:
            answered += 1
            on_time += int(c.answered_at <= c.answer_due)
            changed += int(c.outcome in ("changed", "reopened"))
    return {"total": len(rows), "by_category": by_cat,
            "top_reasons": sorted(({"reason": k, "count": v} for k, v in by_reason.items()), key=lambda x: -x["count"])[:5],
            "answered": answered, "on_time_rate": round(on_time / answered, 4) if answered else None,
            "changed_or_reopened": changed}


def debate_stats(session: Session) -> dict[str, Any]:
    """Review item 1: how often Agent 2 and Agent 3 needed rounds, and how often the cap was reached."""
    from app.platform.tables import BuApplication

    rounds = capped = cases = 0
    for row in session.scalars(select(BuApplication)):
        p2 = ((row.doc or {}).get("control") or {}).get("phase2") or {}
        if not p2:
            continue
        cases += 1
        rounds += len(p2.get("rounds") or [])
        capped += int(bool(p2.get("cap_reached")))
    return {"cases": cases, "rounds": rounds, "cap_reached": capped}


def _loans_by_app(session: Session) -> dict[str, BuLoan]:
    return {loan.application_id: loan for loan in session.scalars(select(BuLoan))}


def disagreement(session: Session, params: dict[str, Any]) -> dict[str, Any]:
    """Share of reviewed cases where Agent 3's blind phase-1 verdict differs from Agent 2's
    proposal; outside ``agent5.disagreement_band`` the reviewer is too lax or too harsh."""
    cases = disagree = 0
    for doc in session.scalars(select(BuApplication.doc)):
        p1 = ((doc or {}).get("control") or {}).get("phase1")
        if not p1:
            continue
        cases += 1
        proposal = (doc.get("proposal") or {}).get("option_id")
        disagree += 1 if (p1.get("verdict") != "approve" or p1.get("option_id") != proposal) else 0
    lo, hi = params["agent5"]["disagreement_band"]
    rate = round(disagree / cases, 4) if cases else 0.0
    return {"rate": rate, "cases": cases, "disagree": disagree, "band": [lo, hi],
            "flag": bool(cases) and not (lo <= rate <= hi)}


def persuaded_wrong(session: Session, params: dict[str, Any]) -> int:
    """Phase 2 went lighter than phase 1 (Agent 3 was persuaded) and the loan later went bad."""
    loans = _loans_by_app(session)
    day = today()
    n = 0
    for app_id, doc in session.execute(select(BuApplication.id, BuApplication.doc)):
        c = (doc or {}).get("control") or {}
        p1, p2 = c.get("phase1") or {}, c.get("phase2") or {}
        if not p1 or not p2 or legal.SEVERITY[p2["verdict"]] >= legal.SEVERITY[p1["verdict"]]:
            continue
        loan = loans.get(app_id)
        n += 1 if loan is not None and is_bad_loan(loan, params, day) else 0
    return n


def _bad_rate(loans: list[BuLoan], params: dict[str, Any]) -> float:
    day = today()
    return sum(1 for ln in loans if is_bad_loan(ln, params, day)) / len(loans) if loans else 0.0


def _changed_enough(old: float, new: float) -> bool:
    """MIN_CHANGE guard: absolute for ratios (< 1), relative for amounts and points."""
    step = MIN_CHANGE * abs(old) if abs(old) >= 1 else MIN_CHANGE
    return abs(new - old) >= step - 1e-9


def cohort_proposals(session: Session, params: dict[str, Any], report_id: str) -> list[BuProposal]:
    """Beyond prudence: lower ``gate.auto_limit`` when auto-approved loans go bad, raise a
    ``scorecard.grades`` bound when a grade's loans go bad, tighten ``flags.inflow_gap``
    when loans that carried RISK_INFLOW_GAP go bad. Proposals only; ``MIN_CHANGE`` guard;
    no second pending proposal for the same parameter."""
    cfg = params["agent5"]
    trigger, min_n = float(cfg["bad_rate_trigger"]), int(cfg["min_cohort"])
    pending = set(session.scalars(select(BuProposal.param).where(BuProposal.status == "pending")))
    docs = dict(session.execute(select(BuApplication.id, BuApplication.doc)).all())
    loans = list(session.scalars(select(BuLoan)))
    out: list[BuProposal] = []

    def add(param: str, cohort: list[BuLoan], threshold: float, to_value: Any, why: str) -> None:
        if param in pending or len(cohort) < min_n:
            return
        rate = _bad_rate(cohort, params)
        current = get_path(params, param)
        if rate < threshold or to_value == current or not _changed_enough(float(current), float(to_value)):
            return
        out.append(BuProposal(
            id="prop_" + secrets.token_hex(6), report_id=report_id, param=param, from_value=current,
            to_value=to_value, status="pending",
            evidence=f"{why}: {rate * 100:.0f}% nợ xấu trên {len(cohort)} khoản (ngưỡng xem xét {threshold * 100:.0f}%). "
                     "Đề nghị hội đồng rủi ro xem xét.",
        ))

    auto = [ln for ln in loans if ((docs.get(ln.application_id) or {}).get("decision") or {}).get("by") == "gate"]
    limit = int(params["gate"]["auto_limit"])
    add("gate.auto_limit", auto, trigger, max(10_000, floor_to(limit * 0.8, 10_000)),
        "Khoản duyệt tự động có nợ xấu cao")
    for grade in ("A", "B", "C", "D"):
        cohort = [ln for ln in loans if (ln.doc or {}).get("grade") == grade]
        bound = int(params["scorecard"]["grades"][grade])
        add(f"scorecard.grades.{grade}", cohort, 2 * trigger, min(100, bound + 5), f"Khoản vay hạng {grade} trả kém")
    lifted = [ln for ln in loans
              if ((docs.get(ln.application_id) or {}).get("internal") or {}).get("statements_verified")]
    bonus = float(params["revenue"]["statement_bonus"])
    add("revenue.statement_bonus", lifted, 2 * trigger, max(0.0, round(bonus - 0.02, 2)),
        "Hồ sơ được nâng hạn mức nhờ ảnh doanh thu tự nộp trả kém")
    return out


def _proposals_from(session: Session, findings: list[dict[str, Any]], report_id: str) -> list[BuProposal]:
    """Prudence proposals. None while a proposal for the same parameter is pending (each run used
    to add one more), none on a sample below MIN_SAMPLE (§6), and at most MAX_PRUDENCE_STEP away
    from the current factor (§3.3: 0,70 → 0,66 even when the backtest says 0,64)."""
    pending = set(session.scalars(select(BuProposal.param).where(BuProposal.status == "pending")))
    out = []
    for f in findings:
        param = f"prudence.{f['segment']}"
        if param in pending or not f.get("enough_sample", True):
            continue
        # Rounded first: 0.70 → 0.68 is a change of exactly MIN_CHANGE, not 0.0199999… (float subtraction).
        if f["value"] >= TARGET_HIT_RATE or round(abs(f["suggested_factor"] - f["current_factor"]), 4) < MIN_CHANGE:
            continue
        room = round(MAX_PRUDENCE_STEP - quarter_moves(session, param), 4)  # what is left of this quarter's step
        if room < MIN_CHANGE:
            continue
        step = max(-room, min(room, f["suggested_factor"] - f["current_factor"]))
        to_value = round(f["current_factor"] + step, 4)
        sample = (f"{f['sample']} mẫu ({f['own_loans']} khoản vay thật, {f.get('synthetic_samples', 0)} mẫu "
                  "tổng hợp)") if f.get("synthetic_samples") else f"{f['sample']} khoản vay thật"
        out.append(BuProposal(
            id="prop_" + secrets.token_hex(6), report_id=report_id, param=param,
            from_value=f["current_factor"], to_value=to_value, status="pending",
            evidence=(f"Tỷ lệ đạt {f['value'] * 100:.0f}% < {TARGET_HIT_RATE * 100:.0f}% trên {sample}; "
                      f"kiểm định ngược cho phân vị 20% = {f['suggested_factor']:.2f}"
                      + (f", đề xuất trong giới hạn {MAX_PRUDENCE_STEP:.2f} mỗi quý" if to_value != f["suggested_factor"]
                         else "") + ". Đề nghị hội đồng rủi ro duyệt hệ số mới."),
        ))
        pending.add(param)
    return out


def shadow_run(session: Session, params: dict[str, Any], param: str, to_value: Any,
               limit: int = 200) -> dict[str, Any]:
    """§3.7 "chạy song song": re-run the algorithm on recent offered cases with the proposed value,
    using the old one for nothing but the comparison. Read-only."""
    from app.agents import agent2_advise as advise

    trial = json.loads(json.dumps(params))
    set_path(trial, param, to_value)
    cases = changed = 0
    delta = 0
    rows = session.scalars(select(BuApplication).order_by(BuApplication.created_at.desc()).limit(limit))
    for row in rows:
        doc = row.doc or {}
        if not (doc.get("offer") and (doc.get("internal") or {}).get("data")):
            continue
        try:
            old = advise.compute(params, row, doc)["amount"]
            new = advise.compute(trial, row, doc)["amount"]
        except Exception:  # noqa: BLE001 - an old case the current algorithm cannot read is skipped
            continue
        cases += 1
        if new != old:
            changed += 1
            delta += int(new) - int(old)
    return {"param": param, "to": to_value, "cases": cases, "changed": changed, "amount_delta": delta,
            "simulated": True}


def _proposal_record(p: BuProposal) -> dict[str, Any]:
    return {"id": p.id, "param": p.param, "from": p.from_value, "to": p.to_value, "evidence": p.evidence}


def run(session: Session, user: BuUser) -> tuple[BuReport, list[BuProposal]]:
    params = active_params(session)
    loans = session.scalar(select(func.count()).select_from(BuLoan)) or 0
    closed = session.scalar(select(func.count()).select_from(BuLoan).where(BuLoan.status == "closed")) or 0
    report_id = "rep_" + secrets.token_hex(6)
    findings = backtest_prudence(session, params)
    data = {
        "id": report_id, "at": utcnow().isoformat() + "Z", "params_version": _active_version(session),
        "cohort": {"loans": int(loans), "closed": int(closed)},
        "findings": findings, "rule_stats": rule_stats(session),
        "manipulation_blocked": manipulation_blocked(session),
        "citation_rejected": citation_rejected(session),
        "persuaded_wrong": persuaded_wrong(session, params),
        "a2_a3_disagreement": disagreement(session, params),
        "debate": debate_stats(session),
        "complaints": complaint_stats(session),
        "legal_rule_hits": legal_rule_hits(session),
        "auto_cohort": auto_cohort_npl(session, params),
        "requested_by": user.id,
        # Simulated when any finding leans on the synthetic backtest sample (not "always").
        "simulated": any(f.get("simulated") for f in findings),
    }
    data["a2_a3_disagreement_rate"] = data["a2_a3_disagreement"]["rate"]
    proposals = _proposals_from(session, findings, report_id) + cohort_proposals(session, params, report_id)
    # The model reads the finished numbers, may add guarded proposals and writes the council summary;
    # all of it is inside the report before its hash goes on chain.
    from app.agents import agent5_llm as llm_agent5

    summary, extra, calls = llm_agent5.review(session, data, params, report_id, proposals)
    proposals += extra
    data["summary"] = llm_agent5.summary_payload(summary, extra)
    for p in proposals:  # §3.7: what would change, on last quarter's cases
        p.evidence = (p.evidence or "") + _shadow_text(shadow_run(session, params, p.param, p.to_value))
    for call in calls:
        events.log(session, "system", "agent5", "llm_tool_call", f"{call['id']} · {call['tool']}",
                   {"report_id": report_id, "tool_call": {k: call[k] for k in ("id", "tool", "input", "output")}})
    # Everything the council will decide on is inside the hashed report: each proposal's parameter,
    # values and evidence, and the model's tool calls (README principle 4).
    data["proposals"] = [_proposal_record(p) for p in proposals]
    data["llm_tool_calls"] = [{k: c.get(k) for k in ("id", "tool", "input")} for c in calls]
    entry = chain.record(session, "system", "postaudit_report", data)
    data["hash"], data["chain_tx"] = entry.fingerprint, entry.tx
    report = BuReport(id=report_id, data=data, at=utcnow())
    session.add(report)
    session.add_all(proposals)
    events.log(session, "system", "agent5", "postaudit_report",
               f"Hậu kiểm: {loans} khoản vay, {len(proposals)} đề xuất", {"report_id": report_id},
               entry.fingerprint)
    session.flush()
    return report, proposals


def _shadow_text(shadow: dict[str, Any]) -> str:
    if not shadow["cases"]:
        return " Chạy song song: chưa có hồ sơ nào để so."
    delta = f"{shadow['amount_delta']:+,}".replace(",", ".")  # Vietnamese thousands separator, number only
    return (f" Chạy song song trên {shadow['cases']} hồ sơ gần nhất: {shadow['changed']} hồ sơ đổi hạn mức, "
            f"tổng thay đổi {delta} tệ.")


def auto_cohort_npl(session: Session, params: dict[str, Any]) -> dict[str, Any]:
    """§3.2: bad-loan rate of the auto-approved loans against the hard switch (code, Agent 4) and an
    earlier warning line (WARN_SHARE of it) at which Agent 5 reports to the council."""
    docs = dict(session.execute(select(BuApplication.id, BuApplication.doc)).all())
    auto = [ln for ln in session.scalars(select(BuLoan))
            if ((docs.get(ln.application_id) or {}).get("decision") or {}).get("by") == "gate"]
    hard = float(params["gate"]["npl_off_ratio"])
    warn = round(hard * WARN_SHARE, 4)
    rate = round(_bad_rate(auto, params), 4)
    status = "hard" if auto and rate >= hard else "warn" if auto and rate >= warn else "ok"
    return {"loans": len(auto), "bad_rate": rate, "warn": warn, "hard": hard, "status": status}


WARN_SHARE = 0.75  # warning at 3/4 of the hard switch (spec: 3% against 4%) [Đặt tay]


def _active_version(session: Session) -> str:
    row = session.scalar(select(BuParams).where(BuParams.active.is_(True)).limit(1))
    return row.version if row else "v4.0"


def _next_version(session: Session) -> str:
    minors = []
    for version in session.scalars(select(BuParams.version)):
        major, _, minor = version.lstrip("v").partition(".")
        if major == "4" and minor.isdigit():
            minors.append(int(minor))
    return f"v4.{max(minors, default=0) + 1}"


def decide(session: Session, proposal: BuProposal, user: BuUser, decision: str, note: str) -> BuParams | None:
    """Admin decision. Approve → new active parameter version anchored on the chain."""
    if proposal.status != "pending":
        raise api_error(400, "INVALID_STATE", "Đề xuất này đã được quyết định.")
    report = session.get(BuReport, proposal.report_id)
    if report is not None and (report.data or {}).get("requested_by") == user.id:
        # Independent review (NETLOAN-2020#39): who ran the post-audit cannot approve its proposals.
        raise api_error(403, "FORBIDDEN", "Người chạy hậu kiểm không được tự duyệt đề xuất của lần chạy đó.")
    proposal.decided_by, proposal.decided_at, proposal.note = user.id, utcnow(), note
    if decision == "reject":
        proposal.status = "rejected"
        entry = chain.record(session, "system", "proposal_decision", {
            "proposal_id": proposal.id, "param": proposal.param, "from": proposal.from_value,
            "to": proposal.to_value, "decision": "rejected", "by": user.id, "note": note[:500]})
        events.log(session, "system", "admin", "proposal_rejected", f"Từ chối đề xuất {proposal.param}",
                   {"proposal_id": proposal.id, "by": user.id}, entry.fingerprint)
        session.flush()
        return None
    params = active_params(session)
    try:
        current = get_path(params, proposal.param)
    except (KeyError, TypeError):
        raise api_error(400, "INVALID_STATE", "Tham số trong đề xuất không còn tồn tại.") from None
    if current != proposal.from_value:
        raise api_error(400, "INVALID_STATE", "Tham số đã đổi từ khi đề xuất; hãy chạy lại hậu kiểm.",
                        {"current": current, "from": proposal.from_value})
    from app.agents.agent5_llm import out_of_bounds

    if isinstance(proposal.to_value, (int, float)) and (problem := out_of_bounds(params, proposal.param,
                                                                               float(proposal.to_value))):
        raise api_error(400, "INVALID_STATE", problem)
    if proposal.param.startswith("prudence."):
        moved = quarter_moves(session, proposal.param)
        step = abs(float(proposal.to_value) - float(proposal.from_value))
        if moved + step > MAX_PRUDENCE_STEP + 1e-9:
            raise api_error(400, "INVALID_STATE",
                            f"{proposal.param} đã đổi {moved:.2f} trong {STEP_WINDOW_DAYS} ngày; mỗi quý tối đa "
                            f"{MAX_PRUDENCE_STEP:.2f}.", {"moved": moved, "step": step})
    set_path(params, proposal.param, proposal.to_value)
    version = _next_version(session)
    entry = chain.record(session, "system", "params", {"version": version, "params": params})
    for row in session.scalars(select(BuParams).where(BuParams.active.is_(True))):
        row.active = False
    new = BuParams(version=version, hash=entry.fingerprint, chain_tx=entry.tx, active=True, created_at=utcnow(),
                   note=f"{proposal.param}: {proposal.from_value} → {proposal.to_value} (đề xuất {proposal.id})")
    save_json(new, "params", params)
    session.add(new)
    proposal.status = "approved"
    events.log(session, "system", "admin", "params_version",
               f"Duyệt {proposal.param} {proposal.from_value} → {proposal.to_value}: phiên bản {version}",
               {"proposal_id": proposal.id, "version": version, "by": user.id}, entry.fingerprint)
    session.flush()
    return new


def quarter_moves(session: Session, param: str) -> float:
    """How far ``param`` moved through approved proposals in the last STEP_WINDOW_DAYS days."""
    since = utcnow() - timedelta(days=STEP_WINDOW_DAYS)
    rows = session.scalars(select(BuProposal).where(BuProposal.param == param, BuProposal.status == "approved",
                                                    BuProposal.decided_at >= since))
    return round(sum(abs(float(r.to_value) - float(r.from_value)) for r in rows), 4)


def proposal_view(p: BuProposal) -> dict[str, Any]:
    return {
        "id": p.id, "report_id": p.report_id, "param": p.param, "from": p.from_value, "to": p.to_value,
        "evidence": p.evidence, "status": p.status, "decided_by": p.decided_by,
        "decided_at": p.decided_at.isoformat() + "Z" if p.decided_at else None, "note": p.note,
    }


def params_view(session: Session) -> dict[str, Any]:
    rows = list(session.scalars(select(BuParams).order_by(BuParams.created_at, BuParams.version)))
    active = next((r for r in rows if r.active), None)
    history = [{"version": r.version, "hash": r.hash, "chain_tx": r.chain_tx, "active": r.active,
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else None, "note": r.note}
               for r in reversed(rows)]
    from app.platform.seed import latest_ruleset_entry

    ruleset = latest_ruleset_entry(session)
    return {
        "version": active.version if active else "v4.0",
        "hash": active.hash if active else "",
        "chain_tx": active.chain_tx if active else "",
        "params": active.params if active else DEFAULT_PARAMS,
        "history": history,
        "ruleset": {"version": legal.RULESET_VERSION, "hash": legal.RULESET_HASH,
                    "chain_tx": ruleset.tx if ruleset is not None else None,
                    "anchored_hash": ruleset.payload.get("hash") if ruleset is not None else None},
    }
