"""Chatbot answering questions about BuoyUp from the bundled knowledge base (knowledge/kb.json).

Retrieval reuses the backend's RAG module (app/core/rag.py) on a third corpus, "KB": BM25 over Vietnamese
syllables plus the same local e5 embeddings, fused by RRF and weighted by source (team Q&A first).

Answering:
- default: the best-matching section, quoted as written, plus two related sections; nothing leaves the machine;
- optional: a language model writes the answer from the five best sections only, when configured:
    BUOYUP_CHAT_LLM=anthropic  ANTHROPIC_API_KEY=…            [BUOYUP_CHAT_MODEL=claude-sonnet-5-5]
    BUOYUP_CHAT_LLM=openai     OPENAI_BASE_URL=… OPENAI_API_KEY=… BUOYUP_CHAT_MODEL=…
  The sections are then sent to that provider. Any error falls back to the quoted answer.
Questions about the law also get the nearest articles from the Chinese and Vietnamese law corpora.
"""

from __future__ import annotations

import json
import os
import re
import threading
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

KB_FILE = Path(__file__).resolve().parent / "knowledge" / "kb.json"
RRF_K = 60
# A question is about BuoyUp when it names a topic below, or its embedding is close to some section.
# (0.865: questions on topic scored 0.877–0.893 on the e5 model, off-topic ones 0.807–0.852.)
ON_TOPIC_SIM = 0.865
_DOMAIN = re.compile(r"buoyup|\bvay\b|han muc|ngan hang|\blai\b|tra no|\bno\b|giai ngan|hop dong|agent|fate|fisco|"
                     r"blockchain|chuoi|\brag\b|luat|demo|ho so|tat toan|qua han|tra cham|dong y|sao ke|thue|tin dung|"
                     r"loan|credit|bank|lend|repay|limit|interest|contract|disburse|borrow|seller|shop|cua hang|"
                     r"nguoi ban|webank|syndicat|chain|chatbot|gop y|feedback|fintech|cuoc thi|de tai")
_GREETING = re.compile(r"^(xin chào|chào|chao|hello|hi|hey|alo)\b[\s!.,]*(bạn|ban|bot)?[\s!.?]*$", re.I)
_LEGAL = re.compile(r"\b(luật|điều luật|nghị định|pháp lý|pháp luật|quy định pháp|thông tư|law|legal|regulation)\b|法|条例",
                    re.I)

try:
    from app.core import rag  # sys.path is set by buoyup_app.py
except Exception:  # noqa: BLE001 - keyword search below still works
    rag = None


def _fold(text: str) -> str:
    text = text.lower().replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


