"""Face enrollment at sign-up and face login, with a scripted engine instead of buffalo_l."""

from __future__ import annotations

import base64
import itertools
import json
import math
import zlib

import numpy as np
import pytest

from Reid.src import pose
from Reid.src.engine import Detection, FaceInputError, Frame, decode_b64
from Reid.src.flows import Enrollment, FaceLogin, Registry
from Reid.src.store import FaceStore
from app.api import face as face_api

BASE_RATIO = 0.55


def _person(name: str) -> np.ndarray:
    vec = np.random.default_rng(zlib.crc32(name.encode())).normal(size=512).astype(np.float32)
    return vec / np.linalg.norm(vec)


class FakeEngine:
    """A frame is base64 JSON: {"person", "yaw", "pitch_up", "faces"}; embeddings are per person."""

    provider = "fake"
    ready = True
    error = ""

    def installed(self) -> bool:
        return True

    def status(self) -> dict:
        return {"model": "fake", "installed": True, "loaded": True, "provider": "fake", "error": ""}

    def load(self) -> None:
        return None

    def analyze(self, image_b64: str) -> Frame:
        spec = json.loads(base64.b64decode(image_b64))
        ratio = BASE_RATIO - spec.get("pitch_up", 0.0) / -pose.PITCH_DEG_PER_RATIO
        faces = [Detection(bbox=np.array([200.0, 120.0, 440.0, 380.0]), kps=np.zeros((5, 2)), score=0.9,
                           yaw=spec.get("yaw", 0.0), pitch_ratio=ratio, roll=0.0)
                 for _ in range(spec.get("faces", 1))]
        frame = Frame(image=spec.get("person"), width=640, height=480, faces=faces)
        return frame

    def embed(self, frame: Frame, det: Detection) -> np.ndarray:
        rng = np.random.default_rng(int(abs(det.yaw) * 10))
        vec = _person(frame.image) + rng.normal(scale=0.01, size=512).astype(np.float32)
        return vec / np.linalg.norm(vec)

    def crop_jpeg(self, frame: Frame, det: Detection) -> bytes:
        return b"jpeg"


_frames = itertools.count()


def _img(person: str, yaw: float = 0.0, pitch_up: float = 0.0, faces: int = 1) -> dict:
    # "n" makes every frame unique, like camera noise (identical frames are skipped)
    spec = {"person": person, "yaw": yaw, "pitch_up": pitch_up, "faces": faces, "n": next(_frames)}
    return {"image": base64.b64encode(json.dumps(spec).encode()).decode()}


@pytest.fixture()
def fake_face(monkeypatch, tmp_path):
    monkeypatch.setattr(face_api, "engine", FakeEngine())
    monkeypatch.setattr(face_api, "store", FaceStore(str(tmp_path / "faces")))
    monkeypatch.setattr(face_api, "enrollments", Registry(face_api.ENROLL_TTL))
    monkeypatch.setattr(face_api, "logins", Registry(face_api.LOGIN_TTL))
    monkeypatch.setattr(face_api, "_MIN_FRAME_GAP", 0.0)
    return tmp_path / "faces"


def _enroll(client, person: str) -> str:
    r = client.post("/v4/face/enroll")
    assert r.status_code == 200, r.text
    enroll_id = r.json()["enroll_id"]
    for _ in range(3):
        out = client.post(f"/v4/face/enroll/{enroll_id}/frame", json=_img(person)).json()
    assert out["stage"] == "turn" and out["next_segment"] is not None
    for i in range(pose.SEGMENTS):
        angle = i * 2 * math.pi / pose.SEGMENTS
        r = client.post(f"/v4/face/enroll/{enroll_id}/frame", json=_img(
            person, yaw=-1.3 * pose.SEGMENT_YAW_DEG * math.cos(angle),
            pitch_up=1.3 * pose.SEGMENT_PITCH_DEG * math.sin(angle)))
        if r.status_code != 200:
            return r
        assert r.json()["segments"][i], (i, r.json())
    assert r.json()["done"] and r.json()["progress"] == 1.0
    return enroll_id


def _register(client, email: str, enroll_id: str | None):
    body = {"email": email, "password": "abc12345", "display_name": "Chị Mai", "accept_terms": True}
    if enroll_id:
        body["face_enroll_id"] = enroll_id
    return client.post("/v4/auth/register", json=body)


def _face_login(client, person: str, *, turn: bool = True, email: str = "", gradual: bool = True):
    login = client.post("/v4/face/login", json={"email": email}).json()
    for _ in range(12):
        r = client.post(f"/v4/face/login/{login['login_id']}/frame", json=_img(person))
        if r.status_code != 200 or r.json()["stage"] != "frontal":
            break
    sign = 1 if r.status_code == 200 and r.json()["challenge"] == "left" else -1
    for i in range(50):
        if r.status_code != 200 or r.json().get("token"):
            return r
        yaw = (12.0 if gradual and i == 0 else 30.0) if turn else 0.0
        r = client.post(f"/v4/face/login/{login['login_id']}/frame", json=_img(person, yaw=sign * yaw))
    return r


