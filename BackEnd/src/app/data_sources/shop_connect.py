"""Connecting a seller's store (HANDOVER 16.7): who owns the store, proven before an application exists.

A pasted link proves nothing (anyone can paste anyone's link), so an application is made from a *connection*:

- **Platform OAuth** (``verified_via = "oauth"``): the seller signs in on the platform's own page and grants
  BuoyUp read access to the shop; the platform hands back a code that only the shop's account can obtain.
  One connector per open platform below. A connector is on only when its app key and secret are configured
  (``<PLATFORM>_APP_KEY`` / ``<PLATFORM>_APP_SECRET`` in ``.env``); none is configured today.
- **Registered-phone code** (``verified_via = "otp_registered_phone"``): a 6-digit code goes to the phone
  number registered for the store on the platform. Today only the demo sample stores have one
  (``DemoShopConnector``, APP_ENV dev/demo/test), and no SMS provider is wired: the code is generated and
  checked on the server, and in those environments the response carries it as ``dev_code`` so the app can
  show it as the incoming text, except for a store whose phone is not the seller's ("other").

Never here: the platform's login page or logo, or the seller's platform password. Tokens are used once to
read the shop profile and are not stored (``token_ref`` stays null).

What a platform does not give (several hide the licence holder or the settlement account) stays empty and
the identity step reports it as ``not_comparable``. Each ``TODO(<platform>)`` marks what to confirm against
that platform's documentation once BuoyUp has an app there. Nothing in this module runs a network call at
import or in the tests (the HTTP client is injectable).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from app.data_sources import sources
from app.platform.config import settings


class ConnectorUnavailable(Exception):
    """The platform's connector is off (no app key) or not finished (an endpoint still to confirm)."""


class ConnectorError(Exception):
    """The platform answered with an error, or not at all."""


@dataclass
class ShopProfile:
    """The store as its platform describes it to its owner. Personal data is masked before it leaves here."""
    platform: str
    shop_id: str
    shop_name: str = ""
    url: str = ""
    subject_name: str = ""            # licence holder shown on the store (E-commerce Law art. 15)
    reg_no: str = ""                  # unified social credit code of the subject
    subject_type: str = ""            # individual | individual_business | company | "" (not given)
    owner_name: str = ""              # operator / legal representative
    owner_id_tail: str = ""           # last 4 digits of the owner's ID card, when the platform gives them
    registered_phone_masked: str = ""
    rating: float | None = None
    category: str = ""
    licenses: list[str] = field(default_factory=list)
    settlement_account: dict[str, str] | None = None   # {bank, tail, holder}
    opened: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ShopToken:
    access_token: str
    expires_in: int = 0
    refresh_token: str = ""
    shop_id: str = ""
    shop_name: str = ""
    owner_id: str = ""
    owner_name: str = ""


class ShopConnector(Protocol):
    platform: str

    def authorize_url(self, state: str, redirect_uri: str) -> str: ...

    def exchange_code(self, code: str, redirect_uri: str) -> ShopToken: ...

    def fetch_shop(self, token: ShopToken) -> ShopProfile: ...


def mask_phone(phone: str) -> str:
    """Only the last three digits are ever shown: "•••• 451"."""
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    return "•••• " + digits[-3:] if len(digits) >= 3 else ""


def mask_subject(name: str) -> str:
    """"Hộ kinh doanh Trần Vũ" → "Hộ kinh doanh Trần V•". The type of subject stays; the owner's given name
    keeps its first letter, so the owner recognises it and a stranger learns little."""
    name = str(name or "").strip()
    for prefix in ("Hộ kinh doanh ", "Công ty TNHH ", "Công ty cổ phần ", "Công ty "):
        if name.startswith(prefix):
            return prefix + mask_subject(name[len(prefix):])
    words = name.split()
    if not words:
        return ""
    if len(words) == 1:
        w = words[0]
        return w[:1] + "•" * max(1, min(3, len(w) - 1))
    return " ".join(words[:-1] + [words[-1][:1] + "•" * max(1, min(3, len(words[-1]) - 1))])


