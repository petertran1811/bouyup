"""Agent 1 · Xác minh (loan circle, Stage 1–2): identity, the three consents, the profile and the
store, revenue from tax filings and optional seller statements, credit, FATE; the flag table, fixed
questions and the verification record.

Loan circle rules (docs/BuoyUp loan circle .docx):
- the borrower picks a type: company (working-capital loan, the legal representative guarantees) or
  individual business (online only, at most 200,000 CNY in total);
- one screen, three separate consents, none pre-ticked: credit inquiry by WeBank and the partner
  banks, sharing the application with the listed partner banks, processing face and financial data;
  signed by face, or by an alternative for a borrower who does not want to use the face;
- scoring data only through lawful channels: licensed credit reports, the FATE score the banks train
  together, tax data under consent. Nothing directly from another bank or from the platform;
- optional: revenue and cost statements for 1–6 months from the store's back office, to be
  considered for a higher limit. Agent 1 checks them against the tax filings; a large gap goes to a
  person.

The language model's part (order of tool calls, phrasing a question) is fixed as code here, so every
verdict is a tool output and every flag status change is made by code. Agent 1 never computes money.

Steps 1–2 run at create, 3 at /identity, 4 at /consent, 5–10 at /verify; step 9 continues at
/answers until no question is left.
"""

from __future__ import annotations

import copy
import re
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform.errors import api_error
from app.platform.config import settings
from app.core import algorithm
from app.blockchain import chain
from app.data_sources import consent as consent_mod
from app.platform import events
from app.data_sources import sources
from app.agents import llm_tools
from app.platform.tables import BuApplication, BuLoan
from app.api.views import QUESTION_ALIASES, now_iso, store
from app.blockchain.withdrawals import reference_code

BORROWER_TYPES = {"individual": "Cá nhân", "individual_business": "Hộ kinh doanh", "company": "Doanh nghiệp"}

STEPS = (
    (1, "link", "Kết nối cửa hàng và đọc hồ sơ", "connect_shop · lookup_public_store(url)"),
    (2, "registry", "Tra đăng ký", "lookup_business_registry(reg_no)"),
    (3, "identity", "Định danh", "verify_identity(face, liveness)"),
    (4, "consent", "Ba ô đồng ý", "request_consent(credit, share, data)"),
    (5, "revenue", "Doanh thu theo thuế", "pull_revenue(tax)"),
    (6, "sources", "Tín dụng, FATE, nhà cung cấp", "get_credit_report · get_interbank_score · pull_tax_data · link_entities"),
    (7, "plan", "Kế hoạch và ảnh doanh thu", "kế hoạch vay; verify_statements"),
    (8, "flags", "Tính và gắn cờ", "derive_financials; bảng cờ"),
    (9, "questions", "Xử lý cờ", "câu hỏi chọn sẵn; công cụ kiểm"),
    (10, "conclusion", "Kết luận", "biên bản xác minh; hash lên chuỗi"),
)

QUESTIONS: dict[str, dict[str, Any]] = {
    "RISK_SALES_SPIKE": {"text": "Vì sao doanh số tháng gần nhất tăng mạnh?", "needs": [],
                         "choices": [{"key": "wholesale", "label": "Đơn sỉ cho doanh nghiệp"},
                                     {"key": "promo", "label": "Chạy khuyến mãi"}, {"key": "other", "label": "Khác"}]},
    "RISK_INVENTORY_HIGH": {"text": "Số tồn kho chị khai cao hơn ước tính từ hóa đơn. Chị sửa số hay giữ?",
                            "needs": ["inventory"],
                            "choices": [{"key": "fix", "label": "Sửa số tồn kho", "needs": ["inventory"]},
                                        {"key": "keep", "label": "Giữ nguyên"}]},
    "RISK_SUPPLIER_LINKED": {"text": "Nhà cung cấp này cùng nhóm liên kết với cửa hàng nên bị loại. "
                                     "Chị chọn nhà cung cấp khác (một lần).", "needs": [], "choices": []},
}
GROUP_BY_INDUSTRY = {"thời trang": "quần áo", "tạp hóa": "thực phẩm đóng gói", "điện tử": "điện tử"}


# --- helpers -----------------------------------------------------------------

def _internal(doc: dict[str, Any]) -> dict[str, Any]:
    return doc["internal"]


def _tool(session: Session, app_row: BuApplication, doc: dict[str, Any], name: str,
          inp: dict[str, Any], out: dict[str, Any], simulated: bool = True) -> str:
    internal = _internal(doc)
    internal["tc_seq"] += 1
    tc_id = f"TC-{internal['tc_seq']}"
    doc["verification"]["tool_calls"].append(
        {"id": tc_id, "tool": name, "input": inp, "output": out, "at": now_iso(), "simulated": simulated})
    events.log(session, app_row.id, "agent1", "tool_call", f"{tc_id} · {name}", {"tool_call": tc_id})
    return tc_id


def _step(doc: dict[str, Any], n: int, status: str, summary: str) -> None:
    step = doc["verification"]["steps"][n - 1]
    step["status"], step["summary"] = status, summary


def _flag(doc: dict[str, Any], code: str) -> dict[str, Any] | None:
    return next((f for f in doc["verification"]["flags"] if f["code"] == code), None)


def _params(session: Session) -> dict[str, Any]:
    from app.core.params import active_params

    return active_params(session)


def _fmt(x: float) -> str:
    return algorithm.fmt_num(x)


# --- steps 1–2 (create) ----------------------------------------------------------

def new_doc(scenario_data: dict[str, Any], owner_name: str, borrower_type: str = "individual_business",
            connection: dict[str, Any] | None = None) -> dict[str, Any]:
    """``connection``: the store connection the application is made from (HANDOVER 16.7: platform OAuth or the
    store's registered-phone code); None only where SHOP_CONNECT_REQUIRED is off (``self_declared``)."""
    industry = scenario_data["store"]["industry"]
    return {
        "shop_connection": connection,
        "region": sources.REGION, "currency": sources.CURRENCY,
        "province": scenario_data["store"].get("province", ""),
        "category": GROUP_BY_INDUSTRY.get(industry, "khác"), "borrower_type": borrower_type,
        "requested": None, "stores": [], "identity": None, "consent": None, "plan": None, "statements": None,
        "verification": {"state": "IN_PROGRESS",
                         "steps": [{"n": n, "key": k, "title": t, "tool": tool, "status": "pending", "summary": ""}
                                   for n, k, t, tool in STEPS],
                         "flags": [], "questions": [], "derived": {}, "tool_calls": [], "evidence": None,
                         "record_hash": None, "chain_tx": None, "reason": None},
        "offer": None, "proposal": None, "control": None, "decision": None, "payee": None,
        "syndicate": None, "selection": None, "contract": None,
        "human_request": None, "escalation": None,
        "internal": {"data": scenario_data, "owner_name": owner_name, "tc_seq": 100, "llm_notes": "",
                     "manip": 0, "sheet": None},
    }


