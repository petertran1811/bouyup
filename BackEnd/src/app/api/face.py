"""/v4/face: face enrollment at sign-up and face login (Reid, InsightFace buffalo_l).

Sign-up: POST /face/enroll → POST /face/enroll/{id}/frame until ``done`` → POST /auth/register
with ``face_enroll_id``. Login: POST /face/login → POST /face/login/{id}/frame until it
returns a session (same shape as /auth/login) or fails with 401.
"""

from __future__ import annotations

import hashlib
import time

import numpy as np
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from Reid.src.engine import FaceEngine, FaceInputError, FaceUnavailable, Frame
from Reid.src.flows import ENROLL_MAX_FRAMES, Enrollment, FaceLogin, Registry
from Reid.src.store import FaceStore
from app.api.auth import _MAX_IP_FAILS, _client_ip, _recent, _reserve, _session_out
from app.platform import audit
from app.platform.config import settings
from app.platform.db.session import get_session
from app.platform.db.tables import utcnow
from app.platform.errors import api_error
from app.platform.security import current_user, find_user_by_email, issue_session
from app.platform.tables import BuLoginAttempt, BuRateEvent, BuUser

router = APIRouter(prefix="/face", tags=["v4-face"])

ENROLL_TTL, LOGIN_TTL = 300, 120
VERIFIED_TTL = 600  # a passed re-check stays usable for the identity step this long
_MAX_VERIFY_FAILS = 10  # failed re-checks per account per 15 minutes
_MAX_ENROLL = 20  # enrollment starts per ip per 15 minutes
_MIN_FRAME_GAP = 0.05  # seconds between two frames of one flow

engine = FaceEngine(settings.face_model_root, settings.face_det_size)
store = FaceStore(settings.face_data_dir)
enrollments: Registry[Enrollment] = Registry(ENROLL_TTL)
logins: Registry[FaceLogin] = Registry(LOGIN_TTL)
verifications: Registry[FaceLogin] = Registry(LOGIN_TTL)  # signed-in re-checks in progress
verified: Registry[FaceLogin] = Registry(VERIFIED_TTL)  # passed re-checks, each usable once


class FrameIn(BaseModel):
    image: str = Field(min_length=16, max_length=2_100_000)  # base64 JPEG (data URL accepted)


class FaceLoginIn(BaseModel):
    email: str = Field(default="", max_length=254)  # optional: 1:1 instead of 1:N


def warmup() -> None:
    try:
        engine.load(wait=True)
        audit.logger.info("face_engine_ready", model="buffalo_l", provider=engine.provider)
    except Exception as exc:  # noqa: BLE001 - the app runs without face login
        audit.logger.warning("face_engine_unavailable", error=str(exc)[:300])


def available() -> bool:
    return settings.face_auth_enabled and engine.installed() and (engine.ready or not engine.error)


def signup_requires_face() -> bool:
    """Sign-up needs a face scan whenever the model is loaded; without it sign-up still works."""
    return settings.face_auth_enabled and settings.face_required_at_signup and engine.ready


def _unavailable(exc: Exception | None = None) -> Exception:
    return api_error(503, "FACE_UNAVAILABLE", "Xác thực khuôn mặt chưa sẵn sàng trên máy chủ.",
                     {"reason": str(exc)} if exc else None)


def _ready() -> None:
    if not settings.face_auth_enabled:
        raise _unavailable()
    try:
        engine.load()
    except FaceUnavailable as exc:
        raise _unavailable(exc) from exc


def _analyze(body: FrameIn) -> Frame:
    try:
        return engine.analyze(body.image)
    except FaceInputError as exc:
        raise api_error(400, "VALIDATION_ERROR", str(exc), {"field": "image"}) from exc
    except FaceUnavailable as exc:
        raise _unavailable(exc) from exc


def _expired() -> Exception:
    return api_error(404, "NOT_FOUND", "Phiên xác thực khuôn mặt đã hết hạn. Vui lòng thử lại.")


def _repeat(flow: Enrollment | FaceLogin, body: FrameIn) -> dict | None:
    """Throttles a flow and skips byte-identical frames (a replayed picture, a frozen camera)."""
    now = time.monotonic()
    if now - flow.context.get("last_frame", 0.0) < _MIN_FRAME_GAP:
        raise api_error(429, "RATE_LIMITED", "Gửi khung hình quá nhanh.")
    flow.context["last_frame"] = now
    digest = hashlib.sha256(body.image.encode()).digest()
    seen = flow.context.setdefault("seen", set())
    if digest in seen:
        return flow.state("STILL_FRAME", "Hình từ camera không thay đổi. Kiểm tra camera rồi thử lại.")
    seen.add(digest)
    return None


