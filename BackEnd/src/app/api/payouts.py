"""/v4/regions and staff payouts: manual withdrawal, decrypted list, verification (Agent 4 duties).

A manual withdrawal is a payout made by a person (officer/admin) with a required
reason, e.g. when the agent run failed after approval. It is validated like Agent
4's split (B12 rules: ≤2 decimals, total exactly 100.00 %, banks of the region with
a key, each share ≥ the minimum and within the bank's remaining limit) but it is
not a loan: no bank limit is reserved. ``demo: true`` caps the amount (10.000.000
VND / 50.000 CNY, as the chain service does) and records the requester ``DEMO``.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform.errors import api_error
from app.blockchain import chain
from app.blockchain import chain_remote
from app.platform import events
from app.data_sources import sources
from app.blockchain import withdrawals
from app.banks.split import BP_TOTAL, MASTER_CODE, split_largest_remainder, validate_split
from app.core.params import active_params
from app.platform.security import current_user, require_roles
from app.platform.tables import BuBank, BuUser, BuWithdrawal
from app.platform.db.session import get_session

router = APIRouter(tags=["v4-payouts"])

_STAFF = ("officer", "admin")
DEMO_CAP = {"VND": 10_000_000, "CNY": 50_000}


class ShareIn(BaseModel):
    bank: str = Field(min_length=1, max_length=16)
    pct: float = Field(gt=0, le=1)


class ManualIn(BaseModel):
    requestId: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._:\-]+$")
    user: str = Field(min_length=1, max_length=80)
    account: str = Field(min_length=1, max_length=64)
    amount: int = Field(gt=0, le=100_000_000_000)
    currency: Literal["CNY", "VND"]
    region: Literal["CN", "VN"]
    province: str = Field(min_length=1, max_length=40)
    split: list[ShareIn] = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=3, max_length=500)
    demo: bool = False


@router.get("/regions")
def regions(_: BuUser = Depends(current_user)) -> dict:
    """Regions and provinces (same codes as the chain service)."""
    if chain.mode() == "remote":
        try:
            data = chain_remote.get_remote().regions()
        except chain_remote.ChainUnavailable as exc:
            raise chain.unavailable(exc) from exc
        return {"regions": [{"code": r.get("code"), "name": r.get("name"), "currency": r.get("currency"),
                             "provinces": [{"code": p.get("code"), "name": p.get("name")}
                                           for p in r.get("provinces") or []]} for r in data.get("regions") or []],
                "source": "remote"}
    return {"regions": sources.REGIONS, "source": "local"}


def _master_key(session: Session) -> str:
    master = session.get(BuBank, MASTER_CODE)
    return master.private_key_demo if master is not None else ""


def _remote_staff_view(row: BuWithdrawal) -> dict[str, Any]:
    try:
        data = chain_remote.get_remote().get_withdrawal(row.id)
    except chain_remote.ChainUnavailable as exc:
        raise chain.unavailable(exc) from exc
    currency = str(data.get("currency") or "")
    actor = data.get("actor") or {}
    return {
        "amount": chain_remote.from_minor(int(data.get("amount") or 0), currency), "currency": currency,
        "region": data.get("region"), "province": data.get("province"),
        "requester": actor.get("agentId") or actor.get("role"), "reason": None,
        "shares": [{"bank": leg.get("bank"), "pct": round(float(leg.get("percent") or 0) / 100, 4),
                    "amount": chain_remote.from_minor(int(leg.get("amount") or 0), currency),
                    "contract_id": leg.get("contractNo")} for leg in data.get("legs") or []],
        "locked": False,
    }


def staff_view(session: Session, row: BuWithdrawal) -> dict[str, Any]:
    """Public record + the plaintext opened with the platform master key (demo envs
    hold it; production has it in an HSM, so the row stays ``locked``)."""
    base = {**withdrawals.public_view(row, detail=True), "request_id": row.request_id, "loan_id": row.loan_id}
    if withdrawals.is_remote(row):
        return {**base, **_remote_staff_view(row)}
    key = _master_key(session)
    if not key:
        return {**base, "locked": True}
    opened = withdrawals.decrypt(row, key)
    summary = opened["pieces"].get("summary") or {}
    shares = [{k: piece.get(k) for k in ("bank", "pct", "amount", "contract_id")}
              for name, piece in opened["pieces"].items() if name != "summary"]
    return {**base, **{k: summary.get(k) for k in ("amount", "currency", "region", "province", "requester")},
            "reason": summary.get("reason"), "shares": shares, "fingerprints_ok": opened["fingerprints_ok"],
            "locked": False}


@router.post("/withdrawals/manual", status_code=201)
def manual_withdrawal(body: ManualIn, user: BuUser = Depends(require_roles(*_STAFF)),
                      session: Session = Depends(get_session)) -> dict:
    if sources.REGION_CURRENCY[body.region] != body.currency:
        raise api_error(400, "VALIDATION_ERROR", f"Khu vực {body.region} chi bằng {sources.REGION_CURRENCY[body.region]}.",
                        {"field": "currency"})
    province = sources.province_code(body.region, body.province)
    if province is None:
        raise api_error(400, "VALIDATION_ERROR", "Tỉnh/thành không có trong danh mục của khu vực.",
                        {"field": "province"})
    if body.demo and body.amount > DEMO_CAP[body.currency]:
        raise api_error(400, "VALIDATION_ERROR",
                        f"Lệnh chi thủ công tối đa {DEMO_CAP[body.currency]:,} {body.currency}.".replace(",", "."),
                        {"field": "amount", "max": DEMO_CAP[body.currency]})
    bps = [round(s.pct * BP_TOTAL) for s in body.split]
    amounts = split_largest_remainder(body.amount, bps) if sum(bps) == BP_TOTAL else [0] * len(bps)
    banks = {b.code: b for b in session.scalars(select(BuBank))}
    shares = [{"bank": s.bank.upper(), "pct": s.pct, "amount": a,
               "contract_id": getattr(banks.get(s.bank.upper()), "contract_id", "")}
              for s, a in zip(body.split, amounts)]
    problems = validate_split(session, region=body.region, amount=body.amount, shares=shares,
                              params=active_params(session))
    if problems:
        raise api_error(400, "VALIDATION_ERROR", "Phương án chia không hợp lệ.", {"problems": problems})
    requester = "DEMO" if body.demo else f"staff:{user.id}"
    try:
        row = withdrawals.create_withdrawal(
            session, request_id=body.requestId, amount=body.amount, currency=body.currency, region=body.region,
            province=province, user=body.user, account=body.account,
            payout_ref=withdrawals.reference_code("manual", body.requestId), requester=requester,
            shares=shares, reason=body.reason.strip(),
        )
    except chain_remote.ChainUnavailable as exc:
        raise chain.unavailable(exc) from exc
    events.log(session, "system", user.role, "manual_withdrawal",
               f"Lệnh giải ngân thủ công {row.id}",
               {"withdrawal_id": row.id, "by": user.id, "request_id": body.requestId})
    session.commit()
    return staff_view(session, row)


@router.get("/withdrawals")
def staff_withdrawals(limit: int = Query(default=50, ge=1, le=200), _: BuUser = Depends(require_roles(*_STAFF)),
                      session: Session = Depends(get_session)) -> dict:
    rows = session.scalars(select(BuWithdrawal).order_by(BuWithdrawal.created_at.desc()).limit(limit))
    return {"items": [staff_view(session, row) for row in rows]}


@router.get("/withdrawals/{wid}/verify")
def verify_withdrawal(wid: str, _: BuUser = Depends(require_roles(*_STAFF)),
                      session: Session = Depends(get_session)) -> dict:
    row = session.get(BuWithdrawal, wid)
    if row is None:
        raise api_error(404, "NOT_FOUND", "Không tìm thấy lệnh giải ngân.")
    if withdrawals.is_remote(row):
        result = withdrawals.remote_verification(row)
        checks = {c.get("name"): bool(c.get("ok")) for c in result.get("checks") or []}
        ref = result.get("chain") or {}
        return {"id": row.id, "ok": bool(result.get("valid")), "merkle_ok": checks.get("root_matches_commitments"),
                "fingerprints_ok": checks.get("pieces_match_commitments"),
                "split_total_pct": 100.0 if checks.get("ratios_total_100") else None,
                "amounts_ok": checks.get("amounts_total"), "record_ok": checks.get("recorded_on_chain"),
                "nodes": [{"id": c.get("node"), "holds": bool(c.get("confirmed"))} for c in ref.get("confirmations") or []],
                "checks": result.get("checks") or [], "simulated": False}
    merkle_ok = withdrawals.merkle_root(list(row.piece_fingerprints or [])) == row.merkle_root
    record_ok = withdrawals.verify_record(session, row)
    key = _master_key(session)
    fingerprints_ok = split_total = amounts_ok = None
    if key:
        opened = withdrawals.decrypt(row, key)
        fingerprints_ok = bool(opened["fingerprints_ok"])
        bank_pieces = [p for name, p in opened["pieces"].items() if name != "summary"]
        split_total = round(sum(round(float(p["pct"]) * BP_TOTAL) for p in bank_pieces) / 100, 2)
        summary = opened["pieces"].get("summary") or {}
        amounts_ok = sum(int(p["amount"]) for p in bank_pieces) == int(summary.get("amount", -1))
    ok = merkle_ok and record_ok and fingerprints_ok is not False and split_total in (None, 100.0) \
        and amounts_ok is not False
    return {"id": row.id, "ok": ok, "merkle_ok": merkle_ok, "fingerprints_ok": fingerprints_ok,
            "split_total_pct": split_total, "amounts_ok": amounts_ok, "record_ok": record_ok,
            "nodes": [{"id": n, "holds": record_ok} for n in chain.NODES], "simulated": True}
