"""/v4/chain: explorer, encrypted withdrawals, integrity checks (contract §8).

Local mode simulates FISCO BCOS (4 nodes, PBFT); responses carry
``simulated: true`` unless a remote chain is configured."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform.errors import api_error
from app.blockchain import chain
from app.blockchain import chain_remote
from app.blockchain import chain_sync
from app.blockchain import withdrawals
from app.banks.split import MASTER_CODE, get_bank
from app.platform.security import current_user, require_roles
from app.platform.tables import BuApplication, BuBank, BuChainBlock, BuChainKey, BuChainOutbox, BuLoan, BuUser, BuWithdrawal
from app.platform.config import settings
from app.platform.db.session import get_session

router = APIRouter(prefix="/chain", tags=["v4-chain"])

_DEMO_ENVS = ("dev", "demo", "test")
KEY_HELD_BY_BANK = "Khóa riêng do ngân hàng tự giữ; dán khóa để giải mã"


class DecryptIn(BaseModel):
    private_key_hex: str | None = Field(default=None, max_length=128)


def _withdrawal_or_404(session: Session, wid: str, user: BuUser) -> BuWithdrawal:
    row = session.get(BuWithdrawal, wid)
    if row is None or (user.role == "seller" and wid not in _seller_refs(session, user)):
        raise api_error(404, "NOT_FOUND", "Không tìm thấy lệnh giải ngân.")
    return row


def _seller_refs(session: Session, user: BuUser) -> set[str]:
    """Chain refs a seller may see: own application ids and own withdrawal ids."""
    apps = set(session.scalars(select(BuApplication.id).where(BuApplication.seller_user_id == user.id)))
    wds = session.scalars(select(BuLoan.withdrawal_id).where(BuLoan.seller_user_id == user.id))
    return apps | {w for w in wds if w}


@router.get("/status")
def chain_status(_: BuUser = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    out = chain.status(session)
    out["withdrawals"] = len(session.scalars(select(BuWithdrawal.id)).all())
    return out


def _visible_txs(txs: list[dict], own: set[str] | None) -> list[dict]:
    if own is None:
        return txs
    return [{**t, "ref": t.get("ref") if t.get("ref") in own else None} for t in txs]


@router.get("/blocks")
def chain_blocks(
    limit: int = Query(default=20, ge=1, le=200),
    user: BuUser = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    rows = session.scalars(select(BuChainBlock).order_by(BuChainBlock.height.desc()).limit(limit))
    own = _seller_refs(session, user) if user.role == "seller" else None
    return {
        "items": [{"height": b.height, "hash": b.hash, "prev": b.prev, "sealer": b.sealer,
                   "txs": _visible_txs(b.txs or [], own), "at": chain._iso(b.at) + "Z"} for b in rows],
        # These are the platform's local blocks (the simulation), also in remote mode.
        "simulated": True,
    }


@router.get("/withdrawals")
def list_withdrawals(
    limit: int = Query(default=50, ge=1, le=200),
    user: BuUser = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    stmt = select(BuWithdrawal).order_by(BuWithdrawal.created_at.desc()).limit(limit)
    if user.role == "seller":
        stmt = stmt.where(BuWithdrawal.id.in_(_seller_refs(session, user)))
    return {"items": [withdrawals.public_view(w) for w in session.scalars(stmt)]}


@router.get("/withdrawals/{wid}")
def get_withdrawal(wid: str, user: BuUser = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    row = _withdrawal_or_404(session, wid, user)
    return {**withdrawals.public_view(row, detail=True),
            "merkle_ok": withdrawals.merkle_root(list(row.piece_fingerprints or [])) == row.merkle_root,
            "record_ok": withdrawals.verify_record(session, row)}


DECRYPT_SCRIPT = Path(__file__).resolve().parent.parent / "static" / "decrypt_withdrawal.py"


@router.get("/decrypt_withdrawal.py", response_class=PlainTextResponse)
def decrypt_script() -> PlainTextResponse:
    """Standalone verifier for the UI's "Tự giải mã" section (public: holds no secret)."""
    return PlainTextResponse(DECRYPT_SCRIPT.read_text(encoding="utf-8"), media_type="text/x-python")


@router.get("/withdrawals/{wid}/envelope")
def get_envelope(wid: str, user: BuUser = Depends(current_user), session: Session = Depends(get_session)) -> dict:
    """The ciphertext record exactly as anchored (input of decrypt_withdrawal.py)."""
    row = _withdrawal_or_404(session, wid, user)
    if withdrawals.is_remote(row):
        raise api_error(400, "INVALID_STATE", "Lệnh này nằm trên chuỗi remote: tải bản mã và script ở "
                                              f"{chain_remote.get_remote().base_url}/explorer/.", {"remote": True})
    return {"id": row.id, "envelope": row.envelope, "piece_fingerprints": row.piece_fingerprints,
            "merkle_root": row.merkle_root, "tx": row.tx, "block": row.block}


