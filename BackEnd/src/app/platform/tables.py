"""Persistence for BuoyUp v4 (multi-bank, five agents).

Registered on the shared ``Base`` so ``init_db()`` creates them with the rest.
An application is one JSON document (``doc``) whose sub-objects mirror the API
contract in ``BackEnd/API_config/API_CONTRACT_V4.md``; rows that are queried or
appended to on their own (messages, events, loans, repayments, chain) get
their own tables.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import copy

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm.attributes import flag_modified

from app.platform.db.tables import Base, utcnow


def save_json(row: Any, attr: str, value: Any) -> None:
    """Assign a JSON column so SQLAlchemy persists it.

    Plain ``JSON`` columns do not track in-place mutation: ``row.doc["x"] = 1``
    is silently lost. Always write JSON columns through this helper (or assign
    a new object) — e.g. ``save_json(app_row, "doc", doc)``.
    """
    setattr(row, attr, copy.deepcopy(value))
    flag_modified(row, attr)


class BuUser(Base):
    __tablename__ = "bu_users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    role: Mapped[str] = mapped_column(String(16), index=True)  # seller|officer|bank|admin
    bank_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BuSession(Base):
    """Opaque bearer tokens; only the SHA-256 of the token is stored."""

    __tablename__ = "bu_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(40), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BuLoginAttempt(Base):
    __tablename__ = "bu_login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    ok: Mapped[bool] = mapped_column(Boolean)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class BuRateEvent(Base):
    """Rate-limit ledger: key is "login:<email>|<ip>", "login-ip:<ip>" or "register:<ip>"."""

    __tablename__ = "bu_rate_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(300), index=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class BuBank(Base):
    __tablename__ = "bu_banks"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    region: Mapped[str] = mapped_column(String(4), index=True)  # CN | VN
    currency: Mapped[str] = mapped_column(String(4))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    limit_total: Mapped[int] = mapped_column(Integer, default=0)
    limit_used: Mapped[int] = mapped_column(Integer, default=0)
    policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    contract_id: Mapped[str] = mapped_column(String(40), default="")
    public_key: Mapped[str] = mapped_column(String(64), default="")
    # Demo only: in production the bank keeps its private key; the platform
    # stores the public key alone.
    private_key_demo: Mapped[str] = mapped_column(String(64), default="")


class BuApplication(Base):
    __tablename__ = "bu_applications"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    seller_user_id: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    tier: Mapped[int] = mapped_column(Integer, default=2)
    scenario: Mapped[str] = mapped_column(String(16), default="")
    doc: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    loan_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class BuMessage(Base):
    __tablename__ = "bu_messages"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    application_id: Mapped[str] = mapped_column(String(40), index=True)
    sender: Mapped[str] = mapped_column(String(12))  # seller|agent2|system
    text: Mapped[str] = mapped_column(Text, default="")
    card: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    blocked_numbers: Mapped[int] = mapped_column(Integer, default=0)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class BuEvent(Base):
    """Trace of who did what on an application (agents, gate, officer)."""

    __tablename__ = "bu_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[str] = mapped_column(String(40), index=True)
    actor: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    hash: Mapped[str] = mapped_column(String(80), default="")
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class BuLoan(Base):
    __tablename__ = "bu_loans"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    application_id: Mapped[str] = mapped_column(String(40), index=True)
    seller_user_id: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(12), index=True)  # active|closed|overdue
    currency: Mapped[str] = mapped_column(String(4), default="CNY")
    doc: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    repaid: Mapped[int] = mapped_column(Integer, default=0)
    outstanding: Mapped[int] = mapped_column(Integer, default=0)
    withdrawal_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BuLoanShare(Base):
    __tablename__ = "bu_loan_shares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    loan_id: Mapped[str] = mapped_column(String(40), index=True)
    bank_code: Mapped[str] = mapped_column(String(16), index=True)
    pct: Mapped[float] = mapped_column(Float)
    amount: Mapped[int] = mapped_column(Integer)
    repaid: Mapped[int] = mapped_column(Integer, default=0)
    contract_id: Mapped[str] = mapped_column(String(40), default="")


class BuRepayment(Base):
    __tablename__ = "bu_repayments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    loan_id: Mapped[str] = mapped_column(String(40), index=True)
    inflow: Mapped[int] = mapped_column(Integer)
    swept: Mapped[int] = mapped_column(Integer)
    split: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    chain_tx: Mapped[str] = mapped_column(String(80), default="")
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class BuAlert(Base):
    __tablename__ = "bu_alerts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    loan_id: Mapped[str] = mapped_column(String(40), index=True)
    level: Mapped[str] = mapped_column(String(8))  # yellow|red
    signals: Mapped[list[Any]] = mapped_column(JSON, default=list)
    text: Mapped[str] = mapped_column(Text, default="")
    acked: Mapped[bool] = mapped_column(Boolean, default=False)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class BuWithdrawal(Base):
    """Encrypted payout record: summary piece + one piece per funding bank."""

    __tablename__ = "bu_withdrawals"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    request_digest: Mapped[str] = mapped_column(String(64))
    loan_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    envelope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    piece_fingerprints: Mapped[list[str]] = mapped_column(JSON, default=list)
    merkle_root: Mapped[str] = mapped_column(String(80), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    tx: Mapped[str] = mapped_column(String(80), default="")
    block: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class BuChainBlock(Base):
    __tablename__ = "bu_chain_blocks"

    height: Mapped[int] = mapped_column(Integer, primary_key=True)
    hash: Mapped[str] = mapped_column(String(80))
    prev: Mapped[str] = mapped_column(String(80))
    sealer: Mapped[str] = mapped_column(String(12))
    txs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BuChainEntry(Base):
    """Per-case hash chain. ``payload`` + ``salt`` are the off-chain record kept
    by the platform so anyone holding them can recompute ``fingerprint``."""

    __tablename__ = "bu_chain_entries"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    salt: Mapped[str] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(String(80))
    head: Mapped[str] = mapped_column(String(80))
    tx: Mapped[str] = mapped_column(String(80))
    block: Mapped[int] = mapped_column(Integer, default=0)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BuReport(Base):
    __tablename__ = "bu_reports"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BuProposal(Base):
    __tablename__ = "bu_proposals"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    report_id: Mapped[str] = mapped_column(String(40), index=True)
    param: Mapped[str] = mapped_column(String(80))
    from_value: Mapped[Any] = mapped_column(JSON)
    to_value: Mapped[Any] = mapped_column(JSON)
    evidence: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(10), default="pending")
    decided_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


class BuParams(Base):
    __tablename__ = "bu_params"

    version: Mapped[str] = mapped_column(String(16), primary_key=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    hash: Mapped[str] = mapped_column(String(80))
    chain_tx: Mapped[str] = mapped_column(String(80), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    note: Mapped[str] = mapped_column(Text, default="")


class BuComplaint(Base):
    """A borrower's complaint (review item 4): received from the app, the hotline or email; the reasons
    of the decision complained about are attached at once; reviewed by an officer other than the one
    who decided; answered within the committed deadline (working days), else escalated to the lead."""

    __tablename__ = "bu_complaints"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    seller_user_id: Mapped[str] = mapped_column(String(40), index=True)
    application_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    loan_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    category: Mapped[str] = mapped_column(String(20))
    channel: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), index=True)
    reasons: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    decided_by: Mapped[str] = mapped_column(String(40), default="")
    assigned_to: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ack_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    answer_due: Mapped[datetime] = mapped_column(DateTime)
    max_due: Mapped[datetime] = mapped_column(DateTime)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    history: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class BuPayoutGrant(Base):
    """One-off payout grant for Agent 4a (review item 3): bound to one application, one amount and one
    payee (fingerprint), valid until ``expires_at``. Used once, then revoked; a payout without a live
    grant is refused. Issued when the contract is signed or by an officer re-authorizing a payout."""

    __tablename__ = "bu_payout_grants"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    application_id: Mapped[str] = mapped_column(String(40), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    payee_hash: Mapped[str] = mapped_column(String(80))
    issued_by: Mapped[str] = mapped_column(String(40))
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_why: Mapped[str] = mapped_column(String(40), default="")


class BuChainOutbox(Base):
    """Remote-chain writes (mirrored anchors, pending disbursements) and their state.

    ``status``: ``sent`` (remote tx stored), ``pending`` (to retry), ``failed``.
    Flushed by ``POST /v4/chain/outbox/flush``; retries reuse the same payload, so a
    withdrawal keeps its ``requestId`` and is never paid twice."""

    __tablename__ = "bu_chain_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    entry_seq: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(10), index=True, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    remote_tx: Mapped[str] = mapped_column(String(80), default="")
    remote_block: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BuBankKey(Base):
    """History of a bank's encryption keys (rotation). The newest row is current;
    older withdrawals stay readable only with the key current when they were made."""

    __tablename__ = "bu_bank_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bank: Mapped[str] = mapped_column(String(16), index=True)
    public_key: Mapped[str] = mapped_column(String(64))
    active_from: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    by: Mapped[str] = mapped_column(String(40), default="")


class BuChainKey(Base):
    """Encryption keys the remote chain service holds for each bank and the master
    (``chain_sync``). Remote withdrawals are encrypted to these keys, local ones to
    ``BuBank.public_key``; so the bank portal opens each record with the matching key.
    ``private_key_demo`` only while the service shows its demo keys (dev/demo)."""

    __tablename__ = "bu_chain_keys"

    bank: Mapped[str] = mapped_column(String(16), primary_key=True)
    public_key: Mapped[str] = mapped_column(String(64), default="")
    private_key_demo: Mapped[str] = mapped_column(String(64), default="")
    active_from: Mapped[str] = mapped_column(String(40), default="")
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BuAutoSwitch(Base):
    """Auto-approval switch per group ``"<industry>|t<tier>"`` (gate condition 5)."""

    __tablename__ = "bu_auto_switch"

    group_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    manual: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    npl_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    loans: Mapped[int] = mapped_column(Integer, default=0)
    bad: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BuBankApproval(Base):
    """Bank sign-off of an approved application (lỗ hổng 14; ``banks.require_signoff``)."""

    __tablename__ = "bu_bank_approvals"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    application_id: Mapped[str] = mapped_column(String(40), index=True)
    bank: Mapped[str] = mapped_column(String(16), index=True)
    pct: Mapped[float] = mapped_column(Float)
    amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), index=True, default="pending")  # pending|signed|declined
    signature: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    chain_tx: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BuSellerReport(Base):
    """Agent 5's reports to the seller (SELLER_SERVICES_PLAN §6.1): one row per (seller, kind, period);
    re-running the same period overwrites ``data``. ``read_at`` feeds the notification centre."""

    __tablename__ = "bu_seller_reports"
    __table_args__ = (UniqueConstraint("seller_user_id", "kind", "period", name="uq_seller_report_period"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # "srp_" + hex
    seller_user_id: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # month|quarter|year|closing|registration
    period: Mapped[str] = mapped_column(String(40))  # "2026-10" | "2026-Q4" | "2026" | loan id
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    hash: Mapped[str] = mapped_column(String(80), default="")
    chain_tx: Mapped[str | None] = mapped_column(String(80), nullable=True)


class BuShopConnection(Base):
    """A store the seller proved is theirs (HANDOVER 16.7): through the platform's OAuth (``verified_via =
    "oauth"``) or a code sent to the store's registered phone (``"otp_registered_phone"``). An application is
    made from one of these; ``profile`` is the shop profile read at connection time (phone masked). Tokens are
    never kept here (``token_ref`` stays null until a secret store holds them)."""

    __tablename__ = "bu_shop_connections"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # "shc_" + hex
    user_id: Mapped[str] = mapped_column(String(40), index=True)
    platform: Mapped[str] = mapped_column(String(16))
    shop_id: Mapped[str] = mapped_column(String(64), index=True)
    url: Mapped[str] = mapped_column(String(500), default="")
    shop_name: Mapped[str] = mapped_column(String(200), default="")
    subject_reg_no: Mapped[str] = mapped_column(String(40), default="")
    owner_name: Mapped[str] = mapped_column(String(120), default="")
    verified_via: Mapped[str] = mapped_column(String(24))  # otp_registered_phone | oauth
    verified_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    token_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    scenario: Mapped[str | None] = mapped_column(String(24), nullable=True)  # demo sample store, else None
    profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class BuShopConnectRequest(Base):
    """One attempt to connect a store: an OTP challenge (``kind = "otp"``: sha256 of the code, 5 minutes, at most
    5 wrong codes) or an OAuth round trip (``kind = "oauth"``: sha256 of the ``state``, 10 minutes, single use)."""

    __tablename__ = "bu_shop_connect_requests"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # "scr_" + hex
    user_id: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(8))
    platform: Mapped[str] = mapped_column(String(16))
    shop_id: Mapped[str] = mapped_column(String(64), default="")
    scenario: Mapped[str | None] = mapped_column(String(24), nullable=True)
    secret_hash: Mapped[str] = mapped_column(String(64), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending|verified|locked|expired|failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
