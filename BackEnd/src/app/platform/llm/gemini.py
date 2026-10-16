"""Gemini adapter (plan sections 11 and 16).

This is the only module in the codebase that imports the Google SDK. Everything
else talks to :class:`~app.platform.llm.base.LLMProvider`.

Function calling is driven manually: automatic function calling is disabled so
the backend - not the SDK - decides what runs, validates the arguments and
executes the tool (plan section 16).

**Model fallback.** Gemini quota is enforced per model and per time window, so
one model being exhausted says nothing about the next. The provider therefore
holds an ordered chain of models: on a 429 it parks that model for a cooldown
and immediately retries the request on the next one, rather than failing the
whole call. A 404 (model not available to this key) parks it for the day. Only
a genuinely transient 503/500 is retried against the *same* model.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from pydantic import BaseModel

from app.platform.config import settings
from app.platform.llm.base import LLMUnavailable, NullProvider
from app.platform.llm.messages import AgentStep, LLMMessage
from app.platform import audit
from app.platform.llm.schema import to_gemini_schema

# The SDK warns about AFC whenever tools are passed to generate_content, even
# with AFC explicitly disabled. The warning is noise here.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

# A briefly overloaded model is worth another attempt; a rate-limited one is not.
TRANSIENT_RETRIES = 2
TRANSIENT_BACKOFF = (1.0, 3.0)

QUOTA_MARKERS = ("429", "RESOURCE_EXHAUSTED")
NOT_FOUND_MARKERS = ("404", "NOT_FOUND")
TRANSIENT_MARKERS = ("503", "500", "UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED")

# How long a model sits out after each kind of failure.
NOT_FOUND_COOLDOWN_SECONDS = 86_400.0
TIMEOUT_COOLDOWN_SECONDS = 60.0


class GeminiProvider:
    """Implements the provider protocol on top of ``google-genai``."""

    name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        fallback_models: list[str] | None = None,
    ) -> None:
        self._api_key = (api_key if api_key is not None else settings.gemini_api_key).strip()

        primary = model or settings.gemini_model
        chain = fallback_models if fallback_models is not None else settings.gemini_fallback_models
        # Primary first, then the fallbacks, de-duplicated with order preserved.
        seen = {primary}
        self.last_model: str | None = None
        self.models: list[str] = [primary]
        for candidate in chain:
            if candidate and candidate not in seen:
                seen.add(candidate)
                self.models.append(candidate)

        # model name -> monotonic deadline before which we will not use it.
        self._cooldown: dict[str, float] = {}
        # One client per running event loop: the SDK's async transport is bound to the loop
        # it was first used on, and callers here run on several (FastAPI's, asyncio.run in
        # the lending pipeline). Keyed by id(loop); the loop is kept to detect reuse of an id.
        self._clients: dict[int, tuple[asyncio.AbstractEventLoop, Any]] = {}

    # -- model chain ------------------------------------------------------
    def _model_chain(self) -> list[str]:
        """Models to try, in order. Parked ones go last, never missing."""
        now = time.monotonic()
        ready = [m for m in self.models if self._cooldown.get(m, 0.0) <= now]
        # If everything is parked, try anyway - a stale cooldown is no reason
        # to refuse outright.
        return ready or list(self.models)

    @property
    def model(self) -> str:
        """The model a call would use right now."""
        return self._model_chain()[0]

    def _park(self, model: str, seconds: float, reason: str) -> None:
        self._cooldown[model] = time.monotonic() + seconds
        audit.logger.warning(
            "gemini_model_parked", model=model, reason=reason, cooldown_seconds=seconds
        )

    def status(self) -> list[dict[str, Any]]:
        """Per-model availability, for /v1/system/info."""
        now = time.monotonic()
        out = []
        for index, name in enumerate(self.models):
            remaining = max(0.0, self._cooldown.get(name, 0.0) - now)
            out.append(
                {
                    "model": name,
                    "role": "primary" if index == 0 else "fallback",
                    "available": remaining <= 0,
                    "cooldown_seconds_remaining": round(remaining, 1),
                }
            )
        return out

    # -- plumbing ---------------------------------------------------------
    def available(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> Any:
        """The client of the running event loop, created on first use there. Clients of
        loops that have since closed are dropped (their sync transport closed)."""
        if not self._api_key:
            raise LLMUnavailable("GEMINI_API_KEY is not set")
        loop = asyncio.get_running_loop()
        for key, (owner, client) in list(self._clients.items()):
            if owner.is_closed() or (key == id(loop) and owner is not loop):
                del self._clients[key]
                try:
                    client.close()
                except Exception:  # noqa: BLE001 - a dead loop's client is discarded either way
                    pass
        entry = self._clients.get(id(loop))
        if entry is None:
            from google import genai

            entry = self._clients[id(loop)] = (loop, genai.Client(api_key=self._api_key))
        return entry[1]

    async def aclose(self) -> None:
        """Close the running loop's client (call before that loop ends)."""
        entry = self._clients.pop(id(asyncio.get_running_loop()), None)
        if entry is not None:
            await entry[1].aio.aclose()
            entry[1].close()

    @staticmethod
    def _to_contents(history: list[LLMMessage]) -> list[Any]:
        """Translate provider-agnostic messages into Gemini ``Content`` objects."""
        from google.genai import types

        contents: list[Any] = []
        for message in history:
            # Replay the model's own turn byte for byte when we kept it: it
            # carries the thought_signature Gemini 3.x requires (see
            # LLMMessage.provider_payload).
            if message.provider_payload is not None:
                contents.append(message.provider_payload)
                continue
            if message.role == "user":
                contents.append(
                    types.Content(role="user", parts=[types.Part(text=message.text or "")])
                )
            elif message.role == "model":
                parts = []
                if message.text:
                    parts.append(types.Part(text=message.text))
                if message.tool_name:
                    parts.append(
                        types.Part(
                            function_call=types.FunctionCall(
                                name=message.tool_name, args=message.tool_args or {}
                            )
                        )
                    )
                contents.append(types.Content(role="model", parts=parts or [types.Part(text="")]))
            else:  # tool response
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=message.tool_name or "unknown",
                                response=message.tool_response or {},
                            )
                        ],
                    )
                )
        return contents

    # -- error classification ---------------------------------------------
    @staticmethod
    def _classify(exc: Exception) -> str:
        """``quota`` | ``not_found`` | ``transient`` | ``fatal``.

        Order matters: a 503 body contains "UNAVAILABLE" and a 404 body contains
        "NOT_FOUND", so the more specific cases are tested first.
        """
        text = str(exc)
        if any(marker in text for marker in QUOTA_MARKERS):
            return "quota"
        if any(marker in text for marker in NOT_FOUND_MARKERS):
            return "not_found"
        if any(marker in text for marker in TRANSIENT_MARKERS):
            return "transient"
        return "fatal"

    @classmethod
    def _is_transient(cls, exc: Exception) -> bool:
        """True when retrying the *same* model is worth it."""
        return cls._classify(exc) == "transient"

    async def _generate(self, *, contents: Any, config: Any) -> Any:
        """Run one request, walking the model chain until something answers."""
        client = self._get_client()
        primary = self.models[0]
        last_exc: Exception | None = None
        tried: list[str] = []

        for model in self._model_chain():
            tried.append(model)

            for attempt in range(TRANSIENT_RETRIES + 1):
                try:
                    response = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=model, contents=contents, config=config
                        ),
                        timeout=settings.llm_timeout_seconds,
                    )
                except asyncio.TimeoutError as exc:
                    last_exc = exc
                    audit.logger.warning(
                        "gemini_call_timeout",
                        model=model,
                        timeout_seconds=settings.llm_timeout_seconds,
                    )
                    self._park(model, TIMEOUT_COOLDOWN_SECONDS, "timeout")
                    break

                except Exception as exc:  # noqa: BLE001 - surfaced as LLMUnavailable
                    last_exc = exc
                    kind = self._classify(exc)
                    audit.logger.warning(
                        "gemini_call_failed",
                        model=model,
                        attempt=attempt + 1,
                        kind=kind,
                        error_type=type(exc).__name__,
                        error=str(exc)[:300],
                    )

                    # A bad request will fail identically on every model.
                    if kind == "fatal":
                        raise LLMUnavailable(
                            f"Gemini call failed on {model}: {type(exc).__name__}"
                        ) from exc

                    if kind == "transient" and attempt < TRANSIENT_RETRIES:
                        await asyncio.sleep(
                            TRANSIENT_BACKOFF[min(attempt, len(TRANSIENT_BACKOFF) - 1)]
                        )
                        continue

                    if kind == "quota":
                        self._park(model, settings.gemini_quota_cooldown_seconds, "quota")
                    elif kind == "not_found":
                        self._park(model, NOT_FOUND_COOLDOWN_SECONDS, "model_not_available")
                    else:
                        self._park(model, TIMEOUT_COOLDOWN_SECONDS, "repeated_overload")
                    break

                else:
                    # Which model actually answered, as opposed to which one
                    # would be tried next. After a fallback those differ, and
                    # the admin trace needs the one that did the work.
                    self.last_model = model
                    if model != primary:
                        audit.logger.info(
                            "gemini_answered_by_fallback", model=model, primary=primary
                        )
                    return response

        raise LLMUnavailable(
            "Gemini call failed on every candidate model "
            f"({', '.join(tried)}): {type(last_exc).__name__ if last_exc else 'unknown'}"
        )

    # -- protocol ---------------------------------------------------------
    async def next_step(
        self,
        *,
        system_prompt: str,
        history: list[LLMMessage],
        tools: list[dict[str, Any]],
    ) -> AgentStep:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.0,
            # The backend runs functions, not the SDK (plan section 16).
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        if tools:
            config.tools = [types.Tool(function_declarations=tools)]

        response = await self._generate(contents=self._to_contents(history), config=config)

        candidates = getattr(response, "candidates", None) or []
        if not candidates or candidates[0].content is None:
            return AgentStep(type="final", text="")

        parts = candidates[0].content.parts or []
        text_chunks: list[str] = []
        for part in parts:
            call = getattr(part, "function_call", None)
            if call is not None and call.name:
                return AgentStep(
                    type="tool_call",
                    tool_name=call.name,
                    arguments=dict(call.args or {}),
                    raw_text="".join(text_chunks) or None,
                    provider_payload=candidates[0].content,
                )
            if getattr(part, "text", None):
                text_chunks.append(part.text)

        return AgentStep(type="final", text="".join(text_chunks).strip())

    async def generate_text(self, *, system_prompt: str, user_input: str) -> str:
        from google.genai import types

        response = await self._generate(
            contents=user_input,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt, temperature=0.2
            ),
        )
        return (response.text or "").strip()

    async def generate_structured(
        self, *, system_prompt: str, user_input: str, schema: type[BaseModel]
    ) -> BaseModel:
        from google.genai import types

        response = await self._generate(
            contents=user_input,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=to_gemini_schema(schema),
            ),
        )
        raw = (response.text or "").strip()
        if not raw:
            raise LLMUnavailable("Gemini returned an empty structured response")
        try:
            return schema.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001
            raise LLMUnavailable(f"Structured response did not match schema: {exc}") from exc


_provider: Any | None = None


def get_provider() -> Any:
    """Process-wide provider. Returns :class:`NullProvider` when unconfigured."""
    global _provider
    if _provider is None:
        if not settings.use_llm:
            _provider = NullProvider()
        elif settings.llm_base_url:
            from app.platform.llm.openai_compat import OpenAICompatProvider

            _provider = OpenAICompatProvider()
        else:
            _provider = GeminiProvider()
        audit.logger.info(
            "llm_provider_selected",
            provider=_provider.name,
            model=_provider.model,
            models=getattr(_provider, "models", None),
            api_key=settings.masked_api_key,
        )
    return _provider


def set_provider(provider: Any) -> None:
    """Override the provider (used by tests to inject a fake)."""
    global _provider
    _provider = provider