def mask_reg_no(reg_no: str) -> str:
    reg_no = str(reg_no or "")
    return reg_no[:4] + "••••••••" + reg_no[-3:] if len(reg_no) >= 10 else ("••••" if reg_no else "")


def _md5_upper(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest().upper()


def _concat_sorted(params: dict[str, Any]) -> str:
    return "".join(f"{k}{params[k]}" for k in sorted(params) if params[k] is not None and k != "sign")


# --- OAuth connectors -------------------------------------------------------------------------------------------

class OAuthConnector:
    """Base of the open-platform connectors. ``ready()``: keys configured and every endpoint confirmed."""

    platform = ""
    name = ""
    key_prefix = ""               # settings.<prefix>_app_key / _app_secret
    implemented = True            # False while an endpoint is still a TODO

    def __init__(self, client: httpx.Client | None = None, *, app_key: str | None = None,
                 app_secret: str | None = None) -> None:
        self._client = client
        self._key = app_key
        self._secret = app_secret

    @property
    def app_key(self) -> str:
        return (self._key if self._key is not None else getattr(settings, f"{self.key_prefix}_app_key", "")).strip()

    @property
    def app_secret(self) -> str:
        return (self._secret if self._secret is not None
                else getattr(settings, f"{self.key_prefix}_app_secret", "")).strip()

    def configured(self) -> bool:
        return bool(self.app_key and self.app_secret)

    def ready(self) -> bool:
        return self.configured() and self.implemented

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=15.0)
        return self._client

    def _json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ConnectorError(f"{self.name}: {type(exc).__name__}") from exc
        if not isinstance(body, dict):
            raise ConnectorError(f"{self.name}: phản hồi không phải JSON object")
        return body

    def _require(self) -> None:
        if not self.configured():
            raise ConnectorUnavailable(f"{self.name}: chưa cấu hình khóa ứng dụng")
        if not self.implemented:
            raise ConnectorUnavailable(f"{self.name}: connector chưa hoàn thiện (xem TODO)")

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        raise NotImplementedError

    def exchange_code(self, code: str, redirect_uri: str) -> ShopToken:
        raise NotImplementedError

    def fetch_shop(self, token: ShopToken) -> ShopProfile:
        raise NotImplementedError


