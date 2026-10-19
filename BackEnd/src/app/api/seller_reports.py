"""/v4/me/reports and /v4/officer/sellers/{user_id}/reports: Agent 5's reports to the seller
(SELLER_SERVICES_PLAN §6.5, 17/10/2026). Read-only; opening a report marks it read (its notice too)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agents import agent5_seller_reports as reports
from app.platform.db.session import get_session
from app.platform.db.tables import utcnow
from app.platform.errors import api_error
from app.platform.security import require_roles
from app.platform.tables import BuSellerReport, BuUser

router = APIRouter(tags=["v4-seller-reports"])
_sellers = require_roles("seller")
_staff = require_roles("officer", "admin")


@router.get("/me/reports")
def my_reports(user: BuUser = Depends(_sellers), session: Session = Depends(get_session)) -> dict:
    items = [reports.report_brief(r) for r in reports.list_for(session, user.id)]
    return {"items": items, "unread": sum(1 for i in items if not i["read_at"])}


@router.get("/me/reports/{report_id}")
def my_report(report_id: str, user: BuUser = Depends(_sellers), session: Session = Depends(get_session)) -> dict:
    row = session.get(BuSellerReport, report_id)
    if row is None or row.seller_user_id != user.id:
        raise api_error(404, "NOT_FOUND", "Không tìm thấy báo cáo.")
    if row.read_at is None:
        row.read_at = utcnow()
        session.commit()
    return reports.report_view(row)


@router.get("/officer/sellers/{user_id}/reports")
def seller_reports(user_id: str, _: BuUser = Depends(_staff), session: Session = Depends(get_session)) -> dict:
    if session.get(BuUser, user_id) is None:
        raise api_error(404, "NOT_FOUND", "Không tìm thấy người bán.")
    return {"seller_user_id": user_id, "items": [reports.report_view(r) for r in reports.list_for(session, user_id)]}
