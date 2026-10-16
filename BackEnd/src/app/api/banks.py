"""/v4 bank catalog and the partner-bank portal (contract §7).

A bank user sees its own bank in full and only code/name/region/currency of
the others; it never sees another bank's amounts or limits."""

from __future__ import annotations

from typing import Any, Literal

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform.errors import api_error
from app.blockchain import chain
from app.blockchain import chain_remote
from app.blockchain import chain_sync
from app.platform import events
from app.blockchain import withdrawals
from app.banks.split import bank_view, catalog, get_bank
from app.core.params import active_params
from app.platform.security import current_user, require_roles
from app.platform.tables import BuApplication, BuBank, BuBankKey, BuLoan, BuLoanShare, BuUser, BuWithdrawal, save_json
from app.platform.db.session import get_session
from app.platform.db.tables import utcnow

router = APIRouter(tags=["v4-banks"])

GOODS_GROUPS = (
    "quần áo", "thực phẩm đóng gói", "thực phẩm rời", "thực phẩm chức năng", "dược", "thiết bị y tế I",
    "thiết bị y tế II", "thiết bị y tế III", "thuốc lá điện tử", "dịch thuốc lá điện tử", "điện tử", "khác",
)


class PolicyIn(BaseModel):
    """Partial policy update; omitted fields keep their value."""

    min_grade: Literal["A", "B", "C", "D", "E"] | None = None
    tiers: list[Literal[1, 2]] | None = Field(default=None, min_length=1, max_length=2)
    min_amount: int | None = Field(default=None, ge=0)
    max_amount: int | None = Field(default=None, ge=0)
    max_rate: float | None = Field(default=None, gt=0, le=0.36)
    excluded_groups: list[str] | None = Field(default=None, max_length=len(GOODS_GROUPS))
    min_share: float | None = Field(default=None, le=1.0)
    # Loan circle: what the bank's own (simulated) decision in the syndicate round looks at.
    exclude_industries: list[Literal["thời trang", "mỹ phẩm", "tạp hóa", "điện tử", "khác"]] | None = None
    borrower_types: list[Literal["individual_business", "company"]] | None = Field(default=None, min_length=1)
    max_tenor_m: int | None = Field(default=None, ge=3, le=36)
    max_late_days: int | None = Field(default=None, ge=0, le=90)

    @field_validator("excluded_groups")
    @classmethod
    def _known_groups(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(g not in GOODS_GROUPS for g in value):
            raise ValueError("excluded_groups chứa nhóm hàng không có trong danh mục")
        return value


def _own_or_admin(user: BuUser, code: str) -> None:
    if user.role == "admin":
        return
    if user.role == "bank" and (user.bank_code or "").upper() == code.upper():
        return
    raise api_error(403, "FORBIDDEN", "Bạn không có quyền với ngân hàng này.")


def _bank_or_404(session: Session, code: str) -> BuBank:
    bank = get_bank(session, code)
    if bank is None:
        raise api_error(404, "NOT_FOUND", "Không tìm thấy ngân hàng.")
    return bank


@router.get("/banks")
def list_banks(
    region: str | None = None,
    user: BuUser = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    items = []
    for bank in catalog(session, region.upper() if region else None):
        if user.role in ("officer", "admin") or (user.role == "bank" and user.bank_code == bank.code):
            items.append(bank_view(bank))
        elif user.role == "bank":
            items.append({**bank_view(bank, full=False), "currency": bank.currency, "active": bank.active})
        else:
            items.append(bank_view(bank, full=False))
    return {"items": items}


@router.get("/banks/{code}")
def get_bank_detail(
    code: str,
    user: BuUser = Depends(require_roles("officer", "admin", "bank")),
    session: Session = Depends(get_session),
) -> dict:
    if user.role == "bank":
        _own_or_admin(user, code)
    return bank_view(_bank_or_404(session, code))


@router.put("/banks/{code}/policy")
def put_policy(
    code: str,
    body: PolicyIn,
    user: BuUser = Depends(require_roles("admin", "bank")),
    session: Session = Depends(get_session),
) -> dict:
    _own_or_admin(user, code)
    bank = _bank_or_404(session, code)
    changes = body.model_dump(exclude_none=True)
    owned = sorted(set(changes) & set(chain_sync.CHAIN_KEYS))
    if owned and (bank.policy or {}).get("chain"):  # the next sync would silently undo the edit
        raise api_error(400, "VALIDATION_ERROR", "Trường này do danh mục trên chuỗi quản lý; đổi trên dịch vụ chuỗi.",
                        {"fields": owned})
    policy: dict[str, Any] = {**(bank.policy or {}), **changes}
    floor = float(active_params(session)["banks"]["min_share"])
    if float(policy.get("min_share", floor)) < floor - 1e-9:
        raise api_error(400, "VALIDATION_ERROR", f"Phần tối thiểu không được dưới {floor * 100:.0f}%.",
                        {"field": "min_share"})
    if int(policy.get("max_amount", 0)) < int(policy.get("min_amount", 0)):
        raise api_error(400, "VALIDATION_ERROR", "Số tiền tối đa phải lớn hơn hoặc bằng số tiền tối thiểu.",
                        {"field": "max_amount"})
    if "tiers" in changes:
        policy["tiers"] = sorted(set(changes["tiers"]))
    before = dict(bank.policy or {})
    save_json(bank, "policy", policy)
    entry = chain.record(session, "system", "bank_policy",
                         {"bank": bank.code, "before": before, "after": policy, "by": user.id})
    events.log(session, "system", user.role, "bank_policy", f"Cập nhật chính sách {bank.code}",
               {"bank": bank.code, "by": user.id, "changes": changes, "chain_tx": entry.tx}, entry.fingerprint)
    session.commit()
    return {**bank_view(bank), "policy_chain_tx": entry.tx}


class PublicKeyIn(BaseModel):
    public_key: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


@router.put("/banks/{code}/public-key")
def put_public_key(
    code: str,
    body: PublicKeyIn,
    user: BuUser = Depends(require_roles("admin", "bank")),
    session: Session = Depends(get_session),
) -> dict:
    """Register / rotate the bank's X25519 key. New withdrawals use it; older ones stay
    readable only with the key current then. Not written to the chain (the public
    record does not reveal a rotation); forwarded to the chain service in remote mode."""
    _own_or_admin(user, code)
    bank = _bank_or_404(session, code)
    key_hex = body.public_key.lower()
    try:
        X25519PublicKey.from_public_bytes(bytes.fromhex(key_hex))
    except ValueError:
        raise api_error(400, "VALIDATION_ERROR", "Khóa công khai phải là 32 byte X25519 (64 ký tự hex).",
                        {"field": "public_key"}) from None
    if key_hex == bank.public_key:
        raise api_error(400, "VALIDATION_ERROR", "Khóa này đang được dùng.", {"field": "public_key"})
    if chain.mode() == "remote":
        try:
            chain_remote.get_remote().put_bank_key(bank.code, key_hex)
        except chain_remote.ChainUnavailable as exc:
            raise chain.unavailable(exc) from exc
    now = utcnow()
    current = session.scalar(select(BuBankKey).where(BuBankKey.bank == bank.code, BuBankKey.retired_at.is_(None)))
    if current is None and bank.public_key:
        session.add(BuBankKey(bank=bank.code, public_key=bank.public_key, active_from=now, retired_at=now, by="seed"))
    elif current is not None:
        current.retired_at = now
    session.add(BuBankKey(bank=bank.code, public_key=key_hex, active_from=now, by=user.id))
    bank.public_key = key_hex
    # The server never holds the new private key; the demo key no longer matches.
    bank.private_key_demo = ""
    if chain.mode() == "remote":  # the service now encrypts new withdrawals to this key
        held = chain_sync.chain_key(session, bank.code)
        if held is not None:
            held.public_key, held.private_key_demo, held.synced_at = key_hex, "", now
    events.log(session, "system", user.role, "bank_key", f"{bank.code} đăng ký khóa mã hóa mới",
               {"bank": bank.code, "by": user.id})
    session.commit()
    history = session.scalars(select(BuBankKey).where(BuBankKey.bank == bank.code).order_by(BuBankKey.id))
    return {**bank_view(bank), "keys": [
        {"public_key": k.public_key, "active_from": k.active_from.isoformat() + "Z",
         "retired_at": k.retired_at.isoformat() + "Z" if k.retired_at else None} for k in history]}


# --- partner-bank portal -----------------------------------------------------

def _my_bank(session: Session, user: BuUser) -> BuBank:
    bank = get_bank(session, user.bank_code or "")
    if bank is None:
        raise api_error(403, "FORBIDDEN", "Tài khoản chưa gắn với ngân hàng đối tác.")
    return bank


@router.get("/bank/portfolio")
def bank_portfolio(
    user: BuUser = Depends(require_roles("bank")),
    session: Session = Depends(get_session),
) -> dict:
    bank = _my_bank(session, user)
    rows = session.execute(
        select(BuLoanShare, BuLoan).join(BuLoan, BuLoan.id == BuLoanShare.loan_id)
        .where(BuLoanShare.bank_code == bank.code).order_by(BuLoan.created_at.desc())
    ).all()
    shares = []
    for share, loan in rows:
        doc = loan.doc or {}
        due = round(share.pct * int(doc.get("total_due", 0)))
        shares.append({
            "loan_id": loan.id, "pct": share.pct, "amount": share.amount, "repaid": share.repaid,
            "outstanding": max(0, due - share.repaid), "status": loan.status, "contract_id": share.contract_id,
            "grade": doc.get("grade"), "rate": doc.get("rate"), "final_due_date": doc.get("final_due_date"),
            "early_warning": (doc.get("early_warning") or {}).get("level", "green"),
        })
    active = [s for s in shares if s["status"] != "closed"]
    return {
        "bank": bank_view(bank),
        "shares": shares,
        "totals": {
            "loans": len(shares), "active": len(active),
            "amount": sum(s["amount"] for s in shares), "repaid": sum(s["repaid"] for s in shares),
            "outstanding": sum(s["outstanding"] for s in active),
        },
        "simulated": True,
    }


@router.get("/bank/withdrawals")
def bank_withdrawals(
    limit: int = Query(default=50, ge=1, le=200),
    user: BuUser = Depends(require_roles("bank")),
    session: Session = Depends(get_session),
) -> dict:
    """Withdrawals funded by this bank. Opened server-side only when the demo key
    is held (dev/demo/test); in production the bank decrypts with its own key."""
    bank = _my_bank(session, user)
    rows = session.scalars(
        select(BuWithdrawal).join(BuLoanShare, BuLoanShare.loan_id == BuWithdrawal.loan_id)
        .where(BuLoanShare.bank_code == bank.code).order_by(BuWithdrawal.created_at.desc()).limit(limit)
    )
    down = [False]
    return {"items": [_bank_withdrawal_item(session, bank, wd, down) for wd in rows]}


# A remote record never changes, so its decryption for one key is cached (no repeat calls).
_REMOTE_OPENED: dict[tuple[str, str], dict[str, Any]] = {}


def _bank_withdrawal_item(session: Session, bank: BuBank, wd: BuWithdrawal, down: list[bool]) -> dict[str, Any]:
    base = withdrawals.public_view(wd)
    locked = {**base, "summary": None, "my_piece": None, "fingerprint_ok": None, "locked": True}
    remote = withdrawals.is_remote(wd)
    key = chain_sync.demo_private_key(session, bank.code, remote_record=remote)
    if not key or (remote and down[0] and (wd.id, key) not in _REMOTE_OPENED):
        return locked
    try:
        if remote:
            if (wd.id, key) not in _REMOTE_OPENED:
                _REMOTE_OPENED[(wd.id, key)] = withdrawals.decrypt_any(wd, key)
            result = _REMOTE_OPENED[(wd.id, key)]
        else:
            result = withdrawals.decrypt_any(wd, key)
    except HTTPException:  # the chain service is down: the rest of the page stays locked, no more waiting
        down[0] = True
        return locked
    pieces = result["pieces"]
    mine = pieces.get(bank.code)
    return {
        **base,
        "summary": {k: v for k, v in (pieces.get("summary") or {}).items() if k != "piece"} or None,
        "my_piece": {k: mine.get(k) for k in ("pct", "amount", "contract_id")} if mine else None,
        "fingerprint_ok": bool(result["fingerprints_ok"]),
        "locked": False,
    }


# --- loan circle, Stage 2: what this bank was asked in the syndicate rounds ------------------

@router.get("/bank/syndicate")
def bank_syndicate(
    user: BuUser = Depends(require_roles("bank")),
    session: Session = Depends(get_session),
) -> dict:
    """Every case the orchestrator sent this bank, with its own answer (and time) per round, and the
    final split. The bank's decision is simulated from its catalog policy in this demo."""
    bank = _my_bank(session, user)
    items = []
    rows = session.scalars(select(BuApplication).order_by(BuApplication.updated_at.desc()).limit(500))
    for app_row in rows:
        doc = app_row.doc or {}
        syn = doc.get("syndicate") or {}
        mine = [{"amount": r["amount"], **next(x for x in r["responses"] if x["bank"] == bank.code)}
                for r in syn.get("rounds") or [] if any(x["bank"] == bank.code for x in r["responses"])]
        share = next((s for s in syn.get("split") or [] if s["bank"] == bank.code), None)
        if not mine and share is None:
            continue
        offer = doc.get("offer") or {}
        items.append({"application": app_row.code, "status": app_row.status, "grade": offer.get("grade"),
                      "borrower_type": doc.get("borrower_type"), "province": doc.get("province"),
                      "industry": ((doc.get("internal") or {}).get("data") or {}).get("store", {}).get("industry"),
                      "rounds": mine, "result": syn.get("status"), "limit": syn.get("limit"), "share": share,
                      "expires_at": syn.get("expires_at"), "hash": syn.get("hash")})
        if len(items) >= 100:
            break
    return {"bank": bank.code, "items": items}