class TaobaoConnector(OAuthConnector):
    """淘宝开放平台 (TOP), shared by Taobao and Tmall shops.

    - Authorise: ``https://oauth.taobao.com/authorize?response_type=code&client_id=<AppKey>&redirect_uri=…
      &state=…&view=web`` (the seller signs in on Taobao's page).
    - Token: ``POST https://oauth.taobao.com/token`` (form) ``grant_type=authorization_code``, ``code``,
      ``client_id``, ``client_secret``, ``redirect_uri`` → ``access_token``, ``expires_in``,
      ``taobao_user_id``, ``taobao_user_nick``.
    - Shop: TOP API ``taobao.shop.seller.get`` (``fields=sid,title,created``) on
      ``https://eco.taobao.com/router/rest``, signed MD5(secret + sorted key/value pairs + secret), upper case.
    TODO(taobao): the licence holder (主体), its credit code, the operator's name and the settlement (Alipay)
    account are not part of ``taobao.shop.seller.get``; they need the merchant-qualification APIs granted to
    lending partners (apply when registering the app), then fill subject_name / reg_no / owner_name /
    settlement_account below. Until then those stay empty (identity: ``not_comparable``)."""

    platform = "taobao"
    name = "Taobao"
    key_prefix = "taobao"
    AUTHORIZE = "https://oauth.taobao.com/authorize"
    TOKEN = "https://oauth.taobao.com/token"
    GATEWAY = "https://eco.taobao.com/router/rest"

    def __init__(self, platform: str = "taobao", **kw: Any) -> None:
        super().__init__(**kw)
        self.platform = platform
        self.name = "Tmall" if platform == "tmall" else "Taobao"

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        self._require()
        return self.AUTHORIZE + "?" + urlencode({"response_type": "code", "client_id": self.app_key,
                                                 "redirect_uri": redirect_uri, "state": state, "view": "web"})

    def exchange_code(self, code: str, redirect_uri: str) -> ShopToken:
        self._require()
        body = self._json(self.client.post(self.TOKEN, data={
            "grant_type": "authorization_code", "code": code, "client_id": self.app_key,
            "client_secret": self.app_secret, "redirect_uri": redirect_uri, "view": "web"}))
        if not body.get("access_token"):
            raise ConnectorError(f"{self.name}: không nhận được access_token ({body.get('error', '')})")
        return ShopToken(access_token=str(body["access_token"]), expires_in=int(body.get("expires_in") or 0),
                         refresh_token=str(body.get("refresh_token") or ""),
                         owner_id=str(body.get("taobao_user_id") or ""), owner_name=str(body.get("taobao_user_nick") or ""))

    def sign(self, params: dict[str, Any]) -> str:
        return _md5_upper(self.app_secret + _concat_sorted(params) + self.app_secret)

    def fetch_shop(self, token: ShopToken) -> ShopProfile:
        self._require()
        cst = datetime.now(timezone(timedelta(hours=8)))
        params = {"method": "taobao.shop.seller.get", "app_key": self.app_key, "session": token.access_token,
                  "timestamp": cst.strftime("%Y-%m-%d %H:%M:%S"), "format": "json", "v": "2.0",
                  "sign_method": "md5", "fields": "sid,title,created"}
        params["sign"] = self.sign(params)
        body = self._json(self.client.post(self.GATEWAY, data=params))
        shop = (body.get("shop_seller_get_response") or {}).get("shop") or {}
        if not shop.get("sid"):
            raise ConnectorError(f"{self.name}: không đọc được cửa hàng ({(body.get('error_response') or {}).get('msg', '')})")
        sid = str(shop["sid"])
        return ShopProfile(platform=self.platform, shop_id=sid, shop_name=str(shop.get("title") or ""),
                           url=f"https://shop{sid}.taobao.com" if self.platform == "taobao" else "",
                           opened=str(shop.get("created") or "")[:10] or None)