@router.get("/status")
def status() -> dict:
    return {"enabled": settings.face_auth_enabled, "available": available(),
            "required_at_signup": signup_requires_face(),
            "enrolled_users": store.count(), **engine.status()}


@router.post("/enroll")
def enroll_start(request: Request, session: Session = Depends(get_session)) -> dict:
    key = "face-enroll:" + _client_ip(request)
    _reserve(session, key)
    if _recent(session, key, failures_only=False) > _MAX_ENROLL:
        raise api_error(429, "RATE_LIMITED", "Thử xác thực khuôn mặt quá nhiều lần. Thử lại sau 15 phút.")
    _ready()
    flow = enrollments.add(Enrollment())
    return {"enroll_id": flow.id, "expires_in": ENROLL_TTL, **flow.state("OK", "")}


@router.post("/enroll/{enroll_id}/frame")
def enroll_frame(enroll_id: str, body: FrameIn) -> dict:
    flow = enrollments.get(enroll_id)
    if flow is None:
        raise _expired()
    with flow.lock:
        if flow.frames >= ENROLL_MAX_FRAMES:
            enrollments.pop(enroll_id)
            raise _expired()
        out = _repeat(flow, body)
        if out is None:
            frame = _analyze(body)
            crop = (lambda det: engine.crop_jpeg(frame, det)) if settings.face_save_crops else (lambda det: b"")
            out = flow.feed(frame, lambda det: engine.embed(frame, det), crop)
    return {"enroll_id": flow.id, **out}


def claim_enrollment(enroll_id: str) -> Enrollment:
    """For /auth/register: takes a finished scan out of the registry, so only one sign-up can use it.
    The duplicate-face check runs in save_enrollment (here it would let anyone probe who has an account)."""
    flow = enrollments.pop(enroll_id)
    if flow is None:
        raise api_error(400, "VALIDATION_ERROR", "Phiên xác thực khuôn mặt đã hết hạn. Vui lòng quét lại.",
                        {"field": "face_enroll_id"})
    if not flow.done:
        enrollments.add(flow)
        raise api_error(400, "VALIDATION_ERROR", "Chưa hoàn tất xác thực khuôn mặt.", {"field": "face_enroll_id"})
    return flow


def release_enrollment(flow: Enrollment) -> None:
    """Sign-up failed after the claim: the scan can be used for the next attempt."""
    enrollments.add(flow)


def save_enrollment(flow: Enrollment, user: BuUser, session: Session) -> None:
    """One face, one account: the check and the save are atomic in the store."""
    owner = store.save_if_unique(
        user.id, flow.templates(), np.stack(flow.center), settings.face_match_threshold,
        {"email": user.email, "display_name": user.display_name, "model": "buffalo_l",
         "segments": len(flow.segments)}, flow.crops,
        is_live=lambda uid: session.get(BuUser, uid) is not None)
    if owner is not None:
        raise api_error(409, "FACE_ALREADY_REGISTERED", "Khuôn mặt này đã được đăng ký cho một tài khoản khác.",
                        {"field": "face_enroll_id"})


@router.post("/login")
def login_start(body: FaceLoginIn, request: Request, session: Session = Depends(get_session)) -> dict:
    ip_key = "face-login-ip:" + _client_ip(request)
    event = _reserve(session, ip_key)
    if _recent(session, ip_key, failures_only=True) > _MAX_IP_FAILS:
        raise api_error(429, "RATE_LIMITED", "Xác thực khuôn mặt thất bại quá nhiều lần. Thử lại sau 15 phút.")
    _ready()
    only = None
    if body.email.strip():
        user = find_user_by_email(session, body.email)
        # An unknown or un-enrolled email still runs the flow and fails the same way: no account probing.
        only = user.id if user is not None else "-"
    flow = logins.add(FaceLogin(only_user=only))
    flow.context.update(rate_event=event.id, email=body.email.strip().lower())
    return {"login_id": flow.id, "expires_in": LOGIN_TTL, **flow.state("OK", "Nhìn thẳng vào camera.")}


