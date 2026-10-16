"""Shared helpers for category 03 (LLM agents, RAG & legal citations).

Not a test module (leading underscore): it carries the application-flow helpers and a
scripted fake LLM provider so each themed file can inject attacker-controlled model
output. The harness disables the LLM (LLM_ENABLED=false); installing a fake provider is
the only way to exercise the model path and prove the *code* guards still win.

SCORING: a test PASSES when the coded decision/limit/citation check RESISTS the injected
text. A FAIL means the injection moved the outcome -> a real vulnerability.
"""
from __future__ import annotations

import json
from typing import Any

from conftest import DEMO, login  # root Testbench harness

from app.agents.agent2_advise import AGENT2_SYSTEM
from app.agents.agent5_llm import AGENT5_SYSTEM
from app.agents.llm_tools import AGENT3_SYSTEM
from app.data_sources import sources
from app.platform.llm.base import LLMUnavailable
from app.platform.llm.gemini import set_provider  # noqa: F401 (re-exported for tests)
from app.platform.llm.messages import AgentStep

SCOPES = ["inflows", "tax", "credit", "fate", "sweep"]
ACCOUNTS = [{"bank": "WeBank", "tail": "8826"}]


# --- role headers ------------------------------------------------------------------

def seller(client) -> dict[str, str]:
    return login(client, DEMO["seller"])


def officer(client) -> dict[str, str]:
    return login(client, DEMO["officer"])


def admin(client) -> dict[str, str]:
    return login(client, DEMO["admin"])


# --- application flow (mirrors the backend's own pipeline helpers) -----------------

def start(client, h: dict[str, str], scenario: str = "lan", tier: int = 2) -> dict:
    """create -> identity -> consent -> plan (suggested) -> verify. Returns the application."""
    r = client.post("/v4/applications", headers=h,
                    json={"tier": tier, "store_urls": [sources.demo_url(scenario)]})
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


def answer_all(client, h: dict[str, str], app: dict) -> dict:
    """Answer each open verification question the way chị Lan does."""
    while app["status"] == "needs_answer":
        q = app["verification"]["questions"][0]
        body = {"flag": q["flag"], "choice": q["choices"][0]["key"]}
        if q["flag"] == "RISK_INFLOW_GAP":
            body.update(choice="other_bank", account={"bank": "CMB", "tail": "1203"})
        r = client.post(f"/v4/applications/{app['id']}/answers", headers=h, json=body)
        assert r.status_code == 200, r.text
        app = r.json()
    return app


def offered(client, h: dict[str, str], scenario: str = "lan") -> dict:
    app = answer_all(client, h, start(client, h, scenario))
    assert app["status"] == "offered", app["status"]
    return app


def accept_full(client, h: dict[str, str], app_id: str) -> dict:
    r = client.post(f"/v4/applications/{app_id}/accept", headers=h, json={"option_id": "full"})
    assert r.status_code == 200, r.text
    return r.json()


def officer_trace(client, app_id: str, h: dict[str, str]) -> list[dict]:
    return client.get(f"/v4/applications/{app_id}/trace", headers=h).json()["events"]


# --- scripted model output ----------------------------------------------------------

def call(name: str, **args: Any) -> AgentStep:
    return AgentStep(type="tool_call", tool_name=name, arguments=args)


def final(text: str) -> AgentStep:
    return AgentStep(type="final", text=text)


def judgment(**kw: Any) -> AgentStep:
    base = {"verdict": "approve", "option_id": "full", "concerns": [], "checked_ok": []}
    return final(json.dumps({**base, **kw}, ensure_ascii=False))


class FakeProvider:
    """Attacker-controlled model. ``agent2``/``agent3``/``agent5`` are scripted step lists
    keyed by system prompt; ``texts`` maps a system-prompt keyword to a reply (Agent 1 notes
    / rephrase, Agent 2 explanation); ``order`` drives Agent 1's tool ordering; ``fail`` makes
    every call raise (provider outage)."""

    name = "openai_compat"
    model = "fake"

    def __init__(self, *, agent2: list[AgentStep] | None = None, agent3: list[AgentStep] | None = None,
                 agent5: list[AgentStep] | None = None, texts: dict[str, Any] | None = None,
                 order: list[str] | None = None, fail: bool = False) -> None:
        self.agent2 = list(agent2 or [])
        self.agent3 = list(agent3 or [])
        self.agent5 = list(agent5 or [])
        self.texts = texts or {}
        self.order = order
        self.fail = fail
        self.seen_tools: list[list[str]] = []
        self.agent3_prompts: list[str] = []

    def available(self) -> bool:
        return True

    async def next_step(self, *, system_prompt: str, history: list, tools: list[dict]) -> AgentStep:
        if self.fail:
            raise LLMUnavailable("down")
        self.seen_tools.append([t["name"] for t in tools])
        if system_prompt == AGENT2_SYSTEM:
            return self.agent2.pop(0) if self.agent2 else final("Em đã ghi nhận.")
        if system_prompt == AGENT3_SYSTEM:
            self.agent3_prompts.append(" ".join(m.text or "" for m in history))
            if self.agent3:
                return self.agent3.pop(0)
            raise LLMUnavailable("no agent3 script")
        if system_prompt == AGENT5_SYSTEM:
            if self.agent5:
                return self.agent5.pop(0)
            raise LLMUnavailable("no agent5 script")
        raise LLMUnavailable("no script")

    async def generate_text(self, *, system_prompt: str, user_input: str) -> str:
        if self.fail:
            raise LLMUnavailable("down")
        for key, fn in self.texts.items():
            if key in system_prompt:
                return fn(user_input)
        raise LLMUnavailable("no text script")

    async def generate_structured(self, *, system_prompt: str, user_input: str, schema: type) -> Any:
        if self.fail or self.order is None or getattr(schema, "__name__", "") == "Judgment":
            raise LLMUnavailable("no structured script")
        return schema(order=self.order)
