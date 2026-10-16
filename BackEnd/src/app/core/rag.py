"""Retrieval over the Chinese law corpus (RAG for Agent 3).

The corpus (``laws/corpus.json``: 794 articles from 14 Chinese laws and measures, original Chinese
text) is split into short passages and searched two ways, then fused:

- **Lexical (always on):** BM25 over Chinese character bigrams, so no word segmenter is needed. A
  query in Vietnamese or English is expanded with Chinese legal terms from :data:`GLOSSARY`
  (``thuốc lá điện tử`` → ``电子烟``), and its words also match the Vietnamese law names.
- **Dense (optional):** a multilingual sentence-embedding model run locally with ``fastembed``
  (``BUOYUP_RAG_MODEL``, default ``intfloat/multilingual-e5-large``) so a question in any of the three
  languages finds a Chinese article by meaning. Off when the package or the model is missing, or with
  ``BUOYUP_RAG_DENSE=0``; model files and passage vectors are cached under ``BUOYUP_RAG_CACHE``
  (default ``~/.cache/buoyup-rag``), the vectors keyed by model and corpus hash.
  ``scripts/build_rag_index.py`` builds the cache ahead of time (about 6 minutes on a laptop CPU).

Quality (``scripts/eval_rag.py``): recall@5 on the 22-question held-out set is 0.59 lexical only,
0.82 hybrid with e5-large; the 42-question dev set was used to write the glossary.

The two ranked lists are fused with reciprocal rank fusion (RRF); passages are grouped per article.
Retrieval only *finds and shows* law text: decisions stay with the coded rules, and every quote an
agent uses is still checked verbatim and for its effective date (:func:`legal.verify_citation`).
"""

from __future__ import annotations

import math
import os
import re
import threading
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from app.core import legal


def _env(name: str, default: str | None = None) -> str | None:
    """Process environment first, then the app's .env file (pydantic settings do not export it).
    A relative BUOYUP_RAG_CACHE in the .env file is relative to that file's folder."""
    if name in os.environ:
        return os.environ[name]
    try:
        from app.platform.config import ENV_FILE
    except Exception:  # noqa: BLE001
        return default
    path = Path(ENV_FILE)
    if not path.is_file():
        return default
    for line in path.read_text(encoding="utf-8").splitlines():
        k, sep, v = line.partition("=")
        if sep and k.strip() == name:
            v = v.strip().strip('"').strip("'")
            if name == "BUOYUP_RAG_CACHE" and v and not Path(v).is_absolute():
                v = str((path.parent / v).resolve())
            return v
    return default


# Default: multilingual-e5-large (2.2 GB, best on the held-out set); a lighter choice is
# sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (0.2 GB).
MODEL = _env("BUOYUP_RAG_MODEL", "intfloat/multilingual-e5-large") or "intfloat/multilingual-e5-large"
# e5 models expect role prefixes on both sides.
_PREFIX = ("query: ", "passage: ") if "e5" in MODEL else ("", "")
RRF_K = 60
# Fusion weights chosen on tests/rag_eval_holdout.json (not on the dev set the glossary was tuned on):
# e5-large is as good as the lexical side, the small MiniLM model only as a tie-breaker.
WEIGHTS = {"lexical": 1.0, "dense": 1.0 if "e5" in MODEL else 0.35}
CHUNK = 200       # characters per passage
OVERLAP = 40