def read_store(session: Session, app_row: BuApplication, doc: dict[str, Any],
               urls: list[str], reg_no: str | None) -> None:
    """Steps 1–2: public store page and the national business registry. The borrower type chosen
    at submission must be the one registered (a company cannot apply as an individual business)."""
    data = _internal(doc)["data"]
    s = data["store"]
    conn = doc.get("shop_connection")
    via = conn["verified_via"] if conn else None
    evidence = sources.evidence_levels(data, via, reg_no_typed=not urls)
    doc["verification"]["evidence"] = evidence
    if conn:
        # Step 1 starts from the proof of ownership: who connected which store, and how.
        _tool(session, app_row, doc, "connect_shop", {"platform": conn["platform"], "shop_id": conn["shop_id"]},
              {"connection_id": conn["id"], "verified_via": via, "verified_at": conn["verified_at"],
               "shop_name": conn.get("shop_name"), "phone_masked": conn.get("phone_masked") or None,
               "evidence_level": evidence}, simulated=bool(data.get("sample")))
    proof = {"otp_registered_phone": " · chủ cửa hàng xác minh qua số điện thoại đăng ký",
             "oauth": " · chủ cửa hàng xác minh qua đăng nhập sàn"}.get(via or "", " · chưa xác minh chủ cửa hàng")
    if urls:
        for url in urls:
            out = sources.lookup_public_store(data, url)
            _tool(session, app_row, doc, "lookup_public_store", {"url": url},
                  {**out, "evidence_level": evidence["store"]}, simulated=evidence["store"] != "platform_oauth")
            doc["stores"].append({"url": url, "platform": sources.detect_platform(url) or s["platform"],
                                  "entity": s["entity"], "reg_no": s["reg_no"], "rating": s["rating"],
                                  "category": s["category"], "licenses": list(s["licenses"]),
                                  "province": s.get("province", ""), "opened": s.get("opened"), "registry": None,
                                  "shop_name": (data.get("shop") or {}).get("shop_name"),
                                  "verified_via": via, "connection_id": conn["id"] if conn else None})
        _step(doc, 1, "ok", f"{s['entity']} · {s['reg_no']} · điểm {_fmt(s['rating'])} · "
                            f"{BORROWER_TYPES[doc['borrower_type']]}{proof}")
    else:
        doc["stores"].append({"url": None, "platform": s["platform"], "entity": s["entity"], "reg_no": reg_no,
                              "rating": None, "category": None, "licenses": [], "registry": None,
                              "via": "reg_no", "verified_via": via, "connection_id": conn["id"] if conn else None})
        _step(doc, 1, "warn", f"Người vay nhập số đăng ký; cửa hàng xác nhận qua hồ sơ thuế{proof}")
    reg = sources.lookup_business_registry(data, s["reg_no"])
    _tool(session, app_row, doc, "lookup_business_registry", {"reg_no": s["reg_no"]},
          {**reg, "evidence_level": evidence["registry"]}, simulated=evidence["registry"] != "platform_oauth")
    for st in doc["stores"]:
        st["registry"] = {"status": reg["status"], "registered": reg["registered"], "type": reg.get("type")}
    if doc["borrower_type"] == "individual" and not reg["exists"]:
        # A personal seller with no business registration at all: allowed as an individual borrower.
        _step(doc, 2, "ok", "Vay với tư cách cá nhân · cửa hàng chưa đăng ký kinh doanh · trần cá nhân")
        events.log(session, app_row.id, "agent1", "steps_1_2", "Đọc link: người bán cá nhân chưa đăng ký")
        store(app_row, doc, "draft")
        return
    if not reg["exists"] and doc["borrower_type"] != "individual":
        # 18/10/2026: a store with no business registration at all is a personal seller, not a dissolved
        # entity: say which borrower type fits instead of "thu hồi hoặc giải thể".
        _step(doc, 2, "fail", f"Cửa hàng chưa đăng ký kinh doanh, chọn {BORROWER_TYPES[doc['borrower_type']]} "
                              "→ POL_BORROWER_TYPE")
        _hard(session, app_row, doc, "POL_BORROWER_TYPE", "cửa hàng chưa đăng ký kinh doanh: chỉ vay được với tư "
                                                          "cách Cá nhân")
        return
    if not reg["exists"] or reg["status"] != "active":
        _step(doc, 2, "fail", "Chủ thể không còn hoạt động → POL_ENTITY_INACTIVE")
        _hard(session, app_row, doc, "POL_ENTITY_INACTIVE", "chủ thể bị thu hồi hoặc đã giải thể")
        return
    registered_type = reg.get("type") or "individual_business"
    if doc["borrower_type"] == "individual" and registered_type == "individual_business":
        # A personal seller: the registry entry (when there is one) must be the person's own household
        # business; the loan is personal, with the lower individual cap, and identity is the CCCD check.
        _step(doc, 2, "ok", "Vay với tư cách cá nhân · chủ cửa hàng là người vay · trần cá nhân")
        events.log(session, app_row.id, "agent1", "steps_1_2", "Đọc link và tra đăng ký: vay cá nhân")
        # 18/10/2026: allowed (the product rule of 17/10), but the seller is told plainly why the cap is the
        # individual one and which borrower type the registration supports.
        doc["borrower_type_hint"] = {
            "registered": registered_type, "chosen": "individual",
            "text": "Cửa hàng này đăng ký hộ kinh doanh; bạn đang vay với tư cách Cá nhân nên áp trần cá nhân "
                    f"{algorithm.fmt_num(int(_params(session)['product']['type_cap']['individual']))} tệ. "
                    "Muốn được xét theo trần hộ kinh doanh, hãy nộp lại và chọn Hộ kinh doanh."}
        from app.agents import notify

        notify.push_app_notice(doc, "borrower_type", doc["borrower_type_hint"]["text"], "info", {"view": "apply"})
        store(app_row, doc, "draft")
        return
    if registered_type != doc["borrower_type"]:
        _step(doc, 2, "fail", f"Đăng ký là {BORROWER_TYPES.get(registered_type, registered_type)}, chọn "
                              f"{BORROWER_TYPES[doc['borrower_type']]} → POL_BORROWER_TYPE")
        _hard(session, app_row, doc, "POL_BORROWER_TYPE", "loại người vay không khớp đăng ký")
        return
    reg_date = (date.fromisoformat(reg["registered"]).strftime("%d/%m/%Y") if reg.get("registered")
                else "chưa rõ ngày")  # a store connected through OAuth: the platform may not give the date
    _step(doc, 2, "ok", f"Đang hoạt động · đăng ký {reg_date} · {BORROWER_TYPES[registered_type]}")
    events.log(session, app_row.id, "agent1", "steps_1_2", "Đọc link và tra đăng ký: đạt")
    store(app_row, doc, "draft")


# --- step 3 ----------------------------------------------------------------------

