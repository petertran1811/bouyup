"""Borrower consent: the three loan-circle boxes in one signed document, expiry, revocation, checks.

The seller signs (Ed25519) the canonical bytes of
``{consent_id, application, scopes, accounts, signed_at, expires_at}``. The client
gets that exact document from ``POST …/consent/draft`` and sends the signature with
``POST …/consent``. Without a signature, dev/demo/test sign with a throwaway server
key and mark ``signature.simulated = true``; production refuses.

:func:`problem` is the single check used by Agent 1 (before authorized-data tools),
LAW-01 (Agent 3) and Agent 4 (FATE re-score): consent present, not revoked, not
expired, signature valid over the signed document, every account in use either
signed or added later through its own consent record (``extra_accounts``).
Consents stored before signing existed have no ``signed``/``expires_at`` and are
checked for revocation only.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from app.blockchain import chain
from app.platform.db.tables import utcnow

ALG = "ed25519"
SIGNED_KEYS = ("consent_id", "application", "scopes", "accounts", "signed_at", "expires_at")

# Loan circle, Stage 1: one screen, three separate boxes, none pre-ticked, each linked to its text.
BOXES: dict[str, dict[str, str]] = {
    "credit_inquiry": {
        "title": "Ủy quyền tra cứu tín dụng cho WeBank và các ngân hàng hợp tác",
        "covers": "Báo cáo tín dụng tại tổ chức được cấp phép; điểm FATE của các ngân hàng cùng huấn luyện",
        "doc": "/app/giaodien/van-ban/tra-cuu-tin-dung.html"},
    "share_partners": {
        "title": "Đồng ý chuyển hồ sơ vay cho các ngân hàng hợp tác trong danh sách đính kèm",
        "covers": "Hồ sơ vay, kết quả thẩm định; tên và cách liên hệ từng ngân hàng ở danh sách",
        "doc": "/app/giaodien/van-ban/ngan-hang-hop-tac.html"},
    "data_processing": {
        "title": "Đồng ý xử lý thông tin khuôn mặt và dữ liệu tài chính để xác thực và thẩm định",
        "covers": "Khuôn mặt (xác thực, ký điện tử); dữ liệu thuế 银税互动; ảnh doanh thu chị tự nộp",
        "doc": "/app/giaodien/van-ban/xu-ly-du-lieu.html"},
}
CONSENT_BOXES = tuple(BOXES)
# What each authorized source needs: tax → data processing; credit report and FATE → credit inquiry.
SOURCE_BOX = {"tax": "data_processing", "credit": "credit_inquiry", "fate": "credit_inquiry",
              "partners": "share_partners"}
DATA_SCOPES = CONSENT_BOXES
SIGN_METHODS = ("face", "otp")


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds") + "Z"


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.rstrip("Z"))


def build_document(application_code: str, scopes: list[str], accounts: list[dict[str, Any]],
                   ttl_days: int, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    return {
        "consent_id": "CS-" + secrets.token_hex(3), "application": application_code, "scopes": list(scopes),
        "accounts": [{"bank": a["bank"], "tail": a["tail"]} for a in accounts],
        "signed_at": _iso(now), "expires_at": _iso(now + timedelta(days=int(ttl_days))),
    }


def message(document: dict[str, Any]) -> bytes:
    """The exact bytes the seller signs."""
    return chain.canonical({k: document[k] for k in SIGNED_KEYS})


def verify_signature(document: dict[str, Any], signature: dict[str, Any] | None) -> bool:
    if not signature or signature.get("alg") != ALG:
        return False
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(str(signature.get("public_key", ""))))
        key.verify(bytes.fromhex(str(signature.get("sig", ""))), message(document))
    except (ValueError, KeyError, InvalidSignature):
        return False
    return True


def demo_sign(document: dict[str, Any], method: str = "face") -> dict[str, Any]:
    """Simulated signature with a throwaway key (dev/demo only; the key is not kept). ``method`` is
    how the borrower confirmed: a face scan, or an OTP for one who does not want to use the face."""
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {"alg": ALG, "public_key": public.hex(), "sig": key.sign(message(document)).hex(), "simulated": True,
            "method": method}


def problem(consent: dict[str, Any] | None, scopes: tuple[str, ...] = (), now: datetime | None = None) -> str | None:
    """Why ``consent`` cannot be used now (``missing|revoked|expired|signature|accounts|scope``), else None."""
    if not consent:
        return "missing"
    if consent.get("revoked_at"):
        return "revoked"
    now = now or utcnow()
    if consent.get("expires_at") and _parse(str(consent["expires_at"])) <= now:
        return "expired"
    signed = consent.get("signed")
    if signed is not None:
        if not verify_signature(signed, consent.get("signature")):
            return "signature"
        allowed = {(a["bank"], a["tail"]) for a in signed.get("accounts", []) + consent.get("extra_accounts", [])}
        if any((a.get("bank"), a.get("tail")) not in allowed for a in consent.get("accounts", [])):
            return "accounts"
    keys = {s["key"] if isinstance(s, dict) else s for s in consent.get("scopes", [])}
    if any(s not in keys for s in scopes):
        return "scope"
    return None


def valid(consent: dict[str, Any] | None, scope: str | None = None, now: datetime | None = None) -> bool:
    return problem(consent, (scope,) if scope else (), now) is None


def blocked_reason(consent: dict[str, Any] | None) -> str | None:
    """Revoked or expired only (used by ``next_action`` and the monitoring job)."""
    p = problem(consent)
    return p if p in ("revoked", "expired", "signature", "accounts") else None