# Vietnamese / English phrase → Chinese terms used in the corpus. Longest phrases are matched first.
GLOSSARY: dict[str, list[str]] = {
    # goods, licences, trademarks
    "thuốc lá điện tử": ["电子烟"], "e-cigarette": ["电子烟"], "vape": ["电子烟"],
    "vị hoa quả": ["调味", "口味"], "vị trái cây": ["调味", "口味"], "flavor": ["调味", "口味"], "hương vị": ["口味"],
    "tinh dầu": ["雾化物"], "nicotine": ["尼古丁"], "thuốc lá": ["烟草"],
    "nhãn hiệu": ["商标", "注册商标"], "trademark": ["商标"], "thương hiệu": ["商标"], "brand": ["商标"],
    "hàng giả": ["假冒", "以假充真"], "counterfeit": ["假冒", "以假充真"], "xâm phạm": ["侵犯"],
    "ủy quyền phân phối": ["许可", "注册商标专用权"], "giấy phép": ["许可"], "license": ["许可"],
    "giấy phép kinh doanh": ["营业执照", "行政许可"], "business license": ["营业执照"],
    "thực phẩm chức năng": ["保健食品"], "thực phẩm": ["食品"], "food": ["食品"], "đóng gói sẵn": ["预包装食品"],
    "dược phẩm": ["药品"], "thuốc": ["药品"], "drug": ["药品"], "thiết bị y tế": ["医疗器械"], "medical device": ["医疗器械"],
    "công khai": ["公示"], "disclose": ["公示"], "hàng cấm": ["禁止", "禁售"], "prohibited": ["禁止"],
    "chất lượng sản phẩm": ["产品质量"], "phạt": ["罚款"], "fine": ["罚款"], "tịch thu": ["没收"],
    "danh sách tiêu cực": ["负面清单"], "tiếp cận thị trường": ["市场准入"], "negative list": ["负面清单"],
    # e-commerce
    "thương mại điện tử": ["电子商务"], "e-commerce": ["电子商务"], "sàn": ["平台"], "platform": ["平台"],
    "người bán": ["经营者"], "cửa hàng trực tuyến": ["网络交易经营者"], "online store": ["网络交易经营者"],
    # AML
    "rửa tiền": ["洗钱"], "money laundering": ["洗钱"], "aml": ["洗钱"],
    "chủ sở hữu hưởng lợi": ["受益所有人"], "beneficial owner": ["受益所有人"],
    "nhận biết khách hàng": ["客户身份", "识别"], "kyc": ["客户身份", "识别"], "xác minh danh tính": ["核实", "身份"],
    "giao dịch đáng ngờ": ["可疑交易"], "suspicious transaction": ["可疑交易"], "giao dịch lớn": ["大额交易"],
    "large transaction": ["大额交易"], "báo cáo": ["报告"], "bảo mật": ["保密"],
    # personal data, credit
    "thông tin cá nhân": ["个人信息"], "personal information": ["个人信息"], "dữ liệu cá nhân": ["个人信息"],
    "đồng ý": ["同意"], "consent": ["同意"], "rút lại": ["撤回"], "withdraw": ["撤回"],
    "khuôn mặt": ["人脸", "生物识别", "敏感个人信息"], "biometric": ["生物识别", "敏感个人信息"],
    "thông tin nhạy cảm": ["敏感个人信息"], "sensitive": ["敏感个人信息"],
    "quyết định tự động": ["自动化决策"], "automated decision": ["自动化决策"], "giải thích": ["说明"],
    "chuyển cho bên thứ ba": ["提供", "第三方"], "third party": ["第三方"],
    "tín dụng": ["征信", "信用信息"], "credit report": ["征信", "信用报告"], "tra cứu": ["查询"],
    # lending
    "cho vay": ["贷款"], "loan": ["贷款"], "khoản vay": ["贷款"], "vốn lưu động": ["流动资金"],
    "working capital": ["流动资金"], "mục đích vay": ["贷款用途"], "loan purpose": ["贷款用途"],
    "sai mục đích": ["挪用"], "misuse": ["挪用"], "chứng khoán": ["证券", "股本权益性投资"], "bất động sản": ["房地产"],
    "thanh toán ủy thác": ["受托支付"], "entrusted payment": ["受托支付"], "trả thẳng nhà cung cấp": ["受托支付"],
    "trả nợ": ["还款"], "repayment": ["还款"], "lãi suất": ["利率"], "interest rate": ["利率"], "hợp đồng": ["合同"],
    "cho vay qua internet": ["互联网贷款"], "internet loan": ["互联网贷款"], "cho vay trực tuyến": ["互联网贷款"],
    "ngân hàng hợp tác": ["合作机构", "联合贷款"], "cho vay hợp vốn": ["联合贷款"], "joint lending": ["联合贷款"],
    "tập trung": ["集中度"], "concentration": ["集中度"], "đánh giá rủi ro": ["风险评估"], "risk": ["风险"],
    "giám sát sau cho vay": ["贷后管理"], "post-loan": ["贷后管理"], "quá hạn": ["逾期"], "overdue": ["逾期"],
    "thu hồi nợ": ["催收"], "collection": ["催收"], "công khai chi phí": ["综合成本", "披露"], "phí": ["费用"],
    "khiếu nại": ["投诉"], "complaint": ["投诉"], "kênh khiếu nại": ["投诉渠道"],
    # common legal wording
    "chưa thành niên": ["未成年人"], "trẻ vị thành niên": ["未成年人"], "minor": ["未成年人"],
    "qua mạng": ["信息网络"], "online": ["信息网络", "网络"], "trên sàn": ["信息网络", "平台"],
    "danh tính khách hàng": ["客户身份资料"], "khách hàng": ["客户"], "customer": ["客户"], "giao dịch": ["交易"],
    "lưu hồ sơ": ["保存", "交易记录"], "giữ bí mật": ["保密"], "ngưỡng": ["以上", "金额"], "threshold": ["以上", "金额"],
    "dù số tiền": ["不论", "金额"], "regardless": ["不论"], "thời hạn": ["期限"], "bao lâu": ["期限"],
    "thông tin tín dụng xấu": ["不良信息"], "bad credit": ["不良信息"], "bên khác": ["其他个人信息处理者", "提供"],
    "lãi suất năm thực tế": ["实际年利率"], "chi phí vay": ["综合资金成本"], "annual rate": ["实际年利率"],
    "người vay": ["借款人"], "borrower": ["借款人"], "nhà cung cấp": ["交易对象", "支付对象"], "supplier": ["交易对象"],
    "bồi thường": ["赔偿"], "compensation": ["赔偿"], "đã đăng ký": ["注册商标专用权"], "registered": ["注册"],
    "giả mạo": ["以假充真", "伪造"], "kém chất lượng": ["以次充好"], "bán": ["销售"], "sell": ["销售"],
    "sở hữu trí tuệ": ["知识产权"], "intellectual property": ["知识产权"], "tỷ lệ góp vốn": ["出资比例"],
    "tổ chức hợp tác": ["合作机构"], "bên thứ ba thu hồi nợ": ["第三方机构", "清收"], "bạo lực": ["暴力催收"],
    "minh bạch": ["透明度"], "transparency": ["透明度"], "đồng ý riêng": ["单独同意"], "separate consent": ["单独同意"],
}
_GLOSS = sorted(GLOSSARY, key=len, reverse=True)
_CJK = re.compile(r"[㐀-鿿]")
_WORD = re.compile(r"[0-9a-zà-ỹđ]+", re.I)


