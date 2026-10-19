"""/v4/shops: connect the seller's store before an application (HANDOVER 16.7, API_CONTRACT_V4.md §2b).

- ``GET  /v4/shops/platforms`` — supported platforms, whether each OAuth button can be shown, whether the
  registered-phone code (sample stores) is available.
- ``POST /v4/shops/connect/lookup`` ``{url | reg_no}`` — the store preview and the masked phone, no code sent.
- ``POST /v4/shops/connect/start`` ``{url | reg_no}`` — a sample store: a 6-digit code to its registered
  phone (sha256 kept, 5 minutes, at most 5 wrong codes). ``dev_code`` only in dev/demo/test and only when the
  phone is the seller's. Any other store: 400 ``SHOP_NOT_CONNECTED``.
- ``POST /v4/shops/connect/{id}/verify`` ``{code}`` — the right code makes a ``bu_shop_connections`` row.
- ``GET  /v4/shops/connect/oauth/{platform}/start`` — the platform's authorisation page (302, or JSON with
  ``?format=json``); 503 when BuoyUp has no app on that platform yet.
- ``GET  /v4/shops/connect/oauth/{platform}/callback?code&state`` — exchange, read the shop, save the
  connection, back to the seller app.
- ``GET  /v4/shops/connections``, ``DELETE /v4/shops/connections/{id}``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import _recent, _reserve
from app.data_sources import shop_connect, sources
from app.platform.config import settings
from app.platform.db.session import get_session
from app.platform.db.tables import utcnow
from app.platform.errors import api_error
from app.platform.security import require_roles
from app.platform.tables import BuShopConnection, BuShopConnectRequest, BuUser

router = APIRouter(prefix="/shops", tags=["v4-shops"])
_sellers = require_roles("seller")

OTP_TTL = timedelta(minutes=5)
OTP_MAX_WRONG = 5
OAUTH_TTL = timedelta(minutes=10)
MAX_STARTS = 60  # codes / authorisations per seller per 15 minutes (all stores together)
MAX_PER_SHOP = 5  # codes to one store's registered phone per seller per 15 minutes
WORKSPACE = "/app/giaodien/workspace.html"


class StartIn(BaseModel):
    url: str = Field(default="", max_length=500)
    reg_no: str = Field(default="", max_length=40)


class VerifyIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


def _hash(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()


def _platform_name(platform: str) -> str:
    return (sources.PLATFORMS.get(platform) or {}).get("name", platform)


def connection_view(c: BuShopConnection) -> dict[str, Any]:
    p = c.profile or {}
    return {"id": c.id, "platform": c.platform, "platform_name": _platform_name(c.platform), "shop_id": c.shop_id,
            "shop_name": c.shop_name, "url": c.url, "subject_name": p.get("subject_name") or "",
            "subject_reg_no": c.subject_reg_no, "owner_name": c.owner_name, "verified_via": c.verified_via,
            "verified_at": c.verified_at.isoformat() + "Z", "expires_at": c.expires_at.isoformat() + "Z",
            "phone_masked": p.get("registered_phone_masked") or "", "sample": bool(c.scenario)}


def _live(c: BuShopConnection | None) -> bool:
    return c is not None and c.revoked_at is None and c.expires_at > utcnow()


def usable_connection(session: Session, user: BuUser, connection_id: str) -> BuShopConnection:
    """The seller's own connection, not revoked or expired (application create)."""
    c = session.get(BuShopConnection, connection_id)
    if c is None or c.user_id != user.id:
        raise api_error(403, "SHOP_NOT_CONNECTED", "Cửa hàng này chưa được kết nối với tài khoản của bạn.",
                        {"field": "shop_connection_id"})
    if not _live(c):
        raise api_error(400, "SHOP_NOT_CONNECTED", "Kết nối cửa hàng đã hết hạn. Vui lòng kết nối lại cửa hàng.",
                        {"field": "shop_connection_id", "expired": True})
    return c


def connection_for_sample(session: Session, user: BuUser, scenario: str) -> BuShopConnection | None:
    rows = session.scalars(select(BuShopConnection).where(
        BuShopConnection.user_id == user.id, BuShopConnection.scenario == scenario,
        BuShopConnection.revoked_at.is_(None)).order_by(BuShopConnection.verified_at.desc()))
    return next((c for c in rows if _live(c)), None)