def _default_key(session: Session, user: BuUser, row: BuWithdrawal) -> str:
    """Demo-held key of the caller (bank: own key, admin: master key) that matches the
    record (chain service key for a remote withdrawal). Outside dev/demo/test the
    server holds no private key, so one must be pasted."""
    holder = get_bank(session, user.bank_code or "") if user.role == "bank" else (
        session.get(BuBank, MASTER_CODE) if user.role == "admin" else None)
    if holder is not None:
        key = chain_sync.demo_private_key(session, holder.code, remote_record=withdrawals.is_remote(row))
        if key:
            return key
    raise api_error(400, "VALIDATION_ERROR", KEY_HELD_BY_BANK, {"field": "private_key_hex"})


@router.post("/withdrawals/{wid}/decrypt")
def decrypt_withdrawal(
    wid: str,
    body: DecryptIn | None = None,
    user: BuUser = Depends(require_roles("bank", "officer", "admin")),
    session: Session = Depends(get_session),
) -> dict:
    row = _withdrawal_or_404(session, wid, user)
    key = (body.private_key_hex if body else None) or _default_key(session, user, row)
    return {"id": row.id, **withdrawals.decrypt_any(row, key)}


@router.get("/cases/{application_id}/verify")
def verify_case(
    application_id: str,
    _: BuUser = Depends(require_roles("officer", "admin")),
    session: Session = Depends(get_session),
) -> dict:
    entries = chain.case_entries(session, application_id)
    out = {**chain.verify_case(session, application_id), "chain": chain.public_entries(session, entries)}
    if chain.mode() == "remote":
        try:
            remote = chain_remote.get_remote().verify_case(application_id)
        except chain_remote.ChainUnavailable as exc:
            raise chain.unavailable(exc) from exc
        out["remote"] = remote
        out["ok"] = out["ok"] and remote["valid"]
    return out


@router.post("/sync")
def sync_catalog(
    user: BuUser = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> dict:
    """Pull the partner banks' limits, written policies, contracts and keys from the
    chain service (remote mode). Also runs at startup."""
    if chain.mode() != "remote":
        raise api_error(400, "INVALID_STATE", "Chỉ đồng bộ được khi nối chuỗi thật (BUOYUP_CHAIN_BACKEND=remote).")
    try:
        result = chain_sync.sync_catalog(session, actor=user.id)
    except chain_remote.ChainUnavailable as exc:
        chain_sync.note_failure(exc)
        raise chain.unavailable(exc) from exc
    session.commit()
    return result


@router.post("/outbox/flush")
def flush_outbox(
    _: BuUser = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> dict:
    """Retry remote-chain writes that failed (anchors, pending disbursements)."""
    result = chain.flush_outbox(session)
    session.commit()
    return result


@router.get("/outbox")
def list_outbox(
    status: str | None = Query(default=None, max_length=10),
    _: BuUser = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> dict:
    stmt = select(BuChainOutbox).order_by(BuChainOutbox.id.desc()).limit(200)
    if status:
        stmt = stmt.where(BuChainOutbox.status == status)
    return {"items": [chain.outbox_view(r) for r in session.scalars(stmt)]}


@router.get("/verify")
def verify_everything(
    _: BuUser = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> dict:
    result = chain.verify_all(session)
    bad = withdrawals.verify_withdrawals(session)
    return {**result, "ok": result["ok"] and not bad, "broken_withdrawals": bad}


@router.get("/keys")
def demo_keys(
    _: BuUser = Depends(require_roles("admin")),
    session: Session = Depends(get_session),
) -> dict:
    if settings.app_env not in _DEMO_ENVS:
        raise api_error(404, "NOT_FOUND", "Không hiển thị khóa ở môi trường hiện tại.")
    rows = session.scalars(select(BuBank).order_by(BuBank.region, BuBank.code))
    held = {k.bank: k for k in session.scalars(select(BuChainKey))}

    def chain_keys(code: str) -> dict:  # what the chain service encrypts remote withdrawals to
        k = held.get(code)
        return {"chain_public_key": k.public_key, "chain_private_key_hex": k.private_key_demo} if k else {}

    return {
        "items": [{"code": b.code, "name": b.name, "region": b.region, "master": b.code == MASTER_CODE,
                   "public_key": b.public_key, "private_key_hex": b.private_key_demo, **chain_keys(b.code)}
                  for b in rows],
        "warning": "Lưu ý: khi vận hành chính thức, ngân hàng tự giữ khóa riêng, khóa chủ nằm trong HSM/KMS.",
    }
