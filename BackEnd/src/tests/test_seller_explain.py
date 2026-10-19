"""SELLER_SERVICES_PLAN §4 (Việc 1): Agent 3 explains its decision to the seller.

Every sentence comes from the case (offer reason codes, Agent 3's concerns, the banks' own answers);
the challenger model is named without its figures; an AML case gets no reasons; a "vì sao" question in
the chat is answered from the explanation instead of being taken as a request for an officer."""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import quote

from app.agents import agent3_control as control
from app.agents.notify import SELLER_ADDRESS
from app.data_sources import sources
from app.platform.db.session import session_scope
from app.platform.tables import BuBank, save_json
from tests import lc

GROUP = "thời trang|t2"


def _policy(code: str, **changes) -> None:
    with session_scope() as s:
        bank = s.get(BuBank, code)
        policy = dict(bank.policy or {})
        policy.update(changes)
        save_json(bank, "policy", policy)


def _lan_price_120(client, h) -> dict:
    plan = {**sources.suggested_plan(sources.SCENARIOS["lan"][3]), "price": 120}
    return lc.answer_all(client, h, lc.start(client, h, "lan", plan=plan))


def _texts(exp: dict) -> list[str]:
    return [b["text"] for b in exp["because"]]


def test_explanation_lists_price_and_bank_reasons(bu_client, as_seller, as_officer):
    # CMB takes stores rated from 4,7 (chị Lan: 4,6); ICBC stores selling for 36 months (she has 26).
    _policy("CMB", min_store_rating=4.7)
    _policy("ICBC", min_store_age_months=36)
    app = _lan_price_120(bu_client, as_seller)
    assert app["status"] == "offered", app["status"]
    exp = app["decision"]["explanation"]
    because = _texts(exp)
    assert any("120" in t and "62" in t for t in because), because
    assert any("China Merchants Bank" in t and "4,7" in t and "4,6" in t for t in because), because
    assert any("Industrial and Commercial Bank of China" in t and "36 tháng" in t for t in because), because
    assert len(because) <= 4 and 1 <= len(exp["improve"]) <= 3
    blob = json.dumps(exp, ensure_ascii=False)
    assert "65" not in blob and "PD" not in blob and "xác suất" not in blob
    assert exp["hidden"] is False and exp["source"] == "template" and "140.000" in exp["headline"]
    # The invoice upload is a button that opens the application on the invoice data type.
    assert {"view": "apply", "data_type": "invoice"} in [i["action"] for i in exp["improve"]]
    # The seller reads text only; staff see where each sentence came from.
    assert all(set(b) == {"text"} for b in exp["because"])
    full = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()["decision"]["explanation"]
    refs = [b["ref"] for b in full["because"]]
    assert "control.phase1.concerns.RISK-04" in refs and any(r.endswith(".CMB") for r in refs)
    assert _texts(full) == because
    # The notification centre gets headline · first reason; the chat thread gets the whole explanation.
    notice = next(i for i in lc.ok(bu_client.get("/v4/me/notices", headers=as_seller))["items"]
                  if i["kind"] == "decision")
    assert notice["text"] == exp["headline"] + " · " + because[0]
    msgs = lc.ok(bu_client.get(f"/v4/applications/{app['id']}/messages", headers=as_seller))["items"]
    system = [m for m in msgs if m["from"] == "system" and "120" in m["text"]]
    assert system and all(t in system[-1]["text"] for t in because)


def test_explanation_hidden_for_aml(bu_client, as_seller, as_officer):
    app = lc.answer_all(bu_client, as_seller, lc.start(bu_client, as_seller, "company"))
    assert app["status"] == "escalated"
    exp = app["decision"]["explanation"]
    assert exp["because"] == [] and exp["hidden"] is True
    assert [i["text"] for i in exp["improve"]] == [f"Cán bộ tín dụng sẽ liên hệ {SELLER_ADDRESS}."]
    full = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    assert full["decision"]["explanation"]["because"] == []
    notice = next(i for i in lc.ok(bu_client.get("/v4/me/notices", headers=as_seller))["items"]
                  if i["kind"] == "decision")
    assert "chủ sở hữu" not in notice["text"] and "danh tính" not in notice["text"]


