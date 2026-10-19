"""/v4/applications: the seller's loan application, Agents 1–3 and the gate (contract section 3).

Only this layer commits. Sellers act on their own applications; officers and
admins may read every application; the bank role has no access here.
"""

from __future__ import annotations

import copy
import secrets
import threading
import unicodedata
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.platform.errors import api_error
from app.data_sources import consent as consent_mod
from app.data_sources import sources
from app.api import face as face_api
from app.api.auth import _recent, _reserve
from app.api import views
from app.blockchain import chain
from app.platform import events
from app.agents import agent2_advise as advise
from app.agents import agent3_control as control
from app.agents import agent1_verify as verify
from app.agents import contract as contract_mod
from app.core.params import active_params
from app.platform.security import require_roles
from app.platform.tables import BuApplication, BuRateEvent, BuUser
from app.platform.config import settings
from app.platform.db.session import get_session
from app.platform.db.tables import utcnow

router = APIRouter(prefix="/applications", tags=["v4-applications"])

_readers = require_roles("seller", "officer", "admin")
_sellers = require_roles("seller")

SCOPE_KEYS = consent_mod.CONSENT_BOXES


class CreateIn(BaseModel):
    tier: Literal[1, 2] = 2
    borrower_type: Literal["individual", "individual_business", "company"] = "individual_business"
    # HANDOVER 16.7: the store the seller connected (POST /v4/shops/connect/...). store_urls / reg_no name a
    # sample store (dev/demo/test) and still need that store's connection unless SHOP_CONNECT_REQUIRED=false.
    shop_connection_id: str | None = Field(default=None, max_length=40)
    store_urls: list[str] = Field(default_factory=list, max_length=5)
    reg_no: str | None = Field(default=None, max_length=40)


class IdentityIn(BaseModel):
    cccd: bool
    face: bool = False
    # A passed /v4/face/verify re-check; required when the account registered a face at sign-up,
    # unless the seller verified with an SMS OTP instead (no camera, no face model, failed scan).
    face_verify_id: str | None = Field(default=None, max_length=64)
    # TODO(SMS): checked in the browser today; with an SMS provider this becomes a server proof
    # from POST /v4/otp/verify (API_CONTRACT_V4.md §1b).
    otp_verified: bool = False
    otp_phone: str = Field(default="", max_length=40)  # masked, e.g. "•••• 678"


class SignerCheck(BaseModel):
    """How the seller proved it is them right before signing (optional; recorded in the events)."""
    face_verify_id: str | None = Field(default=None, max_length=64)
    otp_verified: bool = False


class SignatureIn(BaseModel):
    alg: Literal["ed25519"]
    public_key: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    sig: str = Field(pattern=r"^[0-9a-fA-F]{128}$")


class ConsentIn(SignerCheck):
    """The three separate boxes (none pre-ticked), each one ticked, and how the borrower signs."""
    scopes: list[str] = Field(min_length=1, max_length=10)
    method: Literal["face", "otp"] = "face"
    signature: SignatureIn | None = None


class StatementIn(BaseModel):
    """One month of the borrower's own revenue statement (optional, up to 6 months)."""
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    revenue: int = Field(ge=0, le=1_000_000_000)
    cost: int = Field(default=0, ge=0, le=1_000_000_000)


class PlanIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event: str = Field(min_length=1, max_length=40)
    item: str = Field(min_length=1, max_length=120)
    group: Literal[sources.GOODS_GROUPS]  # type: ignore[valid-type]
    # The "khác" (other goods) description; also read for prohibited or licensed goods.
    group_other: str = Field(default="", max_length=120)
    # Review 17/10/2026: the plan no longer asks for a brand or a supplier (kept optional for older clients).
    brand: str = Field(default="", max_length=80)
    auth: str = Field(default="", max_length=60)
    flavor: str | None = Field(default=None, max_length=40)
    self_fill: bool = False
    qty: int = Field(gt=0, le=10_000_000)
    price: float = Field(gt=0, le=1_000_000)
    supplier: str = Field(default="", max_length=40)
    inventory: int = Field(ge=0, le=1_000_000_000)
    own_capital: int = Field(ge=0, le=1_000_000_000)
    other_loans: int = Field(default=0, ge=0, le=1_000_000_000)
    statements: list[StatementIn] | None = Field(default=None, max_length=6)
    # "Tôi cam đoan …": the borrower declares the plan, the figures and the screenshots are true.
    declaration: bool = False