def _bigrams(text: str) -> list[str]:
    cjk = "".join(ch if _CJK.match(ch) else " " for ch in text)
    out: list[str] = []
    for run in cjk.split():
        out += [run] if len(run) == 1 else [run[i:i + 2] for i in range(len(run) - 1)]
    return out


def tokens(text: str) -> list[str]:
    """Chinese character bigrams + lower-cased Latin/Vietnamese words."""
    return _bigrams(text) + [w.lower() for w in _WORD.findall(text)]


def query_tokens(expanded: str) -> list[str]:
    """Chinese bigrams of the (expanded) query. Vietnamese/English words are used only when there is
    no Chinese at all: they can match nothing but the law names, and common words would add noise."""
    zh = _bigrams(expanded)
    return zh or [w.lower() for w in _WORD.findall(expanded)]


def expand(query: str) -> tuple[str, list[str]]:
    """The query plus the Chinese terms of every glossary phrase it contains."""
    low, terms = query.lower(), []
    for phrase in _GLOSS:
        if phrase in low:
            terms += [t for t in GLOSSARY[phrase] if t not in terms]
            low = low.replace(phrase, " ")
    return (query + " " + " ".join(terms)).strip(), terms


# --- Vietnamese ------------------------------------------------------------------------------

# English → Vietnamese legal terms (a Vietnamese question needs no expansion; English or Chinese
# questions rely on the embedding side as well).
GLOSSARY_VN: dict[str, list[str]] = {
    "money laundering": ["rửa tiền"], "aml": ["rửa tiền"], "beneficial owner": ["chủ sở hữu hưởng lợi"],
    "customer identification": ["nhận biết khách hàng"], "kyc": ["nhận biết khách hàng"],
    "customer due diligence": ["nhận biết khách hàng"], "suspicious transaction": ["giao dịch đáng ngờ"],
    "large transaction": ["giao dịch có giá trị lớn"], "report": ["báo cáo"], "record keeping": ["lưu trữ hồ sơ"],
    "terrorist financing": ["tài trợ khủng bố"], "politically exposed": ["người có ảnh hưởng chính trị"],
    "conditional business": ["kinh doanh có điều kiện"], "prohibited": ["cấm"], "banned": ["cấm"],
    "investment": ["đầu tư"], "business line": ["ngành, nghề"], "counterfeit": ["hàng giả"], "fake goods": ["hàng giả"],
    "smuggled": ["hàng nhập lậu"], "fine": ["phạt tiền"], "penalty": ["xử phạt", "phạt tiền"],
    "consumer": ["người tiêu dùng"], "e-commerce": ["thương mại điện tử"], "online": ["thương mại điện tử", "mạng"],
    "cigarette": ["thuốc lá"], "e-cigarette": ["thuốc lá điện tử"], "drug": ["thuốc", "ma túy"],
    "narcotic": ["ma túy"], "chemical": ["hóa chất"], "food": ["thực phẩm"], "cosmetics": ["mỹ phẩm"],
    "trademark": ["nhãn hiệu"], "intellectual property": ["sở hữu trí tuệ"], "label": ["nhãn hàng hóa"],
    "multi-level marketing": ["kinh doanh theo phương thức đa cấp"], "promotion": ["khuyến mại"],
    "license": ["giấy phép"], "invoice": ["hóa đơn"], "origin": ["nguồn gốc"],
    "selling": ["buôn bán"], "sell": ["buôn bán"], "goods": ["hàng hóa"], "smuggling": ["nhập lậu"],
}
_VI_MARK = re.compile(r"[ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]", re.I)


