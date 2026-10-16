"""Auth & Session — registration hygiene, login brute-force / rate-limits, logout.

Scoring: a test PASSES when BuoyUp RESISTS the attack (secure); it FAILS when the
attack SUCCEEDS (a real vulnerability). Asserts demand the secure outcome.
"""
from __future__ import annotations

import pytest

from conftest import DEMO, DEMO_PASSWORD, login


@pytest.mark.easy
def test_auth_e2_weak_password_rejected(bu_client):
    """AUTH-E2: registration with a weak password is rejected (400)."""
    for pw in ("short", "allletters", "12345678"):
        r = bu_client.post(
            "/v4/auth/register",
            json={"email": f"weak_{pw}@example.vn", "password": pw,
                  "display_name": "X", "accept_terms": True},
        )
        assert r.status_code == 400, (pw, r.status_code, r.text)
        assert r.json()["error"]["details"]["field"] == "password", (pw, r.text)


@pytest.mark.easy
def test_auth_e3_duplicate_email_rejected(bu_client):
    """AUTH-E3: registering an already-used email is rejected (409), case-insensitively."""
    body = {"email": DEMO["seller"], "password": "abc12345", "display_name": "X", "accept_terms": True}
    r = bu_client.post("/v4/auth/register", json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONFLICT", r.text

    body["email"] = DEMO["seller"].upper()  # same account, different case
    r2 = bu_client.post("/v4/auth/register", json=body)
    assert r2.status_code == 409, r2.text


@pytest.mark.medium
def test_auth_m3_login_bruteforce_per_account(bu_client):
    """AUTH-M3: repeated wrong-password logins for one account are locked out (429)."""
    statuses = []
    for _ in range(7):
        r = bu_client.post("/v4/auth/login", json={"email": DEMO["seller"], "password": "wrongpass1"})
        statuses.append(r.status_code)

    assert 200 not in statuses, statuses              # brute force never authenticates
    assert statuses[:5] == [401] * 5, statuses        # the first 5 tries are rejected credentials
    assert statuses[5] == 429 and statuses[6] == 429, statuses  # then throttled

    # The lock cannot be bypassed: even the correct password is refused while throttled.
    r = bu_client.post("/v4/auth/login", json={"email": DEMO["seller"], "password": DEMO_PASSWORD})
    assert r.status_code == 429, r.text


@pytest.mark.hard
def test_auth_h3_login_bruteforce_per_ip(bu_client):
    """AUTH-H3: many wrong logins across different accounts from one IP are rate-limited (429)."""
    statuses = []
    for i in range(32):
        r = bu_client.post(
            "/v4/auth/login",
            json={"email": f"victim{i}@buoyup.vn", "password": "wrongpass1"},
        )
        statuses.append(r.status_code)

    assert 200 not in statuses, statuses
    # Distinct emails keep each per-account counter low, so only the per-IP budget (30) bites.
    assert all(s == 401 for s in statuses[:30]), statuses
    assert statuses[30] == 429, statuses


@pytest.mark.medium
def test_auth_m4_logout_invalidates_session(bu_client):
    """AUTH-M4: a bearer token is rejected after logout (the session cannot be reused)."""
    h = login(bu_client, DEMO["seller"])
    assert bu_client.get("/v4/auth/me", headers=h).status_code == 200

    assert bu_client.post("/v4/auth/logout", headers=h).status_code == 204
    r = bu_client.get("/v4/auth/me", headers=h)
    assert r.status_code == 401, r.text
