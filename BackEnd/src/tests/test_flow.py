"""Staff view of the whole calculation of one application (GET /v4/applications/{id}/flow)."""

from __future__ import annotations

from tests import lc
from tests.lc import offered


def test_flow_rebuilds_every_block_and_matches_the_recorded_sheet(bu_client, as_seller, as_officer, as_admin):
    loan = lc.loan_for(bu_client, as_seller)
    app_id = loan["application_id"]
    f = bu_client.get(f"/v4/applications/{app_id}/flow", headers=as_officer).json()
    assert f["application"]["status"] == "disbursed"
    assert f["params_version"] == "v4.0" and f["params_rebuilt"] is False and f["error"] is None
    blocks = {b["block"]: b for b in f["blocks"]}
    assert list(blocks) == ["B1", "B3", "B4", "B5", "B6", "B7", "B8", "B9"]
    assert f["matches"] is True and f["sheet_on_chain"] is True
    b8 = blocks["B8"]["output"]
    assert (b8["affordability"], b8["binding_cap"], b8["limit"]) == (962_374, "type_cap", 200_000)
    assert "140.028 × 12 × 0,63 ÷ (1 + 0,1 × 12 ÷ 12) = 962.374" in blocks["B8"]["steps"][0]
    assert blocks["B4"]["steps"][-1] == "Thận trọng = 200.040 × 0,7 = 140.028"
    assert "14% ở kỳ hạn 12 tháng" in blocks["B9"]["steps"][1]
    assert sum(i["points"] for i in blocks["B6"]["inputs"]) == 80 and blocks["B6"]["output"]["grade"] == "B"
    assert any(i["source"].startswith("Thuế") for i in blocks["B5"]["inputs"])
    assert [x["code"] for x in f["b10"]["flags"]] == ["RISK_PRICE_DEVIATION"]
    assert [(s["bank"], s["pct"]) for s in f["b12"]["split"]] == [("WEBANK", 0.4), ("CMB", 0.3), ("ICBC", 0.3)]
    assert [(s["bank"], s["amount"]) for s in f["b12"]["shares"]] == [("WEBANK", 80_000), ("CMB", 60_000),
                                                                     ("ICBC", 60_000)]
    assert f["withdrawal"]["simulated"] is True and f["b11"]["early_warning"]["level"] == "green"
    assert f["b11"]["loan"]["amount"] == 200_000 and len(f["b11"]["schedule"]) == 12
    assert f["seller"]["email"] == "lan@buoyup.vn" and len(f["chain"]) >= 5
    assert bu_client.get(f"/v4/applications/{app_id}/flow", headers=as_admin).status_code == 200
    assert bu_client.get(f"/v4/applications/{app_id}/flow", headers=as_seller).status_code == 403


def test_a_changed_sheet_is_reported_as_not_matching(bu_client, as_seller, as_officer):
    from app.platform.tables import BuApplication
    from app.platform.db.session import session_scope

    app = offered(bu_client, as_seller)
    with session_scope() as s:
        row = s.get(BuApplication, app["id"])
        doc = dict(row.doc)
        doc["internal"] = {**doc["internal"], "sheet": {**doc["internal"]["sheet"], "blocks": {
            **doc["internal"]["sheet"]["blocks"], "B8": {**doc["internal"]["sheet"]["blocks"]["B8"], "affordability": 1}}}}
        row.doc = doc
    f = bu_client.get(f"/v4/applications/{app['id']}/flow", headers=as_officer).json()
    assert f["matches"] is False and next(b for b in f["blocks"] if b["block"] == "B8")["matches"] is False


def test_staff_can_filter_applications_by_seller(bu_client, as_seller, as_officer):
    offered(bu_client, as_seller)
    assert bu_client.get("/v4/applications?seller=lan@", headers=as_officer).json()["items"]
    assert bu_client.get("/v4/applications?seller=L%C3%A2m", headers=as_officer).json()["items"]
    assert bu_client.get("/v4/applications?seller=nobody-xyz", headers=as_officer).json()["items"] == []


def _lan_inputs(bu_client, as_seller):
    from app.agents import agent2_advise as advise
    from app.core.params import DEFAULT_PARAMS
    from app.platform.tables import BuApplication
    from app.platform.db.session import session_scope

    app = offered(bu_client, as_seller)
    with session_scope() as s:
        row = s.get(BuApplication, app["id"])
        plan = advise._plan_inputs(row.doc)
        return DEFAULT_PARAMS, plan, advise._facts(row, row.doc, plan)


