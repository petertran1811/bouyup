"""Agent 4a · Giải ngân (review item 3, 16/10/2026): high privilege, used once.

Split from monitoring (:mod:`app.agents.agent4b_monitor`): a process that watches a loan for months must
not hold the power to pay out. 4a runs only when a contract is signed (or an officer re-authorizes a
payout), acts under the ``agent4a`` role (:mod:`app.platform.capabilities`) and needs a one-off payout
grant (``BuPayoutGrant``) bound to the application, the amount and the payee, valid
``payout.token_ttl_min`` minutes. The grant is revoked as soon as the payout is recorded; a retry after
it expired goes to an officer instead of being retried on its own.

- :func:`disburse` — Stage 5: each bank transfers its share into the escrow account at WeBank; once the
  full amount is there the money goes out in one order: up to 100.000 tệ to the borrower's WeBank
  business account, the rest straight to the supplier. Contract, decision and payout hashes go on the chain.
- :func:`issue_grant` / :func:`reauthorize` — the orchestrator (contract signed) or an officer grants it.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.agent4b_monitor import _create_loan, _n, _set_app_status
from app.blockchain import chain
from app.blockchain.chain_remote import ChainUnavailable
from app.blockchain.withdrawals import create_withdrawal, reference_code
from app.core.params import active_params
from app.data_sources import consent as consent_mod
from app.data_sources import sources
from app.platform import capabilities, events
from app.platform.db.tables import utcnow
from app.platform.errors import api_error
from app.platform.tables import BuApplication, BuChainOutbox, BuLoan, BuPayoutGrant, save_json

# --- one-off payout grants ---------------------------------------------------------

def _payee_hash(amount: int, payee: dict[str, Any]) -> str:
    raw = json.dumps({"amount": int(amount), "payee": payee}, ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def issue_grant(session: Session, app_row: BuApplication, by: str) -> BuPayoutGrant:
    """A grant for this application's signed contract; any older live grant is revoked first."""
    contract = (app_row.doc or {}).get("contract") or {}
    if not contract.get("signed_at"):
        raise api_error(400, "INVALID_STATE", "Hợp đồng chưa được ký; không cấp quyền giải ngân.")
    now = utcnow()
    for old in _grants(session, app_row.id):
        if old.revoked_at is None:
            old.revoked_at, old.revoked_why = now, "replaced"
    ttl = int(active_params(session)["payout"]["token_ttl_min"])
    grant = BuPayoutGrant(id="pg_" + secrets.token_hex(8), application_id=app_row.id, amount=int(contract["amount"]),
                          payee_hash=_payee_hash(contract["amount"], contract.get("payee") or {}), issued_by=by,
                          issued_at=now, expires_at=now + timedelta(minutes=ttl))
    session.add(grant)
    session.flush()
    events.log(session, app_row.id, "agent4a", "payout_grant",
               f"Cấp quyền giải ngân một lần ({ttl} phút) cho {_n(grant.amount)}", {"grant_id": grant.id, "by": by})
    return grant


def _grants(session: Session, app_id: str) -> list[BuPayoutGrant]:
    return list(session.scalars(select(BuPayoutGrant).where(BuPayoutGrant.application_id == app_id)
                                .order_by(BuPayoutGrant.issued_at.desc())))


def live_grant(session: Session, app_row: BuApplication) -> BuPayoutGrant | None:
    """The grant 4a may use now: not used, not revoked, not expired, same amount and payee as the contract."""
    contract = (app_row.doc or {}).get("contract") or {}
    want = _payee_hash(contract.get("amount") or 0, contract.get("payee") or {})
    now = utcnow()
    for g in _grants(session, app_row.id):
        if g.used_at is None and g.revoked_at is None and g.expires_at > now and g.payee_hash == want:
            return g
    return None