class JdConnector(OAuthConnector):
    """京东开放平台 (JOS).

    - Authorise: ``https://open-oauth.jd.com/oauth2/to_login?app_key=…&response_type=code&redirect_uri=…
      &state=…&scope=snsapi_base``.
    - Token: ``GET https://open-oauth.jd.com/oauth2/access_token?app_key=…&app_secret=…
      &grant_type=authorization_code&code=…`` → ``access_token``, ``expires_in``, ``refresh_token``.
    - Shop: ``jingdong.vender.shop.query`` on ``https://api.jd.com/routerjson`` (``360buy_param_json``),
      signed MD5(secret + sorted key/value pairs + secret), upper case.
    TODO(jd): confirm the response field names of ``jingdong.vender.shop.query`` (shop_id, shop_name,
    open_time) for the app type BuoyUp gets; the licence holder needs the vendor-qualification API."""

    platform = "jd"
    name = "JD"
    key_prefix = "jd"
    AUTHORIZE = "https://open-oauth.jd.com/oauth2/to_login"
    TOKEN = "https://open-oauth.jd.com/oauth2/access_token"
    GATEWAY = "https://api.jd.com/routerjson"

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        self._require()
        return self.AUTHORIZE + "?" + urlencode({"app_key": self.app_key, "response_type": "code",
                                                 "redirect_uri": redirect_uri, "state": state,
                                                 "scope": "snsapi_base"})

    def exchange_code(self, code: str, redirect_uri: str) -> ShopToken:
        self._require()
        body = self._json(self.client.get(self.TOKEN, params={
            "app_key": self.app_key, "app_secret": self.app_secret, "grant_type": "authorization_code",
            "code": code}))
        if not body.get("access_token"):
            raise ConnectorError(f"JD: không nhận được access_token ({body.get('msg', '')})")
        return ShopToken(access_token=str(body["access_token"]), expires_in=int(body.get("expires_in") or 0),
                         refresh_token=str(body.get("refresh_token") or ""), owner_id=str(body.get("uid") or ""))

    def sign(self, params: dict[str, Any]) -> str:
        return _md5_upper(self.app_secret + _concat_sorted(params) + self.app_secret)

    def fetch_shop(self, token: ShopToken) -> ShopProfile:
        self._require()
        cst = datetime.now(timezone(timedelta(hours=8)))
        params = {"method": "jingdong.vender.shop.query", "access_token": token.access_token,
                  "app_key": self.app_key, "timestamp": cst.strftime("%Y-%m-%d %H:%M:%S"), "v": "2.0",
                  "360buy_param_json": "{}", "sign_method": "md5"}
        params["sign"] = self.sign(params)
        body = self._json(self.client.post(self.GATEWAY, data=params))
        result = ((body.get("jingdong_vender_shop_query_responce") or {}).get("shop_jos_result") or {})
        if not result.get("shop_id"):
            raise ConnectorError("JD: không đọc được cửa hàng")
        return ShopProfile(platform="jd", shop_id=str(result["shop_id"]), shop_name=str(result.get("shop_name") or ""),
                           url=f"https://mall.jd.com/index-{result['shop_id']}.html",
                           opened=str(result.get("open_time") or "")[:10] or None)


class PinduoduoConnector(OAuthConnector):
    """拼多多开放平台 (merchant apps).

    - Authorise: ``https://fuwu.pinduoduo.com/service-market/auth?response_type=code&client_id=…
      &redirect_uri=…&state=…``.
    - Token: ``pdd.pop.auth.token.create`` on ``https://gw-api.pinduoduo.com/api/router`` (``code``) →
      ``access_token``, ``expires_in``, ``owner_id``, ``owner_name``.
    - Shop: ``pdd.mall.info.get`` → ``mall_id``, ``mall_name``, ``merchant_type`` (1 personal, 2 company …).
    Requests are signed MD5(client_secret + sorted key/value pairs + client_secret), upper case.
    TODO(pinduoduo): licence holder and settlement account need the merchant-qualification permission."""

    platform = "pinduoduo"
    name = "Pinduoduo"
    key_prefix = "pinduoduo"
    AUTHORIZE = "https://fuwu.pinduoduo.com/service-market/auth"
    GATEWAY = "https://gw-api.pinduoduo.com/api/router"
    MERCHANT_TYPES = {1: "individual", 2: "company"}

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        self._require()
        return self.AUTHORIZE + "?" + urlencode({"response_type": "code", "client_id": self.app_key,
                                                 "redirect_uri": redirect_uri, "state": state})

    def sign(self, params: dict[str, Any]) -> str:
        return _md5_upper(self.app_secret + _concat_sorted(params) + self.app_secret)

    def _call(self, kind: str, **extra: Any) -> dict[str, Any]:
        params = {"type": kind, "client_id": self.app_key, "timestamp": str(int(time.time())), "data_type": "JSON",
                  **extra}
        params["sign"] = self.sign(params)
        body = self._json(self.client.post(self.GATEWAY, data=params))
        if "error_response" in body:
            raise ConnectorError(f"Pinduoduo: {(body['error_response'] or {}).get('error_msg', '')}")
        return body

    def exchange_code(self, code: str, redirect_uri: str) -> ShopToken:
        self._require()
        out = self._call("pdd.pop.auth.token.create", code=code).get("pop_auth_token_create_response") or {}
        if not out.get("access_token"):
            raise ConnectorError("Pinduoduo: không nhận được access_token")
        return ShopToken(access_token=str(out["access_token"]), expires_in=int(out.get("expires_in") or 0),
                         refresh_token=str(out.get("refresh_token") or ""), owner_id=str(out.get("owner_id") or ""),
                         owner_name=str(out.get("owner_name") or ""))

    def fetch_shop(self, token: ShopToken) -> ShopProfile:
        self._require()
        mall = self._call("pdd.mall.info.get", access_token=token.access_token).get("mall_info_get_response") or {}
        if not mall.get("mall_id"):
            raise ConnectorError("Pinduoduo: không đọc được cửa hàng")
        return ShopProfile(platform="pinduoduo", shop_id=str(mall["mall_id"]), shop_name=str(mall.get("mall_name") or ""),
                           url=f"https://mobile.yangkeduo.com/mall_page.html?mall_id={mall['mall_id']}",
                           subject_type=self.MERCHANT_TYPES.get(int(mall.get("merchant_type") or 0), ""))


