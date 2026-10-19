"""Seller notices at the application level (SELLER_SERVICES_PLAN §3.1.b, 17/10/2026).

Agent 4b writes its loan notices into ``BuLoan.doc["notices"]`` (``agent4b_monitor.push_notice``). Before a
loan exists the seller had no channel at all: the limit approval, a request for more documents or the
reason of a decision were recorded for staff and never reached her. This module writes those into
``BuApplication.doc["seller_notices"]`` with the same shape as a loan notice, so ``GET /v4/me/notices``
can merge both (and the seller reports) into one notification centre.

Only text and a link to a page: nothing here reads or moves money.
"""

from __future__ import annotations

import secrets
from typing import Any

from app.platform.db.tables import utcnow

# How every new sentence addresses the seller (the older templates said "chị" to everyone).
SELLER_ADDRESS = "bạn"

MAX_APP_NOTICES = 50

# Short title per notice kind, set by code (the text says the rest).
NOTICE_TITLES: dict[str, str] = {
    # application level
    "decision": "Kết quả xét hồ sơ",
    "limit_approved": "Ngân hàng đã duyệt hạn mức",
    "data_request": "Cần bổ sung chứng từ",
    # loan level (Agent 4b)
    "info": "Thông báo khoản vay",
    "disbursed": "Đã giải ngân",
    "due": "Đã trích kỳ trả",
    "overdue": "Kỳ trả chưa đủ tiền",
    "reminder": "Nhắc kỳ trả sắp tới",
    "minimum": "Đã chọn trả tối thiểu",
    "prepay": "Đã trả trước",
    "closed": "Đã tất toán khoản vay",
    "bureau": "Khoản vay quá hạn",
    "question": "BuoyUp cần bạn trả lời",
    "alert": "Cảnh báo khoản vay",
    "shortfall_forecast": "Có thể thiếu tiền kỳ tới",
    "dsr_high": "Tiền trả nợ đang nặng",
    "spend_below_due": "Số dư thấp hơn kỳ tới",
    # reports (Agent 5)
    "month": "Báo cáo tháng",
    "quarter": "Báo cáo quý",
    "year": "Báo cáo năm",
    "closing": "Báo cáo tất toán",
    "registration": "Nhắc đăng ký kinh doanh",
}

_LEVELS = {"info": "info", "green": "info", "warn": "warn", "yellow": "warn", "danger": "danger", "red": "danger"}


def level_of(value: Any) -> str:
    """Notice levels for the seller: info | warn | danger (Agent 4's yellow/red map onto warn/danger)."""
    return _LEVELS.get(str(value or "info"), "info")


def title_for(kind: Any, level: Any = "info", question: bool = False) -> str:
    if question:
        return NOTICE_TITLES["question"]
    if kind in NOTICE_TITLES:
        return NOTICE_TITLES[str(kind)]
    return {"warn": "Cần bạn lưu ý", "danger": "Cần bạn xử lý ngay"}.get(level_of(level), "Thông báo từ BuoyUp")


def make_notice(kind: str, text: str, level: str = "info", action: dict[str, Any] | None = None) -> dict[str, Any]:
    """Same structure as ``agent4b_monitor._notice`` plus ``action`` and ``read_at``."""
    return {"id": "nt_" + secrets.token_hex(6), "at": utcnow().isoformat() + "Z", "level": level_of(level),
            "kind": kind, "text": text, "source": "code", "answer": None, "action": action, "read_at": None}


def push_app_notice(doc: dict[str, Any], kind: str, text: str, level: str = "info",
                    action: dict[str, Any] | None = None) -> dict[str, Any]:
    """Add a notice to ``doc["seller_notices"]`` (newest first, at most MAX_APP_NOTICES). The caller
    persists the doc as usual (``views.store`` / ``save_json``)."""
    notice = make_notice(kind, text, level, action)
    doc["seller_notices"] = [notice, *(doc.get("seller_notices") or [])][:MAX_APP_NOTICES]
    return notice
