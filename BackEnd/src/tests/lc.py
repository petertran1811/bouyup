"""Loan-circle helpers shared by the tests: the borrower's way from store link to a running loan.

    start()      create → identity → consent (3 boxes) → plan → verify (Agent 1 → Agents 2–3 → banks)
    answer_all() answer each open verification question with its first choice
    offered()    a case whose limit the banks approved (status "offered")
    select()     Stage 3 choice; contract() opens the disclosure; sign() waits out the reading time
    loan_for()   offered → selected → signed → disbursed, returns the loan view
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.data_sources import consent, sources
from app.platform.db.session import session_scope
from app.platform.tables import BuApplication, save_json

BOXES = list(consent.CONSENT_BOXES)
SIGN = {"read_ack": True, "webank_account": "6222000012345", "use_of_funds_commitment": True,
        "supplier_account": "88880001", "guarantee": True, "method": "face"}


def ok(r: Any) -> dict[str, Any]:
    assert r.status_code < 300, (r.status_code, r.text[:2000])
    return r.json()


def start(client, h, scenario: str = "lan", tier: int = 2, borrower_type: str | None = None,
          statements: list[dict[str, Any]] | None = None, plan: dict[str, Any] | None = None) -> dict:
    bt = borrower_type or ("company" if scenario == "company" else "individual_business")
    app = ok(client.post("/v4/applications", headers=h,
                         json={"tier": tier, "borrower_type": bt, "store_urls": [sources.demo_url(scenario)]}))
    if app["status"] == "rejected":
        return app
    app = ok(client.post(f"/v4/applications/{app['id']}/identity", headers=h, json={"cccd": True, "face": True}))
    if app["status"] == "rejected":
        return app
    app = ok(client.post(f"/v4/applications/{app['id']}/consent", headers=h, json={"scopes": BOXES}))
    if tier == 2:
        body = dict(plan or app["plan"]["suggested"])
        if statements:
            body["statements"] = statements
        app = ok(client.put(f"/v4/applications/{app['id']}/plan", headers=h, json=body))
    return ok(client.post(f"/v4/applications/{app['id']}/verify", headers=h, json={}))


def answer_all(client, h, app: dict) -> dict:
    while app["status"] == "needs_answer":
        q = app["verification"]["questions"][0]
        app = ok(client.post(f"/v4/applications/{app['id']}/answers", headers=h,
                             json={"flag": q["flag"], "choice": q["choices"][0]["key"]}))
    return app


def offered(client, h, scenario: str = "lan", **kw: Any) -> dict:
    app = answer_all(client, h, start(client, h, scenario, **kw))
    assert app["status"] == "offered", (app["status"], app.get("decision"))
    return app


def select(client, h, app: dict, amount: int | None = None, tenor_m: int | None = None,
           method: str = "installment", due_day: int = 10) -> dict:
    offer = app["offer"]
    return ok(client.post(f"/v4/applications/{app['id']}/select", headers=h, json={
        "amount": amount or offer["suggested"] or offer["limit"], "tenor_m": tenor_m or offer["tenor_max"],
        "method": method, "due_day": due_day}))


def contract(client, h, app: dict) -> dict:
    return ok(client.get(f"/v4/applications/{app['id']}/contract", headers=h))


def rewind_contract(app_id: str, seconds: int = 30) -> None:
    """The reading clock of the disclosure, moved back (instead of sleeping in tests)."""
    with session_scope() as s:
        row = s.get(BuApplication, app_id)
        doc = dict(row.doc)
        ct = dict(doc["contract"])
        ct["issued_at"] = (datetime.fromisoformat(ct["issued_at"].rstrip("Z")) - timedelta(seconds=seconds)).isoformat() + "Z"
        doc["contract"] = ct
        save_json(row, "doc", doc)


def sign(client, h, app: dict, **changes: Any) -> Any:
    rewind_contract(app["id"])
    return client.post(f"/v4/applications/{app['id']}/sign", headers=h, json={**SIGN, **changes})


def loan_for(client, h, scenario: str = "lan", **choice: Any) -> dict:
    app = offered(client, h, scenario)
    app = select(client, h, app, **choice)
    contract(client, h, app)
    app = ok(sign(client, h, app))
    assert app["status"] == "disbursed" and app["loan_id"], app["status"]
    return ok(client.get(f"/v4/loans/{app['loan_id']}", headers=h))


def advance(client, h, loan: dict, to: str) -> dict:
    return ok(client.post(f"/v4/loans/{loan['id']}/simulate-advance", headers=h, json={"to": to}))
