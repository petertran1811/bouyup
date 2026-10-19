"""/v4/webank: notifications from WeBank core banking (17/10/2026).

``POST /v4/webank/inflows`` — money reached a borrower's WeBank business account (a platform settlement,
a transfer). WeBank signs the body (``X-WeBank-Signature``: HMAC-SHA256 with ``WEBANK_WEBHOOK_SECRET``),
or a signed-in WeBank bank user posts it. The amount is credited to the open loan that services that
account; anything due is debited at once by the standing order; the seller's app shows a notification.
The payout id makes it idempotent (a re-sent notification is never counted twice).

``POST /v4/webank/outflows`` (SELLER_SERVICES_PLAN §3.3) — money left the business account (paid to a
supplier, salaries, ads, shipping, tax …). Same signature rule. BuoyUp only mirrors it: the simulated balance
goes down, the transfer is put in an expense group from its memo and payee; nothing is paid from here.
Idempotent on ``transfer_id``.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import agent4b_monitor as agent4
from app.autopilot import loop as autopilot
from app.platform.config import settings
from app.platform.db.session import get_session
from app.platform.errors import api_error
from app.platform.security import current_user_optional
from app.platform.tables import BuLoan, BuUser

router = APIRouter(prefix="/webank", tags=["v4-webank"])


class InflowIn(BaseModel):
    account_number: str = Field(min_length=6, max_length=20, pattern=r"^\d+$")
    amount: int = Field(gt=0, le=100_000_000)
    payout_id: str = Field(min_length=4, max_length=80)
    source: str = Field(default="", max_length=40, description="douyin, taobao, … or the payer's name")


class PayeeIn(BaseModel):
    kind: str = Field(default="", max_length=20, description="supplier, individual, platform, tax, bank, …")
    name: str = Field(default="", max_length=80)


class OutflowIn(BaseModel):
    account_number: str = Field(min_length=6, max_length=20, pattern=r"^\d+$")
    amount: int = Field(gt=0, le=100_000_000)
    transfer_id: str = Field(min_length=4, max_length=80)
    payee: PayeeIn = Field(default_factory=PayeeIn)
    memo: str = Field(default="", max_length=120)


def loan_for_account(session: Session, number: str) -> BuLoan | None:
    for loan in session.scalars(select(BuLoan).where(BuLoan.status.in_(agent4.OPEN_STATUSES))
                                .order_by(BuLoan.created_at.desc())):
        if str(((loan.doc or {}).get("account") or {}).get("number") or "") == number:
            return loan
    return None


def credit(session: Session, loan: BuLoan, amount: int, payout_id: str, source: str,
           on: date | None = None) -> dict[str, Any]:
    """Credit a platform payout (``on``: its business day, default the loan's clock); idempotent on ``payout_id``."""
    with agent4.LOAN_LOCK:
        session.refresh(loan)
        seen = payout_id in ((loan.doc or {}).get("payout_ids") or [])
        loan = agent4.simulate_inflow(session, loan, amount, payout_id, source, on=on)
    acc = (loan.doc or {}).get("account") or {}
    return {"credited": not seen, "balance": int(acc.get("balance") or 0),
            "loan_id": loan.id, "status": loan.status}


def _signed(raw: bytes, signature: str) -> bool:
    secret = settings.webank_webhook_secret.strip()
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def debit(session: Session, loan: BuLoan, amount: int, transfer_id: str, payee: dict[str, Any] | None,
          memo: str, source: str = "webank", on: date | None = None) -> dict[str, Any]:
    """Mirror a transfer out of the business account (no money is moved here)."""
    with agent4.LOAN_LOCK:
        session.refresh(loan)
        out = agent4.record_outflow(session, loan, amount, transfer_id, payee=payee, memo=memo, source=source, on=on)
    return {**out, "status": loan.status}


async def _from_webank(request: Request, user: BuUser | None) -> None:
    raw = await request.body()
    by_bank_user = user is not None and user.role == "bank" and (user.bank_code or "").upper() == "WEBANK"
    if not (_signed(raw, request.headers.get("X-WeBank-Signature", "")) or by_bank_user):
        raise api_error(401, "UNAUTHORIZED", "Thông báo không có chữ ký hợp lệ của WeBank.")


@router.post("/outflows")
async def outflow(request: Request, body: OutflowIn, session: Session = Depends(get_session),
                  user: BuUser | None = Depends(current_user_optional)) -> dict:
    await _from_webank(request, user)
    loan = loan_for_account(session, body.account_number)
    if loan is None:
        raise api_error(404, "NOT_FOUND", "Không có khoản vay đang mở cho tài khoản này.")
    out = debit(session, loan, body.amount, body.transfer_id, body.payee.model_dump(), body.memo)
    session.commit()
    if out.get("recorded") and autopilot.enabled():  # SELLER_SERVICES_PLAN §5.3: reassess at once (low balance)
        try:
            autopilot.assess_loan(loan.id, "chi tiền")
        except Exception:  # noqa: BLE001 - the outflow is recorded; the next round reassesses
            pass
    return out


@router.post("/inflows")
async def inflow(request: Request, body: InflowIn, session: Session = Depends(get_session),
                 user: BuUser | None = Depends(current_user_optional)) -> dict:
    await _from_webank(request, user)
    loan = loan_for_account(session, body.account_number)
    if loan is None:
        raise api_error(404, "NOT_FOUND", "Không có khoản vay đang mở cho tài khoản này.")
    out = credit(session, loan, body.amount, body.payout_id, body.source)
    session.commit()
    return out
