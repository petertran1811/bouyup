"""18/10/2026: a slow or unreachable model server is skipped for a while (agents use their templates)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.platform.llm import openai_compat
from app.platform.llm.base import LLMUnavailable


def test_read_timeout_opens_the_breaker(monkeypatch):
    calls = []

    async def slow_post(self, *a, **kw):
        calls.append(1)
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx.AsyncClient, "post", slow_post)
    monkeypatch.setattr(openai_compat, "_breaker_until", 0.0)
    prov = openai_compat.OpenAICompatProvider(base_url="http://llm.test/v1", api_key="k", model="m")
    assert prov.available()
    with pytest.raises(LLMUnavailable):
        asyncio.run(prov.generate_text(system_prompt="s", user_input="u"))
    assert len(calls) == 1  # no retries on a timeout
    assert not prov.available() and openai_compat.breaker_open()
    monkeypatch.setattr(openai_compat, "_breaker_until", 0.0)
    assert prov.available()


def test_second_verify_while_running_is_409(bu_client, as_seller):
    from app.api import applications

    applications._VERIFYING.add("app_x")
    try:
        r = bu_client.post("/v4/applications/app_x/verify", headers=as_seller, json={})
        assert r.status_code == 409 and r.json()["error"]["code"] == "VERIFY_IN_PROGRESS"
    finally:
        applications._VERIFYING.discard("app_x")
