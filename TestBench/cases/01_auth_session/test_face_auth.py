"""Auth & Session — face / ReID login: anonymous access, spoofing, replay, rate-limits.

Scoring: a test PASSES when BuoyUp RESISTS the attack (secure); it FAILS when the
attack SUCCEEDS (a real vulnerability). Asserts demand the secure outcome.

The engine-driven tests install a scripted fake engine (same machinery the backend's
own test_face.py uses) via the ``fake_face`` fixture, so no real model is ever loaded
(a real load would be slow and would leak enrolled-state across the whole session).
The non-engine tests deliberately stay on code paths that never reach the engine.
"""
from __future__ import annotations

import pytest

from conftest import DEMO  # noqa: F401  (kept for parity / future cases)

# Proven helpers + fake engine from the backend's face suite (import-only: not collected here).
from Reid.src.flows import Enrollment, FaceLogin, Registry  # noqa: F401
from Reid.src.store import FaceStore
from app.api import face as face_api
from tests.test_face import FakeEngine, _enroll, _face_login, _register


@pytest.fixture()
def fake_face(monkeypatch, tmp_path):
    """Scripted engine + throwaway face store; reverted after the test (no real model load)."""
    monkeypatch.setattr(face_api, "engine", FakeEngine())
    monkeypatch.setattr(face_api, "store", FaceStore(str(tmp_path / "faces")))
    monkeypatch.setattr(face_api, "enrollments", Registry(face_api.ENROLL_TTL))
    monkeypatch.setattr(face_api, "logins", Registry(face_api.LOGIN_TTL))
    monkeypatch.setattr(face_api, "_MIN_FRAME_GAP", 0.0)
    return tmp_path / "faces"


@pytest.mark.easy
def test_auth_e5_face_verify_requires_auth(bu_client):
    """AUTH-E5: the signed-in face re-check endpoints reject anonymous callers (401)."""
    assert bu_client.post("/v4/face/verify").status_code == 401
    r = bu_client.post("/v4/face/verify/anything/frame", json={"image": "A" * 40})
    assert r.status_code == 401, r.text


@pytest.mark.medium
def test_auth_m6_face_login_bogus_and_garbage(bu_client):
    """AUTH-M6: face-login frames with an undersized image or a bogus session id are rejected."""
    # Undersized / garbage image is a validation error, not a 500.
    r = bu_client.post("/v4/face/login/whatever/frame", json={"image": "short"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR", r.text

    # A well-formed frame against an unknown login id is a dead end (404), never a bypass.
    r = bu_client.post("/v4/face/login/does-not-exist/frame", json={"image": "A" * 64})
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND", r.text
    assert "token" not in r.json()


@pytest.mark.hard
def test_auth_h4_enroll_then_impersonate(bu_client, fake_face):
    """AUTH-H4: an enrolled face cannot be impersonated by a stranger, a wrong account, or a photo."""
    r = _register(bu_client, "mai@shop.vn", _enroll(bu_client, "mai"))
    assert r.status_code == 201, r.text

    # 1:N — a different person must not be recognized as the enrolled seller.
    r = _face_login(bu_client, "stranger")
    assert r.status_code == 401 and r.json()["error"]["code"] == "FACE_NOT_RECOGNIZED", r.text

    # 1:1 — a stranger pointing the flow at mai's account must still fail.
    r = _face_login(bu_client, "stranger", email="mai@shop.vn")
    assert r.status_code == 401 and r.json()["error"]["code"] == "FACE_NOT_RECOGNIZED", r.text

    # Liveness — a still photo of the real face (never turns) must be refused, no token issued.
    r = _face_login(bu_client, "mai", turn=False)
    assert r.status_code == 401 and r.json()["error"]["code"] == "FACE_LIVENESS_FAILED", r.text
    assert "token" not in r.json()


@pytest.mark.hard
def test_auth_h5_face_login_ip_flood(bu_client, fake_face):
    """AUTH-H5: repeated face-login starts from one IP are rate-limited (429), no session issued."""
    statuses = []
    for _ in range(32):
        r = bu_client.post("/v4/face/login", json={})
        statuses.append(r.status_code)
        assert "token" not in r.json()  # a login *start* must never hand out a session

    # The per-IP failure budget is 30; the 31st start is throttled.
    assert 429 in statuses, statuses
    assert statuses[30] == 429, statuses
