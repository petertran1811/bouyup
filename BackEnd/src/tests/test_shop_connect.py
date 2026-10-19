"""Store connection (HANDOVER 16.7): an application is made from a store the seller proved is theirs.

- Registered-phone code for the sample stores (server-side: sha256, 5 minutes, 5 wrong codes), "other" gets no code;
- a link that is no sample and no connected store answers SHOP_NOT_CONNECTED (no copy of chị Lan's dossier);
- applications need the seller's own live connection (SHOP_CONNECT_REQUIRED, on here);
- entity_match is computed: ownership proof AND the CCCD against the store's owner;
- the platform OAuth connectors are off without keys (503) and build their authorisation links offline.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.data_sources import shop_connect, sources
from app.platform.config import settings
from app.platform.db.session import session_scope
from app.platform.db.tables import utcnow
from app.platform.security import hash_password
from app.platform.tables import BuApplication, BuShopConnection, BuShopConnectRequest, BuUser, save_json
from tests import lc
from tests.conftest import login

LAN = sources.demo_url("lan")


@pytest.fixture(autouse=True)
def required(monkeypatch) -> None:
    monkeypatch.setattr(settings, "shop_connect_required", True)


def _start(c, h, **body: str) -> Any:
    return c.post("/v4/shops/connect/start", headers=h, json=body)


def _connect(c, h, url: str = LAN) -> dict[str, Any]:
    s = lc.ok(_start(c, h, url=url))
    return lc.ok(c.post(f"/v4/shops/connect/{s['connect_id']}/verify", headers=h, json={"code": s["dev_code"]}))


def _wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


def _second_seller(client) -> dict[str, str]:
    with session_scope() as s:
        s.add(BuUser(id="usr_" + secrets.token_hex(6), email="vu@example.com", password_hash=hash_password("Vu@2026!x"),
                     display_name="Trần Vũ", phone="+8613925517451", role="seller"))
    return login(client, "vu@example.com", "Vu@2026!x")


def _card(app_id: str, number: str, name: str = "示例用户") -> None:
    """A CCCD front/back as the OCR would have read them (no image needed)."""
    with session_scope() as s:
        row = s.get(BuApplication, app_id)
        doc = dict(row.doc)
        doc["cccd_scans"] = {
            "front": {"engine": "rapidocr", "warnings": [], "fields": {
                "name": {"value": name}, "id_number": {"value": number},
                "id_number_validation": {"format_valid": True, "checksum_valid": True, "birth_date": "1990-01-01"}}},
            "back": {"engine": "rapidocr", "warnings": [], "fields": {"validity_period": {"value": "2020.01.01-2040.01.01"}}}}
        save_json(row, "doc", doc)


# --- registered-phone code --------------------------------------------------------------------------------------

def test_code_right_wrong_and_the_connection(bu_client, as_seller):
    s = lc.ok(_start(bu_client, as_seller, url=LAN))
    assert s["phone_masked"] == "•••• 812" and s["platform"] == "douyin" and len(s["dev_code"]) == 6
    assert s["shop"]["subject_masked"] == "Hộ kinh doanh Lâm L••" and "Lâm Lan" not in str(s["shop"])
    with session_scope() as db:  # only the hash of the code is kept
        req = db.get(BuShopConnectRequest, s["connect_id"])
        assert s["dev_code"] not in req.secret_hash and len(req.secret_hash) == 64
    bad = bu_client.post(f"/v4/shops/connect/{s['connect_id']}/verify", headers=as_seller, json={"code": _wrong(s["dev_code"])})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "OTP_INVALID"
    assert bad.json()["error"]["details"]["attempts_left"] == 4
    ok = lc.ok(bu_client.post(f"/v4/shops/connect/{s['connect_id']}/verify", headers=as_seller, json={"code": s["dev_code"]}))
    conn = ok["connection"]
    assert conn["verified_via"] == "otp_registered_phone" and conn["sample"] and conn["shop_id"] == "58812"
    assert ok["shop"]["owner_name"] == "Lâm Lan" and ok["shop"]["registered_phone_masked"] == "•••• 812"
    assert "+86" not in str(ok)  # the full phone number never leaves the server
    again = bu_client.post(f"/v4/shops/connect/{s['connect_id']}/verify", headers=as_seller, json={"code": s["dev_code"]})
    assert again.status_code == 400  # single use
    listed = bu_client.get("/v4/shops/connections", headers=as_seller).json()["items"]
    assert [x["id"] for x in listed] == [conn["id"]]


def test_code_expires_after_five_minutes(bu_client, as_seller):
    s = lc.ok(_start(bu_client, as_seller, url=LAN))
    with session_scope() as db:
        db.get(BuShopConnectRequest, s["connect_id"]).expires_at = utcnow() - timedelta(seconds=1)
    r = bu_client.post(f"/v4/shops/connect/{s['connect_id']}/verify", headers=as_seller, json={"code": s["dev_code"]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "OTP_EXPIRED"


def test_five_wrong_codes_lock_the_request(bu_client, as_seller):
    s = lc.ok(_start(bu_client, as_seller, url=LAN))
    codes = []
    for _ in range(5):
        r = bu_client.post(f"/v4/shops/connect/{s['connect_id']}/verify", headers=as_seller, json={"code": _wrong(s["dev_code"])})
        codes.append(r.json()["error"]["code"])
    assert codes == ["OTP_INVALID"] * 4 + ["OTP_LOCKED"]
    r = bu_client.post(f"/v4/shops/connect/{s['connect_id']}/verify", headers=as_seller, json={"code": s["dev_code"]})
    assert r.status_code == 429 and r.json()["error"]["code"] == "OTP_LOCKED"


def test_new_code_replaces_the_old_one(bu_client, as_seller):
    first = lc.ok(_start(bu_client, as_seller, url=LAN))
    lc.ok(_start(bu_client, as_seller, url=LAN))
    r = bu_client.post(f"/v4/shops/connect/{first['connect_id']}/verify", headers=as_seller, json={"code": first["dev_code"]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "OTP_EXPIRED"


def test_someone_elses_store_gets_no_code(bu_client, as_seller):
    s = lc.ok(_start(bu_client, as_seller, url=sources.demo_url("other")))
    assert "dev_code" not in s and s["phone_masked"] == "•••• 451"
    assert s["shop"]["subject_masked"] == "Hộ kinh doanh Trần V•"
    r = bu_client.post(f"/v4/shops/connect/{s['connect_id']}/verify", headers=as_seller, json={"code": "000000"})
    assert r.status_code in (400, 429)
    # Neither the link nor the registration number opens an application without the connection.
    for body in ({"store_urls": [sources.demo_url("other")]}, {"reg_no": "92440106MA9TRANV2Q"}):
        r = bu_client.post("/v4/applications", headers=as_seller, json=body)
        assert r.status_code == 400 and r.json()["error"]["code"] == "SHOP_NOT_CONNECTED"
    stores = {x["scenario"]: x for x in bu_client.get("/v4/public/demo-stores").json()["stores"]}
    assert stores["other"]["check"] == {"status": "not_connected", "stage": "connect"}
    assert "451" in stores["other"]["expect"]


def test_unknown_link_is_not_connected_and_never_copies_lan(bu_client, as_seller):
    for body in ({"url": "https://shop.tmall.com/abc"}, {"reg_no": "91110000ABCDEFGH1X"}):
        r = _start(bu_client, as_seller, **body)
        assert r.status_code == 400 and r.json()["error"]["code"] == "SHOP_NOT_CONNECTED", r.text
    r = bu_client.post("/v4/applications", headers=as_seller, json={"store_urls": ["https://shop.tmall.com/abc"]})
    err = r.json()["error"]
    assert r.status_code == 400 and err["code"] == "SHOP_NOT_CONNECTED"
    assert err["message"] == "Chưa kết nối được cửa hàng này. Hãy kết nối cửa hàng qua sàn, hoặc chọn một gian hàng mẫu."
    r = bu_client.post("/v4/applications", headers=as_seller, json={"reg_no": "91110000ABCDEFGH1X"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "SHOP_NOT_CONNECTED"
    r = _start(bu_client, as_seller, url="https://example.com/x")
    assert r.status_code == 400 and r.json()["error"]["details"]["fallback"] == "reg_no"
    with session_scope() as db:
        assert db.query(BuApplication).count() == 0


def test_registration_number_of_a_sample_connects_the_same_store(bu_client, as_seller):
    s = lc.ok(_start(bu_client, as_seller, reg_no="92330110MA2HYAQ71K"))
    assert s["platform"] == "tmall" and s["phone_masked"] == "•••• 307"


# --- applications need the seller's own connection ---------------------------------------------------------------

def test_application_needs_a_connection_of_the_same_seller(bu_client, as_seller):
    r = bu_client.post("/v4/applications", headers=as_seller, json={"store_urls": [LAN]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "SHOP_NOT_CONNECTED"
    assert r.json()["error"]["details"]["connect"] is True
    conn = _connect(bu_client, as_seller)["connection"]
    a = lc.ok(bu_client.post("/v4/applications", headers=as_seller, json={"shop_connection_id": conn["id"]}))
    assert a["status"] == "draft" and a["shop_connection"]["verified_via"] == "otp_registered_phone"
    assert a["stores"][0]["verified_via"] == "otp_registered_phone" and a["stores"][0]["url"] == LAN
    # The sample link alone now finds the live connection.
    b = lc.ok(bu_client.post("/v4/applications", headers=as_seller, json={"store_urls": [LAN]}))
    assert b["shop_connection"]["id"] == conn["id"]
    other = _second_seller(bu_client)
    r = bu_client.post("/v4/applications", headers=other, json={"shop_connection_id": conn["id"]})
    assert r.status_code == 403 and r.json()["error"]["code"] == "SHOP_NOT_CONNECTED"
    r = bu_client.post("/v4/applications", headers=other, json={"store_urls": [LAN]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "SHOP_NOT_CONNECTED"
    with session_scope() as db:
        db.get(BuShopConnection, conn["id"]).expires_at = utcnow() - timedelta(minutes=1)
    r = bu_client.post("/v4/applications", headers=as_seller, json={"shop_connection_id": conn["id"]})
    assert r.status_code == 400 and r.json()["error"]["details"]["expired"] is True


def test_agent1_records_the_connection_and_the_evidence_levels(bu_client, as_seller, as_officer):
    conn = _connect(bu_client, as_seller)["connection"]
    a = lc.ok(bu_client.post("/v4/applications", headers=as_seller, json={"shop_connection_id": conn["id"]}))
    a = lc.ok(bu_client.post(f"/v4/applications/{a['id']}/identity", headers=as_seller, json={"cccd": True, "face": True}))
    full = bu_client.get(f"/v4/applications/{a['id']}", headers=as_officer).json()
    v = full["verification"]
    assert v["evidence"] == {"store": "sample_data", "registry": "sample_data", "identity": "registered_phone_otp",
                             "revenue": "sample_data"}
    tools = [t["tool"] for t in v["tool_calls"]]
    assert tools[:3] == ["connect_shop", "lookup_public_store", "lookup_business_registry"]
    first = v["tool_calls"][0]
    assert first["output"]["verified_via"] == "otp_registered_phone" and first["output"]["verified_at"]
    assert first["input"] == {"platform": "douyin", "shop_id": "58812"}
    result = full["identity"]["result"]
    assert result["entity_match"] is True and result["ownership"]["proven"] and result["account_owner_match"] is True
    assert result["name_check"] == "no_card" and v["steps"][0]["tool"].startswith("connect_shop")


# --- entity_match is computed ---------------------------------------------------------------------------------------

def test_sample_card_matches_the_sample_owner(bu_client, as_seller, as_officer):
    conn = _connect(bu_client, as_seller)["connection"]
    a = lc.ok(bu_client.post("/v4/applications", headers=as_seller, json={"shop_connection_id": conn["id"]}))
    _card(a["id"], "440106199001011235")  # Frontend/giaodien/mau-cccd: 示例用户
    a = lc.ok(bu_client.post(f"/v4/applications/{a['id']}/identity", headers=as_seller, json={"cccd": True, "face": True}))
    assert a["status"] == "identified"
    result = bu_client.get(f"/v4/applications/{a['id']}", headers=as_officer).json()["identity"]["result"]
    # The owner's registered name is in Vietnamese reading (Lâm Lan): not comparable with 示例用户, the ID tail is.
    assert result["name_check"] == "not_comparable" and result["id_tail_check"] == "match"


def test_a_card_that_is_not_the_owners_is_law_id_mismatch(bu_client, as_seller):
    conn = _connect(bu_client, as_seller)["connection"]
    a = lc.ok(bu_client.post("/v4/applications", headers=as_seller, json={"shop_connection_id": conn["id"]}))
    _card(a["id"], "11010519491231002X")  # a valid number that is not chị Lan's
    a = lc.ok(bu_client.post(f"/v4/applications/{a['id']}/identity", headers=as_seller, json={"cccd": True, "face": True}))
    assert a["status"] == "rejected"
    assert "LAW_ID_MISMATCH" in {f["code"] for f in a["verification"]["flags"]}
    assert "4 số cuối CCCD" in a["verification"]["reason"]["factor"]


def test_without_connection_requirement_the_card_still_decides(bu_client, as_seller, monkeypatch):
    """SHOP_CONNECT_REQUIRED=false (older tests, a pilot): the link is "self_declared"; "other" is then caught by
    the CCCD (the sample card ends in 1235, Trần Vũ's in 6620)."""
    monkeypatch.setattr(settings, "shop_connect_required", False)
    a = lc.ok(bu_client.post("/v4/applications", headers=as_seller, json={"store_urls": [sources.demo_url("other")]}))
    _card(a["id"], "440106199001011235")
    a = lc.ok(bu_client.post(f"/v4/applications/{a['id']}/identity", headers=as_seller, json={"cccd": True, "face": True}))
    assert a["status"] == "rejected" and "LAW_ID_MISMATCH" in {f["code"] for f in a["verification"]["flags"]}
    assert a["identity"]["result"]["ownership"]["verified_via"] == "self_declared"


def test_compare_card_name_handles_hanzi_and_vietnamese_reading():
    assert sources.compare_card_name("周雅琴", ["Chu Nhã Cầm", "Hộ kinh doanh Chu Nhã Cầm"]) == "not_comparable"
    assert sources.compare_card_name("周雅琴", ["周雅琴"]) == "match"
    assert sources.compare_card_name("示例用户", ["王小明", "王小明个体工商户"]) == "mismatch"
    assert sources.compare_card_name("", ["王小明"]) == "not_comparable"
    unproven = sources.verify_identity(sources.SCENARIOS["lan"][3], {"verified_via": "self_declared", "accepted": False})
    assert unproven["entity_match"] is False and unproven["mismatch"]


# --- platform OAuth -----------------------------------------------------------------------------------------------

def test_oauth_is_off_without_keys(bu_client, as_seller):
    body = bu_client.get("/v4/shops/platforms").json()
    assert {p["platform"] for p in body["platforms"]} == set(sources.PLATFORMS)
    assert not any(p["oauth"] for p in body["platforms"]) and body["registered_phone_code"] is True
    for platform in sources.PLATFORMS:
        r = bu_client.get(f"/v4/shops/connect/oauth/{platform}/start?format=json", headers=as_seller)
        assert r.status_code == 503 and r.json()["error"]["code"] == "SHOP_PLATFORM_NOT_CONNECTED"
        assert r.json()["error"]["message"] == "Sàn này chưa được kết nối với BuoyUp."


def test_oauth_links_are_built_from_the_keys_offline(bu_client, as_seller, monkeypatch):
    monkeypatch.setattr(settings, "taobao_app_key", "test-key")
    monkeypatch.setattr(settings, "taobao_app_secret", "test-secret")
    monkeypatch.setattr(settings, "douyin_app_key", "dy-key")
    monkeypatch.setattr(settings, "douyin_app_secret", "dy-secret")
    oauth = {p["platform"]: p["oauth"] for p in bu_client.get("/v4/shops/platforms").json()["platforms"]}
    assert oauth["tmall"] and oauth["taobao"] and not oauth["douyin"] and not oauth["jd"]  # douyin: link TODO
    r = lc.ok(bu_client.get("/v4/shops/connect/oauth/tmall/start?format=json", headers=as_seller))
    url = urlparse(r["authorize_url"])
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert url.netloc == "oauth.taobao.com" and url.path == "/authorize"
    assert q["client_id"] == "test-key" and q["response_type"] == "code" and q["view"] == "web" and len(q["state"]) > 20
    assert q["redirect_uri"] == "http://testserver/v4/shops/connect/oauth/tmall/callback"
    assert "test-secret" not in r["authorize_url"]
    redirect = bu_client.get("/v4/shops/connect/oauth/taobao/start", headers=as_seller, follow_redirects=False)
    assert redirect.status_code == 302 and redirect.headers["location"].startswith("https://oauth.taobao.com/authorize?")
    assert bu_client.get("/v4/shops/connect/oauth/douyin/start?format=json", headers=as_seller).status_code == 503
    jd = shop_connect.JdConnector(app_key="k", app_secret="s").authorize_url("st", "https://b/cb")
    assert jd.startswith("https://open-oauth.jd.com/oauth2/to_login?") and "app_key=k" in jd and "state=st" in jd
    pdd = shop_connect.PinduoduoConnector(app_key="k", app_secret="s").authorize_url("st", "https://b/cb")
    assert pdd.startswith("https://fuwu.pinduoduo.com/service-market/auth?") and "client_id=k" in pdd
    with pytest.raises(NotImplementedError):
        shop_connect.KuaishouConnector(app_key="k", app_secret="s").authorize_url("st", "https://b/cb")


def test_taobao_exchange_and_shop_read_through_a_mock_transport():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "oauth.taobao.com":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600, "taobao_user_id": "7",
                                             "taobao_user_nick": "nick"})
        return httpx.Response(200, json={"shop_seller_get_response": {"shop": {"sid": 123, "title": "Shop A",
                                                                               "created": "2021-05-01 10:00:00"}}})

    conn = shop_connect.TaobaoConnector("taobao", client=httpx.Client(transport=httpx.MockTransport(handler)),
                                        app_key="k", app_secret="s")
    token = conn.exchange_code("the-code", "https://b/cb")
    profile = conn.fetch_shop(token)
    assert token.access_token == "tok" and profile.shop_id == "123" and profile.opened == "2021-05-01"
    form = parse_qs(seen[1].content.decode())
    params = {k: v[0] for k, v in form.items()}
    assert params["method"] == "taobao.shop.seller.get" and params["sign"] == conn.sign(params)
    assert len(seen) == 2


