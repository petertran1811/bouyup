"""/v4/admin: user management and system audit (contract §9). Admin only."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.platform.errors import api_error
from app.platform import events
from app.agents.agent4b_monitor import refresh_auto_switch
from app.banks.split import get_bank
from app.core.params import active_params
from app.platform.security import ROLES, find_user_by_email, hash_password, new_user_id, normalize_email, password_problem, require_roles, user_public, valid_email
from app.platform.tables import BuAutoSwitch, BuEvent, BuSession, BuUser
from app.platform.db.session import get_session
from app.platform.db.tables import utcnow

router = APIRouter(prefix="/admin", tags=["v4-admin"])

STAFF_MIN_PASSWORD = 12


class UserIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    role: Literal["officer", "bank", "admin"]
    bank_code: str | None = Field(default=None, max_length=16)
    phone: str = Field(default="", max_length=40)


class UserPatch(BaseModel):
    active: bool | None = None
    role: Literal["seller", "officer", "bank", "admin"] | None = None
    bank_code: str | None = Field(default=None, max_length=16)


def admin_user_view(user: BuUser) -> dict[str, Any]:
    return {**user_public(user), "active": user.active,
            "last_login_at": user.last_login_at.isoformat() + "Z" if user.last_login_at else None}


def _bank_code_for(session: Session, role: str, bank_code: str | None) -> str | None:
    if role != "bank":
        return None
    bank = get_bank(session, bank_code or "")
    if bank is None:
        raise api_error(400, "VALIDATION_ERROR", "Tài khoản ngân hàng cần mã ngân hàng có trong danh mục.",
                        {"field": "bank_code"})
    return bank.code


def staff_password_problem(password: str) -> str | None:
    """Staff accounts (officer/bank/admin) need ≥12 characters with letters and digits."""
    if len(password) < STAFF_MIN_PASSWORD:
        return f"Mật khẩu tài khoản nội bộ cần ít nhất {STAFF_MIN_PASSWORD} ký tự."
    return password_problem(password)


@router.get("/users")
def list_users(
    role: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    _: BuUser = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> dict:
    stmt = select(BuUser).order_by(BuUser.created_at.desc()).limit(limit)
    if role in ROLES:
        stmt = stmt.where(BuUser.role == role)
    return {"items": [admin_user_view(u) for u in session.scalars(stmt)]}


@router.post("/users", status_code=201)
def create_user(
    body: UserIn,
    admin: BuUser = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> dict:
    email = normalize_email(body.email)
    if not valid_email(email):
        raise api_error(400, "VALIDATION_ERROR", "Email không hợp lệ.", {"field": "email"})
    problem = staff_password_problem(body.password)
    if problem:
        raise api_error(400, "VALIDATION_ERROR", problem, {"field": "password"})
    if find_user_by_email(session, email) is not None:
        raise api_error(409, "CONFLICT", "Email này đã được đăng ký.", {"field": "email"})
    user = BuUser(
        id=new_user_id(), email=email, password_hash=hash_password(body.password),
        display_name=body.display_name.strip(), phone=body.phone.strip(), role=body.role,
        bank_code=_bank_code_for(session, body.role, body.bank_code), active=True, created_at=utcnow(),
    )
    session.add(user)
    events.log(session, "system", "admin", "user_created", f"Tạo tài khoản {email} ({body.role})",
               {"user_id": user.id, "by": admin.id})
    session.commit()
    return {"user": admin_user_view(user)}


@router.patch("/users/{user_id}")
def patch_user(
    user_id: str,
    body: UserPatch,
    admin: BuUser = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> dict:
    user = session.get(BuUser, user_id)
    if user is None:
        raise api_error(404, "NOT_FOUND", "Không tìm thấy người dùng.")
    if user.id == admin.id and (body.active is False or (body.role and body.role != "admin")):
        raise api_error(400, "INVALID_STATE", "Không thể tự khóa hoặc tự hạ quyền tài khoản của chính mình.")
    changes: dict[str, Any] = {}
    if body.role is not None:
        user.bank_code = _bank_code_for(session, body.role, body.bank_code or user.bank_code)
        user.role = body.role
        changes.update(role=body.role, bank_code=user.bank_code)
    if body.active is not None:
        user.active = body.active
        changes["active"] = body.active
    if body.active is False or body.role is not None:
        session.execute(update(BuSession).where(BuSession.user_id == user.id, BuSession.revoked_at.is_(None))
                        .values(revoked_at=utcnow()))
    events.log(session, "system", "admin", "user_updated", f"Cập nhật tài khoản {user.email}",
               {"user_id": user.id, "by": admin.id, "changes": changes})
    session.commit()
    return {"user": admin_user_view(user)}


@router.get("/audit")
def audit(
    limit: int = Query(default=100, ge=1, le=500),
    actor: str | None = None,
    _: BuUser = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> dict:
    stmt = select(BuEvent).order_by(BuEvent.id.desc()).limit(limit)
    if actor:
        stmt = stmt.where(BuEvent.actor == actor)
    return {"items": [{"id": e.id, "application_id": e.application_id, **events.event_public(e)}
                      for e in session.scalars(stmt)]}


class SwitchIn(BaseModel):
    enabled: bool = True
    note: str = Field(default="", max_length=500)
    mode: Literal["manual", "auto"] = "manual"


@router.put("/auto-approval/{group}")
def put_auto_approval(
    group: str,
    body: SwitchIn,
    admin: BuUser = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> dict:
    """Switch auto-approval of a group (``<industry>|t<tier>``) on/off by hand, or hand it
    back to the NPL rule (``mode: "auto"``)."""
    from app.api.loans import switch_view

    if "|t" not in group or len(group) > 64:
        raise api_error(400, "VALIDATION_ERROR", "Nhóm có dạng <ngành>|t<tầng>, ví dụ “thời trang|t2”.",
                        {"field": "group"})
    row = session.get(BuAutoSwitch, group)
    if row is None:
        row = BuAutoSwitch(group_key=group, enabled=True, manual=False, reason="", updated_at=utcnow())
        session.add(row)
    if body.mode == "auto":
        row.manual = False
        session.flush()
        refresh_auto_switch(session, active_params(session))
    else:
        row.manual, row.enabled = True, body.enabled
        row.reason = body.note.strip() or ("Bật bằng tay" if body.enabled else "Tắt bằng tay")
        row.updated_at = utcnow()
    events.log(session, "system", "admin", "auto_approval_switch",
               f"Duyệt tự động nhóm {group}: {'bật' if row.enabled else 'tắt'} ({body.mode})",
               {"group": group, "enabled": row.enabled, "mode": body.mode, "by": admin.id, "note": body.note[:500]})
    session.commit()
    return switch_view(row)