def _weights(corpus: "Corpus", query: str) -> dict[str, float]:
    """Fusion weights. Vietnamese corpus: a Vietnamese question is matched well by its words, so the
    embedding side only breaks ties; an English or Chinese question needs the embedding side.
    (Chosen on tests/rag_eval_vn.json; tests/rag_eval_vn_holdout.json is reported, not tuned on.)"""
    if corpus.kind == "vi":
        return {"lexical": 1.0, "dense": 0.3 if _looks_vietnamese(corpus, query) else 1.0}
    return WEIGHTS


def _looks_vietnamese(corpus: "Corpus", query: str) -> bool:
    """Diacritics, or (typed without them) most words are Vietnamese syllables of the corpus."""
    if _VI_MARK.search(query):
        return True
    if _CJK.search(query):
        return False
    words = [w.lower() for w in _WORD.findall(query)]
    if not words:
        return False
    vocab = index(corpus.name).idf
    return sum(("~" + _fold(w)) in vocab for w in words) / len(words) >= 0.8
_GLOSS_VN = sorted(GLOSSARY_VN, key=len, reverse=True)
_VN_STOP = set("của và các được có là cho trong này theo với không những một đã từ khi về để tại đến do hoặc bị "
               "thì mà như nếu phải sẽ đó ra vào trên dưới bao gồm quy định điều khoản".split())


def _fold(w: str) -> str:
    import unicodedata

    return "".join(ch for ch in unicodedata.normalize("NFD", w.replace("đ", "d").replace("Đ", "D"))
                   if unicodedata.category(ch) != "Mn")


