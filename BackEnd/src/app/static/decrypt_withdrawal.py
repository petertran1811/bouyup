#!/usr/bin/env python3
"""Open a BuoyUp withdrawal record with your own X25519 private key, without the platform.

Downloads the public record (envelope, piece fingerprints, Merkle root), opens the
key slot your key can open, decrypts the pieces it lists and checks each piece
against its fingerprint and the fingerprints against the Merkle root.

    pip install cryptography
    python decrypt_withdrawal.py --api http://localhost:8000 --token <bearer> --id WD-… --key <64 hex>
    python decrypt_withdrawal.py --file record.json --key <64 hex>      # record saved earlier

Format (version 1): X25519 (ephemeral) + HKDF-SHA256 (info = "buoyup-withdrawal-slot|" + id)
wraps per-piece AES-256-GCM keys (AAD = withdrawal id); fingerprint = "0x" +
SHA-256(salt ‖ canonical JSON); Merkle leaf = H(0x00‖fp), node = H(0x01‖l‖r),
odd node promoted, root = H(0x02‖count(4 bytes)‖top).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import urllib.request
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def canonical(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode()


def fingerprint(plain: dict[str, Any]) -> str:
    return "0x" + hashlib.sha256(bytes.fromhex(plain["salt"]) + canonical(plain["data"])).hexdigest()


def merkle_root(fingerprints: list[str]) -> str:
    level = [hashlib.sha256(b"\x00" + bytes.fromhex(fp[2:])).digest() for fp in fingerprints]
    while len(level) > 1:
        nxt = [hashlib.sha256(b"\x01" + level[i] + level[i + 1]).digest() for i in range(0, len(level) - 1, 2)]
        if len(level) % 2:
            nxt.append(level[-1])
        level = nxt
    top = level[0] if level else b"\x00" * 32
    return "0x" + hashlib.sha256(b"\x02" + len(fingerprints).to_bytes(4, "big") + top).hexdigest()


def _open_slot(wid: str, private: X25519PrivateKey, slot: dict[str, str]) -> dict[str, str] | None:
    shared = private.exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(slot["epk"])))
    kek = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
               info=b"buoyup-withdrawal-slot|" + wid.encode()).derive(shared)
    try:
        plain = AESGCM(kek).decrypt(base64.b64decode(slot["nonce"]), base64.b64decode(slot["ct"]), wid.encode())
    except InvalidTag:
        return None
    return json.loads(plain)["k"]


def open_record(record: dict[str, Any], private_key_hex: str) -> dict[str, Any]:
    """``record`` = {"id", "envelope", "piece_fingerprints", "merkle_root"}."""
    wid = record["id"]
    private = X25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex.strip()))
    envelope = record["envelope"]
    keys = next((k for slot in envelope["slots"] if (k := _open_slot(wid, private, slot)) is not None), None)
    if keys is None:
        return {"opened": [], "pieces": {}, "fingerprints_ok": None, "message": "this key opens no slot"}
    by_index = {p["index"]: p for p in envelope["pieces"]}
    pieces: dict[str, Any] = {}
    all_ok = True
    for index_text, key_hex in sorted(keys.items(), key=lambda kv: int(kv[0])):
        index = int(index_text)
        enc = by_index[index]
        raw = AESGCM(bytes.fromhex(key_hex)).decrypt(base64.b64decode(enc["nonce"]), base64.b64decode(enc["ct"]),
                                                     wid.encode())
        plain = json.loads(raw)
        ok = fingerprint(plain) == record["piece_fingerprints"][index]
        all_ok = all_ok and ok
        name = "summary" if index == 0 else str(plain["data"].get("bank", f"piece{index}"))
        pieces[name] = {**plain["data"], "fingerprint_ok": ok}
    root_ok = merkle_root(record["piece_fingerprints"]) == record["merkle_root"]
    return {"opened": list(pieces), "pieces": pieces, "fingerprints_ok": all_ok and root_ok, "merkle_ok": root_ok}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--token", default="")
    parser.add_argument("--id")
    parser.add_argument("--file")
    parser.add_argument("--key", required=True, help="your X25519 private key, 64 hex characters")
    args = parser.parse_args()
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            record = json.load(fh)
    elif args.id:
        req = urllib.request.Request(f"{args.api.rstrip('/')}/v4/chain/withdrawals/{args.id}/envelope",
                                     headers={"Authorization": f"Bearer {args.token}"} if args.token else {})
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - user-supplied API URL
            record = json.load(resp)
    else:
        parser.error("--id or --file is required")
    print(json.dumps(open_record(record, args.key), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
