"""Local simulation of the BuoyUp FISCO BCOS ledger (4 nodes, PBFT, group 1).

What is real here: per-case hash chains, salted SHA-256 fingerprints, block
linking, tamper detection on verify. What is simulated: the four nodes and the
consensus (one process seals every block, the sealer label rotates like a PBFT
leader). The UI must label chain data "mô phỏng" unless ``mode() == "remote"``.

Remote mode (``BUOYUP_CHAIN_BACKEND=remote``): every :func:`record` still writes
the local entry (the UI and the trace read it) and mirrors its fingerprint to the
BuoyUp Chain service as an audit anchor (``chain_remote``), whose own head chain
uses keccak256. The local head stays sha3-256 (labelled "mô phỏng"). A mirror that
fails is queued in ``bu_chain_outbox`` — except the kinds in :data:`CRITICAL_KINDS`
(Agent 3 seal/conclusion, gate decision): those raise 503 ``CHAIN_UNAVAILABLE`` so
the request rolls back and the case is never auto-approved without its seal
(lỗ hổng 19).

Other modules only need :func:`record`, :func:`entry_public` and
:func:`verify_case`; withdrawals (per-bank envelope encryption) live in
``app.blockchain.withdrawals`` and seal their own tx through :func:`seal_block`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.platform.errors import api_error
from app.blockchain import chain_remote
from app.blockchain.chain_remote import ChainUnavailable
from app.platform.tables import BuChainBlock, BuChainEntry, BuChainOutbox
from app.platform.config import settings
from app.platform.ledger_key import resolve_key
from app.platform.db.tables import utcnow

NODES = ("node0", "node1", "node2", "node3")
GENESIS = "0" * 64
CRITICAL_KINDS = frozenset({"agent3_phase1_seal", "agent3_conclusion", "gate_decision", "contract_signed"})
MAX_OUTBOX_ATTEMPTS = 20


def mode() -> str:
    """``remote`` only when explicitly selected; the local simulation is the default."""
    return "remote" if settings.buoyup_chain_backend.strip().lower() == "remote" else "local"


def unavailable(exc: ChainUnavailable) -> HTTPException:
    """503 the client can show as is ("chuỗi không truy cập được")."""
    return api_error(503, "CHAIN_UNAVAILABLE", str(exc), {"kind": exc.kind, "backend": "remote"})


def canonical(payload: Any) -> bytes:
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")


def fingerprint(payload: Any, salt_hex: str) -> str:
    return "sha256:" + hashlib.sha256(bytes.fromhex(salt_hex) + canonical(payload)).hexdigest()


def _sha3(text: str) -> str:
    return hashlib.sha3_256(text.encode("utf-8")).hexdigest()


def _iso(dt) -> str:  # type: ignore[no-untyped-def]
    return dt.isoformat(timespec="microseconds")


def _block_hash(prev: str, height: int, txs: list[dict[str, Any]], at) -> str:  # type: ignore[no-untyped-def]
    """Blocks are keyed with the ledger HMAC key (kept outside the DB), so a
    database writer cannot rebuild a consistent chain after editing it."""
    msg = f"{prev}|{height}|{canonical(txs).decode()}|{_iso(at)}".encode("utf-8")
    return hmac.new(resolve_key().encode("utf-8"), msg, hashlib.sha256).hexdigest()


def seal_block(session: Session, txs: list[dict[str, Any]]) -> BuChainBlock:
    """Append one block holding ``txs``. Sealer rotates across the 4 nodes.

    Two writers can read the same tip; the loser's insert hits the primary key
    and is retried on the new tip inside a savepoint (no partial state left)."""
    for _ in range(8):
        last = session.scalar(select(BuChainBlock).order_by(BuChainBlock.height.desc()).limit(1))
        height = (last.height + 1) if last else 1
        prev = last.hash if last else GENESIS
        at = utcnow()
        block = BuChainBlock(
            height=height,
            prev=prev,
            sealer=NODES[height % len(NODES)],
            txs=txs,
            at=at,
            hash=_block_hash(prev, height, txs, at),
        )
        try:
            with session.begin_nested():
                session.add(block)
                session.flush()
            return block
        except IntegrityError:
            session.expire_all()
    raise RuntimeError("chain tip contention: could not seal block")


def _head_for(prev: str, kind: str, fp: str, at) -> str:  # type: ignore[no-untyped-def]
    return _sha3(f"{prev}|{kind}|{fp}|{_iso(at)}")


def record(session: Session, case_id: str, kind: str, payload: dict[str, Any]) -> BuChainEntry:
    """Fingerprint ``payload`` and append it to the hash chain of ``case_id``."""
    prev_entry = session.scalar(
        select(BuChainEntry)
        .where(BuChainEntry.case_id == case_id)
        .order_by(BuChainEntry.seq.desc())
        .limit(1)
    )
    prev = prev_entry.head if prev_entry else GENESIS
    # Normalize once (datetimes, Decimals -> str) so the stored JSON and the
    # fingerprinted bytes are the same object.
    payload = json.loads(canonical(payload))
    at = utcnow()
    salt = secrets.token_hex(16)
    fp = fingerprint(payload, salt)
    head = _head_for(prev, kind, fp, at)
    tx = "0x" + _sha3(head + case_id)[:40]
    block = seal_block(session, [{"tx": tx, "kind": kind, "ref": case_id}])
    entry = BuChainEntry(
        case_id=case_id,
        kind=kind,
        payload=payload,
        salt=salt,
        fingerprint=fp,
        head=head,
        tx=tx,
        block=block.height,
        at=at,
    )
    session.add(entry)
    session.flush()
    if mode() == "remote":
        _mirror(session, entry)
    return entry


def _anchor_payload(entry: BuChainEntry) -> dict[str, str]:
    return {"subject": entry.case_id, "kind": entry.kind, "content_hash": "0x" + entry.fingerprint.split(":", 1)[1],
            "uri": f"buoyup:{entry.case_id}:{entry.seq}"}


def _send_anchor(row: BuChainOutbox) -> None:
    p = row.payload
    out = chain_remote.get_remote().post_anchor(p["subject"], p["kind"], p["content_hash"], p["uri"])
    row.status, row.remote_tx, row.remote_block, row.last_error = "sent", out["tx"], out["block"], ""


def _mirror(session: Session, entry: BuChainEntry) -> None:
    row = BuChainOutbox(case_id=entry.case_id, kind=entry.kind, entry_seq=entry.seq,
                        payload=_anchor_payload(entry), status="pending", attempts=1,
                        created_at=utcnow(), updated_at=utcnow())
    try:
        _send_anchor(row)
    except ChainUnavailable as exc:
        if entry.kind in CRITICAL_KINDS:
            # Agent 3 §6 "thử lại": one more attempt before the request fails (no hash, no phase 2).
            try:
                row.attempts += 1
                _send_anchor(row)
            except ChainUnavailable as again:
                raise unavailable(again) from again
        else:
            row.last_error = str(exc)[:500]
    session.add(row)
    session.flush()


def remote_ref(session: Session, entry: BuChainEntry) -> dict[str, Any] | None:
    """Remote anchor of a local entry: ``{"tx", "block", "status"}`` (None in local mode)."""
    row = session.scalar(select(BuChainOutbox).where(BuChainOutbox.entry_seq == entry.seq).limit(1))
    if row is None:
        return None
    return {"tx": row.remote_tx or None, "block": row.remote_block or None, "status": row.status}


def enqueue(session: Session, case_id: str, kind: str, payload: dict[str, Any], error: str) -> BuChainOutbox:
    """Queue a non-anchor remote job (``kind="disburse"``) for :func:`flush_outbox`."""
    row = BuChainOutbox(case_id=case_id, kind=kind, payload=payload, status="pending", attempts=1,
                        last_error=error[:500], created_at=utcnow(), updated_at=utcnow())
    session.add(row)
    session.flush()
    return row


def outbox_view(row: BuChainOutbox) -> dict[str, Any]:
    return {"id": row.id, "case_id": row.case_id, "kind": row.kind, "status": row.status,
            "attempts": row.attempts, "remote_tx": row.remote_tx or None, "last_error": row.last_error or None,
            "updated_at": _iso(row.updated_at) + "Z"}


def flush_outbox(session: Session, include_payouts: bool = True) -> dict[str, Any]:
    """Retry every pending job once. Anchors resend the same fingerprint (a 409
    duplicate counts as sent); a pending disbursement reruns Agent 4a, whose
    ``requestId`` is fixed per application so a payout is never made twice, and only while its
    one-off grant is still valid. The monitoring loop passes ``include_payouts=False``: it never pays out."""
    from app.agents.agent4a_payout import disburse_failed, disburse_pending

    stmt = select(BuChainOutbox).where(BuChainOutbox.status == "pending")
    if not include_payouts:
        stmt = stmt.where(BuChainOutbox.kind != "disburse")
    rows = list(session.scalars(stmt.order_by(BuChainOutbox.id)))
    for row in rows:
        row.attempts += 1
        row.updated_at = utcnow()
        try:
            if row.kind == "disburse":
                disburse_pending(session, row)
            else:
                _send_anchor(row)
        except ChainUnavailable as exc:
            row.last_error = str(exc)[:500]
            client_error = exc.status is not None and 400 <= exc.status < 500 and exc.status not in (408, 429)
            if client_error or row.attempts >= MAX_OUTBOX_ATTEMPTS:
                row.status = "failed"
                if row.kind == "disburse":
                    disburse_failed(session, row)
    session.flush()
    counts = {s: 0 for s in ("sent", "pending", "failed")}
    for status_, in session.execute(select(BuChainOutbox.status)):
        counts[status_] = counts.get(status_, 0) + 1
    return {"processed": len(rows), "counts": counts, "items": [outbox_view(r) for r in rows]}


def entry_public(entry: BuChainEntry, remote: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {
        "seq": entry.seq,
        "kind": entry.kind,
        "fingerprint": entry.fingerprint,
        "head": entry.head,
        "tx": entry.tx,
        "block": entry.block,
        "at": _iso(entry.at) + "Z",
    }
    if remote is not None:
        out["remote"] = remote
    return out


def public_entries(session: Session, entries: list[BuChainEntry]) -> list[dict[str, Any]]:
    if mode() != "remote":
        return [entry_public(e) for e in entries]
    return [entry_public(e, remote_ref(session, e)) for e in entries]


def case_entries(session: Session, case_id: str) -> list[BuChainEntry]:
    return list(
        session.scalars(
            select(BuChainEntry).where(BuChainEntry.case_id == case_id).order_by(BuChainEntry.seq)
        )
    )


def _block_txs(session: Session, case_id: str) -> list[str]:
    """Tx ids the blocks say belong to ``case_id``, in block order."""
    out: list[str] = []
    for block in session.scalars(select(BuChainBlock).order_by(BuChainBlock.height)):
        out.extend(t["tx"] for t in block.txs if t.get("ref") == case_id and t.get("kind") != "withdrawal")
    return out


def verify_case(session: Session, case_id: str) -> dict[str, Any]:
    """Recompute every fingerprint, head and tx of one case, and cross-check
    the entries against the blocks both ways (catches edits, deletions and
    tail truncation). First mismatch wins."""
    prev = GENESIS
    entries = case_entries(session, case_id)
    n = len(entries)
    for entry in entries:
        fp = fingerprint(entry.payload, entry.salt)
        if fp != entry.fingerprint:
            return {"ok": False, "entries": n, "broken_at": entry.seq, "reason": "fingerprint"}
        if _head_for(prev, entry.kind, fp, entry.at) != entry.head:
            return {"ok": False, "entries": n, "broken_at": entry.seq, "reason": "head"}
        if entry.tx != "0x" + _sha3(entry.head + case_id)[:40]:
            return {"ok": False, "entries": n, "broken_at": entry.seq, "reason": "tx"}
        prev = entry.head
    if [e.tx for e in entries] != _block_txs(session, case_id):
        return {"ok": False, "entries": n, "broken_at": None, "reason": "missing_or_extra_entry"}
    return {"ok": True, "entries": n, "broken_at": None, "reason": None}


def verify_all(session: Session) -> dict[str, Any]:
    """Check block linkage and every case chain."""
    prev = GENESIS
    blocks = list(session.scalars(select(BuChainBlock).order_by(BuChainBlock.height)))
    for block in blocks:
        expected = _block_hash(prev, block.height, block.txs, block.at)
        if block.prev != prev or not hmac.compare_digest(block.hash, expected):
            return {"ok": False, "blocks": len(blocks), "broken_block": block.height, "broken_cases": []}
        prev = block.hash
    case_ids = list(session.scalars(select(BuChainEntry.case_id).distinct()))
    broken = [cid for cid in case_ids if not verify_case(session, cid)["ok"]]
    return {"ok": not broken, "blocks": len(blocks), "broken_block": None, "broken_cases": broken}


def status(session: Session) -> dict[str, Any]:
    if mode() == "remote":
        return _remote_status(session)
    last = session.scalar(select(BuChainBlock).order_by(BuChainBlock.height.desc()).limit(1))
    height = last.height if last else 0
    leader = NODES[(height + 1) % len(NODES)]
    return {
        "mode": mode(),
        "group": 1,
        "consensus": "PBFT",
        "height": height,
        "nodes": [{"id": n, "status": "up", "leader": n == leader} for n in NODES],
        "hash_alg": "sha3-256 (mô phỏng)",
        "simulated": True,
    }


def _catalog_sync() -> dict[str, Any]:
    from app.blockchain import chain_sync

    return chain_sync.last_sync()


def _remote_status(session: Session) -> dict[str, Any]:
    try:
        info = chain_remote.get_remote().status()
    except ChainUnavailable as exc:
        raise unavailable(exc) from exc
    meta = info.get("chain") or {}
    pending = session.scalar(select(BuChainOutbox.id).where(BuChainOutbox.status == "pending").limit(1))
    return {
        "mode": "remote",
        "url": chain_remote.get_remote().base_url,
        "backend": meta.get("backend"),
        "group": meta.get("groupId", 1),
        "consensus": "PBFT",
        "height": int(meta.get("blockNumber") or 0),
        "nodes": [{"id": n.get("name"), "status": "up" if n.get("online") else "down", "leader": False,
                   "sealer": bool(n.get("sealer")), "block": n.get("blockNumber")} for n in info.get("nodes") or []],
        "contracts": meta.get("contracts") or {},
        "explorer_url": chain_remote.get_remote().base_url + "/explorer/",
        "catalog_sync": _catalog_sync(),
        "hash_alg": "keccak256",
        "outbox_pending": pending is not None,
        "simulated": False,
    }
