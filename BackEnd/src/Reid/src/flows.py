"""Frame-by-frame state machines for face enrollment (sign-up) and face login.

Both are driven by the browser posting webcam frames one at a time; every call returns
what the UI should show next. They are engine-agnostic: the caller passes the analysed
frame plus ``embed`` / ``crop`` callables, so ArcFace only runs on frames that are kept.

Enrollment: three frontal frames (identity + pitch baseline), then the user turns their
head in a circle until all eight directions are captured: nine templates in all.

Login: identify on frontal frames (1:N, or 1:1 when an email is given), then a random
turn challenge (left or right) with the same identity, so a still photo cannot pass.
"""

from __future__ import annotations

import math
import secrets
import threading
import time
from collections.abc import Callable
from typing import Generic, TypeVar

import numpy as np

from Reid.src import pose
from Reid.src.engine import Detection, Frame

CENTER_FRAMES = 3
FRONTAL_YAW = 12.0
FRONTAL_ROLL = 18.0
MIN_FACE_FRAC, MAX_FACE_FRAC = 0.16, 0.8
MIN_DET_SCORE = 0.6
SAME_PERSON_FRONTAL = 0.5  # frontal frames of one enrollment against each other
SAME_PERSON_TURNED = 0.3  # a turned head against the frontal mean (profiles score lower)
ENROLL_MAX_FRAMES = 500
LOGIN_MAX_FRAMES = 90
LOGIN_MAX_MISSES = 8
LOGIN_TURN_FRAMES = 45
LOGIN_TURN_YAW = 20.0
LOGIN_PARTIAL_YAW = 6.0  # the turn must be seen part-way (6-20 degrees) before it counts
MAX_BOX_JUMP = 0.2  # face centre may move at most this much (frame fraction) between frames
LOGIN_MATCH_HITS = 2
MATCH_MARGIN = 0.05  # 1:N: best user must beat the runner-up by this much

DIRECTIONS = ("sang phải", "lên trên bên phải", "lên trên", "lên trên bên trái",
              "sang trái", "xuống dưới bên trái", "xuống dưới", "xuống dưới bên phải")

Embed = Callable[[Detection], np.ndarray]
Search = Callable[[np.ndarray, "str | None"], list[tuple[str, float]]]


def _face_box(frame: Frame, det: Detection) -> list[float]:
    x1, y1, x2, y2 = (float(v) for v in det.bbox)
    return [round(x1 / frame.width, 4), round(y1 / frame.height, 4),
            round((x2 - x1) / frame.width, 4), round((y2 - y1) / frame.height, 4)]


def quality(frame: Frame) -> tuple[Detection | None, str, str]:
    """(the face to use or None, hint code, Vietnamese message)."""
    if not frame.faces:
        return None, "NO_FACE", "Chưa thấy khuôn mặt. Hãy nhìn vào camera."
    det = frame.faces[0]
    area = lambda d: (d.bbox[2] - d.bbox[0]) * (d.bbox[3] - d.bbox[1])  # noqa: E731
    if len(frame.faces) > 1 and area(frame.faces[1]) > 0.3 * area(det):
        return None, "MULTIPLE_FACES", "Chỉ một người trong khung hình."
    frac = (det.bbox[2] - det.bbox[0]) / frame.width
    if frac < MIN_FACE_FRAC:
        return None, "TOO_FAR", "Đưa mặt lại gần camera hơn."
    if frac > MAX_FACE_FRAC:
        return None, "TOO_CLOSE", "Lùi ra xa camera một chút."
    cx = (det.bbox[0] + det.bbox[2]) / 2 / frame.width
    cy = (det.bbox[1] + det.bbox[3]) / 2 / frame.height
    if not (0.2 < cx < 0.8 and 0.15 < cy < 0.85):
        return None, "OFF_CENTER", "Đưa khuôn mặt vào giữa khung tròn."
    if det.score < MIN_DET_SCORE:
        return None, "LOW_QUALITY", "Ảnh chưa rõ. Tìm chỗ đủ sáng và giữ yên camera."
    return det, "OK", ""


class _Flow:
    def __init__(self) -> None:
        self.id = secrets.token_urlsafe(24)
        self.created = time.monotonic()
        self.lock = threading.Lock()
        self.frames = 0
        self.context: dict = {}  # caller's own data (e.g. the rate-limit row to clear on success)


