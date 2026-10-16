"""Agent 3 · Kiểm soát and the approval gate.

Phase 0: code runs every machine-checkable rule and derives the floor (the
strictest violated code rule). Phase 1: Agent 3 judges without Agent 2's
rationale; its verdict is sealed on the chain before phase 2 may start.
Phase 2: it reads the rationale, may ask Agent 2 once, and may only go lighter
than phase 1 when every resolved concern points to evidence that exists —
never lighter than the floor. The gate (code) then checks five conditions and
trusts no agent. The model's judgment calls (RISK-05, RISK-06, LAW-IP) are
fixed here as deterministic checks.
"""

from __future__ import annotations

import re
import secrets
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.platform.errors import api_error
from app.blockchain import chain
from app.data_sources import consent as consent_mod
from app.platform import events
from app.core import challenger
from app.core import legal
from app.data_sources import sources
from app.core import stress
from app.agents import agent2_advise as advise
from app.agents import llm_tools
from app.agents.llm_tools import Tool, ToolRefused, obj
from app.core.legal import SEVERITY
from app.core.params import active_params
from app.platform.tables import BuApplication, BuUser
from app.api.views import now_iso, store, today

GATE_TEXTS = (
    "Biên bản VERIFIED; mỗi cờ resolved_by_check trỏ tới tool_calls đạt",
    "Không quy tắc hard nào vi phạm; sàn là Đồng ý",
    "Agent 3 approve trùng option_id Agent 2 (smaller: hạn mức gửi ngân hàng là phương án nhỏ hơn)",
    "Hash pha 1 có trên chuỗi và trước hash kết luận cuối",
    "Không có yêu cầu người xem; hạn mức dưới ngưỡng tự động; nhóm duyệt tự động chưa bị tắt",
)
PRE_DECISION = ("draft", "identified", "consented", "needs_answer", "verified", "offered", "selected")
_TARGETS_CONTROL = re.compile(r"agent\s*3|duyệt nhanh|\bvip\b|bỏ qua|ignore|kiểm soát vui lòng", re.I)
_SMALLER_ORDER = ("step70", "step50")


# --- phase 0 -----------------------------------------------------------------------

def payee_type(doc: dict[str, Any]) -> str:
    """AML-LTR-01 threshold class of the borrower's own account: individual when registered as an
    individual business (hộ kinh doanh), else organization. The supplier part is always an organization."""
    registry = (doc.get("internal") or {}).get("data", {}).get("registry") or {}
    return "individual" if registry.get("type", "individual_business") == "individual_business" else "organization"


def _ltr_ok(params: dict[str, Any], doc: dict[str, Any], amount: int) -> bool:
    """Large-transaction lines on each leg of the payout: the part paid into the borrower's account and
    the part above the direct-payment threshold paid to the supplier (loan circle, Stage 5)."""
    split = advise.payee_for(params, doc, amount)
    thr = params["legal"]["ltr_threshold"]
    return split["to_account"] < int(thr[payee_type(doc)]) and split["to_supplier"] < int(thr["organization"])


def evaluate_rules(params: dict[str, Any], app_row: BuApplication, doc: dict[str, Any],
                   option: dict[str, Any], event: dict[str, Any] | None = None,
                   other_loans: int = 0) -> dict[str, dict[str, Any]]:
    """Every enabled rule → {code, ok (True/False/None for judgment), value?}.
    ``event`` is the stress concentration of the plan's event (EVENT-01)."""
    offer, v = doc["offer"], doc["verification"]
    plan = advise._plan_inputs(doc)
    data = doc["internal"]["data"]
    flags = v["flags"]
    full = offer["options"][0]
    group, grade = offer["group"], offer["grade"]
    licenses = doc["stores"][0].get("licenses", [])
    goods = (plan or {}).get("group", "")
    ecig = goods in sources.ECIG_GROUPS
    brand = (plan or {}).get("brand") or ""
    auth = (plan or {}).get("auth") or ""
    supplier_linked = bool(plan) and sources.supplier_info(data, plan["supplier"])["linked"]
    purpose_known = app_row.tier == 1 or bool(plan and plan.get("event") and plan.get("item"))
    identity = (doc.get("identity") or {}).get("result") or {}
    invoice = data["tax"]["invoice_unit_price_3m"]
    dev = round((plan["price"] - invoice) / invoice, 2) if plan and invoice else 0.0
    # LAW-01 "bao phủ mọi nguồn đã dùng": every authorized source Agent 1 read is in the consent.
    scopes = {s["key"] for s in (doc.get("consent") or {}).get("scopes", [])}
    used = {_SOURCE_SCOPE[t["tool"]] for t in v["tool_calls"] if t["tool"] in _SOURCE_SCOPE}
    consent_problem = consent_mod.problem(doc.get("consent"), consent_mod.DATA_SCOPES)
    uncovered = sorted(used - scopes)
    # AML-CDD-01: beneficial owners are verified for a company; an individual business is its owner.
    company = (data.get("registry") or {}).get("type", "individual_business") != "individual_business"

    checks: dict[str, tuple[bool | None, Any]] = {
        "LAW-01": (consent_problem is None and not uncovered,
                   consent_problem or (f"thiếu phạm vi: {', '.join(uncovered)}" if uncovered else None)),
        "LAW-02": (option["rate"] <= params["legal"]["rate_cap"], option["rate"]),
        "LAW-03": (bool(offer["reason_codes"]) or offer["requested"] is None
                   or option["amount"] >= offer["requested"], None),
        "POL-01": (advise.find_option(doc, option["id"]) is not None and option["amount"] <= full["amount"],
                   option["amount"]),
        "POL-02": (group != 4, group),
        "POL-03": (option["amount"] < params["gate"]["auto_limit"], option["amount"]),
        "POL-04": (offer["blocks"]["B9"]["revenue_rate_max_tenor"] <= offer["blocks"]["B5"]["sweep_cap"]
                   and not supplier_linked, offer["blocks"]["B9"]["revenue_rate_max_tenor"]),
        "RISK-01": (not any(f["status"] == "open" for f in flags), None),
        "RISK-02": (not any(f["status"] == "explained_unverified" or f["code"] == "DATA_PARTNER_MISSING"
                            for f in flags), None),
        "RISK-03": (grade != "E", grade),
        "RISK-04": (not dev > params["gate"]["risk04_warn"], dev),
        "RISK-05": (None, None),
        "RISK-06": (None, None),
        "LAW-GOODS-01": (not (ecig and ((plan or {}).get("flavor") not in (None, "", "thuốc lá")
                                        or (plan or {}).get("self_fill"))), None),
        "LAW-GOODS-02": (not ecig, None),
        "LAW-LIC-01": (not (goods in ("thực phẩm rời", "thực phẩm chức năng") and "food" not in licenses), None),
        "LAW-LIC-02": (not (goods == "dược" and "drug" not in licenses), None),
        "LAW-LIC-03": (not (goods == "thiết bị y tế III" and "med3" not in licenses), None),
        "LAW-IP-01": (not (brand and auth == "Không có ủy quyền"), None),
        "LAW-IP-02": (None if (brand and auth == "Chưa rõ") else True, None),
        "AML-CDD-01": (bool(identity.get("entity_match")) and purpose_known
                       and (not company or bool(data["registry"].get("beneficial_owner_verified"))), None),
        # Loan circle: no bank or platform data before the loan, so no transfer pattern to judge here;
        # Agent 4 watches the WeBank business account after disbursement (Stage 6).
        "AML-STR-01": (True, None),
        "AML-LTR-01": (_ltr_ok(params, doc, option["amount"]), option["amount"]),
        "POL-05": (not (plan and option["amount"] > int(params["repay"]["supplier_direct_threshold"])),
                   option["amount"]),
        "POL-07": ((doc.get("borrower_type") != "individual_business"
                    or option["amount"] <= int(params["product"]["type_cap"]["individual_business"]))
                   and other_loans == 0, other_loans),
        "POL-06": (purpose_known, None),
        "EVENT-01": (not (event or {}).get("fires"), (event or {}).get("ratio")),
    }
    out = {}
    for rule in legal.ENABLED_RULES:
        ok, value = checks[rule.code]
        out[rule.code] = {"code": rule.code, "ok": ok, "level": rule.min_verdict, "value": value, "what": rule.what}
    return out


