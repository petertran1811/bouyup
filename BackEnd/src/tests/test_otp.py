"""SMS OTP instead of the face (no camera, no face model, failed scan): sign-up, the identity step and
the signer check before a consent or a contract. The code itself is checked in the browser for now."""

from __future__ import annotations

import copy

import numpy as np
from sqlalchemy import select

from app.api import face as face_api
from app.api.auth import mask_phone, normalize_phone
from app.data_sources import sources
from app.platform.db.session import session_scope
from app.platform.tables import BuApplication, BuEvent
from tests import lc
from tests.test_face import _enroll, _face_verify, _person, _register, fake_face  # noqa: F401 - fixture

OTP_PHONE = "•••• 678"


def _otp_register(client, email: str, phone: str | None = "0912 345 678", **extra):
    body = {"email": email, "password": "abc12345", "display_name": "Chị Mai", "accept_terms": True,
            "otp_verified": True, **extra}
    if phone is not None:
        body["phone"] = phone
    return client.post("/v4/auth/register", json=body)


def _events(kind: str) -> list[BuEvent]:
    with session_scope() as s:
        rows = list(s.scalars(select(BuEvent).where(BuEvent.kind == kind)))
        s.expunge_all()
        return rows


def _doc(app_id: str) -> dict:
    with session_scope() as s:
        return copy.deepcopy(s.get(BuApplication, app_id).doc)


def test_phone_numbers_for_the_sms_otp():
    assert normalize_phone("0912 345 678") == "+84912345678"
    assert normalize_phone("+84 0912345678") == "+84912345678"
    assert normalize_phone("+86 138 0000 0000") == "+8613800000000"
    assert normalize_phone("13800000000") == "+8613800000000"
    for bad in ("", "12345", "0212345678", "+1 415 555 2671", "+84 13800000000", "09123x5678"):
        assert normalize_phone(bad) is None, bad
    assert mask_phone("+84912345678") == OTP_PHONE


def test_register_with_otp_when_the_face_scan_is_required(bu_client, fake_face):
    # The face model is loaded: no scan and no OTP is refused as before.
    r = _register(bu_client, "mai@shop.vn", None)
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "face_enroll_id"
    # OTP chosen: the phone number is required and must be a VN/CN mobile number.
    for phone in (None, "", "12345", "+1 415 555 2671"):
        r = _otp_register(bu_client, "mai@shop.vn", phone)
        assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "phone", (phone, r.text)
    r = _otp_register(bu_client, "mai@shop.vn")
    assert r.status_code == 201, r.text
    user = r.json()["user"]
    assert user["face_enrolled"] is False and user["phone"] == "0912 345 678"
    [event] = _events("register_otp")
    assert event.application_id == user["id"] and event.payload["phone_masked"] == OTP_PHONE
    assert event.payload["checked_in"] == "browser"
    # A face scan still wins when both are sent; no OTP record then.
    enroll_id = _enroll(bu_client, "lan")
    r = _otp_register(bu_client, "lan@shop.vn", face_enroll_id=enroll_id)
    assert r.status_code == 201 and r.json()["user"]["face_enrolled"] is True
    assert len(_events("register_otp")) == 1


def test_register_otp_is_rate_limited_per_phone(bu_client, fake_face):
    for i in range(3):
        assert _otp_register(bu_client, f"shop{i}@shop.vn", "+86 138 0000 0000").status_code == 201
    r = _otp_register(bu_client, "shop9@shop.vn", "13800000000")  # same number, other spelling
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"
    assert _otp_register(bu_client, "shop9@shop.vn", "0987 654 321").status_code == 201


