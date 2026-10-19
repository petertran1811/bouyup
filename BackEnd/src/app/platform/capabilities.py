"""Who may move money right now (review item 3, 16/10/2026).

Agent 4 is split in two: 4a pays out once with high privilege, 4b watches the loan for its whole life
with low privilege. The split is enforced at the functions that move money, not only by module layout:

- ``agent4a`` may pay out, and only with a one-off payout grant (``BuPayoutGrant``) bound to the
  application, the amount and the payee, valid ``payout.token_ttl_min`` minutes, revoked once used.
- ``standing_order`` is the core-banking standing order the borrower signed with the contract: it may
  debit the WeBank business account on due dates and when money arrives (simulated here).
- ``agent4b`` (monitoring) is read-only for money: any payout or debit attempted while it acts raises
  :class:`CapabilityDenied`. It may read, score, alert and notify.
- ``agent5`` (the seller reports) is read-only for money in the same way: it reads, writes reports, notifies.

Requests made by a person (the seller's prepayment, an officer's decision) run with no agent role and
keep the checks of their own routes.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar

_ROLE: ContextVar[str | None] = ContextVar("buoyup_agent_role", default=None)

ROLES = ("agent4a", "agent4b", "standing_order", "agent5")
READ_ONLY_ROLES = ("agent4b", "agent5")  # never debit (agent5: the seller reports, SELLER_SERVICES_PLAN §2)


class CapabilityDenied(PermissionError):
    """An agent tried something its role does not allow (e.g. 4b moving money)."""


@contextlib.contextmanager
def acting(role: str) -> Iterator[None]:
    if role not in ROLES:
        raise ValueError(f"unknown role {role}")
    token = _ROLE.set(role)
    try:
        yield
    finally:
        _ROLE.reset(token)


def current() -> str | None:
    return _ROLE.get()


def require(capability: str) -> None:
    """``payout`` only as ``agent4a``; ``debit`` never as ``agent4b``."""
    role = current()
    if capability == "payout" and role != "agent4a":
        raise CapabilityDenied(f"giải ngân chỉ do Agent 4a thực hiện (vai trò hiện tại: {role or 'không'})")
    if capability == "debit" and role in READ_ONLY_ROLES:
        who = "Agent 4b chỉ đọc và cảnh báo" if role == "agent4b" else "Agent 5 chỉ đọc và viết báo cáo"
        raise CapabilityDenied(f"{who}; trích nợ do lệnh định kỳ của core banking")