class AnswerIn(BaseModel):
    flag: str = Field(min_length=1, max_length=40)
    choice: str = Field(min_length=1, max_length=40)
    account: dict[str, Any] | None = None
    inventory: int | None = None
    store_url: str | None = Field(default=None, max_length=500)


class WhatIfIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    own_capital: int | None = Field(default=None, ge=0, le=1_000_000_000)
    inventory: int | None = Field(default=None, ge=0, le=1_000_000_000)
    qty: int | None = Field(default=None, gt=0, le=10_000_000)
    supplier: str | None = Field(default=None, min_length=1, max_length=40)


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ChoiceIn(BaseModel):
    """Stage 3: the borrower's choice within the approved limit."""
    amount: int = Field(gt=0, le=100_000_000)
    # None: the system's tenor (the longest of the borrower type; the borrower does not pick it).
    tenor_m: int | None = Field(default=None, gt=0, le=60)
    method: Literal["installment", "revenue"] = "installment"
    due_day: int = Field(default=10, ge=1, le=28)


class QuoteIn(BaseModel):
    amount: int = Field(gt=0, le=100_000_000)
    tenor_m: int | None = Field(default=None, gt=0, le=60)
    method: Literal["installment", "revenue"] = "installment"
    due_day: int = Field(default=10, ge=1, le=28)


class SignIn(SignerCheck):
    read_ack: bool
    webank_account: str = Field(min_length=6, max_length=20)
    use_of_funds_commitment: bool
    supplier_account: str | None = Field(default=None, max_length=40)
    guarantee: bool = False
    method: Literal["face", "otp"] = "face"


class HumanIn(BaseModel):
    reason: str = Field(default="", max_length=500)


# --- helpers ---------------------------------------------------------------------

def load(session: Session, app_id: str, user: BuUser) -> BuApplication:
    app_row = session.get(BuApplication, app_id)
    if app_row is None:
        raise api_error(404, "NOT_FOUND", "Không tìm thấy hồ sơ.")
    if user.role == "seller" and app_row.seller_user_id != user.id:
        raise api_error(403, "FORBIDDEN", "Bạn không có quyền xem hồ sơ này.")
    if user.role == "seller" and app_row.status == "withdrawn":
        raise api_error(404, "NOT_FOUND", "Hồ sơ đã được xóa.")
    return app_row


def _own(session: Session, app_id: str, user: BuUser) -> tuple[BuApplication, dict[str, Any]]:
    app_row = load(session, app_id, user)
    return app_row, copy.deepcopy(app_row.doc)


def _require(app_row: BuApplication, *statuses: str) -> None:
    if app_row.status not in statuses:
        raise api_error(400, "INVALID_STATE", "Thao tác không hợp lệ ở trạng thái hiện tại của hồ sơ.",
                        {"status": app_row.status, "allowed": list(statuses)})


def out(session: Session, app_row: BuApplication, viewer: BuUser) -> dict[str, Any]:
    return views.application_view(app_row, session.get(BuUser, app_row.seller_user_id), viewer,
                                  int(active_params(session)["complaint"]["review_days"]))


def _new_code(session: Session) -> str:
    prefix = "APP-" + utcnow().strftime("%Y-%m%d") + "-"
    n = session.scalar(select(func.count()).select_from(BuApplication)
                       .where(BuApplication.code.like(prefix + "%"))) or 0
    return f"{prefix}{n + 1:04d}"


def _done(session: Session, app_row: BuApplication, user: BuUser) -> dict[str, Any]:
    session.commit()
    return out(session, app_row, user)


# --- endpoints ------------------------------------------------------------------------

