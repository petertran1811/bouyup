"""T10: rate cap as a parameter, B7 cost-of-funds floor, standalone verifier, chat rate limit, group 3 cap."""

from __future__ import annotations

import copy
import importlib.util

from sqlalchemy import select

from app.core import algorithm
from app.blockchain import withdrawals
from app.api.chain_api import DECRYPT_SCRIPT
from app.core.params import DEFAULT_PARAMS
from app.data_sources import sources
from app.platform.tables import BuBank, BuLoan, BuParams, BuWithdrawal, save_json
from app.platform.db.session import session_scope
from tests import lc


def set_param(path: list[str], value) -> None:
    with session_scope() as s:
        row = s.scalar(select(BuParams).where(BuParams.active.is_(True)))
        params = copy.deepcopy(row.params)
        node = params
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = value
        save_json(row, "params", params)


def test_rate_cap_is_a_parameter(bu_client, as_seller, as_officer):
    set_param(["legal", "rate_cap"], 0.08)  # below grade B's 10 %
    app = lc.answer_all(bu_client, as_seller, lc.start(bu_client, as_seller))
    assert app["status"] == "rejected" and app["decision"]["by"] == "gate" and app["syndicate"] is None
    full = bu_client.get(f"/v4/applications/{app['id']}", headers=as_officer).json()
    law02 = next(r for r in full["control"]["phase0"]["results"] if r["code"] == "LAW-02")
    assert law02["ok"] is False and law02["value"] == 0.10


def test_rate_floor(bu_client, as_seller):
    app = lc.offered(bu_client, as_seller)
    assert app["offer"]["blocks"]["B7"] == {"rate": 0.10}  # internal pricing threshold, never shown
    assert algorithm.rate_floor(DEFAULT_PARAMS, 200_000, 12, 0.05) == 0.0505
    with session_scope() as s:
        bank = s.get(BuBank, "ICBC")
        bank.policy = {**bank.policy, "cost_of_funds": 0.0999}  # floor 0.1004 > 10 %
    app = lc.answer_all(bu_client, as_seller, lc.start(bu_client, as_seller))
    assert app["status"] == "rejected" and app["offer"] is None
    assert "B7" in app["decision"]["reason"]["law"]


def test_standalone_decrypt_script(bu_client, as_admin, as_webank, as_seller):
    script = bu_client.get("/v4/chain/decrypt_withdrawal.py")
    assert script.status_code == 200 and "def open_record" in script.text
    assert script.headers["content-type"].startswith("text/x-python")
    loan = lc.loan_for(bu_client, as_seller)  # 200.000, WeBank 40 %
    with session_scope() as s:
        wid = s.get(BuLoan, loan["id"]).withdrawal_id
        key = s.get(BuBank, "WEBANK").private_key_demo
        expected = withdrawals.decrypt(s.get(BuWithdrawal, wid), key)
    record = bu_client.get(f"/v4/chain/withdrawals/{wid}/envelope", headers=as_webank).json()
    assert bu_client.get(f"/v4/chain/withdrawals/{wid}/envelope", headers=as_seller).status_code == 200  # own loan
    spec = importlib.util.spec_from_file_location("decrypt_withdrawal", DECRYPT_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out = module.open_record(record, key)
    assert out["opened"] == expected["opened"] == ["summary", "WEBANK"] and out["fingerprints_ok"] is True
    assert out["pieces"]["WEBANK"]["amount"] == expected["pieces"]["WEBANK"]["amount"] == 80_000
    record["piece_fingerprints"][1] = "0x" + "00" * 32
    assert module.open_record(record, key)["fingerprints_ok"] is False


def test_chat_rate_limit(bu_client, as_seller):
    set_param(["chat", "max_per_minute"], 2)
    app = lc.offered(bu_client, as_seller)
    url = f"/v4/applications/{app['id']}/messages"
    assert bu_client.post(url, headers=as_seller, json={"text": "Vì sao?"}).status_code == 200
    assert bu_client.post(url, headers=as_seller, json={"text": "Vì sao?"}).status_code == 200
    r = bu_client.post(url, headers=as_seller, json={"text": "Vì sao?"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"


def test_group3_cap():
    """A borrower with no credit history anywhere (group 3): limit = 0,5 × monthly revenue (B8 group cap)."""
    d = sources.SCENARIOS["lan"][3]
    facts = {"credit": {**d["credit"], "has_credit_elsewhere": False, "network_history": "none"},
             "revenue": d["revenue"], "tax": d["tax"], "fate": d["fate"]["value"], "rating": d["store"]["rating"],
             "industry": d["store"]["industry"], "supplier": sources.supplier_info(d, "SUP-0091")}
    sheet = algorithm.compute_sheet(DEFAULT_PARAMS, borrower_type="individual_business", plan=d["plan"], facts=facts)
    assert sheet["group"] == 3 and DEFAULT_PARAMS["product"]["group_cap_mult"]["3"] == 0.5
    b8 = sheet["blocks"]["B8"]
    assert b8["group_cap"] == round(0.5 * d["revenue"]["monthly_avg_12m"]) == 83_350
    assert b8["binding_cap"] == "group_cap" and sheet["limit"] == 83_300 and sheet["suggested"] == 83_300
