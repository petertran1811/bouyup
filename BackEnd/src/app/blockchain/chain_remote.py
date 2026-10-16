"""Adapter for the remote BuoyUp Chain service (FISCO BCOS v2.11.1, e.g. fs.buoyup.app).

Field names follow the service's OpenAPI document (``<BUOYUP_CHAIN_URL>/openapi.json``,
"BuoyUp Chain API" 2.0.0, read 2026-10-13):

- ``POST /v1/audit/anchors`` ``{subject, kind, contentHash, uri}`` → AnchorRecord
  ``{subject, index, kind, contentHash, timestamp, writer, head, tx}``; 409 ``duplicate``
  when the same content is anchored twice for one subject.
- ``GET /v1/audit/anchors/{subject}/verify`` → ``{valid, records, head, brokenAt}``.
- ``POST /v1/withdrawals`` ``{requestId, userId, accountNo, amount, currency, region,
  province, bankSplit{code: percent}, actor}`` → Withdrawal ``{withdrawalId, legs[],
  onChain{root, commitments, pieces, slots, envelopeBytes, blockNumber, txHash},
  chain{sealedBy, confirmedNodes, totalNodes, …}}``. Amounts are in the minor unit
  (CNY in fen, VND in đồng); a replayed ``requestId`` returns ``replayed: true``.
- ``GET /v1/withdrawals/{id}/verify`` → ``{valid, checks[{name, ok, detail}], chain, root}``.
- ``PUT /v1/banks/{code}/public-key`` ``{publicKey}``; ``GET /v1/regions``; ``GET /v1/chain``;
  ``POST /explorer/api/decrypt`` ``{withdrawalId, privateKey}``.
- ``GET /v1/banks/{code}`` → Bank ``{code, active, contractStatus, limits{…, in the minor unit},
  policy{summary, redFlags, escalateWhen, dealBreakers, version, hash, …}, contract{contractNo,
  creditLine, status, hash, …}, encryptionKey{publicKey, activeFrom}}`` (``chain_sync``).
- ``GET /v1/overview`` → ``{demoKeysShown, secrets[{name, publicKey, privateKey}]}``: the demo
  key of every bank and of the master, shown only while the service runs with demo keys.
- ``POST /v1/audit/verify`` ``{contentHash}`` → ``{found, record}``.
- ``explorerUrl`` / ``verifyUrl`` in a withdrawal's ``chain`` are relative to the service.

Every failure (unreachable, timeout, 5xx, unexpected 4xx) raises :class:`ChainUnavailable`
with the service's own error ``kind`` when it sent one, so callers fail clearly.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.platform.config import settings

# Our chain-entry kinds → the service's anchor kinds (its enum is closed).
ANCHOR_KINDS: dict[str, str] = {
    "consent": "application",
    "consent_revoked": "application",
    "verification": "agent_io",
    "offer": "algorithm_output",
    "proposal": "credit_memo",
    "agent3_phase1_seal": "risk_challenge",
    "agent3_conclusion": "risk_challenge",
    "debate_round": "risk_challenge",
    "gate_decision": "decision_package",
    "syndicate": "decision_package",
    "officer_decision": "human_decision",
    "complaint_opened": "other",
    "complaint_answered": "human_decision",
    "contract_signed": "decision_package",
    "escrow_funded": "decision_package",
    "disbursement": "decision_package",
    "repayment": "sweep_notice",
    "bureau_report": "other",
    "misuse_flag": "risk_challenge",
    "params": "other",
    "ruleset": "other",
    "bank_policy": "other",
    "postaudit_report": "other",
}
MINOR_UNIT = {"CNY": 100, "VND": 1}


class ChainUnavailable(Exception):
    """The remote chain could not complete a call."""

    def __init__(self, message: str, *, kind: str = "unreachable", status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status


class RemoteChain:
    """Synchronous client (routes are sync and run in FastAPI's threadpool)."""

    def __init__(self, base_url: str, token: str = "", *, timeout: float = 10.0,
                 transport: httpx.BaseTransport | None = None) -> None:
        if not base_url.strip():
            raise ChainUnavailable("BUOYUP_CHAIN_URL chưa được cấu hình cho chế độ chuỗi remote.",
                                   kind="not_configured")
        self.base_url = base_url.strip().rstrip("/")
        headers = {"Authorization": f"Bearer {token.strip()}"} if token.strip() else {}
        self._client = httpx.Client(base_url=self.base_url, headers=headers, timeout=timeout, transport=transport)

    # --- plumbing -------------------------------------------------------------

    def _call(self, method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None,
              ok_conflict: bool = False) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, json=json, params=params)
        except httpx.HTTPError as exc:
            raise ChainUnavailable(f"Không kết nối được dịch vụ chuỗi {self.base_url}: {type(exc).__name__}") from exc
        if response.status_code == 409 and ok_conflict:
            return {"duplicate": True}
        if response.status_code >= 400:
            kind, message = "http_error", response.text[:300]
            try:
                err = response.json().get("error") or {}
                kind, message = str(err.get("kind") or kind), str(err.get("message") or message)
            except ValueError:
                pass
            raise ChainUnavailable(f"Dịch vụ chuỗi trả lỗi {response.status_code} ({kind}): {message}",
                                   kind=kind, status=response.status_code)
        try:
            return response.json()
        except ValueError as exc:
            raise ChainUnavailable("Dịch vụ chuỗi trả dữ liệu không phải JSON.", kind="bad_response") from exc

    # --- audit trail ------------------------------------------------------------

    def post_anchor(self, subject: str, kind: str, content_hash: str, uri: str = "") -> dict[str, Any]:
        """Anchor one fingerprint. A 409 ``duplicate`` (retry of an anchor that already
        landed) counts as success: ``{"duplicate": True}``."""
        body: dict[str, Any] = {"subject": subject, "kind": ANCHOR_KINDS.get(kind, "other"),
                                "contentHash": content_hash}
        if uri:
            body["uri"] = uri[:256]
        out = self._call("POST", "/v1/audit/anchors", json=body, ok_conflict=True)
        tx = out.get("tx") or {}
        return {"tx": str(tx.get("txHash") or tx.get("hash") or out.get("txHash") or ""),
                "block": int(tx.get("blockNumber") or out.get("blockNumber") or 0),
                "index": out.get("index"), "head": out.get("head"), "duplicate": bool(out.get("duplicate"))}

    def verify_case(self, subject: str) -> dict[str, Any]:
        out = self._call("GET", f"/v1/audit/anchors/{subject}/verify")
        return {"valid": bool(out.get("valid")), "records": int(out.get("records") or 0),
                "head": out.get("head"), "broken_at": out.get("brokenAt")}

    # --- withdrawals -------------------------------------------------------------

    def post_withdrawal(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", "/v1/withdrawals", json=request)

    def get_withdrawal(self, wid: str) -> dict[str, Any]:
        return self._call("GET", f"/v1/withdrawals/{wid}")

    def verify_withdrawal(self, wid: str) -> dict[str, Any]:
        return self._call("GET", f"/v1/withdrawals/{wid}/verify")

    def decrypt(self, wid: str, private_key_hex: str) -> dict[str, Any]:
        return self._call("POST", "/explorer/api/decrypt", json={"withdrawalId": wid, "privateKey": private_key_hex})

    # --- catalog and status ----------------------------------------------------------

    def verify_content(self, content_hash: str) -> dict[str, Any]:
        """Was this exact fingerprint anchored? ``{found, record}``."""
        return self._call("POST", "/v1/audit/verify", json={"contentHash": content_hash})

    def put_bank_key(self, code: str, public_key_hex: str) -> dict[str, Any]:
        return self._call("PUT", f"/v1/banks/{code}/public-key", json={"publicKey": public_key_hex})

    def banks(self) -> dict[str, Any]:
        return self._call("GET", "/v1/banks")

    def bank(self, code: str) -> dict[str, Any]:
        return self._call("GET", f"/v1/banks/{code}")

    def overview(self) -> dict[str, Any]:
        return self._call("GET", "/v1/overview")

    def regions(self) -> dict[str, Any]:
        return self._call("GET", "/v1/regions")

    def status(self) -> dict[str, Any]:
        return self._call("GET", "/v1/chain")


_override: RemoteChain | None = None
_cached: RemoteChain | None = None


def set_remote(client: RemoteChain | None) -> None:
    """Install a client (tests pass one built on ``httpx.MockTransport``); None resets."""
    global _override, _cached
    _override, _cached = client, None


def get_remote() -> RemoteChain:
    global _cached
    if _override is not None:
        return _override
    if _cached is None:
        _cached = RemoteChain(settings.buoyup_chain_url, settings.buoyup_chain_token,
                              timeout=settings.buoyup_chain_timeout_seconds)
    return _cached


def absolute_url(path: str | None) -> str | None:
    """The service returns explorer links relative to itself (``/explorer/#/…``)."""
    if not path:
        return None
    if path.startswith(("http://", "https://")):
        return path
    return get_remote().base_url + "/" + path.lstrip("/")


def to_minor(amount: int, currency: str) -> int:
    return int(amount) * MINOR_UNIT.get(currency, 1)


def from_minor(amount: int, currency: str) -> int:
    return int(amount) // MINOR_UNIT.get(currency, 1)