def data_for(c: BuShopConnection) -> tuple[str, dict[str, Any]]:
    """Agent 1's data for a connection: the sample dossier, or what the platform gave (OAuth)."""
    if c.scenario:
        if c.scenario not in sources.SCENARIOS or not sources.is_demo_env():
            raise api_error(400, "SHOP_NOT_CONNECTED", "Kết nối này không còn dùng được. Vui lòng kết nối lại cửa hàng.")
        return c.scenario, sources.scenario_data(c.scenario)
    return "connected", sources.data_from_profile(c.profile or {})


def summary(c: BuShopConnection) -> dict[str, Any]:
    """What an application keeps of its connection (doc.shop_connection)."""
    p = c.profile or {}
    return {"id": c.id, "platform": c.platform, "shop_id": c.shop_id, "shop_name": c.shop_name, "url": c.url,
            "verified_via": c.verified_via, "verified_at": c.verified_at.isoformat() + "Z",
            "phone_masked": p.get("registered_phone_masked") or "", "sample": bool(c.scenario)}


def _save_connection(session: Session, user: BuUser, profile: shop_connect.ShopProfile, via: str,
                     scenario: str | None) -> BuShopConnection:
    now = utcnow()
    existing = session.scalars(select(BuShopConnection).where(
        BuShopConnection.user_id == user.id, BuShopConnection.platform == profile.platform,
        BuShopConnection.shop_id == profile.shop_id, BuShopConnection.revoked_at.is_(None))).first()
    row = existing or BuShopConnection(id="shc_" + secrets.token_hex(8), user_id=user.id, platform=profile.platform,
                                       shop_id=profile.shop_id)
    row.url, row.shop_name = profile.url, profile.shop_name
    row.subject_reg_no, row.owner_name = profile.reg_no, profile.owner_name
    row.verified_via, row.verified_at = via, now
    row.expires_at = now + timedelta(days=int(settings.shop_connection_ttl_days))
    row.scenario, row.token_ref = scenario, None
    row.profile = profile.to_dict()
    if existing is None:
        session.add(row)
    return row


def _rate(session: Session, user: BuUser, shop_id: str = "") -> None:
    checks = [("shop-connect:" + user.id, MAX_STARTS)]
    if shop_id:
        checks.append((f"shop-connect:{user.id}:{shop_id}", MAX_PER_SHOP))
    for key, _limit in checks:
        _reserve(session, key)
    if any(_recent(session, key, failures_only=False) > limit for key, limit in checks):
        raise api_error(429, "RATE_LIMITED", "Bạn đã yêu cầu kết nối cửa hàng quá nhiều lần. Vui lòng chờ 15 phút.")


# --- endpoints ------------------------------------------------------------------------------------------------

@router.get("/platforms")
def list_platforms() -> dict:
    return {"platforms": shop_connect.platforms(), "registered_phone_code": shop_connect.demo.enabled()}


@router.get("/connections")
def list_connections(user: BuUser = Depends(_sellers), session: Session = Depends(get_session)) -> dict:
    rows = session.scalars(select(BuShopConnection).where(BuShopConnection.user_id == user.id)
                           .order_by(BuShopConnection.verified_at.desc()))
    return {"items": [connection_view(c) for c in rows if _live(c)]}


@router.get("/connections/{connection_id}")
def get_connection(connection_id: str, user: BuUser = Depends(_sellers), session: Session = Depends(get_session)) -> dict:
    return connection_view(usable_connection(session, user, connection_id))


@router.delete("/connections/{connection_id}")
def revoke_connection(connection_id: str, user: BuUser = Depends(_sellers),
                      session: Session = Depends(get_session)) -> dict:
    c = session.get(BuShopConnection, connection_id)
    if c is None or c.user_id != user.id:
        raise api_error(404, "NOT_FOUND", "Không tìm thấy kết nối cửa hàng.")
    c.revoked_at = c.revoked_at or utcnow()
    session.commit()
    return {"id": c.id, "revoked": True}