class FakePdd:
    """A platform connector as it would answer once BuoyUp has keys (no network)."""
    platform = "pinduoduo"

    def __init__(self, owner: str = "王小明") -> None:
        self.owner = owner

    def configured(self) -> bool:
        return True

    def ready(self) -> bool:
        return True

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        return "https://auth.example.invalid/?state=" + state

    def exchange_code(self, code: str, redirect_uri: str) -> shop_connect.ShopToken:
        assert code == "good-code"
        return shop_connect.ShopToken(access_token="t")

    def fetch_shop(self, token: shop_connect.ShopToken) -> shop_connect.ShopProfile:
        return shop_connect.ShopProfile(platform="pinduoduo", shop_id="777", shop_name="小明家居", subject_name="王小明个体工商户",
                                        reg_no="92110000MA0000777X", subject_type="individual_business",
                                        owner_name=self.owner, owner_id_tail="0777",
                                        settlement_account={"bank": "ICBC", "tail": "0777", "holder": "王小明个体工商户"})


@pytest.fixture()
def fake_pdd():
    shop_connect.set_connector("pinduoduo", FakePdd())
    yield
    shop_connect.set_connector("pinduoduo", None)


def _oauth_connection(client, h) -> str:
    start = lc.ok(client.get("/v4/shops/connect/oauth/pinduoduo/start?format=json", headers=h))
    state = parse_qs(urlparse(start["authorize_url"]).query)["state"][0]
    r = client.get(f"/v4/shops/connect/oauth/pinduoduo/callback?code=good-code&state={state}", follow_redirects=False)
    assert r.status_code == 302, r.text
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert urlparse(r.headers["location"]).path == "/app/giaodien/workspace.html"
    reused = client.get(f"/v4/shops/connect/oauth/pinduoduo/callback?code=good-code&state={state}", follow_redirects=False)
    assert "shop_connect_error=STATE_INVALID" in reused.headers["location"]  # single use
    return q["shop_connection"][0]


