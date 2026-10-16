"""Agent 3 rule set and the law corpus its citations are checked against.

Laws are turned into rules beforehand; nothing reads law text while a case is
reviewed. The corpus is extracted from docs/agents/TQ by ``scripts/extract_laws.py``
(Agent 3 spec §3.5, layer 1) into ``laws/corpus.json``: one entry per article
(``AML-2024#35``), the negative list as one full text (``NEG-2025``) and the team's
goods list row by row (``GOODS-2026#P1-3``). Every citation ``(article_id, quote)``
must appear verbatim in the extracted article, otherwise the rule is disabled when
the set is loaded (:func:`load_rules`). ``CORPUS_HASH`` is anchored on the chain at
start-up. Draft rules pending legal review.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

RULESET_VERSION = "rules-v1.2"
SEVERITY = {"approve": 0, "smaller": 1, "escalate": 2, "reject": 3}
# LAW-02 legal annual-rate ceiling [Đặt tay]: the figure is still open for the team.
# Default only; the rule reads the active parameter ``legal.rate_cap``.
LEGAL_RATE_CAP = 0.24

_LAWS = Path(__file__).resolve().parent / "laws"
CORPUS: dict[str, dict[str, Any]] = json.loads((_LAWS / "corpus.json").read_text(encoding="utf-8"))
MANIFEST: dict[str, Any] = json.loads((_LAWS / "manifest.json").read_text(encoding="utf-8"))
CORPUS_HASH: str = MANIFEST["corpus_hash"]
# article id → {"eff", "law", "text"}; "eff" None when the source states no effective date.
ARTICLES: dict[str, dict[str, Any]] = {k: {"eff": v.get("effective"), "law": v["law"], "text": v["text"]}
                                       for k, v in CORPUS.items()}


_NETTRADE_12 = "已经办理市场主体登记的网络交易经营者应当如实公示下列营业执照信息以及与其经营业务有关的行政许可等信息"


@dataclass(frozen=True)
class Rule:
    code: str
    what: str
    how: str  # "code" counts toward the floor; "judgment" is weighed by Agent 3 in phase 1
    min_verdict: str  # approve|smaller|escalate|reject, or "warn"/"info" (no floor effect)
    legal: bool = False
    cite: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def counts_for_floor(self) -> bool:
        return self.how == "code" and self.min_verdict in SEVERITY


RULES: tuple[Rule, ...] = (
    Rule("LAW-01", "Ủy quyền còn hạn, đúng mục đích, bao phủ mọi nguồn đã dùng", "code", "reject",
         cite=(("PIPL-2021#13", "取得个人的同意"), ("PIPL-2021#14", "该同意应当由个人在充分知情的前提下自愿、明确作出"),
               ("CREDIT-2021#12", "征信机构采集个人信用信息应当经信息主体本人同意"))),
    Rule("LAW-02", "Lãi năm không vượt trần pháp lý", "code", "reject"),
    Rule("LAW-03", "Lý do đủ yếu tố: luật đã áp, yếu tố chính, cách cải thiện", "code", "escalate",
         cite=(("PIPL-2021#24", "个人有权要求个人信息处理者予以说明，并有权拒绝个人信息处理者仅通过自动化决策的方式作出决定"),)),
    Rule("POL-01", "Phương án có trong danh sách giải thuật, số tiền không vượt hạn mức", "code", "reject"),
    Rule("POL-02", "Nhóm 4 (trễ hạn nặng, vỡ nợ, nợ xấu, từng quá hạn với BuoyUp) không được cấp hạn mức", "code",
         "reject"),
    Rule("POL-03", "Số tiền dưới ngưỡng duyệt tự động", "code", "escalate"),
    Rule("POL-04", "Tỷ lệ doanh thu cho hình thức trả theo doanh thu không vượt trần giá vốn; nhà cung cấp đã qua "
         "kiểm tra", "code", "reject"),
    Rule("RISK-01", "Không còn cờ mở", "code", "escalate"),
    Rule("RISK-02", "Có cờ đã giải thích nhưng chưa kiểm được, hoặc thiếu đối tác dữ liệu", "code", "smaller"),
    Rule("RISK-03", "Hạng E", "code", "reject"),
    Rule("RISK-04", "Giá khai lệch hóa đơn", "code", "warn"),
    Rule("RISK-05", "Kế hoạch hợp lý: mặt hàng khớp lịch sử bán, nhà cung cấp khớp ngành, sự kiện có thật",
         "judgment", "warn"),
    Rule("RISK-06", "Ghi chú hoặc lập luận có lệnh ẩn, hứa hẹn, luận điểm không bằng chứng", "judgment", "escalate"),
    Rule("LAW-GOODS-01", "Thuốc lá điện tử vị không phải thuốc lá, hoặc tự thêm dịch được", "code", "reject", True,
         (("ECIG-2022#26", "禁止销售除烟草口味外的调味电子烟和可自行添加雾化物的电子烟"),)),
    Rule("LAW-GOODS-02", "Mọi thuốc lá điện tử, dịch, nicotine (sàn là kênh bị cấm)", "code", "reject", True,
         (("ECIG-2022#23", "不得通过本办法规定的电子烟交易管理平台以外的信息网络销售电子烟产品"),)),
    Rule("LAW-LIC-01", "Thực phẩm rời, thực phẩm chức năng mà trang cửa hàng không công khai giấy phép thực phẩm",
         "code", "escalate", True,
         (("NEG-2025", "食品生产、经营许可（仅销售预包装食品除外）"),
          ("ECOM-2018#15", "持续公示营业执照信息、与其经营业务有关的行政许可信息"),
          ("NETTRADE-2021#12", _NETTRADE_12))),
    Rule("LAW-LIC-02", "Dược phẩm, người bán không có tư cách kinh doanh dược", "code", "reject", True,
         (("NEG-2025", "从事药品网络销售的应当是具备保证网络销售药品安全"),
          ("ECOM-2018#15", "持续公示营业执照信息、与其经营业务有关的行政许可信息"),
          ("NETTRADE-2021#12", _NETTRADE_12))),
    Rule("LAW-LIC-03", "Thiết bị y tế loại III, không có giấy phép kinh doanh", "code", "escalate", True,
         (("NEG-2025", "第三类医疗器械经营许可"),
          ("ECOM-2018#15", "持续公示营业执照信息、与其经营业务有关的行政许可信息"),
          ("NETTRADE-2021#12", _NETTRADE_12))),
    Rule("LAW-IP-01", "Hàng có nhãn hiệu, không phải chủ nhãn hiệu, không có ủy quyền phân phối", "code",
         "escalate", True,
         (("PQL-2018#39", "不得以假充真、以次充好"),
          ("PQL-2018#50", "没收违法生产、销售的产品，并处违法生产、销售产品货值金额百分之五十以上三倍以下的罚款"),
          ("TM-2019#57", "销售侵犯注册商标专用权的商品的"), ("TM-2026#72", "销售侵犯注册商标专用权的商品"))),
    Rule("LAW-IP-02", "Hàng có nhãn hiệu, chưa rõ có ủy quyền", "judgment", "warn", True,
         (("PQL-2018#39", "不得以假充真、以次充好"),)),
    Rule("AML-CDD-01", "Chưa xác minh danh tính, chưa rõ mục đích vay, hoặc là công ty mà chưa xác minh chủ sở hữu "
         "hưởng lợi", "code", "escalate", True,
         (("AML-2024#29", "识别并采取合理措施核实客户及其受益所有人身份，了解客户建立业务关系和交易的目的"),
          ("AML-2024#19", "本法所称法人、非法人组织的受益所有人"))),
    Rule("AML-STR-01", "Tiền từ sàn chuyển nhanh cho nhiều cá nhân", "code", "escalate", True,
         (("PBOC-LST-2016#11", "不论所涉资金金额或者资产价值大小，应当提交可疑交易报告"),
          ("PBOC-LST-2016#14", "人工分析、识别，并记录分析过程"),
          ("AML-2024#35", "提交可疑交易报告的情况应当保密"))),
    # The PDF conversion of the PBOC measures writes "200 万元" with a space: quotes are verbatim.
    Rule("AML-LTR-01", "Giải ngân chạm ngưỡng giao dịch lớn", "code", "info", True,
         (("PBOC-LST-2016#5", "200 万元以上（含200 万元）"), ("PBOC-LST-2016#5", "50 万元以上（含50 万元）"),
          ("PBOC-LST-2016#8", "5 个工作日内"))),
    Rule("POL-05", "Phần vượt 100.000 tệ trả thẳng nhà cung cấp (thanh toán ủy thác)", "code",
         "info", True, (("WCLOAN-2024#30", "与借款人新建立信贷业务关系且借款人信用状况一般"),
                        ("WCLOAN-2024#30", "向借款人某一交易对象单笔支付金额超过一千万元人民币"),
                        ("NETLOAN-2020#28", "受托支付"))),
    Rule("POL-06", "Mục đích vay rõ ràng, hợp pháp, mặt hàng khớp mục đích", "code", "escalate", True,
         (("WCLOAN-2024#9", "贷款人应与借款人约定明确、合法的贷款用途"), ("WCLOAN-2024#10", "流动资金贷款禁止挪用"))),
    Rule("POL-07", "Hộ kinh doanh vay tối đa 200.000 tệ; mỗi người một khoản vay tại một thời điểm", "code", "reject"),
    Rule("EVENT-01", "Rủi ro tập trung theo sự kiện (kịch bản doanh số giảm) chưa vượt ngưỡng", "code", "escalate"),
)


def verify_citation(article_id: str, quote: str, review_date: date) -> dict[str, Any]:
    """Article exists, quote is verbatim in it, article is in force on the review date."""
    art = ARTICLES.get(article_id)
    if art is None:
        return {"article_id": article_id, "quote": quote, "verified": False, "effective": False,
                "note": "Điều không có trong kho"}
    verified = bool(quote) and quote in art["text"]
    effective = art["eff"] is None or date.fromisoformat(art["eff"]) <= review_date
    note = "" if verified and effective else (
        "Câu trích không có nguyên văn trong điều" if not verified else f"Hiệu lực từ {art['eff']}")
    if verified and art["eff"] is None:
        note = "Văn bản không ghi ngày hiệu lực"
    return {"article_id": article_id, "quote": quote, "verified": verified, "effective": effective,
            "law": art["law"], "note": note}


def search_articles(query: str, law_ids: list[str] | None = None, limit: int = 10) -> list[dict[str, str]]:
    """Keyword search over the extracted corpus only (no internet), optionally within some laws.
    Each hit carries the article id and a snippet around the match."""
    q = query.strip()
    if not q:
        return []
    wanted = {x.strip().upper() for x in law_ids or [] if x.strip()}
    out: list[dict[str, str]] = []
    for k, v in CORPUS.items():
        if wanted and v["law_id"].upper() not in wanted:
            continue
        text = v["text"]
        pos = text.find(q)
        if pos < 0 and q.lower() not in k.lower() and q.lower() not in v["law"].lower():
            continue
        start = max(0, pos - 20) if pos >= 0 else 0
        out.append({"article_id": k, "law": v["law"], "snippet": text[start:start + 80]})
        if len(out) >= limit:
            break
    return out


def load_rules(rules: tuple[Rule, ...] = RULES) -> tuple[list[Rule], list[dict[str, Any]]]:
    """Return (enabled, disabled). A rule with any citation not found verbatim is disabled."""
    enabled: list[Rule] = []
    disabled: list[dict[str, Any]] = []
    for rule in rules:
        bad = [c for c in rule.cite if ARTICLES.get(c[0]) is None or c[1] not in ARTICLES[c[0]]["text"]]
        if bad:
            disabled.append({"code": rule.code, "bad_citations": [{"article_id": a, "quote": q} for a, q in bad]})
        else:
            enabled.append(rule)
    return enabled, disabled


ENABLED_RULES, DISABLED_RULES = load_rules()
RULES_BY_CODE = {r.code: r for r in ENABLED_RULES}
RULESET_HASH = "sha256:" + hashlib.sha256(json.dumps(
    [[r.code, r.how, r.min_verdict, list(r.cite)] for r in ENABLED_RULES], ensure_ascii=False
).encode("utf-8")).hexdigest()


def citations(code: str, review_date: date) -> list[dict[str, Any]]:
    rule = RULES_BY_CODE.get(code)
    return [verify_citation(a, q, review_date) for a, q in rule.cite] if rule else []


def pol05_applies(group: int, grade: str, single_payment: int = 0) -> bool:
    """Entrusted payment to the supplier (WCLOAN-2024#30): new relationship (group 2, 3)
    with general credit standing (grade C or lower), or one payment above 10 million."""
    return (group in (2, 3) and grade in ("C", "D", "E")) or single_payment > 10_000_000