def _find(body: StartIn) -> str:
    """The sample store a link / registration number names, or the 400 the seller sees."""
    url, reg_no = body.url.strip(), body.reg_no.strip().upper()
    if not url and not reg_no:
        raise api_error(400, "VALIDATION_ERROR", "Dán link cửa hàng hoặc nhập số đăng ký kinh doanh.", {"field": "url"})
    platform = sources.detect_platform(url) if url else None
    if url and platform is None:
        raise api_error(400, "VALIDATION_ERROR", sources.UNSUPPORTED_LINK,
                        {"field": "url", "url": url[:300], "fallback": "reg_no"})
    scenario = shop_connect.demo.find(url=url, reg_no=reg_no)
    if scenario is None:
        err = sources.not_connected(url=url, reg_no=reg_no)
        err.detail.setdefault("details", {})["oauth"] = bool(platform and shop_connect.oauth_ready(platform))
        raise err
    return scenario


def _preview(profile: shop_connect.ShopProfile) -> dict[str, Any]:
    return {"platform": profile.platform, "platform_name": _platform_name(profile.platform),
            "shop": {"shop_name": profile.shop_name, "platform": profile.platform,
                     "subject_masked": shop_connect.mask_subject(profile.subject_name),
                     "reg_no_masked": shop_connect.mask_reg_no(profile.reg_no)},
            "phone_masked": profile.registered_phone_masked, "verified_via": shop_connect.demo.verified_via}


@router.post("/connect/lookup")
def lookup(body: StartIn, user: BuUser = Depends(_sellers)) -> dict:
    """The store and where the code would go, before any code is sent ("Xác nhận bạn là chủ cửa hàng")."""
    return _preview(shop_connect.demo.fetch_shop(_find(body)))


@router.post("/connect/start")
def start(body: StartIn, user: BuUser = Depends(_sellers), session: Session = Depends(get_session)) -> dict:
    scenario = _find(body)
    profile = shop_connect.demo.fetch_shop(scenario)
    _rate(session, user, profile.shop_id)
    now = utcnow()
    for old in session.scalars(select(BuShopConnectRequest).where(
            BuShopConnectRequest.user_id == user.id, BuShopConnectRequest.kind == "otp",
            BuShopConnectRequest.shop_id == profile.shop_id, BuShopConnectRequest.status == "pending")):
        old.status = "expired"  # one live code per store
    req_id = "scr_" + secrets.token_hex(8)
    code = f"{secrets.randbelow(10 ** 6):06d}"
    session.add(BuShopConnectRequest(
        id=req_id, user_id=user.id, kind="otp", platform=profile.platform, shop_id=profile.shop_id,
        scenario=scenario, secret_hash=_hash(req_id, code), created_at=now, expires_at=now + OTP_TTL,
        data={"phone_masked": profile.registered_phone_masked}))
    session.commit()
    out = {"connect_id": req_id, **_preview(profile), "expires_in": int(OTP_TTL.total_seconds()),
           "max_attempts": OTP_MAX_WRONG}
    # TODO(SMS): with an SMS provider the code is sent to the registered phone and never returned.
    if sources.is_demo_env() and shop_connect.demo.phone_reachable(scenario):
        out["dev_code"] = code
    return out


@router.post("/connect/{connect_id}/verify")
def verify(connect_id: str, body: VerifyIn, user: BuUser = Depends(_sellers),
           session: Session = Depends(get_session)) -> dict:
    req = session.get(BuShopConnectRequest, connect_id)
    if req is None or req.user_id != user.id or req.kind != "otp":
        raise api_error(404, "NOT_FOUND", "Không tìm thấy yêu cầu kết nối cửa hàng.")
    if req.status == "locked" or req.attempts >= OTP_MAX_WRONG:
        raise api_error(429, "OTP_LOCKED", "Bạn đã nhập sai 5 lần. Vui lòng gửi lại mã mới.")
    if req.status != "pending":
        raise api_error(400, "OTP_EXPIRED", "Mã này không còn dùng được. Vui lòng gửi lại mã mới.")
    if req.expires_at <= utcnow():
        req.status = "expired"
        session.commit()
        raise api_error(400, "OTP_EXPIRED", "Mã đã hết hạn. Vui lòng gửi lại mã mới.")
    if not hmac.compare_digest(req.secret_hash, _hash(req.id, body.code)):
        req.attempts += 1
        left = OTP_MAX_WRONG - req.attempts
        if left <= 0:
            req.status = "locked"
            session.commit()
            raise api_error(429, "OTP_LOCKED", "Bạn đã nhập sai 5 lần. Vui lòng gửi lại mã mới.")
        session.commit()
        raise api_error(400, "OTP_INVALID", f"Mã chưa đúng. Bạn còn {left} lần nhập.", {"attempts_left": left})
    req.status = "verified"
    if req.scenario not in sources.SCENARIOS:
        raise api_error(400, "SHOP_NOT_CONNECTED", "Cửa hàng này không còn trong danh sách.")
    profile = shop_connect.demo.fetch_shop(req.scenario)
    conn = _save_connection(session, user, profile, shop_connect.demo.verified_via, req.scenario)
    session.commit()
    shop = profile.to_dict()
    return {"connection": connection_view(conn), "shop": shop}


