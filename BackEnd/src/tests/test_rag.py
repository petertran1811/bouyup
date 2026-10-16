"""Law retrieval (RAG) over the Chinese corpus: quality on the dev and held-out sets, per-case
retrieval stored by Agent 3, the staff search API."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from urllib.parse import quote

from app.core import legal, rag
from tests import lc

HERE = Path(__file__).parent


def _recall_at(cases: list[dict], k: int, use: str) -> float:
    hit = sum(any(h["article_id"] in c["gold"] for h in rag.search(c["q"], k=k, use=use)) for c in cases)
    return hit / len(cases)


def test_passages_cover_the_whole_corpus():
    ix = rag.index()
    assert {p["article_id"] for p in ix.passages} == set(legal.CORPUS)
    assert max(len(p["text"]) for p in ix.passages) <= rag.CHUNK + rag.OVERLAP + 1


def test_glossary_bridges_vietnamese_and_english_to_chinese():
    _, terms = rag.expand("Bán thuốc lá điện tử vị hoa quả qua mạng")
    assert {"电子烟", "调味"} <= set(terms)
    _, terms = rag.expand("customer due diligence of the beneficial owner")
    assert "受益所有人" in terms


@pytest.mark.parametrize("q,gold", [
    ("thuốc lá điện tử vị hoa quả có được bán không", "ECIG-2022#26"),
    ("xác minh chủ sở hữu hưởng lợi của khách hàng là công ty", "AML-2024#29"),
    ("禁止通过信息网络销售电子烟", "ECIG-2022#23"),
    ("selling goods that infringe a registered trademark", "TM-2019#57"),
])
def test_lexical_search_finds_the_article(q, gold):
    ids = [h["article_id"] for h in rag.search(q, k=5, use="bm25")]
    assert gold in ids or gold.replace("2019#57", "2026#72") in ids


def test_quality_lexical_dev_and_holdout():
    """The glossary was written on the dev set; the held-out set measures it honestly."""
    dev = json.loads((HERE / "rag_eval.json").read_text(encoding="utf-8"))
    hold = json.loads((HERE / "rag_eval_holdout.json").read_text(encoding="utf-8"))
    assert _recall_at(dev, 5, "bm25") >= 0.9
    assert _recall_at(hold, 5, "bm25") >= 0.55


@pytest.mark.skipif(os.environ.get("BUOYUP_RAG_EVAL_DENSE") != "1", reason="needs the embedding model (opt-in)")
def test_quality_hybrid_holdout(monkeypatch):
    monkeypatch.setenv("BUOYUP_RAG_DENSE", "1")
    rag._INDEX = None
    hold = json.loads((HERE / "rag_eval_holdout.json").read_text(encoding="utf-8"))
    assert rag.index().dense_ready()
    assert _recall_at(hold, 5, "hybrid") >= 0.75


def test_effective_date_is_reported():
    hits = rag.search("销售侵犯注册商标专用权的商品", k=10, use="bm25", law_ids=["TM-2026"])
    assert hits and all(h["law_id"] == "TM-2026" for h in hits)
    from datetime import date

    early = rag.search("销售侵犯注册商标专用权的商品", k=10, use="bm25", law_ids=["TM-2026"], as_of=date(2026, 10, 14))
    assert not any(h["in_force"] for h in early)  # the 2026 trademark law is in force from 2027


def test_agent3_stores_case_retrieval_and_cross_checks_fired_rules(bu_client, as_seller, as_officer):
    app = lc.answer_all(bu_client, as_seller, lc.start(bu_client, as_seller, "ecig"))
    full = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    ret = full["control"]["retrieval"]
    assert ret["mode"] == "bm25" and ret["queries"]
    found = {h["article_id"] for q in ret["queries"] for h in q["hits"]}
    assert "ECIG-2022#26" in found or "ECIG-2022#23" in found
    checks = {c["rule"]: c for c in ret["rule_checks"]}
    assert checks["LAW-GOODS-01"]["agrees"] or checks["LAW-GOODS-02"]["agrees"]
    seller = bu_client.get(f"/v4/applications/{app['id']}", headers=as_seller).json()
    assert "retrieval" not in (seller["control"] or {})  # staff only


def test_company_case_retrieves_beneficial_owner_rules(bu_client, as_seller, as_officer):
    app = lc.answer_all(bu_client, as_seller, lc.start(bu_client, as_seller, "company"))
    ret = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()["control"]["retrieval"]
    aml = next(q for q in ret["queries"] if q["topic"] == "aml")
    assert {"AML-2024#29", "AML-2024#19"} & {h["article_id"] for h in aml["hits"]}


def test_search_api_is_staff_only(bu_client, as_seller, as_officer):
    r = bu_client.get("/v4/legal/search", params={"q": "rút lại sự đồng ý", "k": 3}, headers=as_officer)
    assert r.status_code == 200 and r.json()["items"][0]["article_id"].startswith("PIPL-2021")
    aid = r.json()["items"][0]["article_id"]  # ids contain "#": encode it in the path
    art = bu_client.get(f"/v4/legal/articles/{quote(aid, safe='')}", headers=as_officer).json()
    assert art["text"] and art["law"]
    assert bu_client.get("/v4/legal/search", params={"q": "x"}, headers=as_seller).status_code == 403
    assert bu_client.get("/v4/legal/articles/NOPE#1", headers=as_officer).status_code == 404


# --- Vietnamese corpus -------------------------------------------------------------------------

def test_vn_corpus_extracted_with_repeals():
    assert "VN" in rag.available()
    arts = rag.index("VN").corpus.articles
    assert sum(1 for k in arts if k.startswith("PCRT-2022#") and k.split("#")[1].isdigit()) == 66
    assert arts["ND59-2006#6"]["status"] == "repealed" and arts["ND59-2006#6"]["repealed_on"] == "2025-02-15"
    assert arts["ND59-2006#5"]["status"] == "in_force"
    assert "XÁC THỰC" not in arts["ND98-2020#91"]["text"]  # the consolidation footnotes are their own entries


def test_vn_quality_lexical_dev_and_holdout():
    dev = json.loads((HERE / "rag_eval_vn.json").read_text(encoding="utf-8"))
    hold = json.loads((HERE / "rag_eval_vn_holdout.json").read_text(encoding="utf-8"))

    def recall(cases):
        return sum(any(h["article_id"] in c["gold"] for h in rag.search(c["q"], k=5, use="bm25", jurisdiction="VN"))
                   for c in cases) / len(cases)

    assert recall(dev) >= 0.9 and recall(hold) >= 0.9


def test_vn_accent_free_query_and_repeal_flag():
    hits = rag.search("nhan biet khach hang", k=3, use="bm25", jurisdiction="VN")
    assert hits[0]["article_id"].startswith("PCRT-2022#")
    hits = rag.search("điều kiện kinh doanh hàng hóa hạn chế kinh doanh", k=10, use="bm25", jurisdiction="VN",
                      law_ids=["ND59-2006"])
    rep = next(h for h in hits if h["article_id"] == "ND59-2006#6")
    assert rep["status"] == "repealed" and rep["in_force"] is False


def test_vn_region_case_uses_vietnamese_corpus():
    doc = {"region": "VN", "borrower_type": "company", "plan": {"item": "Áo khoác", "group": "quần áo", "brand": "X"}}
    ret = rag.retrieve_for_case(doc, {}, amount=50_000)
    assert ret["jurisdiction"] == "VN" and ret["rule_checks"] == []
    aml = [h["article_id"] for q in ret["queries"] if q["topic"] == "aml" for h in q["hits"]]
    assert any(a.startswith("PCRT-2022#") for a in aml)


def test_search_api_vn(bu_client, as_officer):
    r = bu_client.get("/v4/legal/search", params={"q": "báo cáo giao dịch đáng ngờ", "jurisdiction": "VN"},
                      headers=as_officer).json()
    assert r["jurisdiction"] == "VN" and r["items"][0]["article_id"] == "PCRT-2022#26"
    art = bu_client.get(f"/v4/legal/articles/{quote('ND59-2006#6', safe='')}", headers=as_officer).json()
    assert art["jurisdiction"] == "VN" and art["status"] == "repealed"
    corp = {c["jurisdiction"]: c for c in bu_client.get("/v4/legal/corpora", headers=as_officer).json()["items"]}
    assert corp["VN"]["articles"] > 1000 and corp["CN"]["articles"] == 794