@router.post("/login/{login_id}/frame")
def login_frame(login_id: str, body: FrameIn, session: Session = Depends(get_session)) -> dict:
    flow = logins.get(login_id)
    if flow is None:
        raise _expired()
    with flow.lock:
        if logins.get(login_id) is not flow:  # a parallel request already finished this flow
            raise _expired()
        out = _repeat(flow, body)
        if out is not None:
            return {"login_id": flow.id, **out}
        frame = _analyze(body)
        out = flow.feed(frame, lambda det: engine.embed(frame, det),
                        lambda probe, only: store.search(np.asarray(probe), only), settings.face_match_threshold)
        if not (out["done"] or out["failed"]):
            return {"login_id": flow.id, **out}
        logins.pop(login_id)
        user = session.get(BuUser, flow.user_id) if flow.user_id else None
        if user is None or not user.active:
            if flow.user_id and user is None:
                store.delete(flow.user_id)  # templates of a sign-up that never committed
            session.add(BuLoginAttempt(email=flow.context.get("email") or "(face)", ok=False, at=utcnow()))
            session.commit()
            if out["failed"]:
                raise api_error(401, "FACE_" + out["hint"], out["message"])
            raise api_error(401, "FACE_NOT_RECOGNIZED", "Không nhận ra khuôn mặt đã đăng ký.")
        event = session.get(BuRateEvent, flow.context.get("rate_event"))
        if event is not None:
            event.ok = True
        user.last_login_at = utcnow()
        session.add(BuLoginAttempt(email=user.email, ok=True, at=utcnow()))
        token, row = issue_session(session, user)
        session.commit()
        audit.logger.info("face_login", user_id=user.id, score=round(flow.score, 3), challenge=flow.challenge)
        return {"login_id": flow.id, **out, **_session_out(token, row, user)}


# --- re-check for a signed-in user (identity step of a loan application) -----------------

def verification_required(user: BuUser) -> bool:
    """The identity step needs a live 1:1 face re-check when this account has a registered face."""
    return settings.face_auth_enabled and engine.ready and store.has(user.id)


def consume_verification(verify_id: str, user: BuUser) -> FaceLogin | None:
    flow = verified.pop(verify_id) if verify_id else None
    return flow if flow is not None and flow.user_id == user.id else None


@router.post("/verify")
def verify_start(user: BuUser = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    key = "face-verify:" + user.id
    event = _reserve(session, key)
    if _recent(session, key, failures_only=True) > _MAX_VERIFY_FAILS:
        raise api_error(429, "RATE_LIMITED", "Xác minh khuôn mặt thất bại quá nhiều lần. Thử lại sau 15 phút.")
    _ready()
    if not store.has(user.id):
        raise api_error(409, "FACE_NOT_ENROLLED", "Tài khoản này chưa đăng ký khuôn mặt.")
    flow = verifications.add(FaceLogin(only_user=user.id))
    flow.context.update(rate_event=event.id)
    return {"verify_id": flow.id, "expires_in": LOGIN_TTL,
            **flow.state("OK", "Nhìn thẳng vào camera để so với khuôn mặt bạn đã đăng ký.")}


@router.post("/verify/{verify_id}/frame")
def verify_frame(verify_id: str, body: FrameIn, user: BuUser = Depends(current_user),
                 session: Session = Depends(get_session)) -> dict:
    flow = verifications.get(verify_id)
    if flow is None or flow.only_user != user.id:
        raise _expired()
    with flow.lock:
        if verifications.get(verify_id) is not flow:
            raise _expired()
        out = _repeat(flow, body)
        if out is not None:
            return {"verify_id": flow.id, **out}
        frame = _analyze(body)
        out = flow.feed(frame, lambda det: engine.embed(frame, det),
                        lambda probe, only: store.search(np.asarray(probe), only), settings.face_match_threshold)
        if not (out["done"] or out["failed"]):
            return {"verify_id": flow.id, **out}
        verifications.pop(verify_id)
        if out["failed"] or flow.user_id != user.id:
            session.commit()
            # 403, not 401: the user is still signed in, only the face did not match
            raise api_error(403, "FACE_" + (out["hint"] if out["failed"] else "NOT_RECOGNIZED"),
                            out["message"] if out["failed"] else "Khuôn mặt không khớp tài khoản.")
        event = session.get(BuRateEvent, flow.context.get("rate_event"))
        if event is not None:
            event.ok = True
        session.commit()
        verified.add(flow)
        audit.logger.info("face_verify", user_id=user.id, score=round(flow.score, 3), challenge=flow.challenge)
        return {"verify_id": flow.id, **out, "score": round(flow.score, 3)}
