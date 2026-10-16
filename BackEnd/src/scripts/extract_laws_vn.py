"""Extract the Vietnamese law corpus (docs/agents/VN/*.docx) into ``app/core/laws/vn/corpus.json``
and ``manifest.json``, the same shape as the Chinese corpus.

Run again whenever a file in docs/agents/VN changes:

    cd BackEnd/src && ../.venv/bin/python scripts/extract_laws_vn.py [path/to/VN]

* Articles start at a line "Điều N." (N may carry a letter: 4a, 46b). A line only opens a new article
  when its number follows the previous one (same number + letter, or the next number), so a
  cross-reference at the start of a line stays inside its article. In a consolidated text (văn bản
  hợp nhất) the articles of the amending decrees printed after the last article are kept under
  ``#HN-k``.
* Appendices (Phụ lục) are read from the document body in order, table row by table row, one entry
  per row (``#PL4-12``); appendix paragraphs outside tables become one entry each.
* Footnote markers such as ``[16]`` are removed.
* Repeals known from the corpus itself are recorded per entry: Decree 173/2024 repeals parts of
  Decree 59/2006 from 15/02/2025 (``status: repealed``, ``repealed_on``).

Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

SRC = Path(__file__).resolve().parents[1]
DEFAULT_VN = SRC.parents[1] / "docs" / "agents" / "VN"
OUT = SRC / "app" / "core" / "laws" / "vn"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

SOURCES: dict[str, dict] = {
    "2022_909 + 910_14-2022-QH15 (Luật Phòng Chống Rửa Tiền)).docx": {
        "id": "PCRT-2022", "name": "Luật Phòng, chống rửa tiền 2022 (14/2022/QH15)", "eff": "2023-03-01", "expect": 66},
    "2026_42_143_2025_QH15 (Luật Đầu tư).docx": {
        "id": "DT-2025", "name": "Luật Đầu tư 2025 (143/2025/QH15)", "eff": "2026-03-01", "expect": 52,
        "eff_parts": {"7": "2026-07-01", "PL4": "2026-07-01"},
        "warn": ["Điều 7 và Phụ lục IV có hiệu lực từ 01/07/2026; khoản 3 Điều 50 từ 01/01/2026."]},
    "Nghi_dinh_173_2024_ND_CP.docx": {
        "id": "ND173-2024", "name": "Nghị định 173/2024/NĐ-CP (bãi bỏ một phần NĐ 59/2006)", "eff": "2025-02-15",
        "expect": 2},
    "Nghi_dinh_59_2006_ND_CP_toan_van_phu_luc.docx": {
        "id": "ND59-2006", "name": "Nghị định 59/2006/NĐ-CP (hàng hóa, dịch vụ cấm, hạn chế kinh doanh)",
        "eff": "2006-07-01", "expect": 11,
        "warn": ["Ngày hiệu lực: 15 ngày sau khi đăng Công báo (2006); ghi tạm 2006-07-01.",
                 "Nhiều phần đã bị bãi bỏ bởi NĐ 173/2024 từ 15/02/2025 (đánh dấu từng mục)."]},
    "Nghi_dinh_98_2020_VBHN_03_2025.docx": {
        "id": "ND98-2020", "name": "Nghị định 98/2020/NĐ-CP (xử phạt hành chính thương mại, hàng giả, hàng cấm; "
                                 "bản hợp nhất 03/2025)", "eff": "2020-10-15", "expect": 99,
        "warn": ["Văn bản hợp nhất: chú thích (điều nào được sửa bởi nghị định nào, và điều khoản thi hành của các nghị định sửa đổi) nằm ở mục #CT-n."]},
}
ND173_REPEALED_ON = "2025-02-15"


def _num(s: str) -> tuple[int, str]:
    m = re.match(r"(\d+)([a-zđ]?)", s)
    return int(m.group(1)), m.group(2)


def _follows(prev: tuple[int, str] | None, cur: tuple[int, str]) -> bool:
    if prev is None:
        return cur == (1, "")
    if cur[0] == prev[0]:
        return bool(cur[1]) and (not prev[1] or cur[1] > prev[1])
    return cur[0] == prev[0] + 1 and not cur[1]


def _text(el: ET.Element) -> str:
    return "".join(t.text or "" for t in el.iter(W + "t")).strip()


def _clean(t: str) -> str:
    return re.sub(r"\[\d+\]", "", t).strip()


def body_items(path: Path) -> list[tuple[str, object]]:
    """Body in order: ("p", text) or ("tr", [cell texts])."""
    root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    body = root.find(W + "body")
    out: list[tuple[str, object]] = []
    for el in body:
        if el.tag == W + "p":
            t = _text(el)
            if t:
                out.append(("p", t))
        elif el.tag == W + "tbl":
            for tr in el.iter(W + "tr"):
                cells = [_text(tc) for tc in tr.findall(W + "tc")]
                if any(cells):
                    out.append(("tr", cells))
    return out


_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}


def extract(path: Path, meta: dict) -> tuple[dict[str, dict], list[str]]:
    lid, name = meta["id"], meta["name"]
    items = body_items(path)
    entries: dict[str, dict] = {}
    warns: list[str] = list(meta.get("warn", []))
    cur_id, cur_lines, prev, tail_k = None, [], None, 0
    notes = False  # after the authentication block of a consolidated text: footnotes [n]
    appendix, row_k, header_skipped = None, 0, False

    def flush() -> None:
        if cur_id and cur_lines:
            entries[cur_id] = {"id": cur_id, "law_id": lid, "law": "", "text": "\n".join(cur_lines).strip()}

    for kind, val in items:
        if kind == "p":
            raw = val  # type: ignore[assignment]
            t = _clean(raw)
            if prev and not notes and (raw.startswith("XÁC THỰC VĂN BẢN HỢP NHẤT") or re.match(r"^BỘ .{0,40}_{3,}", raw)):
                flush(); cur_id, cur_lines, notes = None, [], True
                continue
            if notes:
                m_note = re.match(r"^\[(\d+)\]\s*(.*)", raw)
                if m_note:
                    flush()
                    cur_id, cur_lines = f"{lid}#CT-{m_note.group(1)}", [m_note.group(2)]
                elif cur_id:
                    cur_lines.append(t)
                continue
            m_pl = re.match(r"^(PHỤ LỤC|Phụ lục)\s*([IVX]+)", t)
            if m_pl:
                flush(); cur_id, cur_lines = None, []
                appendix, row_k, header_skipped = _ROMAN.get(m_pl.group(2), 0), 0, False
                pid = f"{lid}#PL{appendix}"
                entries[pid] = {"id": pid, "law_id": lid, "law": "", "text": t}
                continue
            m = re.match(r"^Điều\s+(\d+[a-zđ]?)[\.\s]", t + " ")
            if m and appendix is None:
                n = _num(m.group(1))
                if _follows(prev, n) and (prev is None or prev[0] < 200):
                    flush(); prev = n
                    cur_id, cur_lines = f"{lid}#{m.group(1)}", [t]
                    continue
                if prev and n[0] <= prev[0] and len(entries) >= meta.get("expect", 0) * 0.9:
                    flush(); tail_k += 1   # an amending decree's own article after the last one
                    cur_id, cur_lines = f"{lid}#HN-{tail_k}", [t]
                    continue
            if appendix is not None:
                row_k += 1
                rid = f"{lid}#PL{appendix}-{row_k}"
                entries[rid] = {"id": rid, "law_id": lid, "law": "", "text": t}
                continue
            if cur_id:
                cur_lines.append(t)
        else:
            cells = [c for c in val if c]  # type: ignore[union-attr]
            if appendix is None:
                if cur_id:
                    cur_lines.append(" | ".join(cells))
                continue
            if not header_skipped and any(c.upper() in ("STT", "TT") for c in cells):
                header_skipped = True
                continue
            row_k += 1
            rid = f"{lid}#PL{appendix}-{row_k}"
            entries[rid] = {"id": rid, "law_id": lid, "law": "", "text": " | ".join(cells)}
    flush()

    arts = [k for k in entries if "#PL" not in k and "#HN" not in k and "#CT" not in k]
    if meta.get("expect") and len(arts) != meta["expect"]:
        warns.append(f"Số điều trích được {len(arts)} khác số dự kiến {meta['expect']}.")
    for k, e in entries.items():
        tag = k.split("#", 1)[1]
        e["law"] = f"{name}, " + (f"Điều {tag}" if tag[0].isdigit() else
                                   f"Phụ lục {tag[2:].replace('-', ', dòng ')}" if tag.startswith("PL") else
                                   f"chú thích hợp nhất [{tag[3:]}]" if tag.startswith("CT") else
                                   f"điều khoản của văn bản sửa đổi {tag[3:]}")
        e["effective"] = meta["eff"]
        parts = meta.get("eff_parts", {})
        if tag in parts:
            e["effective"] = parts[tag]
        elif tag.startswith("PL4") and "PL4" in parts:
            e["effective"] = parts["PL4"]
        e["status"] = "in_force"
        e["jurisdiction"] = "VN"
    if lid == "ND59-2006":
        _mark_nd59_repeals(entries)
    return entries, warns


def _mark_nd59_repeals(entries: dict[str, dict]) -> None:
    """Decree 173/2024 Art. 1(2): Articles 6, 7, 8; points b, c of clause 1 Art. 4 (the article stays,
    partly repealed); Appendix I part A points 1–12, 14, 17, 18 and all of part B; Appendices II and III."""
    def rep(e: dict, partly: bool = False) -> None:
        e["status"] = "partly_repealed" if partly else "repealed"
        e["repealed_on"] = ND173_REPEALED_ON
        e["repealed_by"] = "ND173-2024#1"

    for k, e in entries.items():
        tag = k.split("#", 1)[1]
        if tag in ("6", "7", "8"):
            rep(e)
        elif tag == "4":
            rep(e, partly=True)
        elif tag.startswith(("PL2", "PL3")):
            rep(e)
    # Appendix I: rows are "number | goods | legal basis | authority"; part B (services) follows part A.
    in_b = False
    for k, e in sorted(((k, e) for k, e in entries.items() if k.split("#", 1)[1].startswith("PL1-")),
                       key=lambda kv: int(kv[0].rsplit("-", 1)[1])):
        first = e["text"].split(" | ")[0].strip()
        if first == "B":
            in_b = True
        if in_b:
            rep(e)
        elif first.isdigit() and int(first) not in (13, 15, 16):
            rep(e)


def main(argv: list[str]) -> None:
    vn = Path(argv[1]) if len(argv) > 1 else DEFAULT_VN
    corpus: dict[str, dict] = {}
    sources = []
    for fname, meta in SOURCES.items():
        path = vn / fname
        if not path.exists():
            sources.append({"file": fname, "missing": True})
            continue
        entries, warns = extract(path, meta)
        corpus.update(entries)
        sources.append({"file": fname, "law_id": meta["id"], "name": meta["name"], "effective": meta["eff"],
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "entries": len(entries),
                        "articles": len([k for k in entries if "#PL" not in k and "#HN" not in k and "#CT" not in k]),
                        "warnings": warns})
    OUT.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(corpus, ensure_ascii=False, sort_keys=True, indent=1)
    (OUT / "corpus.json").write_text(blob, encoding="utf-8")
    manifest = {"extracted": date.today().isoformat(), "extractor": "scripts/extract_laws_vn.py",
                "jurisdiction": "VN", "corpus_hash": "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest(),
                "entries": len(corpus), "sources": sources}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in sources:
        print(s.get("law_id"), s.get("entries"), s.get("articles"), "|", "; ".join(s.get("warnings") or []))
    print("total", len(corpus), manifest["corpus_hash"][:23])


if __name__ == "__main__":
    main(sys.argv)
