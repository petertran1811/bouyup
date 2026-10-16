"""Idempotent seed for BuoyUp v4: bank catalog, parameter set v4.0, demo users.

Banks and parameters are always ensured (the app cannot run without them).
Demo users are created only when ``app_env`` is ``dev`` or ``demo``.
Bank policies, limits and contract ids are illustrative ([Ví dụ]).
"""

from __future__ import annotations

from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.blockchain import chain
from app.core import legal
from app.core.params import DEFAULT_PARAMS, PARAMS_VERSION
from app.platform.security import hash_password, new_user_id
from app.platform.tables import BuBank, BuChainEntry, BuParams, BuUser, save_json
from app.platform.config import settings
from app.platform.db.session import session_scope

_ECIG = ["thuốc lá điện tử", "dịch thuốc lá điện tử"]
_DEMO_ENVS = ("dev", "demo", "test")


def _demo() -> bool:
    return settings.app_env in _DEMO_ENVS

# code, name, region, currency, limit_total, policy overrides. Loan circle (Stage 2): WeBank is the lead;
# the partners answer in parallel within 30 s from their own policy (response_ms simulates the answer
# time); tier1_capital / total_loans carry the 25 % / 50 % concentration rules; monthly_budget the
# monthly budget for this channel; local_province marks a local bank [Ví dụ, demo figures].
BANKS: list[tuple[str, str, str, str, int, dict[str, Any]]] = [
    ("WEBANK", "WeBank", "CN", "CNY", 20_000_000, {"role": "lead", "min_grade": "C", "min_amount": 10_000,
                                                 "max_amount": 2_000_000, "response_ms": 400}),
    ("CMB", "China Merchants Bank", "CN", "CNY", 8_000_000, {
        "min_grade": "C", "min_amount": 10_000, "max_amount": 1_500_000, "response_ms": 1200,
        "exclude_industries": ["điện tử"], "tier1_capital": 40_000_000, "total_loans": 300_000_000,
        "monthly_budget": 3_000_000, "max_tenor_m": 36}),
    ("ICBC", "Industrial and Commercial Bank of China", "CN", "CNY", 10_000_000, {
        "min_grade": "C", "min_amount": 10_000, "max_amount": 3_000_000, "response_ms": 2500,
        "tier1_capital": 80_000_000, "total_loans": 600_000_000, "monthly_budget": 5_000_000, "max_tenor_m": 36}),
    ("BOC", "Bank of China", "CN", "CNY", 6_000_000, {
        "min_grade": "B", "min_amount": 50_000, "max_amount": 3_000_000, "response_ms": 35_000,
        "tier1_capital": 60_000_000, "total_loans": 500_000_000, "monthly_budget": 2_000_000}),
    ("CCB", "China Construction Bank", "CN", "CNY", 6_000_000, {
        "min_grade": "C", "min_amount": 50_000, "max_amount": 5_000_000, "response_ms": 2800,
        "exclude_industries": ["điện tử"], "tier1_capital": 60_000_000, "total_loans": 500_000_000, "monthly_budget": 3_000_000}),
    ("GZRCB", "Ngân hàng Nông thương Quảng Châu", "CN", "CNY", 3_000_000, {
        "min_grade": "A", "min_amount": 10_000, "max_amount": 500_000, "response_ms": 3000,
        "local_province": "CN-GD", "tier1_capital": 8_000_000, "total_loans": 60_000_000,
        "monthly_budget": 800_000, "borrower_types": ["individual_business"], "max_tenor_m": 12}),
    ("VCB", "Vietcombank", "VN", "VND", 50_000_000_000, {"min_grade": "C", "min_amount": 50_000_000, "max_amount": 5_000_000_000}),
    ("BIDV", "BIDV", "VN", "VND", 40_000_000_000, {"min_grade": "C", "min_amount": 50_000_000, "max_amount": 5_000_000_000}),
    ("TCB", "Techcombank", "VN", "VND", 30_000_000_000, {"min_grade": "B", "min_amount": 30_000_000, "max_amount": 3_000_000_000}),
    ("AGRI", "Agribank", "VN", "VND", 30_000_000_000, {"min_grade": "C", "min_amount": 50_000_000, "max_amount": 3_000_000_000}),
    ("MBB", "MB Bank", "VN", "VND", 20_000_000_000, {"min_grade": "C", "min_amount": 20_000_000, "max_amount": 2_000_000_000}),
]

DEMO_USERS: list[tuple[str, str, str, str | None]] = [
    ("lan@buoyup.vn", "Lâm Lan", "seller", None),
    ("officer@buoyup.vn", "Cán bộ Minh", "officer", None),
    ("admin@buoyup.vn", "Quản trị BuoyUp", "admin", None),
    ("webank@buoyup.vn", "WeBank · đối tác", "bank", "WEBANK"),
    ("cmb@buoyup.vn", "CMB · đối tác", "bank", "CMB"),
    ("icbc@buoyup.vn", "ICBC · đối tác", "bank", "ICBC"),
    ("vcb@buoyup.vn", "Vietcombank · đối tác", "bank", "VCB"),
]