def _redirect_uri(request: Request, platform: str) -> str:
    base = settings.shop_oauth_redirect_base.strip().rstrip("/") or str(request.base_url).rstrip("/")
    return f"{base}/v4/shops/connect/oauth/{platform}/callback"


def _oauth(platform: str) -> Any:
    if platform not in sources.PLATFORMS:
        raise api_error(404, "NOT_FOUND", "Sàn không được hỗ trợ.")
    conn = shop_connect.oauth_connector(platform)
    if conn is None or not conn.ready():
        raise api_error(503, "SHOP_PLATFORM_NOT_CONNECTED", "Sàn này chưa được kết nối với BuoyUp.",
                        {"platform": platform, "configured": bool(conn is not None and conn.configured())})
    return conn


@router.get("/connect/oauth/{platform}/start")
def oauth_start(platform: str, request: Request, format: str = Query(default="redirect", pattern="^(redirect|json)$"),
                user: BuUser = Depends(_sellers), session: Session = Depends(get_session)) -> Any:
    conn = _oauth(platform)
    _rate(session, user)
    state = secrets.token_urlsafe(24)
    now = utcnow()
    session.add(BuShopConnectRequest(id="scr_" + secrets.token_hex(8), user_id=user.id, kind="oauth",
                                     platform=platform, secret_hash=_hash("state", state), created_at=now,
                                     expires_at=now + OAUTH_TTL))
    session.commit()
    url = conn.authorize_url(state, _redirect_uri(request, platform))
    if format == "json":
        return {"authorize_url": url, "platform": platform, "expires_in": int(OAUTH_TTL.total_seconds())}
    return RedirectResponse(url, status_code=302)


@router.get("/connect/oauth/{platform}/callback")
def oauth_callback(platform: str, request: Request, code: str = Query(default="", max_length=512),
                   state: str = Query(default="", max_length=128), error: str = Query(default="", max_length=80),
                   session: Session = Depends(get_session)) -> RedirectResponse:
    """The platform sends the seller's browser here (no BuoyUp token): ``state`` names the seller."""
    def back(**q: str) -> RedirectResponse:
        from urllib.parse import urlencode

        return RedirectResponse(WORKSPACE + "?" + urlencode(q), status_code=302)

    req = session.scalars(select(BuShopConnectRequest).where(
        BuShopConnectRequest.secret_hash == _hash("state", state), BuShopConnectRequest.kind == "oauth")).first() \
        if state else None
    if req is None or req.platform != platform or req.status != "pending" or req.expires_at <= utcnow():
        return back(shop_connect_error="STATE_INVALID")
    req.status = "failed"  # single use whatever happens next
    session.commit()
    if error or not code:
        return back(shop_connect_error="DENIED")
    try:
        conn = _oauth(platform)
        token = conn.exchange_code(code, _redirect_uri(request, platform))
        profile = conn.fetch_shop(token)
    except Exception:  # noqa: BLE001 - any platform failure is one answer for the seller; details in the log
        import logging

        logging.getLogger(__name__).warning("shop_oauth_failed", exc_info=True)
        return back(shop_connect_error="PLATFORM_ERROR")
    user = session.get(BuUser, req.user_id)
    if user is None:
        return back(shop_connect_error="STATE_INVALID")
    row = _save_connection(session, user, profile, "oauth", None)
    req.status = "verified"
    session.commit()
    return back(shop_connection=row.id)
