"""/v4/legal: search the law corpora (RAG) and read one article. Staff only.

Two corpora: ``CN`` (Chinese laws, original Chinese text) and ``VN`` (Vietnamese laws)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.core import legal, rag
from app.platform.errors import api_error
from app.platform.security import require_roles
from app.platform.tables import BuUser

router = APIRouter(prefix="/legal", tags=["v4-legal"])
_staff = require_roles("officer", "admin")


@router.get("/corpora")
def corpora(_: BuUser = Depends(_staff)) -> dict:
    out = []
    for j in rag.available():
        ix = rag.index(j)
        out.append({"jurisdiction": j, "name": rag.JURISDICTIONS[j], "articles": len(ix.corpus.articles),
                    "passages": len(ix.passages), "mode": rag.mode(j), "corpus_hash": ix.corpus.hash,
                    "laws": sorted({a.split("#")[0] for a in ix.corpus.articles})})
    return {"items": out, "model": rag.MODEL}


@router.get("/search")
def search(q: str = Query(min_length=1, max_length=300), k: int = Query(default=5, ge=1, le=20),
           law: list[str] | None = Query(default=None, max_length=10), as_of: date | None = None,
           use: Literal["auto", "bm25", "dense", "hybrid"] = "auto",
           jurisdiction: Literal["CN", "VN"] = "CN", _: BuUser = Depends(_staff)) -> dict:
    """Question in Vietnamese, English or Chinese → the closest articles of one corpus."""
    if jurisdiction not in rag.available():
        raise api_error(404, "NOT_FOUND", "Chưa có kho luật này.")
    ix = rag.index(jurisdiction)
    return {"query": q, "jurisdiction": jurisdiction, "mode": rag.mode(jurisdiction) if use == "auto" else use,
            "corpus_hash": ix.corpus.hash,
            "items": rag.search(q, k=k, law_ids=law, as_of=as_of, use=use, jurisdiction=jurisdiction)}


@router.get("/articles/{article_id}")
def article(article_id: str, _: BuUser = Depends(_staff)) -> dict:
    art = rag.article(article_id)
    if art is None:
        raise api_error(404, "NOT_FOUND", "Không có điều này trong kho luật.")
    return {"article_id": article_id, "jurisdiction": art["jurisdiction"], "law": art["law"],
            "effective": art.get("eff"), "status": art.get("status", "in_force"),
            "repealed_on": art.get("repealed_on"), "repealed_by": art.get("repealed_by"), "text": art["text"]}


assert legal.CORPUS  # the Chinese corpus is part of the rule set; it must load
