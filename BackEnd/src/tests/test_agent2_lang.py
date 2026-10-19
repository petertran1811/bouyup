"""Agent 2 answers in the language the seller picked in the UI (X-BU-Lang: en / zh), 19/10/2026."""

from __future__ import annotations

from app.agents import agent2_advise as advise
from app.agents.agent2_advise import AGENT2_SYSTEM
from app.platform import i18n
from app.platform.llm.gemini import set_provider
from tests.lc import offered
from tests.test_llm_agents import FakeProvider, final


def _say(client, h, app_id, text, lang):
    r = client.post(f"/v4/applications/{app_id}/messages", headers={**h, "X-BU-Lang": lang}, json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()["items"][1]["text"]


def _hl(h, lang):
    return {**h, "X-BU-Lang": lang}


def test_english_thousands_are_read_as_whole_numbers():
    assert advise._norm("100,000") == 100000
    assert advise._norm("1,234.5") == 1234.5
    assert advise._norm("100.000") == 100000  # Vietnamese thousands still work
    assert advise._norm("8,5") == 8.5  # Vietnamese decimal comma still works


def test_templates_follow_the_language(bu_client, as_seller):
    app = offered(bu_client, as_seller)
    en = _say(bu_client, as_seller, app["id"], "What is the interest rate and the total to repay?", "en")
    assert "annual rate" in en and "CNY" in en and "tệ" not in en
    zh = _say(bu_client, as_seller, app["id"], "利率是多少？", "zh")
    assert "年利率" in zh and "元" in zh
    vi = _say(bu_client, as_seller, app["id"], "Lãi bao nhiêu?", "vi")
    assert "Lãi năm" in vi


def test_human_request_in_english_and_chinese_is_never_refused(bu_client, as_seller, as_officer):
    app = offered(bu_client, as_seller)
    text = _say(bu_client, as_seller, app["id"], "I want to talk to a human officer please", "en")
    assert "credit officer" in text
    assert bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()["status"] == "escalated"
    app2 = offered(bu_client, as_seller)
    assert "信贷员" in _say(bu_client, as_seller, app2["id"], "我要人工", "zh")


def test_why_question_in_english_is_not_a_human_request(bu_client, as_seller, as_officer):
    app = offered(bu_client, as_seller)
    text = _say(bu_client, as_seller, app["id"], "Why is my limit this number?", "en")
    assert "Your limit is" in text
    assert bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()["status"] == "offered"


def test_offer_explanation_is_rendered_per_language_and_stored_in_vietnamese(bu_client, as_seller, as_officer):
    app = offered(bu_client, as_seller)
    en = bu_client.get(f"/v4/applications/{app['id']}", headers=_hl(as_seller, "en")).json()["offer"]["explanation"]
    zh = bu_client.get(f"/v4/applications/{app['id']}/offer", headers=_hl(as_seller, "zh")).json()["explanation"]
    stored = bu_client.get(f"/v4/applications/{app['id']}", headers=_hl(as_officer, "en")).json()["offer"]["explanation"]
    assert en.startswith("Your limit is") and zh.startswith("您的额度为")
    assert "Hạn mức" in stored or "hạn mức" in stored


class _Capture(FakeProvider):
    def __init__(self, reply: str) -> None:
        super().__init__()
        self.reply, self.prompts = reply, []

    async def next_step(self, *, system_prompt, history, tools):  # noqa: ANN001
        self.prompts.append(system_prompt)
        if system_prompt.startswith(AGENT2_SYSTEM):
            return final(self.reply)
        return await super().next_step(system_prompt=system_prompt, history=history, tools=tools)


def test_model_is_told_the_language_and_english_figures_pass_the_filter(bu_client, as_seller):
    app = offered(bu_client, as_seller)
    limit = bu_client.get(f"/v4/applications/{app['id']}", headers=as_seller).json()["offer"]["limit"]
    prov = _Capture(f"Your approved limit is {limit:,} CNY.")
    set_provider(prov)
    try:
        text = _say(bu_client, as_seller, app["id"], "How much can I borrow?", "en")
    finally:
        set_provider(None)
    assert any(p.endswith(i18n.MODEL_LANGUAGE["en"]) for p in prov.prompts)
    assert text == f"Your approved limit is {limit:,} CNY."


def test_a_draft_in_the_wrong_language_is_rewritten(bu_client, as_seller):
    app = offered(bu_client, as_seller)

    class Twice(FakeProvider):
        def __init__(self):
            super().__init__()
            self.replies = ["Hạn mức của bạn đã được tính theo hóa đơn và kế hoạch nhập hàng.", "您的额度根据发票和进货计划计算。"]

        async def next_step(self, *, system_prompt, history, tools):  # noqa: ANN001
            if system_prompt.startswith(AGENT2_SYSTEM):
                return final(self.replies.pop(0))
            return await super().next_step(system_prompt=system_prompt, history=history, tools=tools)

    set_provider(Twice())
    try:
        text = _say(bu_client, as_seller, app["id"], "额度是怎么计算的？", "zh")
    finally:
        set_provider(None)
    assert text == "您的额度根据发票和进货计划计算。"
    with i18n.forced("en"):
        assert advise.wrong_language("Hạn mức của bạn đã được tính theo hóa đơn.")
        assert not advise.wrong_language("Your limit is 100,000 CNY from Nhã Cầm Gia Dụng.")


def test_english_and_chinese_use_comma_thousands(bu_client, as_seller):
    app = offered(bu_client, as_seller)
    en = bu_client.get(f"/v4/applications/{app['id']}", headers=_hl(as_seller, "en")).json()["offer"]["explanation"]
    assert "," in en.split("CNY")[0] and "." not in en.split("CNY")[0].replace("Your limit is", "")
