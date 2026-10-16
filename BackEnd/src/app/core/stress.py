"""Tier-2 event stress (lỗ hổng 8): what open loans of one event would miss if the
event's sales came in at ``stress.event_drop`` (50 %) of the last campaign.

``shortfall = max(0, total_due − cost_share × drop × forecast)`` per loan, where
``forecast`` is the prudent monthly revenue × tenor and ``cost_share`` the B5 share of
revenue the borrower can put to repayment (loan circle); the
event ratio is Σshortfall ÷ Σexposure (total due) over open loans of that event.
Agent 3 rule EVENT-01 sends new files of an event to an officer when the ratio is
above ``stress.event_threshold`` and the event has at least
``stress.event_min_loans`` open loans (a single loan is not a concentration).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.platform.tables import BuLoan

OPEN_STATUSES = ("active", "overdue")


def stress_shortfall(doc: dict[str, Any], drop: float) -> int:
    """Lỗ hổng 8: max(0, total due − usable share × drop × revenue forecast over the tenor)."""
    shortfall = int(doc.get("total_due", 0)) - float(doc.get("sweep_usable", 0)) * drop * int(doc.get("forecast", 0))
    return max(0, round(shortfall))


def event_concentration(session: Session, params: dict[str, Any], event: str) -> dict[str, Any]:
    """Open-loan exposure of ``event`` under the stress drop, and whether EVENT-01 fires."""
    stress = params["stress"]
    loans = exposure = shortfall = 0
    for loan in session.scalars(select(BuLoan).where(BuLoan.status.in_(OPEN_STATUSES))):
        doc = loan.doc or {}
        if not event or str(doc.get("event") or "") != event:
            continue
        loans += 1
        exposure += int(doc.get("total_due", 0))
        shortfall += stress_shortfall(doc, float(stress["event_drop"]))
    ratio = round(shortfall / exposure, 4) if exposure else 0.0
    fires = loans >= int(stress["event_min_loans"]) and ratio > float(stress["event_threshold"])
    return {"event": event, "loans": loans, "exposure": exposure, "shortfall": shortfall, "ratio": ratio,
            "fires": fires}
