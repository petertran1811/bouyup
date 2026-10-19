"""Loan circle, Stages 3–4: the borrower's choice within the approved limit, the cost disclosure
and the contract, the signature, then Agent 4.

- Stage 3 (:func:`select`): amount (≤ the limit the banks approved), tenor (by borrower type),
  repayment method (instalment or revenue-based, chosen once), due day (1–28). No new approval: the
  banks approved the limit, not one amount. One loan at a time per borrower.
- Stage 4 (:func:`issue`, :func:`sign`): the disclosure lists principal, annual rate (= total annual
  cost, no fee), penalty rate, the minimum-payment rule, the banks and their shares, the complaint
  channel and the projected schedule; it must stay on screen ``contract.read_seconds`` before
  signing. Signing needs the WeBank business account, the use-of-funds commitment, the supplier's
  account when part of the loan goes straight to the supplier, and a guarantee from the legal
  representative of a company. At signing each bank's concentration room and budget are taken
  (``syndicate.reserve_at_signing``), the contract is anchored on the chain, and Agent 4 disburses.

Code only: no model writes any figure here.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import func, select as sql_select
from sqlalchemy.orm import Session

from app.agents import agent2_advise as advise
from app.blockchain import chain
from app.core import algorithm
from app.platform import events
from app.platform.db.tables import utcnow
from app.platform.errors import api_error
from app.platform.tables import BuApplication, BuLoan

OPEN_APP_STATUSES = ("selected", "signed")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(str(value).rstrip("Z"))


def expired(doc: dict[str, Any]) -> bool:
    exp = (doc.get("offer") or {}).get("expires_at")
    return bool(exp) and _parse(exp) <= utcnow()


def other_open_loan(session: Session, app_row: BuApplication) -> str | None:
    """POL-07: one loan at a time. Returns what is open (a loan, or another application past selection)."""
    loans = session.scalar(sql_select(func.count()).select_from(BuLoan).where(
        BuLoan.seller_user_id == app_row.seller_user_id, BuLoan.status.in_(("active", "overdue")))) or 0
    if loans:
        return "loan"
    other = session.scalar(sql_select(func.count()).select_from(BuApplication).where(
        BuApplication.seller_user_id == app_row.seller_user_id, BuApplication.id != app_row.id,
        BuApplication.status.in_(OPEN_APP_STATUSES))) or 0
    return "application" if other else None


def one_loan_error(message: str) -> Exception:
    """POL-07 at selection / signing. In a demo environment the error names the demo reset of sample loans."""
    from app.data_sources import sources

    if sources.is_demo_env():
        return api_error(400, "ONE_LOAN_AT_A_TIME", message + " Bấm “Làm mới khoản vay mẫu” để tất toán "
                                                              "các khoản vay mở từ gian hàng mẫu.",
                         {"demo_reset": "/v4/demo/reset-my-loans"})
    return api_error(400, "ONE_LOAN_AT_A_TIME", message)


def _consent_ok(doc: dict[str, Any]) -> None:
    from app.data_sources import consent as consent_mod

    problem = consent_mod.blocked_reason(doc.get("consent"))
    if problem:
        raise api_error(400, "INVALID_STATE", "Ủy quyền đã bị rút hoặc hết hạn; chị cần ký lại trước khi chọn và ký "
                                              "khoản vay.", {"consent": problem})


def validate_choice(params: dict[str, Any], doc: dict[str, Any], amount: int, tenor_m: int, method: str,
                    due_day: int) -> None:
    offer = doc["offer"]
    limit = int(offer["limit"])
    low = min(int(params["product"]["min_amount"]), limit)
    if not low <= amount <= limit:
        raise api_error(400, "VALIDATION_ERROR", f"Số tiền phải trong khoảng {algorithm.fmt_num(low)}–"
                                                 f"{algorithm.fmt_num(limit)} (hạn mức đã duyệt).",
                        {"field": "amount", "min": low, "max": limit})
    if not params["product"].get("borrower_picks_tenor", True) and tenor_m != max(offer["tenors"]):
        raise api_error(400, "VALIDATION_ERROR", "Kỳ hạn do hệ thống xác định theo loại người vay.",
                        {"field": "tenor_m", "allowed": [max(offer["tenors"])]})
    if tenor_m not in offer["tenors"]:
        raise api_error(400, "VALIDATION_ERROR", "Kỳ hạn không có trong khung của loại người vay này.",
                        {"field": "tenor_m", "allowed": offer["tenors"]})
    if method not in algorithm.METHODS or method not in params["product"].get("methods", algorithm.METHODS):
        raise api_error(400, "VALIDATION_ERROR", "Hình thức trả không hợp lệ.",
                        {"field": "method", "allowed": list(params["product"].get("methods", algorithm.METHODS))})
    if not 1 <= due_day <= int(params["product"]["due_day_max"]):
        raise api_error(400, "VALIDATION_ERROR", f"Ngày trả trong tháng từ 1 đến {params['product']['due_day_max']}.",
                        {"field": "due_day"})


def select(session: Session, app_row: BuApplication, doc: dict[str, Any], params: dict[str, Any], *,
           amount: int, tenor_m: int, method: str, due_day: int) -> dict[str, Any]:
    """Stage 3: store the choice with its projected schedule. Can be changed until signing."""
    validate_choice(params, doc, amount, tenor_m, method, due_day)
    _consent_ok(doc)
    if other_open_loan(session, app_row):
        raise one_loan_error("Mỗi người vay chỉ có một khoản vay tại một thời điểm; bạn cần tất toán khoản đang có "
                             "trước.")
    quote = advise.quote(params, doc, amount, tenor_m, method, due_day)
    doc["selection"] = {**quote, "at": utcnow().isoformat() + "Z"}
    doc["contract"] = None  # a new choice needs a new disclosure (and a new reading time)
    events.log(session, app_row.id, "seller", "select",
               f"Chọn {algorithm.fmt_num(amount)} · {tenor_m} tháng · {algorithm.METHOD_LABELS[method]} · ngày {due_day}")
    advise._post(session, app_row.id, "agent2",
                 f"Chị chọn {algorithm.fmt_num(amount)} tệ trong {tenor_m} tháng, {algorithm.METHOD_LABELS[method].lower()}, "
                 f"trả ngày {due_day} hằng tháng. Kỳ đầu {quote['first_due_date']} khoảng "
                 f"{algorithm.fmt_num(quote['first_payment'])}; tổng lãi dự kiến {algorithm.fmt_num(quote['total_interest'])}, "
                 "không có phí. Bước tiếp theo: đọc bảng chi phí và hợp đồng rồi ký.", card=quote)
    return doc["selection"]


def _banks(doc: dict[str, Any], amount: int) -> list[dict[str, Any]]:
    from app.banks.split import split_largest_remainder

    split = (doc.get("syndicate") or {}).get("split") or []
    parts = split_largest_remainder(amount, [round(s["pct"] * 10_000) for s in split]) if split else []
    return [{"bank": s["bank"], "name": s.get("name", s["bank"]), "pct": s["pct"], "role": s.get("role"),
             "amount": part} for s, part in zip(split, parts)]


def issue(session: Session, app_row: BuApplication, doc: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Stage 4: the disclosure and contract for the current choice (issued once per choice; the
    reading clock starts here)."""
    sel = doc.get("selection")
    if not sel:
        raise api_error(400, "INVALID_STATE", "Chị cần chọn số tiền và ngày trả trước.")
    current = doc.get("contract")
    if current and current.get("selection_at") == sel["at"]:
        return current
    rate = float(sel["rate"])
    penalty = round(min(rate * float(params["repay"]["penalty_mult"]), float(params["legal"]["rate_cap"])), 4)
    rp = params["repay"]
    body = {
        "id": "HD-" + secrets.token_hex(4).upper(), "application": app_row.code,
        "borrower": (doc.get("stores") or [{}])[0].get("entity"), "borrower_type": doc.get("borrower_type"),
        "amount": sel["amount"], "rate": rate, "apr": sel["apr"], "fees": 0, "penalty_rate": penalty,
        "tenor_m": sel["tenor_m"], "method": sel["method"], "method_label": sel["method_label"],
        "due_day": sel["due_day"], "revenue_rate": sel.get("revenue_rate"),
        "first_due_date": sel["first_due_date"], "final_due_date": sel["final_due_date"],
        "total_interest": sel["total_interest"], "total_due": sel["total_due"], "schedule": sel["schedule"],
        "payee": sel["payee_split"],
        "banks": _banks(doc, int(sel["amount"])),
        "terms": [
            f"Lãi suất năm {rate * 100:.2f}% là toàn bộ chi phí; không có phí nào khác.",
            "Lãi tính theo số ngày thực tế trên dư nợ gốc còn lại (năm 365 ngày).",
            f"Trả chậm: {rp['grace_days']} ngày ân hạn, sau đó lãi phạt {penalty * 100:.2f}%/năm trên số tiền quá hạn.",
            f"Trả tối thiểu (chỉ hình thức trả góp, kỳ hạn từ {rp['min_tenor_m']} tháng): lãi kỳ + "
            f"{round(rp['min_principal_share'] * 100)}% gốc của một kỳ; tối đa {rp['min_max_consecutive']} kỳ liên tiếp.",
            "Trả trước bất cứ lúc nào, không mất phí; chỉ trả lãi cho số ngày đã dùng.",
            f"Quá hạn {rp['report_overdue_days']} ngày: báo trung tâm thông tin tín dụng; các bước xử lý do nhóm ngân "
            f"hàng nắm từ {round(rp['majority'] * 100, 2):g}% dư nợ quyết định.",
            "Tiền hàng từ sàn về tài khoản kinh doanh WeBank cho đến khi tất toán; hệ thống tự trích vào ngày trả.",
            "Không dùng vốn vay để mua chứng khoán, bất động sản hay cho vay lại.",
        ],
        "complaint_channel": params["contract"]["complaint_channel"],
        "read_seconds": int(params["contract"]["read_seconds"]),
        "issued_at": utcnow().isoformat() + "Z", "selection_at": sel["at"],
        "needs": {"supplier_account": bool(sel["payee_split"].get("to_supplier")),
                  "guarantee": doc.get("borrower_type") == "company"},
    }
    body["hash"] = "sha256:" + hashlib.sha256(chain.canonical(
        {k: v for k, v in body.items() if k != "issued_at"})).hexdigest()
    doc["contract"] = body
    events.log(session, app_row.id, "orchestrator", "contract_issued",
               f"Bảng chi phí và hợp đồng {body['id']} gửi người vay (đọc tối thiểu {body['read_seconds']} giây)")
    return body


