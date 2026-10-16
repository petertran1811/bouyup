"""Bank catalog and encryption keys from the BuoyUp Chain service (remote mode only).

The chain service is the shared source of the partner banks' terms (YAML catalog, demo data):
limits, written credit policy and contract. :func:`sync_catalog` copies them into
``bu_banks`` so B12 and Agents 3–4 decide on the same terms the chain records:

==========================  ==========================================================
chain ``limits``            ``BuBank.policy`` (amounts converted from the minor unit)
==========================  ==========================================================
minAnnualRatePercent        min_rate (fraction)
maxAnnualRatePercent        max_rate (fraction)
maxSharePercent             max_share (fraction of one loan)
maxLoanAmount               max_share_amount: the most this bank funds in one loan
minWithdrawal               min_share_amount: the smallest part it takes
maxTenorDays                max_tenor_days
minStoreAgeMonths           min_store_age_months
minStoreRating              min_store_rating
feePercent                  fee_pct
contract.creditLine         BuBank.limit_total; contract.contractNo → contract_id
==========================  ==========================================================

``maxLoanAmount`` is read as the bank's part of a split loan, not the whole loan
(the service documents limits as "information for the agents", not enforced).
BuoyUp's own rules stay local: ``min_grade``, ``tiers``, ``min_share`` (platform floor),
``excluded_groups``, ``min_amount`` / ``max_amount`` of the whole loan.

The written policy (summary, red flags, when to escalate, deal breakers) is kept under
``policy.chain`` for Agent 3 and the bank portal, with its version and hash. The keys the
service encrypts withdrawals to go to ``bu_chain_keys`` (demo private keys only while the
service shows them and we run in dev/demo). One chain entry records each change of the
catalog's policy and contract hashes.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.blockchain import chain
from app.blockchain import chain_remote
from app.platform import events
from app.banks.split import MASTER_CODE, catalog
from app.blockchain.chain_remote import ChainUnavailable, from_minor
from app.platform.tables import BuBank, BuChainKey, save_json
from app.platform.config import settings
from app.platform.db.tables import utcnow

_DEMO_ENVS = ("dev", "demo", "test")
MASTER_SECRET = "BuoyUp master key"
TEXT_FIELDS = {"summary": "summary", "riskAppetite": "risk_appetite", "redFlags": "red_flags",
               "escalateWhen": "escalate_when", "dealBreakers": "deal_breakers", "useOfFunds": "use_of_funds",
               "positiveSignals": "positive_signals", "reviewerNotes": "reviewer_notes", "sectors": "sectors",
               "customers": "customers", "regions": "regions"}

# Policy keys owned by the chain catalog: dropped before each merge so a rule the service
# removes stops applying here.
CHAIN_KEYS = ("min_rate", "max_rate", "max_share", "max_share_amount", "min_share_amount", "max_tenor_days",
              "min_store_age_months", "min_store_rating", "fee_pct", "chain")

_last: dict[str, Any] = {"at": None, "ok": None, "banks": 0, "keys": 0, "changed": [], "error": None}


def _pct(value: Any) -> float | None:
    return round(float(value) / 100, 6) if value is not None else None


def chain_policy(profile: dict[str, Any], currency: str) -> dict[str, Any]:
    """The numeric rules of one bank, in BuoyUp's units (see the module table)."""
    limits = profile.get("limits") or {}
    out = {
        "min_rate": _pct(limits.get("minAnnualRatePercent")),
        "max_rate": _pct(limits.get("maxAnnualRatePercent")),
        "max_share": _pct(limits.get("maxSharePercent")),
        "max_share_amount": from_minor(int(limits["maxLoanAmount"]), currency) if limits.get("maxLoanAmount") else None,
        "min_share_amount": from_minor(int(limits["minWithdrawal"]), currency) if limits.get("minWithdrawal") else None,
        "max_tenor_days": int(limits["maxTenorDays"]) if limits.get("maxTenorDays") else None,
        "min_store_age_months": int(limits["minStoreAgeMonths"]) if limits.get("minStoreAgeMonths") else None,
        "min_store_rating": float(limits["minStoreRating"]) if limits.get("minStoreRating") else None,
        "fee_pct": _pct(limits.get("feePercent")),
    }
    return {k: v for k, v in out.items() if v is not None}


def _texts(profile: dict[str, Any]) -> dict[str, Any]:
    policy = profile.get("policy") or {}
    contract = profile.get("contract") or {}
    return {
        "source": "chain",
        "version": policy.get("version"), "updated_at": policy.get("updatedAt"), "hash": policy.get("hash"),
        **{ours: policy[theirs] for theirs, ours in TEXT_FIELDS.items() if policy.get(theirs)},
        "profile": profile.get("profile"), "disclaimer": profile.get("disclaimer"),
        "contract": {"no": contract.get("contractNo"), "status": profile.get("contractStatus") or contract.get("status"),
                     "hash": contract.get("hash"), "effective_from": contract.get("effectiveFrom"),
                     "expires_on": contract.get("expiresOn"), "reimbursement_terms": contract.get("reimbursementTerms"),
                     "fee_terms": contract.get("feeTerms")},
    }


def _demo_keys(remote: chain_remote.RemoteChain) -> dict[str, dict[str, str]]:
    """``{code|MASTER: {public, private}}`` from the overview, only while it shows demo keys."""
    if settings.app_env not in _DEMO_ENVS:
        return {}
    try:
        overview = remote.overview()
    except ChainUnavailable:
        return {}
    if not overview.get("demoKeysShown"):
        return {}
    out: dict[str, dict[str, str]] = {}
    for item in overview.get("secrets") or []:
        name = str(item.get("name") or "")
        code = MASTER_CODE if name == MASTER_SECRET else (
            name[: -len(" encryption key")] if name.endswith(" encryption key") else None)
        if code and item.get("publicKey") and item.get("privateKey"):
            out[code] = {"public": str(item["publicKey"]).lower(), "private": str(item["privateKey"]).lower(),
                         "active_from": str(item.get("activeFrom") or "")}
    return out