def identify(session: Session, app_row: BuApplication, doc: dict[str, Any],
             face_check: dict[str, Any] | None = None, otp_check: dict[str, Any] | None = None) -> None:
    """``face_check``: the live ArcFace 1:1 re-check against the face registered at sign-up, when there is one.
    ``otp_check``: the seller verified with an SMS OTP instead of the face (no camera, no face model, failed
    scan); the CCCD checks below run the same way."""
    data = _internal(doc)["data"]
    entity = doc["stores"][0]["entity"]
    face = face_check["method"] if face_check else "sms_otp" if otp_check else "liveness"
    card = cccd_checks(doc, data)
    conn = doc.get("shop_connection")
    ownership = ({"verified_via": conn["verified_via"], "connection_id": conn["id"], "verified_at": conn["verified_at"]}
                 if conn else {"verified_via": "self_declared", "accepted": not settings.shop_connect_required})
    # Computed here (18/10/2026): proof of ownership from the store connection, then the CCCD against the
    # store's owner. Nothing about the match is read from the dossier any more.
    result = sources.verify_identity(data, ownership, card)
    evidence = doc["verification"].get("evidence") or {}
    _tool(session, app_row, doc, "verify_identity", {"cccd": "••••", "face": face, "entity": entity,
                                                     "ownership": ownership["verified_via"]},
          {**result, "evidence_level": evidence.get("identity")}, simulated=bool(data.get("sample")))
    if card is not None:
        tc = _tool(session, app_row, doc, "read_cccd", {"engine": card["engine"], "sides": card["sides"]},
                   {k: v for k, v in card.items() if k not in ("id_masked", "id_tail")} | {"id_masked": card["id_masked"]},
                   simulated=False)
        card["tool_call"] = tc
    doc["identity"] = {"cccd": True, "face": otp_check is None, "liveness": otp_check is None,
                       "method": "otp" if otp_check else "face", "result": result,
                       **({"face_check": face_check} if face_check else {}),
                       **({"otp_check": otp_check} if otp_check else {}),
                       **({"card": {k: v for k, v in card.items() if k != "id_tail"}} if card is not None else {})}
    if card is not None and card["under_18"]:
        _step(doc, 3, "fail", "CCCD: người vay chưa đủ 18 tuổi → LAW_ID_MINOR")
        _hard(session, app_row, doc, "LAW_ID_MINOR", "người vay chưa đủ 18 tuổi")
        return
    if card is not None and card["problems"]:
        # Checksum, expiry or a name that differs from the store owner: an officer looks (never auto-approved).
        doc["verification"]["flags"].append({"code": "RISK_ID_REVIEW", "status": "open", "evidence_tool_call": card["tool_call"],
                                             "note": "CCCD cần cán bộ kiểm: " + "; ".join(card["problems"])})
    if result["account_owner_match"] is False:
        doc["verification"]["flags"].append({
            "code": "RISK_ID_REVIEW", "status": "open",
            "note": "Tài khoản quyết toán của cửa hàng không đứng tên chủ thể hoặc chủ cửa hàng"})
    if not (result["face_match"] and result["entity_match"]):
        why = "; ".join(result.get("mismatch") or []) or "người và chủ thể không khớp"
        _step(doc, 3, "fail", f"Người vay không khớp chủ thể của cửa hàng ({why}) → LAW_ID_MISMATCH")
        _hard(session, app_row, doc, "LAW_ID_MISMATCH", why)
        return
    who = "số điện thoại (mã OTP)" if otp_check else "khuôn mặt (người thật)"
    owner = {"otp_registered_phone": "chủ thể (mã gửi số đăng ký cửa hàng)", "oauth": "chủ thể (đăng nhập sàn)"}.get(
        result["ownership"]["verified_via"], "chủ thể (tự khai)")
    _step(doc, 3, "warn" if card and card["problems"] else "ok",
          f"CCCD ↔ {who} ↔ {owner}: khớp" + (f" · CCCD cần kiểm: {', '.join(card['problems'])}"
                                              if card and card["problems"] else
                                              " · CCCD đọc bằng OCR, số hợp lệ" if card else ""))
    events.log(session, app_row.id, "agent1", "identity", "Định danh khớp")
    store(app_row, doc, "identified")


