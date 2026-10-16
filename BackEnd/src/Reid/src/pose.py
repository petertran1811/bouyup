"""Head pose from the five SCRFD landmarks (eyes, nose tip, mouth corners).

Cheaper than buffalo_l's 1k3d68 model and good enough to guide a head turn. Fitted
against 1k3d68's pose on InsightFace's sample images (yaw r=0.99, pitch r=0.96):

* yaw   ≈ atan(nose offset / eye distance / 0.37); positive = the person turns to
  THEIR left (nose moves right in the raw camera frame, left in a mirrored selfie view).
* pitch ≈ -62° × change in (eye→nose) / (eye→mouth); only the change from the person's
  own frontal baseline is meaningful, since the ratio differs between faces.

The landmarks are de-rotated around the eye line first, so head roll does not leak in.
"""

from __future__ import annotations

import math

import numpy as np

YAW_SCALE = 0.37
PITCH_DEG_PER_RATIO = -62.0

SEGMENTS = 8  # 0 = screen right, counter-clockwise: 2 = up, 4 = left, 6 = down
# A head turn fills a segment once it reaches this far from frontal (an ellipse).
SEGMENT_YAW_DEG = 20.0
SEGMENT_PITCH_DEG = 13.0


def head_pose(kps: np.ndarray) -> tuple[float, float, float]:
    """Returns (yaw_deg, pitch_ratio, roll_deg) for one face's 5x2 landmarks."""
    k = np.asarray(kps, dtype=np.float64).reshape(5, 2)
    eye_vec = k[1] - k[0]
    roll = math.atan2(eye_vec[1], eye_vec[0])
    c, s = math.cos(-roll), math.sin(-roll)
    q = (k - k[:2].mean(axis=0)) @ np.array([[c, -s], [s, c]]).T
    eye_dist = max(q[1, 0] - q[0, 0], 1e-6)
    eye_mid, mouth_mid = q[:2].mean(axis=0), q[3:].mean(axis=0)
    yaw = math.degrees(math.atan((q[2, 0] - eye_mid[0]) / eye_dist / YAW_SCALE))
    pitch_ratio = (q[2, 1] - eye_mid[1]) / max(mouth_mid[1] - eye_mid[1], 1e-6)
    return yaw, float(pitch_ratio), math.degrees(roll)


def pitch_delta(pitch_ratio: float, baseline_ratio: float) -> float:
    """Degrees up (positive) or down (negative) from the person's frontal pose."""
    return PITCH_DEG_PER_RATIO * (pitch_ratio - baseline_ratio)


def segment(yaw: float, pitch_up: float) -> tuple[int, float]:
    """(segment index, reach) in a mirrored selfie view; reach >= 1 means far enough."""
    dx = -yaw / SEGMENT_YAW_DEG  # turning to one's left moves the face left on the mirrored screen
    dy = pitch_up / SEGMENT_PITCH_DEG
    angle = math.atan2(dy, dx)
    index = int(round(angle / (2 * math.pi / SEGMENTS))) % SEGMENTS
    return index, math.hypot(dx, dy)