def test_head_pose_from_landmarks():
    frontal = np.array([[40, 50], [80, 50], [60, 72], [45, 90], [75, 90]], dtype=float)
    yaw, ratio, roll = pose.head_pose(frontal)
    assert abs(yaw) < 1 and abs(roll) < 1 and 0.5 < ratio < 0.6
    # nose towards the raw frame's right = the person turned to their own left (positive)
    turned = frontal.copy(); turned[2, 0] += 10
    assert pose.head_pose(turned)[0] > 20
    # the same turn with the head rolled 30 degrees reads the same yaw
    c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
    rolled = (turned - 60) @ np.array([[c, -s], [s, c]]).T + 60
    assert abs(pose.head_pose(rolled)[0] - pose.head_pose(turned)[0]) < 0.5
    assert pose.segment(-30, 0) == (0, 1.5)  # mirrored view: the person's right is screen right
    assert pose.segment(0, 20)[0] == 2 and pose.segment(30, 0)[0] == 4 and pose.segment(0, -20)[0] == 6


def test_signup_with_face_then_face_login(bu_client, fake_face):
    enroll_id = _enroll(bu_client, "mai")
    r = _register(bu_client, "mai@shop.vn", enroll_id)
    assert r.status_code == 201, r.text
    user_id = r.json()["user"]["id"]
    assert (fake_face / user_id / "templates.npy").exists()
    assert len(list((fake_face / user_id / "crops").glob("*.jpg"))) == 3 + pose.SEGMENTS

    r = _face_login(bu_client, "mai")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == "mai@shop.vn" and body["token"]
    me = bu_client.get("/v4/auth/me", headers={"Authorization": "Bearer " + body["token"]})
    assert me.status_code == 200 and me.json()["user"]["id"] == user_id
    assert _face_login(bu_client, "mai", email="mai@shop.vn").status_code == 200  # 1:1 with email


def test_face_login_rejects_strangers_and_still_photos(bu_client, fake_face):
    _register(bu_client, "mai@shop.vn", _enroll(bu_client, "mai"))
    r = _face_login(bu_client, "stranger")
    assert r.status_code == 401 and r.json()["error"]["code"] == "FACE_NOT_RECOGNIZED"
    r = _face_login(bu_client, "mai", turn=False)  # a photo held still never turns
    assert r.status_code == 401 and r.json()["error"]["code"] == "FACE_LIVENESS_FAILED"
    r = _face_login(bu_client, "mai", gradual=False)  # frontal picture swapped for a profile picture
    assert r.status_code == 401 and r.json()["error"]["code"] == "FACE_LIVENESS_FAILED"
    r = _face_login(bu_client, "mai", email="lan@buoyup.vn")  # someone else's account (1:1)
    assert r.status_code == 401 and r.json()["error"]["code"] == "FACE_NOT_RECOGNIZED"


def test_repeated_frames_do_not_count(bu_client, fake_face, monkeypatch):
    _register(bu_client, "mai@shop.vn", _enroll(bu_client, "mai"))
    login = bu_client.post("/v4/face/login", json={}).json()
    frame = _img("mai")
    path = f"/v4/face/login/{login['login_id']}/frame"
    assert bu_client.post(path, json=frame).json()["stage"] == "frontal"
    for _ in range(3):
        assert bu_client.post(path, json=frame).json()["hint"] == "STILL_FRAME"
    assert bu_client.post(path, json=_img("mai")).json()["stage"] == "turn"
    monkeypatch.setattr(face_api, "_MIN_FRAME_GAP", 60.0)
    assert bu_client.post(path, json=_img("mai")).status_code == 429  # one flow cannot flood the model


def test_one_face_one_account(bu_client, fake_face):
    enroll_id = _enroll(bu_client, "mai")
    assert _register(bu_client, "mai@shop.vn", enroll_id).status_code == 201
    assert _register(bu_client, "mai2@shop.vn", enroll_id).status_code == 400  # a scan is single-use
    r = _register(bu_client, "mai2@shop.vn", _enroll(bu_client, "mai"))  # checked at sign-up, not at scan end
    assert r.status_code == 409 and r.json()["error"]["code"] == "FACE_ALREADY_REGISTERED"
    assert bu_client.post("/v4/auth/login", json={"email": "mai2@shop.vn", "password": "abc12345"}).status_code == 401


