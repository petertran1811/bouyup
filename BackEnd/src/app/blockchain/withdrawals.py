"""Encrypted payout records (lệnh giải ngân), envelope-encrypted per bank.

Layout of one withdrawal:
- pieces: index 0 = summary, then one piece per funding bank. Each piece is
  ``{"data": …, "salt": hex}`` encrypted with its own random 256-bit key,
  AES-256-GCM, AAD = withdrawal id.
- slots (unnamed, shuffled): one per reader (platform master key + each funding
  bank). A slot holds the piece keys that reader may open, wrapped with
  AES-256-GCM under a key derived by X25519 (ephemeral) + HKDF-SHA256 whose
  ``info`` contains the withdrawal id. A bank slot holds the summary key and its
  own piece key; the master slot holds every key.
- fingerprints: ``0x`` + SHA-256(salt || canonical plaintext) per piece; the
  salt lives inside the ciphertext, so a reader can prove its piece to an
  arbiter without handing over the key. Merkle root over the fingerprints is
  recomputed before the record is anchored (the "contract" refuses mismatch).

The public view shows id, time, piece count, size, fingerprints, root, tx and
block — never a bank name.

Remote chain mode: the plaintext request goes to the BuoyUp Chain service
(``POST /v1/withdrawals``), which pays, encrypts and anchors it; the local row then
keeps only the service's public record (``envelope.remote = true``: commitments,
root, tx, block, sealer) and reading/verifying is forwarded to the service.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform.errors import api_error
from app.blockchain import chain
from app.blockchain import chain_remote
from app.banks.split import MASTER_CODE
from app.blockchain.chain_remote import ChainUnavailable
from app.platform.tables import BuBank, BuChainBlock, BuWithdrawal
from app.platform.ledger_key import resolve_key
from app.platform.db.tables import utcnow

ALG = "X25519-HKDF-SHA256-AES-256-GCM"
NO_SLOT_MESSAGE = "Khóa này không mở được ô nào"


# --- primitives ------------------------------------------------------------

def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _unb64(text: str) -> bytes:
    return base64.b64decode(text)


def _ref_salt() -> bytes:
    """Secret salt for account/user reference codes, derived from the ledger key
    (fails closed outside dev/test like the ledger). Never exposed."""
    return hmac.new(resolve_key().encode(), b"buoyup-ref-salt-v1", hashlib.sha256).digest()


def reference_code(*parts: str) -> str:
    """HMAC-SHA256 reference: only the platform can map it back to the person."""
    mac = hmac.new(_ref_salt(), "|".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()
    return "ref_" + mac[:32]


def piece_fingerprint(plain: dict[str, Any]) -> str:
    salt = bytes.fromhex(plain["salt"])
    return "0x" + hashlib.sha256(salt + chain.canonical(plain["data"])).hexdigest()


def merkle_root(fingerprints: list[str]) -> str:
    """Domain-separated Merkle root: leaf = H(0x00‖fp), node = H(0x01‖l‖r), an
    odd node is promoted unchanged, root = H(0x02‖leaf count‖top)."""
    level = [hashlib.sha256(b"\x00" + bytes.fromhex(fp[2:])).digest() for fp in fingerprints]
    while len(level) > 1:
        nxt = [hashlib.sha256(b"\x01" + level[i] + level[i + 1]).digest() for i in range(0, len(level) - 1, 2)]
        if len(level) % 2:
            nxt.append(level[-1])
        level = nxt
    top = level[0] if level else b"\x00" * 32
    return "0x" + hashlib.sha256(b"\x02" + len(fingerprints).to_bytes(4, "big") + top).hexdigest()


def _kek(shared: bytes, wid: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None,
        info=b"buoyup-withdrawal-slot|" + wid.encode(),
    ).derive(shared)


def _public_bytes(key: X25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _seal_slot(wid: str, reader_public_hex: str, keys: dict[str, str]) -> dict[str, str]:
    ephemeral = X25519PrivateKey.generate()
    shared = ephemeral.exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(reader_public_hex)))
    nonce = secrets.token_bytes(12)
    ct = AESGCM(_kek(shared, wid)).encrypt(nonce, chain.canonical({"k": keys}), wid.encode())
    return {"epk": _public_bytes(ephemeral.public_key()).hex(), "nonce": _b64(nonce), "ct": _b64(ct)}


def _open_slot(wid: str, private: X25519PrivateKey, slot: dict[str, str]) -> dict[str, str] | None:
    shared = private.exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(slot["epk"])))
    try:
        plain = AESGCM(_kek(shared, wid)).decrypt(_unb64(slot["nonce"]), _unb64(slot["ct"]), wid.encode())
    except InvalidTag:
        return None
    return json.loads(plain)["k"]


# --- building and anchoring --------------------------------------------------

def build_record(wid: str, pieces: list[dict[str, Any]], readers: list[tuple[str, list[int]]]) -> dict[str, Any]:
    """Encrypt ``pieces`` (plaintext data dicts) for ``readers`` = [(public_key_hex, piece indexes)]."""
    keys = [AESGCM.generate_key(bit_length=256) for _ in pieces]
    plains = [{"data": data, "salt": secrets.token_hex(16)} for data in pieces]
    enc = []
    for i, (key, plain) in enumerate(zip(keys, plains)):
        nonce = secrets.token_bytes(12)
        ct = AESGCM(key).encrypt(nonce, chain.canonical(plain), wid.encode())
        enc.append({"index": i, "nonce": _b64(nonce), "ct": _b64(ct)})
    slots = [_seal_slot(wid, pub, {str(i): keys[i].hex() for i in idx}) for pub, idx in readers]
    secrets.SystemRandom().shuffle(slots)
    fingerprints = [piece_fingerprint(p) for p in plains]
    envelope = {"version": 1, "alg": ALG, "withdrawal_id": wid, "pieces": enc, "slots": slots}
    return {
        "envelope": envelope,
        "piece_fingerprints": fingerprints,
        "merkle_root": merkle_root(fingerprints),
        "size": len(chain.canonical(envelope)),
    }


def withdrawal_tx(wid: str, root: str, envelope: dict[str, Any]) -> str:
    """Tx id binding the withdrawal id, the Merkle root and the exact ciphertext."""
    envelope_digest = hashlib.sha256(chain.canonical(envelope)).hexdigest()
    return "0x" + hashlib.sha3_256(f"{wid}|{root}|{envelope_digest}".encode()).hexdigest()[:40]


def anchor(
    session: Session, *, wid: str, request_id: str, digest: str, loan_id: str | None,
    record: dict[str, Any],
) -> BuWithdrawal:
    """What the chain contract does: recompute the root, refuse a mismatch, seal."""
    if merkle_root(record["piece_fingerprints"]) != record["merkle_root"]:
        raise api_error(400, "VALIDATION_ERROR", "Gốc Merkle không khớp dấu vân tay các phần; từ chối ghi.")
    tx = withdrawal_tx(wid, record["merkle_root"], record["envelope"])
    block = chain.seal_block(session, [{"tx": tx, "kind": "withdrawal", "ref": wid}])
    row = BuWithdrawal(
        id=wid, request_id=request_id, request_digest=digest, loan_id=loan_id,
        envelope=record["envelope"], piece_fingerprints=record["piece_fingerprints"],
        merkle_root=record["merkle_root"], size=record["size"], tx=tx, block=block.height,
        created_at=utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def _reader_key(session: Session, code: str) -> str:
    bank = session.get(BuBank, code)
    if bank is None or not bank.public_key:
        raise api_error(400, "VALIDATION_ERROR", f"{code}: chưa có khóa mã hóa.")
    return bank.public_key


def create_withdrawal(
    session: Session, *, request_id: str, amount: int, currency: str, region: str, province: str,
    user: str, account: str, payout_ref: str, requester: str, shares: list[dict[str, Any]],
    loan_id: str | None = None, reason: str | None = None,
) -> BuWithdrawal:
    """Create (or return, idempotently) the encrypted payout record.

    ``shares`` = [{"bank", "pct", "amount", "contract_id"}], already validated.
    Same ``request_id`` + same data returns the existing record; same id with
    different data is a 409 CONFLICT. ``reason`` (manual payouts) goes into the
    encrypted summary piece only.
    """
    request = {
        "amount": amount, "currency": currency, "region": region, "province": province,
        "user": user, "account": account, "payout_ref": payout_ref, "requester": requester,
        "shares": [{k: s[k] for k in ("bank", "pct", "amount", "contract_id")} for s in shares],
    }
    if reason:
        request["reason"] = reason
    digest = hashlib.sha256(chain.canonical(request)).hexdigest()
    existing = session.scalar(select(BuWithdrawal).where(BuWithdrawal.request_id == request_id))
    if existing is not None:
        if existing.request_digest == digest:
            return existing
        raise api_error(409, "CONFLICT", "requestId này đã dùng cho một lệnh giải ngân khác.",
                        {"request_id": request_id})
    if chain.mode() == "remote":
        return _create_remote(session, request_id=request_id, digest=digest, request=request, loan_id=loan_id)
    wid = "WD-" + secrets.token_hex(8).upper()
    summary = {
        "piece": "summary", "amount": amount, "currency": currency, "region": region,
        "province": province, "account_ref": reference_code(user, account), "payout_ref": payout_ref,
        "requester": requester, "bank_count": len(shares),
    }
    if reason:
        summary["reason"] = reason
    pieces = [summary] + [
        {"piece": "bank", "bank": s["bank"], "pct": s["pct"], "amount": s["amount"],
         "contract_id": s["contract_id"]}
        for s in shares
    ]
    readers = [(_reader_key(session, MASTER_CODE), list(range(len(pieces))))]
    readers += [(_reader_key(session, s["bank"]), [0, i + 1]) for i, s in enumerate(shares)]
    record = build_record(wid, pieces, readers)
    return anchor(session, wid=wid, request_id=request_id, digest=digest, loan_id=loan_id, record=record)


def _remote_actor(requester: str, reason: str | None, request_id: str = "") -> dict[str, Any]:
    if requester in ("agent4", "agent4a"):
        from app.platform.config import settings

        # agentId stays "agent-4" (the chain service knows that id); the payout half is Agent 4a.
        actor = {"type": "agent", "agentId": "agent-4", "name": "Giải ngân (Agent 4a)", "version": "4.1",
                 "model": (settings.llm_model_name.strip() if settings.llm_enabled else "") or "code"}
        if request_id:
            actor["runId"] = request_id[-32:]
        return actor
    if requester == "DEMO":
        return {"type": "human", "staffId": "DEMO", "role": "demo", "reason": "Demo: " + (reason or "")[:200]}
    return {"type": "human", "staffId": requester.removeprefix("staff:"), "role": "credit_officer",
            "reason": reason or "Giải ngân thủ công"}


def _create_remote(session: Session, *, request_id: str, digest: str, request: dict[str, Any],
                   loan_id: str | None) -> BuWithdrawal:
    """Send the plaintext request; the service pays, encrypts and anchors it. A retry
    with the same ``requestId`` returns the service's existing record (no second payout)."""
    currency, region = request["currency"], request["region"]
    body = {
        "requestId": request_id, "userId": request["user"], "accountNo": request["account"],
        "amount": chain_remote.to_minor(request["amount"], currency), "currency": currency, "region": region,
        "province": request["province"],
        "bankSplit": {s["bank"]: round(float(s["pct"]) * 100, 2) for s in request["shares"]},
        "actor": _remote_actor(request["requester"], request.get("reason"), request_id),
    }
    try:
        out = chain_remote.get_remote().post_withdrawal(body)
    except ChainUnavailable as exc:
        if exc.status == 409:
            raise api_error(409, "CONFLICT", "requestId này đã dùng cho một lệnh giải ngân khác.",
                            {"request_id": request_id, "kind": exc.kind}) from exc
        if exc.status is not None and 400 <= exc.status < 500 and exc.status not in (401, 408, 429):
            raise api_error(400, "VALIDATION_ERROR", str(exc), {"kind": exc.kind}) from exc
        raise
    on_chain = out.get("onChain") or {}
    ref = out.get("chain") or {}
    chain_ref = {k: ref.get(k) for k in ("backend", "blockHash", "sealedBy", "submittedTo", "confirmedNodes",
                                         "totalNodes", "contract", "timestamp") if k in ref}
    chain_ref["explorerUrl"] = chain_remote.absolute_url(ref.get("explorerUrl"))
    chain_ref["verifyUrl"] = chain_remote.absolute_url(ref.get("verifyUrl"))
    envelope = {
        "remote": True, "pieces": int(on_chain.get("pieces") or 0), "slots": int(on_chain.get("slots") or 0),
        "alg": ALG, "replayed": bool(out.get("replayed")), "chain": chain_ref,
        # What the chain says each bank funds, in the minor unit (kept server-side; the public
        # view never shows bank names).
        "legs": [{"bank": leg.get("bank"), "bp": leg.get("ratioBps"), "amount_minor": int(leg.get("amount") or 0)}
                 for leg in out.get("legs") or []],
    }
    # The chain cuts the amount in fen from the percentages (largest share takes the remainder);
    # BuoyUp's shares are whole units. Flag any difference so it is never silent.
    ours = {s["bank"]: chain_remote.to_minor(int(s["amount"]), currency) for s in request["shares"]}
    theirs = {leg["bank"]: leg["amount_minor"] for leg in envelope["legs"]}
    if theirs and theirs != ours:
        envelope["legs_mismatch"] = {"buoyup_minor": ours, "chain_minor": theirs}
    row = BuWithdrawal(
        id=str(out.get("withdrawalId") or on_chain.get("withdrawalId")), request_id=request_id,
        request_digest=digest, loan_id=loan_id, envelope=envelope,
        piece_fingerprints=list(on_chain.get("commitments") or []), merkle_root=str(on_chain.get("root") or ""),
        size=int(on_chain.get("envelopeBytes") or 0), tx=str(on_chain.get("txHash") or ref.get("txHash") or ""),
        block=int(on_chain.get("blockNumber") or ref.get("blockNumber") or 0), created_at=utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def is_remote(withdrawal: BuWithdrawal) -> bool:
    return bool((withdrawal.envelope or {}).get("remote"))


# --- reading -----------------------------------------------------------------

def _private_key(private_key_hex: str) -> X25519PrivateKey:
    try:
        raw = bytes.fromhex(private_key_hex.strip())
        if len(raw) != 32:
            raise ValueError
        return X25519PrivateKey.from_private_bytes(raw)
    except ValueError:
        raise api_error(400, "VALIDATION_ERROR", "Khóa bí mật phải là 64 ký tự hex (X25519).") from None


def _piece_name(index: int, data: dict[str, Any]) -> str:
    return "summary" if index == 0 else str(data.get("bank", f"piece{index}"))


def decrypt(withdrawal: BuWithdrawal, private_key_hex: str) -> dict[str, Any]:
    """Open every piece this key can open and check each against its fingerprint."""
    private = _private_key(private_key_hex)
    wid = withdrawal.id
    envelope = withdrawal.envelope or {}
    keys = next(
        (k for slot in envelope.get("slots", []) if (k := _open_slot(wid, private, slot)) is not None), None
    )
    if keys is None:
        return {"opened": [], "pieces": {}, "fingerprints_ok": None, "message": NO_SLOT_MESSAGE}
    by_index = {p["index"]: p for p in envelope.get("pieces", [])}
    opened: list[str] = []
    pieces: dict[str, Any] = {}
    failed: list[int] = []
    all_ok = True
    for index_text, key_hex in sorted(keys.items(), key=lambda kv: int(kv[0])):
        index = int(index_text)
        enc = by_index.get(index)
        try:
            if enc is None:
                raise InvalidTag
            raw = AESGCM(bytes.fromhex(key_hex)).decrypt(_unb64(enc["nonce"]), _unb64(enc["ct"]), wid.encode())
        except InvalidTag:
            failed.append(index)
            all_ok = False
            continue
        plain = json.loads(raw)
        expected = withdrawal.piece_fingerprints[index] if index < len(withdrawal.piece_fingerprints) else ""
        ok = hmac.compare_digest(piece_fingerprint(plain), expected)
        all_ok = all_ok and ok
        name = _piece_name(index, plain["data"])
        opened.append(name)
        pieces[name] = {**plain["data"], "fingerprint": expected, "fingerprint_ok": ok}
    root_ok = merkle_root(withdrawal.piece_fingerprints) == withdrawal.merkle_root
    out: dict[str, Any] = {
        "opened": opened, "pieces": pieces, "fingerprints_ok": all_ok and root_ok, "merkle_ok": root_ok,
    }
    if failed:
        out["failed_pieces"] = failed
        out["message"] = "Có phần không giải mã được: bản mã đã bị sửa hoặc không khớp mã lệnh."
    return out


def _count(value: Any) -> int:
    return value if isinstance(value, int) else len(value or [])


def public_view(withdrawal: BuWithdrawal, *, detail: bool = False) -> dict[str, Any]:
    env = withdrawal.envelope or {}
    out: dict[str, Any] = {
        "id": withdrawal.id,
        "at": chain._iso(withdrawal.created_at) + "Z",
        "pieces": _count(env.get("pieces")),
        "size": withdrawal.size,
        "tx": withdrawal.tx,
        "block": withdrawal.block,
        "merkle_root": withdrawal.merkle_root,
        "piece_fingerprints": list(withdrawal.piece_fingerprints or []),
        "simulated": not env.get("remote"),
    }
    if env.get("remote"):
        out["explorer_url"] = (env.get("chain") or {}).get("explorerUrl")
    if detail:
        out["slots"] = _count(env.get("slots"))
        out["alg"] = env.get("alg", ALG)
        if env.get("remote"):
            out["remote"] = env.get("chain") or {}
    return out


def _remote_decrypt(withdrawal: BuWithdrawal, private_key_hex: str) -> dict[str, Any]:
    """Forward to the service's explorer decrypt; map to the local decrypt shape
    (amounts back from the minor unit)."""
    _private_key(private_key_hex)
    try:
        out = chain_remote.get_remote().decrypt(withdrawal.id, private_key_hex.strip())
    except ChainUnavailable as exc:
        if exc.status == 403:
            return {"opened": [], "pieces": {}, "fingerprints_ok": None, "message": NO_SLOT_MESSAGE}
        raise chain.unavailable(exc) from exc
    opened: list[str] = []
    pieces: dict[str, Any] = {}
    ok = True
    for item in out.get("readable") or []:
        content = dict(item.get("content") or {})
        if "amount" in content:
            content["amount"] = chain_remote.from_minor(int(content["amount"]), str(content.get("currency") or ""))
        if item.get("kind") == "bank_share":  # the service's names → the local piece's names
            if content.get("percent") is not None:
                content["pct"] = round(float(content["percent"]) / 100, 6)
            if content.get("contractNo"):
                content["contract_id"] = content["contractNo"]
        name = "summary" if item.get("kind") == "summary" else str(content.get("bank") or f"piece{item.get('index')}")
        match = bool(item.get("commitmentMatches"))
        ok = ok and match
        opened.append(name)
        pieces[name] = {**content, "fingerprint": item.get("commitment"), "fingerprint_ok": match}
    root_ok = bool(out.get("rootMatchesCommitments"))
    if not opened:
        return {"opened": [], "pieces": {}, "fingerprints_ok": None, "message": NO_SLOT_MESSAGE}
    return {"opened": opened, "pieces": pieces, "fingerprints_ok": ok and root_ok, "merkle_ok": root_ok}


def decrypt_any(withdrawal: BuWithdrawal, private_key_hex: str) -> dict[str, Any]:
    return _remote_decrypt(withdrawal, private_key_hex) if is_remote(withdrawal) else decrypt(withdrawal, private_key_hex)


def remote_verification(withdrawal: BuWithdrawal) -> dict[str, Any]:
    try:
        return chain_remote.get_remote().verify_withdrawal(withdrawal.id)
    except ChainUnavailable as exc:
        raise chain.unavailable(exc) from exc


def verify_record(session: Session, withdrawal: BuWithdrawal) -> bool:
    """Root, tx and block agree: the root is recomputed from the fingerprints, the
    tx from id + root + ciphertext, and the (HMAC-keyed) block at ``block`` must
    hold exactly that tx for this withdrawal. A remote record is checked by the
    chain service (``GET /v1/withdrawals/{id}/verify``)."""
    if is_remote(withdrawal):
        return bool(remote_verification(withdrawal).get("valid"))
    if merkle_root(list(withdrawal.piece_fingerprints or [])) != withdrawal.merkle_root:
        return False
    if withdrawal_tx(withdrawal.id, withdrawal.merkle_root, withdrawal.envelope or {}) != withdrawal.tx:
        return False
    block = session.get(BuChainBlock, withdrawal.block)
    expected = {"tx": withdrawal.tx, "kind": "withdrawal", "ref": withdrawal.id}
    return block is not None and expected in (block.txs or [])


def verify_withdrawals(session: Session) -> list[str]:
    """Ids of withdrawals that fail :func:`verify_record`, plus withdrawal txs
    sealed in blocks whose record row is missing or points elsewhere."""
    rows = {w.id: w for w in session.scalars(select(BuWithdrawal))}
    broken = [wid for wid, w in rows.items() if not verify_record(session, w)]
    for block in session.scalars(select(BuChainBlock).order_by(BuChainBlock.height)):
        for tx in block.txs or []:
            if tx.get("kind") != "withdrawal":
                continue
            row = rows.get(str(tx.get("ref")))
            if (row is None or row.tx != tx.get("tx") or row.block != block.height) and tx.get("ref") not in broken:
                broken.append(str(tx.get("ref")))
    return broken