def reauthorize(session: Session, app_row: BuApplication, officer_id: str) -> BuLoan | None:
    """An officer grants a new one-off payout after a failure or an expired grant, then 4a runs once."""
    if app_row.loan_id:
        raise api_error(400, "INVALID_STATE", "Hồ sơ đã giải ngân.")
    issue_grant(session, app_row, by=officer_id)
    if app_row.status == "escalated":
        _set_app_status(app_row, "signed")
    return disburse_or_queue(session, app_row)


class PayoutNotAuthorized(Exception):
    """No live one-off grant for this payout (expired, used, revoked or never issued)."""


# --- Stage 5: escrow and payout ---------------------------------------------------

class SupplierCheckFailed(Exception):
    """The light check right before the payout did not pass."""

    def __init__(self, result: dict[str, Any]) -> None:
        super().__init__("pre-payout check failed")
        self.result = result


def check_before_payout(session: Session, app_row: BuApplication, doc: dict[str, Any]) -> dict[str, Any]:
    """Stage 4 light check before the money moves: consent still valid, the payee is the one in the
    signed contract (an account swap after signing is the classic fraud), and a supplier receiving the
    part above 100.000 still has invoices with the borrower and is not in her linked group."""
    from app.platform.tables import BuChainEntry

    contract = doc.get("contract") or {}
    payee = contract.get("payee") or {}
    signed = session.scalar(select(BuChainEntry).where(BuChainEntry.case_id == app_row.id,
                                                       BuChainEntry.kind == "contract_signed")
                            .order_by(BuChainEntry.seq.desc()).limit(1))
    recorded = (signed.payload or {}).get("payee") if signed is not None else None
    out: dict[str, Any] = {"payee": payee, "account_match": recorded is None or recorded == payee,
                           "consent": consent_mod.blocked_reason(doc.get("consent"))}
    if payee.get("to_supplier"):
        data = (doc.get("internal") or {}).get("data") or {}
        name = str(payee.get("supplier") or "")
        info = sources.supplier_info(data, name) if data else {}
        links = sources.link_entities(data, [name]) if data else {"linked": []}
        out.update(exists=bool(info.get("invoice_history")), linked_to_seller=bool(links["linked"]))
    out["ok"] = (out["account_match"] and out["consent"] is None and out.get("exists", True)
                 and not out.get("linked_to_seller", False))
    return out


def _duties(doc: dict[str, Any]) -> list[dict[str, str]]:
    """Legal duties Agent 3 attached (AML-LTR-01 report in 5 working days, POL-05, …)."""
    return [{"code": item["code"], "action": item["action"]}
            for item in (doc.get("control") or {}).get("legal") or [] if item.get("action") and item.get("ok") is False]


