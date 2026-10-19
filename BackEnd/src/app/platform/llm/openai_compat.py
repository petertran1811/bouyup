"""OpenAI-compatible adapter, for a model served by vLLM (plan section 34, phase 5).

Configured by ``LLM_HOST`` / ``LLM_PORT`` / ``LLM_MODEL_NAME`` / ``LLM_API_KEY``. When
``LLM_HOST`` is set this provider is used instead of Gemini (see ``get_provider``).

It talks plain HTTP to ``/v1/chat/completions`` so no extra SDK is needed. A new
``httpx.AsyncClient`` is opened per call: callers run on several event loops (FastAPI's,
``asyncio.run`` in the lending pipeline) and a shared async client is bound to one.
"""

from __future__ import annotations

import asyncio
import time
import json
from typing import Any

import httpx
from pydantic import BaseModel

from app.platform.config import settings
from app.platform.llm.base import LLMUnavailable
from app.platform.llm.messages import AgentStep, LLMMessage
from app.platform import audit

# A briefly overloaded or unreachable server is worth another attempt; a 4xx is not.
TRANSIENT_RETRIES = 2
TRANSIENT_BACKOFF = (1.0, 3.0)
CONNECT_TIMEOUT_SECONDS = 5.0
# 18/10/2026: when the model server times out or cannot be reached, stop calling it for a while. Every agent
# then falls back to its template at once, instead of each request (often inside a database transaction)
# waiting timeout × retries for a server that is down or overloaded.
BREAKER_SECONDS = 120.0
_breaker_until = 0.0


def _trip(reason: str) -> None:
    global _breaker_until
    _breaker_until = time.monotonic() + BREAKER_SECONDS
    audit.logger.warning("llm_breaker_open", seconds=BREAKER_SECONDS, reason=reason)


def breaker_open() -> bool:
    return time.monotonic() < _breaker_until


def _to_openai_schema(spec: Any) -> Any:
    """Tool declarations are written in Gemini's dialect (``"type": "OBJECT"``); JSON Schema
    wants the type names in lower case."""
    if isinstance(spec, dict):
        return {
            key: value.lower() if key == "type" and isinstance(value, str) else _to_openai_schema(value)
            for key, value in spec.items()
        }
    if isinstance(spec, list):
        return [_to_openai_schema(item) for item in spec]
    return spec


