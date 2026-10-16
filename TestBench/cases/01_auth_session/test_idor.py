"""Auth & Session — IDOR / cross-tenant isolation between sellers and roles.

Scoring: a test PASSES when BuoyUp RESISTS the attack (secure); it FAILS when the
attack SUCCEEDS (a real vulnerability). Asserts demand the secure outcome.
"""
from __future__ import annotations

import pytest

from conftest import DEMO, login, register_seller


@pytest.mark.medium
def test_auth_m5_seller_cannot_read_others_application(bu_client):
    """AUTH-M5: a seller cannot read, drive or list another seller's application (403)."""
    from app.data_sources import sources

    ha = login(bu_client, DEMO["seller"])  # Lan creates a real application
    created = bu_client.post(
        "/v4/applications", headers=ha,
        json={"tier": 2, "store_urls": [sources.demo_url("lan")]},
    )
    assert created.status_code == 201, created.text
    app_id = created.json()["id"]

    hb = register_seller(bu_client, "attacker_idor@example.vn")  # a different seller

    # Direct object reference: reading by id must be forbidden.
    r = bu_client.get(f"/v4/applications/{app_id}", headers=hb)
    assert r.status_code == 403, r.text

    # Acting on someone else's application must be forbidden too.
    r = bu_client.post(f"/v4/applications/{app_id}/identity", headers=hb,
                       json={"cccd": True, "face": True})
    assert r.status_code == 403, r.text

    # And the attacker's own listing must not leak the victim's application.
    items = bu_client.get("/v4/applications", headers=hb).json()["items"]
    assert all(it.get("id") != app_id for it in items), items


@pytest.mark.easy
def test_auth_e4_bank_cannot_access_applications(bu_client):
    """AUTH-E4: the bank role has no access to seller applications or the officer queue (403)."""
    h = login(bu_client, DEMO["webank"])
    assert bu_client.get("/v4/auth/me", headers=h).json()["user"]["role"] == "bank"

    assert bu_client.get("/v4/applications", headers=h).status_code == 403
    assert bu_client.post("/v4/applications", headers=h,
                          json={"tier": 2, "store_urls": ["https://example.vn/shop"]}).status_code == 403
    assert bu_client.get("/v4/officer/queue", headers=h).status_code == 403