def test_tier1_group3_cap_and_b8_b9_are_rebuilt_exactly(bu_client, as_seller):
    import copy

    from app.core import algorithm
    from app.core import flow

    params, _, facts = _lan_inputs(bu_client, as_seller)
    facts = copy.deepcopy(facts)
    facts["credit"] = {**facts["credit"], "has_credit_elsewhere": False, "network_history": None}  # group 3
    sheet = algorithm.compute_sheet(params, borrower_type="individual_business", tier=1, plan=None, facts=facts)
    blocks = {b["block"]: b for b in flow.algorithm_blocks(params, 1, None, facts, 0, sheet)}
    # Group 3: 0,5 × 166.700 = 83.350 binds below the 200.000 type cap.
    assert sheet["group"] == 3 and blocks["B8"]["output"]["group_cap"] == sheet["blocks"]["B8"]["group_cap"] == 83_350
    assert sheet["limit"] == blocks["B8"]["output"]["limit"] == 83_300 and sheet["binding_cap"] == "group_cap"
    assert "Trần theo nhóm = 0,5 × 166.700 = 83.350" in blocks["B8"]["steps"]
    assert "B3" not in blocks and all(blocks[k]["matches"] for k in ("B1", "B4", "B8", "B9"))


def test_zero_prudent_forecast_and_grade_e_do_not_crash(bu_client, as_seller):
    import copy

    from app.core import algorithm
    from app.core import flow

    params, plan, facts = _lan_inputs(bu_client, as_seller)
    zero = copy.deepcopy(facts)
    zero["revenue"] = {**zero["revenue"], "monthly_avg_12m": 0}
    sheet = algorithm.compute_sheet(params, borrower_type="individual_business", tier=2, plan=plan, facts=zero)
    assert sheet["limit"] == 0 and sheet["options"] == [] and sheet["suggested"] == 0
    blocks = {b["block"]: b for b in flow.algorithm_blocks(params, 2, plan, zero, 0, sheet)}
    assert blocks["B4"]["output"]["prudent"] == 0 and blocks["B8"]["output"]["limit"] == 0
    assert "0% ở kỳ hạn 12 tháng" in blocks["B9"]["steps"][1] and blocks["B9"]["matches"] is True
    bad = copy.deepcopy(facts)
    bad["credit"] = {**bad["credit"], "late_max_days_24m": 120}
    sheet = algorithm.compute_sheet(params, borrower_type="individual_business", tier=2, plan=plan, facts=bad)
    blocks = {b["block"]: b for b in flow.algorithm_blocks(params, 2, plan, bad, 0, sheet)}
    assert blocks["B6"]["output"]["grade"] == "E" and "B8" not in blocks
    assert blocks["B3"]["note"].startswith("Hạng E") and blocks["B3"].get("matches") is None


def test_missing_block_or_edited_sheet_is_never_reported_as_matching(bu_client, as_seller, as_officer):
    from app.platform.tables import BuApplication
    from app.platform.db.session import session_scope

    app = offered(bu_client, as_seller)
    url = f"/v4/applications/{app['id']}/flow"
    assert bu_client.get(url, headers=as_officer).json()["sheet_on_chain"] is True
    with session_scope() as s:
        row = s.get(BuApplication, app["id"])
        doc = dict(row.doc)
        blocks = {k: v for k, v in doc["internal"]["sheet"]["blocks"].items() if k != "B8"}
        doc["internal"] = {**doc["internal"], "sheet": {**doc["internal"]["sheet"], "blocks": blocks}}
        row.doc = doc
    f = bu_client.get(url, headers=as_officer).json()
    assert f["matches"] is None and f["sheet_on_chain"] is False
    assert next(b for b in f["blocks"] if b["block"] == "B8")["note"] == "Phiếu đã ghi không có khối này"


def test_seller_filter_handles_vietnamese_capitals_and_wildcards(bu_client, as_seller, as_officer):
    from app.platform.tables import BuUser
    from app.platform.db.session import session_scope

    offered(bu_client, as_seller)
    with session_scope() as s:
        s.query(BuUser).filter(BuUser.email == "lan@buoyup.vn").one().display_name = "Đỗ Thị Lan"
    get = lambda q: bu_client.get("/v4/applications", params={"seller": q}, headers=as_officer).json()["items"]  # noqa: E731
    assert get("đỗ") and get("ĐỖ THỊ") and get("Đỗ")
    assert get("_") == [] and get("%") == []
    assert bu_client.get(f"/v4/applications/{offered.__name__}/flow", headers=as_officer).status_code == 404
