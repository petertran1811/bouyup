"""Layer 1 of Agent 3 §3.5: extract the TQ law corpus (docs/agents/TQ/*.docx) into
``app/core/laws/corpus.json`` and ``manifest.json``.

Run again whenever a file in docs/agents/TQ changes:

    cd BackEnd/src && ../.venv/bin/python scripts/extract_laws.py [path/to/TQ]

* Laws and measures are split per article (``第X条`` at the start of a line). A line only
  opens a new article when its number is exactly one more than the previous one, so a
  cross-reference such as "第三十一条、第三十二条的规定予以处罚" that a PDF conversion put at
  the start of a line is kept inside its article. Lines broken mid-sentence are joined; a
  line break is kept only after a sentence end.
* The market-access negative list (two columns mixed by the PDF conversion) is kept as one
  full text, only to check quotes against.
* The team's goods list is read table by table, row by row.
* The manifest lists each source file with its SHA-256, the article count against the
  expected one, the effective date and warnings; ``corpus_hash`` (SHA-256 of the corpus) is
  anchored on the chain at start-up (``seed.ensure_law_corpus``).

Standard library only (zipfile + ElementTree), so the image needs nothing extra.
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

SRC = Path(__file__).resolve().parents[1]  # BackEnd/src
DEFAULT_TQ = SRC.parents[1] / "docs" / "agents" / "TQ"
OUT = SRC / "app" / "core" / "laws"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# file → law id, Vietnamese name, effective date (None: not stated), mode, expected article count
SOURCES: dict[str, dict] = {
    "China_Anti_Money_Laundering_Law_2024.docx": {
        "id": "AML-2024", "name": "Luật Chống rửa tiền 2024", "eff": "2025-01-01", "mode": "articles", "expect": 65,
        "warn": ["Ngày hiệu lực cần đối chiếu nguồn chính thức (README TQ)."]},
    "China_Large_Suspicious_Transactions.docx": {
        "id": "PBOC-LST-2016", "name": "Quy định báo cáo giao dịch lớn và đáng ngờ", "eff": "2017-07-01",
        "mode": "articles", "expect": 30, "warn": ["Bản 2016; kiểm các lần sửa đổi sau (README TQ)."]},
    "China_E_Cigarette_Measures_2022.docx": {
        "id": "ECIG-2022", "name": "Quy định quản lý thuốc lá điện tử", "eff": "2022-05-01", "mode": "articles",
        "expect": 45},
    "China_Product_Quality_Law_2018.docx": {
        "id": "PQL-2018", "name": "Luật Chất lượng sản phẩm", "eff": "2018-12-29", "mode": "articles", "expect": 74},
    "China_Trademark_Law_2026.docx": {
        "id": "TM-2026", "name": "Luật Nhãn hiệu 2026", "eff": "2027-01-01", "mode": "articles", "expect": 87,
        "warn": ["Chưa có hiệu lực trước 2027-01-01."]},
    "China_Trademark_Law_2019.docx": {
        "id": "TM-2019", "name": "Luật Nhãn hiệu 2019", "eff": "2019-11-01", "mode": "articles", "expect": 73},
    "China_Market_Access_Negative_List_2025.docx": {
        "id": "NEG-2025", "name": "Danh sách tiêu cực tiếp cận thị trường 2025", "eff": None, "mode": "fulltext",
        "warn": ["Chuyển từ PDF hai cột, lẫn cột: chỉ dùng để kiểm câu trích trên toàn văn; mục đang dùng cần người "
                 "đối chiếu bản PDF gốc.", "Văn bản không ghi ngày hiệu lực."]},
    "China_Prohibited_and_Restricted_Goods_List_2026.docx": {
        "id": "GOODS-2026", "name": "Danh mục hàng cấm và hạn chế (bản tổng hợp của đội)", "eff": None,
        "mode": "table", "warn": ["Bản tổng hợp của đội, không phải danh mục chính thức."]},
    "China_Personal_Information_Protection_Law_2021.docx": {
        "id": "PIPL-2021", "name": "Luật Bảo vệ thông tin cá nhân", "eff": "2021-11-01", "mode": "articles", "expect": 74},
    "China_E_Commerce_Law_2018.docx": {
        "id": "ECOM-2018", "name": "Luật Thương mại điện tử", "eff": "2019-01-01", "mode": "articles", "expect": 89},
    "China_Online_Trading_Supervision_Measures_2021.docx": {
        "id": "NETTRADE-2021", "name": "Quy định giám sát giao dịch trực tuyến", "eff": "2021-05-01",
        "mode": "articles", "expect": 56},
    "China_Credit_Reporting_Business_Measures_2021.docx": {
        "id": "CREDIT-2021", "name": "Quy định hoạt động thông tin tín dụng", "eff": "2022-01-01", "mode": "articles",
        "expect": 53},
    "China_Commercial_Bank_Internet_Loan_Measures_2020.docx": {
        "id": "NETLOAN-2020", "name": "Quy định cho vay qua internet", "eff": "2020-07-12", "mode": "articles",
        "expect": 70},
    "China_Working_Capital_Loan_Measures_2024.docx": {
        "id": "WCLOAN-2024", "name": "Quy định cho vay vốn lưu động", "eff": "2024-07-01", "mode": "articles",
        "expect": 51},
}

_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_UNITS = {"十": 10, "百": 100, "千": 1000}
_ARTICLE = re.compile(r"^\s*第([零〇一二两三四五六七八九十百千]+)条")
_CHAPTER = re.compile(r"^\s*第[零〇一二三四五六七八九十百]+章")
_APPENDIX = re.compile(r"^\s*(附件|附录)")
_SENTENCE_END = ("。", "；", "：", "！", "？", "”", "」", "）")


def cn_number(s: str) -> int:
    total, cur = 0, 0
    for ch in s:
        if ch in _DIGITS:
            cur = _DIGITS[ch]
        else:
            unit = _UNITS[ch]
            total += (cur or 1) * unit
            cur = 0
    return total + cur


def _paragraphs(path: Path) -> tuple[list[str], list[list[list[str]]]]:
    root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    paras: list[str] = []
    tables: list[list[list[str]]] = []
    for el in root.find(W + "body"):
        if el.tag == W + "p":
            text = "".join(t.text or "" for t in el.iter(W + "t")).strip()
            if text:
                paras.append(text)
        elif el.tag == W + "tbl":
            rows = []
            for tr in el.iter(W + "tr"):
                cells = ["".join(t.text or "" for t in tc.iter(W + "t")).strip() for tc in tr.iter(W + "tc")]
                if any(cells):
                    rows.append(cells)
            tables.append(rows)
    return paras, tables


def _join(lines: list[str]) -> str:
    out = ""
    for line in lines:
        if not out:
            out = line
        elif out.endswith(_SENTENCE_END):
            out += "\n" + line
        else:
            out += line  # a PDF line break in the middle of a sentence
    return out


def drop_running_heads(paras: list[str]) -> tuple[list[str], list[str]]:
    """Page headers a PDF conversion left between lines (e.g. "中国人民银行发布中国人民银行规章"
    on every page): short lines repeated at least 3 times that are not an article or chapter."""
    counts: dict[str, int] = {}
    for p in paras:
        counts[p] = counts.get(p, 0) + 1
    heads = {p for p, n in counts.items() if n >= 3 and len(p) <= 40 and not _ARTICLE.match(p)
             and not _CHAPTER.match(p) and not p.endswith(_SENTENCE_END)}
    return [p for p in paras if p not in heads], sorted(heads)


def split_articles(law_id: str, paras: list[str]) -> tuple[list[dict], list[str]]:
    articles: list[dict] = []
    warnings: list[str] = []
    paras, heads = drop_running_heads(paras)
    if heads:
        warnings.append("Bỏ dòng tiêu đề trang lặp lại: " + "; ".join(heads))
    chapter, current, body = None, None, []
    tail: list[str] = []
    skipped_refs = 0

    def close() -> None:
        if current is not None:
            articles.append({"id": f"{law_id}#{current}", "law_id": law_id, "no": current, "chapter": chapter_of[current],
                             "text": _join(body)})

    chapter_of: dict[int, str | None] = {}
    for line in paras:
        m = _ARTICLE.match(line)
        if _APPENDIX.match(line) and current is not None:
            close()
            current, body = None, []
            tail.append(line)
            continue
        if tail:
            tail.append(line)
            continue
        if _CHAPTER.match(line) and not m:
            chapter = line.split()[0] if " " in line else line
            continue
        if m:
            n = cn_number(m.group(1))
            expected = (current or 0) + 1
            if n == expected:
                close()
                current, body = n, [line]
                chapter_of[n] = chapter
                continue
            if current is not None:
                skipped_refs += 1  # a cross-reference that landed at the start of a line
        if current is not None:
            body.append(line)
    close()
    if skipped_refs:
        warnings.append(f"{skipped_refs} dòng bắt đầu bằng 第X条 nhưng sai số thứ tự: giữ trong điều trước "
                        "(câu viện dẫn bị ngắt dòng).")
    if tail:
        articles.append({"id": f"{law_id}#appendix", "law_id": law_id, "no": None, "chapter": "附件",
                         "text": _join(tail)})
    return articles, warnings


def extract(tq: Path) -> tuple[dict, dict]:
    corpus: dict[str, dict] = {}
    sources = []
    for file, meta in SOURCES.items():
        path = tq / file
        if not path.exists():
            sources.append({"file": file, "law_id": meta["id"], "missing": True,
                            "warnings": ["Không tìm thấy file trong docs/agents/TQ."]})
            continue
        raw = path.read_bytes()
        paras, tables = _paragraphs(path)
        warnings = list(meta.get("warn", []))
        entry = {"file": file, "law_id": meta["id"], "name": meta["name"], "title": paras[0] if paras else "",
                 "effective": meta["eff"], "mode": meta["mode"], "sha256": hashlib.sha256(raw).hexdigest()}
        header = next((p for p in paras[:4] if p.startswith("来源")), None)
        if header:
            entry["origin"] = header
        if meta["mode"] == "articles":
            arts, more = split_articles(meta["id"], paras)
            warnings += more
            entry["articles"] = len([a for a in arts if a["no"] is not None])
            entry["expected_articles"] = meta["expect"]
            if entry["articles"] != meta["expect"]:
                warnings.append(f"Đếm được {entry['articles']} điều, README ghi {meta['expect']}.")
            if any(a["no"] is None for a in arts):
                entry["appendix"] = True
        elif meta["mode"] == "fulltext":
            arts = [{"id": meta["id"], "law_id": meta["id"], "no": None, "chapter": None, "text": "\n".join(paras)}]
            entry["paragraphs"] = len(paras)
        else:
            arts = []
            for t, rows in enumerate(tables, start=1):
                header_row, *data = rows
                for r, cells in enumerate(data, start=1):
                    arts.append({"id": f"{meta['id']}#P{t}-{r}", "law_id": meta["id"], "no": None,
                                 "chapter": paras[2 + t] if len(paras) > 2 + t else f"Phần {t}",
                                 "columns": header_row, "cells": cells, "text": " | ".join(cells)})
            entry["rows"] = len(arts)
        for a in arts:
            a["effective"] = meta["eff"]
            a["law"] = meta["name"] + (f", Điều {a['no']}" if a.get("no") else "")
            corpus[a["id"]] = a
        entry["warnings"] = warnings
        sources.append(entry)
    body = json.dumps(corpus, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest = {"extracted": date.today().isoformat(), "extractor": "scripts/extract_laws.py",
                "corpus_hash": "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "entries": len(corpus), "sources": sources}
    return corpus, manifest


def main() -> None:
    tq = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TQ
    corpus, manifest = extract(tq)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "corpus.json").write_text(json.dumps(corpus, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{manifest['entries']} mục · {manifest['corpus_hash'][:23]}…")
    for s in manifest["sources"]:
        count = s.get("articles", s.get("rows", s.get("paragraphs", "-")))
        print(f"  {s['law_id']:<14} {count!s:>5}  " + ("; ".join(s["warnings"]) or "ok"))


if __name__ == "__main__":
    main()