@router.post("", status_code=201)
def create(body: CreateIn, user: BuUser = Depends(_sellers), session: Session = Depends(get_session)) -> dict:
    from app.api import shops

    urls = [u.strip() for u in body.store_urls if u.strip()]
    reg_no = (body.reg_no or "").strip().upper()
    connection = None
    if body.shop_connection_id:
        connection = shops.usable_connection(session, user, body.shop_connection_id)
        scenario, data = shops.data_for(connection)
        urls = [connection.url] if connection.url else []
        reg_no = ""
    elif not urls and not reg_no:
        raise api_error(400, "VALIDATION_ERROR", "Kết nối cửa hàng, dán link cửa hàng hoặc nhập số đăng ký.",
                        {"field": "store_urls", "fallback": "reg_no"})
    else:
        # A sample store named by its link or registration number. Unknown stores: SHOP_NOT_CONNECTED, no
        # dossier is made up for them (the copy of chị Lan's case for any link is gone).
        scenario, data = sources.resolve_store(urls[0]) if urls else sources.resolve_reg_no(reg_no)
        if settings.shop_connect_required:
            connection = shops.connection_for_sample(session, user, scenario)
            if connection is None:
                raise api_error(400, "SHOP_NOT_CONNECTED", "Cần xác nhận bạn là chủ cửa hàng này trước khi tạo hồ sơ: "
                                                           "kết nối cửa hàng bằng mã gửi tới số điện thoại đăng ký "
                                                           "của cửa hàng.",
                                {"field": "store_urls", "connect": True, "url": (urls or [""])[0][:300],
                                 "reg_no": reg_no})
    for extra in urls[1:]:
        key = sources.resolve_store(extra)[0]
        if settings.shop_connect_required and shops.connection_for_sample(session, user, key) is None:
            raise sources.not_connected(url=extra)
    now = utcnow()
    app_row = BuApplication(id="app_" + secrets.token_hex(8), code=_new_code(session),
                            seller_user_id=user.id, status="draft", tier=body.tier, scenario=scenario, doc={},
                            created_at=now, updated_at=now)
    session.add(app_row)
    session.flush()
    doc = verify.new_doc(data, user.display_name, body.borrower_type,
                         connection=shops.summary(connection) if connection else None)
    verify.read_store(session, app_row, doc, urls, reg_no or None)
    return _done(session, app_row, user)


@router.get("")
def list_applications(status: str | None = Query(default=None, max_length=20),
                      seller: str | None = Query(default=None, max_length=80), user: BuUser = Depends(_readers),
                      session: Session = Depends(get_session)) -> dict:
    """``seller`` (staff): part of the seller's name or email, or a seller id."""
    q = select(BuApplication).order_by(BuApplication.updated_at.desc())
    if user.role == "seller":
        q = q.where(BuApplication.seller_user_id == user.id, BuApplication.status != "withdrawn")
    elif seller and seller.strip():
        text = unicodedata.normalize("NFC", seller.strip()).casefold()
        like = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        ids = select(BuUser.id).where(func.ulower(BuUser.email).like(like, escape="\\")
                                      | func.ulower(BuUser.display_name).like(like, escape="\\")
                                      | (BuUser.id == seller.strip()))
        q = q.where(BuApplication.seller_user_id.in_(ids))
    if status:
        q = q.where(BuApplication.status == status)
    rows = list(session.scalars(q.limit(500)))
    sellers = {u.id: u for u in session.scalars(select(BuUser).where(BuUser.id.in_({r.seller_user_id for r in rows})))}
    return {"items": [views.summary_view(r, sellers.get(r.seller_user_id)) for r in rows]}


@router.get("/{app_id}")
def get_application(app_id: str, user: BuUser = Depends(_readers), session: Session = Depends(get_session)) -> dict:
    return out(session, load(session, app_id, user), user)


# Review 17/10/2026: the seller may remove an application from "Hồ sơ của bạn". It is withdrawn and hidden, never
# erased: the chain entries already written stay (they cannot be removed) and the record is kept for audit.
NOT_DELETABLE = ("verifying", "in_control", "signed", "disbursed", "repaying", "closed")


def deletable(app_row: BuApplication) -> bool:
    return not app_row.loan_id and app_row.status not in NOT_DELETABLE and app_row.status != "withdrawn"


@router.delete("/{app_id}")
def delete_application(app_id: str, user: BuUser = Depends(_sellers), session: Session = Depends(get_session)) -> dict:
    app_row, doc = _own(session, app_id, user)
    if not deletable(app_row):
        raise api_error(400, "INVALID_STATE", "Hồ sơ đã có khoản vay hoặc đang ký, giải ngân nên không xóa được.",
                        {"status": app_row.status})
    before = app_row.status
    doc["withdrawn"] = {"at": views.now_iso(), "status_before": before}
    entry = chain.record(session, app_row.id, "application_withdrawn", {"application": app_row.code, "status_before": before})
    doc["withdrawn"]["chain_tx"] = entry.tx
    events.log(session, app_row.id, "seller", "withdrawn", f"Người vay xóa hồ sơ (trạng thái trước: {before})",
               hash_=entry.fingerprint)
    views.store(app_row, doc, "withdrawn")
    session.commit()
    return {"id": app_row.id, "status": "withdrawn", "deleted": True}