def test_identity_with_otp_instead_of_the_registered_face(bu_client, fake_face, as_seller):
    h = as_seller
    lan_id = bu_client.get("/v4/auth/me", headers=h).json()["user"]["id"]
    face_api.store.save(lan_id, np.stack([_person("lan")]), {}, {})  # face registered, model ready
    app_id = bu_client.post("/v4/applications", headers=h,
                            json={"tier": 2, "store_urls": [sources.demo_url("lan")]}).json()["id"]
    identity = f"/v4/applications/{app_id}/identity"
    # Neither a face re-check nor an OTP: refused as before.
    r = bu_client.post(identity, headers=h, json={"cccd": True, "face": True})
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "face_verify_id"
    r = bu_client.post(identity, headers=h, json={"cccd": True, "face": False})
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "cccd"
    r = bu_client.post(identity, headers=h, json={"cccd": False, "face": False, "otp_verified": True})
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "cccd"

    r = bu_client.post(identity, headers=h, json={"cccd": True, "face": False, "otp_verified": True,
                                                  "otp_phone": OTP_PHONE})
    assert r.status_code == 200 and r.json()["status"] == "identified", r.text
    ident = _doc(app_id)["identity"]
    assert ident["method"] == "otp" and ident["face"] is False and ident["cccd"] is True
    assert ident["otp_check"] == {"method": "sms_otp", "phone_masked": OTP_PHONE, "checked_in": "browser",
                                  "face_registered": True}
    assert "face_check" not in ident and ident["result"]["entity_match"]
    step3 = _doc(app_id)["verification"]["steps"][2]
    assert step3["status"] == "ok" and "số điện thoại (mã OTP)" in step3["summary"], step3
    [event] = [e for e in _events("identity_otp") if e.application_id == app_id]
    assert event.payload["phone_masked"] == OTP_PHONE


def test_face_identity_is_unchanged_and_wins_over_the_otp_flag(bu_client, fake_face, as_seller):
    h = as_seller
    lan_id = bu_client.get("/v4/auth/me", headers=h).json()["user"]["id"]
    face_api.store.save(lan_id, np.stack([_person("lan")]), {}, {})
    app_id = bu_client.post("/v4/applications", headers=h,
                            json={"tier": 2, "store_urls": [sources.demo_url("lan")]}).json()["id"]
    verify_id = _face_verify(bu_client, h, "lan").json()["verify_id"]
    r = bu_client.post(f"/v4/applications/{app_id}/identity", headers=h,
                       json={"cccd": True, "face": True, "face_verify_id": verify_id, "otp_verified": True})
    assert r.status_code == 200, r.text
    ident = _doc(app_id)["identity"]
    assert ident["method"] == "face" and ident["face"] is True and ident["face_check"]["score"] > 0.5
    assert "otp_check" not in ident


def test_consent_and_contract_signed_after_an_otp_are_recorded(bu_client, as_seller):
    c, h = bu_client, as_seller
    app = lc.ok(c.post("/v4/applications", headers=h, json={"tier": 2, "borrower_type": "individual_business",
                                                           "store_urls": [sources.demo_url("lan")]}))
    app_id = app["id"]
    lc.ok(c.post(f"/v4/applications/{app_id}/identity", headers=h,
                 json={"cccd": True, "face": False, "otp_verified": True, "otp_phone": OTP_PHONE}))
    # A face re-check sent with a signature must be a live one.
    r = c.post(f"/v4/applications/{app_id}/consent", headers=h,
               json={"scopes": lc.BOXES, "method": "face", "face_verify_id": "missing"})
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "face_verify_id"
    app = lc.ok(c.post(f"/v4/applications/{app_id}/consent", headers=h,
                       json={"scopes": lc.BOXES, "method": "otp", "otp_verified": True}))
    assert _doc(app_id)["consent"]["sign_method"] == "otp"
    app = lc.ok(c.put(f"/v4/applications/{app_id}/plan", headers=h, json=dict(app["plan"]["suggested"])))
    app = lc.answer_all(c, h, lc.ok(c.post(f"/v4/applications/{app_id}/verify", headers=h, json={})))
    assert app["status"] == "offered", app["status"]
    app = lc.select(c, h, app)
    lc.contract(c, h, app)
    r = lc.sign(c, h, app, method="face", face_verify_id="missing")
    assert r.status_code == 400 and r.json()["error"]["details"]["field"] == "face_verify_id"
    app = lc.ok(lc.sign(c, h, app, method="otp", otp_verified=True))
    assert app["status"] == "disbursed"
    assert _doc(app_id)["contract"]["sign_method"] == "otp"
    checks = [e.payload for e in _events("signer_verified") if e.application_id == app_id]
    assert [(p["what"], p["method"], p["otp_verified"], p["checked_in"]) for p in checks] == [
        ("ủy quyền", "otp", True, "browser"), ("hợp đồng", "otp", True, "browser")]
