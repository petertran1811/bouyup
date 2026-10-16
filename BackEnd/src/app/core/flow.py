"""Full calculation flow of one application, block by block, for staff (admin.html).

Every number is rebuilt from what the application stored (Agent 1's tool results in
``doc.internal.data``, the plan, the flags) with the same pure functions of
``algorithm`` (``prudent_revenue``, ``limit_caps``, ``revenue_rate``, shared with
``compute_sheet``), under the parameter version used for the offer. Each block is compared
with the stored sheet (``matches``); ``sheet_on_chain`` checks that stored sheet against
the fingerprint of the ``offer`` entry on the chain.

Stages: inputs and sources → Agent 1 (B10 flags) → B1–B9 → Agent 2 → Agent 3 and the
gate → B12 the banks' parallel approval and the signed legs → disbursement (Agent 4) →
B11 repayments, overdue, monitoring, notices.
Staff only: it shows thresholds and internal values the seller must never see.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import algorithm
from app.blockchain import chain
from app.blockchain import chain_remote
from app.core.params import active_params, with_defaults
from app.platform.tables import BuAlert, BuApplication, BuLoan, BuLoanShare, BuParams, BuRepayment, BuUser, BuWithdrawal

SRC = {
    "credit": "Báo cáo tín dụng · get_credit_report",
    "tax": "Thuế 银税互动 · pull_revenue / pull_tax_data",
    "network": "Lịch sử vay với BuoyUp (khoản vay đã ghi)",
    "statements": "Ảnh doanh thu người vay nộp · verify_statements",
    "fate": "FATE liên ngân hàng · get_interbank_score",
    "store": "Trang công khai của cửa hàng · lookup_public_store",
    "plan": "Biểu mẫu kế hoạch của người bán",
    "supplier": "Hóa đơn với nhà cung cấp · supplier_info",
    "flags": "Cờ của Agent 1",
    "params": "Bảng tham số",
}


def n(value: Any) -> str:
    """Vietnamese number: 139900 → 139.900, 0.63 → 0,63."""
    if value is None:
        return "—"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, float) and not value.is_integer():
        return f"{round(value, 4)}".replace(".", ",")
    return algorithm.fmt_num(value)


def pct(value: float | None) -> str:
    return "—" if value is None else f"{round(value * 100, 2):g}%".replace(".", ",")


def _in(name: str, value: Any, source: str, shown: str | None = None) -> dict[str, Any]:
    return {"name": name, "value": value, "shown": shown if shown is not None else n(value), "source": SRC.get(source, source)}


NOT_RECORDED = "Phiếu đã ghi không có khối này"
GRADE_E_NOTE = "Hạng E: phiếu không ghi khối này (từ chối trước khi tính hạn mức)"


def _block(code: str, title: str, question: str, inputs: list, steps: list[str], output: dict[str, Any],
           *, stored: dict[str, Any] | None = None, note: str | None = None, status: str = "done",
           expect: bool = True) -> dict[str, Any]:
    """``stored`` None while ``expect`` is True: the recorded sheet lacks the block (``matches`` None)."""
    if stored is None and expect:
        note = note or NOT_RECORDED
    out: dict[str, Any] = {"block": code, "title": title, "question": question, "inputs": inputs, "steps": steps,
                           "output": output, "status": status}
    if stored is not None:  # every output key must equal the recorded sheet; a missing key is a mismatch
        out["matches"] = all(k in stored and stored[k] == v for k, v in output.items())
    if note:
        out["note"] = note
    return out


# --- algorithm (B1–B9) -----------------------------------------------------------------

def _params_for(session: Session, doc: dict[str, Any]) -> tuple[dict[str, Any], str, bool]:
    """Parameter set of the offer when recorded, else the active one (``rebuilt`` = True)."""
    version = (doc.get("internal") or {}).get("params_version")
    if version:
        row = session.get(BuParams, version)
        if row is not None:
            return with_defaults(row.params), version, False
    row = session.scalar(select(BuParams).where(BuParams.active.is_(True)).limit(1))
    return active_params(session), (row.version if row else "mặc định"), True


def algorithm_blocks(params: dict[str, Any], tier: int, plan: dict[str, Any] | None, facts: dict[str, Any],
                     penalties: int, stored_sheet: dict[str, Any], borrower_type: str = "individual_business"
                     ) -> list[dict[str, Any]]:
    credit, revenue, tax = facts["credit"], facts["revenue"], facts["tax"]
    stored = stored_sheet.get("blocks") or {}
    out: list[dict[str, Any]] = []

    group = algorithm.customer_group(credit)
    rule = ("trễ ≥ 30 ngày, vỡ nợ, nợ xấu hoặc từng quá hạn với BuoyUp → nhóm 4" if group == 4 else
            "đã vay qua BuoyUp và trả tốt → nhóm 1" if group == 1 else
            "có tín dụng ở nơi khác → nhóm 2" if group == 2 else "chưa từng vay → nhóm 3")
    out.append(_block("B1", "Nhóm khách hàng", "Người này từng vay và trả thế nào?", [
        _in("Trễ hạn nặng nhất 24 tháng (ngày)", credit.get("late_max_days_24m", 0), "credit"),
        _in("Lịch sử vay với BuoyUp", credit.get("network_history"), "network",
            {"good": "đã tất toán, trả tốt", "bad": "từng quá hạn ≥ 30 ngày"}.get(str(credit.get("network_history")),
                                                                                 "chưa vay qua BuoyUp")),
        _in("Có tín dụng ở nơi khác", bool(credit.get("has_credit_elsewhere")), "credit",
            "có" if credit.get("has_credit_elsewhere") else "không"),
        _in("Vỡ nợ trong 24 tháng", bool(credit.get("defaulted_within_24m")), "credit",
            "có" if credit.get("defaulted_within_24m") else "không"),
        _in("Đang có nợ xấu", bool(credit.get("active_npl")), "credit", "có" if credit.get("active_npl") else "không"),
    ], [f"Luật: {rule}"], {"group": group},
        stored={"group": stored_sheet["group"]} if "group" in stored_sheet else None))

    b5 = algorithm.sweep_cap(tax["gross_margin"], tax["platform_fee"])
    graded = params["rates"].get(stored_sheet.get("grade")) is not None
    b3 = None
    if plan:
        b3 = algorithm.capital_need(params, plan, tax.get("invoice_unit_price_3m"), facts["supplier"])
        deductions = plan["inventory"] + plan["own_capital"] + plan.get("other_loans", 0)
        steps = [f"Giá dùng = số nhỏ hơn của (giá khai {n(plan['price'])}, giá hóa đơn "
                 f"{n(tax.get('invoice_unit_price_3m'))}) = {n(b3['unit_price_used'])}"]
        if b3["data_source_gap"]:
            steps[0] = (f"Không có hóa đơn: giá tham chiếu = {n(plan['price'])} × (1 − "
                        f"{n(params['price']['no_invoice_haircut'])}); giá dùng = {n(b3['unit_price_used'])}")
        steps.append(f"Giá trị kế hoạch = {n(plan['qty'])} × {n(b3['unit_price_used'])} × hệ số nhà cung cấp "
                     f"{n(b3['supplier_factor'])} = {n(b3['plan_value'])}")
        steps.append(f"Nhu cầu (vay vừa đủ) = {n(b3['plan_value'])} − tồn kho {n(plan['inventory'])} − vốn tự có "
                     f"{n(plan['own_capital'])} − vay khác {n(plan.get('other_loans', 0))} = {n(b3['need'])}"
                     + (" (không âm)" if b3["plan_value"] < deductions else ""))
        out.append(_block("B3", "Giá nhập hợp lý, nhu cầu vốn", "Người vay thật sự thiếu bao nhiêu để nhập hàng?", [
            _in("Số lượng định nhập", plan["qty"], "plan"), _in("Giá khai", plan["price"], "plan"),
            _in("Giá nhập trên hóa đơn 3 tháng", tax.get("invoice_unit_price_3m"), "tax"),
            _in("Tồn kho dùng được", plan["inventory"], "plan"), _in("Vốn tự có", plan["own_capital"], "plan"),
            _in("Khoản vay khác", plan.get("other_loans", 0), "plan"),
            _in("Hệ số nhà cung cấp", b3["supplier_factor"], "supplier"),
        ], steps, {"unit_price_used": b3["unit_price_used"], "price_declared": b3["price_declared"],
                   "plan_value": b3["plan_value"], "need": b3["need"]}, stored=stored.get("B3"), expect=graded,
            note=None if stored.get("B3") or graded else GRADE_E_NOTE))

    verified = bool(facts.get("statements_verified"))
    b4 = algorithm.prudent_revenue(params, revenue, facts["industry"], verified)
    cap = params["forecast"]["growth_cap"]
    out.append(_block("B4", "Doanh thu tháng dự báo thận trọng", "Mỗi tháng có bao nhiêu doanh thu để dựa vào?", [
        _in("Doanh thu bình quân 12 tháng (thuế)", revenue["monthly_avg_12m"], "tax"),
        _in("Tăng trưởng 3 tháng", revenue["growth_3m"], "tax", pct(revenue["growth_3m"])),
        _in("Trần tăng trưởng", cap, "params", pct(cap)),
        _in(f"Hệ số thận trọng ngành {facts['industry']}", params["prudence"].get(facts["industry"],
                                                                                 params["prudence"]["khác"]), "params"),
        _in("Ảnh doanh thu người vay nộp khớp thuế", verified, "statements", "có (+5% hệ số)" if verified else "không"),
    ], [f"Tăng trưởng dùng = số nhỏ hơn của ({pct(revenue['growth_3m'])}, {pct(cap)}) = {pct(b4['growth_used'])}",
        f"Dự báo = {n(revenue['monthly_avg_12m'])} × (1 + {n(b4['growth_used'])}) = {n(b4['forecast'])}",
        f"Thận trọng = {n(b4['forecast'])} × {n(b4['prudence'])} = {n(b4['prudent'])}"],
        {"forecast": b4["forecast"], "prudent": b4["prudent"], "growth_used": b4["growth_used"],
         "prudence": b4["prudence"]}, stored=stored.get("B4"), expect=graded,
        note=None if stored.get("B4") or graded else GRADE_E_NOTE))

    out.append(_block("B5", "Phần doanh thu dành trả nợ", "Mỗi đồng doanh thu, dành trả nợ tối đa bao nhiêu?", [
        _in("Biên lãi gộp 12 tháng (hóa đơn)", tax["gross_margin"], "tax", pct(tax["gross_margin"])),
        _in("Tỷ lệ phí sàn", tax["platform_fee"], "tax", pct(tax["platform_fee"])),
    ], [f"Trần = (1 − {n(tax['gross_margin'])}) ÷ (1 − {n(tax['platform_fee'])}) = {pct(b5['sweep_cap'])}",
        f"Dùng được (làm tròn xuống 1%) = {pct(b5['sweep_usable'])}"], b5, stored=stored.get("B5")))

    points = algorithm.scorecard(params, credit=credit, fate=facts["fate"], rating=facts["rating"],
                                 age_m=revenue["months_with_sales"], cv=revenue["cv_monthly"],
                                 gross_margin=tax["gross_margin"], monthly_avg=revenue["monthly_avg_12m"])
    fate_thin = facts.get("fate_state") == "thin"
    alt = algorithm.fate_alt_points(params, facts.get("fate_alt") or {}) if fate_thin else None
    if alt is not None:
        points["fate"] = sum(alt.values())
    score = sum(points.values())
    before = algorithm.grade_of(params, score)
    hard_e = credit.get("late_max_days_24m", 0) >= 90 or bool(credit.get("defaulted_within_24m"))
    grade = algorithm.apply_penalties(before, penalties, hard_e)
    rows = [("Trễ hạn nặng nhất 24 tháng", credit.get("late_max_days_24m", 0), "credit", "late"),
            ("Số lần tra cứu 3 tháng", credit.get("inquiries_3m", 0), "credit", "inquiries"),
            ("Nợ trên doanh thu", credit.get("debt_to_inflow", 0.0), "credit", "debt"),
            (("FATE tín hiệu mỏng → điểm thay thế (hóa đơn đều, chuỗi cung ứng, bảng lương, tuổi ĐKKD)"
              if fate_thin else "Điểm FATE (1 tốt nhất)"),
             (" + ".join(str(v) for v in alt.values()) if alt else facts["fate"]), "fate", "fate"),
            ("Điểm cửa hàng", facts["rating"], "store", "rating"),
            ("Số tháng có doanh thu", revenue["months_with_sales"], "tax", "age"),
            ("Độ dao động doanh thu (CV)", revenue["cv_monthly"], "tax", "volatility"),
            ("Biên lãi gộp", tax["gross_margin"], "tax", "gross_margin"),
            ("Doanh thu bình quân tháng", revenue["monthly_avg_12m"], "tax", "monthly_avg")]
    grades = params["scorecard"]["grades"]
    out.append(_block("B6", "Bảng điểm → hạng", "Rủi ro cỡ nào?",
                      [{**_in(name, value, src), "points": points[key]} for name, value, src, key in rows],
                      [" + ".join(str(points[key]) for *_, key in rows) + f" = {score} điểm",
                       f"Ngưỡng hạng: A ≥ {grades['A']} · B ≥ {grades['B']} · C ≥ {grades['C']} · D ≥ {grades['D']} → "
                       f"hạng {before}",
                       ("Loại thẳng hạng E (trễ ≥ 90 ngày hoặc vỡ nợ chưa đủ 24 tháng)" if hard_e else
                        f"Cờ có phạt: hạ {penalties} hạng → hạng {grade}" if penalties else "Không có cờ phạt")],
                      {"score": score, "grade_before": before, "grade": grade}, stored=stored.get("B6")))

    rate = params["rates"].get(grade)
    floor = stored_sheet.get("b7_floor") or {}
    b7_steps = [f"Bảng lãi: A {pct(params['rates']['A'])} · B {pct(params['rates']['B'])} · C {pct(params['rates']['C'])}"
                f" · D {pct(params['rates']['D'])} · E từ chối",
                f"Hạng {grade} → lãi {pct(rate)} (là toàn bộ chi phí năm, không phí)" if rate is not None
                else "Hạng E: từ chối thay vì tăng lãi"]
    if floor:
        b7_steps.append(f"Sàn lãi = chi phí vốn {pct(floor.get('cost_of_funds'))} + chi phí xử lý ÷ (dư nợ bình quân × "
                        f"kỳ hạn) = {pct(floor.get('rate_floor'))} → {'đạt' if rate and rate >= floor['rate_floor'] else 'không đạt'}")
    out.append(_block("B7", "Lãi suất", "Lãi bao nhiêu?", [_in("Hạng sau phạt", grade, "B6")], b7_steps,
                      {"rate": rate}, stored=stored.get("B7")))
    if rate is None:
        return out

    tenors = algorithm.tenors_for(params, borrower_type)
    tenor = max(tenors)
    c = algorithm.limit_caps(params, prudent=b4["prudent"], sweep_usable=b5["sweep_usable"], rate=rate,
                             tenor_max=tenor, monthly_avg=revenue["monthly_avg_12m"], group=group,
                             borrower_type=borrower_type, fate_thin=fate_thin,
                             seed=algorithm.seed_ratio(params, facts.get("history")))
    limit = c["limit"] if c["limit"] >= params["product"]["min_amount"] else 0
    need = b3["need"] if b3 else None
    suggested = min(limit, need) if need is not None else limit
    if suggested and suggested < params["product"]["min_amount"]:
        suggested = 0
    names = {"affordability": "khả năng trả", "group_cap": "trần theo nhóm", "type_cap": "trần loại người vay",
             "thin_fate_cap": "trần FATE mỏng", "seed_cap": "khoản vay mồi"}
    seed_steps = ([f"Khoản vay mồi: {n(c['seed_ratio'])} × {n(c['computed'])} = {n(c['limit'])} "
                   "(hệ số tăng khi trả tốt và tiền bán hàng về TK WeBank đều đặn)"] if c["seed_ratio"] < 1 else [])
    p = params["product"]
    out.append(_block("B8", "Hạn mức", "Cho vay tối đa bao nhiêu?", [
        _in("Doanh thu tháng thận trọng (B4)", b4["prudent"], "B4"),
        _in("Phần doanh thu dành trả nợ (B5)", b5["sweep_usable"], "B5", pct(b5["sweep_usable"])),
        _in("Lãi năm (B7)", rate, "B7", pct(rate)), _in("Kỳ hạn dài nhất (tháng)", tenor, "params"),
        _in(f"Hệ số nhóm {group}", p["group_cap_mult"][str(group)], "params"),
        _in("Doanh thu bình quân tháng", revenue["monthly_avg_12m"], "tax"),
        _in("Trần loại người vay", c["caps"]["type_cap"], "params"),
        _in("Nhu cầu (B3)", need, "B3"),
    ], [f"Khả năng trả = {n(b4['prudent'])} × {tenor} × {n(b5['sweep_usable'])} ÷ (1 + {n(rate)} × {tenor} ÷ 12) = "
        f"{n(round(c['caps']['affordability']))}",
        f"Trần theo nhóm = {n(p['group_cap_mult'][str(group)])} × {n(revenue['monthly_avg_12m'])} = {n(c['caps']['group_cap'])}",
        "Số nhỏ nhất của (" + ", ".join(f"{names[k]} {n(round(v))}" for k, v in c["caps"].items())
        + f") → làm tròn xuống trăm {n(c['computed'])}", *seed_steps,
        f"Hạn mức ({names[c['binding']]}) = {n(limit)}",
        f"Gợi ý vay vừa đủ = số nhỏ hơn của (hạn mức, nhu cầu) = {n(suggested)}"],
        {"affordability": round(c["caps"]["affordability"]), "group_cap": c["caps"]["group_cap"],
         "type_cap": c["caps"]["type_cap"], "binding_cap": c["binding"], "limit": limit, "suggested": suggested,
         "computed": c["computed"]},
        stored=stored.get("B8")))
    rr = algorithm.revenue_rate(params, limit, rate, tenor, b4["prudent"], b5["sweep_usable"]) if limit else 0.0
    out.append(_block("B9", "Kỳ hạn và hình thức trả", "Trả trong bao lâu, trả thế nào?", [
        _in("Hạn mức (B8)", limit, "B8"), _in("Khung kỳ hạn", ", ".join(map(str, tenors)), "params"),
        _in("Doanh thu tháng thận trọng (B4)", b4["prudent"], "B4"),
        _in("Phần trả gốc tối thiểu", params["repay"]["min_principal_share"], "params",
            pct(params["repay"]["min_principal_share"])),
    ], ["Trả góp cố định: gốc chia đều mỗi kỳ + lãi theo ngày thực tế trên dư nợ",
        f"Trả theo doanh thu: tỷ lệ = (gốc + lãi ước tính) ÷ (doanh thu thận trọng × kỳ hạn), không vượt "
        f"{pct(b5['sweep_usable'])} → {pct(rr)} ở kỳ hạn {tenor} tháng",
        f"Mỗi kỳ ít nhất = lãi kỳ + {pct(params['repay']['min_principal_share'])} gốc của một kỳ trả góp đều"],
        {"tenors": tenors, "tenor_max": tenor, "methods": list(algorithm.METHODS), "revenue_rate_max_tenor": rr,
         "min_principal_share": params["repay"]["min_principal_share"]}, stored=stored.get("B9")))
    return out


# --- whole application -----------------------------------------------------------------

def _b10(doc: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    v = doc.get("verification") or {}
    calls = {t["id"]: t for t in v.get("tool_calls") or []}
    link = next((t for t in calls.values() if t.get("tool") == "link_entities"), None)
    stmt = next((t for t in calls.values() if t.get("tool") == "verify_statements"), None)
    f, r = params["flags"], params["revenue"]
    rows = [{"name": "Đột biến doanh thu tháng gần nhất", "value": (v.get("derived") or {}).get("spike_ratio"),
             "rule": f"> {n(f['spike_mult'])} lần bình quân → RISK_SALES_SPIKE"},
            {"name": "Ảnh doanh thu người vay nộp so với thuế", "value": (stmt or {}).get("output"),
             "rule": f"lệch > {pct(r['statement_tolerance'])} → hỏi lại; > {pct(r['statement_reject'])} → không dùng"},
            {"name": "Cụm liên kết (union-find)", "value": (link or {}).get("output"),
             "rule": "nhà cung cấp cùng cụm → RISK_SUPPLIER_LINKED"}]
    return {"block": "B10", "title": "Gian lận (cờ và cụm liên kết)", "question": "Có dấu hiệu gian lận không?",
            "checks": rows, "flags": [{k: fl.get(k) for k in ("code", "status", "note", "penalty", "evidence_tool_call")}
                                      for fl in v.get("flags") or []], "status": "done"}


def _split(doc: dict[str, Any], session: Session, loan: BuLoan | None) -> dict[str, Any]:
    """Stage 2 (bank side): the parallel rounds and the final split; the legs signed in Stage 4."""
    syn = doc.get("syndicate") or {}
    shares = []
    if loan is not None:
        shares = [{"bank": s.bank_code, "pct": s.pct, "amount": s.amount, "repaid": s.repaid,
                   "contract_id": s.contract_id}
                  for s in session.scalars(select(BuLoanShare).where(BuLoanShare.loan_id == loan.id))]
    return {"block": "B12", "title": "Các ngân hàng duyệt song song", "question": "Ngân hàng nào đồng ý, mỗi bên bao nhiêu?",
            "rounds": syn.get("rounds") or [], "result": syn.get("status"), "limit": syn.get("limit"),
            "reduced": syn.get("reduced"), "split": syn.get("split") or [], "expires_at": syn.get("expires_at"),
            "legs": (doc.get("contract") or {}).get("legs") or [], "shares": shares,
            "status": "done" if syn else "pending"}


def _monitoring(session: Session, loan: BuLoan | None, params: dict[str, Any]) -> dict[str, Any] | None:
    if loan is None:
        return None
    d = loan.doc or {}
    ew = d.get("early_warning") or {}
    w = params["early_warning"]
    rp = params["repay"]
    repayments = list(session.scalars(select(BuRepayment).where(BuRepayment.loan_id == loan.id)
                                      .order_by(BuRepayment.at)))
    alerts = list(session.scalars(select(BuAlert).where(BuAlert.loan_id == loan.id).order_by(BuAlert.at.desc())))
    return {
        "block": "B11", "title": "Thu nợ và cảnh báo sớm (Agent 4)", "question": "Sau giải ngân có ổn không?",
        "loan": {"id": loan.id, "status": loan.status, "amount": d.get("amount"), "repaid": loan.repaid,
                 "outstanding": loan.outstanding, "method": d.get("method"), "tenor_m": d.get("tenor_m"),
                 "due_day": d.get("due_day"), "first_due_date": d.get("first_due_date"),
                 "final_due_date": d.get("final_due_date"), "clock": d.get("clock"), "arrears": d.get("arrears"),
                 "overdue_days": d.get("overdue_days"), "balance": (d.get("account") or {}).get("balance")},
        "schedule": d.get("schedule") or [],
        "early_warning": {"level": ew.get("level", "green"), "score": ew.get("score"), "as_of": ew.get("as_of"),
                          "signals": ew.get("signals") or []},
        "rule": ("Trọng số: " + " · ".join(f"{k} {v}" for k, v in w["weights"].items())
                 + f"; xanh < {w['yellow']} · vàng {w['yellow']}–{w['red']} · đỏ ≥ {w['red']}; đỏ ngay khi dùng vốn sai "
                 f"mục đích hoặc quá hạn ≥ {w['overdue_red_days']} ngày. Ân hạn {rp['grace_days']} ngày rồi lãi phạt "
                 f"{n(rp['penalty_mult'])} × lãi; quá hạn {rp['report_overdue_days']} ngày báo trung tâm tín dụng."),
        "repayments": [{"at": r.at.isoformat() + "Z", "amount": r.swept, "split": r.split, "chain_tx": r.chain_tx}
                       for r in repayments],
        "alerts": [{"at": a.at.isoformat() + "Z", "level": a.level, "text": a.text, "acked": a.acked} for a in alerts],
        "notices": d.get("notices") or [], "use_of_funds": d.get("use_of_funds"), "reminders": d.get("reminders") or [],
        "transfers": (d.get("account") or {}).get("transfers") or [], "bureau": d.get("bureau") or [],
        "bank_report": d.get("bank_report"), "status": "done",
    }


def _withdrawal(session: Session, loan: BuLoan | None) -> dict[str, Any] | None:
    if loan is None or not loan.withdrawal_id:
        return None
    row = session.get(BuWithdrawal, loan.withdrawal_id)
    if row is None:
        return None
    env = row.envelope or {}
    ref = env.get("chain") or {}
    return {"id": row.id, "tx": row.tx, "block": row.block, "simulated": not env.get("remote"),
            "explorer_url": ref.get("explorerUrl"), "sealed_by": ref.get("sealedBy"),
            "confirmed": ref.get("confirmedNodes"), "nodes": ref.get("totalNodes"),
            "legs_mismatch": bool(env.get("legs_mismatch"))}


def _sheet_on_chain(session: Session, app_row: BuApplication, sheet: dict[str, Any]) -> bool | None:
    """The stored sheet is the one sealed in the last ``offer`` chain entry, and that entry's
    fingerprint still verifies (editing the DB copy of inputs and sheet together is caught here)."""
    if not sheet:
        return None
    offers = [e for e in chain.case_entries(session, app_row.id) if e.kind == "offer"]
    if not offers:
        return None
    entry = offers[-1]
    return (chain.fingerprint(entry.payload, entry.salt) == entry.fingerprint
            and (entry.payload or {}).get("sheet") == json.loads(chain.canonical(sheet)))


def _chain(session: Session, app_id: str) -> list[dict[str, Any]]:
    try:
        rows = chain.public_entries(session, chain.case_entries(session, app_id))
        base = chain_remote.get_remote().base_url if chain.mode() == "remote" else None
    except chain_remote.ChainUnavailable:  # remote mode without a configured URL
        return [chain.entry_public(e) for e in chain.case_entries(session, app_id)]
    for e in rows:
        remote = e.get("remote")
        if base and remote and remote.get("tx"):
            remote["explorer_url"] = f"{base}/explorer/#/tx/{remote['tx']}"
    return rows


def application_flow(session: Session, app_row: BuApplication) -> dict[str, Any]:
    doc = dict(app_row.doc or {})
    seller = session.get(BuUser, app_row.seller_user_id)
    loan = session.get(BuLoan, app_row.loan_id) if app_row.loan_id else None
    params, version, rebuilt = _params_for(session, doc)
    internal = doc.get("internal") or {}
    sheet = internal.get("sheet") or {}
    blocks: list[dict[str, Any]] = []
    error = None
    if internal.get("data") and (doc.get("verification") or {}).get("state") == "VERIFIED":
        from app.agents import agent2_advise as advise

        plan = advise._plan_inputs(doc)
        try:
            facts = advise._facts(app_row, doc, plan)
            blocks = algorithm_blocks(params, app_row.tier, plan, facts, advise.penalties(doc), sheet,
                                      doc.get("borrower_type") or "individual_business")
        except Exception as exc:  # noqa: BLE001 - display-only rebuild of an old or partial dossier: never 500
            error = f"Không dựng lại được khối tính toán: {type(exc).__name__} {exc}"
    store = (doc.get("stores") or [{}])[0]
    v = doc.get("verification") or {}
    control = doc.get("control") or {}
    return {
        "application": {"id": app_row.id, "code": app_row.code, "status": app_row.status, "tier": app_row.tier,
                        "currency": doc.get("currency"), "region": doc.get("region")},
        "seller": {"id": seller.id if seller else None, "name": seller.display_name if seller else None,
                   "email": seller.email if seller else None, "store": store.get("entity"),
                   "platform": store.get("platform")},
        "params_version": version, "params_rebuilt": rebuilt, "error": error,
        "sources": [{"tool": t.get("tool"), "id": t.get("id"), "simulated": t.get("simulated", True)}
                    for t in v.get("tool_calls") or []],
        "agent1": {"state": v.get("state"), "steps": len(v.get("steps") or []), "record_hash": v.get("record_hash")},
        "b10": _b10(doc, params),
        "blocks": blocks,
        "matches": (None if not sheet or not blocks or any(b.get("note") == NOT_RECORDED for b in blocks)
                    else all(b.get("matches", True) for b in blocks)),
        "sheet_on_chain": _sheet_on_chain(session, app_row, sheet),
        "agent2": {"option_id": (doc.get("proposal") or {}).get("option_id"),
                   "rationale": (doc.get("proposal") or {}).get("rationale") or [],
                   "card": (doc.get("offer") or {}).get("card")},
        "agent3": {"floor": (control.get("phase0") or {}).get("floor"),
                   "phase1": (control.get("phase1") or {}).get("verdict"),
                   "phase2": (control.get("phase2") or {}).get("verdict"),
                   # Review items 1–2: the challenger's score, the debate rounds and the model independence.
                   "challenger_pd": ((control.get("phase1") or {}).get("challenger") or {}).get("pd"),
                   "debate_rounds": len((control.get("phase2") or {}).get("rounds") or []),
                   "cap_reached": (control.get("phase2") or {}).get("cap_reached"),
                   "independence": (control.get("phase1") or {}).get("independence")},
        "retrieval": control.get("retrieval"),
        "gate": control.get("gate"), "decision": doc.get("decision"),
        "selection": doc.get("selection"), "contract": doc.get("contract"),
        "b12": _split(doc, session, loan),
        "withdrawal": _withdrawal(session, loan),
        "b11": _monitoring(session, loan, params),
        "chain": _chain(session, app_row.id),
        "chain_mode": chain.mode(),
    }