class DouyinConnector(OAuthConnector):
    """抖店开放平台 (op.jinritemai.com).

    - Token: ``GET https://openapi-fxg.jinritemai.com/token/create`` with ``app_key``, ``method=token.create``,
      ``param_json={"code":…,"grant_type":"authorization_code"}`` (keys sorted, no spaces), ``timestamp``,
      ``v=2``, ``sign_method=md5`` and ``sign`` = md5(secret + "app_key"… "method"… "param_json"… "timestamp"…
      "v2" + secret), lower case → ``data.access_token``, ``data.shop_id``, ``data.shop_name``.
    TODO(douyin): the authorisation link depends on how the app is published (服务市场 service vs. 自用型):
    confirm the URL and its parameters (``DOUYIN_SERVICE_ID``) with 抖店 before turning this connector on;
    until then ``implemented = False`` and the button stays hidden. The licence holder needs ``shop.getShopInfo``
    style permissions (confirm the API name)."""

    platform = "douyin"
    name = "Douyin"
    key_prefix = "douyin"
    implemented = False
    TOKEN = "https://openapi-fxg.jinritemai.com/token/create"

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        raise NotImplementedError("TODO(douyin): xác nhận link cấp quyền của 抖店服务市场")

    def sign(self, method: str, param_json: str, timestamp: str) -> str:
        raw = (f"{self.app_secret}app_key{self.app_key}method{method}param_json{param_json}"
               f"timestamp{timestamp}v2{self.app_secret}")
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def exchange_code(self, code: str, redirect_uri: str) -> ShopToken:
        if not self.configured():
            raise ConnectorUnavailable("Douyin: chưa cấu hình khóa ứng dụng")
        method = "token.create"
        param_json = json.dumps({"code": code, "grant_type": "authorization_code"}, sort_keys=True,
                                separators=(",", ":"))
        timestamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
        body = self._json(self.client.get(self.TOKEN, params={
            "app_key": self.app_key, "method": method, "param_json": param_json, "timestamp": timestamp, "v": "2",
            "sign_method": "md5", "sign": self.sign(method, param_json, timestamp)}))
        data = body.get("data") or {}
        if not data.get("access_token"):
            raise ConnectorError(f"Douyin: {body.get('message') or body.get('msg') or 'không nhận được access_token'}")
        return ShopToken(access_token=str(data["access_token"]), expires_in=int(data.get("expires_in") or 0),
                         refresh_token=str(data.get("refresh_token") or ""), shop_id=str(data.get("shop_id") or ""),
                         shop_name=str(data.get("shop_name") or ""))

    def fetch_shop(self, token: ShopToken) -> ShopProfile:
        if not token.shop_id:
            raise ConnectorError("Douyin: token không kèm shop_id")
        return ShopProfile(platform="douyin", shop_id=token.shop_id, shop_name=token.shop_name,
                           url=f"https://haohuo.jinritemai.com/views/shop/index?id={token.shop_id}")