def sign(session: Session, app_row: BuApplication, doc: dict[str, Any], params: dict[str, Any],
         body: dict[str, Any]) -> None:
    """Stage 4 signature → reserve the banks' room → Agent 4 (escrow, payout)."""
    from app.agents import agent4a_payout
    from app.banks import syndicate

    contract = doc.get("contract")
    if not contract or contract.get("selection_at") != (doc.get("selection") or {}).get("at"):
        raise api_error(400, "INVALID_STATE", "Chị cần mở bảng chi phí và hợp đồng của lựa chọn hiện tại trước khi ký.")
    waited = (utcnow() - _parse(contract["issued_at"])).total_seconds()
    if not body.get("read_ack") or waited < int(contract["read_seconds"]):
        raise api_error(400, "READ_TIME", f"Chị cần đọc bảng chi phí ít nhất {contract['read_seconds']} giây và xác "
                                          "nhận đã đọc.", {"waited": int(waited), "need": contract["read_seconds"]})
    if not body.get("use_of_funds_commitment"):
        raise api_error(400, "VALIDATION_ERROR", "Cần cam kết dùng vốn cho kinh doanh.",
                        {"field": "use_of_funds_commitment"})
    account = str(body.get("webank_account") or "").strip()
    if not (account.isdigit() and 6 <= len(account) <= 20):
        raise api_error(400, "VALIDATION_ERROR", "Số tài khoản kinh doanh WeBank gồm 6–20 chữ số.",
                        {"field": "webank_account"})
    payee = dict(contract["payee"])
    if contract["needs"]["supplier_account"]:
        sup = str(body.get("supplier_account") or "").strip()
        if not sup:
            raise api_error(400, "VALIDATION_ERROR", f"Cần số tài khoản của nhà cung cấp {payee['supplier']} cho phần "
                                                     "trả thẳng.", {"field": "supplier_account"})
        payee["supplier_account"] = sup
    if contract["needs"]["guarantee"] and not body.get("guarantee"):
        raise api_error(400, "VALIDATION_ERROR", "Doanh nghiệp cần bảo lãnh của người đại diện theo pháp luật.",
                        {"field": "guarantee"})
    method = body.get("method") or "face"
    if method not in ("face", "otp"):
        raise api_error(400, "VALIDATION_ERROR", "Ký bằng khuôn mặt hoặc mã OTP.", {"field": "method"})
    if other_open_loan(session, app_row):
        raise one_loan_error("Mỗi người vay chỉ có một khoản vay tại một thời điểm.")
    _consent_ok(doc)
    legs = syndicate.reserve_at_signing(session, doc["syndicate"]["split"], int(contract["amount"]))
    contract.update(payee=payee, webank_account=account, legs=legs, sign_method=method,
                    guarantee=bool(body.get("guarantee")), signed_at=utcnow().isoformat() + "Z")
    entry = chain.record(session, app_row.id, "contract_signed", {
        "contract": contract["id"], "hash": contract["hash"], "payee": payee, "amount": contract["amount"],
        "legs": [{k: leg[k] for k in ("bank", "amount", "contract_id")} for leg in legs], "method": method})
    contract["chain_tx"] = entry.tx
    events.log(session, app_row.id, "seller", "contract_signed",
               f"Ký hợp đồng {contract['id']} bằng {'khuôn mặt' if method == 'face' else 'mã OTP'}; hợp đồng từng ngân "
               "hàng: " + ", ".join(f"{leg['name']} {algorithm.fmt_num(leg['amount'])}" for leg in legs),
               hash_=entry.fingerprint)
    doc["payee"] = payee
    advise.store(app_row, doc, "signed")
    # Review item 3: the orchestrator grants Agent 4a one payout for this contract; 4a uses it once.
    agent4a_payout.issue_grant(session, app_row, by="orchestrator")
    agent4a_payout.disburse_or_queue(session, app_row)
