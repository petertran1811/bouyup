"""Per-user face templates on disk: <data_dir>/<user_id>/{templates.npy, meta.json, crops/*.jpg}.

A template is one L2-normalised ArcFace embedding; a user has one per captured pose
(frontal + the eight head-turn segments). A user's score against a probe is the best
cosine similarity over their templates.
"""

from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


class FaceStore:
    def __init__(self, data_dir: str) -> None:
        self.root = Path(data_dir)
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()  # held across "is this face new?" + save
        self._cache: dict[str, np.ndarray] | None = None

    def _load_all(self) -> dict[str, np.ndarray]:
        if self._cache is None:
            cache: dict[str, np.ndarray] = {}
            if self.root.is_dir():
                for path in self.root.glob("*/templates.npy"):
                    if not path.parent.name.startswith("."):  # .tmp holds half-written saves
                        cache[path.parent.name] = np.load(path).astype(np.float32)
            self._cache = cache
        return self._cache

    def has(self, user_id: str) -> bool:
        with self._lock:
            return user_id in self._load_all()

    def count(self) -> int:
        with self._lock:
            return len(self._load_all())

    def owner_of(self, probes: np.ndarray, threshold: float,
                 is_live: Callable[[str], bool] = lambda _uid: True) -> str | None:
        """A live user any probe matches; folders of users that no longer exist are removed."""
        for probe in probes:
            for uid, score in self.search(probe):
                if score < threshold:
                    break
                if is_live(uid):
                    return uid
                self.delete(uid)  # left behind by a sign-up that never committed
        return None

    def save_if_unique(self, user_id: str, templates: np.ndarray, probes: np.ndarray, threshold: float,
                       meta: dict, crops: dict[str, bytes],
                       is_live: Callable[[str], bool] = lambda _uid: True) -> str | None:
        """Saves and returns None, or returns the existing owner of this face without saving."""
        with self._write_lock:
            owner = self.owner_of(probes, threshold, is_live)
            if owner is None:
                self.save(user_id, templates, meta, crops)
            return owner

    def save(self, user_id: str, templates: np.ndarray, meta: dict, crops: dict[str, bytes]) -> None:
        folder = self.root / user_id
        tmp = self.root / ".tmp" / user_id
        shutil.rmtree(tmp, ignore_errors=True)
        (tmp / "crops").mkdir(parents=True)
        np.save(tmp / "templates.npy", templates.astype(np.float32))
        meta = {**meta, "user_id": user_id, "templates": int(templates.shape[0]),
                "saved_at": datetime.now(timezone.utc).isoformat()}
        (tmp / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        for name, data in crops.items():
            if data:
                (tmp / "crops" / f"{name}.jpg").write_bytes(data)
        with self._lock:
            shutil.rmtree(folder, ignore_errors=True)
            tmp.rename(folder)
            self._load_all()[user_id] = templates.astype(np.float32)

    def delete(self, user_id: str) -> None:
        with self._lock:
            shutil.rmtree(self.root / user_id, ignore_errors=True)
            self._load_all().pop(user_id, None)

    def search(self, probe: np.ndarray, only: str | None = None) -> list[tuple[str, float]]:
        """[(user_id, score)] best first; ``only`` restricts the search to one user (1:1)."""
        with self._lock:
            items = list(self._load_all().items())
        if only is not None:
            items = [(uid, t) for uid, t in items if uid == only]
        scores = [(uid, float(np.max(t @ probe))) for uid, t in items if len(t)]
        return sorted(scores, key=lambda item: item[1], reverse=True)
