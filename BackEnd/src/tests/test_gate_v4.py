"""T3: auto-approval kill switch by group NPL, event concentration (EVENT-01), auto-escalation.

Loan circle: the gate runs right after verification (no seller acceptance), so these checks show on
the application returned by ``verify``.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from urllib.parse import quote

from app.data_sources import sources
from app.platform.tables import BuLoan
from app.platform.db.session import session_scope
from app.platform.db.tables import utcnow
from tests import lc

GROUP = "thời trang|t2"


def seed_loans(n: int, *, event: str, bad: bool) -> None:
    """``n`` fashion Tier-2 loans of other borrowers (chị Lan may hold one loan at a time, POL-07);
    ``bad`` ones are 120 days overdue. Under the 50 % event stress each misses
    200.000 − 0,5 × 0,5 × 280.000 = 130.000 of its 200.000 due (ratio 0,65)."""
    today = utcnow().date()
    with session_scope() as s:
        for _ in range(n):
            s.add(BuLoan(
                id="loan_" + secrets.token_hex(6), application_id="app_seed_" + secrets.token_hex(4),
                seller_user_id="usr_seed_" + secrets.token_hex(4), status="overdue" if bad else "active",
                currency="CNY", repaid=0, outstanding=200_000,
                doc={"amount": 190_000, "total_due": 200_000, "rate": 0.10, "tenor_m": 6, "method": "installment",
                     "event": event, "category": "thời trang", "tier": 2, "auto_group": GROUP, "grade": "B",
                     "prudent": 46_666, "forecast": 280_000, "sweep_usable": 0.5,
                     "overdue_days": 120 if bad else 0, "principal_outstanding": 190_000,
                     "final_due_date": (today + timedelta(days=150)).isoformat()},
            ))


def test_npl_switches_auto_approval_off(bu_client, as_seller, as_officer, as_admin):
    seed_loans(10, event="12.12", bad=True)
    app = lc.start(bu_client, as_seller)
    assert app["status"] == "escalated" and app["loan_id"] is None and app["syndicate"] is None
    assert app["decision"]["reason"]["law"] and "nợ xấu" not in app["decision"]["reason"]["factor"]
    full = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    assert full["escalation"]["why"] == "AUTO_APPROVAL_OFF"
    gate = full["control"]["gate"]
    assert gate["conditions"][4]["ok"] is False and gate["auto_group"] == GROUP and gate["auto_enabled"] is False
    assert all(c["ok"] for c in gate["conditions"][:4])
    queue = bu_client.get("/v4/officer/queue", headers=as_officer).json()["items"]
    assert any(i["id"] == app["id"] and i["why"] == "AUTO_APPROVAL_OFF" for i in queue)
    switches = bu_client.get("/v4/portfolio", headers=as_officer).json()["auto_approval"]
    row = next(s for s in switches if s["group"] == GROUP)
    assert row["enabled"] is False and row["npl_ratio"] == 1.0 and row["loans"] == 10 and not row["manual"]

    url = f"/v4/admin/auto-approval/{quote(GROUP)}"
    assert bu_client.put(url, headers=as_officer, json={"enabled": True}).status_code == 403
    r = bu_client.put(url, headers=as_admin, json={"enabled": True, "note": "Hội đồng rủi ro cho mở lại"})
    assert r.status_code == 200 and r.json()["enabled"] is True and r.json()["manual"] is True
    assert lc.offered(bu_client, as_seller)["syndicate"]["status"] == "approved"
    back = bu_client.put(url, headers=as_admin, json={"mode": "auto"}).json()
    assert back["manual"] is False and back["enabled"] is False
    assert bu_client.put("/v4/admin/auto-approval/no-tier", headers=as_admin, json={}).status_code == 400


def test_small_group_keeps_auto_approval(bu_client, as_seller):
    seed_loans(9, event="12.12", bad=True)  # below gate.npl_min_loans
    assert lc.start(bu_client, as_seller)["status"] == "offered"


def test_event_concentration_escalates(bu_client, as_seller, as_officer):
    seed_loans(4, event="11.11", bad=False)  # under stress.event_min_loans: no concentration yet
    assert lc.start(bu_client, as_seller)["status"] == "offered"
    # Now 5 open 11.11 loans, stress shortfall ratio 0.65 > 0.25.
    seed_loans(1, event="11.11", bad=False)
    app = lc.start(bu_client, as_seller)
    assert app["status"] == "escalated" and app["syndicate"] is None
    full = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    assert full["escalation"]["why"] == "EVENT_CONCENTRATION"
    rule = next(r for r in full["control"]["phase0"]["results"] if r["code"] == "EVENT-01")
    assert rule["ok"] is False and rule["value"] == 0.65 and full["control"]["phase0"]["event"]["loans"] == 5
    assert app["decision"]["reason"]["fix"] and "0,25" not in str(app["decision"]["reason"])


def test_open_question_auto_escalates_after_three_days(bu_client, as_seller, as_officer):
    plan = {**sources.suggested_plan(sources.SCENARIOS["lan"][3]), "inventory": 200_000}
    app = lc.start(bu_client, as_seller, plan=plan)
    assert app["status"] == "needs_answer"
    today = utcnow().date()
    r = bu_client.post("/v4/monitoring/tick", headers=as_officer, json={"as_of": (today + timedelta(days=2)).isoformat()})
    assert r.json()["escalated"] == []
    r = bu_client.post("/v4/monitoring/tick", headers=as_officer, json={"as_of": (today + timedelta(days=4)).isoformat()})
    assert r.json()["escalated"] == [app["id"]]
    full = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    assert full["status"] == "escalated" and full["verification"]["state"] == "ESCALATED"
    assert full["escalation"]["why"] == "RISK_INVENTORY_HIGH" and full["escalation"]["auto"] is True
