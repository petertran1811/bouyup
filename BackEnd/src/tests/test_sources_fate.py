"""T7: data-source seams, FATE adapter, several stores on one application."""

from __future__ import annotations

import httpx
import pytest

from app.data_sources import sources
from tests.lc import answer_all, start


class BrokenFate:
    def score(self, consent, seller_ref):
        raise sources.SourceUnavailable("FATE timeout")


@pytest.fixture()
def broken_fate():
    sources.set_fate_source(BrokenFate())
    yield
    sources.set_fate_source(None)


def test_fate_failure_flags_partner_missing_no_auto_approve(bu_client, as_seller, as_officer, broken_fate):
    app = answer_all(bu_client, as_seller, start(bu_client, as_seller))
    flag = next(f for f in app["verification"]["flags"] if f["code"] == "DATA_PARTNER_MISSING")
    assert flag["status"] == "explained_unverified"
    step6 = app["verification"]["steps"][5]
    assert step6["status"] == "warn" and "FATE chưa trả điểm" in step6["summary"]
    # Never auto-approved: the gate sends the case to an officer (RISK-02), no bank is asked, no loan.
    assert app["status"] == "escalated" and app["loan_id"] is None
    full = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    assert next(r for r in full["control"]["phase0"]["results"] if r["code"] == "RISK-02")["ok"] is False
    assert full["offer"]["score"] == 69  # FATE scored as the worst band (0 points instead of 11)
    assert full["offer"]["grade"] == "C" and full["offer"]["rate"] == 0.12
    assert full["escalation"]["why"] == "RISK-02" and full["decision"]["kind"] == "escalate"
    assert not full.get("syndicate")


def test_http_fate_source():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        if "bad" in body:
            return httpx.Response(200, json={"value": 9, "run_id": "r"})
        if "down" in body:
            return httpx.Response(503)
        if "thin" in body:
            return httpx.Response(200, json={"value": 3, "run_id": "fate-run-2", "coverage": {"banks": 1, "months": 4}})
        if "oddcov" in body:
            return httpx.Response(200, json={"value": 3, "run_id": "fate-run-3", "coverage": {"banks": 7}})
        return httpx.Response(200, json={"value": 2, "run_id": "fate-run-1"})

    fate = sources.HttpFateSource("http://fate.test", transport=httpx.MockTransport(handler))
    # An older service without coverage keeps working: coverage is unknown (None).
    assert fate.score({"id": "CS-1"}, "ref_ok") == {"value": 2, "source": "fate", "run_id": "fate-run-1",
                                                    "coverage": None}
    assert fate.score({"id": "CS-1"}, "ref_thin")["coverage"] == {"banks": 1, "months": 4}
    assert fate.score({"id": "CS-1"}, "ref_oddcov")["coverage"] is None  # out of range: treated as unknown
    for ref in ("ref_bad", "ref_down"):
        with pytest.raises(sources.SourceUnavailable):
            fate.score({"id": "CS-1"}, ref)


def test_scenario_sources_match_module_functions():
    data = sources.SCENARIOS["lan"][3]
    src = sources.ScenarioSources(data)
    assert src.get_credit_report() == sources.get_credit_report(data)
    assert src.pull_tax_data() == sources.pull_tax_data(data)
    assert src.score({}, "x") == sources.get_interbank_score(data)
    assert src.pull_tax_data("purchase_invoices", supplier="SUP-0091", amount=100)["invoiced"] == 100
    assert src.pull_tax_data("purchase_invoices", supplier="SUP-0137", amount=100)["invoiced"] == 0


def test_application_can_carry_a_second_store(bu_client, as_seller):
    """Stores on other platforms are read at step 1 (no bank inflows to reconcile any more)."""
    r = bu_client.post("/v4/applications", headers=as_seller, json={
        "tier": 2, "borrower_type": "individual_business",
        "store_urls": [sources.demo_url("lan"), "https://shop123.taobao.com/?id=1"]})
    assert r.status_code == 201
    app = r.json()
    assert [s["platform"] for s in app["stores"]] == ["douyin", "taobao"]
    assert [t["tool"] for t in app["verification"]["tool_calls"]].count("lookup_public_store") == 2