def vn_tokens(text: str) -> list[str]:
    """Vietnamese syllables (lower-cased), syllable bigrams, and accent-free syllables (``~``) so a
    question typed without diacritics still matches."""
    syl = [w.lower() for w in _WORD.findall(text)]
    keep = [w for w in syl if w not in _VN_STOP]
    return keep + [syl[i] + "_" + syl[i + 1] for i in range(len(syl) - 1)] + ["~" + _fold(w) for w in keep]


def vn_expand(query: str) -> tuple[str, list[str]]:
    low, terms = query.lower(), []
    for phrase in _GLOSS_VN:
        if phrase in low:
            terms += [t for t in GLOSSARY_VN[phrase] if t not in terms]
            low = low.replace(phrase, " ")
    return (query + " " + " ".join(terms)).strip(), terms


# --- corpora -----------------------------------------------------------------------------------

_VN_DIR = Path(__file__).resolve().parent / "laws" / "vn"


class Corpus:
    """One jurisdiction's law corpus with its own tokenizer and query expansion."""

    def __init__(self, name: str, articles: dict[str, dict[str, Any]], corpus_hash: str, kind: str) -> None:
        self.name, self.articles, self.hash, self.kind = name, articles, corpus_hash, kind
        self.chunk, self.overlap = (CHUNK, OVERLAP) if kind == "zh" else (420, 80)

    def tokens(self, text: str) -> list[str]:
        return tokens(text) if self.kind == "zh" else vn_tokens(text)

    def query_tokens(self, expanded: str) -> list[str]:
        return query_tokens(expanded) if self.kind == "zh" else vn_tokens(expanded)

    def expand(self, query: str) -> tuple[str, list[str]]:
        return expand(query) if self.kind == "zh" else vn_expand(query)

    def in_force(self, aid: str, day: date) -> bool:
        a = self.articles[aid]
        if a.get("eff") and date.fromisoformat(a["eff"]) > day:
            return False
        return not (a.get("repealed_on") and date.fromisoformat(a["repealed_on"]) <= day)


def _cn() -> Corpus:
    arts = {k: {"law": v["law"], "text": v["text"], "eff": v.get("effective"), "status": "in_force"}
            for k, v in legal.CORPUS.items()}
    return Corpus("CN", arts, legal.CORPUS_HASH, "zh")


def _vn() -> Corpus | None:
    f = _VN_DIR / "corpus.json"
    if not f.exists():
        return None
    import json

    raw = json.loads(f.read_text(encoding="utf-8"))
    man = json.loads((_VN_DIR / "manifest.json").read_text(encoding="utf-8"))
    arts = {k: {"law": v["law"], "text": v["text"], "eff": v.get("effective"), "status": v.get("status", "in_force"),
                "repealed_on": v.get("repealed_on"), "repealed_by": v.get("repealed_by")} for k, v in raw.items()}
    return Corpus("VN", arts, man["corpus_hash"], "vi")


JURISDICTIONS = {"CN": "Trung Quốc", "VN": "Việt Nam"}


def _chunks(text: str, size: int, overlap: int) -> list[str]:
    lines = [ln.strip() for ln in re.split(r"[\n。；;]", text) if ln.strip()] if len(text) > size else [text]
    out, cur = [], ""
    for ln in lines:
        while len(ln) > size:  # a single very long line: hard windows with overlap
            out.append(ln[:size]); ln = ln[size - overlap:]
        if cur and len(cur) + len(ln) + 1 > size:
            out.append(cur); cur = cur[-overlap:] + " " + ln
        else:
            cur = (cur + " " + ln).strip()
    if cur:
        out.append(cur)
    return out or [text[:size]]


_MODEL: Any = None
_MODEL_LOCK = threading.Lock()


