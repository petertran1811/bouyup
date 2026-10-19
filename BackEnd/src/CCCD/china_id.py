"""Local OCR and deterministic field extraction for PRC resident ID cards (居民身份证).

From the team's Backend_CCCD (sellergraph-core/app/credit/ocr/china_id.py). The field parser and
the GB 11643 checks are unchanged. The engine: PaddleOCR needs Python 3.10 and paddlepaddle 2.6, the
BuoyUp backend runs Python 3.12, so the same PaddleOCR Chinese models run through RapidOCR on the
onnxruntime BuoyUp already ships (``rapidocr_onnxruntime``). PaddleOCR is still used when installed
and ``CCCD_OCR_ENGINE=paddle``. This module never writes the source image or OCR text to disk.
"""

from __future__ import annotations

import io
import os
import re
from datetime import date
from functools import lru_cache
from typing import Any, Literal

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000
SUPPORTED_IMAGE_FORMATS = {"JPEG", "PNG"}
Side = Literal["auto", "front", "back"]


class OCRUnavailable(RuntimeError):
    """The optional Chinese OCR runtime is missing or failed to initialize."""


class InvalidImage(ValueError):
    """The upload is not a supported, safely decodable image."""


_FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "name": ("姓名",),
    "gender": ("性别",),
    "ethnicity": ("民族",),
    "birth_date": ("出生日期", "出生"),
    "address": ("住址",),
    "id_number": ("公民身份号码", "身份证号码", "身份证号", "身份号码"),
    "issuing_authority": ("签发机关",),
    "validity_period": ("有效期限", "有效期"),
}
_ALL_LABELS = tuple(label for labels in _FIELD_LABELS.values() for label in labels)
_ID_RE = re.compile(r"(?<!\d)(\d{17}[0-9Xx])(?!\d)")
_DATE_RE = re.compile(r"((?:19|20)\d{2})\s*年?\s*(\d{1,2})\s*月?\s*(\d{1,2})\s*日?")
_PERIOD_RE = re.compile(
    r"((?:19|20)\d{2}[.年/-]\d{1,2}[.月/-]\d{1,2}日?\s*[-~至到]\s*"
    r"(?:长期|(?:19|20)\d{2}[.年/-]\d{1,2}[.月/-]\d{1,2}日?))"
)
_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_CHECK_CHARS = "10X98765432"


def validate_image(data: bytes) -> tuple[int, int]:
    """Check actual image encoding/dimensions; do not trust the client MIME type."""
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:  # pragma: no cover - optional OCR runtime
        raise OCRUnavailable("Chưa cài Pillow. Cài sellergraph-core/requirements-ocr.txt.") from exc
    if not data:
        raise InvalidImage("Ảnh tải lên đang trống.")
    if len(data) > MAX_IMAGE_BYTES:
        raise InvalidImage("Ảnh vượt giới hạn 8 MB.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in SUPPORTED_IMAGE_FORMATS:
                raise InvalidImage("Chỉ nhận ảnh JPEG hoặc PNG.")
            width, height = image.size
            if width < 250 or height < 150:
                raise InvalidImage("Ảnh có độ phân giải quá thấp để nhận dạng.")
            if width * height > MAX_IMAGE_PIXELS:
                raise InvalidImage("Ảnh có kích thước điểm ảnh vượt giới hạn an toàn.")
            image.verify()
            return width, height
    except InvalidImage:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidImage("Không đọc được ảnh. Hãy tải ảnh JPEG hoặc PNG rõ nét.") from exc


class _RapidEngine:
    """RapidOCR (PaddleOCR det/cls/rec models on onnxruntime) with PaddleOCR 2.x's output shape."""

    name = "RapidOCR / PaddleOCR ch (onnxruntime)"

    def __init__(self) -> None:
        from rapidocr_onnxruntime import RapidOCR

        self._ocr = RapidOCR()

    def ocr(self, image: Any, cls: bool = True) -> Any:
        result, _elapsed = self._ocr(image, use_cls=cls)
        # RapidOCR: [[box, text, score], …] → PaddleOCR 2.x: [[[box, (text, score)], …]]
        return [[[box, (text, float(score))] for box, text, score in (result or [])]]


def engine_name() -> str:
    return getattr(_engine(), "name", "PaddleOCR / ch")


@lru_cache(maxsize=1)
def _engine() -> Any:
    if os.getenv("CCCD_OCR_ENGINE", "rapid").lower() != "paddle":
        try:
            return _RapidEngine()
        except Exception as exc:  # pragma: no cover - depends on the deployment
            raise OCRUnavailable("Chưa cài rapidocr_onnxruntime (BackEnd/src/requirements.txt).") from exc
    try:
        from paddleocr import PaddleOCR
    except Exception as exc:  # pragma: no cover - depends on deployment extras
        raise OCRUnavailable(
            "Chưa cài PaddleOCR. Cài sellergraph-core/requirements-ocr.txt bằng Python 3.10."
        ) from exc
    try:
        return PaddleOCR(
            lang="ch",
            use_angle_cls=True,
            use_gpu=os.getenv("PADDLE_OCR_USE_GPU", "false").lower() in {"1", "true", "yes"},
            show_log=False,
        )
    except Exception as exc:  # pragma: no cover - model/platform specific
        raise OCRUnavailable("Không khởi tạo được model PaddleOCR tiếng Trung.") from exc


def _image_array(data: bytes) -> Any:
    import numpy as np
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        return np.asarray(image.convert("RGB"))


def _detections(raw: Any) -> list[tuple[str, float, float, float]]:
    """Flatten PaddleOCR 2.x detections into text/confidence/top/left tuples."""
    found: list[tuple[str, float, float, float]] = []

    def visit(node: Any) -> None:
        if not isinstance(node, (list, tuple)):
            return
        if len(node) == 2 and isinstance(node[1], (list, tuple)) and len(node[1]) >= 2:
            box, recognition = node
            text, confidence = recognition[0], recognition[1]
            if isinstance(text, str):
                try:
                    top = sum(float(point[1]) for point in box) / len(box)
                    left = sum(float(point[0]) for point in box) / len(box)
                    found.append((text.strip(), float(confidence), top, left))
                    return
                except (TypeError, ValueError, IndexError, ZeroDivisionError):
                    pass
        for child in node:
            visit(child)

    visit(raw)
    found.sort(key=lambda value: (round(value[2] / 12), value[3]))
    return found


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).replace(":", "：")


