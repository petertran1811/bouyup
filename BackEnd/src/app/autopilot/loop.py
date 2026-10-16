"""Agents 4 and 5 run on their own.

* Agent 4 (giám sát): every ``BUOYUP_AGENT4_INTERVAL_SECONDS`` it assesses each open loan
  (B11, FATE re-score, use-of-funds, reminders, seller notices), refreshes the auto-approval
  switches and retries pending chain writes. It also reassesses a loan right after money
  arrives (``loans.post_inflow``), so the seller sees the result at once.
* Agent 5 (hậu kiểm): every ``BUOYUP_AGENT5_INTERVAL_SECONDS``, and soon after a real
  outcome (a loan paid off, a red alert); it skips a run when no loan changed since the
  last report. Its proposals still wait for a human.

Each loan is assessed in its own short transaction, so the SQLite write lock is never held
across the whole portfolio or across model calls for other loans. Off when ``APP_ENV=test``
or ``BUOYUP_AUTOPILOT=false``; staff can still run both by hand.
"""
from __future__ import annotations

import asyncio
import fcntl
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, select

from app.platform.config import settings
from app.platform.db.session import session_scope

AGENT5_MIN_GAP_SECONDS = 60  # an outcome-triggered post-audit waits at least this long after the last one
SYSTEM_ACTOR = SimpleNamespace(id="agent5:auto", role="system")

_lock = threading.Lock()
_state: dict[str, Any] = {
    "agent4": {"last_run_at": None, "last_reason": None, "loans": 0, "alerts": 0, "error": None, "next_run_at": None},
    "agent5": {"last_run_at": None, "last_reason": None, "report_id": None, "proposals": 0, "skipped": None,
               "error": None, "next_run_at": None, "due_reason": None},
}
_agent5_due: dict[str, Any] = {"at": None, "reason": None}
_due_lock = threading.Lock()
LOCK_FILE = Path(".buoyup-autopilot.lock")  # one loop per host even with several workers


def enabled() -> bool:
    return bool(settings.buoyup_autopilot) and settings.app_env != "test"


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"


def mark_agent5_due(reason: str) -> None:
    """Called by Agent 4 when a real outcome appears; the loop runs Agent 5 soon."""
    with _due_lock:
        if _agent5_due["at"] is None:
            _agent5_due.update(at=time.time(), reason=reason)
            _state["agent5"]["due_reason"] = reason


def _assess(loan_ids: list[str], budget: list[int]) -> tuple[int, list[str]]:
    """Each loan in its own short locked transaction (no model call inside); then the queued
    seller notices, drafted by the model outside any transaction."""
    from app.agents.agent4b_monitor import LOAN_LOCK, deliver_notices, tick

    alerts, errors, pending = 0, [], []
    for loan_id in loan_ids:
        try:
            with LOAN_LOCK, session_scope() as session:
                alerts += len(tick(session, loan_ids=[loan_id], refresh=False, deferred=pending))
        except Exception as exc:  # noqa: BLE001 - one loan must not stop the round
            errors.append(f"{loan_id}: {type(exc).__name__}")
    try:
        deliver_notices(pending, budget)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"notices: {type(exc).__name__}")
    return alerts, errors


def run_agent4(reason: str = "schedule", loan_ids: list[str] | None = None) -> dict[str, Any]:
    """A monitoring round over every open loan; then switches and (scheduled) the chain outbox."""
    from app.blockchain import chain
    from app.platform import events
    from app.agents.agent4b_monitor import NOTICE_MODEL_BUDGET, OPEN_STATUSES, refresh_auto_switch
    from app.core.params import active_params
    from app.platform.tables import BuLoan

    with _lock:
        if loan_ids is None:
            with session_scope() as session:
                loan_ids = list(session.scalars(select(BuLoan.id).where(BuLoan.status.in_(OPEN_STATUSES))))
        alerts, errors = _assess(loan_ids, [NOTICE_MODEL_BUDGET])  # one model budget per round
        with session_scope() as session:
            refresh_auto_switch(session, active_params(session))
            from app.agents import complaints

            complaints.sweep_overdue(session)  # review item 4: late complaints go to the lead
            events.log(session, "system", "agent4", "autopilot_run",
                       f"Agent 4 tự chạy ({reason}): {len(loan_ids)} khoản vay, {alerts} cảnh báo",
                       {"reason": reason, "loans": len(loan_ids), "alerts": alerts, "errors": errors[:10]})
        if reason == "schedule":  # remote calls in their own transaction, after the writes above
            with session_scope() as session:
                # Review item 3: the monitoring loop re-sends anchors only; a pending payout is Agent 4a's,
                # retried by an admin flush or re-authorized by an officer, never by this loop.
                chain.flush_outbox(session, include_payouts=False)
        _state["agent4"].update(last_run_at=_now(), last_reason=reason, loans=len(loan_ids), alerts=alerts,
                                error="; ".join(errors[:3]) or None)
        return dict(_state["agent4"])


