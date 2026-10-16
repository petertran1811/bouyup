"""Review item 4 (16/10/2026): the complaint desk."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from app.agents import complaints as desk
from app.platform.db.session import session_scope
from app.platform.db.tables import utcnow
from app.platform.tables import BuChainEntry, BuComplaint
from tests import lc
from tests.conftest import login


def _rejected(c, h):
    app = lc.start(c, h, "ecig")  # e-cigarettes: rejected by LAW-GOODS rules
    assert app["status"] == "rejected"
    return app


def test_working_days_skip_the_weekend():
    friday = datetime(2026, 10, 16, 9, 0)
    assert desk.add_working_days(friday, 1).date().isoformat() == "2026-10-19"
    assert desk.add_working_days(friday, 5).date().isoformat() == "2026-10-23"


def test_seller_complaint_gets_reasons_and_deadline(bu_client, as_seller):
    app = _rejected(bu_client, as_seller)
    r = bu_client.post("/v4/complaints", headers=as_seller,
                       json={"category": "rejection", "text": "Tôi bán thuốc lá điện tử có giấy phép", "application_id": app["id"]})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["id"].startswith("KN-") and c["status"] == "acknowledged" and c["ack_at"]
    assert c["reasons"]["decision"] == "reject" and "thuốc lá điện tử" in c["reasons"]["reason"]["factor"].lower()
    assert c["answer_due"] < c["max_due"] and c["overdue"] is False
    assert "assigned_to" not in c  # staff fields stay with staff
    with session_scope() as s:
        kinds = set(s.scalars(select(BuChainEntry.kind).where(BuChainEntry.case_id == app["id"])))
    assert "complaint_opened" in kinds
    listing = bu_client.get("/v4/complaints", headers=as_seller).json()
    assert [x["id"] for x in listing["items"]] == [c["id"]] and "95384" in listing["channel"]
    assert listing["deadlines"] == {"ack_days": 1, "answer_days": 5, "max_days": 15}


def test_limit_complaint_carries_the_b8_reason_codes(bu_client, as_seller):
    app = lc.offered(bu_client, as_seller, "thin")
    c = bu_client.post("/v4/complaints", headers=as_seller,
                       json={"category": "limit", "text": "Hạn mức thấp quá", "application_id": app["id"]}).json()
    assert any(r["code"] == "THIN_FATE_CAP" for r in c["reasons"]["reason_codes"])


def test_officer_who_decided_cannot_review_the_complaint(bu_client, as_seller, as_officer):
    app = lc.start(bu_client, as_seller, "tea")  # escalated: an officer decides
    lc.ok(bu_client.post(f"/v4/officer/applications/{app['id']}/decision", headers=as_officer,
                         json={"decision": "reject", "note": "Chưa có giấy phép thực phẩm"}))
    c = bu_client.post("/v4/complaints", headers=as_seller,
                       json={"category": "rejection", "text": "Tôi đã bổ sung giấy phép", "application_id": app["id"]}).json()
    r = bu_client.post(f"/v4/complaints/{c['id']}/assign", headers=as_officer)
    assert r.status_code == 403
    admin = login(bu_client, "admin@buoyup.vn")
    assert bu_client.post(f"/v4/complaints/{c['id']}/assign", headers=admin).json()["status"] == "in_review"


def test_answer_reopens_a_rejected_application(bu_client, as_seller, as_officer):
    app = _rejected(bu_client, as_seller)
    c = bu_client.post("/v4/complaints", headers=as_seller,
                       json={"category": "rejection", "text": "Xin xem lại hồ sơ của tôi", "application_id": app["id"]}).json()
    assert bu_client.post(f"/v4/complaints/{c['id']}/answer", headers=as_officer,
                          json={"outcome": "reopened", "text": "Mở lại để cán bộ xem giấy tờ mới"}).status_code == 403
    lc.ok(bu_client.post(f"/v4/complaints/{c['id']}/assign", headers=as_officer))
    done = lc.ok(bu_client.post(f"/v4/complaints/{c['id']}/answer", headers=as_officer,
                                json={"outcome": "reopened", "text": "Mở lại để cán bộ xem giấy tờ mới"}))
    assert done["status"] == "answered" and done["outcome_label"] == "Mở lại hồ sơ để xét lại"
    full = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    assert full["status"] == "escalated" and full["escalation"]["why"] == "COMPLAINT"
    assert full["expected_review_at"]
    queue = bu_client.get("/v4/officer/queue", headers=as_officer).json()["items"]
    assert any(i["id"] == app["id"] for i in queue)


def test_extension_is_bounded_by_the_maximum(bu_client, as_seller, as_officer):
    app = _rejected(bu_client, as_seller)
    c = bu_client.post("/v4/complaints", headers=as_seller,
                       json={"category": "rejection", "text": "Xin xem lại", "application_id": app["id"]}).json()
    lc.ok(bu_client.post(f"/v4/complaints/{c['id']}/assign", headers=as_officer))
    ext = lc.ok(bu_client.post(f"/v4/complaints/{c['id']}/extend", headers=as_officer,
                               json={"days": 5, "note": "Cần đối chiếu giấy phép với cơ quan cấp"}))
    assert ext["answer_due"] > c["answer_due"] and ext["extension_note"]
    r = bu_client.post(f"/v4/complaints/{c['id']}/extend", headers=as_officer, json={"days": 10, "note": "Thêm nữa"})
    assert r.status_code == 400


def test_overdue_complaint_goes_to_the_lead(bu_client, as_seller):
    app = _rejected(bu_client, as_seller)
    c = bu_client.post("/v4/complaints", headers=as_seller,
                       json={"category": "rejection", "text": "Xin xem lại", "application_id": app["id"]}).json()
    with session_scope() as s:
        late = desk.sweep_overdue(s, now=utcnow() + timedelta(days=30))
        assert [x.id for x in late] == [c["id"]]
        assert s.get(BuComplaint, c["id"]).status == "escalated"
    assert bu_client.get(f"/v4/complaints/{c['id']}", headers=as_seller).json()["status"] == "escalated"


def test_staff_logs_a_hotline_complaint(bu_client, as_seller, as_officer):
    r = bu_client.post("/v4/complaints", headers=as_officer,
                       json={"category": "debit", "text": "Gọi tổng đài: trích nợ hai lần", "channel": "hotline",
                             "seller_email": "lan@buoyup.vn"})
    assert r.status_code == 201 and r.json()["channel"] == "hotline"
    assert bu_client.get("/v4/complaints", headers=as_seller).json()["items"][0]["category"] == "debit"
    bad = bu_client.post("/v4/complaints", headers=as_officer, json={"category": "debit", "text": "Thiếu email"})
    assert bad.status_code == 400


def test_other_sellers_cannot_see_a_complaint(bu_client, as_seller):
    app = _rejected(bu_client, as_seller)
    c = bu_client.post("/v4/complaints", headers=as_seller,
                       json={"category": "rejection", "text": "Xin xem lại", "application_id": app["id"]}).json()
    other = bu_client.post("/v4/auth/register", json={"email": "khac@shop.vn", "password": "BuoyUp@2026a",
                                                      "display_name": "Người khác", "accept_terms": True}).json()
    h = {"Authorization": "Bearer " + other["token"]}
    assert bu_client.get(f"/v4/complaints/{c['id']}", headers=h).status_code == 404
    r = bu_client.post("/v4/complaints", headers=h, json={"category": "rejection", "text": "Hồ sơ người khác",
                                                         "application_id": app["id"]})
    assert r.status_code == 404
