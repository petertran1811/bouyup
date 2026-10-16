"""Shared helpers for the Ledger & disbursement adversarial cases.

Not a ``test_*`` module, so pytest does not collect it. It replicates the HTTP
"get to an offer" flow (so these cases do not import the backend's own pytest
conftest, which would re-point the test database) and offers a small builder for
hand-made per-case hash chains.
"""
from __future__ import annotations

from typing import Any

from app.blockchain import chain
from app.data_sources import sources
from app.platform.db.session import session_scope

ACCOUNTS = [{"bank": "WeBank", "tail": "8826"}]
SCOPES = ["inflows", "tax", "credit", "fate", "sweep"]


def start(client: Any, h: dict[str, str], scenario: str = "lan", tier: int = 2) -> dict[str, Any]:
    """Create -> identity -> consent -> plan -> verify. Returns the application view."""
    r = client.post("/v4/applications", headers=h, json={"tier": tier, "store_urls": [sources.demo_url(scenario)]})
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]
    r = client.post(f"/v4/applications/{app_id}/identity", headers=h, json={"cccd": True, "face": True})
    assert r.status_code == 200, r.text
    if r.json()["status"] == "rejected":
        return r.json()
    r = client.post(f"/v4/applications/{app_id}/consent", headers=h, json={"scopes": SCOPES, "accounts": ACCOUNTS})
    assert r.status_code == 200, r.text
    if tier == 2:
        plan = dict(r.json()["plan"]["suggested"])
        r = client.put(f"/v4/applications/{app_id}/plan", headers=h, json=plan)
        assert r.status_code == 200, r.text
    r = client.post(f"/v4/applications/{app_id}/verify", headers=h, json={})
    assert r.status_code == 200, r.text
    return r.json()


def answer_all(client: Any, h: dict[str, str], app: dict[str, Any]) -> dict[str, Any]:
    """Answer every open verification question the way chi Lan does."""
    while app.get("status") == "needs_answer":
        q = app["verification"]["questions"][0]
        body: dict[str, Any] = {"flag": q["flag"], "choice": q["choices"][0]["key"]}
        if q["flag"] == "RISK_INFLOW_GAP":
            body.update(choice="other_bank", account={"bank": "CMB", "tail": "1203"})
        r = client.post(f"/v4/applications/{app['id']}/answers", headers=h, json=body)
        assert r.status_code == 200, r.text
        app = r.json()
    return app


def offered(client: Any, h: dict[str, str], scenario: str = "lan") -> dict[str, Any]:
    """Drive the pipeline to an accepted-ready offer and return the application view."""
    app = answer_all(client, h, start(client, h, scenario))
    assert app["status"] == "offered", app.get("status")
    return app


def seed_case(case_id: str, entries: list[tuple[str, dict[str, Any]]]) -> None:
    """Commit a hand-made per-case hash chain: ``entries`` = [(kind, payload), ...]."""
    with session_scope() as session:
        for kind, payload in entries:
            chain.record(session, case_id, kind, payload)
