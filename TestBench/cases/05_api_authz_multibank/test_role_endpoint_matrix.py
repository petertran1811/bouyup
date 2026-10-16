"""API authorization — role x endpoint matrix for the sensitive mutating routes.

Scoring: a test PASSES when BuoyUp RESISTS (wrong-role / no-token calls are blocked
with 401/403). A test FAILS when a call that should be blocked got through.

Every wrong-role call below is sent with an otherwise VALID body, so a 403 here means
the role guard rejected it (not a stray 400 from body validation masking the result).
"""
from __future__ import annotations

import pytest

from conftest import DEMO, login

# A structurally valid manual-payout body (reused as a benign body for role checks).
_MANUAL = {
    "requestId": "role-check-1", "user": "U-1", "account": "6222020200112233", "amount": 100_000,
    "currency": "CNY", "region": "CN", "province": "CN-GD",
    "split": [{"bank": "WEBANK", "pct": 0.6}, {"bank": "CMB", "pct": 0.4}],
    "reason": "role-matrix probe",
}
_CREATE_USER = {"email": "newstaff@buoyup.vn", "password": "LongEnoughPw123", "display_name": "N", "role": "officer"}


@pytest.mark.easy
def test_api_e1_seller_blocked_from_admin(bu_client):
    """API-E1: a seller cannot reach any /admin route (users, audit, auto-approval)."""
    h = login(bu_client, DEMO["seller"])
    calls = [
        ("GET", "/v4/admin/users", None),
        ("GET", "/v4/admin/audit", None),
        ("POST", "/v4/admin/users", _CREATE_USER),
        ("PATCH", "/v4/admin/users/usr_whatever", {"active": True}),
        ("PUT", "/v4/admin/auto-approval/food|t2", {"enabled": False}),
    ]
    for method, path, body in calls:
        r = bu_client.request(method, path, headers=h, json=body)
        assert r.status_code in (401, 403), f"{method} {path} -> {r.status_code}: {r.text}"


@pytest.mark.easy
def test_api_e2_no_or_garbage_token_blocked(bu_client):
    """API-E2: sensitive GET routes reject a missing or forged bearer token (401)."""
    sensitive = [
        "/v4/admin/users", "/v4/admin/audit", "/v4/portfolio", "/v4/bank/portfolio",
        "/v4/officer/queue", "/v4/withdrawals", "/v4/chain/keys", "/v4/params",
    ]
    for path in sensitive:
        assert bu_client.get(path).status_code == 401, f"no-token {path}"
        bad = {"Authorization": "Bearer not.a.real.token"}
        assert bu_client.get(path, headers=bad).status_code == 401, f"garbage-token {path}"


@pytest.mark.medium
def test_api_m1_bank_blocked_from_seller_and_staff_routes(bu_client):
    """API-M1: the bank role is confined to /bank/* and cannot read seller/officer data."""
    h = login(bu_client, DEMO["webank"])
    forbidden = [
        ("GET", "/v4/loans", None),
        ("GET", "/v4/applications", None),
        ("GET", "/v4/portfolio", None),
        ("GET", "/v4/officer/queue", None),
        ("GET", "/v4/alerts", None),
        ("GET", "/v4/params", None),
        ("GET", "/v4/postaudit/reports", None),
        ("POST", "/v4/monitoring/tick", {}),
    ]
    for method, path, body in forbidden:
        r = bu_client.request(method, path, headers=h, json=body)
        assert r.status_code == 403, f"bank {method} {path} -> {r.status_code}: {r.text}"


@pytest.mark.medium
def test_api_m2_seller_blocked_from_bank_payout_and_chain_admin(bu_client):
    """API-M2: a seller cannot reach the bank portal, staff payouts, or chain-admin routes."""
    h = login(bu_client, DEMO["seller"])
    forbidden = [
        ("GET", "/v4/bank/portfolio", None),
        ("GET", "/v4/bank/withdrawals", None),
        ("GET", "/v4/bank/approvals", None),
        ("POST", "/v4/bank/approvals/ba_x/sign", {"decision": "sign"}),
        ("POST", "/v4/withdrawals/manual", _MANUAL),
        ("GET", "/v4/withdrawals", None),
        ("POST", "/v4/chain/sync", None),
        ("GET", "/v4/chain/keys", None),
        ("GET", "/v4/admin/users", None),
    ]
    for method, path, body in forbidden:
        r = bu_client.request(method, path, headers=h, json=body)
        assert r.status_code == 403, f"seller {method} {path} -> {r.status_code}: {r.text}"


@pytest.mark.hard
def test_api_h1_officer_cannot_do_admin_only_actions(bu_client):
    """API-H1: an officer is below admin and is blocked from every admin-only route."""
    h = login(bu_client, DEMO["officer"])
    # Sanity anchor: the officer login works and officer-scoped routes are reachable.
    assert bu_client.get("/v4/officer/queue", headers=h).status_code == 200
    admin_only = [
        ("POST", "/v4/admin/users", _CREATE_USER),
        ("PATCH", "/v4/admin/users/usr_x", {"active": True}),
        ("GET", "/v4/admin/users", None),
        ("GET", "/v4/admin/audit", None),
        ("PUT", "/v4/admin/auto-approval/food|t2", {"enabled": False}),
        ("POST", "/v4/chain/sync", None),
        ("GET", "/v4/chain/keys", None),
        ("GET", "/v4/chain/verify", None),
        ("GET", "/v4/chain/outbox", None),
        ("POST", "/v4/chain/outbox/flush", None),
        ("POST", "/v4/postaudit/proposals/pr_x/decision", {"decision": "approve"}),
    ]
    for method, path, body in admin_only:
        r = bu_client.request(method, path, headers=h, json=body)
        assert r.status_code == 403, f"officer {method} {path} -> {r.status_code}: {r.text}"