@router.post("/{app_id}/identity")
def identity(app_id: str, body: IdentityIn, user: BuUser = Depends(_sellers),
             session: Session = Depends(get_session)) -> dict:
    app_row, doc = _own(session, app_id, user)
    _require(app_row, "draft")
    if not (body.cccd and (body.face or body.otp_verified)):
        raise api_error(400, "VALIDATION_ERROR", "Cần quét CCCD và xác thực khuôn mặt hoặc mã OTP.", {"field": "cccd"})
    scans = doc.get("cccd_scans") or {}
    if settings.cccd_ocr_required and "front" not in scans:
        raise api_error(400, "VALIDATION_ERROR", "Cần chụp mặt trước CCCD để hệ thống đọc thông tin.", {"field": "cccd"})
    face_check = otp_check = None
    use_otp = body.otp_verified and not body.face_verify_id
    if use_otp:
        key = "identity-otp:" + user.id
        _reserve(session, key)
        if _recent(session, key, failures_only=False) > _MAX_IDENTITY_OTP:
            raise api_error(429, "RATE_LIMITED", "Xác thực bằng mã OTP quá nhiều lần. Vui lòng chờ 15 phút.")
        otp_check = {"method": "sms_otp", "phone_masked": _masked(body.otp_phone or user.phone),
                     "checked_in": "browser", "face_registered": face_api.verification_required(user)}
    elif face_api.verification_required(user):
        proof = face_api.consume_verification(body.face_verify_id or "", user)
        if proof is None:
            raise api_error(400, "VALIDATION_ERROR", "Cần quét lại khuôn mặt hoặc xác thực bằng mã OTP để xác minh "
                                                     "danh tính.", {"field": "face_verify_id"})
        face_check = {"method": "arcface_buffalo_l_1to1_liveness", "score": round(proof.score, 3),
                      "challenge": proof.challenge}
    verify.identify(session, app_row, doc, face_check=face_check, otp_check=otp_check)
    if otp_check is not None:
        events.log(session, app_row.id, "seller", "identity_otp",
                   "Người vay xác thực danh tính bằng mã OTP thay cho khuôn mặt", otp_check)
    return _done(session, app_row, user)


_MAX_IDENTITY_OTP = 10  # identity steps verified by OTP per account per 15 minutes


def _masked(phone: str) -> str:
    """Only the last three digits are ever kept: "•••• 678"."""
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    return "•••• " + digits[-3:] if len(digits) >= 3 else ""


def _signer_check(session: Session, app_row: BuApplication, user: BuUser, body: SignerCheck, method: str,
                  what: str) -> None:
    """A face re-check sent with a signature must be valid (single use); an OTP is noted as checked in the browser."""
    if not (body.face_verify_id or body.otp_verified):
        return
    payload: dict[str, Any] = {"what": what, "method": method}
    if body.face_verify_id:
        proof = face_api.consume_verification(body.face_verify_id, user)
        if proof is None:
            raise api_error(400, "VALIDATION_ERROR", "Phiên xác minh khuôn mặt đã hết hạn. Vui lòng xác thực lại.",
                            {"field": "face_verify_id"})
        payload.update(face_checked=True, score=round(proof.score, 3))
    if body.otp_verified:
        payload.update(otp_verified=True, checked_in="browser", phone_masked=_masked(user.phone))
    label = "khuôn mặt" if body.face_verify_id else "mã OTP"
    events.log(session, app_row.id, "seller", "signer_verified", f"Người vay xác thực bằng {label} trước khi ký {what}",
               payload)


_RENEWABLE = ("consented", "needs_answer", "verified", "offered", "selected", "escalated")
_DEMO_ENVS = ("dev", "demo", "test")


def _consent_scopes(body: ConsentIn) -> list[str]:
    unknown = [s for s in body.scopes if s not in SCOPE_KEYS]
    missing = [s for s in SCOPE_KEYS if s not in body.scopes]
    if unknown or missing:
        raise api_error(400, "VALIDATION_ERROR", "Cần đánh dấu đủ ba ô: tra cứu tín dụng, chuyển hồ sơ cho ngân hàng "
                                                 "hợp tác, xử lý khuôn mặt và dữ liệu tài chính.",
                        {"field": "scopes", "missing": missing, "unknown": unknown})
    return [s for s in SCOPE_KEYS if s in body.scopes]


