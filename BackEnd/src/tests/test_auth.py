from __future__ import annotations

from tests.conftest import login


def test_register_login_me_logout(bu_client):
    r = bu_client.post("/v4/auth/register", json={"email": "Shop@Example.vn", "password": "abc12345",
                                                    "display_name": "Shop", "accept_terms": True})
    assert r.status_code == 201
    assert r.json()["user"]["role"] == "seller"
    headers = {"Authorization": "Bearer " + r.json()["token"]}
    assert bu_client.get("/v4/auth/me", headers=headers).json()["user"]["email"] == "shop@example.vn"
    assert bu_client.post("/v4/auth/logout", headers=headers).status_code == 204
    assert bu_client.get("/v4/auth/me", headers=headers).status_code == 401


def test_register_rejects_duplicate_and_weak(bu_client):
    body = {"email": "lan@buoyup.vn", "password": "abc12345", "display_name": "X", "accept_terms": True}
    assert bu_client.post("/v4/auth/register", json=body).json()["error"]["code"] == "CONFLICT"
    body = {"email": "b@x.vn", "password": "short", "display_name": "X", "accept_terms": True}
    assert bu_client.post("/v4/auth/register", json=body).status_code == 400


def test_login_errors_and_rate_limit(bu_client):
    assert bu_client.get("/v4/auth/me").json()["error"]["code"] == "AUTH_REQUIRED"
    for _ in range(5):
        assert bu_client.post("/v4/auth/login", json={"email": "lan@buoyup.vn", "password": "nope1234"}).status_code == 401
    assert bu_client.post("/v4/auth/login", json={"email": "lan@buoyup.vn", "password": "nope1234"}).status_code == 429


def test_demo_roles(bu_client):
    for email, role in [("officer@buoyup.vn", "officer"), ("admin@buoyup.vn", "admin"), ("webank@buoyup.vn", "bank")]:
        h = login(bu_client, email)
        assert bu_client.get("/v4/auth/me", headers=h).json()["user"]["role"] == role