def disburse(session: Session, app_row: BuApplication) -> BuLoan:
    """Escrow, then one payout order, then the loan. Idempotent: an application that already has a
    loan returns that loan. Only as ``agent4a`` and with a live one-off grant, which is revoked here."""
    if app_row.loan_id:
        existing = session.get(BuLoan, app_row.loan_id)
        if existing is not None:
            return existing
    doc = dict(app_row.doc or {})
    contract = doc.get("contract") or {}
    if not contract.get("signed_at") or not contract.get("legs"):
        raise api_error(400, "INVALID_STATE", "Hợp đồng chưa được ký; chưa giải ngân.")
    amount = int(contract["amount"])
    decision = doc.get("decision") or {}
    params = active_params(session)
    if int(decision.get("amount") or 0) >= int(params["gate"]["auto_limit"]) and decision.get("by") != "officer":
        raise api_error(400, "INVALID_STATE", "Hạn mức vượt ngưỡng duyệt tự động cần cán bộ duyệt trước khi giải ngân.",
                        {"limit": decision.get("amount"), "auto_limit": int(params["gate"]["auto_limit"])})
    check = check_before_payout(session, app_row, doc)
    if not check["ok"]:
        raise SupplierCheckFailed(check)
    capabilities.require("payout")
    grant = live_grant(session, app_row)
    if grant is None:
        raise PayoutNotAuthorized(app_row.id)
    legs = list(contract["legs"])
    escrow = chain.record(session, app_row.id, "escrow_funded", {
        "application": app_row.code, "escrow": "Tài khoản trung gian BuoyUp tại WeBank", "total": amount,
        "legs": [{k: leg[k] for k in ("bank", "amount", "contract_id")} for leg in legs]})
    events.log(session, app_row.id, "agent4", "escrow_funded",
               "Các ngân hàng chuyển phần vốn vào tài khoản trung gian tại WeBank: "
               + ", ".join(f"{leg['name']} {_n(leg['amount'])}" for leg in legs) + f" = {_n(amount)} (đủ)",
               {"legs": legs, "hidden_from_seller": False}, escrow.fingerprint)
    payee = contract["payee"]
    region = str(doc.get("region") or "CN")
    account = f"webank_business:{contract.get('webank_account', '')}"
    if payee.get("to_supplier"):
        account += f"|supplier:{payee.get('supplier')}"
    loan_id = "loan_" + secrets.token_hex(8)
    withdrawal = create_withdrawal(
        session, request_id="disburse:" + app_row.id, amount=amount, currency=str(doc.get("currency") or "CNY"),
        region=region, province=str(doc.get("province") or ""), user=app_row.seller_user_id, account=account,
        payout_ref=reference_code("payout", app_row.id), requester="agent4a", shares=legs)
    withdrawal.loan_id = loan_id
    loan = _create_loan(session, app_row, doc, loan_id, contract, withdrawal.id, params)
    _set_app_status(app_row, "disbursed", loan_id=loan_id)
    now = utcnow()
    grant.used_at, grant.revoked_at, grant.revoked_why = now, now, "used"  # 4a's privilege ends with the payout
    entry = chain.record(session, app_row.id, "disbursement", {
        "withdrawal_id": withdrawal.id, "merkle_root": withdrawal.merkle_root, "tx": withdrawal.tx,
        "loan_id": loan_id, "contract_hash": contract.get("hash"), "decision_tx": decision.get("chain_tx"),
        "escrow_tx": escrow.tx, "to_account": payee["to_account"], "to_supplier": payee["to_supplier"],
        "duties": _duties(doc), "grant": {"id": grant.id, "issued_by": grant.issued_by, "revoked": "used"}})
    events.log(session, app_row.id, "agent4", "disbursed",
               f"Giải ngân {_n(amount)} {loan.currency}: {_n(payee['to_account'])} vào tài khoản kinh doanh WeBank"
               + (f", {_n(payee['to_supplier'])} trả thẳng {payee['supplier']}" if payee.get("to_supplier") else ""),
               {"loan_id": loan_id, "withdrawal_id": withdrawal.id, "banks": [leg["bank"] for leg in legs]},
               entry.fingerprint)
    return loan


def release_reserved(session: Session, doc: dict[str, Any]) -> None:
    """A payout that will not happen gives back the room taken at signing (limit and monthly budget)."""
    from app.banks.syndicate import release_at_stop

    contract = doc.get("contract") or {}
    if contract.get("legs") and not contract.get("released_at"):
        release_at_stop(session, contract["legs"], contract.get("signed_at"))
        contract["released_at"] = utcnow().isoformat() + "Z"


def _escalate_payout(session: Session, app_row: BuApplication, why: str, detail: Any) -> None:
    doc = dict(app_row.doc or {})
    if why == "SUPPLIER_CHECK_FAILED" and isinstance(detail, dict) and detail.get("consent"):
        why = "CONSENT_INVALID"
    doc["escalation"] = {"why": why, "detail": detail, "at": utcnow().isoformat() + "Z"}
    release_reserved(session, doc)
    save_json(app_row, "doc", doc)
    _set_app_status(app_row, "escalated")
    events.log(session, app_row.id, "agent4", "disburse_stopped",
               {"SUPPLIER_CHECK_FAILED": "Kiểm nhà cung cấp lần cuối không đạt: dừng giải ngân, chuyển cán bộ",
                "CONSENT_INVALID": "Ủy quyền đã bị rút hoặc hết hạn trước khi giải ngân: dừng, trả lại hạn mức ngân hàng",
                "DISBURSE_FAILED": "Lệnh giải ngân bị từ chối hoặc hết lượt thử: chuyển cán bộ",
                "PAYOUT_GRANT_EXPIRED": "Quyền giải ngân một lần đã hết hạn hoặc không còn: cán bộ cấp lại"}.get(why, why),
               {"detail": detail, "hidden_from_seller": True})


