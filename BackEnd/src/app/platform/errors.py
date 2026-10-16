"""Client-safe error contract.

Internal exception details never reach the client (plan section 32); they go to
the JSON log instead.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def api_error(
    status_code: int, code: str, message: str, details: dict[str, Any] | None = None
) -> HTTPException:
    detail: dict[str, Any] = {"code": code, "message": message}
    if details:
        detail["details"] = details
    return HTTPException(status_code=status_code, detail=detail)


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return {"error": body}