_SOURCE_SCOPE = {"pull_revenue": "data_processing", "pull_tax_data": "data_processing",
                 "get_credit_report": "credit_inquiry", "get_interbank_score": "credit_inquiry"}


def floor_of(results: dict[str, dict[str, Any]]) -> str:
    floor = "approve"
    for code, r in results.items():
        rule = legal.RULES_BY_CODE[code]
        if r["ok"] is False and rule.counts_for_floor and SEVERITY[rule.min_verdict] > SEVERITY[floor]:
            floor = rule.min_verdict
    return floor


def _legal_view(results: dict[str, dict[str, Any]], doc: dict[str, Any], day: date) -> list[dict[str, Any]]:
    plan = advise._plan_inputs(doc) or {}
    actions = {
        "AML-STR-01": "Soạn sẵn báo cáo giao dịch đáng ngờ cho bộ phận tuân thủ; giữ bí mật với người bán",
        "AML-LTR-01": "Ghi nghĩa vụ báo cáo giao dịch lớn trong 5 ngày làm việc vào gói phê duyệt",
        "POL-05": f"Bắt buộc trả nhà cung cấp {plan.get('supplier', '')}".strip(),
    }
    out = []
    for code, r in results.items():
        rule = legal.RULES_BY_CODE[code]
        if not rule.legal:
            continue
        item = {"code": code, "ok": r["ok"], "citations": legal.citations(code, day)}
        if r["ok"] is False and code in actions:
            item["action"] = actions[code]
        out.append(item)
    out.append({"code": "WCLOAN-2024#10", "ok": True,
                "action": "Giao nghĩa vụ kiểm tra việc dùng vốn cho hệ thống cho vay của ngân hàng cấp vốn",
                "citations": [legal.verify_citation("WCLOAN-2024#10", "流动资金贷款禁止挪用", day)]})
    return out


# --- phases 1 and 2 -----------------------------------------------------------------------

def _smaller_of(doc: dict[str, Any], option: dict[str, Any]) -> str | None:
    for oid in _SMALLER_ORDER:
        o = advise.find_option(doc, oid)
        if o and o["amount"] < option["amount"]:
            return oid
    return None