def _require_consentable(app_row: BuApplication, doc: dict[str, Any]) -> None:
    """First consent at ``identified``; a new one only after revocation/expiry."""
    if app_row.status == "identified":
        return
    if app_row.status in _RENEWABLE and consent_mod.blocked_reason(doc.get("consent")):
        return
    raise api_error(400, "INVALID_STATE", "Thao tác không hợp lệ ở trạng thái hiện tại của hồ sơ.",
                    {"status": app_row.status, "allowed": ["identified"]})


@router.post("/{app_id}/consent/draft")
def consent_draft(app_id: str, body: ConsentIn, user: BuUser = Depends(_sellers),
                  session: Session = Depends(get_session)) -> dict:
    """The exact document the seller signs (Ed25519 over ``message``)."""
    app_row, doc = _own(session, app_id, user)
    _require_consentable(app_row, doc)
    document = consent_mod.build_document(app_row.code, _consent_scopes(body), [],
                                          active_params(session)["consent"]["ttl_days"])
    doc["internal"]["consent_draft"] = document
    views.store(app_row, doc)
    session.commit()
    return {"document": document, "message": consent_mod.message(document).decode("utf-8"),
            "alg": consent_mod.ALG, "boxes": consent_mod.BOXES}


@router.post("/{app_id}/consent")
def consent(app_id: str, body: ConsentIn, user: BuUser = Depends(_sellers),
            session: Session = Depends(get_session)) -> dict:
    app_row, doc = _own(session, app_id, user)
    _require_consentable(app_row, doc)
    scopes = _consent_scopes(body)
    _signer_check(session, app_row, user, body, body.method, "ủy quyền")
    if body.signature is not None:
        document = doc["internal"].get("consent_draft")
        if document is None or document["scopes"] != scopes:
            raise api_error(400, "VALIDATION_ERROR", "Chữ ký phải ký trên bản ủy quyền vừa tạo ở /consent/draft "
                                                     "với cùng ba ô.", {"field": "signature"})
        signature = body.signature.model_dump()
        if not consent_mod.verify_signature(document, signature):
            raise api_error(400, "VALIDATION_ERROR", "Chữ ký ủy quyền không hợp lệ.", {"field": "signature"})
        signature["simulated"] = False
        signature["method"] = body.method
    elif settings.app_env in _DEMO_ENVS:
        document = consent_mod.build_document(app_row.code, scopes, [],
                                              active_params(session)["consent"]["ttl_days"])
        signature = consent_mod.demo_sign(document, body.method)
    else:
        raise api_error(400, "VALIDATION_ERROR", "Cần chữ ký số của người vay trên bản ủy quyền.",
                        {"field": "signature"})
    verify.consent(session, app_row, doc, document, signature)
    return _done(session, app_row, user)


@router.post("/{app_id}/consent/revoke")
def revoke_consent(app_id: str, user: BuUser = Depends(_sellers), session: Session = Depends(get_session)) -> dict:
    app_row, doc = _own(session, app_id, user)
    verify.revoke_consent(session, app_row, doc)
    return _done(session, app_row, user)


@router.put("/{app_id}/plan")
def put_plan(app_id: str, body: PlanIn, user: BuUser = Depends(_sellers),
             session: Session = Depends(get_session)) -> dict:
    app_row, doc = _own(session, app_id, user)
    _require(app_row, "consented")
    if app_row.tier != 2:
        raise api_error(400, "INVALID_STATE", "Biểu mẫu kế hoạch chỉ dùng cho Tầng 2.")
    plan = body.model_dump()
    statements = plan.pop("statements", None)
    declared = plan.pop("declaration", False)
    if settings.plan_declaration_required and not declared:
        raise api_error(400, "VALIDATION_ERROR", "Bạn cần tích ô cam đoan thông tin kê khai là đúng sự thật.",
                        {"field": "declaration"})
    if float(plan["price"]).is_integer():
        plan["price"] = int(plan["price"])
    verify.set_plan(app_row, doc, plan, statements)
    if declared:
        verify.record_declaration(session, app_row, doc, statements, plan)
    return _done(session, app_row, user)