def _keypair() -> tuple[str, str]:
    key = X25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    ).hex()
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()
    return private, public


def ensure_banks(session: Session) -> None:
    for code, name, region, currency, limit_total, overrides in BANKS:
        existing = session.get(BuBank, code)
        if existing is not None:
            # A database seeded before the loan circle gains the new policy keys (its own values stay).
            missing = {k: v for k, v in overrides.items() if k not in (existing.policy or {})}
            if missing:
                save_json(existing, "policy", {**(existing.policy or {}), **missing})
            continue
        private, public = _keypair()
        policy = {
            "min_grade": "C",
            "tiers": [1, 2],
            "min_amount": 0,
            "max_amount": limit_total,
            "max_rate": 0.15,
            "excluded_groups": list(_ECIG),
            "min_share": 0.30,
            **overrides,
        }
        session.add(
            BuBank(
                code=code,
                name=name,
                region=region,
                currency=currency,
                active=True,
                limit_total=limit_total,
                limit_used=0,
                policy=policy,
                contract_id=f"BU-{code}-2026-01",
                public_key=public,
                # Production: the bank keeps its private key; we store the public key only.
                private_key_demo=private if _demo() else "",
            )
        )


def ensure_master_key(session: Session) -> None:
    """Platform master key, stored as the pseudo-bank ``MASTER`` (inactive)."""
    if session.get(BuBank, "MASTER") is not None:
        return
    private, public = _keypair()
    session.add(
        BuBank(
            code="MASTER", name="Khóa chủ BuoyUp", region="--", currency="--", active=False,
            limit_total=0, policy={}, contract_id="", public_key=public,
            # Production: the master key lives in an HSM/KMS, never in the DB.
            private_key_demo=private if _demo() else "",
        )
    )


def ensure_params(session: Session) -> None:
    if session.scalar(select(BuParams).limit(1)) is not None:
        return
    entry = chain.record(session, "system", "params", {"version": PARAMS_VERSION, "params": DEFAULT_PARAMS})
    session.add(
        BuParams(
            version=PARAMS_VERSION, params=DEFAULT_PARAMS, hash=entry.fingerprint,
            chain_tx=entry.tx, active=True, note="Bộ tham số khởi điểm theo thiết kế v4",
        )
    )


def latest_ruleset_entry(session: Session) -> BuChainEntry | None:
    return session.scalar(
        select(BuChainEntry).where(BuChainEntry.case_id == "system", BuChainEntry.kind == "ruleset")
        .order_by(BuChainEntry.seq.desc()).limit(1)
    )


def ensure_ruleset(session: Session) -> None:
    """Anchor Agent 3's rule set (code, how, min verdict, citations) when it changes."""
    last = latest_ruleset_entry(session)
    if last is not None and last.payload.get("hash") == legal.RULESET_HASH:
        return
    chain.record(session, "system", "ruleset", {
        "version": legal.RULESET_VERSION, "hash": legal.RULESET_HASH,
        "rules": [[r.code, r.how, r.min_verdict, [list(c) for c in r.cite]] for r in legal.ENABLED_RULES],
        "disabled": legal.DISABLED_RULES,
    })


def ensure_law_corpus(session: Session) -> None:
    """Anchor the extracted TQ law corpus (Agent 3 §3.5 layer 1: manifest hash on FISCO) when it changes."""
    last = session.scalar(
        select(BuChainEntry).where(BuChainEntry.case_id == "system", BuChainEntry.kind == "law_corpus")
        .order_by(BuChainEntry.seq.desc()).limit(1))
    if last is not None and last.payload.get("corpus_hash") == legal.CORPUS_HASH:
        return
    chain.record(session, "system", "law_corpus", {
        "corpus_hash": legal.CORPUS_HASH, "entries": legal.MANIFEST["entries"],
        "extracted": legal.MANIFEST["extracted"],
        "sources": [{k: s.get(k) for k in ("law_id", "file", "sha256", "effective", "articles", "rows")}
                    for s in legal.MANIFEST["sources"]],
    })


def ensure_demo_users(session: Session) -> None:
    if not _demo():
        return
    for email, name, role, bank_code in DEMO_USERS:
        if session.scalar(select(BuUser).where(BuUser.email == email)) is not None:
            continue
        session.add(
            BuUser(
                id=new_user_id(), email=email, password_hash=hash_password(settings.buoyup_demo_password),
                display_name=name, role=role, bank_code=bank_code, active=True,
            )
        )


def seed_buoyup() -> None:
    with session_scope() as session:
        ensure_banks(session)
        ensure_master_key(session)
        ensure_params(session)
        ensure_ruleset(session)
        ensure_law_corpus(session)
        ensure_demo_users(session)
