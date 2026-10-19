"""Agent 4 (giải ngân & giám sát) through the configured model.

Code keeps every decision that moves money (loan circle: the banks' shares are fixed by the
syndicate round, 40/30/30 or 30/70). The model may only word the notice a borrower gets when the
early warning turns yellow or red. The notice passes the number and promise filters; a yellow
notice asks the cause with fixed choices.
Without a model, or on any failure, the deterministic path is used.
"""
from __future__ import annotations

import json
import secrets
from typing import Any


from app.agents import llm_tools
from app.platform.tables import BuLoan
from app.platform.guards import forbidden_phrases
from app.platform.db.tables import utcnow

NOTICE_SYSTEM = (
    "Bạn là Agent 4 (giám sát khoản vay) của BuoyUp. Viết MỘT thông báo ngắn (tối đa 3 câu), tiếng Việt, xưng "
    "'BuoyUp', gọi người bán là 'bạn', gửi người bán về tình hình khoản vay, dựa trên dữ liệu JSON. Nói điều hệ thống "
    "thấy bằng lời thường, không nêu ngưỡng, điểm số, trọng số hay mã nội bộ. Mức 'yellow': kết thúc bằng lời mời bạn "
    "cho biết nguyên nhân (giao diện sẽ hiện các lựa chọn). Mức 'red': nói cán bộ tín dụng sẽ liên hệ. Không hứa "
    "gia hạn, giảm lãi hay xóa nợ. Chỉ dùng con số có trong dữ liệu. Chỉ trả về đoạn văn."
)

# What the seller may be told about each B11 signal (no thresholds, weights or codes).
SELLER_SIGNAL = {
    "sales_low": "doanh số tháng gần đây thấp so với khoản phải trả",
    "rating_low": "điểm đánh giá cửa hàng giảm",
    "low_balance": "số dư tài khoản kinh doanh chưa đủ cho kỳ trả sắp tới",
    "large_personal": "có khoản chuyển lớn sang tài khoản cá nhân",
    "misuse": "có giao dịch không đúng mục đích kinh doanh",
    "new_inquiry": "có tra cứu tín dụng mới ở nơi khác",
    "fate_worse": "điểm tín dụng liên ngân hàng xấu đi",
    "overdue": "kỳ trả đã quá hạn",
    "use_of_funds": "chưa thấy hóa đơn mua hàng cho khoản vay",
}

# Fixed answers to "what is the cause?" (yellow). Officers see the answer next to the alert.
CAUSE_CHOICES = [
    {"key": "seasonal", "label": "Doanh số giảm theo mùa, sẽ tăng lại"},
    {"key": "other_account", "label": "Tiền hàng chưa về tài khoản kinh doanh WeBank"},
    {"key": "paused", "label": "Tạm ngừng bán một thời gian"},
    {"key": "invoice_pending", "label": "Đã nhập hàng, hóa đơn chưa về"},
    {"key": "other", "label": "Lý do khác"},
]


# --- (b) seller notices ----------------------------------------------------------------------

def _allowed(loan: BuLoan, doc: dict[str, Any]) -> set[float]:
    from app.agents.agent2_advise import _walk

    out: set[float] = set()
    nxt = next((r for r in doc.get("schedule") or [] if r.get("status") == "upcoming"), {})
    _walk({k: doc.get(k) for k in ("amount", "first_due_date", "final_due_date", "tenor_m")}, out)
    _walk([loan.outstanding, loan.repaid, nxt.get("payment_est"), nxt.get("due_date"),
           (doc.get("account") or {}).get("balance")], out)
    return out


def _template(level: str, reasons: list[str]) -> str:
    what = "; ".join(reasons) or "khoản vay cần chú ý"
    if level == "red":
        return (f"BuoyUp thấy khoản vay của bạn cần chú ý: {what}. Cán bộ tín dụng sẽ liên hệ bạn sớm để cùng "
                "tìm cách xử lý.")
    return f"BuoyUp nhận thấy {what}. Bạn cho BuoyUp biết nguyên nhân để cùng tìm cách trả nợ thuận lợi nhé."


def write_notice(loan: BuLoan, doc: dict[str, Any], level: str, signals: list[dict[str, Any]],
                 alert_id: str, use_model: bool = True) -> dict[str, Any]:
    """A seller notice for a new or changed alert: {id, at, level, text, source, question?}."""
    from app.agents.agent2_advise import blocked

    reasons = [SELLER_SIGNAL[s["key"]] for s in signals if s.get("key") in SELLER_SIGNAL]
    text, source = _template(level, reasons), "template"
    prov = llm_tools.provider() if use_model else None
    if prov is not None:
        facts = {"level": level, "what_we_see": reasons, "loan": {
            "amount": doc.get("amount"), "outstanding": loan.outstanding, "repaid": loan.repaid,
            "currency": loan.currency, "final_due_date": doc.get("final_due_date"),
            "next_due": next((r for r in doc.get("schedule") or [] if r.get("status") == "upcoming"), None),
            "business_account_balance": (doc.get("account") or {}).get("balance")}}
        allowed = _allowed(loan, doc)
        for _ in range(1):
            try:
                draft = llm_tools.run_sync(prov.generate_text(
                    system_prompt=NOTICE_SYSTEM, user_input=json.dumps(facts, ensure_ascii=False))).strip()
            except Exception:  # noqa: BLE001 - template stands
                break
            if draft and len(draft) <= 600 and not blocked(draft, allowed) and not forbidden_phrases(draft, "intake"):
                text, source = draft, "llm"
                break
    notice: dict[str, Any] = {"id": "nt_" + secrets.token_hex(6), "at": utcnow().isoformat() + "Z", "level": level,
                              "text": text, "source": source, "alert_id": alert_id, "answer": None}
    if level == "yellow":
        notice["question"] = {"text": "Nguyên nhân là gì?", "choices": CAUSE_CHOICES}
    return notice