def disburse_failed(session: Session, row: BuChainOutbox) -> None:
    """Outbox gave up on a payout (rejected by the chain service, or out of attempts): the case must
    not stay "approved" with no one looking at it (§6: báo cán bộ)."""
    app_row = session.get(BuApplication, str((row.payload or {}).get("application_id")))
    if app_row is not None and app_row.status == "signed" and not app_row.loan_id:
        _escalate_payout(session, app_row, "DISBURSE_FAILED", {"outbox_id": row.id, "error": row.last_error})


def disburse_pending(session: Session, row: BuChainOutbox) -> None:
    """Outbox job: an approved application whose payout failed on the remote chain.
    Same ``requestId`` (``disburse:<application>``), so a retry never pays twice."""
    app_row = session.get(BuApplication, str(row.payload.get("application_id")))
    if app_row is None:
        row.status, row.last_error = "failed", "application not found"
        return
    try:
        with capabilities.acting("agent4a"):
            loan = disburse(session, app_row)
    except PayoutNotAuthorized:
        # The one-off grant expired before the chain came back: an officer re-authorizes (no silent retry).
        row.status, row.last_error = "failed", "payout grant expired"
        _escalate_payout(session, app_row, "PAYOUT_GRANT_EXPIRED", {"outbox_id": row.id})
        return
    except SupplierCheckFailed as exc:
        row.status, row.last_error = "failed", "pre-payout check failed"
        _escalate_payout(session, app_row, "SUPPLIER_CHECK_FAILED", exc.result)
        return
    except HTTPException as exc:
        row.status, row.last_error = "failed", str(exc.detail)[:500]
        # The split chosen before the outage no longer fits (limit used up, bank inactive). It may
        # already sit at the remote under this requestId, so do not re-split silently: an officer decides.
        doc = dict(app_row.doc or {})
        doc["escalation"] = {"why": "DISBURSE_FAILED", "detail": str(exc.detail)[:300], "at": utcnow().isoformat() + "Z"}
        save_json(app_row, "doc", doc)
        _set_app_status(app_row, "escalated")
        events.log(session, app_row.id, "agent4", "disburse_failed",
                   "Giải ngân lại thất bại (phương án chia không còn hợp lệ); chuyển cán bộ",
                   {"outbox_id": row.id, "detail": str(exc.detail)[:300]})
        return
    row.status, row.remote_tx = "sent", loan.withdrawal_id or ""
    events.log(session, app_row.id, "agent4", "disbursed_retry", "Giải ngân lại thành công sau khi chuỗi phục hồi",
               {"loan_id": loan.id, "outbox_id": row.id})


def disburse_or_queue(session: Session, app_row: BuApplication) -> BuLoan | None:
    """Agent 4 after approval. Remote chain down → keep ``approved`` and queue the
    payout in the outbox (``POST /v4/chain/outbox/flush`` retries it)."""
    try:
        with capabilities.acting("agent4a"):
            return disburse(session, app_row)
    except PayoutNotAuthorized:
        _escalate_payout(session, app_row, "PAYOUT_GRANT_EXPIRED", None)
        return None
    except SupplierCheckFailed as exc:
        _escalate_payout(session, app_row, "SUPPLIER_CHECK_FAILED", exc.result)
        return None
    except ChainUnavailable as exc:
        chain.enqueue(session, app_row.id, "disburse", {"application_id": app_row.id}, str(exc))
        events.log(session, app_row.id, "agent4", "disbursement_pending",
                   "Chuỗi không truy cập được: lệnh giải ngân xếp hàng chờ gửi lại (cùng requestId)",
                   {"error": str(exc)[:300]})
        return None