def cccd_checks(doc: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
    """Checks on the OCR'd CCCD (never the image): GB 11643 number and checksum, age ≥ 18, validity
    period not expired, and, when the store owner's registered name is in Chinese, that it matches."""
    scans = doc.get("cccd_scans") or {}
    front = (scans.get("front") or {}).get("fields") or {}
    if not front:
        return None
    back = (scans.get("back") or {}).get("fields") or {}
    number = (front.get("id_number") or {}).get("value") or ""
    checks = front.get("id_number_validation") or {}
    name = (front.get("name") or {}).get("value") or ""
    problems: list[str] = []
    if not checks.get("format_valid"):
        problems.append("số CCCD sai định dạng hoặc mã vùng")
    elif not checks.get("checksum_valid"):
        problems.append("số CCCD sai số kiểm tra")
    birth = checks.get("birth_date") or (front.get("birth_date") or {}).get("value")
    today_ = date.today()
    under_18 = False
    if birth:
        b = date.fromisoformat(birth)
        under_18 = (today_.year - b.year - ((today_.month, today_.day) < (b.month, b.day))) < 18
    period = (back.get("validity_period") or {}).get("value") or ""
    expired = False
    m = re.search(r"[-~至到]\s*((?:19|20)\d{2})[.年/-](\d{1,2})[.月/-](\d{1,2})", period)
    if m:
        expired = date(int(m.group(1)), int(m.group(2)), int(m.group(3))) < today_
    if not back:
        problems.append("chưa chụp mặt sau (hạn hiệu lực)")
    elif expired:
        problems.append("CCCD đã hết hạn")
    # The name and the last four digits are compared with the store's owner at step 3 (sources.verify_identity):
    # a mismatch there is LAW_ID_MISMATCH, not a review flag.
    shop = data.get("shop") or {}
    name_check = sources.compare_card_name(name, [str(shop.get("owner_name") or ""),
                                                  str((data.get("store") or {}).get("entity") or "")])
    warnings = list((scans.get("front") or {}).get("warnings") or []) + list((scans.get("back") or {}).get("warnings") or [])
    return {"engine": (scans.get("front") or {}).get("engine"), "sides": sorted(scans),
            "id_masked": (number[:6] + "••••••••" + number[-4:]) if len(number) == 18 else None,
            "name": name, "birth_date": birth, "under_18": under_18, "validity_period": period or None,
            "expired": expired, "checksum_valid": bool(checks.get("checksum_valid")), "name_check": name_check,
            "id_tail": number[-4:] if len(number) == 18 else None,
            "problems": problems, "ocr_warnings": warnings[:10]}


# --- step 4: three consents ----------------------------------------------------------

def consent(session: Session, app_row: BuApplication, doc: dict[str, Any], document: dict[str, Any],
            signature: dict[str, Any]) -> None:
    """Step 4: anchor the signed consent document (three boxes, each with its text). A renewal
    (after revocation or expiry) replaces the consent but keeps the status and the plan."""
    renew = doc.get("consent") is not None
    boxes = document["scopes"]
    method = signature.get("method", "face")
    payload = {**document, "signature": {k: signature[k] for k in ("alg", "public_key", "sig")},
               "sign_method": method, "simulated_signature": bool(signature.get("simulated")), "renewal": renew}
    entry = chain.record(session, app_row.id, "consent", payload)
    consent_id = document["consent_id"]
    _tool(session, app_row, doc, "request_consent", {"boxes": boxes, "method": method},
          sources.request_consent(consent_id, boxes, entry.tx))
    doc["consent"] = {
        "id": consent_id,
        "scopes": [{"key": k, **consent_mod.BOXES[k]} for k in boxes],
        "accounts": [],
        "sign_method": method,
        "signed_at": document["signed_at"], "expires_at": document["expires_at"], "revoked_at": None,
        "signature": dict(signature), "signed": dict(document),
        "chain_tx": entry.tx, "hash": entry.fingerprint,
    }
    _step(doc, 4, "ok", f"{consent_id} · 3/3 ô · ký bằng {'khuôn mặt' if method == 'face' else 'mã OTP'} "
                        f"· {entry.fingerprint[7:15]}…")
    _internal(doc).pop("consent_draft", None)
    events.log(session, app_row.id, "agent1", "consent",
               f"Ủy quyền {consent_id} {'ký lại ' if renew else ''}đã ghi lên chuỗi", hash_=entry.fingerprint)
    if renew:
        store(app_row, doc)
        return
    suggested = sources.suggested_plan(_internal(doc)["data"])
    doc["plan"] = {"submitted": False, "suggested": suggested}
    store(app_row, doc, "consented")


def revoke_consent(session: Session, app_row: BuApplication, doc: dict[str, Any]) -> None:
    """The borrower withdraws consent (PIPL art. 15): every authorized-data tool and LAW-01 stop
    until a new consent is signed."""
    current = doc.get("consent")
    if not current:
        raise api_error(400, "INVALID_STATE", "Hồ sơ chưa có ủy quyền để rút.")
    if current.get("revoked_at"):
        raise api_error(400, "INVALID_STATE", "Ủy quyền này đã được rút.")
    current["revoked_at"] = now_iso()
    entry = chain.record(session, app_row.id, "consent_revoked",
                         {"consent_id": current["id"], "revoked_at": current["revoked_at"]})
    current["revoked_tx"] = entry.tx
    events.log(session, app_row.id, "seller", "consent_revoked", f"Người vay rút ủy quyền {current['id']}",
               hash_=entry.fingerprint)
    store(app_row, doc)


def require_consent(doc: dict[str, Any]) -> None:
    """Gate before any authorized-data tool (tax, credit report, FATE)."""
    problem = consent_mod.problem(doc.get("consent"), consent_mod.DATA_SCOPES)
    if problem:
        raise api_error(400, "INVALID_STATE", "Ủy quyền đã hết hạn, đã bị rút hoặc chưa đủ ba ô; chị cần ký lại "
                                              "trước khi hệ thống tra dữ liệu.", {"consent": problem})


def set_plan(app_row: BuApplication, doc: dict[str, Any], plan: dict[str, Any],
             statements: list[dict[str, Any]] | None = None) -> None:
    suggested = (doc.get("plan") or {}).get("suggested") or sources.suggested_plan(_internal(doc)["data"])
    doc["plan"] = {**plan, "submitted": True, "suggested": suggested}
    doc["category"] = plan["group"]
    doc["requested"] = round(plan["qty"] * plan["price"])
    doc["statements"] = statements or None
    note = f" · {len(statements)} tháng ảnh doanh thu" if statements else ""
    _step(doc, 7, "ok", f"Kế hoạch: {plan['event']} · {plan['item']} · {_fmt(plan['qty'])} × {_fmt(plan['price'])}{note}")
    store(app_row, doc)


DECLARATION_TEXT = ("Tôi cam đoan các thông tin trong kế hoạch vay, số liệu doanh thu và ảnh chụp tôi tải lên là đúng "
                    "sự thật và do tôi tự kê khai. Tôi hiểu rằng kê khai gian dối để được cấp vốn có thể bị từ chối, "
                    "thu hồi khoản vay trước hạn và chịu trách nhiệm theo pháp luật.")


def record_declaration(session: Session, app_row: BuApplication, doc: dict[str, Any],
                       statements: list[dict[str, Any]] | None, plan: dict[str, Any]) -> None:
    """The "Tôi cam đoan" declaration: its text, time and what it covers go on the chain."""
    images = [i["sha256"] for i in doc.get("statement_images") or []]
    payload = {"text": DECLARATION_TEXT, "at": now_iso(), "plan_item": plan.get("item"),
               "statements_months": [s["month"] for s in statements or []], "statement_images": images}
    entry = chain.record(session, app_row.id, "declaration", payload)
    doc["plan"]["declaration"] = {"text": DECLARATION_TEXT, "at": payload["at"], "chain_tx": entry.tx}
    events.log(session, app_row.id, "seller", "declaration", "Người vay cam đoan thông tin kê khai",
               hash_=entry.fingerprint)
    store(app_row, doc)


# --- steps 5–10 --------------------------------------------------------------------

def network_history(session: Session, seller_user_id: str) -> str:
    """Stage 10: the borrower's own history with BuoyUp: a closed loan never 30 days overdue is
    "good"; any loan that reached 30 days overdue is "bad"; else "none"."""
    loans = list(session.scalars(select(BuLoan).where(BuLoan.seller_user_id == seller_user_id)))
    if any(int((ln.doc or {}).get("max_overdue_days") or 0) >= 30 for ln in loans):
        return "bad"
    if any(ln.status == "closed" for ln in loans):
        return "good"
    return "none"


def borrower_history(session: Session, seller_user_id: str, params: dict[str, Any],
                     tax_monthly_avg: float) -> dict[str, Any]:
    """Seed-loan inputs: good closed loans with BuoyUp and the sales money that reached the WeBank
    business account during them (WeBank's own data, so no other bank is read). The account is
    "confirmed" when it saw ≥ ``seed.min_webank_months`` months averaging ≥ ``seed.min_inflow_share``
    of the tax revenue."""
    loans = list(session.scalars(select(BuLoan).where(BuLoan.seller_user_id == seller_user_id)))
    good = [ln for ln in loans if ln.status == "closed" and int((ln.doc or {}).get("max_overdue_days") or 0) < 30]
    by_month: dict[str, int] = {}
    personal = 0
    for ln in loans:
        account = (ln.doc or {}).get("account") or {}
        for item in account.get("inflows") or []:
            month = str(item.get("on") or "")[:7]
            if month:
                by_month[month] = by_month.get(month, 0) + int(item.get("amount") or 0)
        personal += sum(int(t.get("amount") or 0) for t in account.get("transfers") or [] if t.get("kind") == "personal")
    months = len(by_month)
    avg = round(sum(by_month.values()) / months) if months else 0
    share = round(avg / tax_monthly_avg, 4) if tax_monthly_avg else 0.0
    sp = params["seed"]
    confirmed = months >= int(sp["min_webank_months"]) and share >= float(sp["min_inflow_share"])
    inflow = sum(by_month.values())
    return {"good_loans": len(good), "webank_months": months, "webank_monthly_avg": avg,
            "webank_share_of_tax": share, "webank_confirmed": confirmed,
            "personal_out_share": round(personal / inflow, 4) if inflow else 0.0}


def fate_state(params: dict[str, Any], fate: dict[str, Any]) -> str:
    """``missing`` (no score), ``thin`` (fewer than ``fate.thin_min_banks`` partner banks behind it)
    or ``ok``. An unknown coverage (older FATE service) counts as ``ok``: behaviour as before."""
    if fate.get("value") is None:
        return "missing"
    cov = fate.get("coverage")
    if cov and int(cov["banks"]) < int(params["fate"]["thin_min_banks"]):
        return "thin"
    return "ok"


def fate_alt_signals(data: dict[str, Any]) -> dict[str, Any]:
    """Inputs of the B6 alternative points (all from tax and the registry, already authorized)."""
    rev, tax, reg = data["revenue"], data["tax"], data.get("registry") or {}
    linked = {k for k, v in (data.get("suppliers") or {}).items() if v.get("linked")}
    age = 0
    try:
        as_of, registered = date.fromisoformat(rev["as_of"]), date.fromisoformat(reg["registered"])
        age = (as_of.year - registered.year) * 12 + as_of.month - registered.month
    except (KeyError, TypeError, ValueError):
        pass
    return {"invoice_months_12m": sum(1 for m in rev.get("monthly_12m") or [] if m["amount"] > 0),
            "suppliers_with_history": len([s for s in tax.get("suppliers") or [] if s not in linked]),
            "employees_declared": int(tax.get("employees_declared") or 0), "registry_age_m": max(0, age)}


def run(session: Session, app_row: BuApplication, doc: dict[str, Any], params: dict[str, Any]) -> None:
    require_consent(doc)
    data = _internal(doc)["data"]
    if data.get("sources_connected") is False:
        # A store connected through the platform (not a sample): tax, credit and FATE are not connected yet, so
        # no figure is invented; an officer takes the case (HANDOVER 16.7).
        app_row.status = "verifying"
        _source_gap(session, app_row, doc, ["tax", "credit"], step=5)
        return
    src = sources.ScenarioSources(data)
    app_row.status = "verifying"
    rev = src.pull_revenue()
    _tool(session, app_row, doc, "pull_revenue", {"consent_id": doc["consent"]["id"], "source": "thuế 银税互动"}, rev)
    if rev["months_with_sales"] < params["scope"]["min_inflow_months"]:
        first = date.fromisoformat((rev.get("first_sale_month") or date.today().isoformat()[:7]) + "-01")
        eligible = algorithm.add_months(first, params["scope"]["min_inflow_months"])
        _step(doc, 5, "fail", f"Doanh thu trên thuế mới {rev['months_with_sales']} tháng → POL_OUT_OF_SCOPE")
        _out_of_scope(session, app_row, doc, rev["months_with_sales"], eligible)
        return
    _step(doc, 5, "ok", f"Doanh thu từ {rev.get('first_sale_month')} · {rev['months_with_sales']} tháng · "
                        f"bình quân {_fmt(rev['monthly_avg_12m'])}/tháng · {rev['peak_seasons']} mùa 11.11")

    cid = doc["consent"]["id"]

    def fate_call() -> dict[str, Any]:
        try:
            return sources.fate_source(data).score(doc["consent"],
                                                   reference_code("fate", doc["stores"][0]["reg_no"] or ""))
        except sources.SourceUnavailable as exc:
            return {"value": None, "source": "fate", "error": str(exc)[:200]}

    def guarded(name: str, call: Any) -> Any:
        def run_call() -> dict[str, Any]:
            try:
                return call()
            except sources.SourceUnavailable as exc:
                return {"error": str(exc)[:200], "source": name}
        return run_call

    calls = {"pull_tax_data": guarded("tax", src.pull_tax_data),
             "get_credit_report": guarded("credit", src.get_credit_report),
             "get_interbank_score": fate_call}
    order, order_source = llm_tools.choose_order(list(calls))
    out: dict[str, dict[str, Any]] = {}
    for name in order:
        out[name] = calls[name]()
        _tool(session, app_row, doc, name, {"consent_id": cid}, out[name])
    if order_source == "llm":
        events.log(session, app_row.id, "agent1", "tool_order", "Thứ tự gọi công cụ do mô hình chọn", {"order": order})
    down = [out[n]["source"] for n in ("pull_tax_data", "get_credit_report") if "error" in out[n]]
    if down:
        _source_gap(session, app_row, doc, down)
        return
    tax, credit, fate = out["pull_tax_data"], out["get_credit_report"], out["get_interbank_score"]
    history = network_history(session, app_row.seller_user_id)
    if history != "none":
        credit = {**credit, "network_history": history}
        data["credit"]["network_history"] = history
    fate_missing = fate.get("value") is None
    _internal(doc)["fate_value"] = (int(params["scorecard"]["fate_missing"]) if fate_missing
                                    else int(fate["value"]))
    fstate = fate_state(params, fate)
    _internal(doc)["fate_state"] = fstate
    _internal(doc)["fate_coverage"] = fate.get("coverage")
    if fstate == "thin":
        _internal(doc)["fate_alt"] = fate_alt_signals(data)
    _internal(doc)["history"] = borrower_history(session, app_row.seller_user_id, params,
                                                 float(rev["monthly_avg_12m"]))
    _internal(doc)["record_sources"] = {
        "credit": {"late_12m": credit["late_12m"], "active_npl": bool(credit["active_npl"]),
                   "network_history": credit.get("network_history", "none")},
        "interbank_score": {"value": fate.get("value"), "source": "fallback" if fate_missing else "fate",
                            "run_id": fate.get("run_id"), "coverage": fate.get("coverage"), "state": fstate},
    }
    plan = doc.get("plan")
    suppliers = sorted(set(tax["suppliers"]) | ({plan["supplier"]} if plan and plan.get("supplier") else set()))
    links = sources.link_entities(data, suppliers)
    _tool(session, app_row, doc, "link_entities", {"seller": doc["stores"][0]["entity"], "suppliers": suppliers}, links)
    _step(doc, 6, "warn" if fate_missing else "ok",
          ("Chưa có hóa đơn mua vào cho mặt hàng" if tax["invoice_unit_price_3m"] is None
           else f"Giá nhập 3 tháng {_fmt(tax['invoice_unit_price_3m'])} tệ") + " · biên lãi gộp "
          f"{round(tax['gross_margin'] * 100)}% · trễ hạn {credit['late_12m']} · "
          + ("FATE chưa trả điểm" if fate_missing else f"FATE {fate['value']}"
             + (" (tín hiệu mỏng: chấm điểm thay thế)" if fstate == "thin" else ""))
          + ("" if history == "none" else f" · lịch sử với BuoyUp: {'tốt' if history == 'good' else 'từng quá hạn'}"))
    if credit["active_npl"]:
        _hard(session, app_row, doc, "POL_ACTIVE_NPL", "đang có nợ xấu")
        return

    statements = doc.get("statements")
    st_result = None
    if statements:
        st_result = sources.verify_statements(data, statements, params)
        tc = _tool(session, app_row, doc, "verify_statements", {"months": [s["month"] for s in statements]}, st_result)
        st_result = {**st_result, "tool_call": tc}
        _internal(doc)["statements_verified"] = st_result["verdict"] == "verified"
        images = doc.get("statement_images") or []
        if (_internal(doc)["statements_verified"] and not images
                and params["revenue"].get("bonus_requires_images", False)):
            _internal(doc)["statements_verified"] = False
            doc["verification"]["flags"].append({
                "code": "DATA_STATEMENT_UNUSED", "status": "resolved_by_check", "evidence_tool_call": tc,
                "note": "Số doanh thu tự khai không kèm ảnh chụp: không dùng để nâng hạn mức"})
        if images:
            # Screenshots uploaded (review 17/10/2026): the typed monthly revenue should appear on them.
            seen = {n for i in images for n in i.get("numbers") or []}
            read = any(i.get("ocr_read") for i in images)
            found = [s["month"] for s in statements if int(s["revenue"]) in seen]
            check = {"images": len(images), "ocr_read": read, "months_found": found,
                     "months_typed": [s["month"] for s in statements],
                     "supported": read and len(found) * 2 >= len(statements)}
            itc = _tool(session, app_row, doc, "check_statement_images",
                        {"images": [i["sha256"][:12] for i in images]}, check)
            st_result["images"] = check
            if read and not check["supported"] and _internal(doc)["statements_verified"]:
                _internal(doc)["statements_verified"] = False  # no bonus on figures the screenshots do not show
                doc["verification"]["flags"].append({
                    "code": "DATA_STATEMENT_UNUSED", "status": "resolved_by_check", "evidence_tool_call": itc,
                    "note": "Số doanh thu đã nhập không thấy trên ảnh chụp: không dùng để nâng hạn mức"})
    derived = sources.derive_financials(data)
    _tool(session, app_row, doc, "derive_financials", {}, derived)
    doc["verification"]["derived"] = {
        "first_sale_month": rev.get("first_sale_month"), "months": rev["months_with_sales"],
        "monthly_avg_12m": rev["monthly_avg_12m"], "growth_3m": rev["growth_3m"], "peak_seasons": rev["peak_seasons"],
        "last_peak": rev.get("last_peak"), "spike_ratio": rev["spike_ratio"],
        "invoice_unit_price_3m": tax["invoice_unit_price_3m"], "gross_margin": tax["gross_margin"],
        "interbank_score": fate["value"], "interbank_state": fstate, "late_12m": credit["late_12m"],
        "history": _internal(doc)["history"],
        "statements": {k: st_result[k] for k in ("verdict", "deviation", "months")} if st_result else None,
    }
    _apply_flag_table(session, app_row, doc, params, rev, tax, links, plan, st_result)
    opened = now_iso()
    for f in doc["verification"]["flags"]:
        f.setdefault("opened_at", opened)  # the open_days clock of step 10 starts here
    if fate_missing:
        # Never closes: the case can still be offered but never auto-approved (RISK-02).
        doc["verification"]["flags"].append({"code": "DATA_PARTNER_MISSING", "status": "explained_unverified",
                                             "note": "FATE không trả điểm liên ngân hàng; tính như mức rủi ro cao nhất"})
    elif fstate == "thin":
        # Closed by the check itself: B6 scores the alternative signals and B8 adds the lower cap.
        cov = fate.get("coverage") or {}
        tc = _tool(session, app_row, doc, "check_fate_coverage", {"min_banks": params["fate"]["thin_min_banks"]},
                   {"coverage": cov, "state": "thin", "alt_signals": _internal(doc).get("fate_alt")})
        doc["verification"]["flags"].append({
            "code": "DATA_FATE_THIN", "status": "resolved_by_check", "opened_at": opened, "evidence_tool_call": tc,
            "note": f"FATE dựa trên {cov.get('banks', 0)}/3 ngân hàng: chấm điểm thay thế, trần hạn mức thấp hơn"})
    hist = _internal(doc)["history"]
    if hist["good_loans"] > 0:
        hist_tc = _tool(session, app_row, doc, "check_webank_inflows",
                        {"min_months": params["seed"]["min_webank_months"],
                         "min_share": params["seed"]["min_inflow_share"]}, hist)
    if hist["good_loans"] > 0 and not hist["webank_confirmed"]:
        # Item 6: from the second loan, the WeBank account must show the sales money the tax figures claim.
        doc["verification"]["flags"].append({
            "code": "RISK_INFLOW_GAP", "status": "resolved_by_check", "opened_at": opened, "evidence_tool_call": hist_tc,
            "note": f"Tiền bán hàng về TK WeBank {hist['webank_months']} tháng, bình quân "
                    f"{round(hist['webank_share_of_tax'] * 100)}% doanh thu thuế: giữ hệ số khoản vay mồi"})
    if hist["good_loans"] > 0 and hist["personal_out_share"] > float(params["flags"]["pass_share"]):
        # Sales money passed straight on to personal accounts: a person looks (open → officer).
        doc["verification"]["flags"].append({
            "code": "RISK_PASS_THROUGH", "status": "open", "opened_at": opened, "evidence_tool_call": hist_tc,
            "note": f"{round(hist['personal_out_share'] * 100)}% tiền về TK WeBank chuyển tiếp sang tài khoản cá nhân"})
    visible = [f["code"] for f in doc["verification"]["flags"]]
    _step(doc, 8, "ok", "Cờ: " + (", ".join(visible) if visible else "không có cờ cần báo"))
    events.log(session, app_row.id, "agent1", "flags", "Áp bảng cờ",
               {"flags": visible, "hidden_from_seller": True})
    _next(session, app_row, doc, params)


def _apply_flag_table(session: Session, app_row: BuApplication, doc: dict[str, Any], params: dict[str, Any],
                      rev: dict[str, Any], tax: dict[str, Any], links: dict[str, Any],
                      plan: dict[str, Any] | None, statements: dict[str, Any] | None) -> None:
    """Code turns flags on; only tools close them."""
    fp = params["flags"]
    flags = doc["verification"]["flags"]
    if rev["spike_ratio"] > fp["spike_mult"]:
        flags.append({"code": "RISK_SALES_SPIKE", "status": "open", "note": "Doanh thu tháng gần nhất tăng đột biến"})
    if statements and statements["verdict"] == "mismatch":
        # Suspected fraud in the store screenshots: a person looks again (loan circle, Stage 2).
        flags.append({"code": "RISK_STATEMENT_MISMATCH", "status": "open", "evidence_tool_call": statements["tool_call"],
                      "note": f"Ảnh doanh thu lệch {round(statements['deviation'] * 100)}% so với hóa đơn thuế"})
    elif statements and statements["verdict"] == "unverified":
        flags.append({"code": "DATA_STATEMENT_UNUSED", "status": "resolved_by_check",
                      "evidence_tool_call": statements["tool_call"],
                      "note": "Ảnh doanh thu lệch thuế vừa phải: không dùng để nâng hạn mức"})
    if plan is None or not plan.get("submitted"):
        return
    invoice = tax["invoice_unit_price_3m"]
    if invoice is None:
        flags.append({"code": "DATA_SOURCE_GAP", "status": "explained_unverified",
                      "note": "Không có hóa đơn mua vào cho mặt hàng; B3 dùng giá khai trừ hệ số"})
    elif plan["price"] > params["price"]["deviation_flag"] * invoice:
        tc = _tool(session, app_row, doc, "compare_price", {"declared": plan["price"], "invoice": invoice},
                   {"ratio": round(plan["price"] / invoice, 4), "unit_price_used": invoice})
        flags.append({"code": "RISK_PRICE_DEVIATION", "status": "resolved_by_check", "evidence_tool_call": tc,
                      "note": "Tự đóng: B3 dùng giá hóa đơn"})
    if plan["inventory"] > fp["inventory_mult"] * tax["inventory_estimate"]:
        flags.append({"code": "RISK_INVENTORY_HIGH", "status": "open", "note": "Tồn kho khai cao hơn ước tính"})
    if plan.get("supplier") and plan["supplier"] in links["linked"]:
        flags.append({"code": "RISK_SUPPLIER_LINKED", "status": "open",
                      "note": "Nhà cung cấp cùng nhóm liên kết với cửa hàng"})


def _questions(doc: dict[str, Any]) -> list[dict[str, Any]]:
    data = _internal(doc)["data"]
    out = []
    for f in doc["verification"]["flags"]:
        if f["status"] != "open" or f["code"] not in QUESTIONS:
            continue
        q = copy.deepcopy(QUESTIONS[f["code"]])
        if f["code"] == "RISK_SUPPLIER_LINKED":
            if f.get("retried"):
                continue
            q["choices"] = [{"key": k, "label": f"{k} · {v['name']}"} for k, v in data["suppliers"].items()
                            if not v["linked"]]
        out.append({"flag": f["code"], **q})
    return out


def _next(session: Session, app_row: BuApplication, doc: dict[str, Any], params: dict[str, Any]) -> None:
    questions = _questions(doc)
    texts = _internal(doc).setdefault("question_text", {})
    for q in questions:
        if q["flag"] not in texts:
            texts[q["flag"]] = llm_tools.rephrase(q["text"])
        if texts[q["flag"]]:
            q["text"], q["text_source"] = texts[q["flag"]], "llm"
    doc["verification"]["questions"] = questions
    if questions:
        _step(doc, 9, "warn", f"Còn {len(questions)} câu hỏi cần chị trả lời")
        events.log(session, app_row.id, "agent1", "question", "Agent 1 hỏi người vay theo câu chọn sẵn")
        store(app_row, doc, "needs_answer")
        return
    flags = doc["verification"]["flags"]
    _step(doc, 9, "ok", "Không còn câu hỏi" if flags else "Không có cờ cần hỏi")
    if any(f["status"] == "open" for f in flags):
        conclude(session, app_row, doc, "ESCALATED")
        why = next(f["code"] for f in flags if f["status"] == "open")
        doc["escalation"] = {"why": why, "at": now_iso()}
        store(app_row, doc, "escalated")
        return
    conclude(session, app_row, doc, "VERIFIED")
    store(app_row, doc, "verified")
    from app.agents import agent2_advise as advise

    advise.make_offer(session, app_row, doc, params)


# --- step 9: answers ----------------------------------------------------------------

def answer(session: Session, app_row: BuApplication, doc: dict[str, Any], params: dict[str, Any],
           body: dict[str, Any]) -> None:
    code = {v: k for k, v in QUESTION_ALIASES.items()}.get(body["flag"], body["flag"])
    flag = _flag(doc, code)
    open_q = {q["flag"]: q for q in _questions(doc)}
    if flag is None or code not in open_q:
        raise api_error(400, "VALIDATION_ERROR", "Không có câu hỏi nào cho cờ này.", {"field": "flag"})
    require_consent(doc)
    choice = body.get("choice")
    if choice not in {c["key"] for c in open_q[code]["choices"]}:
        raise api_error(400, "VALIDATION_ERROR", "Lựa chọn không có trong danh sách.", {"field": "choice"})
    _HANDLERS[code](session, app_row, doc, params, flag, choice, body)
    events.log(session, app_row.id, "seller", "answer", "Người vay trả lời câu hỏi xác minh")
    _next(session, app_row, doc, params)


def _need(body: dict[str, Any], key: str) -> Any:
    if body.get(key) in (None, "", {}):
        raise api_error(400, "VALIDATION_ERROR", "Cần bổ sung thông tin cho lựa chọn này.", {"field": key})
    return body[key]


def _answer_sales_spike(session: Session, app_row: BuApplication, doc: dict[str, Any], params: dict[str, Any],
                        flag: dict[str, Any], choice: str, body: dict[str, Any]) -> None:
    if choice == "wholesale":
        out = sources.pull_tax_data(_internal(doc)["data"], "b2b_sales")
        tc = _tool(session, app_row, doc, "pull_tax_data", {"query": "hóa đơn bán ra cho doanh nghiệp"}, out)
        if out["explains_spike"]:
            flag.update(status="resolved_by_check", evidence_tool_call=tc, note="Hóa đơn sỉ giải thích phần tăng")
            return
    flag.update(status="explained_unverified", note="Không công cụ nào kiểm được phần tăng")


def _answer_inventory(session: Session, app_row: BuApplication, doc: dict[str, Any], params: dict[str, Any],
                      flag: dict[str, Any], choice: str, body: dict[str, Any]) -> None:
    if choice == "keep":
        flag.update(status="explained_unverified", note="Giữ số khai; cần ảnh kho hoặc phiếu nhập")
        return
    value = _need(body, "inventory")
    if not isinstance(value, int) or value < 0:
        raise api_error(400, "VALIDATION_ERROR", "Tồn kho phải là số nguyên không âm.", {"field": "inventory"})
    doc["plan"]["inventory"] = value
    est = _internal(doc)["data"]["tax"]["inventory_estimate"]
    tc = _tool(session, app_row, doc, "derive_financials", {"inventory": value}, {"inventory_estimate": est})
    if value <= params["flags"]["inventory_mult"] * est:
        flag.update(status="resolved_by_check", evidence_tool_call=tc, note="Đã sửa tồn kho")


def _answer_supplier(session: Session, app_row: BuApplication, doc: dict[str, Any], params: dict[str, Any],
                     flag: dict[str, Any], choice: str, body: dict[str, Any]) -> None:
    out = sources.link_entities(_internal(doc)["data"], [choice])
    tc = _tool(session, app_row, doc, "link_entities", {"supplier": choice}, out)
    flag["retried"] = True
    if not out["linked"]:
        doc["plan"]["supplier"] = choice
        flag.update(status="resolved_by_check", evidence_tool_call=tc, note="Đã chọn nhà cung cấp khác")


_HANDLERS = {"RISK_SALES_SPIKE": _answer_sales_spike, "RISK_INVENTORY_HIGH": _answer_inventory,
             "RISK_SUPPLIER_LINKED": _answer_supplier}


# --- step 10 -------------------------------------------------------------------------

_HARD_REASONS = {
    "LAW_ID_MINOR": lambda doc: {
        "law": "Bộ luật Dân sự Trung Quốc, Điều 18 (năng lực hành vi dân sự đầy đủ từ 18 tuổi)",
        "factor": "Theo ngày sinh trên CCCD, người vay chưa đủ 18 tuổi.",
        "fix": "Người vay cần đủ 18 tuổi; người đại diện theo pháp luật có thể nộp hồ sơ."},
    "LAW_ID_MISMATCH": lambda doc: {
        "law": "Quy định định danh khách hàng (Luật Chống rửa tiền 2024, Điều 29)",
        "factor": f"Chủ thể của cửa hàng ({doc['stores'][0]['entity']}) không khớp với người vay: "
                  + ("; ".join(((doc.get("identity") or {}).get("result") or {}).get("mismatch") or [])
                     or "người quét CCCD không phải chủ cửa hàng") + ".",
        "fix": "Kết nối cửa hàng do chính bạn đăng ký và dùng CCCD của chính chủ cửa hàng."},
    "POL_ENTITY_INACTIVE": lambda doc: {
        "law": "Điều kiện phục vụ: chủ thể phải đang hoạt động trên hệ thống đăng ký doanh nghiệp",
        "factor": "Chủ thể kinh doanh đã bị thu hồi hoặc giải thể.",
        "fix": "Dùng cửa hàng của chủ thể đang hoạt động, hoặc khôi phục đăng ký rồi nộp lại."},
    "POL_BORROWER_TYPE": lambda doc: _borrower_type_reason(doc),
    "POL_ACTIVE_NPL": lambda doc: {
        "law": "Chính sách tín dụng: không cho vay khi đang có nợ xấu",
        "factor": "Báo cáo tín dụng ghi nhận một khoản nợ xấu chưa tất toán.",
        "fix": "Tất toán khoản nợ xấu rồi nộp lại hồ sơ."},
}


def _borrower_type_reason(doc: dict[str, Any]) -> dict[str, str]:
    """POL_BORROWER_TYPE in words the seller can act on: what the store is registered as and what to pick."""
    reg = ((doc.get("stores") or [{}])[0] or {}).get("registry") or {}
    chosen = BORROWER_TYPES.get(str(doc.get("borrower_type")), str(doc.get("borrower_type")))
    if reg.get("status") in (None, "none") or not reg.get("registered"):
        registered, fits = "chưa đăng ký kinh doanh", "Cá nhân"
    else:
        fits = BORROWER_TYPES.get(str(reg.get("type") or "individual_business"), "Hộ kinh doanh")
        registered = f"đăng ký {fits.lower()}"
    return {"law": "Điều kiện sản phẩm: loại người vay theo đăng ký kinh doanh",
            "factor": f"Cửa hàng này {registered}; bạn đã chọn vay với tư cách {chosen}.",
            "fix": f"Nộp lại hồ sơ và chọn tư cách {fits}."}


def _hard(session: Session, app_row: BuApplication, doc: dict[str, Any], code: str, note: str) -> None:
    doc["verification"]["flags"].append({"code": code, "status": "hard", "note": note})
    doc["verification"]["reason"] = _HARD_REASONS[code](doc)
    conclude(session, app_row, doc, "REJECTED")
    store(app_row, doc, "rejected")


def _source_gap(session: Session, app_row: BuApplication, doc: dict[str, Any], down: list[str], step: int = 6) -> None:
    names = {"tax": "thuế (银税互动)", "credit": "báo cáo tín dụng"}
    note = "Nguồn không trả lời: " + ", ".join(names.get(d, d) for d in down)
    doc["verification"]["flags"].append({"code": "DATA_SOURCE_GAP", "status": "open", "note": note,
                                         "sources": down})
    _step(doc, step, "fail", f"{note} → chuyển cán bộ")
    events.log(session, app_row.id, "agent1", "source_unavailable", note, {"sources": down})
    conclude(session, app_row, doc, "ESCALATED")
    doc["escalation"] = {"why": "DATA_SOURCE_GAP", "at": now_iso()}
    store(app_row, doc, "escalated")


def _out_of_scope(session: Session, app_row: BuApplication, doc: dict[str, Any], months: int,
                  eligible: date | None) -> None:
    doc["verification"]["flags"].append({"code": "POL_OUT_OF_SCOPE", "status": "hard",
                                         "note": "lịch sử doanh thu chưa đủ thời gian"})
    doc["verification"]["reason"] = {
        "law": "Phạm vi phục vụ của BuoyUp",
        "factor": f"Hồ sơ thuế mới ghi nhận doanh thu {months} tháng; BuoyUp cần đủ 12 tháng để đánh giá khả "
                  "năng trả qua ít nhất một mùa cao điểm.",
        "fix": f"Chị có thể nộp lại từ {eligible:%d/%m/%Y}." if eligible else "Chị có thể nộp lại khi đủ 12 tháng."}
    doc["verification"]["eligible_from"] = eligible.isoformat() if eligible else None
    conclude(session, app_row, doc, "OUT_OF_SCOPE")
    store(app_row, doc, "out_of_scope")


def conclude(session: Session, app_row: BuApplication, doc: dict[str, Any], state: str) -> None:
    v = doc["verification"]
    internal = _internal(doc)
    notes = sources.notes_for(internal["data"])
    extra = llm_tools.write_notes({"state": state, "derived": v["derived"],
                                   "flags": [{k: f.get(k) for k in ("code", "status", "note")} for f in v["flags"]]})
    internal["llm_notes"] = f"{notes} {extra}".strip() if extra else notes
    internal["notes_source"] = "llm" if extra else "code"
    internal["notes_code"] = notes  # the part written by code from the tool results (demo sample guard)
    # Recorded, never stripped: RISK-06 (Agent 3) reads both the text and this record.
    internal["notes_scan"] = llm_tools.scan_injection(internal["llm_notes"])
    if internal["notes_scan"]:
        events.log(session, app_row.id, "agent1", "notes_injection",
                   "Ghi chú có lời nhắm vào kiểm soát (ghi nhận, không xóa)",
                   {"phrases": internal["notes_scan"], "hidden_from_seller": True})
    plan = doc.get("plan")
    record = {
        "application_id": app_row.code, "borrower_type": doc.get("borrower_type"),
        "scope": "out" if state == "OUT_OF_SCOPE" else "in",
        "consent_id": (doc.get("consent") or {}).get("id"), "stores": doc["stores"],
        "identity": (doc.get("identity") or {}).get("result"), "derived": v["derived"],
        # How far each source is checked (HANDOVER 16.7) and the store connection the case was made from.
        "evidence_level": v.get("evidence"), "shop_connection": doc.get("shop_connection"),
        **(internal.get("record_sources") or {"credit": None, "interbank_score": None}),
        "plan": {k: plan[k] for k in plan if k not in ("suggested", "submitted")} if plan and plan.get("submitted") else None,
        "flags": [{k: f[k] for k in ("code", "status", "evidence_tool_call", "penalty") if k in f} for f in v["flags"]],
        "statements": [s["month"] for s in doc.get("statements") or []], "state": state,
        "llm_notes": internal["llm_notes"],
    }
    entry = chain.record(session, app_row.id, "verification", record)
    v.update(state=state, record_hash=entry.fingerprint, chain_tx=entry.tx, questions=[])
    _step(doc, 10, "ok" if state == "VERIFIED" else "fail", f"{state} · {entry.fingerprint[7:15]}…")
    events.log(session, app_row.id, "agent1", "conclusion", f"Biên bản xác minh {state}", hash_=entry.fingerprint)


def escalate_overdue(session: Session, params: dict[str, Any], as_of: date) -> list[str]:
    """Step 10 for silent borrowers: an application waiting on an answer for more than
    ``flags.open_days`` days since its oldest open flag is concluded ESCALATED."""
    cutoff = as_of - timedelta(days=int(params["flags"]["open_days"]))
    moved: list[str] = []
    for app_row in session.scalars(select(BuApplication).where(BuApplication.status == "needs_answer")):
        opened = [date.fromisoformat(f["opened_at"][:10]) for f in (app_row.doc or {}).get("verification", {})
                  .get("flags", []) if f.get("status") == "open" and f.get("opened_at")]
        since = min(opened) if opened else app_row.updated_at.date()
        if since >= cutoff:
            continue
        doc = copy.deepcopy(app_row.doc)
        why = next((f["code"] for f in doc["verification"]["flags"] if f["status"] == "open"), "RISK-01")
        conclude(session, app_row, doc, "ESCALATED")
        doc["escalation"] = {"why": why, "at": now_iso(), "auto": True}
        events.log(session, app_row.id, "agent1", "auto_escalate",
                   f"Quá {params['flags']['open_days']} ngày chưa trả lời: chuyển cán bộ", {"why": why})
        store(app_row, doc, "escalated")
        moved.append(app_row.id)
    return moved