_VERIFYING: set[str] = set()
_VERIFYING_LOCK = threading.Lock()


@router.post("/{app_id}/verify")
def run_verify(app_id: str, user: BuUser = Depends(_sellers), session: Session = Depends(get_session)) -> dict:
    # 18/10/2026: one verification per application at a time. A second click while the first is still
    # running (slow model server) used to hit the SQLite write lock and answer 500.
    with _VERIFYING_LOCK:
        if app_id in _VERIFYING:
            raise api_error(409, "VERIFY_IN_PROGRESS", "Hồ sơ đang được xác minh, vui lòng đợi thêm một chút.")
        _VERIFYING.add(app_id)
    try:
        app_row, doc = _own(session, app_id, user)
        _require(app_row, "consented")
        if app_row.tier == 2 and not (doc.get("plan") or {}).get("submitted"):
            raise api_error(400, "INVALID_STATE", "Cần gửi biểu mẫu kế hoạch trước khi xác minh.")
        verify.run(session, app_row, doc, active_params(session))
        return _done(session, app_row, user)
    finally:
        with _VERIFYING_LOCK:
            _VERIFYING.discard(app_id)


@router.post("/{app_id}/answers")
def answers(app_id: str, body: AnswerIn, user: BuUser = Depends(_sellers),
            session: Session = Depends(get_session)) -> dict:
    app_row, doc = _own(session, app_id, user)
    _require(app_row, "needs_answer")
    verify.answer(session, app_row, doc, active_params(session), body.model_dump())
    return _done(session, app_row, user)


def _offered(app_row: BuApplication, doc: dict[str, Any]) -> dict[str, Any]:
    if not doc.get("offer"):
        raise api_error(400, "INVALID_STATE", "Hồ sơ chưa có phiếu đề xuất.", {"status": app_row.status})
    return doc["offer"]


@router.get("/{app_id}/offer")
def get_offer(app_id: str, user: BuUser = Depends(_readers), session: Session = Depends(get_session)) -> dict:
    app_row = load(session, app_id, user)
    offer = _offered(app_row, app_row.doc)
    return offer if user.role in ("officer", "admin") else advise.seller_offer(offer)


@router.post("/{app_id}/what-if")
def what_if(app_id: str, body: WhatIfIn, user: BuUser = Depends(_sellers),
            session: Session = Depends(get_session)) -> dict:
    app_row, doc = _own(session, app_id, user)
    _offered(app_row, doc)
    changes = body.model_dump(exclude_none=True)
    result = advise.what_if(session, app_row, doc, active_params(session), changes)
    session.commit()
    return result


@router.post("/{app_id}/quote")
def quote(app_id: str, body: QuoteIn, user: BuUser = Depends(_readers),
          session: Session = Depends(get_session)) -> dict:
    app_row = load(session, app_id, user)
    _require(app_row, "offered", "selected")
    params = active_params(session)
    doc = app_row.doc
    if body.tenor_m is not None:
        contract_mod.validate_choice(params, doc, min(body.amount, int(doc["offer"]["limit"])), body.tenor_m,
                                     body.method, body.due_day)
    return advise.quote(params, doc, body.amount, body.tenor_m, body.method, body.due_day)


@router.get("/{app_id}/messages")
def get_messages(app_id: str, user: BuUser = Depends(_readers), session: Session = Depends(get_session)) -> dict:
    app_row = load(session, app_id, user)
    return {"items": [advise.message_public(m) for m in advise.messages(session, app_row.id)]}


@router.post("/{app_id}/messages")
def post_message(app_id: str, body: MessageIn, user: BuUser = Depends(_sellers),
                 session: Session = Depends(get_session)) -> dict:
    app_row, doc = _own(session, app_id, user)
    params = active_params(session)
    key = f"chat:{user.id}"
    recent = session.scalar(select(func.count()).select_from(BuRateEvent).where(
        BuRateEvent.key == key, BuRateEvent.at >= utcnow() - timedelta(minutes=1))) or 0
    if recent >= int(params["chat"]["max_per_minute"]):
        raise api_error(429, "RATE_LIMITED", "Bạn gửi tin nhắn quá nhanh. Vui lòng thử lại sau một phút.")
    session.add(BuRateEvent(key=key, ok=True, at=utcnow()))
    items = advise.chat(session, app_row, doc, params, body.text.strip())
    session.commit()
    return {"items": [advise.message_public(m) for m in items]}