class Enrollment(_Flow):
    def __init__(self) -> None:
        super().__init__()
        self.center: list[np.ndarray] = []
        self.center_ratios: list[float] = []
        self.segments: list[np.ndarray | None] = [None] * pose.SEGMENTS
        self.crops: dict[str, bytes] = {}

    @property
    def done(self) -> bool:
        return len(self.center) >= CENTER_FRAMES and all(s is not None for s in self.segments)

    def templates(self) -> np.ndarray:
        return np.stack(self.center + [s for s in self.segments if s is not None])

    def _center_mean(self) -> np.ndarray:
        mean = np.mean(self.center, axis=0)
        return mean / max(float(np.linalg.norm(mean)), 1e-12)

    def _next_segment(self, current: int | None) -> int | None:
        missing = [i for i, s in enumerate(self.segments) if s is None]
        if not missing:
            return None
        if current is None:
            return missing[0]
        return min(missing, key=lambda i: min((i - current) % pose.SEGMENTS, (current - i) % pose.SEGMENTS))

    def state(self, hint: str, message: str, face: list[float] | None = None,
              current: int | None = None) -> dict:
        filled = sum(s is not None for s in self.segments)
        nxt = self._next_segment(current) if len(self.center) >= CENTER_FRAMES else None
        if hint == "OK" and not message:
            if self.done:
                message = "Hoàn tất. Đã ghi nhận khuôn mặt của bạn."
            elif len(self.center) < CENTER_FRAMES:
                message = "Nhìn thẳng vào camera và giữ yên."
            else:
                message = f"Xoay đầu chậm theo vòng tròn: {DIRECTIONS[nxt]}." if nxt is not None else ""
        return {
            "stage": "done" if self.done else ("center" if len(self.center) < CENTER_FRAMES else "turn"),
            "hint": hint, "message": message, "face": face,
            "center": len(self.center), "center_needed": CENTER_FRAMES,
            "segments": [s is not None for s in self.segments], "next_segment": nxt,
            "progress": round((min(len(self.center), CENTER_FRAMES) + filled) / (CENTER_FRAMES + pose.SEGMENTS), 3),
            "done": self.done,
        }

    def feed(self, frame: Frame, embed: Embed, crop: Callable[[Detection], bytes]) -> dict:
        self.frames += 1
        if self.done:
            return self.state("OK", "")
        det, hint, message = quality(frame)
        if det is None:
            return self.state(hint, message)
        box = _face_box(frame, det)
        if len(self.center) < CENTER_FRAMES:
            if abs(det.yaw) > FRONTAL_YAW or abs(det.roll) > FRONTAL_ROLL:
                return self.state("LOOK_STRAIGHT", "Nhìn thẳng vào camera, giữ đầu thẳng.", box)
            vec = embed(det)
            if self.center and float(vec @ self._center_mean()) < SAME_PERSON_FRONTAL:
                self.center, self.center_ratios = [], []  # someone else stepped in: start over
                return self.state("FACE_CHANGED", "Khuôn mặt thay đổi, bắt đầu lại.", box)
            self.crops[f"center_{len(self.center)}"] = crop(det)
            self.center.append(vec)
            self.center_ratios.append(det.pitch_ratio)
            return self.state("OK", "", box)
        baseline = float(np.median(self.center_ratios))
        index, reach = pose.segment(det.yaw, pose.pitch_delta(det.pitch_ratio, baseline))
        if reach < 1.0:
            return self.state("OK", "", box, current=index if reach > 0.5 else None)
        if self.segments[index] is None:
            vec = embed(det)
            if float(vec @ self._center_mean()) < SAME_PERSON_TURNED:
                return self.state("FACE_CHANGED", "Không khớp khuôn mặt ban đầu. Chỉ một người xoay đầu.", box)
            self.segments[index] = vec
            self.crops[f"turn_{index}"] = crop(det)
        return self.state("OK", "", box, current=index)


