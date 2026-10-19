"""CCCD scan and revenue screenshots for an application (review 17/10/2026).

- ``POST /v4/applications/{id}/cccd`` — OCR of one side of the PRC resident ID card (BackEnd/src/CCCD,
  the team's Backend_CCCD). The image is read in memory and never stored; only the recognised fields,
  the GB 11643 checks, the warnings and the image's sha256 are kept on the application.
- ``POST /v4/applications/{id}/statement-images`` — screenshots of the store's back-office revenue
  (JPEG/PNG, up to 6). Stored for the officer; the figures OCR reads on them are kept so Agent 1 can see
  whether the typed monthly revenue appears on the screenshot.
- ``GET /v4/applications/{id}/statement-images/{image_id}`` — the owner or staff view one.
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import re
import secrets
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api import views
from app.api.applications import _done, _own, _require, load
from app.platform import events
from app.platform.config import settings
from app.platform.db.session import get_session
from app.platform.errors import api_error
from app.platform.security import require_roles
from app.platform.tables import BuUser

router = APIRouter(prefix="/applications", tags=["v4-identity-docs"])
_sellers = require_roles("seller")
_readers = require_roles("seller", "officer", "admin")

MAX_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 6


class ImageIn(BaseModel):
    image: str = Field(min_length=16, max_length=12_000_000, description="JPEG/PNG, base64 or a data: URL")
    side: Literal["auto", "front", "back"] = "auto"
    month: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


def _decode(raw: str) -> bytes:
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise api_error(400, "VALIDATION_ERROR", "Ảnh không đúng định dạng base64.", {"field": "image"}) from exc
    if len(data) > MAX_BYTES:
        raise api_error(413, "VALIDATION_ERROR", "Ảnh vượt giới hạn 8 MB.", {"field": "image"})
    return data


def _ocr() -> Any:
    from CCCD import china_id

    return china_id


@router.post("/{app_id}/cccd")
async def scan_cccd(app_id: str, body: ImageIn, user: BuUser = Depends(_sellers),
                    session: Session = Depends(get_session)) -> dict:
    app_row, doc = _own(session, app_id, user)
    _require(app_row, "draft")
    data = _decode(body.image)
    ocr = _ocr()
    try:
        ocr.validate_image(data)
        result = await run_in_threadpool(ocr.scan_image, data, body.side)
    except ocr.InvalidImage as exc:
        raise api_error(422, "VALIDATION_ERROR", str(exc), {"field": "image"}) from exc
    except ocr.OCRUnavailable as exc:
        raise api_error(503, "OCR_UNAVAILABLE", str(exc)) from exc
    side = result["side"]
    if side not in ("front", "back"):
        raise api_error(422, "VALIDATION_ERROR", "Không nhận ra mặt trước hay mặt sau của CCCD; chụp lại rõ hơn.",
                        {"field": "image", "warnings": result["warnings"]})
    scans = dict(doc.get("cccd_scans") or {})
    scans[side] = {**result, "sha256": hashlib.sha256(data).hexdigest(), "at": views.now_iso()}
    doc["cccd_scans"] = scans
    events.log(session, app_row.id, "seller", "cccd_scan", f"Quét CCCD mặt {'trước' if side == 'front' else 'sau'}",
               {"side": side, "warnings": len(result["warnings"])})
    views.store(app_row, doc)
    session.commit()
    return {"side": side, "fields": result["fields"], "warnings": result["warnings"],
            "review_required": True, "scans": sorted(scans)}


def _numbers(text_lines: list[str]) -> list[int]:
    """Every figure of 3+ digits on the screenshot (thousand separators removed)."""
    out: set[int] = set()
    for line in text_lines:
        for tok in re.findall(r"\d[\d,.\s]{2,}\d", line):
            digits = re.sub(r"[^\d]", "", tok)
            if 3 <= len(digits) <= 12:
                out.add(int(digits))
    return sorted(out)


def _screenshot_numbers(data: bytes) -> tuple[list[int], bool]:
    ocr = _ocr()
    try:
        raw = ocr._engine().ocr(ocr._image_array(data)[:, :, ::-1].copy(), cls=True)
        return _numbers([d[0] for d in ocr._detections(raw)]), True
    except Exception:  # noqa: BLE001 - the screenshot is kept for the officer even when OCR fails
        return [], False


@router.post("/{app_id}/statement-images", status_code=201)
async def upload_statement_image(app_id: str, body: ImageIn, user: BuUser = Depends(_sellers),
                                 session: Session = Depends(get_session)) -> dict:
    app_row, doc = _own(session, app_id, user)
    _require(app_row, "consented")
    images = list(doc.get("statement_images") or [])
    if len(images) >= MAX_IMAGES:
        raise api_error(400, "VALIDATION_ERROR", f"Tối đa {MAX_IMAGES} ảnh doanh thu.", {"field": "image"})
    data = _decode(body.image)
    ocr = _ocr()
    try:
        ocr.validate_image(data)
    except ocr.InvalidImage as exc:
        raise api_error(422, "VALIDATION_ERROR", str(exc), {"field": "image"}) from exc
    except ocr.OCRUnavailable:
        pass  # Pillow missing: keep the upload, the officer still sees it
    digest = hashlib.sha256(data).hexdigest()
    if any(i["sha256"] == digest for i in images):
        raise api_error(409, "CONFLICT", "Ảnh này đã được tải lên.", {"field": "image"})
    numbers, read = await run_in_threadpool(_screenshot_numbers, data)
    ext = "png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "jpg"
    folder = Path(settings.upload_dir) / app_row.id
    folder.mkdir(parents=True, exist_ok=True)
    image_id = "img_" + secrets.token_hex(6)
    (folder / f"{image_id}.{ext}").write_bytes(data)
    item = {"id": image_id, "sha256": digest, "bytes": len(data), "ext": ext, "month": body.month,
            "numbers": numbers[:200], "ocr_read": read, "at": views.now_iso()}
    images.append(item)
    doc["statement_images"] = images
    events.log(session, app_row.id, "seller", "statement_image", f"Tải ảnh doanh thu {len(images)}/{MAX_IMAGES}",
               {"image_id": image_id, "sha256": digest})
    views.store(app_row, doc)
    session.commit()
    return {"id": image_id, "month": body.month, "ocr_read": read, "count": len(images)}


@router.delete("/{app_id}/statement-images/{image_id}")
def delete_statement_image(app_id: str, image_id: str, user: BuUser = Depends(_sellers),
                           session: Session = Depends(get_session)) -> dict:
    app_row, doc = _own(session, app_id, user)
    _require(app_row, "consented")
    images = [i for i in doc.get("statement_images") or [] if i["id"] != image_id]
    doc["statement_images"] = images
    views.store(app_row, doc)
    return _done(session, app_row, user)


@router.get("/{app_id}/statement-images/{image_id}")
def get_statement_image(app_id: str, image_id: str, user: BuUser = Depends(_readers),
                        session: Session = Depends(get_session)) -> FileResponse:
    app_row = load(session, app_id, user)
    item = next((i for i in (app_row.doc or {}).get("statement_images") or [] if i["id"] == image_id), None)
    if item is None or not re.fullmatch(r"img_[0-9a-f]{12}", image_id):
        raise api_error(404, "NOT_FOUND", "Không tìm thấy ảnh.")
    path = Path(settings.upload_dir) / app_row.id / f"{image_id}.{item['ext']}"
    if not path.is_file():
        raise api_error(404, "NOT_FOUND", "Ảnh không còn trên máy chủ.")
    return FileResponse(path, media_type="image/png" if item["ext"] == "png" else "image/jpeg",
                        headers={"Cache-Control": "private, no-store"})


def cccd_summary(doc: dict[str, Any]) -> dict[str, Any] | None:
    """What the identity step keeps from the scans (never the image)."""
    scans = copy.deepcopy(doc.get("cccd_scans") or {})
    return scans or None
