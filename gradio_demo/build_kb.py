"""Build the chatbot's knowledge base (knowledge/kb.json) from the team's documents.

Sources, in order of trust (``weight`` raises a source's rank in the chatbot's search):
- knowledge/faq.md: questions and answers written for the chatbot;
- pages/de-hieu.html, part 1 (the product in plain words; part 2 is the team's own competition review, left out);
- ../LOAN_CIRCLE_CHANGES.md §1, §2, §4; ../HANDOVER.md §1 and §15.2–15.5;
- ../docs/agents/agent*.md: the loan-circle update note and the summary (§0) of each agent.

Server addresses and the demo password are removed. kb.json is bundled, so the app does not need the
repository documents at run time (a Hugging Face Space ships only gradio_demo/).

    python build_kb.py
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "knowledge" / "kb.json"

_SECRET = [(re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<máy chủ>"),
           (re.compile(r"BuoyUp@2026"), "<mật khẩu demo>")]


def clean(text: str) -> str:
    for pat, rep in _SECRET:
        text = pat.sub(rep, text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def md_sections(text: str, level: int) -> list[tuple[str, str]]:
    """(heading, body) for every heading of exactly ``level`` hashes; code fences kept in the body."""
    out, title, buf, fence = [], None, [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"^(#{1,6})\s+(.*)$", line)
        if m and len(m.group(1)) <= level:
            if title is not None:
                out.append((title, "\n".join(buf).strip()))
            title, buf = (m.group(2).strip(), []) if len(m.group(1)) == level else (None, [])
            continue
        if title is not None:
            buf.append(line)
    if title is not None:
        out.append((title, "\n".join(buf).strip()))
    return out


def faq() -> list[dict]:
    text = (HERE / "knowledge" / "faq.md").read_text(encoding="utf-8")
    return [{"title": q, "source": "Hỏi đáp", "text": a, "weight": 1.5} for q, a in md_sections(text, 2) if a]


def easy_page() -> list[dict]:
    s = (HERE / "pages" / "de-hieu.html").read_text(encoding="utf-8")
    s = re.sub(r"(?s)<(script|style|svg)[^>]*>.*?</\1>", "", s)
    s = s.split("Phần 2 · Đối chiếu")[0]  # part 2 is the team's own review of the entry
    s = re.sub(r"<(br|/p|/li|/h\d|/div|/tr|/summary)[^>]*>", "\n", s)
    s = re.sub(r"<(td|th)[^>]*>", " | ", s)
    s = re.sub(r"<(h[23])[^>]*>", r"\n@@\1 ", s)
    t = html.unescape(re.sub(r"<[^>]+>", "", s))
    t = "\n".join(ln.strip() for ln in t.splitlines() if ln.strip())
    out = []
    for part in t.split("@@h2 ")[1:]:
        title, _, body = part.partition("\n")
        body = re.sub(r"@@h3 ", "\n", body)
        out.append({"title": title.strip(), "source": "BuoyUp nói dễ hiểu", "text": body.strip(), "weight": 1.25})
    return out


def changes() -> list[dict]:
    text = (ROOT / "LOAN_CIRCLE_CHANGES.md").read_text(encoding="utf-8")
    src = "Nhật ký chuyển sang vòng vay"
    out = []
    for title, body in md_sections(text, 2):
        if title.startswith("1."):
            for row in body.splitlines():
                cells = [c.strip() for c in row.strip("|").split("|")]
                if len(cells) == 3 and not set(cells[0]) <= {"-"} and cells[0] != "Điểm":
                    out.append({"title": f"Quyết định của đội: {cells[0]}", "source": src,
                                "text": f"{cells[1]}\n(Trong code: {cells[2]})", "weight": 1.1})
        elif title.startswith("2."):
            for para in re.split(r"\n\s*\n", body):
                m = re.match(r"\*\*(.+?)\.\*\*\s*(.*)", para.strip(), re.S)
                if m:
                    out.append({"title": m.group(1).capitalize(), "source": src, "text": m.group(2), "weight": 1.1})
        elif title.startswith("4."):
            out.append({"title": "Các tham số đội tự đặt", "source": src, "text": body, "weight": 1.0})
    return out


def handover() -> list[dict]:
    text = (ROOT / "HANDOVER.md").read_text(encoding="utf-8")
    src = "Tài liệu bàn giao (HANDOVER)"
    out = []
    for title, body in md_sections(text, 2):
        if title.startswith("1."):
            for para in re.split(r"\n\s*\n", body):
                para = para.strip()
                if para and para != "---":
                    head = "Năm AI agent và mã nguồn" if para.startswith("| Agent") else \
                        "Vai trò người dùng và trang" if para.startswith("| Vai trò") else "Hệ thống BuoyUp là gì"
                    out.append({"title": head, "source": src, "text": para, "weight": 1.0})
    for title, body in md_sections(text, 3):
        if title[:4] in ("15.2", "15.3", "15.4", "15.5"):
            out.append({"title": title.split(" ", 1)[1], "source": src, "text": body.replace("\n---", ""), "weight": 1.0})
    return out


def agents() -> list[dict]:
    out = []
    for f in sorted((ROOT / "docs" / "agents").glob("agent*.md")):
        text = f.read_text(encoding="utf-8")
        name = text.splitlines()[0].lstrip("# ").strip()
        note = re.search(r"> \*\*Cập nhật[^\n]*", text)
        summary = dict(md_sections(text, 2)).get("0. Tóm tắt", "")
        body = ((note.group(0).lstrip("> ") + "\n\n") if note else "") + summary
        out.append({"title": f"{name} (đặc tả)", "source": f"docs/agents/{f.name}", "text": body, "weight": 0.9})
    return out


def build() -> dict:
    entries = [e for e in faq() + easy_page() + changes() + handover() + agents() if len(e["text"]) >= 80]
    for i, e in enumerate(entries):
        e["id"] = f"KB{i:03d}"
        e["text"] = clean(e["text"])
    digest = hashlib.sha256(json.dumps(entries, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {"hash": "sha256:" + digest, "entries": entries}


if __name__ == "__main__":
    kb = build()
    OUT.write_text(json.dumps(kb, ensure_ascii=False, indent=1), encoding="utf-8")
    by: dict[str, int] = {}
    for e in kb["entries"]:
        by[e["source"]] = by.get(e["source"], 0) + 1
    print(f"{len(kb['entries'])} mục → {OUT.relative_to(HERE)}")
    for k, v in by.items():
        print(f"  {v:3d}  {k}")
