"""Auth & Session — access control, role confinement and bearer-token forgery.

Scoring: a test PASSES when BuoyUp RESISTS the attack (secure); it FAILS when the
attack SUCCEEDS (a real vulnerability). Every assert therefore demands the secure
outcome (401/403/role unchanged). Case ids are stable and prefixed AUTH-.
"""
from __future__ import annotations

import base64
import secrets

import pytest

from conftest import DEMO, DEMO_PASSWORD, login, register_seller


@pytest.mark.easy
def test_auth_e1_protected_routes_require_auth(bu_client):
    """AUTH-E1: protected routes reject requests that carry no token (401)."""
    routes = [
        "/v4/auth/me",
        "/v4/admin/users",
        "/v4/admin/audit",
        "/v4/officer/queue",
        "/v4/loans",
        "/v4/portfolio",
        "/v4/chain/status",
        "/v4/bank/portfolio",
        "/v4/applications",
    ]
    for path in routes:
        r = bu_client.get(path)
        assert r.status_code == 401, (path, r.status_code, r.text)
        assert r.json()["error"]["code"] == "AUTH_REQUIRED", (path, r.text)


@pytest.mark.medium
def test_auth_m1_seller_cannot_reach_staff_routes(bu_client):
    """AUTH-M1: a seller token is refused on officer/admin/bank routes (403)."""
    h = register_seller(bu_client, "attacker_m1@example.vn")
    me = bu_client.get("/v4/auth/me", headers=h).json()["user"]
    assert me["role"] == "seller", me

    forbidden = [
        "/v4/admin/users",
        "/v4/admin/audit",
        "/v4/officer/queue",
        "/v4/portfolio",
        "/v4/bank/portfolio",
        "/v4/chain/verify",
    ]
    for path in forbidden:
        r = bu_client.get(path, headers=h)
        assert r.status_code == 403, (path, r.status_code, r.text)

    # A seller must not be able to mint a staff account through the admin API.
    r = bu_client.post(
        "/v4/admin/users",
        headers=h,
        json={"email": "evil@x.vn", "password": "longenoughpw123",
              "display_name": "E", "role": "admin"},
    )
    assert r.status_code == 403, r.text

    # Nor patch its own row up to admin.
    r = bu_client.patch(f"/v4/admin/users/{me['id']}", headers=h, json={"role": "admin"})
    assert r.status_code == 403, r.text


@pytest.mark.medium
def test_auth_m2_register_cannot_set_role(bu_client):
    """AUTH-M2: role/bank_code injected into the register body cannot grant privileges."""
    r = bu_client.post(
        "/v4/auth/register",
        json={
            "email": "escalate@example.vn",
            "password": "abc12345",
            "display_name": "E",
            "accept_terms": True,
            # Injected privilege fields — must be ignored by the server.
            "role": "admin",
            "bank_code": "WEBANK",
            "active": True,
        },
    )
    assert r.status_code == 201, r.text
    user = r.json()["user"]
    assert user["role"] == "seller", user
    assert user.get("bank_code") in (None, ""), user

    h = {"Authorization": "Bearer " + r.json()["token"]}
    # The freshly minted account is still just a seller, locked out of admin.
    assert bu_client.get("/v4/admin/users", headers=h).status_code == 403


@pytest.mark.hard
def test_auth_h1_forged_bearer_rejected(bu_client):
    """AUTH-H1: forged / garbage / wrong-scheme bearer tokens do not authenticate."""
    login(bu_client, DEMO["admin"])  # a real admin session exists in the DB

    for tok in ["not.a.real.token", "", "null", "a" * 43, secrets.token_urlsafe(32)]:
        r = bu_client.get("/v4/auth/me", headers={"Authorization": "Bearer " + tok})
        assert r.status_code == 401, (repr(tok[:12]), r.status_code, r.text)

    # A Basic-auth header with real credentials is not a session token.
    basic = base64.b64encode(f"{DEMO['admin']}:{DEMO_PASSWORD}".encode()).decode()
    r = bu_client.get("/v4/auth/me", headers={"Authorization": "Basic " + basic})
    assert r.status_code == 401, r.text


@pytest.mark.hard
def test_auth_h2_tampered_token_rejected(bu_client):
    """AUTH-H2: flipping or truncating a valid token invalidates it (401)."""
    r = bu_client.post("/v4/auth/login", json={"email": DEMO["admin"], "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert bu_client.get("/v4/auth/me", headers={"Authorization": "Bearer " + token}).status_code == 200

    flipped = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert bu_client.get("/v4/auth/me", headers={"Authorization": "Bearer " + flipped}).status_code == 401

    truncated = token[:-5]
    assert bu_client.get("/v4/auth/me", headers={"Authorization": "Bearer " + truncated}).status_code == 401