class KuaishouConnector(OAuthConnector):
    """快手电商开放平台 (open.kwaixiaodian.com).

    TODO(kuaishou): confirm the authorisation URL (app_id, scope list, response_type, state), the token
    endpoint (``/oauth2/access_token``, grant type) and the shop-info API with 快手 before turning it on;
    ``implemented = False`` keeps the button hidden even with keys configured."""

    platform = "kuaishou"
    name = "Kuaishou"
    key_prefix = "kuaishou"
    implemented = False

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        raise NotImplementedError("TODO(kuaishou): xác nhận link cấp quyền")

    def exchange_code(self, code: str, redirect_uri: str) -> ShopToken:
        raise NotImplementedError("TODO(kuaishou): xác nhận endpoint đổi code lấy token")

    def fetch_shop(self, token: ShopToken) -> ShopProfile:
        raise NotImplementedError("TODO(kuaishou): xác nhận API thông tin cửa hàng")


_FACTORIES = {"douyin": DouyinConnector, "taobao": lambda: TaobaoConnector("taobao"),
              "tmall": lambda: TaobaoConnector("tmall"), "jd": JdConnector, "pinduoduo": PinduoduoConnector,
              "kuaishou": KuaishouConnector}
_overrides: dict[str, Any] = {}


def set_connector(platform: str, connector: Any | None) -> None:
    """Install a connector for a platform (tests); None restores the configured one."""
    if connector is None:
        _overrides.pop(platform, None)
    else:
        _overrides[platform] = connector


def oauth_connector(platform: str) -> Any | None:
    if platform in _overrides:
        return _overrides[platform]
    factory = _FACTORIES.get(platform)
    return factory() if factory else None


def oauth_ready(platform: str) -> bool:
    conn = oauth_connector(platform)
    return bool(conn is not None and conn.ready())


# --- registered-phone code (demo sample stores) --------------------------------------------------------------

class DemoShopConnector:
    """The 14 sample stores (``sources.SCENARIOS``), APP_ENV dev/demo/test only. Ownership is proven with a code
    sent to the store's registered phone (sample data; ``phone_reachable`` False for "other": the phone is the
    real owner's, so the code never reaches the person who pasted the link)."""

    verified_via = "otp_registered_phone"

    @staticmethod
    def enabled() -> bool:
        return sources.is_demo_env()

    def find(self, url: str = "", reg_no: str = "") -> str | None:
        return sources.find_sample(url=url, reg_no=reg_no) if self.enabled() else None

    @staticmethod
    def registered_phone(scenario: str) -> str:
        return sources.SCENARIOS[scenario][3]["shop"]["registered_phone"]

    @staticmethod
    def phone_reachable(scenario: str) -> bool:
        return bool(sources.SCENARIOS[scenario][3]["shop"]["phone_reachable"])

    def fetch_shop(self, scenario: str) -> ShopProfile:
        data = sources.SCENARIOS[scenario][3]
        st, shop, reg = data["store"], data["shop"], data.get("registry") or {}
        return ShopProfile(platform=st["platform"], shop_id=shop["shop_id"], shop_name=shop["shop_name"],
                           url=shop["url"], subject_name=st["entity"], reg_no=st["reg_no"],
                           subject_type=shop["subject_type"], owner_name=shop["owner_name"],
                           owner_id_tail=shop["owner_id_tail"],
                           registered_phone_masked=mask_phone(shop["registered_phone"]), rating=st["rating"],
                           category=st["category"], licenses=list(st["licenses"]),
                           settlement_account=dict(shop["settlement_account"]),
                           opened=st.get("opened") or reg.get("registered"))


demo = DemoShopConnector()


def platforms() -> list[dict[str, Any]]:
    """Every supported platform and whether its OAuth button can be shown."""
    return [{"platform": pid, "name": info["name"], "oauth": oauth_ready(pid)} for pid, info in sources.PLATFORMS.items()]
