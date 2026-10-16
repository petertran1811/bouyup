"""Phrases a model must never say (promises of approval, waivers, threats, thresholds).

A hit means the caller discards the model output and uses its template; it never repairs it.
"""

from __future__ import annotations

import unicodedata


def _norm(text: str) -> str:
    """Lowercase, accent-free, so 'Miễn lãi' and 'mien lai' compare equal."""
    t = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


FORBIDDEN: dict[str, list[str]] = {
    # PDF §6.3 agent 1: no risk assessment, no promise of approval or limit.
    "intake": [
        "chắc chắn được duyệt", "chắc chắn được vay", "chắc chắn được phê duyệt",
        "sẽ được duyệt", "sẽ được phê duyệt", "sẽ được cấp", "đảm bảo được vay",
        "hạn mức của bạn là", "hạn mức dự kiến", "bạn sẽ nhận được hạn mức",
        "rủi ro của bạn", "xác suất vỡ nợ",
    ],
    # Agent 2 spec §5: no promise of approval, of disbursement or of a lower rate (it says "chị").
    "advisor": [
        "chị sẽ được vay", "em đảm bảo", "em cam kết",
        "chắc chắn giải ngân", "chắc chắn được giải ngân", "đảm bảo giải ngân", "cam kết giải ngân",
        "sẽ được giải ngân ngay", "giải ngân ngay cho chị", "em sẽ giải ngân",
        "giảm lãi cho chị", "hạ lãi cho chị", "giảm lãi suất cho chị", "chị được giảm lãi", "em xin giảm lãi",
        "lãi suất ưu đãi hơn cho chị", "cam kết lãi", "đảm bảo lãi",
    ],
    "underwriter": ["tự phê duyệt", "đã phê duyệt", "vượt trần"],
    "challenger": ["sửa tờ trình", "chỉnh sửa tờ trình"],
    # PDF §6.3 agent 4: nothing that changes an approved term.
    "contract": [
        "thay đổi số tiền", "điều chỉnh số tiền", "thay đổi lãi suất", "điều chỉnh lãi suất",
        "thay đổi điều khoản", "điều chỉnh điều khoản",
    ],
    # PDF §6.3 agent 5: may only recommend to an officer.
    "monitor": [
        "khóa hạn mức", "khoá hạn mức", "thu hồi trước hạn", "đã khóa", "tạm khóa hạn mức",
    ],
    # PDF §6.3 agent 6: no waivers, no threats, no third parties.
    "care": [
        "miễn lãi", "miễn giảm lãi", "miễn phí phạt", "miễn phạt", "xóa nợ", "xoá nợ",
        "sẽ kiện", "khởi kiện", "báo công an", "bắt giữ", "truy cứu", "đe dọa",
        "liên hệ người thân", "gọi cho gia đình", "gọi cho người thân",
        "báo cho nơi làm việc", "báo cho công ty của bạn", "liên hệ hàng xóm",
    ],
    # PDF §6.5: factor level, neutral about fraud, no thresholds.
    "article24": [
        "gian lận", "lừa đảo", "giả mạo", "ngưỡng", "điểm số của bạn là",
        "xác suất vỡ nợ", "cutoff",
    ],
}


def forbidden_phrases(text: str, agent_id: str) -> list[str]:
    """Forbidden phrases of ``agent_id`` found in ``text`` (accent-insensitive)."""
    hay = _norm(text)
    return [p for p in FORBIDDEN.get(agent_id, []) if _norm(p) in hay]
