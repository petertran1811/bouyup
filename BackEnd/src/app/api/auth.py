"""/v4/auth: register (sellers only), login, logout, me."""

from __future__ import annotations

import re
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.platform import audit, events
from app.platform.errors import api_error
from app.data_sources import profiles
from app.platform.security import current_session_row, current_user, find_user_by_email, hash_password, issue_session, new_user_id, normalize_email, password_problem, user_public, valid_email, verify_password
from app.platform.tables import BuLoginAttempt, BuRateEvent, BuSession, BuUser
from app.platform.config import settings
from app.platform.db.session import get_session
from app.platform.db.tables import utcnow

router = APIRouter(prefix="/auth", tags=["v4-auth"])

_MAX_FAILS = 5            # per (email, ip): an attacker elsewhere cannot lock you out
_MAX_IP_FAILS = 30        # per ip, any email
_MAX_REGISTER = 10        # per ip per window
_MAX_OTP_REGISTER = 3     # sign-ups verified by SMS OTP per phone number per window
_DUMMY_HASH = hash_password("dummy-password-0")
_WINDOW = timedelta(minutes=15)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _recent(session: Session, key: str, *, failures_only: bool) -> int:
    q = select(func.count()).select_from(BuRateEvent).where(
        BuRateEvent.key == key, BuRateEvent.at >= utcnow() - _WINDOW
    )
    if failures_only:
        q = q.where(BuRateEvent.ok.is_(False))
    return session.scalar(q) or 0


# Mobile numbers that can receive the SMS OTP: Vietnam (+84 / 0, then 3|5|7|8|9 and 8 digits)
# and mainland China (+86 optional, then 1[3-9] and 9 digits).
_VN_MOBILE = re.compile(r"(?:84|0|840)([35789]\d{8})")
_CN_MOBILE = re.compile(r"(?:86)?(1[3-9]\d{9})")


def normalize_phone(phone: str) -> str | None:
    """``+84912345678`` / ``+8613800000000`` for a valid VN/CN mobile number, else None."""
    raw = (phone or "").strip()
    if not re.fullmatch(r"\+?[\d\s().-]{8,24}", raw):
        return None
    digits = re.sub(r"\D", "", raw)
    international = raw.startswith("+")
    if not international and digits.startswith("00"):
        digits, international = digits[2:], True
    vn, cn = _VN_MOBILE.fullmatch(digits), _CN_MOBILE.fullmatch(digits)
    if vn and (digits.startswith("84") or not international):
        return "+84" + vn.group(1)
    if cn and (digits.startswith("86") or not international):
        return "+86" + cn.group(1)
    return None


def mask_phone(phone: str) -> str:
    """The masked form shown on screen and kept in records: "•••• 678"."""
    digits = re.sub(r"\D", "", phone or "")
    return "•••• " + digits[-3:] if len(digits) >= 3 else ""


def _reserve(session: Session, key: str) -> BuRateEvent:
    """Record the attempt (as a failure) and commit BEFORE checking the password,
    so concurrent requests all see each other; flipped to ok on success."""
    event = BuRateEvent(key=key, ok=False, at=utcnow())
    session.add(event)
    session.commit()
    return event


class RegisterIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(default="", max_length=40)
    accept_terms: bool = False
    # A finished /v4/face/enroll scan; its templates are saved for this account (face login).
    face_enroll_id: str | None = Field(default=None, max_length=64)
    # No face scan (no camera, camera refused, no face model, failed scan): the phone number was
    # verified with an SMS OTP instead. TODO(SMS): the code is generated and checked in the browser
    # today; once an SMS provider is wired, replace this flag with a server proof from
    # POST /v4/otp/verify (see API_CONTRACT_V4.md §1b).
    otp_verified: bool = False


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