def phase1(session: Session, app_row: BuApplication, doc: dict[str, Any], results: dict[str, dict[str, Any]],
           floor: str, option: dict[str, Any], day: date, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Judge without Agent 2's rationale; seal the verdict on the chain.

    Independence (review item 2): three layers judge here, none of them Agent 2's reasoning: the
    deterministic ruleset (phase 0 floor and code concerns), the challenger model on its own feature
    set (:mod:`app.core.challenger`) and, when configured, a model of another family than Agent 2's."""
    params = params or active_params(session)
    concerns: list[dict[str, Any]] = []
    checked: list[str] = []
    verdict = floor
    notes = doc["internal"]["llm_notes"] or ""
    overruled: list[dict[str, Any]] = []

    def worse(v: str) -> None:
        nonlocal verdict
        if SEVERITY[v] > SEVERITY[verdict]:
            verdict = v

    if results["RISK-04"]["ok"] is False:
        concerns.append({"rule": "RISK-04", "citations": [],
                         "note": f"Giá khai cao hơn hóa đơn {round(results['RISK-04']['value'] * 100)}%; có thể khai "
                                 "cao để vay nhiều hơn mức cần"})
        worse("smaller")
    if _TARGETS_CONTROL.search(notes) or doc["internal"].get("notes_scan"):
        concerns.append({"rule": "RISK-06", "citations": [],
                         "note": "llm_notes chứa lời nhắm vào agent kiểm soát"})
        worse("escalate")
    else:
        checked.append("RISK-06: llm_notes không có lệnh ẩn hay hứa hẹn")
    if results["LAW-IP-01"]["ok"] is False:
        concerns.append({"rule": "LAW-IP-01", "citations": [c for c in legal.citations("LAW-IP-01", day) if c["verified"]],
                         "note": "Hàng có nhãn hiệu, người bán khai không có ủy quyền phân phối của chủ nhãn hiệu"})
        worse("escalate")
    ip02 = results["LAW-IP-02"]["ok"] is None and results["LAW-IP-01"]["ok"] is not False
    for code, r in results.items():
        rule = legal.RULES_BY_CODE[code]
        if r["ok"] is False and rule.counts_for_floor and SEVERITY[rule.min_verdict] >= SEVERITY["smaller"] \
                and not any(c["rule"] == code for c in concerns):
            concerns.append({"rule": code, "note": rule.what, "citations": legal.citations(code, day)})
    ch = challenger.score(challenger.features(doc))
    ch_verdict = challenger.verdict(params, ch["pd"])
    if ch_verdict != "approve":
        concerns.append({"rule": "CHAL-01", "citations": [], "source": "challenger", "level": ch_verdict,
                         "note": f"Mô hình thách thức (bộ đặc trưng riêng) ước xác suất vỡ nợ {round(ch['pd'] * 100, 1)}%"})
        worse(ch_verdict)
    plan = advise._plan_inputs(doc)
    judgment, llm_calls, failure = _llm_judgment(session, app_row, doc, results, floor, option, day)
    if failure:
        # §6: the model failed in phase 1 → no automated verdict; an officer reviews.
        concerns.append({"rule": "AGENT3", "citations": [], "note": "Mô hình lỗi ở pha 1; chuyển cán bộ thẩm định"})
        events.log(session, app_row.id, "agent3", "llm_failed", "Mô hình pha 1 lỗi: chuyển cán bộ",
                   {"error": failure, "hidden_from_seller": True})
        worse("escalate")
    if ip02:
        # LAW-IP-02 does not move the floor; Agent 3 judges it (§3.5). Without a model nobody judged it,
        # so the case goes to an officer; with one, only a verified concern makes it stricter.
        concerns.append({"rule": "LAW-IP-02", "level": "warn",
                         "citations": [c for c in legal.citations("LAW-IP-02", day) if c["verified"]],
                         "note": "Hàng có nhãn hiệu, chưa rõ có ủy quyền phân phối; cần đánh giá giá nhập và nhà cung cấp"})
        if judgment is None:
            concerns[-1]["level"] = "escalate"
            worse("escalate")
    if judgment is not None:
        for c in judgment.concerns:
            if c.rule not in llm_tools.JUDGMENT_RULES or any(x["rule"] == c.rule and x.get("level") != "warn"
                                                             for x in concerns):
                continue
            why_not = _unsupported_concern(c, results, notes)
            if why_not:
                events.log(session, app_row.id, "agent3", "llm_concern_overruled",
                           f"{c.rule} của mô hình bị bỏ: {why_not}",
                           {"rule": c.rule, "note": c.note, "hidden_from_seller": True})
                overruled.append({"rule": c.rule, "note": c.note, "why": why_not})
                continue
            checks = [legal.verify_citation(x.article_id, x.quote, day) for x in c.citations]
            bad = [x for x in checks if not (x["verified"] and x["effective"])]
            for x in bad:
                events.log(session, app_row.id, "agent3", "citation_rejected",
                           f"Trích dẫn {x['article_id']} bị loại: {x['note']}",
                           {"rule": c.rule, "article_id": x["article_id"], "hidden_from_seller": True})
            if bad:
                continue
            level = _JUDGMENT_SEVERITY[c.rule]
            concerns.append({"rule": c.rule, "note": c.note, "citations": checks, "source": "llm", "level": level})
            if level != "warn":
                worse(level)
        # The model's bare verdict is recorded, never applied: only a concern code can check moves it
        # (team decision kept, see AGENT3_FIXES.md; §5 "chuyển cán bộ bất cứ lúc nào" is open).
        checked += [f"(mô hình) {t}"[:300] for t in judgment.checked_ok[:5]]
    if plan and not any(c["rule"] == "RISK-05" for c in concerns) and judgment is None:
        checked.append(f"RISK-05: chưa đánh giá bằng mô hình (chạy đường code); {plan['item'].lower()} cho "
                       f"{plan['event']} ghi nhận để cán bộ xem")
    option_id: str | None = option["id"] if verdict == "approve" else None
    if verdict == "smaller":
        # The level Agent 3 accepts. None: no smaller option exists; phase 2 settles it (arbitration).
        option_id = _smaller_of(doc, option)
    p1 = {"phase": 1, "verdict": verdict, "option_id": option_id, "concerns": concerns, "checked_ok": checked,
          "judgment_source": "llm" if judgment is not None else ("llm_failed" if failure else "code"),
          "challenger": {**ch, "verdict": ch_verdict, "features": challenger.features(doc)},
          "independence": llm_tools.model_independence()}
    if overruled:
        p1["llm_overruled"] = overruled
    if judgment is not None:
        p1["llm_verdict"] = judgment.verdict
        # Outputs are fingerprinted (not copied) so the seal proves what the model saw without bloating it.
        p1["llm_tool_calls"] = [{**{k: c[k] for k in ("id", "tool", "input")}, "output_hash": _digest(c.get("output"))}
                                for c in llm_calls]
    entry = chain.record(session, app_row.id, "agent3_phase1_seal", p1)
    p1["seal"] = {"hash": entry.fingerprint, "chain_tx": entry.tx, "seq": entry.seq, "at": now_iso()}
    events.log(session, app_row.id, "agent3", "phase1_seal", f"Pha 1: {verdict}, niêm phong trên chuỗi",
               {"verdict": verdict, "hidden_from_seller": True}, hash_=entry.fingerprint)
    return p1


# RISK-05 is "cảnh báo" in agent3 §3.1: recorded for the officer, never moves the verdict.
_JUDGMENT_SEVERITY = {"RISK-05": "warn", "RISK-06": "escalate", "LAW-IP-02": "escalate"}
_PROMISE = re.compile(r"chắc chắn|cam kết|hứa|đảm bảo|bảo đảm|100\s*%|không bao giờ trễ|tuyệt đối", re.I)
_QUOTED = re.compile(r"[\"'“‘「]([^\"'”’」]{6,})[\"'”’」]")


def _unsupported_concern(c: llm_tools.Concern, results: dict[str, dict[str, Any]], notes: str) -> str | None:
    """A model concern may only make the verdict stricter when code can check its reference
    (agent3 §3: RISK-06 is "mô hình + code kiểm tham chiếu"). Returns why it is dropped, else None."""
    if c.rule == "RISK-06":
        quoted = [q.strip().lower() for q in _QUOTED.findall(c.note) if q.strip().lower() in notes.lower()]
        if not quoted:
            return "không trích được câu nào có thật trong ghi chú"
        # The quote must itself be a hidden instruction (the code scan catches it) or a promise;
        # a factual sentence about a resolved flag is not RISK-06.
        if not any(llm_tools.scan_injection(q) or _PROMISE.search(q) for q in quoted):
            return "câu trích không chứa lệnh ẩn hay lời hứa"
    if c.rule == "LAW-IP-02" and results.get("LAW-IP-02", {}).get("ok") is True:
        return "code đã kiểm nhãn hiệu và ủy quyền đạt"
    return None


def _llm_judgment(session: Session, app_row: BuApplication, doc: dict[str, Any],
                  results: dict[str, dict[str, Any]], floor: str, option: dict[str, Any],
                  day: date) -> tuple[llm_tools.Judgment | None, list[dict[str, Any]], str | None]:
    """Model phase 1 for the judgment rules. It sees the case bundle, never the chat nor
    Agent 2's rationale; it can only add concerns (the floor and phase 2 stay code)."""
    offer, v = doc["offer"], doc["verification"]
    bundle = {
        "application": app_row.code, "tier": app_row.tier, "plan": advise._plan_inputs(doc),
        "store": {k: doc["stores"][0].get(k) for k in ("platform", "category", "rating", "licenses")},
        "verification": {"state": v["state"], "derived": v["derived"],
                         "flags": [{k: f.get(k) for k in ("code", "status", "note")} for f in v["flags"]]},
        # Every option, not which one Agent 2 proposed: phase 1 judges before seeing the proposal.
        "offer": {"grade": offer["grade"], "group": offer["group"], "options": offer.get("options") or [],
                  "blocks": offer["blocks"]},
        "phase0": {"floor": floor, "results": [{k: r[k] for k in ("code", "ok", "level")} for r in results.values()]},
        "llm_notes": doc["internal"].get("llm_notes", ""),
    }

    def get_rule(args: dict[str, Any]) -> dict[str, Any]:
        rule = legal.RULES_BY_CODE.get(str(args.get("code") or ""))
        if rule is None:
            raise ToolRefused("Không có quy tắc này")
        return {"code": rule.code, "what": rule.what, "how": rule.how, "min_verdict": rule.min_verdict,
                "cite": [list(c) for c in rule.cite]}

    def get_evidence(args: dict[str, Any]) -> dict[str, Any]:
        ref = str(args.get("ref") or "")
        if not advise.ref_exists(doc, ref):
            raise ToolRefused("evidence_ref không tồn tại")
        if ref.startswith("tool_calls."):
            return next(t for t in v["tool_calls"] if t["id"] == ref[11:])
        if ref.startswith("sheet.options."):
            return advise.find_option(doc, ref[14:]) or {}
        _, block, key = ref.split(".")
        return {"ref": ref, "value": offer["blocks"][block][key]}

    def get_bank_policies(_: dict[str, Any]) -> dict[str, Any]:
        from app.banks.split import catalog

        keep = ("summary", "risk_appetite", "red_flags", "escalate_when", "deal_breakers", "use_of_funds",
                "version", "hash")
        return {"items": [{"bank": b.code, "name": b.name, **{k: (b.policy.get("chain") or {}).get(k) for k in keep}}
                          for b in catalog(session, doc["region"]) if (b.policy or {}).get("chain")]}

    tools = [
        Tool("get_case_bundle", "Toàn bộ hồ sơ cần kiểm soát (không có tin nhắn, không có lập luận Agent 2).",
             obj(), lambda _: bundle),
        Tool("get_bank_policies", "Chính sách tín dụng viết của các ngân hàng cùng khu vực (từ chuỗi BuoyUp).",
             obj(), get_bank_policies),
        Tool("get_rule", f"Nội dung một quy tắc của bộ {legal.RULESET_VERSION}.", obj({"code": {"type": "string"}}, ["code"]),
             get_rule),
        Tool("get_evidence", "Giá trị của một evidence_ref (tool_calls.TC-…, sheet.B3.unit_price_used, …).",
             obj({"ref": {"type": "string"}}, ["ref"]), get_evidence),
        Tool("search_articles", "Tìm điều luật trong kho luật Trung Quốc (RAG: hỏi bằng tiếng Việt, Anh hoặc Trung; "
             "law_ids lọc văn bản, ví dụ PQL-2018, TM-2019). Trích dẫn vẫn phải qua verify_citation.",
             obj({"query": {"type": "string"}, "law_ids": {"type": "array", "items": {"type": "string"}}}, ["query"]),
             lambda a: {"items": [{k: h[k] for k in ("article_id", "law", "snippet", "score", "in_force")}
                                  for h in rag_search(str(a.get("query") or ""),
                                                      [str(x) for x in (a.get("law_ids") or [])][:10], day)]}),
        Tool("verify_citation", "Kiểm một trích dẫn: có nguyên văn trong điều và còn hiệu lực ở ngày xét không.",
             obj({"article_id": {"type": "string"}, "quote": {"type": "string"}}, ["article_id", "quote"]),
             lambda a: legal.verify_citation(str(a.get("article_id") or ""), str(a.get("quote") or ""), day)),
    ]
    calls: list[dict[str, Any]] = []
    failure = None
    try:
        judgment = llm_tools.judge(bundle, tools, calls)
    except llm_tools.JudgeFailed as exc:
        judgment, failure = None, str(exc)
    for call in calls:
        events.log(session, app_row.id, "agent3", "llm_tool_call", f"{call['id']} · {call['tool']}",
                   {"tool_call": {k: call[k] for k in ("id", "tool", "input")}, "hidden_from_seller": True})
    return judgment, calls, failure


# Concerns Agent 2 can answer with evidence, and the references that answer them.
RESOLVERS: dict[str, list[str]] = {"RISK-04": ["sheet.B3.unit_price_used", "sheet.B8.binding_cap"]}
_QUESTIONS = {"RISK-04": "Giá khai lệch hóa đơn có ảnh hưởng tới số tiền đề xuất không? Trả lời kèm evidence_ref."}


def _digest(value: Any) -> str:
    import hashlib
    import json

    return "sha256:" + hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
                                      .encode()).hexdigest()


