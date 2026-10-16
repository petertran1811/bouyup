"""Provider-agnostic LLM interface.

Plan section 11.3 sketches a single-shot ``run_agent(...)``. Multi-turn function
calling (section 16) cannot be expressed that way: the backend has to execute a
function and hand the result back before the model decides the next step. The
protocol below therefore exposes :meth:`next_step`, which is that loop's unit of
work, plus the two one-shot calls the explanation agents need.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from app.platform.llm.messages import AgentStep, LLMMessage


class LLMUnavailable(Exception):
    """No provider is configured, or the provider call failed."""


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model: str

    def available(self) -> bool:
        """True when a call may be attempted."""
        ...

    async def next_step(
        self,
        *,
        system_prompt: str,
        history: list[LLMMessage],
        tools: list[dict[str, Any]],
    ) -> AgentStep:
        """One orchestration step: either a tool call or a final answer."""
        ...

    async def generate_text(self, *, system_prompt: str, user_input: str) -> str:
        """Free-text generation, used for explanations."""
        ...

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_input: str,
        schema: type[BaseModel],
    ) -> BaseModel:
        """Schema-constrained generation (plan section 17)."""
        ...


class NullProvider:
    """Stand-in used when no API key is configured.

    It never pretends to answer: callers fall back to deterministic templates,
    which is why the whole system still works end-to-end with the LLM switched
    off (plan section 35, milestone 1).
    """

    name = "null"
    model = "none"

    def available(self) -> bool:
        return False

    async def next_step(
        self, *, system_prompt: str, history: list[LLMMessage], tools: list[dict[str, Any]]
    ) -> AgentStep:
        raise LLMUnavailable("No LLM provider configured")

    async def generate_text(self, *, system_prompt: str, user_input: str) -> str:
        raise LLMUnavailable("No LLM provider configured")

    async def generate_structured(
        self, *, system_prompt: str, user_input: str, schema: type[BaseModel]
    ) -> BaseModel:
        raise LLMUnavailable("No LLM provider configured")