def test_oauth_callback_connects_and_the_card_is_compared_with_the_owner(bu_client, as_seller, as_officer, fake_pdd):
    bad = bu_client.get("/v4/shops/connect/oauth/pinduoduo/callback?code=x&state=nope", follow_redirects=False)
    assert "shop_connect_error=STATE_INVALID" in bad.headers["location"]
    conn_id = _oauth_connection(bu_client, as_seller)
    conn = lc.ok(bu_client.get(f"/v4/shops/connections/{conn_id}", headers=as_seller))
    assert conn["verified_via"] == "oauth" and not conn["sample"] and conn["shop_name"] == "小明家居"
    with session_scope() as db:
        assert db.get(BuShopConnection, conn_id).token_ref is None  # the token is not kept
    a = lc.ok(bu_client.post("/v4/applications", headers=as_seller, json={"shop_connection_id": conn_id}))
    full = bu_client.get(f"/v4/applications/{a['id']}", headers=as_officer).json()
    assert full["scenario"] == "connected" and full["verification"]["evidence"]["store"] == "platform_oauth"
    assert full["verification"]["evidence"]["identity"] == "platform_oauth"
    _card(a["id"], "11010519491231002X", name="李四")
    a = lc.ok(bu_client.post(f"/v4/applications/{a['id']}/identity", headers=as_seller, json={"cccd": True, "face": True}))
    assert a["status"] == "rejected" and "LAW_ID_MISMATCH" in {f["code"] for f in a["verification"]["flags"]}
    assert a["identity"]["result"]["name_check"] == "mismatch"


def test_oauth_store_without_tax_and_credit_goes_to_an_officer(bu_client, as_seller, as_officer, fake_pdd):
    conn_id = _oauth_connection(bu_client, as_seller)
    a = lc.ok(bu_client.post("/v4/applications", headers=as_seller, json={"shop_connection_id": conn_id}))
    p = f"/v4/applications/{a['id']}"
    a = lc.ok(bu_client.post(p + "/identity", headers=as_seller, json={"cccd": True, "face": True}))
    assert a["status"] == "identified" and a["identity"]["result"]["account_owner_match"] is True
    lc.ok(bu_client.post(p + "/consent", headers=as_seller, json={"scopes": lc.BOXES, "method": "otp"}))
    lc.ok(bu_client.put(p + "/plan", headers=as_seller, json={
        "event": "11.11", "item": "Nồi", "group": "khác", "group_other": "đồ gia dụng", "qty": 100, "price": 50,
        "inventory": 1000, "own_capital": 1000}))
    a = lc.ok(bu_client.post(p + "/verify", headers=as_seller, json={}))
    full = bu_client.get(p, headers=as_officer).json()
    assert a["status"] == "escalated" and full["escalation"]["why"] == "DATA_SOURCE_GAP"
