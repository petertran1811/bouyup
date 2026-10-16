"""Agent 5 (hậu kiểm) through the configured model.

The statistics are code (postaudit.py). The model reads the finished report, writes a short
summary for the risk council and may propose parameter changes through ``propose_change``.
Code guards every proposal: whitelisted parameter, numeric, a real change (MIN_CHANGE) but at
most ±25 %, no pending proposal for the same parameter, and a reference to a report section.
Proposals are never applied here: an admin other than the requester approves them
(postaudit.decide). Without a model, or on any failure, the report keeps no summary and only
the code proposals stand.
"""
from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import llm_tools
from app.agents.llm_tools import Tool, ToolRefused, obj
from app.core.params import get_path
from app.platform.tables import BuProposal
from app.platform.llm.messages import LLMMessage

AGENT5_SYSTEM = (
    "Bạn là Agent 5 (hậu kiểm) của BuoyUp. Đọc báo cáo hậu kiểm bằng get_report và tham số đang chạy bằng "
    "get_param. Nếu số liệu cho thấy một tham số nên chỉnh, gọi propose_change(param, to_value, evidence_ref, why): "
    "chỉ các tham số prudence.*, flags.*, gate.auto_limit, scorecard.grades.*; evidence_ref là tên một mục trong "
    "báo cáo. prudence.<ngành> là phần dự báo doanh thu được tin dùng: HẠ hệ số là THẬN TRỌNG hơn (cho vay ít "
    "hơn), tăng là nới. Mục 'code_proposals' là đề xuất code đã tạo, đừng lặp lại. Đề xuất chỉ là đề nghị, hội đồng "
    "rủi ro duyệt. Không đề xuất khi mẫu quá nhỏ hoặc không có bằng "
    "chứng. Cuối cùng viết tóm tắt tối đa 5 câu tiếng Việt cho hội đồng rủi ro: điều gì ổn, điều gì cần chú ý, "
    "đã đề xuất gì và vì sao. Viết văn xuôi, không dùng markdown. Chỉ dùng con số có trong báo cáo hoặc tham số."
)
ALLOWED_PREFIXES = ("prudence.", "flags.", "scorecard.grades.")
ALLOWED_EXACT = ("gate.auto_limit",)
MAX_RELATIVE_CHANGE = 0.25
MAX_PROPOSALS = 3
REPORT_SECTIONS = ("cohort", "findings", "rule_stats", "manipulation_blocked", "citation_rejected",
                   "persuaded_wrong", "a2_a3_disagreement", "legal_rule_hits")


def out_of_bounds(params: dict[str, Any], param: str, value: float) -> str | None:
    """Sanity bounds a change must keep (also re-checked when an admin approves)."""
    current = get_path(params, param)
    if isinstance(current, float) and 0 < current <= 1 and not 0 < value <= 1:
        return f"{param} là tỷ lệ, phải nằm trong (0, 1]."
    if param.startswith("scorecard.grades."):
        grades = dict(params["scorecard"]["grades"], **{param.rsplit(".", 1)[1]: value})
        order = [grades[g] for g in ("A", "B", "C", "D")]
        if not all(a > b for a, b in zip(order, order[1:])) or not (0 < order[-1] and order[0] <= 100):
            return "Ngưỡng hạng phải giữ thứ tự A > B > C > D trong (0, 100]."
    if value <= 0:
        return f"{param} phải lớn hơn 0."
    return None


