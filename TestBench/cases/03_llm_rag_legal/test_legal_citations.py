"""Legal citation verification: fabricated, non-verbatim, and not-yet-effective citations.

A citation is trusted only when the article exists, the quote appears verbatim in it, and the
article is in force on the review date. Every case asserts that a bad citation is REJECTED and
never used to move a decision. A FAIL means forged/expired law text was accepted -> vulnerability.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.core import legal

from _llmbench import (FakeProvider, accept_full, judgment, officer, officer_trace, offered,
                       seller, set_provider)

REVIEW_DAY = date(2026, 10, 15)  # harness "today"


@pytest.mark.easy
def test_llm_e3_fabricated_and_nonverbatim_citations_are_rejected(bu_client):
    """LLM-E3: verify_citation rejects a made-up article id and a quote that is not verbatim.

    Both are the raw building block Agent 3 relies on. A fabricated article must not verify,
    and a real article quoted with text that is not present must not verify either.
    """
    # (a) article that does not exist in the vetted store.
    forged = legal.verify_citation("FAKE-2026#1", "bất kỳ câu nào", REVIEW_DAY)
    assert forged["verified"] is False and forged["effective"] is False

    # (b) a real, in-force article but with a quote that is not verbatim in it.
    real_id = "AML-2024#29"
    assert legal.ARTICLES[real_id]["eff"] <= REVIEW_DAY.isoformat()
    bad_quote = legal.verify_citation(real_id, "条文中根本不存在的文字", REVIEW_DAY)
    assert bad_quote["verified"] is False

    # control: the genuine verbatim quote of the same article does verify and is effective.
    good = legal.verify_citation(real_id, legal.ARTICLES[real_id]["text"], REVIEW_DAY)
    assert good["verified"] is True and good["effective"] is True


@pytest.mark.medium
def test_llm_m4_not_yet_effective_article_is_not_in_force(bu_client):
    """LLM-M4: a verbatim quote from a law that takes effect in the future is flagged not-effective.

    TM-2026#72 is a real article with correct text but an effective date of 2027-01-01. On a
    2026 review date the quote verifies verbatim yet must be reported as NOT effective, so it
    cannot be used to justify a decision today.
    """
    art = legal.ARTICLES["TM-2026#72"]
    assert art["eff"] == "2027-01-01"
    res = legal.verify_citation("TM-2026#72", art["text"], REVIEW_DAY)
    assert res["verified"] is True
    assert res["effective"] is False  # future law, not in force yet
    # The in-force sibling article (TM-2019#57) is effective for the same offence.
    in_force = legal.verify_citation("TM-2019#57", legal.ARTICLES["TM-2019#57"]["text"], REVIEW_DAY)
    assert in_force["verified"] is True and in_force["effective"] is True


@pytest.mark.medium
def test_llm_m5_agent3_forged_or_expired_citation_dropped_decision_unchanged(bu_client):
    """LLM-M5: Agent 3 concerns backed by a forged or not-yet-effective citation are dropped; the coded approve stands.

    An attacker-controlled Agent 3 returns a RISK-05 concern citing (a) a non-existent article and
    (b) a real-but-future article. Both citations fail verify_citation, the concern is dropped with
    a citation_rejected audit event, and chị Lan's clean case still disburses the code-computed
    139,900 — the injected law text moves neither the money nor the verdict.
    """
    h, off = seller(bu_client), officer(bu_client)

    # (a) forged article id.
    app = offered(bu_client, h)
    forged = {"rule": "RISK-05", "note": "Sự kiện không có thật",
              "citations": [{"article_id": "FAKE-2026#1", "quote": "không tồn tại"}]}
    set_provider(FakeProvider(agent3=[judgment(verdict="escalate", concerns=[forged])]))
    done = accept_full(bu_client, h, app["id"])
    assert done["status"] == "disbursed" and done["decision"]["amount"] == 139_900
    full = bu_client.get(f"/v4/applications/{app['id']}", headers=off).json()
    assert not any(c.get("source") == "llm" for c in full["control"]["phase1"]["concerns"])
    ev = officer_trace(bu_client, app["id"], off)
    assert any(e["kind"] == "citation_rejected" and e["payload"]["article_id"] == "FAKE-2026#1" for e in ev)

    # (b) a real article quoted verbatim but not yet in force (effective 2027-01-01).
    app2 = offered(bu_client, h)
    expired = {"rule": "RISK-05", "note": "Viện dẫn luật chưa hiệu lực",
               "citations": [{"article_id": "TM-2026#72", "quote": legal.ARTICLES["TM-2026#72"]["text"]}]}
    set_provider(FakeProvider(agent3=[judgment(verdict="escalate", concerns=[expired])]))
    done2 = accept_full(bu_client, h, app2["id"])
    assert done2["status"] == "disbursed" and done2["decision"]["amount"] == 139_900
    full2 = bu_client.get(f"/v4/applications/{app2['id']}", headers=off).json()
    assert not any(c.get("source") == "llm" for c in full2["control"]["phase1"]["concerns"])
    ev2 = officer_trace(bu_client, app2["id"], off)
    assert any(e["kind"] == "citation_rejected" and e["payload"]["article_id"] == "TM-2026#72" for e in ev2)


@pytest.mark.hard
def test_llm_h3_rule_loader_disables_any_rule_with_an_unverifiable_citation(bu_client):
    """LLM-H3: load_rules fails closed — a rule whose citation is not verbatim in the store is disabled.

    The rule set only trusts citations it can re-verify against the vetted article store. A rule
    pointing at a non-existent article, or quoting an existing article with text that is not
    present, must be moved to the disabled list, never enabled. Every production rule already
    satisfies this invariant.
    """
    Rule = legal.Rule
    bad_missing = Rule("TEST-MISS", "cites a non-existent article", "code", "reject", True,
                       (("NOPE-9999#1", "điều luật không có thật"),))
    bad_quote = Rule("TEST-QUOTE", "quotes a real article with wrong text", "code", "reject", True,
                     (("AML-2024#29", "条文里没有这句话"),))
    good = Rule("TEST-GOOD", "quotes a real article verbatim", "code", "reject", True,
                (("AML-2024#29", legal.ARTICLES["AML-2024#29"]["text"]),))

    enabled, disabled = legal.load_rules((bad_missing, bad_quote, good))
    disabled_codes = {d["code"] for d in disabled}
    enabled_codes = {r.code for r in enabled}
    assert {"TEST-MISS", "TEST-QUOTE"} <= disabled_codes
    assert "TEST-MISS" not in enabled_codes and "TEST-QUOTE" not in enabled_codes
    assert "TEST-GOOD" in enabled_codes

    # Production invariant: no enabled rule carries a citation that cannot be verified verbatim.
    for rule in legal.ENABLED_RULES:
        for article_id, quote in rule.cite:
            assert article_id in legal.ARTICLES, f"{rule.code} cites missing {article_id}"
            assert quote in legal.ARTICLES[article_id]["text"], f"{rule.code} non-verbatim quote"