def _model() -> Any:
    """The embedding model, loaded once for every corpus (it is large)."""
    global _MODEL
    if _MODEL is None:
        with _MODEL_LOCK:
            if _MODEL is None:
                try:
                    from fastembed import TextEmbedding

                    cache = Path(_env("BUOYUP_RAG_CACHE") or Path.home() / ".cache" / "buoyup-rag")
                    cache.mkdir(parents=True, exist_ok=True)
                    _MODEL = TextEmbedding(MODEL, cache_dir=str(cache / "models"))
                except Exception:  # noqa: BLE001 - no package or no download: lexical only
                    _MODEL = False
    return _MODEL


class Index:
    def __init__(self, corpus: Corpus | None = None) -> None:
        self.corpus = corpus or _cn()
        self.passages: list[dict[str, Any]] = []
        for aid, art in self.corpus.articles.items():
            for i, ch in enumerate(_chunks(art["text"], self.corpus.chunk, self.corpus.overlap)):
                self.passages.append({"article_id": aid, "n": i, "text": ch, "law": art["law"]})
        self.toks = [self.corpus.tokens(p["text"] + " " + p["law"]) for p in self.passages]
        self.tf = [Counter(t) for t in self.toks]
        self.len = [len(t) for t in self.toks]
        self.avg = sum(self.len) / max(1, len(self.len))
        df: Counter[str] = Counter()
        for t in self.tf:
            df.update(t.keys())
        n = len(self.passages)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}
        self.post: dict[str, list[int]] = defaultdict(list)
        for i, t in enumerate(self.tf):
            for w in t:
                self.post[w].append(i)
        self._dense = None  # passage matrix once loaded; False when unavailable
        self._lock = threading.Lock()

    # --- lexical ---
    def bm25(self, query: str, k1: float = 1.4, b: float = 0.75) -> list[tuple[int, float]]:
        q = Counter(self.corpus.query_tokens(query))
        scores: dict[int, float] = defaultdict(float)
        for w, qn in q.items():
            idf = self.idf.get(w)
            if idf is None:
                continue
            for i in self.post[w]:
                f = self.tf[i][w]
                scores[i] += qn * idf * f * (k1 + 1) / (f + k1 * (1 - b + b * self.len[i] / self.avg))
        return sorted(scores.items(), key=lambda kv: -kv[1])

    # --- dense ---
    def dense_ready(self) -> bool:
        if (_env("BUOYUP_RAG_DENSE", "1") or "1") == "0":
            return False
        if self._dense is None:
            with self._lock:
                if self._dense is None:
                    self._dense = self._load_dense()
        return self._dense is not False

    def _load_dense(self) -> Any:
        try:
            import numpy as np
        except Exception:  # noqa: BLE001
            return False
        model = _model()
        if not model:
            return False
        cache = Path(_env("BUOYUP_RAG_CACHE") or Path.home() / ".cache" / "buoyup-rag")
        key = self.corpus.hash.replace("sha256:", "")[:16]
        tag = MODEL.split("/")[-1]
        name = f"passages-{tag}-{key}-{len(self.passages)}.npy" if self.corpus.name == "CN" else \
            f"passages-{self.corpus.name}-{tag}-{key}-{len(self.passages)}.npy"
        f = cache / name
        try:
            if f.exists():
                return np.load(f)
            sep = "：" if self.corpus.kind == "zh" else ": "
            mat = np.array(list(model.embed([_PREFIX[1] + p["law"] + sep + p["text"] for p in self.passages],
                                            batch_size=32)), dtype="float32")
            mat /= np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
            np.save(f, mat)
            return mat
        except Exception:  # noqa: BLE001
            return False

    def dense(self, query: str, top: int = 60) -> list[tuple[int, float]]:
        if not self.dense_ready():
            return []
        import numpy as np

        v = np.array(list(_model().embed([_PREFIX[0] + query]))[0], dtype="float32")
        v /= np.linalg.norm(v) + 1e-9
        sims = self._dense @ v
        idx = np.argsort(-sims)[:top]
        return [(int(i), float(sims[i])) for i in idx]


_INDEXES: dict[str, Index] = {}
_INDEX = None  # kept for callers that reset the Chinese index (tests)
_INDEX_LOCK = threading.Lock()


def available() -> list[str]:
    return ["CN"] + (["VN"] if (_VN_DIR / "corpus.json").exists() else [])