def _session_out(token: str, row: BuSession, user: BuUser) -> dict:
    return {"token": token, "expires_at": row.expires_at.isoformat() + "Z", "user": user_public(user)}


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request, session: Session = Depends(get_session)) -> dict:
    reg_key = "register:" + _client_ip(request)
    _reserve(session, reg_key)
    if _recent(session, reg_key, failures_only=False) > _MAX_REGISTER:
        raise api_error(429, "RATE_LIMITED", "Đăng ký quá nhiều lần. Thử lại sau 15 phút.")
    email = normalize_email(body.email)
    if not valid_email(email):
        raise api_error(400, "VALIDATION_ERROR", "Email không hợp lệ.", {"field": "email"})
    problem = password_problem(body.password)
    if problem:
        raise api_error(400, "VALIDATION_ERROR", problem, {"field": "password"})
    if not body.accept_terms:
        raise api_error(400, "VALIDATION_ERROR", "Cần đồng ý điều khoản sử dụng.", {"field": "accept_terms"})
    if find_user_by_email(session, email) is not None:
        raise api_error(409, "CONFLICT", "Email này đã được đăng ký.", {"field": "email"})
    from app.api import face  # face imports this module's helpers

    otp_phone = None
    if body.otp_verified and not body.face_enroll_id:
        otp_phone = normalize_phone(body.phone)
        if otp_phone is None:
            raise api_error(400, "VALIDATION_ERROR", "Cần số điện thoại di động hợp lệ (Việt Nam hoặc Trung Quốc) để "
                                                     "xác thực bằng mã OTP.", {"field": "phone"})
        otp_key = "register-otp:" + otp_phone
        _reserve(session, otp_key)
        if _recent(session, otp_key, failures_only=False) > _MAX_OTP_REGISTER:
            raise api_error(429, "RATE_LIMITED", "Số điện thoại này đã đăng ký nhiều lần. Vui lòng chờ 15 phút.")
    if not body.face_enroll_id and otp_phone is None and face.signup_requires_face():
        raise api_error(400, "VALIDATION_ERROR", "Cần quét khuôn mặt hoặc xác thực bằng mã OTP để tạo tài khoản.",
                        {"field": "face_enroll_id"})
    enrollment = face.claim_enrollment(body.face_enroll_id) if body.face_enroll_id else None
    user = BuUser(
        id=new_user_id(),
        email=email,
        password_hash=hash_password(body.password),
        display_name=body.display_name.strip(),
        phone=body.phone.strip(),
        role="seller",
        active=True,
        last_login_at=utcnow(),
    )
    try:
        session.add(user)
        session.flush()
        token, row = issue_session(session, user)
        if enrollment is not None:
            face.save_enrollment(enrollment, user, session)
        if otp_phone is not None:
            # Account-level record (application_id = the user id): sign-up verified by SMS OTP, no face.
            events.log(session, user.id, "seller", "register_otp",
                       "Tạo tài khoản không có khuôn mặt; số điện thoại xác thực bằng mã OTP",
                       {"user_id": user.id, "phone_masked": mask_phone(otp_phone), "checked_in": "browser"})
        session.commit()
    except Exception:
        session.rollback()
        if enrollment is not None:
            face.store.delete(user.id)
            face.release_enrollment(enrollment)
        raise
    if otp_phone is not None:
        audit.logger.info("register_otp", user_id=user.id, phone=mask_phone(otp_phone))
    return _session_out(token, row, user)


@router.post("/login")
def login(body: LoginIn, request: Request, session: Session = Depends(get_session)) -> dict:
    email = normalize_email(body.email)
    ip = _client_ip(request)
    pair_key, ip_key = f"login:{email}|{ip}", f"login-ip:{ip}"
    pair_event = _reserve(session, pair_key)
    ip_event = _reserve(session, ip_key)
    if (
        _recent(session, pair_key, failures_only=True) > _MAX_FAILS
        or _recent(session, ip_key, failures_only=True) > _MAX_IP_FAILS
    ):
        raise api_error(429, "RATE_LIMITED", "Đăng nhập sai quá nhiều lần. Thử lại sau 15 phút.")
    user = find_user_by_email(session, email)
    # Unknown emails still pay one PBKDF2 so timing does not reveal which exist.
    stored = user.password_hash if user is not None else _DUMMY_HASH
    ok = verify_password(body.password, stored) and user is not None and user.active
    session.add(BuLoginAttempt(email=email, ok=ok, at=utcnow()))
    if not ok:
        session.commit()
        raise api_error(401, "INVALID_CREDENTIALS", "Email hoặc mật khẩu không đúng.")
    assert user is not None
    pair_event.ok = True
    ip_event.ok = True
    user.last_login_at = utcnow()
    token, row = issue_session(session, user)
    session.commit()
    return _session_out(token, row, user)


@router.post("/logout", status_code=204)
def logout(
    row: BuSession = Depends(current_session_row), session: Session = Depends(get_session)
) -> Response:
    live = session.get(BuSession, row.token_hash)
    if live is not None:
        live.revoked_at = utcnow()
        session.commit()
    return Response(status_code=204)


@router.get("/me")
def me(user: BuUser = Depends(current_user)) -> dict:
    out: dict = {"user": user_public(user)}
    # Demo accounts with a raw dossier (profiles/*.json) get their store link and account prefilled.
    if user.role == "seller" and settings.app_env in ("dev", "demo", "test"):
        hint = profiles.hint_for_email(user.email)
        if hint:
            out["demo_profile"] = hint
    return out
