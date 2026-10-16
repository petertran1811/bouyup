"""Encrypted withdrawal: who opens what, tampering, Merkle check, idempotency."""

from __future__ import annotations

import base64
import copy

import pytest
from fastapi import HTTPException

from app.blockchain import withdrawals
from app.platform.tables import BuBank, BuLoan, BuWithdrawal, save_json
from app.platform.db.session import session_scope
from tests.test_money_agent4 import disburse_lan

LAN_SHARES = [
    {"bank": "WEBANK", "pct": 0.40, "amount": 55960, "contract_id": "BU-WEBANK-2026-01"},
    {"bank": "CMB", "pct": 0.30, "amount": 41970, "contract_id": "BU-CMB-2026-01"},
    {"bank": "ICBC", "pct": 0.30, "amount": 41970, "contract_id": "BU-ICBC-2026-01"},
]


def _create(session, request_id: str = "req-1", amount: int = 139900) -> BuWithdrawal:
    return withdrawals.create_withdrawal(
        session, request_id=request_id, amount=amount, currency="CNY", region="CN", province="Quảng Đông",
        user="usr_lan", account="supplier:SUP-0091", payout_ref="PO-1", requester="agent4", shares=LAN_SHARES,
    )


def _key(session, code: str) -> str:
    return session.get(BuBank, code).private_key_demo


def test_decrypt_matrix(bu_client):
    with session_scope() as session:
        wd = _create(session)
        master = withdrawals.decrypt(wd, _key(session, "MASTER"))
        assert sorted(master["opened"]) == ["CMB", "ICBC", "WEBANK", "summary"]
        assert master["fingerprints_ok"] is True
        assert master["pieces"]["summary"]["amount"] == 139900
        assert master["pieces"]["summary"]["account_ref"].startswith("ref_")
        assert "SUP-0091" not in str(master["pieces"]["summary"])  # only the HMAC reference

        webank = withdrawals.decrypt(wd, _key(session, "WEBANK"))
        assert webank["opened"] == ["summary", "WEBANK"]
        assert webank["pieces"]["WEBANK"]["amount"] == 55960
        assert "CMB" not in webank["pieces"] and webank["fingerprints_ok"] is True

        boc = withdrawals.decrypt(wd, _key(session, "BOC"))
        assert boc["opened"] == [] and boc["message"] == "Khóa này không mở được ô nào"

        public = withdrawals.public_view(wd, detail=True)
        assert public["pieces"] == 4 and public["slots"] == 4
        assert not any(code in str(public) for code in ("WEBANK", "CMB", "ICBC"))


def test_tampered_ciphertext_fails(bu_client):
    with session_scope() as session:
        wd = _create(session)
        envelope = copy.deepcopy(wd.envelope)
        piece = next(p for p in envelope["pieces"] if p["index"] == 1)
        raw = bytearray(base64.b64decode(piece["ct"]))
        raw[0] ^= 0x01
        piece["ct"] = base64.b64encode(bytes(raw)).decode()
        save_json(wd, "envelope", envelope)
        result = withdrawals.decrypt(wd, _key(session, "MASTER"))
        assert result["fingerprints_ok"] is False and result["failed_pieces"] == [1]


def test_tampered_fingerprint_detected(bu_client):
    with session_scope() as session:
        wd = _create(session)
        fps = list(wd.piece_fingerprints)
        fps[2] = "0x" + "ab" * 32
        save_json(wd, "piece_fingerprints", fps)
        assert withdrawals.verify_record(session, wd) is False
        assert withdrawals.decrypt(wd, _key(session, "MASTER"))["fingerprints_ok"] is False


def test_merkle_mismatch_refused(bu_client):
    with session_scope() as session:
        pub = session.get(BuBank, "MASTER").public_key
        record = withdrawals.build_record("WD-TEST", [{"a": 1}, {"b": 2}], [(pub, [0, 1])])
        record["merkle_root"] = "0x" + "00" * 32
        with pytest.raises(HTTPException) as exc:
            withdrawals.anchor(session, wid="WD-TEST", request_id="r", digest="d", loan_id=None, record=record)
        assert exc.value.status_code == 400


def test_idempotent_request_id(bu_client):
    with session_scope() as session:
        first = _create(session, "req-same")
        again = _create(session, "req-same")
        assert again.id == first.id
        with pytest.raises(HTTPException) as exc:
            _create(session, "req-same", amount=100000)
        assert exc.value.status_code == 409 and exc.value.detail["code"] == "CONFLICT"


def test_aad_binds_withdrawal_id(bu_client):
    """Copying a piece into another withdrawal does not decrypt there."""
    with session_scope() as session:
        a, b = _create(session, "req-a"), _create(session, "req-b")
        envelope = copy.deepcopy(b.envelope)
        envelope["pieces"] = copy.deepcopy(a.envelope["pieces"])
        save_json(b, "envelope", envelope)
        assert withdrawals.decrypt(b, _key(session, "MASTER"))["failed_pieces"] == [0, 1, 2, 3]


def test_disbursed_loan_withdrawal_opens_per_bank(bu_client):
    _, loan_id = disburse_lan()
    with session_scope() as session:
        wd = session.get(BuWithdrawal, session.get(BuLoan, loan_id).withdrawal_id)
        cmb = withdrawals.decrypt(wd, _key(session, "CMB"))
        assert cmb["opened"] == ["summary", "CMB"] and cmb["pieces"]["CMB"]["amount"] == 45_000
        assert cmb["pieces"]["summary"]["bank_count"] == 3


def test_merkle_domain_separation():
    fps = ["0x" + bytes([i]).hex() * 32 for i in range(1, 4)]
    root3 = withdrawals.merkle_root(fps)
    assert root3 != withdrawals.merkle_root(fps + [fps[-1]])  # odd node promoted, not duplicated
    assert root3 != withdrawals.merkle_root(fps[:2])
    assert withdrawals.merkle_root(fps[:1]) != fps[0]  # a leaf is never its own root
    assert withdrawals.merkle_root(fps) == root3  # deterministic


def test_verify_record_checks_tx_and_block(bu_client):
    with session_scope() as session:
        wd = _create(session)
        assert withdrawals.verify_record(session, wd) is True
        assert withdrawals.verify_withdrawals(session) == []
        wd.block = wd.block + 99
        assert withdrawals.verify_record(session, wd) is False
        assert wd.id in withdrawals.verify_withdrawals(session)