def review(session: Session, data: dict[str, Any], params: dict[str, Any], report_id: str,
           code_proposals: list[BuProposal]) -> tuple[str | None, list[BuProposal], list[dict[str, Any]]]:
    """(summary, extra proposals, tool calls)."""
    from app.agents.agent2_advise import _walk, blocked
    from app.agents.agent5_postaudit import MAX_PRUDENCE_STEP, _changed_enough

    prov = llm_tools.provider()
    if prov is None:
        return None, [], []
    pending = set(session.scalars(select(BuProposal.param).where(BuProposal.status == "pending")))
    pending |= {p.param for p in code_proposals}
    made: list[BuProposal] = []
    seen_values: list[Any] = []

    def _allowed_numbers() -> set[float]:
        allowed: set[float] = set()
        _walk([get_report({}), seen_values, params], allowed)
        return allowed

    def get_report(_: dict[str, Any]) -> dict[str, Any]:
        out = {k: data.get(k) for k in REPORT_SECTIONS}
        out["code_proposals"] = [{"param": p.param, "from": p.from_value, "to": p.to_value} for p in code_proposals]
        return out

    def get_param(args: dict[str, Any]) -> dict[str, Any]:
        path = str(args.get("path") or "")
        try:
            value = get_path(params, path)
        except (KeyError, TypeError):
            raise ToolRefused(f"Không có tham số {path}.") from None
        seen_values.append(value)
        return {"path": path, "value": value}

    def propose_change(args: dict[str, Any]) -> dict[str, Any]:
        param = str(args.get("param") or "")
        ref = str(args.get("evidence_ref") or "")
        why = str(args.get("why") or "").strip()[:400]
        if not (param in ALLOWED_EXACT or param.startswith(ALLOWED_PREFIXES)):
            raise ToolRefused("Chỉ được đề xuất prudence.*, flags.*, gate.auto_limit, scorecard.grades.*.")
        if len(made) >= MAX_PROPOSALS:
            raise ToolRefused(f"Tối đa {MAX_PROPOSALS} đề xuất mỗi lần hậu kiểm.")
        if param in pending:
            raise ToolRefused(f"{param} đã có đề xuất đang chờ duyệt.")
        if ref not in REPORT_SECTIONS:
            raise ToolRefused("evidence_ref phải là một mục của báo cáo: " + ", ".join(REPORT_SECTIONS))
        if not why:
            raise ToolRefused("Cần nêu lý do (why).")
        try:
            current = get_path(params, param)
            to_value = float(args.get("to_value"))
        except (KeyError, TypeError, ValueError):
            raise ToolRefused(f"{param} không tồn tại hoặc to_value không phải số.") from None
        if isinstance(current, bool) or not isinstance(current, (int, float)):
            raise ToolRefused(f"{param} không phải tham số số.")
        if not _changed_enough(float(current), to_value):
            raise ToolRefused("Thay đổi quá nhỏ (dưới ngưỡng thay đổi tối thiểu).")
        if not current or abs(to_value - current) / abs(current) > MAX_RELATIVE_CHANGE:
            raise ToolRefused(f"Mỗi lần chỉ đổi tối đa {MAX_RELATIVE_CHANGE * 100:.0f}% so với giá trị hiện tại.")
        if param.startswith("prudence.") and abs(to_value - current) > MAX_PRUDENCE_STEP + 1e-9:
            raise ToolRefused(f"Hệ số thận trọng mỗi quý chỉ đổi tối đa {MAX_PRUDENCE_STEP:.2f}.")
        # §3.7/§6: every number in the reason must come from the report or the parameters.
        bad = blocked(why, _allowed_numbers())
        if bad:
            raise ToolRefused("Lý do có số không có trong báo cáo hay tham số: " + ", ".join(bad[:5])
                              + ". Viết lại, chỉ dùng số trong báo cáo.")
        problem = out_of_bounds(params, param, to_value)
        if problem:
            raise ToolRefused(problem)
        value: Any = int(round(to_value)) if isinstance(current, int) else round(to_value, 4)
        proposal = BuProposal(
            id="prop_" + secrets.token_hex(6), report_id=report_id, param=param, from_value=current, to_value=value,
            status="pending", evidence=f"[Agent 5 · mô hình] {why} (căn cứ: mục {ref} của báo cáo). "
                                       "Đề nghị hội đồng rủi ro xem xét.")
        made.append(proposal)
        pending.add(param)
        return {"ok": True, "proposal_id": proposal.id, "param": param, "from": current, "to": value}

    tools = [
        Tool("get_report", "Báo cáo hậu kiểm vừa chạy (kiểm định ngược, thống kê quy tắc, bất đồng A2–A3…).", obj(),
             get_report),
        Tool("get_param", "Giá trị đang chạy của một tham số, vd prudence.thời trang.",
             obj({"path": {"type": "string"}}, ["path"]), get_param),
        Tool("propose_change", "Đề nghị đổi một tham số (chỉ đề nghị, người duyệt).",
             obj({"param": {"type": "string"}, "to_value": {"type": "number"},
                  "evidence_ref": {"type": "string"}, "why": {"type": "string"}},
                 ["param", "to_value", "evidence_ref", "why"]), propose_change),
    ]
    calls: list[dict[str, Any]] = []
    history = [LLMMessage(role="user", text="Hậu kiểm vừa chạy xong. Đọc báo cáo, đề xuất nếu cần, rồi tóm tắt.")]
    try:
        text = llm_tools.tool_loop(prov, AGENT5_SYSTEM, tools, history, calls, max_steps=10) or ""
    except Exception:  # noqa: BLE001 - code report and proposals stand
        return None, [], calls
    allowed: set[float] = set()
    _walk([get_report({}), seen_values, [{"from": p.from_value, "to": p.to_value} for p in made]], allowed)
    summary = text.strip()[:1500] or None
    bad = blocked(summary, allowed) if summary else []
    if bad:
        # §6 "chặn đề xuất, sinh lại": one more draft with the offending numbers named, then drop the prose.
        history += [LLMMessage(role="model", text=summary or ""),
                    LLMMessage(role="user", text="Tóm tắt có số không có trong báo cáo: " + ", ".join(bad[:5])
                                                 + ". Viết lại tóm tắt, chỉ dùng số trong báo cáo hoặc tham số.")]
        try:
            again = (llm_tools.tool_loop(prov, AGENT5_SYSTEM, tools, history, calls, max_steps=3) or "").strip()[:1500]
        except Exception:  # noqa: BLE001
            again = ""
        summary = again if again and not blocked(again, allowed) else None
    return summary, made, calls


def summary_payload(summary: str | None, made: list[BuProposal]) -> dict[str, Any] | None:
    if summary is None and not made:
        return None
    return {"text": summary, "source": "llm", "proposals": [p.id for p in made]}