class FaceLogin(_Flow):
    def __init__(self, only_user: str | None = None, challenge: str | None = None) -> None:
        super().__init__()
        self.only_user = only_user
        self.challenge = challenge or secrets.choice(("left", "right"))
        self.stage = "frontal"  # frontal → turn → done | failed
        self.candidate: str | None = None
        self.hits = 0
        self.misses = 0
        self.turn_frames = 0
        self.saw_partial = False
        self.last_box: list[float] | None = None
        self.score = 0.0
        self.user_id: str | None = None
        self.failure = ""

    def state(self, hint: str, message: str, face: list[float] | None = None) -> dict:
        return {"stage": self.stage, "hint": hint, "message": message, "face": face,
                "challenge": self.challenge if self.stage in ("turn", "done") else None,
                "done": self.stage == "done", "failed": self.stage == "failed"}

    def _fail(self, code: str, message: str) -> dict:
        self.stage, self.failure = "failed", code
        return self.state(code, message)

    def feed(self, frame: Frame, embed: Embed, search: Search, threshold: float) -> dict:
        self.frames += 1
        if self.stage in ("done", "failed"):
            return self.state(self.failure or "OK", "")
        if self.frames > LOGIN_MAX_FRAMES:
            return self._fail("TIMEOUT", "Hết thời gian xác thực. Vui lòng thử lại.")
        det, hint, message = quality(frame)
        box = _face_box(frame, det) if det is not None else None
        jumped = box is not None and self.last_box is not None and math.hypot(
            box[0] + box[2] / 2 - self.last_box[0] - self.last_box[2] / 2,
            box[1] + box[3] / 2 - self.last_box[1] - self.last_box[3] / 2) > MAX_BOX_JUMP
        self.last_box = box
        if det is None or jumped:  # identification and the turn must come from one continuous face
            self.hits, self.candidate, self.saw_partial = 0, None, False
            if self.stage == "turn":
                self.stage = "frontal"  # identify again before the turn can count
            return self.state(hint, message) if det is None else self.state("SEARCHING", "Giữ khuôn mặt trong khung.", box)
        side = "trái" if self.challenge == "left" else "phải"
        if self.stage == "frontal":
            if abs(det.yaw) > FRONTAL_YAW:
                self.hits, self.candidate = 0, None
                return self.state("LOOK_STRAIGHT", "Nhìn thẳng vào camera.", box)
            ranked = search(embed(det), self.only_user)
            best = ranked[0] if ranked else None
            runner_up = ranked[1][1] if len(ranked) > 1 else -1.0
            if best is None or best[1] < threshold or best[1] - runner_up < MATCH_MARGIN:
                self.misses += 1
                self.hits, self.candidate = 0, None
                if self.misses >= LOGIN_MAX_MISSES:
                    return self._fail("NOT_RECOGNIZED", "Không nhận ra khuôn mặt đã đăng ký.")
                return self.state("SEARCHING", "Đang nhận diện… nhìn thẳng vào camera.", box)
            self.hits = self.hits + 1 if best[0] == self.candidate else 1
            self.candidate, self.score = best[0], max(self.score, best[1])
            if self.hits >= LOGIN_MATCH_HITS:
                self.stage = "turn"
                return self.state("TURN", f"Đã nhận diện. Quay mặt sang {side} để xác nhận người thật.", box)
            return self.state("SEARCHING", "Đang nhận diện… giữ yên.", box)
        # turn: liveness challenge with the same identity
        self.turn_frames += 1
        if self.turn_frames > LOGIN_TURN_FRAMES:
            return self._fail("LIVENESS_FAILED", "Chưa thấy bạn quay mặt theo hướng dẫn. Vui lòng thử lại.")
        toward = det.yaw if self.challenge == "left" else -det.yaw
        if toward < LOGIN_TURN_YAW:
            self.saw_partial = self.saw_partial or toward >= LOGIN_PARTIAL_YAW
            return self.state("TURN", f"Quay mặt sang {side}.", box)
        if not self.saw_partial:  # jumped straight to a profile: a swapped picture, or a very fast turn
            return self.state("TURN", f"Quay mặt sang {side} chậm hơn.", box)
        ranked = search(embed(det), self.candidate)
        if not ranked or ranked[0][1] < threshold - 0.1:
            return self.state("TURN", f"Chưa khớp, quay mặt sang {side} chậm hơn.", box)
        self.stage, self.user_id = "done", self.candidate
        return self.state("OK", "Xác thực khuôn mặt thành công.", box)


T = TypeVar("T", bound=_Flow)


class Registry(Generic[T]):
    """In-process flows with a TTL (the app runs one worker, see Dockerfile)."""

    def __init__(self, ttl_seconds: float, max_items: int = 500) -> None:
        self.ttl, self.max_items = ttl_seconds, max_items
        self._items: dict[str, T] = {}
        self._lock = threading.Lock()

    def _sweep(self) -> None:
        now = time.monotonic()
        for key in [k for k, v in self._items.items() if now - v.created > self.ttl]:
            del self._items[key]

    def add(self, flow: T) -> T:
        with self._lock:
            self._sweep()
            if len(self._items) >= self.max_items:
                del self._items[min(self._items, key=lambda k: self._items[k].created)]
            self._items[flow.id] = flow
        return flow

    def get(self, flow_id: str) -> T | None:
        with self._lock:
            self._sweep()
            return self._items.get(flow_id)

    def pop(self, flow_id: str) -> T | None:
        with self._lock:
            self._sweep()
            return self._items.pop(flow_id, None)