def _side(lines: list[tuple[str, float, float, float]], requested: Side) -> str:
    if requested != "auto":
        return requested
    text = "".join(_compact(line[0]) for line in lines)
    if any(label in text for label in _FIELD_LABELS["issuing_authority"] + _FIELD_LABELS["validity_period"]):
        return "back"
    if any(label in text for label in _FIELD_LABELS["name"] + _FIELD_LABELS["id_number"] + _FIELD_LABELS["birth_date"]):
        return "front"
    return "unknown"


def _next_field_start(text: str, current_key: str) -> int | None:
    positions = [text.find(label) for key, labels in _FIELD_LABELS.items() if key != current_key
                 for label in labels if text.find(label) >= 0]
    return min(positions) if positions else None


def _field_value(
    lines: list[tuple[str, float, float, float]], key: str, *, max_following: int = 2
) -> tuple[str, float] | None:
    for index, (raw, confidence, _top, _left) in enumerate(lines):
        compact = _compact(raw)
        for label in _FIELD_LABELS[key]:
            start = compact.find(label)
            if start < 0:
                continue
            value = compact[start + len(label):].lstrip("：: ")
            next_start = _next_field_start(value, key)
            if next_start is not None:
                value = value[:next_start]
            used = [confidence]
            if value and key != "id_number":
                return value.strip("：: "), min(used)
            fragments: list[str] = [value] if value else []
            for next_raw, next_conf, *_ in lines[index + 1:index + 1 + max_following]:
                next_compact = _compact(next_raw)
                if any(other in next_compact for other in _ALL_LABELS):
                    break
                fragments.append(next_compact)
                used.append(next_conf)
                # Dates and names are one line; addresses/validity can wrap.
                if key in {"name", "gender", "ethnicity", "birth_date"}:
                    break
                if key == "id_number" and len(re.sub(r"[^0-9Xx]", "", "".join(fragments))) >= 18:
                    break
            if fragments:
                return "".join(fragments), min(used)
    return None


def _id_checks(value: str) -> dict[str, Any]:
    number = value.upper()
    shape_ok = bool(re.fullmatch(r"\d{17}[0-9X]", number))
    region_nonzero = shape_ok and number[:6] != "000000"
    result: dict[str, Any] = {
        "format_valid": shape_ok and region_nonzero,
        "region_code_nonzero": region_nonzero,
        "checksum_valid": False,
        "birth_date": None,
    }
    if not shape_ok:
        return result
    try:
        result["birth_date"] = date(int(number[6:10]), int(number[10:12]), int(number[12:14])).isoformat()
    except ValueError:
        result["format_valid"] = False
        return result
    checksum = _CHECK_CHARS[sum(int(digit) * weight for digit, weight in zip(number[:17], _WEIGHTS)) % 11]
    result["checksum_valid"] = checksum == number[-1]
    return result