def test_why_question_is_answered_not_sent_to_an_officer(bu_client, as_seller, as_officer, as_admin):
    # Auto-approval paused for the group: the case goes to an officer with reasons the seller may read.
    r = bu_client.put(f"/v4/admin/auto-approval/{quote(GROUP)}", headers=as_admin,
                      json={"enabled": False, "note": "tạm dừng để thử"})
    assert r.status_code == 200, r.text
    app = _lan_price_120(bu_client, as_seller)
    assert app["status"] == "escalated", app["status"]
    exp = app["decision"]["explanation"]
    because = _texts(exp)
    assert because[0] == control._ESCALATE_REASONS["AUTO_APPROVAL_OFF"]["factor"]
    assert control.CHAL_SENTENCE in because and any("120" in t for t in because)
    url = f"/v4/applications/{app['id']}/messages"
    reply = lc.ok(bu_client.post(url, headers=as_seller,
                                 json={"text": "Vì sao hồ sơ của tôi bị chuyển cho cán bộ?"}))["items"][-1]
    assert reply["from"] == "agent2" and any(t in reply["text"] for t in because), reply["text"]
    full = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    assert full["human_request"] is None and full["status"] == "escalated"
    # Asking to meet someone is still a request for a person (never refused).
    bu_client.post(url, headers=as_seller, json={"text": "Tôi muốn gặp cán bộ"})
    assert bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()["human_request"]


def _no_partner_doc() -> dict:
    responses = [
        {"bank": "CMB", "name": "China Merchants Bank", "decision": "decline", "reason": "Điểm cửa hàng dưới 4,7"},
        {"bank": "ICBC", "name": "ICBC", "decision": "decline", "reason": "Cửa hàng hoạt động chưa đủ 36 tháng"},
        {"bank": "BOC", "name": "Bank of China", "decision": "timeout", "reason": "Không trả lời trong 30 giây"},
    ]
    return {"currency": "CNY", "stores": [{"registry": {"registered": "2023-05-18"}}],
            "internal": {"data": {"store": {"rating": 4.6}, "revenue": {"months_with_sales": 26}}},
            "control": {"results": {}, "phase1": {"concerns": []}, "phase2": {"resolved": []}},
            "syndicate": {"status": "no_partner", "rounds": [{"amount": 50_000, "responses": responses}]},
            "decision": {"kind": "reject", "by": "orchestrator", "reason": dict(control._ESCALATE_REASONS["NO_PARTNER"])}}


def test_no_partner_says_when_to_reapply(monkeypatch):
    monkeypatch.setattr(control, "today", lambda: date(2026, 10, 17))
    exp = control.explain_for_seller(_no_partner_doc(), use_model=False)
    because = _texts(exp)
    assert because[0] == control._ESCALATE_REASONS["NO_PARTNER"]["factor"]
    assert "China Merchants Bank chỉ nhận cửa hàng từ 4,7 điểm; cửa hàng bạn 4,6." in because
    assert because[-1].startswith("Bank of China không trả lời kịp")
    improve = [i["text"] for i in exp["improve"]]
    # 26 of 36 months with sales on 17/10/2026 → ten more months (the registration date alone has passed).
    assert "Nộp lại từ tháng 08/2027, khi cửa hàng đủ 36 tháng hoạt động." in improve
    assert not any("ngân hàng khác vẫn cấp" in t for t in improve)


class _Fake:
    def __init__(self, answer):
        self.answer = answer

    async def generate_text(self, system_prompt: str, user_input: str) -> str:
        texts = json.loads(user_input)
        return json.dumps(self.answer(texts), ensure_ascii=False)