def index(jurisdiction: str = "CN") -> Index:
    global _INDEX
    j = jurisdiction.upper()
    if j == "CN" and _INDEX is None and "CN" in _INDEXES:
        _INDEXES.pop("CN")  # a test reset the index
    if j not in _INDEXES:
        with _INDEX_LOCK:
            if j not in _INDEXES:
                corpus = _cn() if j == "CN" else _vn()
                if corpus is None:
                    raise KeyError(f"No law corpus for {j}")
                _INDEXES[j] = Index(corpus)
                if j == "CN":
                    _INDEX = _INDEXES[j]
    return _INDEXES[j]


def mode(jurisdiction: str = "CN") -> str:
    return "hybrid" if index(jurisdiction).dense_ready() else "bm25"


def search(query: str, k: int = 5, *, law_ids: list[str] | None = None, as_of: date | None = None,
           use: str = "auto", jurisdiction: str = "CN") -> list[dict[str, Any]]:
    """Top ``k`` articles for ``query`` (any language) in one jurisdiction's corpus.
    ``use``: auto|bm25|dense|hybrid. Each hit: article_id, law, law_id, jurisdiction, score (RRF),
    snippet (best passage), lexical/dense ranks, in_force on ``as_of`` (today when omitted), status
    (in_force | partly_repealed | repealed), the glossary terms added to the query."""
    q = query.strip()
    if not q:
        return []
    ix = index(jurisdiction)
    expanded, terms = ix.corpus.expand(q)
    lists: list[tuple[str, list[tuple[int, float]]]] = []
    if use in ("auto", "hybrid", "bm25"):
        lists.append(("lexical", ix.bm25(expanded)[:200]))
    if use in ("auto", "hybrid", "dense") and ix.dense_ready():
        lists.append(("dense", ix.dense(expanded, top=200)))
    wanted = {x.strip().upper() for x in law_ids or [] if x.strip()}
    fused: dict[int, float] = defaultdict(float)
    ranks: dict[int, dict[str, int]] = defaultdict(dict)
    weights = _weights(ix.corpus, q)
    for name, lst in lists:
        w = weights[name] if len(lists) > 1 else 1.0
        for r, (i, _s) in enumerate(lst):
            fused[i] += w / (RRF_K + r + 1)
            ranks[i].setdefault(name, r + 1)
    best: dict[str, tuple[float, int]] = {}
    for i, s in fused.items():
        aid = ix.passages[i]["article_id"]
        if wanted and aid.split("#")[0].upper() not in wanted:
            continue
        if aid not in best or s > best[aid][0]:
            best[aid] = (s, i)
    day = as_of or date.today()
    out = []
    for aid, (s, i) in sorted(best.items(), key=lambda kv: -kv[1][0])[:k]:
        art = ix.corpus.articles[aid]
        out.append({"article_id": aid, "law": art["law"], "law_id": aid.split("#")[0],
                    "jurisdiction": ix.corpus.name, "score": round(s, 5), "snippet": ix.passages[i]["text"],
                    **ranks[i], "in_force": ix.corpus.in_force(aid, day), "status": art.get("status", "in_force"),
                    "terms": terms})
    return out


def article(article_id: str) -> dict[str, Any] | None:
    """One article from any corpus."""
    for j in available():
        a = index(j).corpus.articles.get(article_id)
        if a is not None:
            return {"article_id": article_id, "jurisdiction": j, **a}
    return None


# --- per-case retrieval (Agent 3) --------------------------------------------------------------

_FOOD = ("thực phẩm rời", "thực phẩm chức năng")
_MED = {"dược": "bán thuốc, dược phẩm qua mạng cần tư cách kinh doanh dược",
        "thiết bị y tế III": "kinh doanh thiết bị y tế loại III cần giấy phép"}