def _put_key(session: Session, code: str, public: str, private: str, active_from: str) -> bool:
    row = session.get(BuChainKey, code)
    if row is None:
        row = BuChainKey(bank=code)
        session.add(row)
    changed = (row.public_key, row.private_key_demo) != (public, private)
    row.public_key, row.private_key_demo, row.active_from, row.synced_at = public, private, active_from, utcnow()
    return changed


def sync_catalog(session: Session, actor: str = "system") -> dict[str, Any]:
    """Pull every local bank's terms and key from the chain service. Raises
    :class:`ChainUnavailable` when the service cannot be read (nothing is changed)."""
    remote = chain_remote.get_remote()
    listed = {str(b.get("code")): b for b in (remote.banks().get("banks") or [])}
    profiles = {code: remote.bank(code) for code in listed}
    demo = _demo_keys(remote)
    try:  # parse everything before the first write: bad data from the service changes nothing
        parsed = {code: (chain_policy(p, str(p.get("currency") or "")), _texts(p)) for code, p in profiles.items()}
    except (TypeError, ValueError) as exc:
        raise ChainUnavailable(f"Danh mục ngân hàng từ chuỗi có giá trị không hợp lệ: {exc}", kind="bad_response") from exc
    changed, keys, hashes = [], 0, {}
    for bank in catalog(session):
        profile = profiles.get(bank.code)
        if profile is None:  # not in the shared catalog: cannot be paid through the chain
            if bank.active:
                bank.active = False
                changed.append(bank.code)
            continue
        numbers, texts = parsed[bank.code]
        if str(profile.get("currency") or bank.currency) != bank.currency:
            numbers = chain_policy(profile, bank.currency)
        local = {k: v for k, v in (bank.policy or {}).items() if k not in CHAIN_KEYS}
        policy = {**local, **numbers, "chain": texts}
        active = bool(profile.get("active", True)) and (profile.get("contractStatus") or "active") == "active"
        credit_line = (profile.get("contract") or {}).get("creditLine")
        limit_total = from_minor(int(credit_line), bank.currency) if credit_line else bank.limit_total
        contract_id = texts["contract"]["no"] or bank.contract_id
        before = (json.dumps(bank.policy or {}, sort_keys=True, default=str), bank.active, bank.limit_total,
                  bank.contract_id)
        save_json(bank, "policy", policy)
        bank.active, bank.limit_total, bank.contract_id = active, limit_total, contract_id
        if before != (json.dumps(policy, sort_keys=True, default=str), active, limit_total, contract_id):
            changed.append(bank.code)
        terms = {"limits": profile.get("limits") or {}, "credit_line": credit_line, "active": active,
                 "contract_status": profile.get("contractStatus")}
        hashes[bank.code] = {"policy": texts["hash"], "contract": texts["contract"]["hash"],
                             "policy_version": texts["version"],
                             "terms": "0x" + hashlib.sha256(chain.canonical(terms)).hexdigest()}
        key = (profile.get("encryptionKey") or {})
        public = str(key.get("publicKey") or "").lower()
        mine = demo.get(bank.code) or {}
        private = mine.get("private", "") if mine.get("public") == public else ""
        if public:
            keys += 1
            _put_key(session, bank.code, public, private, str(key.get("activeFrom") or ""))
    master = demo.get(MASTER_CODE)
    if master:
        _put_key(session, MASTER_CODE, master["public"], master["private"], master["active_from"])
    session.flush()
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    last = session.scalars(select(BuBank).where(BuBank.code == MASTER_CODE)).first()
    recorded = ((last.policy or {}).get("catalog_digest") if last else None)
    entry_tx = None
    if last is not None and recorded != digest:  # one chain entry per catalog change
        entry = chain.record(session, "system", "bank_policy",
                             {"source": "chain_catalog", "url": remote.base_url, "banks": hashes, "by": actor})
        save_json(last, "policy", {**(last.policy or {}), "catalog_digest": digest})
        entry_tx = entry.tx
    events.log(session, "system", "system", "chain_catalog_sync",
               f"Đồng bộ danh mục ngân hàng từ chuỗi: {len(hashes)} ngân hàng, {keys} khóa",
               {"changed": changed, "url": remote.base_url, "chain_tx": entry_tx, "by": actor})
    _last.update(at=utcnow().isoformat() + "Z", ok=True, banks=len(hashes), keys=keys, changed=changed, error=None)
    return {**_last, "chain_tx": entry_tx}


def last_sync() -> dict[str, Any]:
    return dict(_last)


def note_failure(exc: Exception) -> None:
    _last.update(at=utcnow().isoformat() + "Z", ok=False, error=str(exc)[:300])


def chain_key(session: Session, code: str) -> BuChainKey | None:
    return session.get(BuChainKey, code)


def demo_private_key(session: Session, code: str, *, remote_record: bool) -> str:
    """The demo-held private key that opens a record: the chain service's key for a
    remote withdrawal, the local key for a local one ("" when not held)."""
    if remote_record:
        row = session.get(BuChainKey, code)
        return row.private_key_demo if row is not None else ""
    bank = session.get(BuBank, code)
    return bank.private_key_demo if bank is not None else ""