def test_tax_source_down_stops_and_escalates(bu_client, as_seller, monkeypatch):
    """Principle 5: a data partner that does not answer stops the case; nothing is guessed."""
    def down(self, *a, **kw):
        raise sources.SourceUnavailable("银税互动 timeout")

    monkeypatch.setattr(sources.ScenarioSources, "pull_tax_data", down)
    app = start(bu_client, as_seller)
    assert app["status"] == "escalated" and app["offer"] is None and app["loan_id"] is None
    flag = next(f for f in app["verification"]["flags"] if f["code"] == "DATA_SOURCE_GAP")
    assert flag["status"] == "open" and flag["sources"] == ["tax"]
    assert app["verification"]["steps"][5]["status"] == "fail"


def test_missing_purchase_invoices_never_auto_approve(bu_client, as_seller, monkeypatch):
    monkeypatch.setitem(sources._LAN["tax"], "invoice_unit_price_3m", None)
    app = answer_all(bu_client, as_seller, start(bu_client, as_seller))
    flag = next(f for f in app["verification"]["flags"] if f["code"] == "DATA_SOURCE_GAP")
    assert flag["status"] == "explained_unverified"
    # B3 falls back to the declared price less the haircut; the gate escalates instead of approving.
    assert app["status"] == "escalated" and app["loan_id"] is None and app["offer"]["limit"] == 200_000


def test_record_carries_credit_and_interbank_blocks(bu_client, as_seller, broken_fate):
    from app.platform.db.session import session_scope
    from app.platform.tables import BuApplication

    app = answer_all(bu_client, as_seller, start(bu_client, as_seller))
    with session_scope() as s:
        internal = s.get(BuApplication, app["id"]).doc["internal"]
    assert internal["record_sources"]["credit"] == {"late_12m": 0, "active_npl": False, "network_history": "none"}
    assert internal["record_sources"]["interbank_score"]["source"] == "fallback"  # FATE did not answer


def test_open_flag_clock_starts_when_the_flag_opens(bu_client, as_seller, as_officer):
    from datetime import date, timedelta

    from app.platform.db.session import session_scope
    from app.platform.tables import BuApplication

    plan = {**sources.SCENARIOS["lan"][3]["plan"], "inventory": 60_000}  # above 1,5 × the invoice estimate
    app = start(bu_client, as_seller, plan=plan)
    assert app["status"] == "needs_answer" and app["verification"]["questions"][0]["flag"] == "RISK_INVENTORY_HIGH"
    opened = date.fromisoformat(next(f for f in app["verification"]["flags"]
                                     if f["status"] == "open")["opened_at"][:10])
    # A chat message touches updated_at; it must not reset the clock.
    bu_client.post(f"/v4/applications/{app['id']}/messages", headers=as_seller, json={"text": "xin chào"})
    tick = lambda d: bu_client.post("/v4/monitoring/tick", headers=as_officer,  # noqa: E731
                                    json={"as_of": d.isoformat()}).json()
    assert app["id"] not in tick(opened + timedelta(days=3))["escalated"]
    assert app["id"] in tick(opened + timedelta(days=4))["escalated"]
    with session_scope() as s:
        assert s.get(BuApplication, app["id"]).status == "escalated"


def test_revoked_entity_is_rejected_at_step_2(bu_client, as_seller, monkeypatch):
    monkeypatch.setitem(sources._LAN["registry"], "status", "revoked")
    app = bu_client.post("/v4/applications", headers=as_seller,
                         json={"tier": 2, "store_urls": [sources.demo_url("lan")]}).json()
    assert app["status"] == "rejected"
    assert any(f["code"] == "POL_ENTITY_INACTIVE" for f in app["verification"]["flags"])


def test_verify_without_any_consent_reads_nothing(bu_client, as_seller):
    app = bu_client.post("/v4/applications", headers=as_seller,
                         json={"tier": 1, "store_urls": [sources.demo_url("lan")]}).json()
    bu_client.post(f"/v4/applications/{app['id']}/identity", headers=as_seller, json={"cccd": True, "face": True})
    r = bu_client.post(f"/v4/applications/{app['id']}/verify", headers=as_seller, json={})
    assert r.status_code == 400
    app = bu_client.get(f"/v4/applications/{app['id']}", headers=as_seller).json()
    assert not any(t["tool"] in ("pull_revenue", "pull_tax_data", "get_credit_report", "get_interbank_score")
                   for t in app["verification"]["tool_calls"])
