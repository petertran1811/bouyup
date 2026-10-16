"""InsightFace buffalo_l: SCRFD-10G detection + ArcFace (w600k_r50) 512-d embeddings.

Only the detector and the recognizer are loaded; head pose comes from the detector's five
landmarks (pose.py), so the 143 MB 1k3d68 model is never run. The model pack is
downloaded by InsightFace into <model_root>/models/buffalo_l on first load.
"""

from __future__ import annotations

import base64
import binascii
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from Reid.src import pose

MODEL_PACK = "buffalo_l"
MAX_IMAGE_BYTES = 1_500_000
MAX_SIDE = 960
MAX_DECODE_SIDE = 2000  # checked in the JPEG header, before any pixel is decoded
RETRY_AFTER_FAILURE = 60.0


class FaceUnavailable(RuntimeError):
    """InsightFace / onnxruntime missing, or the model pack could not be loaded."""


class FaceInputError(ValueError):
    """The uploaded frame is not a decodable image."""


@dataclass
class Detection:
    bbox: np.ndarray  # x1, y1, x2, y2 in frame pixels
    kps: np.ndarray  # 5 x 2
    score: float
    yaw: float
    pitch_ratio: float
    roll: float


@dataclass
class Frame:
    image: Any
    width: int
    height: int
    faces: list[Detection]


def decode_b64(image_b64: str) -> bytes:
    data = image_b64.split(",", 1)[1] if image_b64.startswith("data:") else image_b64
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise FaceInputError("Ảnh không hợp lệ.") from exc
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise FaceInputError("Ảnh rỗng hoặc quá lớn.")
    width, height = jpeg_size(raw)
    if not (0 < width <= MAX_DECODE_SIDE and 0 < height <= MAX_DECODE_SIDE):
        raise FaceInputError("Kích thước ảnh không hợp lệ.")
    return raw


def jpeg_size(raw: bytes) -> tuple[int, int]:
    """(width, height) from the JPEG frame header; only JPEG is accepted (no decompression bombs)."""
    if raw[:2] != b"\xff\xd8":
        raise FaceInputError("Chỉ nhận ảnh JPEG.")
    i = 2
    while i + 9 <= len(raw):
        if raw[i] != 0xFF:
            i += 1
            continue
        marker = raw[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
            i += 1 if marker == 0xFF else 2
            continue
        (length,) = struct.unpack(">H", raw[i + 2:i + 4])
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", raw[i + 5:i + 9])
            return width, height
        i += 2 + length
    raise FaceInputError("Ảnh JPEG không đọc được.")


class FaceEngine:
    def __init__(self, model_root: str, det_size: int = 320) -> None:
        self.model_root = model_root
        self.det_size = det_size
        self._app: Any = None
        self._lock = threading.Lock()
        self.provider = ""
        self.error = ""
        self._failed_at = 0.0

    def installed(self) -> bool:
        try:
            import cv2  # noqa: F401
            import insightface  # noqa: F401
            import onnxruntime  # noqa: F401
        except ImportError:
            return False
        return True

    @property
    def ready(self) -> bool:
        return self._app is not None

    def status(self) -> dict:
        return {"model": MODEL_PACK, "installed": self.installed(), "loaded": self._app is not None,
                "provider": self.provider, "error": self.error}

    def load(self, wait: bool = False) -> Any:
        """Requests pass wait=False: while another thread downloads/loads the model they get
        FaceUnavailable at once instead of tying up a worker thread."""
        if self._app is not None:
            return self._app
        if not wait and time.monotonic() - self._failed_at < RETRY_AFTER_FAILURE:
            raise FaceUnavailable(self.error)
        if not self._lock.acquire(blocking=wait):
            raise FaceUnavailable("Mô hình khuôn mặt đang được tải, vui lòng thử lại sau ít phút.")
        try:
            if self._app is not None:
                return self._app
            try:
                import onnxruntime
                from insightface.app import FaceAnalysis
            except ImportError as exc:
                self.error = "insightface/onnxruntime chưa được cài (pip install -r Reid/requirements.txt)."
                self._failed_at = time.monotonic()
                raise FaceUnavailable(self.error) from exc
            gpu = "CUDAExecutionProvider" in onnxruntime.get_available_providers()
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if gpu else ["CPUExecutionProvider"]
            try:
                app = FaceAnalysis(name=MODEL_PACK, root=self.model_root,
                                   allowed_modules=["detection", "recognition"], providers=providers)
                app.prepare(ctx_id=0 if gpu else -1, det_size=(self.det_size, self.det_size))
            except Exception as exc:  # noqa: BLE001 - download or ONNX errors all mean "unavailable"
                self.error = f"Không tải được mô hình {MODEL_PACK}: {exc}"[:300]
                self._failed_at = time.monotonic()
                raise FaceUnavailable(self.error) from exc
            # InsightFace keeps the 280 MB download next to the unpacked models.
            Path(self.model_root, "models", f"{MODEL_PACK}.zip").unlink(missing_ok=True)
            self.provider, self.error, self._app = providers[0], "", app
            return app
        finally:
            self._lock.release()

    def analyze(self, image_b64: str) -> Frame:
        import cv2

        app = self.load()
        image = cv2.imdecode(np.frombuffer(decode_b64(image_b64), np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise FaceInputError("Ảnh không đọc được.")
        h, w = image.shape[:2]
        if max(h, w) > MAX_SIDE:
            scale = MAX_SIDE / max(h, w)
            image = cv2.resize(image, (round(w * scale), round(h * scale)))
            h, w = image.shape[:2]
        bboxes, kpss = app.det_model.detect(image, max_num=0, metric="default")
        faces = []
        for bbox, kps in zip(bboxes, kpss if kpss is not None else []):
            yaw, pitch_ratio, roll = pose.head_pose(kps)
            faces.append(Detection(bbox=bbox[:4], kps=kps, score=float(bbox[4]),
                                   yaw=yaw, pitch_ratio=pitch_ratio, roll=roll))
        faces.sort(key=lambda d: (d.bbox[2] - d.bbox[0]) * (d.bbox[3] - d.bbox[1]), reverse=True)
        return Frame(image=image, width=w, height=h, faces=faces)

    def embed(self, frame: Frame, det: Detection) -> np.ndarray:
        from insightface.utils import face_align

        rec = self.load().models["recognition"]
        aligned = face_align.norm_crop(frame.image, landmark=det.kps, image_size=rec.input_size[0])
        vec = rec.get_feat(aligned).flatten().astype(np.float32)
        return vec / max(float(np.linalg.norm(vec)), 1e-12)

    def crop_jpeg(self, frame: Frame, det: Detection) -> bytes:
        import cv2
        from insightface.utils import face_align

        aligned = face_align.norm_crop(frame.image, landmark=det.kps, image_size=112)
        ok, buf = cv2.imencode(".jpg", aligned, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return buf.tobytes() if ok else b""
