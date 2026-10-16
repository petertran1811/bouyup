"""Input validation & robustness: unknown ids, injection strings, oversized/malformed bodies.

Secure behaviour: unknown ids return 404 (never a 500 stack trace); SQL/NoSQL-ish
injection strings in the path/query are handled safely and never bypass authorization;
oversized or malformed bodies are rejected with 400 and nothing is created.

Scoring: PASS == rejected cleanly (400/404, authz still enforced). FAIL == 500, or a
bad/oversized payload was accepted, or injection bypassed a role check.
"""
from __future__ import annotations

import pytest

from conftest import DEMO, login

_SQLI = "' OR '1'='1"
_DROP = "'; DROP TABLE bu_user; --"
_NOSQL = '{"$ne": null}'


def _err_code(r):
    try:
        return r.json().get("error", {}).get("code")
    except Exception:  # noqa: BLE001
        return None


@pytest.mark.easy
def test_api_e4_unknown_ids_return_404_not_500(bu_client):
    """API-E4: unknown resource ids return 404 (never a 500) across every lookup route."""
    admin = login(bu_client, DEMO["admin"])
    officer = login(bu_client, DEMO["officer"])
    webank = login(bu_client, DEMO["webank"])
    probes = [
        ("PATCH", "/v4/admin/users/usr_missing", {"active": True}, admin),
        ("POST", "/v4/officer/applications/app_missing/decision", {"decision": "approve"}, officer),
        ("POST", "/v4/bank/approvals/ba_missing/sign", {"decision": "sign"}, webank),
        ("GET", "/v4/loans/loan_missing", None, officer),
        ("GET", "/v4/withdrawals/WD-NONE/verify", None, officer),
        ("GET", "/v4/chain/withdrawals/WD-NONE", None, admin),
        ("GET", "/v4/banks/NOSUCHBANK", None, admin),
        ("GET", "/v4/applications/app_missing", None, officer),
    ]
    for method, path, body, h in probes:
        r = bu_client.request(method, path, headers=h, json=body)
        assert r.status_code != 500, f"{method} {path} crashed: {r.text}"
        assert r.status_code == 404, f"{method} {path} -> {r.status_code}: {r.text}"
        assert _err_code(r) == "NOT_FOUND"


@pytest.mark.easy
def test_api_e5_schema_field_constraints_reject_bad_values(bu_client):
    """API-E5: out-of-range / unknown enum values are rejected with 400, not accepted."""
    admin = login(bu_client, DEMO["admin"])
    # Creating a user with a role the enum forbids must fail (no privilege confusion).
    for role in ("seller", "root", "superuser"):
        body = {"email": f"x-{role}@buoyup.vn", "password": "LongEnoughPw123", "display_name": "X", "role": role}
        assert bu_client.post("/v4/admin/users", json=body, headers=admin).status_code == 400, role
    # Policy fields outside their declared bounds are rejected.
    for bad in ({"max_rate": 0.99}, {"max_rate": 0}, {"tiers": [3]}, {"min_grade": "F"}, {"min_amount": -1}):
        assert bu_client.put("/v4/banks/WEBANK/policy", json=bad, headers=admin).status_code == 400, bad
    # auto-approval group must look like "<industry>|t<tier>".
    assert bu_client.put("/v4/admin/auto-approval/not-a-group", json={"enabled": True},
                         headers=admin).status_code == 400


@pytest.mark.medium
def test_api_m5_injection_strings_are_safe_and_do_not_bypass_authz(bu_client):
    """API-M5: SQL/NoSQL-ish strings in path/query never 500 and never bypass role checks."""
    admin = login(bu_client, DEMO["admin"])
    officer = login(bu_client, DEMO["officer"])
    seller = login(bu_client, DEMO["seller"])
    # Query-parameter injection: filters just no-op; the endpoint stays up and authorized.
    for value in (_SQLI, _DROP, _NOSQL):
        r = bu_client.get("/v4/admin/users", params={"role": value}, headers=admin)
        assert r.status_code == 200 and "items" in r.json(), r.text
        r = bu_client.get("/v4/applications", params={"seller": value}, headers=officer)
        assert r.status_code == 200, r.text
        r = bu_client.get("/v4/admin/audit", params={"actor": value}, headers=admin)
        assert r.status_code == 200, r.text
    # Path-parameter injection: resolves to a clean 404, never a 500.
    for value in (_SQLI, _DROP):
        assert bu_client.get(f"/v4/banks/{value}", headers=admin).status_code in (400, 404)
        assert bu_client.get(f"/v4/loans/{value}", headers=officer).status_code in (400, 404)
    # Injection must not let a seller reach an admin route.
    assert bu_client.get("/v4/admin/users", params={"role": "admin'--"}, headers=seller).status_code == 403
    # The user table still exists / login still works after the "DROP TABLE" probes.
    assert bu_client.get("/v4/admin/users", headers=admin).status_code == 200


@pytest.mark.medium
def test_api_m6_oversized_and_malformed_bodies_rejected(bu_client):
    """API-M6: oversized, missing-field, and non-JSON bodies are rejected (400); nothing created."""
    admin = login(bu_client, DEMO["admin"])
    officer = login(bu_client, DEMO["officer"])
    before = len(bu_client.get("/v4/admin/users", headers=admin).json()["items"])

    huge = "A" * 100_000
    bad_bodies = [
        ("/v4/admin/users", {"email": "a@b.vn", "password": "LongEnoughPw123", "display_name": huge, "role": "officer"}),
        ("/v4/admin/users", {"email": huge + "@b.vn", "password": "LongEnoughPw123", "display_name": "N", "role": "officer"}),
        ("/v4/admin/users", {}),  # missing required fields
    ]
    for path, body in bad_bodies:
        r = bu_client.post(path, json=body, headers=admin)
        assert r.status_code == 400, f"{path} {list(body)} -> {r.status_code}: {r.text}"

    # Semantic bound: max_amount below min_amount is rejected.
    r = bu_client.put("/v4/banks/WEBANK/policy", json={"min_amount": 5_000_000, "max_amount": 10}, headers=admin)
    assert r.status_code == 400

    # Numeric overflow on a payout amount is rejected (never silently created).
    manual = {"requestId": "ov-1", "user": "U", "account": "6222020200112233", "amount": 10 ** 15,
              "currency": "CNY", "region": "CN", "province": "CN-GD",
              "split": [{"bank": "WEBANK", "pct": 1.0}], "reason": "overflow probe"}
    assert bu_client.post("/v4/withdrawals/manual", json=manual, headers=officer).status_code == 400

    # Non-JSON garbage in a JSON endpoint is a clean 400, not a 500.
    r = bu_client.post("/v4/admin/users", headers={**admin, "Content-Type": "application/json"},
                       content=b"{not valid json")
    assert r.status_code == 400 and r.status_code != 500

    # No user was created by any of the rejected requests.
    after = len(bu_client.get("/v4/admin/users", headers=admin).json()["items"])
    assert after == before