class OpenAICompatProvider:
    """Implements the provider protocol on top of an OpenAI-style chat completions API."""

    name = "openai_compat"

    def __init__(
        self, base_url: str | None = None, api_key: str | None = None, model: str | None = None
    ) -> None:
        self._base_url = (base_url if base_url is not None else settings.llm_base_url).rstrip("/")
        self._api_key = (api_key if api_key is not None else settings.llm_api_key).strip()
        self.model = (model if model is not None else settings.llm_model_name).strip()
        self.models = [self.model]
        self.last_model: str | None = None

    def available(self) -> bool:
        return bool(self._base_url and self.model) and not breaker_open()

    def status(self) -> list[dict[str, Any]]:
        """Per-model availability, for /v1/system/info."""
        return [{"model": self.model, "role": "primary", "available": self.available(),
                 "cooldown_seconds_remaining": 0.0}]

    # -- plumbing ---------------------------------------------------------
    @staticmethod
    def _to_messages(system_prompt: str, history: list[LLMMessage]) -> list[dict[str, Any]]:
        """Translate provider-agnostic messages into chat messages. Each tool result is tied
        to the call before it by an id made up here: the API only needs the pair to match."""
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        calls = 0
        for message in history:
            if message.role == "user":
                messages.append({"role": "user", "content": message.text or ""})
            elif message.role == "model":
                if not message.tool_name:
                    messages.append({"role": "assistant", "content": message.text or ""})
                    continue
                calls += 1
                messages.append({
                    "role": "assistant",
                    "content": message.text or "",
                    "tool_calls": [{
                        "id": f"call_{calls}",
                        "type": "function",
                        "function": {
                            "name": message.tool_name,
                            "arguments": json.dumps(message.tool_args or {}, ensure_ascii=False),
                        },
                    }],
                })
            else:  # tool response
                messages.append({
                    "role": "tool",
                    "tool_call_id": f"call_{calls}",
                    "content": json.dumps(message.tool_response or {}, ensure_ascii=False, default=str),
                })
        return messages

    async def _chat(self, body: dict[str, Any]) -> dict[str, Any]:
        """One chat completion; returns the first choice's message."""
        if not self.available():
            raise LLMUnavailable("LLM_HOST / LLM_MODEL_NAME are not set")
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        payload = {"model": self.model, **body}
        timeout = httpx.Timeout(settings.llm_timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS)
        last_error = "unknown"
        for attempt in range(TRANSIENT_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        f"{self._base_url}/chat/completions", json=payload, headers=headers
                    )
            except httpx.HTTPError as exc:
                last_error = type(exc).__name__
                audit.logger.warning(
                    "llm_call_failed", provider=self.name, model=self.model, attempt=attempt + 1,
                    error_type=last_error, error=str(exc)[:300],
                )
                # A server that cannot be reached, or too slow to answer, will not be back within the backoff.
                if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)):
                    _trip(last_error)
                    break
            else:
                if response.status_code < 400:
                    choices = response.json().get("choices") or []
                    if not choices:
                        raise LLMUnavailable(f"{self.model} returned no choices")
                    self.last_model = self.model
                    return choices[0].get("message") or {}
                last_error = f"HTTP {response.status_code}"
                audit.logger.warning(
                    "llm_call_failed", provider=self.name, model=self.model, attempt=attempt + 1,
                    status=response.status_code, error=response.text[:300],
                )
                # A bad request fails the same way every time.
                if response.status_code < 500 and response.status_code != 429:
                    break
            if attempt < TRANSIENT_RETRIES:
                await asyncio.sleep(TRANSIENT_BACKOFF[min(attempt, len(TRANSIENT_BACKOFF) - 1)])
        raise LLMUnavailable(f"LLM call failed on {self.model}: {last_error}")

    # -- protocol ---------------------------------------------------------
    async def next_step(
        self,
        *,
        system_prompt: str,
        history: list[LLMMessage],
        tools: list[dict[str, Any]],
    ) -> AgentStep:
        body: dict[str, Any] = {
            "messages": self._to_messages(system_prompt, history),
            "temperature": 0.0,
        }
        if tools:
            body["tools"] = [{"type": "function", "function": _to_openai_schema(t)} for t in tools]
            body["tool_choice"] = "auto"
            # The loop runs one function per step (plan section 16).
            body["parallel_tool_calls"] = False

        message = await self._chat(body)
        text = (message.get("content") or "").strip()
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            if not function.get("name"):
                continue
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError as exc:
                raise LLMUnavailable(f"Tool arguments were not valid JSON: {exc}") from exc
            return AgentStep(
                type="tool_call",
                tool_name=function["name"],
                arguments=arguments if isinstance(arguments, dict) else {},
                raw_text=text or None,
            )
        return AgentStep(type="final", text=text)

    async def generate_text(self, *, system_prompt: str, user_input: str) -> str:
        message = await self._chat({
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            "temperature": 0.2,
        })
        return (message.get("content") or "").strip()

    async def generate_structured(
        self, *, system_prompt: str, user_input: str, schema: type[BaseModel]
    ) -> BaseModel:
        message = await self._chat({
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            "temperature": 0.0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
            },
        })
        raw = (message.get("content") or "").strip()
        if not raw:
            raise LLMUnavailable(f"{self.model} returned an empty structured response")
        try:
            return schema.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001
            raise LLMUnavailable(f"Structured response did not match schema: {exc}") from exc
