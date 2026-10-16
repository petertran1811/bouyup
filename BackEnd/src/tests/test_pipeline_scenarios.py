"""The demo scenarios (core_tech #demo, loan circle): each changes one factor of chị Lan's case."""

from __future__ import annotations

import pytest

from tests.lc import answer_all, start


def _run(client, h, scenario: str) -> dict:
    """Verification → Agents 2–3 → gate → partner banks run on their own; no seller acceptance step."""
    return answer_all(client, h, start(client, h, scenario))


def test_lan_approves(bu_client, as_seller):
    app = _run(bu_client, as_seller, "lan")
    assert app["status"] == "offered"
    assert app["decision"]["kind"] == "approve" and app["decision"]["amount"] == 200_000
    assert app["decision"]["by"] == "gate" and app["offer"]["limit"] == 200_000


def test_noevid_smaller_limit_sent_to_banks(bu_client, as_seller, as_officer):
    app = _run(bu_client, as_seller, "noevid")
    # Agent 3 "smaller" becomes the limit the banks are asked for (approve_smaller, no acceptance step).
    assert app["status"] == "offered" and app["decision"]["option_id"] == "step70"
    assert app["decision"]["amount"] == app["offer"]["limit"] == 140_000 and app["decision"]["reason"]["fix"]
    full = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    assert full["control"]["phase2"]["asked_agent2"] is True
    assert full["control"]["phase2"]["verdict"] == "smaller"
    assert full["control"]["gate"]["decision"] == "approve_smaller"
    assert app["syndicate"]["status"] == "approved" and app["syndicate"]["limit"] == 140_000
    for path in ("accept", "accept-smaller"):  # the old seller acceptance endpoints are gone
        assert bu_client.post(f"/v4/applications/{app['id']}/{path}", headers=as_seller, json={}).status_code == 404


def test_noevid_manual_channel(bu_client, as_seller, as_officer):
    app = _run(bu_client, as_seller, "noevid")
    app = bu_client.post(f"/v4/applications/{app['id']}/manual-channel", headers=as_seller, json={}).json()
    assert app["status"] == "escalated"
    full = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    assert full["escalation"]["why"] == "MANUAL_CHANNEL"


@pytest.mark.parametrize("scenario,status,kind,why", [
    ("notes", "escalated", "escalate", "RISK-06"),
    ("ecig", "rejected", "reject", None),
    ("tea", "escalated", "escalate", "LAW-LIC-01"),
    ("shoes", "escalated", "escalate", "LAW-IP-01"),
    ("company", "escalated", "escalate", "AML-CDD-01"),
])
def test_control_outcomes(bu_client, as_seller, as_officer, scenario, status, kind, why):
    app = _run(bu_client, as_seller, scenario)
    assert app["status"] == status and app["decision"]["kind"] == kind
    assert app["syndicate"] is None  # the banks are never asked
    full = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    if why:
        assert full["escalation"]["why"] == why
        queue = bu_client.get("/v4/officer/queue", headers=as_officer).json()["items"]
        assert any(i["id"] == app["id"] and i["why"] == why for i in queue)
    reason = app["decision"]["reason"]
    if scenario == "notes":
        assert reason is None
    else:
        assert reason["law"] and reason["factor"] and reason["fix"]
    if scenario == "ecig":
        assert "Điều 23" in reason["law"] and "Điều 26" in reason["law"]
        failed = {r["code"] for r in full["control"]["phase0"]["results"] if r["ok"] is False}
        assert {"LAW-GOODS-01", "LAW-GOODS-02"} <= failed
    if scenario == "shoes":
        concern = next(c for c in full["control"]["phase1"]["concerns"] if c["rule"] == "LAW-IP-01")
        cits = concern["citations"]
        tm = next(c for c in cits if c["article_id"] == "TM-2026#72")
        assert tm["verified"] and not tm["effective"]
    if scenario == "company":
        assert app["offer"]["tenors"] == [3, 6, 12, 24, 36]
    # AML-STR-01 is always ok before the loan (no pass-through data any more).
    str01 = next(r for r in full["control"]["phase0"]["results"] if r["code"] == "AML-STR-01")
    assert str01["ok"] is True


def test_electronics_single_partner(bu_client, as_seller):
    app = _run(bu_client, as_seller, "electronics")
    assert app["status"] == "offered"
    assert [(s["bank"], s["pct"]) for s in app["syndicate"]["split"]] == [("WEBANK", 0.3), ("ICBC", 0.7)]


def test_nobank_rejected_by_orchestrator(bu_client, as_seller):
    app = _run(bu_client, as_seller, "nobank")
    assert app["status"] == "rejected" and app["decision"]["by"] == "orchestrator"
    assert app["decision"]["reason"]["fix"] and app["offer"] is not None


def test_young_out_of_scope(bu_client, as_seller):
    app = start(bu_client, as_seller, "young")
    assert app["status"] == "out_of_scope" and app["verification"]["state"] == "OUT_OF_SCOPE"
    assert app["verification"]["eligible_from"] == "2027-02-01"
    assert "01/02/2027" in app["verification"]["reason"]["fix"]


def test_other_rejected_id_mismatch(bu_client, as_seller):
    app = start(bu_client, as_seller, "other")
    assert app["status"] == "rejected" and app["verification"]["state"] == "REJECTED"
    assert "LAW_ID_MISMATCH" in {f["code"] for f in app["verification"]["flags"]}
    assert "chính chị" in app["verification"]["reason"]["fix"]
