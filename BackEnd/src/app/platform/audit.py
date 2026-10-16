"""Structured JSON logging and audit persistence (plan section 20).

Every line is JSON, never contains an API key or a secret, and carries the
identifiers needed to reconstruct a decision: request, workflow, seller, agent,
step, model, prompt version, tool name and input/output hashes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

import structlog

from app.platform.config import settings

_request_id: ContextVar[str] = ContextVar("request_id", default="-")

# Values that must never appear in a log line.
_REDACT_KEYS = {"gemini_api_key", "api_key", "authorization", "token", "secret", "password"}


def new_request_id() -> str:
    return f"req_{uuid4().hex[:16]}"


def set_request_id(request_id: str) -> None:
    _request_id.set(request_id)


def get_request_id() -> str:
    return _request_id.get()


def _redact(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key in list(event_dict):
        if key.lower() in _REDACT_KEYS:
            event_dict[key] = "***"
    return event_dict


def _inject_request_id(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    event_dict.setdefault("request_id", get_request_id())
    return event_dict


def configure_logging() -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _inject_request_id,
            _redact,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


logger = structlog.get_logger("sellergraph")


def payload_hash(payload: Any) -> str:
    """Stable SHA-256 of a tool input/output, so audits can prove sameness
    without storing everything twice."""
    canonical = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
