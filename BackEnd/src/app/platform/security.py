"""Passwords, session tokens and the request-auth dependencies for /v4.

Passwords: PBKDF2-HMAC-SHA256 (stdlib), per-user random salt.
Sessions: 256-bit random bearer tokens; the database keeps only SHA-256(token),
so a leaked database does not leak usable tokens.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from collections.abc import Callable
from datetime import timedelta

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform.errors import api_error
from app.platform.tables import BuSession, BuUser
from app.platform.config import settings
from app.platform.db.session import get_session
from app.platform.db.tables import utcnow

ROLES = ("seller", "officer", "bank", "admin")
_PBKDF2_ITERATIONS = 240_000
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,}$")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), base64.b64decode(salt_b64), int(iterations)
    )
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


def password_problem(password: str) -> str | None:
    """Vietnamese message when the password is too weak, else None."""
    if len(password) < 8:
        return "Mật khẩu cần ít nhất 8 ký tự."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Mật khẩu cần có cả chữ và số."
    return None


def normalize_email(email: str) -> str:
    return email.strip().lower()


def valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email))


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_user_id() -> str:
    return "usr_" + secrets.token_hex(8)


def issue_session(session: Session, user: BuUser) -> tuple[str, BuSession]:
    token = secrets.token_urlsafe(32)
    row = BuSession(
        token_hash=token_digest(token),
        user_id=user.id,
        created_at=utcnow(),
        expires_at=utcnow() + timedelta(hours=settings.buoyup_session_hours),
    )
    session.add(row)
    return token, row


def user_public(user: BuUser) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "phone": user.phone,
        "role": user.role,
        "bank_code": user.bank_code,
        "created_at": user.created_at.isoformat() + "Z" if user.created_at else None,
    }


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def current_session_row(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> BuSession:
    token = _bearer(authorization)
    if token is None:
        raise api_error(401, "AUTH_REQUIRED", "Vui lòng đăng nhập.")
    row = session.get(BuSession, token_digest(token))
    if row is None or row.revoked_at is not None:
        raise api_error(401, "AUTH_REQUIRED", "Phiên đăng nhập không hợp lệ.")
    if row.expires_at <= utcnow():
        raise api_error(401, "SESSION_EXPIRED", "Phiên đăng nhập đã hết hạn.")
    return row


def current_user(
    row: BuSession = Depends(current_session_row),
    session: Session = Depends(get_session),
) -> BuUser:
    user = session.get(BuUser, row.user_id)
    if user is None or not user.active:
        raise api_error(401, "AUTH_REQUIRED", "Tài khoản không còn hoạt động.")
    return user


def require_roles(*roles: str) -> Callable[..., BuUser]:
    allowed = set(roles)

    def dependency(user: BuUser = Depends(current_user)) -> BuUser:
        if user.role not in allowed:
            raise api_error(403, "FORBIDDEN", "Bạn không có quyền thực hiện thao tác này.")
        return user

    return dependency


def find_user_by_email(session: Session, email: str) -> BuUser | None:
    return session.scalar(select(BuUser).where(BuUser.email == normalize_email(email)))
