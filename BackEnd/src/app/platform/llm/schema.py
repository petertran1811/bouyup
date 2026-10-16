"""Pydantic model -> the JSON-schema subset Gemini accepts (used by the Gemini provider)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def to_gemini_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Convert a Pydantic model to the subset of JSON Schema Gemini accepts.

    Gemini rejects ``additionalProperties``, ``$defs``/``$ref``, ``const`` and a
    few other keywords, so the schema is inlined and reduced to plain
    type/properties/required/items/enum.
    """
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})
    return _convert(raw, defs)


_TYPE_MAP = {
    "object": "OBJECT",
    "array": "ARRAY",
    "string": "STRING",
    "integer": "INTEGER",
    "number": "NUMBER",
    "boolean": "BOOLEAN",
}


def _convert(spec: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Recursively reduce one JSON-schema node to Gemini's dialect."""
    # Resolve $ref against the model's $defs.
    if "$ref" in spec:
        ref_name = spec["$ref"].rsplit("/", 1)[-1]
        spec = {**defs.get(ref_name, {}), **{k: v for k, v in spec.items() if k != "$ref"}}

    # Optional[X] / unions: take the first non-null branch.
    if "anyOf" in spec and "type" not in spec:
        branches = [b for b in spec["anyOf"] if b.get("type") != "null"]
        if branches:
            merged = _convert(branches[0], defs)
            if spec.get("description"):
                merged["description"] = spec["description"]
            return merged

    out: dict[str, Any] = {}
    json_type = spec.get("type")
    # A bare enum with no declared type is a string enum.
    if json_type is None and spec.get("enum"):
        json_type = "string"
    out["type"] = _TYPE_MAP.get(json_type or "string", "STRING")

    if spec.get("description"):
        out["description"] = spec["description"]
    if spec.get("enum"):
        out["enum"] = [str(v) for v in spec["enum"]]

    if out["type"] == "OBJECT":
        properties = {
            name: _convert(sub, defs) for name, sub in (spec.get("properties") or {}).items()
        }
        if properties:
            out["properties"] = properties
        if spec.get("required"):
            out["required"] = list(spec["required"])
    elif out["type"] == "ARRAY":
        out["items"] = _convert(spec.get("items") or {"type": "string"}, defs)

    return out