def assess_loan(loan_id: str, reason: str) -> None:
    """Right after money arrives: reassess that loan only, without waiting for a running round."""
    from app.platform import events
    from app.agents.agent4b_monitor import NOTICE_MODEL_BUDGET

    alerts, errors = _assess([loan_id], [NOTICE_MODEL_BUDGET])
    with session_scope() as session:
        events.log(session, "system", "agent4", "autopilot_run", f"Agent 4 tự chạy ({reason}): 1 khoản vay, "
                   f"{alerts} cảnh báo", {"reason": reason, "loans": 1, "alerts": alerts, "errors": errors})
    _state["agent4"].update(last_run_at=_now(), last_reason=reason, loans=1, alerts=alerts,
                            error="; ".join(errors[:3]) or None)


def run_agent5(reason: str = "schedule") -> dict[str, Any]:
    """Post-audit by Agent 5 unless nothing changed since the last report."""
    from app.agents import agent5_postaudit as postaudit
    from app.platform.tables import BuLoan, BuReport

    started = time.time()
    with _lock, session_scope() as session:
        last = session.scalars(select(BuReport).order_by(BuReport.at.desc()).limit(1)).first()
        changed = session.scalar(select(func.count()).select_from(BuLoan).where(
            BuLoan.updated_at > last.at)) if last is not None else 1
        if not changed:
            _state["agent5"].update(last_reason=reason, skipped="Không có khoản vay nào thay đổi từ lần trước")
            result = dict(_state["agent5"])
        else:
            report, proposals = postaudit.run(session, SYSTEM_ACTOR)  # type: ignore[arg-type]
            _state["agent5"].update(last_run_at=_now(), last_reason=reason, report_id=report.id,
                                    proposals=len(proposals), skipped=None, error=None)
            result = dict(_state["agent5"])
    with _due_lock:  # an outcome that arrived during this run stays due
        if _agent5_due["at"] is not None and _agent5_due["at"] <= started:
            _agent5_due.update(at=None, reason=None)
            _state["agent5"]["due_reason"] = None
    return result


def status() -> dict[str, Any]:
    return {"enabled": enabled(),
            "agent4": {"interval_seconds": settings.buoyup_agent4_interval_seconds, **_state["agent4"]},
            "agent5": {"interval_seconds": settings.buoyup_agent5_interval_seconds, **_state["agent5"]}}


async def loop() -> None:
    """Background task started in the app lifespan. Only the worker holding the file lock runs it."""
    handle = LOCK_FILE.open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        _state["agent4"]["error"] = _state["agent5"]["error"] = "Vòng tự chạy đang chạy ở tiến trình khác"
        return
    a4_every = max(30, int(settings.buoyup_agent4_interval_seconds))
    a5_every = max(300, int(settings.buoyup_agent5_interval_seconds))
    next4 = time.time() + 20  # first round shortly after startup
    next5 = time.time() + 120
    while True:
        now = time.time()
        _state["agent4"]["next_run_at"] = datetime.fromtimestamp(next4, timezone.utc).isoformat()
        _state["agent5"]["next_run_at"] = datetime.fromtimestamp(next5, timezone.utc).isoformat()
        if now >= next4:
            next4 = now + a4_every
            try:
                await asyncio.to_thread(run_agent4, "schedule")
            except Exception as exc:  # noqa: BLE001 - keep the loop alive; the error shows in status()
                _state["agent4"]["error"] = f"{type(exc).__name__}: {exc}"[:300]
        due = _agent5_due["at"]
        if now >= next5 or (due is not None and now - due >= AGENT5_MIN_GAP_SECONDS):
            next5 = now + a5_every
            try:
                await asyncio.to_thread(run_agent5, _agent5_due["reason"] or "schedule")
            except Exception as exc:  # noqa: BLE001
                _state["agent5"]["error"] = f"{type(exc).__name__}: {exc}"[:300]
                with _due_lock:
                    _agent5_due.update(at=None, reason=None)
        await asyncio.sleep(5)