def phase2(session: Session, app_row: BuApplication, doc: dict[str, Any], p1: dict[str, Any], floor: str,
           option: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Arbitration (review item 1). Agent 3 asks, Agent 2 answers with evidence references, at most
    ``arbitration.max_rounds`` rounds; every round is a ``debate_round`` chain entry (the audit file of the
    decision). Past the cap the more cautious conclusion stands (phase 1, never lighter than the floor).
    A remaining disagreement takes the level Agent 3 accepts; with no such level, the case is rejected
    (``arbitration.on_no_acceptable``)."""
    if not p1.get("seal"):
        raise RuntimeError("phase 2 requires the phase 1 seal")
    params = params or active_params(session)
    max_rounds = max(1, int(params["arbitration"]["max_rounds"]))
    rationale = doc["proposal"]["rationale"]
    cited = {r["evidence_ref"] for r in rationale if advise.ref_exists(doc, r["evidence_ref"])}
    resolved, unresolved = [], []
    asked, ask = False, None
    rounds: list[dict[str, Any]] = []
    # RISK-06 also covers the rationale (§3.1): a claim that steers the reviewer or promises.
    steering = [r["claim"] for r in rationale if llm_tools.scan_injection(r.get("claim") or "")
                or _PROMISE.search(r.get("claim") or "")]
    if steering:
        unresolved.append({"rule": "RISK-06", "citations": [], "note": "Lập luận Agent 2 có lời nhắm vào kiểm soát "
                                                                     "hoặc lời hứa: " + steering[0][:120]})
    pending: list[dict[str, Any]] = []
    for c in p1["concerns"]:
        if c.get("level") == "warn":  # model warnings never moved phase 1, so they cannot hold it
            continue
        if c["rule"] not in RESOLVERS:
            unresolved.append(c)  # code facts and the challenger's score are not answered away by argument
            continue
        if all(n in cited for n in RESOLVERS[c["rule"]]):
            resolved.append(_resolution(doc, c["rule"]))  # the rationale already cites the evidence
        else:
            pending.append(c)
    previous: dict[str, list[str]] = {}
    for k in range(1, max_rounds + 1):
        if not pending:
            break
        asks = []
        for c in list(pending):
            need = RESOLVERS[c["rule"]]
            question = _QUESTIONS[c["rule"]] if k == 1 else (
                f"Vòng {k}: còn thiếu bằng chứng {', '.join(n for n in need if n not in previous.get(c['rule'], []))}.")
            answer = advise.answer_challenge(doc, option, c["rule"], question, need)
            refs = [n for n in need if (n in answer["evidence_refs"] or n in cited) and advise.ref_exists(doc, n)]
            valid = len(refs) == len(need)
            item = {"rule": c["rule"], "fields": sorted({".".join(n.split(".")[:2]) for n in need}),
                    "question": question, "answer": {"evidence_refs": refs, "claim": answer.get("claim"),
                                                     "source": answer["source"]}, "valid": valid}
            asks.append(item)
            if ask is None:
                ask = item
            if valid:
                resolved.append(_resolution(doc, c["rule"]))
                pending.remove(c)
        asked = True
        entry = chain.record(session, app_row.id, "debate_round",
                             {"round": k, "max_rounds": max_rounds, "asks": asks,
                              "agent2": asks[0]["answer"]["source"] if asks else None,
                              "independence": p1.get("independence")})
        rounds.append({"round": k, "asks": asks, "chain_tx": entry.tx, "hash": entry.fingerprint})
        events.log(session, app_row.id, "agent3", "debate_round", f"Vòng {k}/{max_rounds}: "
                   f"{sum(a['valid'] for a in asks)}/{len(asks)} băn khoăn được trả lời bằng bằng chứng",
                   {"round": k, "hidden_from_seller": True}, hash_=entry.fingerprint)
        progress = {a["rule"]: a["answer"]["evidence_refs"] for a in asks}
        if all(a["answer"]["source"] == "code" for a in asks) or progress == previous:
            break  # Agent 2 (code) gives the same answer every round: another round adds nothing
        previous = progress
    cap_reached = bool(pending)
    unresolved += pending
    verdict = p1["verdict"] if unresolved else "approve"
    if steering and SEVERITY["escalate"] > SEVERITY[verdict]:
        verdict = "escalate"
    if SEVERITY[verdict] < SEVERITY[floor]:
        verdict = floor
    lighter = SEVERITY[verdict] < SEVERITY[p1["verdict"]]
    valid = not lighter or all(advise.ref_exists(doc, ref) for r in resolved for ref in r["by"])
    if not valid:
        verdict = p1["verdict"]
    option_id = option["id"] if verdict == "approve" else (p1["option_id"] if verdict == "smaller" else None)
    no_level = verdict == "smaller" and option_id is None
    if no_level:
        # Disagreement and no smaller option Agent 3 accepts: rejection by default (or an officer).
        verdict = "reject" if params["arbitration"]["on_no_acceptable"] == "reject" else "escalate"
    p2: dict[str, Any] = {"phase": 2, "verdict": verdict, "option_id": option_id, "resolved": resolved,
                          "asked_agent2": asked, "rounds": rounds, "max_rounds": max_rounds,
                          "cap_reached": cap_reached, "no_acceptable_level": no_level}
    if ask:
        p2["ask"] = ask
    p2["change_rule"] = ("nhẹ hơn pha 1, mọi băn khoăn gỡ có evidence_ref tồn tại: hợp lệ" if lighter and valid
                         else "giữ kết luận pha 1" if verdict == p1["verdict"] else "nghiêm hơn pha 1")
    entry = chain.record(session, app_row.id, "agent3_conclusion", p2)
    p2.update(final_hash=entry.fingerprint, chain_tx=entry.tx, seq=entry.seq)
    events.log(session, app_row.id, "agent3", "conclusion", f"Pha 2: {verdict}",
               {"verdict": verdict, "hidden_from_seller": True}, hash_=entry.fingerprint)
    return p2


def _resolution(doc: dict[str, Any], rule: str) -> dict[str, Any]:
    b3 = doc["offer"]["blocks"].get("B3") or {}
    return {"rule": rule, "by": RESOLVERS[rule],
            "note": f"Số tiền tính theo giá hóa đơn {b3.get('unit_price_used')}; giá khai không ảnh hưởng số tiền"}


def review(session: Session, app_row: BuApplication, doc: dict[str, Any], params: dict[str, Any]) -> None:
    """After the seller accepts: phases 0–2, bank policies, gate. Approve calls Agent 4."""
    app_row.status = "in_control"
    day = today()
    option = advise.find_option(doc, doc["proposal"]["option_id"])
    proposal_entry = chain.record(session, app_row.id, "proposal", doc["proposal"])
    doc["proposal"]["hash"] = proposal_entry.fingerprint
    plan = advise._plan_inputs(doc)
    event = stress.event_concentration(session, params, plan["event"]) if plan and plan.get("event") else None
    from sqlalchemy import func, select

    from app.platform.tables import BuLoan

    other_loans = session.scalar(select(func.count()).select_from(BuLoan).where(
        BuLoan.seller_user_id == app_row.seller_user_id, BuLoan.status.in_(("active", "overdue")))) or 0
    results = evaluate_rules(params, app_row, doc, option, event, int(other_loans))
    floor = floor_of(results)
    phase0 = {"ruleset_version": legal.RULESET_VERSION, "ruleset_hash": legal.RULESET_HASH,
              "results": list(results.values()), "floor": floor,
              "disabled_rules": legal.DISABLED_RULES, "event": event}
    events.log(session, app_row.id, "agent3", "phase0", f"Pha 0: sàn {floor}",
               {"floor": floor, "hidden_from_seller": True})
    if results["AML-STR-01"]["ok"] is False:
        events.log(session, app_row.id, "agent3", "aml_str_draft",
                   "Soạn sẵn báo cáo giao dịch đáng ngờ cho bộ phận tuân thủ", {"hidden_from_seller": True})
    p1 = phase1(session, app_row, doc, results, floor, option, day, params)
    p2 = phase2(session, app_row, doc, p1, floor, option, params)
    doc["control"] = {"phase0": phase0, "phase1": p1, "phase2": p2, "legal": _legal_view(results, doc, day),
                      "bank_policies": [], "gate": None, "results": results,
                      "retrieval": _retrieval(doc, results, option, day)}
    gate(session, app_row, doc, params, accepted=None)


def _retrieval(doc: dict[str, Any], results: dict[str, Any], option: dict[str, Any], day: date) -> dict[str, Any] | None:
    """RAG over the Chinese law corpus for this case (shown to staff; decisions stay with the rules)."""
    from app.core import rag

    try:
        return rag.retrieve_for_case(doc, results, amount=int(option.get("amount") or 0), as_of=day)
    except Exception as exc:  # noqa: BLE001 - retrieval is evidence, never a reason to stop a review
        return {"mode": "error", "error": f"{type(exc).__name__}: {exc}"[:200], "queries": [], "rule_checks": []}


# --- gate --------------------------------------------------------------------------------

def rag_search(query: str, law_ids: list[str], day: date) -> list[dict[str, Any]]:
    from app.core import rag

    return rag.search(query, k=8, law_ids=law_ids or None, as_of=day)


def gate(session: Session, app_row: BuApplication, doc: dict[str, Any], params: dict[str, Any],
         accepted: str | None) -> None:
    from app.agents.agent4b_monitor import auto_approval_enabled, category_of, group_key

    c = doc["control"]
    p1, p2, results, floor = c["phase1"], c["phase2"], c["results"], c["phase0"]["floor"]
    proposal_id = doc["proposal"]["option_id"]
    v = doc["verification"]
    tools_by_id = {t["id"]: t for t in v["tool_calls"]}
    # Condition 1: every flag closed by a check points to a tool call that exists and did not fail;
    # a flag an officer confirmed (resolved_by "officer") is a human check.
    flags_ok = all(f.get("resolved_by") == "officer"
                   or (f.get("evidence_tool_call") in tools_by_id
                       and "error" not in (tools_by_id[f["evidence_tool_call"]].get("output") or {}))
                   for f in v["flags"] if f["status"] == "resolved_by_check")
    hard_bad = any(r["ok"] is False and legal.RULES_BY_CODE[code].min_verdict == "reject"
                   for code, r in results.items())
    target_id = accepted or p2["option_id"]
    target = advise.find_option(doc, target_id) if target_id else None
    agreed = ((p2["verdict"] == "approve" and p2["option_id"] == proposal_id)
              or (p2["verdict"] == "smaller" and accepted == p2["option_id"]))
    waiting = p2["verdict"] == "smaller" and accepted is None
    group = group_key(category_of(doc), app_row.tier)
    switch_on = auto_approval_enabled(session, params, group)
    conditions = [
        v["state"] == "VERIFIED" and flags_ok,
        not hard_bad and floor == "approve",
        agreed,
        _seal_on_chain(session, app_row, p1["seal"], p2),
        not doc.get("human_request") and (target is None or target["amount"] < params["gate"]["auto_limit"])
        and switch_on,
    ]
    if all(conditions):
        kind = "approve"
    elif waiting and all(ok for i, ok in enumerate(conditions) if i != 2):
        # Loan circle: the borrower picks an amount within the approved limit anyway, so Agent 3's
        # "smaller" becomes the limit sent to the banks (no separate acceptance step).
        kind = "approve_smaller"
    else:
        worst = p2["verdict"] if SEVERITY[p2["verdict"]] >= SEVERITY[floor] else floor
        kind = "reject" if worst == "reject" else "escalate"
        if doc.get("human_request") and kind != "reject":
            kind = "escalate"
    why = None
    if (kind == "escalate" and not switch_on and floor == "approve" and p2["verdict"] in ("approve", "smaller")
            and not doc.get("human_request")):
        why = "AUTO_APPROVAL_OFF"
    c["gate"] = {"conditions": [{"text": t, "ok": ok} for t, ok in zip(GATE_TEXTS, conditions)],
                 "decision": kind, "auto_group": group, "auto_enabled": switch_on}
    events.log(session, app_row.id, "gate", "gate", f"Cổng: {kind}",
               {"conditions": conditions, "auto_group": group, "hidden_from_seller": True})
    if kind in ("approve", "approve_smaller"):
        approve(session, app_row, doc, target, by="gate", reason=_smaller_reason(doc) if kind == "approve_smaller" else None)
    else:
        why = why or escalation_why(doc)
        _decide(doc, kind, None, "gate", seller_reason(doc, kind, why))
        # Review item 1: an escalation or a rejection is a decision too; it goes on the chain.
        entry = chain.record(session, app_row.id, "gate_decision",
                             {"application": app_row.code, "decision": doc["decision"], "why": why, "by": "gate",
                              "conditions": conditions, "agent3": {"verdict": p2["verdict"], "rounds": len(p2.get("rounds") or []),
                                                                   "cap_reached": p2.get("cap_reached", False)}})
        doc["decision"]["chain_tx"] = entry.tx
        if kind == "escalate":
            doc["escalation"] = {"why": why, "at": now_iso()}
        store(app_row, doc, "escalated" if kind == "escalate" else "rejected")


def _seal_on_chain(session: Session, app_row: BuApplication, seal: dict[str, Any], p2: dict[str, Any]) -> bool:
    """Condition 4: the phase-1 seal is an entry of this case's chain with the stored hash,
    earlier than the final conclusion; in remote mode its anchor reached the chain service."""
    from sqlalchemy import select

    from app.platform.tables import BuChainEntry, BuChainOutbox

    entry = session.get(BuChainEntry, seal.get("seq"))
    if entry is None or entry.case_id != app_row.id or entry.kind != "agent3_phase1_seal" \
            or entry.fingerprint != seal.get("hash") or not seal["seq"] < p2["seq"]:
        return False
    if chain.mode() == "remote":
        row = session.scalar(select(BuChainOutbox).where(BuChainOutbox.entry_seq == entry.seq).limit(1))
        return row is not None and row.status == "sent"
    return True


def _decide(doc: dict[str, Any], kind: str, option: dict[str, Any] | None, by: str,
            reason: dict[str, str] | None, officer_id: str | None = None) -> None:
    doc["decision"] = {"kind": kind, "option_id": option["id"] if option else None,
                       "amount": option["amount"] if option else None, "by": by, "reason": reason, "at": now_iso()}
    if officer_id:  # a complaint about this decision goes to another officer (review item 4)
        doc["decision"]["officer_id"] = officer_id


def approve(session: Session, app_row: BuApplication, doc: dict[str, Any], option: dict[str, Any], by: str,
            officer: BuUser | None = None, reason: dict[str, str] | None = None) -> None:
    """The limit is approved by the decision core, Agent 3 and the gate (or an officer): record the
    decision on the chain, then the orchestrator sends the case to the partner banks in parallel
    (loan circle, Stage 2). The banks confirm the limit (valid 7 days) or nobody takes it."""
    from app.banks import syndicate

    params = active_params(session)
    _decide(doc, "approve", option, by, reason, officer.id if officer else None)
    payload = {"application": app_row.code, "decision": doc["decision"], "limit": option["amount"],
               "rate": option["rate"], "tenors": doc["offer"]["tenors"], "by": by,
               "officer": officer.id if officer else None}
    entry = chain.record(session, app_row.id, "gate_decision", payload)
    doc["decision"]["chain_tx"] = entry.tx
    events.log(session, app_row.id, "gate" if by == "gate" else "officer", "approve",
               f"Duyệt hạn mức {option['amount']} ({option['id']}); gửi các ngân hàng hợp tác", hash_=entry.fingerprint)
    result = syndicate.run(session, app_row, doc, params, int(option["amount"]))
    doc["syndicate"] = result
    if result["status"] != "approved":
        _decide(doc, "reject", None, "orchestrator", dict(_ESCALATE_REASONS["NO_PARTNER"]))
        store(app_row, doc, "rejected")
        return
    limit = int(result["limit"])
    offer = doc["offer"]
    offer["limit"] = limit
    offer["suggested"] = min(limit, offer.get("suggested") or limit)
    offer["slider"] = {"min": min(params["product"]["min_amount"], limit), "max": limit, "step": 100}
    offer["expires_at"] = result["expires_at"]
    tenors = [t for t in offer["tenors"] if t <= int(result.get("tenor_cap") or 999)] or offer["tenors"][:1]
    offer["tenors"], offer["tenor_max"] = tenors, max(tenors)
    offer["banks"] = result["split"]
    offer["card"] = advise.offer_card(params, doc)
    doc["payee"] = offer["card"]["payee_split"]
    doc["decision"]["amount"] = limit
    advise._post(session, app_row.id, "agent2",
                 advise.template_explanation(offer) + " Các ngân hàng đã duyệt song song: "
                 + ", ".join(f"{s['name']} {round(s['pct'] * 100)}%" for s in result["split"])
                 + ". Hạn mức có hiệu lực 7 ngày; chị chọn số tiền, kỳ hạn, hình thức và ngày trả.",
                 card=offer["card"])
    store(app_row, doc, "offered")


# --- seller-facing reasons (LAW-03; AML kept secret) ------------------------------------------

def hidden_reason(doc: dict[str, Any]) -> bool:
    c = doc.get("control") or {}
    results = c.get("results") or {}
    aml = (results.get("AML-STR-01") or {}).get("ok") is False
    injected = any(x["rule"] == "RISK-06" for x in (c.get("phase1") or {}).get("concerns", []))
    return aml or injected


def escalation_why(doc: dict[str, Any]) -> str:
    c = doc.get("control") or {}
    results = c.get("results") or {}
    settled = {r["rule"] for r in (c.get("phase2") or {}).get("resolved", [])}
    concerns = [x["rule"] for x in (c.get("phase1") or {}).get("concerns", []) if x["rule"] not in settled]
    if (c.get("phase2") or {}).get("no_acceptable_level"):
        return "NO_ACCEPTABLE_LEVEL"
    if (results.get("AML-STR-01") or {}).get("ok") is False:
        return "AML-STR-01"
    if "RISK-06" in concerns:
        return "RISK-06"
    for code, r in results.items():
        rule = legal.RULES_BY_CODE[code]
        if r["ok"] is False and rule.counts_for_floor and SEVERITY[rule.min_verdict] >= SEVERITY["escalate"]:
            return "EVENT_CONCENTRATION" if code == "EVENT-01" else code
    for code in concerns:
        if code.startswith("LAW-IP"):
            return code
    if doc.get("human_request"):
        return "HUMAN_REQUEST"
    if (results.get("RISK-02") or {}).get("ok") is False:
        return "RISK-02"
    return concerns[0] if concerns else "AGENT3"


_ESCALATE_REASONS = {
    "POL-03": {"law": "Quy trình phê duyệt của BuoyUp: khoản lớn do cán bộ tín dụng duyệt",
               "factor": "Số tiền đề xuất cần cán bộ duyệt thay vì duyệt tự động.",
               "fix": "Chị không cần làm gì thêm; hoặc chọn mức thấp hơn trên thanh trượt."},
    "RISK-01": {"law": "Quy tắc kiểm soát rủi ro RISK-01", "factor": "Còn thông tin xác minh chưa được trả lời.",
                "fix": "Trả lời câu hỏi xác minh còn lại; cán bộ sẽ liên hệ chị."},
    "RISK-02": {"law": "Quy tắc kiểm soát rủi ro RISK-02",
                "factor": "Một số thông tin chị giải thích chưa kiểm được bằng công cụ.",
                "fix": "Cán bộ sẽ liên hệ để xác nhận; chị có thể bổ sung ảnh doanh thu hoặc chứng từ."},
    "HUMAN_REQUEST": {"law": "Luật Bảo vệ thông tin cá nhân, Điều 24 (quyền yêu cầu con người xem xét)",
                      "factor": "Chị đã yêu cầu cán bộ xem hồ sơ.", "fix": "Cán bộ sẽ liên hệ chị; chị không cần làm gì thêm."},
    "NO_PARTNER": {"law": "Quy trình duyệt song song của các ngân hàng hợp tác",
                   "factor": "Chưa ngân hàng đối tác nào đồng ý cấp vốn, kể cả ở hạn mức thấp hơn; WeBank không cho "
                             "vay một mình.",
                   "fix": "Chị có thể nộp lại sau, khi doanh thu hoặc lịch sử tín dụng tốt hơn."},
    "NO_ELIGIBLE_BANK": {"law": "Chính sách tín dụng của các ngân hàng đối tác (khối B12)",
                         "factor": "Chưa có ngân hàng đối tác nào nhận được hồ sơ ở mức này.",
                         "fix": "Cán bộ sẽ tìm phương án cấp vốn; chị có thể chọn mức thấp hơn."},
    "AML-CDD-01": {"law": "Luật Chống rửa tiền 2024, Điều 29 (thẩm định khách hàng)",
                   "factor": "Cần xác minh thêm danh tính, chủ sở hữu hưởng lợi hoặc mục đích vay.",
                   "fix": "Cán bộ sẽ liên hệ để bổ sung thông tin."},
    "EVENT_CONCENTRATION": {"law": "Quy trình quản trị rủi ro danh mục của BuoyUp",
                            "factor": "Hồ sơ vay cho cùng sự kiện bán hàng cần cán bộ tín dụng xem thêm.",
                            "fix": "Chị không cần làm gì thêm; cán bộ sẽ liên hệ chị."},
    "AUTO_APPROVAL_OFF": {"law": "Quy trình phê duyệt của BuoyUp: duyệt tự động tạm dừng cho nhóm hồ sơ này",
                          "factor": "Hồ sơ của chị cần cán bộ tín dụng duyệt thay vì duyệt tự động.",
                          "fix": "Chị không cần làm gì thêm; cán bộ sẽ liên hệ chị."},
    "BANK_DECLINED": {"law": "Chính sách tín dụng của các ngân hàng đối tác (khối B12)",
                      "factor": "Ngân hàng cấp vốn chưa ký duyệt phần của mình.",
                      "fix": "Cán bộ sẽ tìm phương án cấp vốn khác; chị không cần làm gì thêm."},
    "NO_ACCEPTABLE_LEVEL": {"law": "Quy tắc phân xử của BuoyUp: không đồng thuận thì lấy kết luận thận trọng hơn",
                            "factor": "Kiểm soát độc lập không chấp nhận được mức hạn mức nào cho hồ sơ này.",
                            "fix": "Chị có thể khiếu nại để cán bộ xem lại, hoặc nộp lại khi doanh thu hay chứng từ "
                                   "đầy đủ hơn."},
    "CHAL-01": {"law": "Quy tắc kiểm soát rủi ro của BuoyUp (mô hình thách thức độc lập)",
                "factor": "Một số tín hiệu của kế hoạch và chứng từ cần cán bộ tín dụng xem thêm.",
                "fix": "Cán bộ sẽ liên hệ chị; chị có thể bổ sung hóa đơn mua vào hoặc ảnh doanh thu."},
    "POL-06": {"law": "Quy định cho vay vốn lưu động, Điều 9 (mục đích vay rõ ràng, hợp pháp)",
               "factor": "Mục đích vay trong kế hoạch chưa rõ hoặc chưa khớp mặt hàng.",
               "fix": "Ghi rõ sự kiện và mặt hàng trong biểu mẫu kế hoạch."},
}


def seller_reason(doc: dict[str, Any], kind: str, why: str) -> dict[str, str] | None:
    if hidden_reason(doc):
        return None
    results = (doc.get("control") or {}).get("results") or {}
    plan = advise._plan_inputs(doc) or {}

    def bad(code: str) -> bool:
        return (results.get(code) or {}).get("ok") is False

    if bad("POL-07"):
        return {"law": "Chính sách sản phẩm: mỗi người vay một khoản vay tại một thời điểm; hộ kinh doanh tối đa "
                       "200.000 tệ",
                "factor": "Chị đang có một khoản vay chưa tất toán qua BuoyUp.",
                "fix": "Tất toán khoản đang có (trả trước không mất phí) rồi nộp lại."}
    if bad("POL-02"):
        return {"law": "Chính sách sản phẩm: nhóm khách hàng 4 không được cấp hạn mức",
                "factor": "Báo cáo tín dụng hoặc lịch sử với BuoyUp có khoản trễ hạn từ 30 ngày, vỡ nợ hoặc nợ xấu.",
                "fix": "Trả dứt điểm các khoản quá hạn; hồ sơ được xét lại khi lịch sử tín dụng cải thiện."}
    if bad("LAW-GOODS-02"):
        return {"law": "Quy định quản lý thuốc lá điện tử, Điều 23" + (" và Điều 26" if bad("LAW-GOODS-01") else ""),
                "factor": "Thuốc lá điện tử không được bán qua sàn thương mại điện tử, nên không thể tài trợ kế hoạch "
                          "nhập mặt hàng này.",
                "fix": "Lập kế hoạch vay cho mặt hàng được phép bán trên sàn."}
    if bad("LAW-LIC-02"):
        return {"law": "Danh sách tiêu cực tiếp cận thị trường 2025, mục bán thuốc qua mạng",
                "factor": "Bán dược phẩm qua mạng cần tư cách kinh doanh dược.",
                "fix": "Bổ sung tư cách kinh doanh dược hoặc đổi mặt hàng."}
    if bad("LAW-LIC-01"):
        return {"law": "Danh sách tiêu cực 2025 (giấy phép kinh doanh thực phẩm) và Luật Thương mại điện tử, Điều 15",
                "factor": f"Trang cửa hàng chưa công khai giấy phép kinh doanh thực phẩm cho mặt hàng "
                          f"{plan.get('item', '').lower()}.",
                "fix": "Công khai giấy phép trên trang cửa hàng; chỉ bán thực phẩm đóng gói sẵn thì không cần giấy "
                       "phép này."}
    if bad("LAW-LIC-03"):
        return {"law": "Danh sách tiêu cực 2025, thiết bị y tế loại III",
                "factor": "Cần giấy phép kinh doanh thiết bị y tế loại III.", "fix": "Bổ sung giấy phép."}
    if why.startswith("LAW-IP"):
        tm = "Luật Nhãn hiệu 2026, Điều 72" if today() >= date(2027, 1, 1) else "Luật Nhãn hiệu 2019, Điều 57"
        return {"law": f"Luật Chất lượng sản phẩm, Điều 39; {tm}",
                "factor": "Hàng có nhãn hiệu mà chưa có ủy quyền phân phối của chủ nhãn hiệu.",
                "fix": "Bổ sung ủy quyền phân phối hoặc chọn nhà cung cấp là nhà phân phối được ủy quyền."}
    if why in _ESCALATE_REASONS:
        return dict(_ESCALATE_REASONS[why])
    if kind == "reject":
        return {"law": f"Bộ quy tắc kiểm soát {legal.RULESET_VERSION}", "factor": "Hồ sơ vi phạm một quy tắc bắt buộc của sản phẩm.",
                "fix": "Liên hệ cán bộ tín dụng để biết cách điều chỉnh hồ sơ."}
    return {"law": "Quy trình phê duyệt của BuoyUp", "factor": "Hồ sơ cần cán bộ tín dụng xem thêm.",
            "fix": "Cán bộ sẽ liên hệ chị; chị không cần làm gì thêm."}


def _smaller_reason(doc: dict[str, Any] | None = None) -> dict[str, str]:
    ctl = (doc or {}).get("control") or {}
    settled = {r["rule"] for r in (ctl.get("phase2") or {}).get("resolved", [])}
    concerns = {x["rule"] for x in (ctl.get("phase1") or {}).get("concerns", []) if x["rule"] not in settled}
    if "CHAL-01" in concerns and "RISK-04" not in concerns:
        return {"law": "Quy tắc phân xử của BuoyUp: không đồng thuận thì hạ về mức kiểm soát độc lập chấp nhận",
                "factor": "Kiểm soát độc lập đánh giá rủi ro cao hơn đề xuất, nên hạn mức gửi ngân hàng là phương án nhỏ hơn.",
                "fix": "Chị vẫn chọn số tiền trong hạn mức này; muốn xét mức đầy đủ thì gửi khiếu nại hoặc gặp cán bộ."}
    return {"law": "Quy tắc kiểm soát rủi ro RISK-04 (giá khai lệch hóa đơn)",
            "factor": "Lập luận đề xuất chưa trỏ tới bằng chứng rằng giá khai không ảnh hưởng số tiền, nên hạn mức "
                      "gửi ngân hàng là phương án nhỏ hơn.",
            "fix": "Chị vẫn chọn số tiền trong hạn mức này; muốn xét mức đầy đủ thì gặp cán bộ."}


# --- seller actions after the gate --------------------------------------------------------------

def request_human(session: Session, app_row: BuApplication, doc: dict[str, Any], reason: str,
                  why: str = "HUMAN_REQUEST") -> None:
    """Never refused. Before a final decision it moves the case to an officer."""
    if not doc.get("human_request"):
        doc["human_request"] = {"id": "HR-" + secrets.token_hex(3), "reason": reason[:500], "at": now_iso()}
    events.log(session, app_row.id, "agent2", "request_human", "Chuyển yêu cầu người xem tới cán bộ")
    automated_reject = app_row.status == "rejected" and (doc.get("decision") or {}).get("by") == "gate"
    if app_row.status in PRE_DECISION or automated_reject:
        doc["escalation"] = {"why": why, "at": now_iso()}
        reason_obj = None if hidden_reason(doc) else dict(_ESCALATE_REASONS["HUMAN_REQUEST"])
        if why == "MANUAL_CHANNEL" and reason_obj:
            reason_obj["factor"] = "Chị chọn kênh thủ công để cán bộ xét hạn mức đầy đủ."
        doc["decision"] = {"kind": "escalate", "option_id": None, "amount": None, "by": "gate",
                           "reason": reason_obj, "at": now_iso()}
        if doc.get("control") and doc["control"].get("gate"):
            doc["control"]["gate"]["conditions"][4]["ok"] = False
            doc["control"]["gate"]["decision"] = "escalate"
        store(app_row, doc, "escalated")
    else:
        store(app_row, doc)


# --- officer -------------------------------------------------------------------------------------

def officer_decision(session: Session, app_row: BuApplication, doc: dict[str, Any], params: dict[str, Any],
                     officer: BuUser, decision: str, option_id: str | None, note: str) -> None:
    if app_row.status not in ("escalated", "needs_answer"):
        raise api_error(400, "INVALID_STATE", "Hồ sơ không ở trạng thái chờ cán bộ.", {"status": app_row.status})
    events.log(session, app_row.id, "officer", "decision", f"Cán bộ quyết định: {decision}",
               {"officer": officer.id, "note": note[:500], "option_id": option_id})
    if decision == "continue":
        _officer_continue(session, app_row, doc, params, officer, note)
        return
    if decision == "reject":
        reason = None if hidden_reason(doc) else {
            "law": "Quyết định của cán bộ tín dụng theo chính sách cho vay",
            "factor": note.strip() or "Hồ sơ chưa đáp ứng điều kiện cho vay ở thời điểm này.",
            "fix": "Liên hệ cán bộ tín dụng để biết cách bổ sung hồ sơ."}
        _decide(doc, "reject", None, "officer", reason, officer.id)
        store(app_row, doc, "rejected")
        return
    if not doc.get("offer"):
        raise api_error(400, "INVALID_STATE", "Hồ sơ chưa có phiếu đề xuất; dùng 'continue' để đi tiếp.")
    chosen = option_id or (doc.get("proposal") or {}).get("option_id") or "full"
    option = advise.find_option(doc, chosen)
    if option is None:
        raise api_error(400, "INVALID_OPTION", "Phương án không có trong phiếu đề xuất.", {"option_id": chosen})
    if decision == "approve":
        # An officer may approve over a code rule whose minimum is "reject"; the override is recorded
        # (event + decision) so post-audit sees it, instead of passing silently.
        results = (doc.get("control") or {}).get("results") or {}
        overridden = [code for code, r in results.items() if r.get("ok") is False and code in legal.RULES_BY_CODE
                      and legal.RULES_BY_CODE[code].min_verdict == "reject"]
        if overridden:
            events.log(session, app_row.id, "officer", "officer_override_hard_rule",
                       "Cán bộ duyệt vượt quy tắc bắt buộc: " + ", ".join(overridden),
                       {"rules": overridden, "officer": officer.id, "note": note[:500], "hidden_from_seller": True})
        approve(session, app_row, doc, option, by="officer", officer=officer)
        if overridden:
            doc["decision"]["overrode_rules"] = overridden
            store(app_row, doc)
        return
    full = doc["offer"]["options"][0]
    if option["amount"] >= full["amount"]:
        raise api_error(400, "INVALID_OPTION", "Phương án nhỏ hơn phải thấp hơn hạn mức đầy đủ.",
                        {"option_id": chosen})
    approve(session, app_row, doc, option, by="officer", officer=officer,
            reason={"law": "Quyết định của cán bộ tín dụng theo chính sách cho vay",
                    "factor": note.strip() or "Cán bộ duyệt hạn mức thấp hơn hạn mức đầy đủ.",
                    "fix": "Chị chọn số tiền trong hạn mức này."})


def _officer_continue(session: Session, app_row: BuApplication, doc: dict[str, Any], params: dict[str, Any],
                      officer: BuUser, note: str) -> None:
    """A case stopped at verification: the officer confirms the open flags and the case moves on."""
    if doc.get("offer") or doc["verification"]["state"] not in ("ESCALATED", "IN_PROGRESS"):
        raise api_error(400, "INVALID_STATE", "Chỉ dùng 'continue' cho hồ sơ bị chuyển ở bước xác minh.")
    for f in doc["verification"]["flags"]:
        if f["status"] == "open":
            f.update(status="resolved_by_check", resolved_by="officer",
                     note=f"Cán bộ xác nhận: {note.strip()[:200] or 'đã kiểm tra'}")
    from app.agents import agent1_verify as verify

    verify.conclude(session, app_row, doc, "VERIFIED")
    doc["escalation"] = None
    doc["human_request"] = None  # the officer has looked: the gate must not send it back for the same request
    store(app_row, doc, "verified")
    advise.make_offer(session, app_row, doc, params)
