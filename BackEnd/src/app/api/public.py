"""/v4/public: landing-page overview and the demo store links (contract section 2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform.errors import api_error
from app.data_sources import sources
from app.api.loans import public_stats
from app.platform.tables import BuBank
from app.platform.config import settings
from app.platform.db.session import get_session

router = APIRouter(prefix="/public", tags=["v4-public"])

AGENTS = [
    {"id": 1, "name": "Xác minh", "summary": "Kiểm cửa hàng có thật, lập bao lâu, doanh số thật qua tiền từ sàn "
                                             "về tài khoản và thuế; hỏi người bán bằng câu chọn sẵn."},
    {"id": 2, "name": "Tư vấn & Đề xuất", "summary": "Chọn phương án giải thuật đã tính, giải thích vì sao, thử "
                                                     "“nếu tôi làm X”; không có công cụ nào nhận số tiền."},
    {"id": 3, "name": "Kiểm soát", "summary": "Phản biện độc lập theo luật và rủi ro; niêm phong kết luận pha 1 "
                                              "trên chuỗi trước khi đọc lập luận."},
    {"id": 4, "name": "Giải ngân", "summary": "Chia khoản vay giữa các ngân hàng, chi một lần, trích nợ theo tỷ lệ "
                                              "mỗi lần tiền hàng về."},
    {"id": 5, "name": "Hậu kiểm", "summary": "So khoản đã vay với kết quả trả thật, đề xuất cải tiến; người duyệt "
                                             "trước khi áp dụng."},
]


@router.get("/overview")
def overview(session: Session = Depends(get_session)) -> dict:
    banks = session.scalars(select(BuBank).where(BuBank.active.is_(True), BuBank.code != "MASTER")
                            .order_by(BuBank.region, BuBank.code))
    return {"stats": public_stats(session),
            "banks": [{"code": b.code, "name": b.name, "region": b.region} for b in banks],
            "agents": AGENTS, "simulated": True}


@router.get("/demo-stores")
def demo_stores() -> dict:
    if settings.app_env not in ("dev", "demo", "test"):
        raise api_error(404, "NOT_FOUND", "Không có danh sách cửa hàng mẫu ở môi trường này.")
    return {"stores": sources.demo_stores(), "simulated": True, "seed_note": sources.SEED_NOTE}


@router.get("/features")
def features() -> dict:
    """Switches the seller app reads at start-up (e.g. CCCD OCR at the identity step, CCCD_OCR_REQUIRED)."""
    return {"cccd_ocr": bool(settings.cccd_ocr_required)}
