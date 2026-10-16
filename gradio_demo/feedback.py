"""Feedback stored on this machine: one JSON object per line in feedback/feedback.jsonl
(override with BUOYUP_FEEDBACK_FILE). Each save appends and flushes to disk; the table re-reads the file
on every visit and on "Tải lại", so entries written by any visitor or edited by hand show up."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

FILE = Path(os.environ.get("BUOYUP_FEEDBACK_FILE") or Path(__file__).resolve().parent / "feedback" / "feedback.jsonl")
VN = timezone(timedelta(hours=7))
ROLES = ["Giám khảo / ban tổ chức", "Người bán", "Ngân hàng", "Thành viên đội", "Khác"]
SECTIONS = ["Chung", "Demo vòng vay", "Luồng mới so với bản trước", "BuoyUp nói dễ hiểu", "Tra cứu luật (RAG)",
            "Hỏi đáp (chatbot)"]
STARS = ["★★★★★ Rất tốt", "★★★★ Tốt", "★★★ Được", "★★ Chưa tốt", "★ Kém"]
COLUMNS = ["Thời gian", "Tên", "Vai trò", "Phần", "Đánh giá", "Nội dung"]
MAX_TEXT = 3000
_LOCK = threading.Lock()


def where() -> str:
    """The file's path for display, relative to the project when possible (no home folder on a public page)."""
    try:
        return str(FILE.relative_to(Path(__file__).resolve().parent.parent))
    except ValueError:
        return FILE.name


def save(name: str, role: str, section: str, stars: str | None, text: str, kind: str = "form") -> dict[str, Any]:
    """Append one entry. Raises ValueError when the text is empty."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Nội dung góp ý đang trống.")
    entry = {
        "id": uuid.uuid4().hex[:12],
        "time": datetime.now(VN).isoformat(timespec="seconds"),
        "name": (name or "").strip()[:80] or "Ẩn danh",
        "role": role if role in ROLES else "Khác",
        "section": section if section in SECTIONS else "Chung",
        "rating": 5 - STARS.index(stars) if stars in STARS else None,
        "text": text[:MAX_TEXT],
        "kind": kind,
    }
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _LOCK:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        with FILE.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
    return entry


def load() -> list[dict[str, Any]]:
    """Every entry in the file, newest first; a damaged line is skipped, not fatal."""
    if not FILE.exists():
        return []
    out = []
    with _LOCK:
        lines = FILE.read_text(encoding="utf-8").splitlines()
    for ln in lines:
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("text"):
            out.append(e)
    return sorted(out, key=lambda e: e.get("time", ""), reverse=True)


def rows(entries: list[dict[str, Any]]) -> list[list[Any]]:
    return [[e.get("time", "").replace("T", " ")[:16], e.get("name", ""), e.get("role", ""), e.get("section", ""),
             "★" * int(e["rating"]) if e.get("rating") else "", e.get("text", "")] for e in entries]


def summary(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return f"Chưa có góp ý nào. File lưu: `{where()}`"
    rated = [e["rating"] for e in entries if e.get("rating") and e.get("kind") != "chat_rating"]
    avg = f" · điểm trung bình **{sum(rated) / len(rated):.1f}/5** ({len(rated)} lượt chấm)" if rated else ""
    chat = [e for e in entries if e.get("kind") == "chat_rating"]
    if chat:
        up = sum(1 for e in chat if (e.get("rating") or 0) >= 3)
        avg += f" · chatbot 👍 {up} / 👎 {len(chat) - up}"
    by: dict[str, int] = {}
    for e in entries:
        by[e.get("section", "Chung")] = by.get(e.get("section", "Chung"), 0) + 1
    parts = " · ".join(f"{k}: {v}" for k, v in sorted(by.items(), key=lambda kv: -kv[1]))
    return (f"**{len(entries)} góp ý**{avg}. Theo phần: {parts}. Mới nhất lúc {entries[0]['time'][:16].replace('T', ' ')}."
            f"\n\nFile lưu: `{where()}`")