class KB:
    def __init__(self, path: Path = KB_FILE) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        self.hash = data["hash"]
        self.entries: dict[str, dict[str, Any]] = {e["id"]: e for e in data["entries"]}
        self.ix = None
        if rag is not None:
            arts = {k: {"law": e["title"], "text": e["text"]} for k, e in self.entries.items()}
            self.ix = rag.Index(rag.Corpus("KB", arts, self.hash, "vi"))
        self._words = {k: set(re.findall(r"\w+", _fold(e["title"] + " " + e["text"]))) for k, e in self.entries.items()}

    def warm(self) -> None:
        if self.ix is not None:
            self.ix.dense_ready()

    def mode(self) -> str:
        if self.ix is None:
            return "từ khóa"
        return "theo chữ + theo nghĩa" if self.ix.dense_ready() else "theo chữ (BM25)"

    def on_topic(self, query: str) -> bool:
        if _DOMAIN.search(_fold(query)):
            return True
        if self.ix is not None and self.ix.dense_ready():
            best = self.ix.dense(query, top=1)
            return bool(best) and best[0][1] >= ON_TOPIC_SIM
        return False

    def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Best ``k`` sections; each hit carries ``lexical`` (True when some query word matched)."""
        q = query.strip()
        if not q:
            return []
        if self.ix is None:  # no backend module: plain word overlap
            qw = set(re.findall(r"\w+", _fold(q)))
            scored = sorted(((len(qw & w) * self.entries[i]["weight"], i) for i, w in self._words.items()), reverse=True)
            return [{**self.entries[i], "score": s, "lexical": s > 0} for s, i in scored[:k] if s > 0]
        expanded, _ = self.ix.corpus.expand(q)
        lists = [("lexical", self.ix.bm25(expanded)[:100])]
        if self.ix.dense_ready():
            lists.append(("dense", self.ix.dense(expanded, top=100)))
        fused: dict[str, float] = defaultdict(float)
        lexical: set[str] = set()
        for name, lst in lists:
            seen: set[str] = set()
            rank = 0
            for i, _s in lst:  # rank sections, not passages
                aid = self.ix.passages[i]["article_id"]
                if aid in seen:
                    continue
                seen.add(aid)
                rank += 1
                fused[aid] += 1.0 / (RRF_K + rank)
                if name == "lexical":
                    lexical.add(aid)
        ranked = sorted(fused, key=lambda a: -fused[a] * self.entries[a]["weight"])[:k]
        return [{**self.entries[a], "score": round(fused[a] * self.entries[a]["weight"], 5), "lexical": a in lexical}
                for a in ranked]


_KB: KB | None = None
_LOCK = threading.Lock()


def kb() -> KB:
    global _KB
    if _KB is None:
        with _LOCK:
            if _KB is None:
                _KB = KB()
    return _KB


# --- answering ---------------------------------------------------------------------------------

def _trim(text: str, limit: int = 1400) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return cut[: max(cut.rfind("\n"), cut.rfind(". ") + 1, limit // 2)].rstrip() + "\n\n…"


def _laws(query: str) -> str:
    if rag is None or not _LEGAL.search(query):
        return ""
    rows = []
    for j, name in (("VN", "Việt Nam"), ("CN", "Trung Quốc")):
        try:
            for h in rag.search(query, k=2, jurisdiction=j):
                rows.append(f"- **{name} · {h['law']}** (`{h['article_id']}`): {h['snippet'][:160].strip()}…")
        except Exception:  # noqa: BLE001
            continue
    if not rows:
        return ""
    return ("\n\n**Điều luật gần nhất** (tra đầy đủ ở tab *Tra cứu luật (RAG)*):\n" + "\n".join(rows))


def _llm(question: str, hits: list[dict[str, Any]], history: list[dict[str, Any]]) -> str | None:
    kind = (os.environ.get("BUOYUP_CHAT_LLM") or "").lower()
    if kind not in ("anthropic", "openai"):
        return None
    import httpx

    context = "\n\n".join(f"[{i}] {h['title']} ({h['source']})\n{h['text']}" for i, h in enumerate(hits, 1))
    system = ("Bạn là trợ lý giải đáp về BuoyUp, một bản demo cho vay người bán online dự thi FinTechathon 2026. "
              "Chỉ trả lời dựa trên các đoạn tài liệu được cung cấp; không có thông tin thì nói không biết và gợi ý "
              "tab Góp ý. Không bịa số liệu. Trả lời ngắn gọn bằng ngôn ngữ của câu hỏi, ghi số đoạn đã dùng như [1]. "
              "Nhắc rằng số liệu là mô phỏng khi nói về khách hàng, ngân hàng hay quyết định cho vay.\n\nTài liệu:\n"
              + context)
    msgs = [{"role": m["role"], "content": str(m["content"])} for m in history[-6:]
            if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
    msgs.append({"role": "user", "content": question})
    model = os.environ.get("BUOYUP_CHAT_MODEL")
    try:
        if kind == "anthropic":
            r = httpx.post("https://api.anthropic.com/v1/messages", timeout=60, headers={
                "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
                json={"model": model or "claude-sonnet-5-5", "max_tokens": 900, "system": system, "messages": msgs})
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json()["content"]).strip() or None
        base = os.environ["OPENAI_BASE_URL"].rstrip("/")
        r = httpx.post(f"{base}/chat/completions", timeout=60,
                       headers={"Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '')}"},
                       json={"model": model, "max_tokens": 900, "messages": [{"role": "system", "content": system}] + msgs})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip() or None
    except Exception:  # noqa: BLE001 - quoted answer instead
        return None


def answer(message: str, history: list[dict[str, Any]] | None = None) -> str:
    history = history or []
    q = (message or "").strip()
    if not q:
        return "Bạn hãy gõ một câu hỏi về BuoyUp."
    query = q
    if len(q.split()) <= 3:  # short follow-up ("còn doanh nghiệp?"): add the previous question
        prev = [m["content"] for m in history if m.get("role") == "user" and isinstance(m.get("content"), str)]
        if prev:
            query = prev[-1] + " " + q
    if _GREETING.match(q):
        query = "Bạn là ai? Chatbot này trả lời được những gì?"
    hits = kb().search(query, k=5) if kb().on_topic(query) else []
    if not hits or not any(h["lexical"] for h in hits[:3]):
        return ("Mình chưa tìm thấy nội dung nào về câu này trong tài liệu BuoyUp. Bạn thử hỏi cách khác, ví dụ "
                "*\"hạn mức được tính thế nào\"*, *\"Agent 3 làm gì\"*, *\"trả chậm bị xử lý ra sao\"*; hoặc ghi câu hỏi "
                "ở tab **Góp ý** để đội trả lời." + _laws(q))
    text = _llm(q, hits, history)
    if text:
        refs = "\n".join(f"[{i}] {h['title']} · *{h['source']}*" for i, h in enumerate(hits, 1))
        return f"{text}\n\n<details><summary>Nguồn</summary>\n\n{refs}\n</details>" + _laws(q)
    top = hits[0]
    more = [h for h in hits[1:] if h["lexical"]][:2]
    out = f"**{top['title']}**\n\n{_trim(top['text'])}\n\n*Nguồn: {top['source']}*"
    if more:
        out += "\n\n**Xem thêm:**\n" + "\n".join(
            f"<details><summary>{h['title']} · {h['source']}</summary>\n\n{_trim(h['text'], 900)}\n</details>" for h in more)
    laws = _laws(q)
    if laws:  # a question about the law: the articles first, the product context after
        return laws.strip() + "\n\n---\n\n" + out
    return out
