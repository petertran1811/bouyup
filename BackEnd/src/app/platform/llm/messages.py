"""Agent-facing contracts: LLM steps, structured outputs, API responses."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LLMMessage(BaseModel):
    """One turn of the model conversation, provider agnostic.

    ``provider_payload`` carries the provider's own representation of a model
    turn back to it untouched. Gemini 3.x signs each function-call part with a
    ``thought_signature`` and rejects the next request if that signature is not
    replayed verbatim, so the turn cannot simply be rebuilt from name and args.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    role: Literal["user", "model", "tool"]
    text: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_response: dict[str, Any] | None = None
    provider_payload: Any = None


class AgentStep(BaseModel):
    """What the orchestrator decided to do next (plan section 15)."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    type: Literal["tool_call", "final", "error"]
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    text: str | None = None
    raw_text: str | None = None
    # The provider's own model turn, replayed verbatim on the next call.
    provider_payload: Any = None


class OpportunitySignal(BaseModel):
    """Structured output of the Opportunity Agent (plan section 13.2)."""

    model_config = ConfigDict(extra="forbid")

    opportunity_detected: bool
    type: Literal["WORKING_CAPITAL_GAP", "STOCKOUT_RISK", "NONE"]
    urgency: Literal["LOW", "MEDIUM", "HIGH", "NONE"]
    evidence: list[str] = Field(default_factory=list)
    recommended_next_tool: str | None = None


class AssistantResponse(BaseModel):
    """Schema the model must respect for machine-readable replies (section 17)."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    status: Literal["INFO", "PROPOSAL", "WAITING_APPROVAL", "EXECUTED", "REJECTED"]
    action_id: str | None = None
    requires_user_action: bool = False


class AgentAPIResponse(BaseModel):
    """Public response contract (plan section 31).

    ``facts`` is rendered by the backend from tool output only; ``explanation``
    is free text from the model and carries no authority over the numbers.
    """

    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    seller_id: str
    status: str

    facts: dict[str, Any] = Field(default_factory=dict)
    explanation: str = ""
    explanation_source: Literal["gemini", "template", "template_fallback"] = "template"

    action_id: str | None = None
    requires_user_action: bool = False

    trace_summary: list[str] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)


class MonitoringTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    observed: float | None = None
    threshold: float | None = None


class MonitoringReport(BaseModel):
    """Result of a monitoring tick (plan section 24)."""

    model_config = ConfigDict(extra="forbid")

    seller_id: str
    checked_at: str
    replan_required: bool
    triggers: list[MonitoringTrigger] = Field(default_factory=list)
    baseline: dict[str, Any] = Field(default_factory=dict)
    current: dict[str, Any] = Field(default_factory=dict)
    source_workflow_id: str | None = None
    replan_workflow_id: str | None = None
    replan_action_id: str | None = None
    message: str = ""