def case_queries(doc: dict[str, Any], amount: int | None = None, jurisdiction: str = "CN") -> list[dict[str, str]]:
    """Questions a reviewer would ask the law about this case, built from the case facts."""
    plan = doc.get("plan") or {}
    qs: list[dict[str, str]] = []
    item, group = str(plan.get("item") or ""), str(plan.get("group") or doc.get("category") or "")
    if jurisdiction == "VN":
        if item:
            qs.append({"topic": "goods", "q": f"kinh doanh {item} ({group}) có thuộc hàng hóa cấm kinh doanh hoặc "
                                              "ngành, nghề đầu tư kinh doanh có điều kiện không"})
        if plan.get("brand"):
            qs.append({"topic": "trademark", "q": f"buôn bán hàng giả mạo nhãn hiệu {plan['brand']} bị xử phạt thế nào"})
        if doc.get("borrower_type") == "company":
            qs.append({"topic": "aml", "q": "nhận biết khách hàng là tổ chức, xác định chủ sở hữu hưởng lợi"})
        qs.append({"topic": "aml", "q": "báo cáo giao dịch có giá trị lớn và giao dịch đáng ngờ"})
        if group in _FOOD:
            qs.append({"topic": "licence", "q": "kinh doanh thực phẩm không bảo đảm điều kiện bị xử phạt"})
        return qs
    if item:
        qs.append({"topic": "goods", "q": f"{item} ({group}) có thuộc danh mục hàng cấm, hạn chế hoặc cần giấy phép không"})
    if "thuốc lá" in (item + group).lower():
        qs.append({"topic": "goods", "q": "thuốc lá điện tử vị hoa quả bán qua mạng"})
    if group in _FOOD:
        qs.append({"topic": "licence", "q": "giấy phép kinh doanh thực phẩm phải công khai trên trang cửa hàng trực tuyến"})
    if group in _MED:
        qs.append({"topic": "licence", "q": _MED[group]})
    if plan.get("brand"):
        qs.append({"topic": "trademark", "q": f"bán hàng nhãn hiệu {plan['brand']} khi {str(plan.get('auth') or 'chưa rõ ủy quyền').lower()}: "
                                               "xâm phạm nhãn hiệu, hàng giả"})
    if doc.get("borrower_type") == "company":
        qs.append({"topic": "aml", "q": "xác minh chủ sở hữu hưởng lợi của công ty khi cho vay"})
    qs.append({"topic": "consent", "q": "đồng ý xử lý thông tin cá nhân, khuôn mặt và tra cứu tín dụng"})
    qs.append({"topic": "purpose", "q": "mục đích vay vốn lưu động rõ ràng, không dùng sai mục đích"})
    if amount and amount > 100_000:
        qs.append({"topic": "payment", "q": "thanh toán ủy thác trả thẳng nhà cung cấp"})
    return qs


def retrieve_for_case(doc: dict[str, Any], results: dict[str, dict[str, Any]] | None = None, *,
                      amount: int | None = None, as_of: date | None = None, k: int = 3) -> dict[str, Any]:
    """Run :func:`case_queries` on the case's jurisdiction (region ``VN`` → Vietnamese corpus), keep
    the top ``k`` per question, and check each fired rule: does retrieval surface at least one
    article the rule cites? (an independent cross-check; the rules cite the Chinese corpus)."""
    j = "VN" if str(doc.get("region") or "CN").upper() == "VN" and "VN" in available() else "CN"
    queries = [{**q, "hits": search(q["q"], k=k, as_of=as_of, jurisdiction=j)}
               for q in case_queries(doc, amount, j)]
    found = {h["article_id"] for q in queries for h in q["hits"]}
    checks = []
    for code, r in (results or {}).items():
        rule = legal.RULES_BY_CODE.get(code)
        if j != "CN" or not rule or not rule.cite or r.get("ok") is not False:
            continue
        cited = sorted({a for a, _ in rule.cite})
        checks.append({"rule": code, "cited": cited, "retrieved": sorted(found & set(cited)),
                       "agrees": bool(found & set(cited))})
    m = mode(j)
    return {"jurisdiction": j, "mode": m, "model": MODEL if m == "hybrid" else None, "queries": queries,
            "rule_checks": checks}