def test_model_only_rewords_with_the_same_figures(monkeypatch):
    doc = _no_partner_doc()
    monkeypatch.setattr(control.llm_tools, "provider",
                        lambda agent3=False: _Fake(lambda ts: ["Xin lưu ý: " + t for t in ts]))
    exp = control.explain_for_seller(doc)
    assert exp["source"] == "llm" and all(b["text"].startswith("Xin lưu ý: ") for b in exp["because"])
    # A changed figure, a missing sentence or an internal threshold: the template stands.
    for bad in (lambda ts: [t.replace("4,7", "4,5") for t in ts], lambda ts: ts[:-1],
                lambda ts: [t + " Ngưỡng nội bộ." for t in ts]):
        monkeypatch.setattr(control.llm_tools, "provider", lambda agent3=False, bad=bad: _Fake(bad))
        assert control.explain_for_seller(doc)["source"] == "template"


# --- phase E (17/10/2026): what the leader saw on staging ---------------------------------------

def test_offer_explanation_rewritten_after_bank_round(bu_client, as_seller):
    """Lỗi 1: the banks lowered the limit and capped the tenor; Agent 2's paragraph is rewritten from the
    template with the new figures (no stale "kỳ hạn tối đa 12 tháng"), addressing the seller as "bạn"."""
    from sqlalchemy import select

    with session_scope() as s:
        partners = [b.code for b in s.scalars(select(BuBank)) if b.code != "WEBANK"]
    for code in partners:  # every partner lends at most 150.000 and 3 months: the 70 % round passes
        _policy(code, max_amount=150_000, max_tenor_m=3)
    app = lc.offered(bu_client, as_seller)
    assert app["status"] == "offered", app["status"]
    offer = lc.ok(bu_client.get(f"/v4/applications/{app['id']}", headers=as_seller))["offer"]
    adj = offer["bank_adjust"]
    assert offer["tenor_max"] == 3 and adj["tenor_from"] > 3 and adj["limit_from"] > offer["limit"]
    text = offer["explanation"]
    assert offer["explanation_source"] == "template"
    assert text.startswith(f"Hạn mức của bạn là {control._num(offer['limit'])} tệ") and "kỳ hạn tối đa 3 tháng" in text
    assert f"thay vì {adj['tenor_from']} tháng" in text and control._num(adj["limit_from"]) in text
    assert "chị" not in text.lower().split()


def test_explanation_text_one_reason_per_line():
    """Lỗi 3: the "vì sao" answer is a headline, then one "• " line per reason, then "Bạn có thể:"."""
    exp = {"headline": "Hồ sơ cần cán bộ tín dụng xem thêm", "because": [{"text": "Lý do một."}, {"text": "Lý do hai."}],
           "improve": [{"text": "Việc nên làm."}]}
    assert control.explanation_text(exp) == ("Hồ sơ cần cán bộ tín dụng xem thêm.\n\nLý do:\n• Lý do một.\n• Lý do hai."
                                             f"\n\n{SELLER_ADDRESS.capitalize()} có thể:\n• Việc nên làm.")


def test_demo_store_labels_have_no_staff_words():
    """Lỗi 5: the seller app strips "Agent n" / "FATE" from text, so the labels must not contain them."""
    import re

    labels = [s["label"] for s in sources.demo_stores()]
    assert "Lập luận tư vấn không trỏ tới bằng chứng" in labels
    assert "Ghi chú xác minh có lời nhắm vào kiểm soát" in labels
    assert not [x for x in labels if re.search(r"\bAgent\b|\bFATE\b", x)]


def test_me_reports_face_enrolled(bu_client, as_seller):
    """Lỗi 6: the payment box needs to know whether the account has a registered face."""
    me = lc.ok(bu_client.get("/v4/auth/me", headers=as_seller))
    assert me["user"]["face_enrolled"] is False