def _field(value: str | None, confidence: float | None) -> dict[str, Any]:
    return {"value": value, "confidence": round(confidence, 4) if confidence is not None else None}


def parse_fields(lines: list[tuple[str, float, float, float]], requested_side: Side) -> dict[str, Any]:
    detected_side = _side(lines, requested_side)
    fields: dict[str, Any] = {}
    warnings: list[str] = []

    if detected_side == "front":
        for key in ("name", "gender", "ethnicity", "birth_date", "address", "id_number"):
            follow = 4 if key == "id_number" else (3 if key == "address" else 1)
            result = _field_value(lines, key, max_following=follow)
            fields[key] = _field(result[0] if result else None, result[1] if result else None)

        gender = fields["gender"]["value"] or ""
        fields["gender"]["value"] = "男" if "男" in gender else ("女" if "女" in gender else None)
        ethnicity = fields["ethnicity"]["value"]
        if ethnicity and not ethnicity.endswith("族"):
            fields["ethnicity"]["value"] = ethnicity + "族"

        dob_value = fields["birth_date"]["value"] or ""
        dob_match = _DATE_RE.search(dob_value)
        if dob_match:
            try:
                fields["birth_date"]["value"] = date(
                    int(dob_match.group(1)), int(dob_match.group(2)), int(dob_match.group(3))
                ).isoformat()
            except ValueError:
                warnings.append("出生日期无法解析，请人工核对。")
        else:
            fields["birth_date"]["value"] = None

        number_text = fields["id_number"]["value"] or ""
        match = _ID_RE.search(number_text.upper().replace(" ", ""))
        number = match.group(1).upper() if match else None
        fields["id_number"]["value"] = number
        fields["id_number_validation"] = _id_checks(number) if number else {
            "format_valid": False, "region_code_nonzero": False,
            "checksum_valid": False, "birth_date": None
        }
        if number and not fields["id_number_validation"]["checksum_valid"]:
            warnings.append("身份证号码格式或校验码不匹配，请人工核对。")
        id_birth = fields["id_number_validation"]["birth_date"]
        if id_birth and fields["birth_date"]["value"] and id_birth != fields["birth_date"]["value"]:
            warnings.append("证件号码中的出生日期与打印出生日期不一致。")
        for key in ("name", "gender", "ethnicity", "birth_date", "address", "id_number"):
            item = fields[key]
            if not item["value"]:
                warnings.append(f"未能识别字段 {key}，请人工核对。")
            elif item["confidence"] is not None and item["confidence"] < 0.85:
                warnings.append(f"字段 {key} 置信度偏低，请人工核对。")
    elif detected_side == "back":
        for key in ("issuing_authority", "validity_period"):
            result = _field_value(lines, key, max_following=2)
            fields[key] = _field(result[0] if result else None, result[1] if result else None)
            if not fields[key]["value"]:
                warnings.append(f"未能识别字段 {key}，请人工核对。")
            elif fields[key]["confidence"] is not None and fields[key]["confidence"] < 0.85:
                warnings.append(f"字段 {key} 置信度偏低，请人工核对。")
        period = fields["validity_period"]["value"] or ""
        match = _PERIOD_RE.search(period)
        if match:
            fields["validity_period"]["value"] = re.sub(r"\s+", "", match.group(1))
    else:
        warnings.append("无法判断证件正反面，请选择正面或反面后重试。")

    return {
        "document_type": "china_resident_identity_card",
        "side": detected_side,
        "engine": "RapidOCR / PaddleOCR ch",
        "fields": fields,
        "review_required": True,
        "authenticity_verified": False,
        "warnings": list(dict.fromkeys(warnings)),
    }


def scan_image(data: bytes, side: Side = "auto") -> dict[str, Any]:
    """Recognize one side of a Chinese resident identity card in memory."""
    validate_image(data)
    try:
        raw = _engine().ocr(_image_array(data)[:, :, ::-1].copy(), cls=True)  # RGB → BGR (OpenCV order)
    except OCRUnavailable:
        raise
    except Exception as exc:  # sanitize model/backend errors; never include OCR content
        raise OCRUnavailable("OCR không xử lý được ảnh trên thiết bị này.") from exc
    detections = _detections(raw)
    if not detections:
        raise InvalidImage("Không nhận diện được vùng chữ trong ảnh.")
    return parse_fields(detections, side)