def test_orphaned_templates_do_not_block_a_face(bu_client, fake_face):
    face_api.store.save("usr_never_committed", np.stack([_person("mai")]), {}, {})
    assert _register(bu_client, "mai@shop.vn", _enroll(bu_client, "mai")).status_code == 201
    assert not (fake_face / "usr_never_committed").exists()


def test_register_needs_a_finished_scan(bu_client, fake_face):
    r = _register(bu_client, "mai@shop.vn", None)  # the model is loaded: a scan is required
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "face_enroll_id"
    enroll_id = bu_client.post("/v4/face/enroll").json()["enroll_id"]
    r = bu_client.post(f"/v4/face/enroll/{enroll_id}/frame", json=_img("mai", faces=2))
    assert r.json()["hint"] == "MULTIPLE_FACES" and r.json()["center"] == 0
    r = _register(bu_client, "mai@shop.vn", enroll_id)
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "face_enroll_id"
    assert _register(bu_client, "mai@shop.vn", "missing").status_code == 400


def test_frames_must_be_small_jpegs():
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 32).decode()
    with pytest.raises(FaceInputError):
        decode_b64(png)
    huge = b"\xff\xd8\xff\xc0\x00\x11\x08" + (30000).to_bytes(2, "big") * 2 + b"\x03" + b"\0" * 9
    with pytest.raises(FaceInputError):
        decode_b64(base64.b64encode(huge).decode())
    ok = b"\xff\xd8\xff\xe0\x00\x04\x00\x00\xff\xc0\x00\x11\x08" + (480).to_bytes(2, "big") + (640).to_bytes(2, "big") + b"\x03" + b"\0" * 9
    assert decode_b64(base64.b64encode(ok).decode()) == ok


def test_face_unavailable_is_503(bu_client, monkeypatch):
    monkeypatch.setattr(face_api.settings, "face_auth_enabled", False)
    assert bu_client.post("/v4/face/enroll").status_code == 503
    assert bu_client.get("/v4/face/status").json()["available"] is False


def test_flows_reset_when_someone_else_steps_in():
    flow, fake = Enrollment(), FakeEngine()
    for person in ("mai", "mai", "lan"):
        frame = fake.analyze(_img(person)["image"])
        out = flow.feed(frame, lambda det: fake.embed(frame, det), lambda det: b"")
    assert out["hint"] == "FACE_CHANGED" and out["center"] == 0
    login = FaceLogin(challenge="left")
    assert login.state("OK", "")["challenge"] is None  # the challenge is revealed only after identification


def _face_verify(client, h: dict, person: str):
    start = client.post("/v4/face/verify", headers=h)
    if start.status_code != 200:
        return start
    path = f"/v4/face/verify/{start.json()['verify_id']}/frame"
    for _ in range(12):
        r = client.post(path, headers=h, json=_img(person))
        if r.status_code != 200 or r.json()["stage"] != "frontal":
            break
    sign = 1 if r.status_code == 200 and r.json()["challenge"] == "left" else -1
    for yaw in [12.0] + [30.0] * 49:
        if r.status_code != 200 or r.json()["done"]:
            return r
        r = client.post(path, headers=h, json=_img(person, yaw=sign * yaw))
    return r


def test_identity_step_rechecks_the_registered_face(bu_client, fake_face, as_seller):
    from app.data_sources import sources

    h = as_seller
    lan_id = bu_client.get("/v4/auth/me", headers=h).json()["user"]["id"]
    app_id = bu_client.post("/v4/applications", headers=h,
                            json={"tier": 2, "store_urls": [sources.demo_url("lan")]}).json()["id"]
    identity = f"/v4/applications/{app_id}/identity"
    # no registered face: the simulated tiles are enough, as before
    assert bu_client.post("/v4/face/verify", headers=h).json()["error"]["code"] == "FACE_NOT_ENROLLED"

    face_api.store.save(lan_id, np.stack([_person("lan")]), {}, {})
    r = bu_client.post(identity, headers=h, json={"cccd": True, "face": True})
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "face_verify_id"

    r = _face_verify(bu_client, h, "stranger")
    assert r.status_code == 403 and r.json()["error"]["code"] == "FACE_NOT_RECOGNIZED"
    assert bu_client.get("/v4/auth/me", headers=h).status_code == 200  # a failed re-check keeps the session

    r = _face_verify(bu_client, h, "lan")
    assert r.status_code == 200 and r.json()["done"], r.text
    verify_id = r.json()["verify_id"]
    r = bu_client.post(identity, headers=h, json={"cccd": True, "face": True, "face_verify_id": verify_id})
    assert r.status_code == 200 and r.json()["status"] == "identified", r.text
    assert face_api.consume_verification(verify_id, type("U", (), {"id": lan_id})()) is None  # single use