def _not_expired(session: Session, app_row: BuApplication, doc: dict[str, Any]) -> None:
    if contract_mod.expired(doc):
        views.store(app_row, doc, "expired")
        session.commit()
        raise api_error(400, "LIMIT_EXPIRED", "Hạn mức đã hết hiệu lực 7 ngày; bạn nộp hồ sơ mới để được duyệt lại.")


@router.post("/{app_id}/select")
def select_terms(app_id: str, body: ChoiceIn, user: BuUser = Depends(_sellers),
                 session: Session = Depends(get_session)) -> dict:
    """Stage 3: amount, tenor, method, due day within the approved limit (no new approval)."""
    app_row, doc = _own(session, app_id, user)
    _require(app_row, "offered", "selected")
    _not_expired(session, app_row, doc)
    contract_mod.select(session, app_row, doc, active_params(session), amount=body.amount,
                        tenor_m=body.tenor_m or max(doc["offer"]["tenors"]),
                        method=body.method, due_day=body.due_day)
    views.store(app_row, doc, "selected")
    return _done(session, app_row, user)


@router.get("/{app_id}/contract")
def get_contract(app_id: str, user: BuUser = Depends(_readers), session: Session = Depends(get_session)) -> dict:
    """Stage 4: the cost disclosure and the contract for the current choice. The seller opening it
    starts the reading clock; staff only read what was issued."""
    app_row = load(session, app_id, user)
    if user.role != "seller":
        if not app_row.doc.get("contract"):
            raise api_error(404, "NOT_FOUND", "Hồ sơ chưa có hợp đồng.")
        return app_row.doc["contract"]
    doc = copy.deepcopy(app_row.doc)
    if app_row.status not in ("selected", "signed", "disbursed", "repaying", "closed"):
        raise api_error(400, "INVALID_STATE", "Bạn cần chọn khoản vay trước.", {"status": app_row.status})
    if app_row.status == "selected":
        _not_expired(session, app_row, doc)
        contract = contract_mod.issue(session, app_row, doc, active_params(session))
        views.store(app_row, doc)
        session.commit()
        return contract
    return doc["contract"]


@router.post("/{app_id}/sign")
def sign_contract(app_id: str, body: SignIn, user: BuUser = Depends(_sellers),
                  session: Session = Depends(get_session)) -> dict:
    """Stage 4–5: sign, the banks' room is taken, escrow, payout."""
    app_row, doc = _own(session, app_id, user)
    _require(app_row, "selected")
    _not_expired(session, app_row, doc)
    _signer_check(session, app_row, user, body, body.method, "hợp đồng")
    contract_mod.sign(session, app_row, doc, active_params(session), body.model_dump())
    return _done(session, app_row, user)


@router.post("/{app_id}/manual-channel")
def manual_channel(app_id: str, user: BuUser = Depends(_sellers), session: Session = Depends(get_session)) -> dict:
    app_row, doc = _own(session, app_id, user)
    _require(app_row, "offered", "selected")
    control.request_human(session, app_row, doc, "Người bán chọn kênh thủ công cho hạn mức đầy đủ",
                          why="MANUAL_CHANNEL")
    return _done(session, app_row, user)


@router.post("/{app_id}/request-human")
def request_human(app_id: str, body: HumanIn, user: BuUser = Depends(_sellers),
                  session: Session = Depends(get_session)) -> dict:
    app_row, doc = _own(session, app_id, user)
    control.request_human(session, app_row, doc, body.reason.strip() or "Người bán yêu cầu cán bộ xem hồ sơ")
    return _done(session, app_row, user)


@router.get("/{app_id}/flow")
def calculation_flow(app_id: str, user: BuUser = Depends(require_roles("officer", "admin")),
                     session: Session = Depends(get_session)) -> dict:
    """Staff: the whole calculation of one application, block by block (inputs, formula with
    the real numbers, output, source), rebuilt with the algorithm and checked against the
    recorded sheet; then the split, the payout on the chain and the monitoring."""
    from app.core import flow

    return flow.application_flow(session, load(session, app_id, user))


@router.get("/{app_id}/trace")
def trace(app_id: str, user: BuUser = Depends(_readers), session: Session = Depends(get_session)) -> dict:
    return views.trace_view(session, load(session, app_id, user), user)
