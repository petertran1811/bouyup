"""Drift guard: every method + path in API_CONTRACT_V4.md exists, and every /v4 route is documented."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.main import app

CONTRACT = Path(__file__).resolve().parents[2] / "API_config" / "API_CONTRACT_V4.md"
_ROUTE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\b[\s|`]*(/v4/[A-Za-z0-9_\-{}/.]+)")


def _norm(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path.rstrip(".").rstrip("/"))


def documented() -> set[tuple[str, str]]:
    return {(m, _norm(p)) for m, p in _ROUTE.findall(CONTRACT.read_text(encoding="utf-8"))}


def implemented() -> set[tuple[str, str]]:
    """From the OpenAPI schema (included routers are not flattened in ``app.routes``)."""
    out = set()
    for path, ops in app.openapi()["paths"].items():
        if path.startswith("/v4/"):
            out |= {(m.upper(), _norm(path)) for m in ops if m.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE")}
    assert len(out) > 50
    return out


def test_contract_routes_exist():
    missing = documented() - implemented()
    assert not missing, f"documented but not implemented: {sorted(missing)}"


def test_every_v4_route_is_documented():
    undocumented = implemented() - documented()
    assert not undocumented, f"implemented but not in API_CONTRACT_V4.md: {sorted(undocumented)}"
