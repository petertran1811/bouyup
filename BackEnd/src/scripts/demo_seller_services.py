"""Nhật ký demo "dịch vụ sau khi vay" (SELLER_SERVICES_PLAN.md mục 8), nộp kèm bài thi.

Chạy trên một cơ sở dữ liệu tạm (SQLite), LLM tắt, chuỗi ``local``, autopilot tắt (Agent 4b/5 được gọi qua
``simulate-advance`` và ``autopilot.run_reports`` bằng tay). Đi đủ 8 bước của kế hoạch, rồi ghi:

    TestBench/evidence/seller_services-<YYYYmmdd-HHMM>.json   (mọi bước, nguyên văn)
    TestBench/evidence/seller_services-<YYYYmmdd-HHMM>.md     (bản đọc được)

    cd BackEnd/src && ../.venv/bin/python scripts/demo_seller_services.py
    ./run-local.sh demo-evidence

Không chạm cơ sở dữ liệu thật, không gọi mô hình, không ghi lên chuỗi FISCO. Thư mục tạm: ``BUOYUP_DEMO_TMP``
(mặc định ``TestBench/evidence/.tmp``), xóa khi xong.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parents[1]
ROOT = SRC.parents[1]
EVIDENCE = Path(os.environ.get("BUOYUP_DEMO_EVIDENCE") or ROOT / "TestBench" / "evidence")
TMP_PARENT = Path(os.environ.get("BUOYUP_DEMO_TMP") or EVIDENCE / ".tmp")
TMP_PARENT.mkdir(parents=True, exist_ok=True)
TMP = tempfile.mkdtemp(prefix="demo-seller-", dir=TMP_PARENT)
SECRET = "demo-webhook-secret"

# Before any ``app`` import: settings are read at import time (same isolation as tests/conftest.py).
os.environ["ENV_FILE"] = os.path.join(TMP, "no.env")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{TMP}/demo.db", "APP_ENV": "dev", "LOG_LEVEL": "WARNING",
    "LLM_ENABLED": "false", "GEMINI_API_KEY": "", "LLM_HOST": "", "LLM_API_KEY": "",
    "BUOYUP_AUTOPILOT": "false", "BUOYUP_CHAIN_BACKEND": "local", "BUOYUP_CHAIN_URL": "", "BUOYUP_CHAIN_TOKEN": "",
    "BUOYUP_RAG_DENSE": "0", "FACE_WARMUP": "false", "FACE_DATA_DIR": os.path.join(TMP, "faces"),
    "FACE_REQUIRED_AT_SIGNUP": "false", "CCCD_OCR_REQUIRED": "false", "PLAN_DECLARATION_REQUIRED": "false",
    "UPLOAD_DIR": os.path.join(TMP, "uploads"), "WEBANK_WEBHOOK_SECRET": SECRET, "PLATFORM_PAYOUT_FEED": "false",
})
sys.path.insert(0, str(SRC))
os.chdir(SRC)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event as sa_event  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.agents import agent4b_monitor as agent4  # noqa: E402
from app.agents import agent5_seller_reports as reports  # noqa: E402
from app.autopilot import loop as autopilot  # noqa: E402
from app.data_sources import consent, sources  # noqa: E402
from app.platform import capabilities  # noqa: E402
from app.platform.config import settings  # noqa: E402
from app.platform.db.init_db import reset_db  # noqa: E402
from app.platform.db.session import session_scope  # noqa: E402
from app.platform.seed import seed_buoyup  # noqa: E402
from app.platform.tables import (BuApplication, BuEvent, BuLoan, BuRepayment, BuSellerReport,  # noqa: E402
                                 save_json)

PASSWORD = "BuoyUp@2026"
BOXES = list(consent.CONSENT_BOXES)
ACCOUNT = "6222000012345"
SIGN = {"read_ack": True, "webank_account": ACCOUNT, "use_of_funds_commitment": True,
        "supplier_account": "88880001", "guarantee": True, "method": "otp"}

# --- what the final checks watch ---------------------------------------------------------------------------
REPAYMENT_ACTORS: list[dict[str, Any]] = []   # one row per BuRepayment insert: the agent role acting then
CAPABILITY_CALLS: list[dict[str, Any]] = []   # every capabilities.require(...) and whether it was refused


@sa_event.listens_for(BuRepayment, "init")
def _repayment_actor(target, _args, kwargs) -> None:  # noqa: ANN001
    """Fires when the row is built, i.e. inside the code that moves the money, under its agent role."""
    REPAYMENT_ACTORS.append({"id": kwargs.get("id"), "loan_id": kwargs.get("loan_id"), "swept": kwargs.get("swept"),
                             "role": capabilities.current() or "không vai (yêu cầu của người bán)"})


_real_require = capabilities.require


def _watch_require(capability: str) -> None:
    row = {"capability": capability, "role": capabilities.current(), "denied": None}
    CAPABILITY_CALLS.append(row)
    try:
        _real_require(capability)
    except capabilities.CapabilityDenied as exc:
        row["denied"] = str(exc)
        raise


capabilities.require = _watch_require


# --- small helpers ------------------------------------------------------------------------------------------

def ok(r: Any) -> dict[str, Any]:
    if r.status_code >= 300:
        raise SystemExit(f"HTTP {r.status_code}: {r.text[:1500]}")
    return r.json()


def register(c: TestClient, email: str, name: str) -> tuple[dict[str, str], dict[str, Any]]:
    out = ok(c.post("/v4/auth/register", json={"email": email, "password": PASSWORD, "display_name": name,
                                               "phone": "0912345678", "accept_terms": True}))
    return {"Authorization": "Bearer " + out["token"]}, out["user"]


def login(c: TestClient, email: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + ok(c.post("/v4/auth/login", json={"email": email, "password": PASSWORD}))["token"]}


def start(c: TestClient, h: dict[str, str], scenario: str, borrower_type: str, plan: dict[str, Any] | None = None) -> dict:
    app = ok(c.post("/v4/applications", headers=h, json={"tier": 2, "borrower_type": borrower_type,
                                                          "store_urls": [sources.demo_url(scenario)]}))
    app = ok(c.post(f"/v4/applications/{app['id']}/identity", headers=h, json={"cccd": True, "face": True}))
    app = ok(c.post(f"/v4/applications/{app['id']}/consent", headers=h, json={"scopes": BOXES}))
    app = ok(c.put(f"/v4/applications/{app['id']}/plan", headers=h, json=plan or app["plan"]["suggested"]))
    app = ok(c.post(f"/v4/applications/{app['id']}/verify", headers=h, json={}))
    while app["status"] == "needs_answer":
        q = app["verification"]["questions"][0]
        app = ok(c.post(f"/v4/applications/{app['id']}/answers", headers=h,
                        json={"flag": q["flag"], "choice": q["choices"][0]["key"]}))
    return app


def rewind_contract(app_id: str, seconds: int = 30) -> None:
    """The disclosure's reading clock, moved back instead of waiting (as the tests do)."""
    with session_scope() as s:
        row = s.get(BuApplication, app_id)
        doc = dict(row.doc)
        ct = dict(doc["contract"])
        ct["issued_at"] = (datetime.fromisoformat(ct["issued_at"].rstrip("Z")) - timedelta(seconds=seconds)).isoformat() + "Z"
        doc["contract"] = ct
        save_json(row, "doc", doc)


def signed_post(c: TestClient, path: str, body: dict[str, Any]) -> Any:
    raw = json.dumps(body, ensure_ascii=False).encode()
    sig = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return c.post(path, content=raw, headers={"Content-Type": "application/json", "X-WeBank-Signature": sig})


def advance(c: TestClient, h: dict[str, str], loan_id: str, to: date) -> dict:
    return ok(c.post(f"/v4/loans/{loan_id}/simulate-advance", headers=h, json={"to": to.isoformat()}))


def notices(c: TestClient, h: dict[str, str]) -> list[dict[str, Any]]:
    return ok(c.get("/v4/me/notices", headers=h))["items"]


def new_notices(c: TestClient, h: dict[str, str], seen: set[str]) -> list[dict[str, Any]]:
    out = []
    for n in notices(c, h):
        if n["id"] not in seen:
            seen.add(n["id"])
            out.append({k: n.get(k) for k in ("kind", "title", "text", "level", "scope", "at")})
    return out[::-1]  # the API lists newest first; the log reads in order


def quarter_store(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """The store block of a quarterly report (rating from the monthly snapshots; returns "chưa có")."""
    if not row:
        return None
    with session_scope() as s:
        r = s.get(BuSellerReport, row["id"])
        data = (r.data or {}) if r else {}
        return {"store": data.get("store"), "notes": data.get("notes")}


def first_of_next(d: date) -> date:
    return (d.replace(day=1) + timedelta(days=32)).replace(day=1)


def report_rows(user_id: str) -> list[dict[str, Any]]:
    with session_scope() as s:
        rows = s.scalars(select(BuSellerReport).where(BuSellerReport.seller_user_id == user_id)
                         .order_by(BuSellerReport.at)).all()
        return [{"id": r.id, "kind": r.kind, "period": r.period, "title": reports.title_of(r), "hash": r.hash,
                 "chain_tx": r.chain_tx, "summary": (r.data or {}).get("summary"),
                 "notes": (r.data or {}).get("notes"), "coverage": (r.data or {}).get("coverage")} for r in rows]


def set_tax(app_id: str, months: dict[str, int]) -> None:
    """The tax authority's monthly revenue for this dossier (the source Agent 5 reads for 'doanh thu năm nay')."""
    with session_scope() as s:
        row = s.get(BuApplication, app_id)
        doc = dict(row.doc)
        internal = dict(doc["internal"])
        data = dict(internal["data"])
        revenue = dict(data["revenue"])
        revenue["monthly_12m"] = [{"month": k, "amount": v} for k, v in months.items()]
        data["revenue"], internal["data"], doc["internal"] = revenue, data, internal
        save_json(row, "doc", doc)


# --- the eight steps ---------------------------------------------------------------------------------------

def run() -> dict[str, Any]:
    reset_db()
    seed_buoyup()
    from app.main import app as fastapi_app

    steps: list[dict[str, Any]] = []
    with TestClient(fastapi_app) as c:
        # 1. A new seller signs up; dossier "lan" with a declared purchase price of 120 (invoices say 62).
        h, user = register(c, "demo.lan@example.com", "Nguyễn Thị Lan (demo)")
        seen: set[str] = set()
        plan = {**sources.suggested_plan(sources.SCENARIOS["lan"][3]), "price": 120}
        app = start(c, h, "lan", "individual_business", plan)
        offer = app.get("offer") or {}
        steps.append({"step": 1, "title": "Đăng ký người bán, hồ sơ lan, giá khai 120 tệ",
                      "status": app["status"], "decision_kind": (app.get("decision") or {}).get("kind"),
                      "decision_explanation": (app.get("decision") or {}).get("explanation"),
                      "offer": {k: offer.get(k) for k in ("limit", "suggested", "tenor_max", "explanation",
                                                           "explanation_source", "bank_adjust")},
                      "notices": new_notices(c, h, seen)})

        # 2. The officer approves when the gate escalated; select 60.000, sign, disburse.
        officer = None
        if app["status"] == "escalated":
            oh = login(c, "officer@buoyup.vn")
            app = ok(c.post(f"/v4/officer/applications/{app['id']}/decision", headers=oh,
                            json={"decision": "approve", "note": "Demo: cán bộ duyệt sau khi xem hóa đơn"}))
            app = ok(c.get(f"/v4/applications/{app['id']}", headers=h))
            officer = "approve"
        if app["status"] != "offered":
            raise SystemExit(f"Hồ sơ không tới bước chọn khoản vay: {app['status']}")
        offer = app["offer"]
        amount = min(60_000, int(offer["limit"]))
        tenor = int(offer["tenor_max"])  # the product sets the tenor (borrower_picks_tenor = false)
        ok(c.post(f"/v4/applications/{app['id']}/select", headers=h,
                  json={"amount": amount, "tenor_m": tenor, "method": "installment", "due_day": 28}))
        ok(c.get(f"/v4/applications/{app['id']}/contract", headers=h))
        rewind_contract(app["id"])
        app = ok(c.post(f"/v4/applications/{app['id']}/sign", headers=h, json=SIGN))
        loan = ok(c.get(f"/v4/loans/{app['loan_id']}", headers=h))
        loan_id = loan["id"]
        start_day = date.fromisoformat(loan["clock"])
        first_due = date.fromisoformat(loan["schedule"][0]["due_date"])
        steps.append({"step": 2, "title": f"Duyệt, ký, giải ngân {agent4._n(amount)} tệ / {tenor} tháng",
                      "approved_by": "cán bộ" if officer else "cổng tự động (không cần cán bộ: đủ 5 điều kiện)",
                      "status": app["status"], "loan_id": loan_id, "amount": loan["amount"], "tenor_m": loan["tenor_m"],
                      "rate": loan["rate"], "first_due_date": loan["first_due_date"],
                      "first_payment": loan["schedule"][0]["payment_est"], "notices": new_notices(c, h, seen)})

        # 3. Money in every day for 20 days (platform payouts), then 4 spends in 4 groups through the signed
        #    WeBank outflow webhook; the large one leaves the balance below the next payment.
        assert settings.webank_webhook_secret == SECRET
        inflows = []
        day = start_day
        for i in range(20):
            if i:
                day = day + timedelta(days=1)
                advance(c, h, loan_id, day)
            r = ok(c.post(f"/v4/loans/{loan_id}/simulate-inflow", headers=h,
                          json={"amount": 300 + 10 * (i % 5), "payout_id": f"douyin-{day:%Y%m%d}"}))
            inflows.append({"on": day.isoformat(), "amount": 300 + 10 * (i % 5), "balance": r["account"]["balance"]})
        spends = [("platform", "抖音电商", "Phí sàn Douyin", 1_200), ("company", "顺丰速运", "Phí vận chuyển 快递费", 800),
                  ("platform", "巨量引擎", "Quảng cáo Douyin", 2_500), ("supplier", "广州布料厂", "Nhập vải lô mới", 58_000)]
        outflows = []
        for n, (kind, name, memo, amt) in enumerate(spends, 1):
            r = signed_post(c, "/v4/webank/outflows", {"account_number": ACCOUNT, "amount": amt,
                                                         "transfer_id": f"wb-out-demo-{n:03d}",
                                                         "payee": {"kind": kind, "name": name}, "memo": memo})
            body = ok(r)
            outflows.append({"transfer_id": f"wb-out-demo-{n:03d}", "amount": amt, "memo": memo,
                             "group": body["transfer"].get("group"), "balance": body["balance"]})
        unsigned = c.post("/v4/webank/outflows", json={"account_number": ACCOUNT, "amount": 10,
                                                       "transfer_id": "wb-out-unsigned", "memo": "x"}).status_code
        steps.append({"step": 3, "title": "20 ngày tiền về, 4 khoản chi 4 nhóm qua webhook có HMAC",
                      "inflows": inflows, "outflows": outflows, "unsigned_webhook_status": unsigned,
                      "notices": new_notices(c, h, seen)})

        # 4. To due−7 (shortfall forecast), the seller tops up, then to the 1st of the next month (monthly
        #    report, debt-service ratio).
        to = first_due - timedelta(days=7)
        view = advance(c, h, loan_id, to)
        got = new_notices(c, h, seen)
        topup = ok(c.post(f"/v4/loans/{loan_id}/simulate-inflow", headers=h,
                          json={"amount": 25_000, "payout_id": f"topup-{to:%Y%m%d}", "source": "nộp thêm"}))
        month1 = first_of_next(first_due)
        view = advance(c, h, loan_id, month1)
        steps.append({"step": 4, "title": f"Tới {to:%d/%m} (kỳ 1 − 7 ngày) rồi tới {month1:%d/%m/%Y}",
                      "due_minus_7": to.isoformat(), "notices_due_minus_7": got,
                      "topup_balance": topup["account"]["balance"], "first_of_month": month1.isoformat(),
                      "schedule_row_1": view["schedule"][0], "notices": new_notices(c, h, seen),
                      "reports": report_rows(user["id"])})

        # 5. Three more months: the quarterly (and yearly) reports; inflows keep each instalment paid.
        cur = month1
        quarter_to = first_of_next(first_of_next(first_of_next(month1)))
        while cur < quarter_to:
            nxt = min(quarter_to, cur + timedelta(days=10))
            ok(c.post(f"/v4/loans/{loan_id}/simulate-inflow", headers=h,
                      json={"amount": 9_000, "payout_id": f"douyin-{cur:%Y%m%d}"}))
            view = advance(c, h, loan_id, nxt)
            cur = nxt
        rows = report_rows(user["id"])
        quarter = next((r for r in rows if r["kind"] == "quarter"), None)
        steps.append({"step": 5, "title": f"Thêm 3 tháng, tới {quarter_to:%d/%m/%Y}: báo cáo quý",
                      "loan_status": view["status"], "quarter": quarter,
                      "quarter_store": quarter_store(quarter),
                      "notices": new_notices(c, h, seen), "reports": rows})

        # 6. Prepay everything with the confirmation box (confirm: true, OTP) → the closing report.
        loan = ok(c.get(f"/v4/loans/{loan_id}", headers=h))
        if loan["status"] in ("active", "overdue"):
            need = int((loan.get("prepay_quote") or {}).get("total") or 0) - int(loan["account"]["balance"])
            if need > 0:
                ok(c.post(f"/v4/loans/{loan_id}/simulate-inflow", headers=h,
                          json={"amount": need, "payout_id": "topup-prepay", "source": "nộp thêm"}))
            refused = c.post(f"/v4/loans/{loan_id}/prepay", headers=h, json={}).json().get("error", {}).get("code")
            loan = ok(c.post(f"/v4/loans/{loan_id}/prepay", headers=h, json={"confirm": True, "method": "otp"}))
        else:
            refused = None
        autopilot.run_reports("closing", [user["id"]])
        closing = next((r for r in report_rows(user["id"]) if r["kind"] == "closing"), None)
        steps.append({"step": 6, "title": "Trả hết (prepay, confirm: true) → báo cáo tất toán",
                      "without_confirm": refused, "loan_status": loan["status"], "closing": closing,
                      "notices": new_notices(c, h, seen)})

        # 7. An individual seller (no business registration) with 85.000 tệ revenue this year.
        h2, user2 = register(c, "demo.canhan@example.com", "Trần Văn Cá Nhân (demo)")
        seen2: set[str] = set()
        app2 = start(c, h2, "personal", "individual")
        today = agent4.today()
        set_tax(app2["id"], {f"{today.year}-01": 30_000, f"{today.year}-02": 25_000, f"{today.year}-03": 30_000})
        with session_scope() as s:
            made = [r.kind for r in reports.run_due(s, today, user_ids=[user2["id"]], use_model=False)]
        reg = next((r for r in report_rows(user2["id"]) if r["kind"] == "registration"), None)
        with session_scope() as s:
            row = s.get(BuSellerReport, reg["id"]) if reg else None
            citations = (row.data or {}).get("citations") if row else None
        steps.append({"step": 7, "title": "Người bán cá nhân, doanh thu năm nay 85.000 tệ → nhắc đăng ký kinh doanh",
                      "borrower_type": app2.get("borrower_type"), "application_status": app2["status"],
                      "reports_made": made, "registration": reg, "citations": citations,
                      "notices": new_notices(c, h2, seen2)})

        # 8. Events by kind, the chain records of the reports.
        with session_scope() as s:
            evs = s.scalars(select(BuEvent).order_by(BuEvent.id)).all()
            by_kind = Counter(e.kind for e in evs)
            actors = defaultdict(Counter)
            for e in evs:
                actors[e.kind][e.actor] += 1
            alert_events = [{"kind": e.kind, "actor": e.actor, "summary": e.summary} for e in evs
                            if e.kind in ("seller_alert", "seller_report", "payment_confirmed")]
            repayments = s.scalars(select(BuRepayment)).all()
            n_repay = len(repayments)
        all_reports = report_rows(user["id"]) + report_rows(user2["id"])
        steps.append({"step": 8, "title": "Sự kiện theo loại và chain_tx của các báo cáo",
                      "events_by_kind": dict(sorted(by_kind.items())),
                      "events_actors": {k: dict(v) for k, v in sorted(actors.items())},
                      "alert_events": alert_events,
                      "reports_chain": [{k: r[k] for k in ("kind", "period", "title", "hash", "chain_tx")}
                                        for r in all_reports]})

    agent5_repayments = [r for r in REPAYMENT_ACTORS if r["role"] == "agent5"]
    violations = [x for x in CAPABILITY_CALLS if x["denied"]]
    checks = {
        "repayments_total": n_repay,
        "repayments_by_role": dict(Counter(r["role"] for r in REPAYMENT_ACTORS)),
        "repayments_by_agent5": len(agent5_repayments),
        "capability_calls": dict(Counter(f"{x['capability']}:{x['role'] or 'không vai'}" for x in CAPABILITY_CALLS)),
        "capability_violations": violations,
        "reports_with_chain_tx": sum(1 for r in all_reports if r["chain_tx"]),
        "reports_total": len(all_reports),
        "ok": not agent5_repayments and not violations and all(r["chain_tx"] for r in all_reports),
    }
    return {"generated_at": datetime.now().isoformat(timespec="seconds"), "plan": "SELLER_SERVICES_PLAN.md mục 8",
            "settings": {"database": "SQLite tạm", "llm": "tắt", "chain": "local", "autopilot": "tắt"},
            "steps": steps, "checks": checks}


# --- Markdown ----------------------------------------------------------------------------------------------

def _cell(x: Any) -> str:
    return str(x if x is not None else "—").replace("|", "\\|").replace("\n", " ")


def _notice_lines(items: list[dict[str, Any]]) -> list[str]:
    return [f"- **{_cell(n.get('title') or n.get('kind'))}** ({n.get('kind')}, {n.get('level')}): {_cell(n.get('text'))}"
            for n in items] or ["- (không có thông báo mới)"]


def markdown(ev: dict[str, Any]) -> str:
    s = {x["step"]: x for x in ev["steps"]}
    ck = ev["checks"]
    out = [f"# Nhật ký demo dịch vụ sau khi vay · {ev['generated_at']}",
           "",
           f"Theo {ev['plan']}. SQLite tạm, LLM tắt, chuỗi `local`, autopilot tắt. "
           f"Kiểm tra cuối: **{'ĐẠT' if ck['ok'] else 'KHÔNG ĐẠT'}**.",
           "",
           "| Bước | Nội dung | Kết quả |",
           "|---|---|---|"]
    summary = {
        1: f"trạng thái `{s[1]['status']}`, quyết định `{s[1]['decision_kind']}`, hạn mức {s[1]['offer']['limit']}",
        2: f"{s[2]['approved_by']}; khoản vay {s[2]['amount']} / {s[2]['tenor_m']} tháng, kỳ 1 {s[2]['first_due_date']}",
        3: f"{len(s[3]['inflows'])} lần tiền về, {len(s[3]['outflows'])} khoản chi "
           f"({', '.join(o['group'] or '?' for o in s[3]['outflows'])}); không chữ ký → HTTP {s[3]['unsigned_webhook_status']}",
        4: f"thông báo: {', '.join(n['kind'] for n in s[4]['notices_due_minus_7'] + s[4]['notices']) or '—'}",
        5: f"báo cáo quý: {(s[5]['quarter'] or {}).get('title', '—')}",
        6: f"thiếu confirm → `{s[6]['without_confirm']}`; khoản vay `{s[6]['loan_status']}`; "
           f"{(s[6]['closing'] or {}).get('title', '—')}",
        7: f"`{s[7]['borrower_type']}`; báo cáo tạo: {', '.join(s[7]['reports_made']) or '—'}",
        8: f"{sum(s[8]['events_by_kind'].values())} sự kiện, {len(s[8]['reports_chain'])} báo cáo có hash",
    }
    for k in range(1, 9):
        out.append(f"| {k} | {_cell(s[k]['title'])} | {_cell(summary[k])} |")
    exp = s[1]["decision_explanation"] or {}
    out += ["", "## 1. Lời giải thích quyết định (việc 1, nguyên văn)", "",
            f"**{_cell(exp.get('headline'))}**", ""]
    out += [f"- Vì sao: {_cell(b['text'])}" for b in exp.get("because") or []]
    out += [f"- Bạn có thể: {_cell(i['text'])}" for i in exp.get("improve") or []]
    out += ["", f"Đoạn tư vấn của Agent 2 sau vòng ngân hàng ({s[1]['offer']['explanation_source']}): "
                f"{_cell(s[1]['offer']['explanation'])}", ""]
    for k, head in ((1, "Thông báo sau bước 1"), (2, "Thông báo sau bước 2"), (3, "Thông báo sau bước 3 (việc 4)")):
        out += [f"## {head}", ""] + _notice_lines(s[k]["notices"]) + [""]
    out += ["## 4. Kỳ 1 − 7 ngày và đầu tháng (việc 2, 3, 5, 9)", "", "Tại ngày kỳ 1 − 7:", ""]
    out += _notice_lines(s[4]["notices_due_minus_7"])
    out += ["", f"Tới {s[4]['first_of_month']}:", ""] + _notice_lines(s[4]["notices"]) + [""]
    qs = (s[5]["quarter_store"] or {}).get("store") or {}
    lines = [f"{k}: {_cell(v.get('unavailable') if isinstance(v, dict) and 'unavailable' in v else v)}"
             for k, v in qs.items()] if isinstance(qs, dict) else [_cell(qs)]
    out += ["## 5. Ba tháng sau (việc 6)", "", "Phần cửa hàng trong báo cáo quý:", ""] + [f"- {x}" for x in lines]
    out += [f"- Ghi chú: {_cell(n)}" for n in (s[5]["quarter_store"] or {}).get("notes") or []]
    out += [""] + _notice_lines(s[5]["notices"]) + [""]
    out += ["## 6. Tất toán (việc 7)", ""] + _notice_lines(s[6]["notices"]) + [""]
    out += ["## 7. Nhắc đăng ký kinh doanh (việc 8)", ""] + _notice_lines(s[7]["notices"])
    out += [f"- Trích dẫn: {_cell(c.get('ref') or c.get('law'))} · đã kiểm: {c.get('verified')}"
            for c in s[7]["citations"] or []]
    out += ["", "## 8. Báo cáo trên chuỗi", "", "| Loại | Kỳ | Tiêu đề | hash | chain_tx |", "|---|---|---|---|---|"]
    out += [f"| {r['kind']} | {_cell(r['period'])} | {_cell(r['title'])} | `{_cell(r['hash'])[:24]}…` | `{_cell(r['chain_tx'])}` |"
            for r in s[8]["reports_chain"]]
    out += ["", "## 8. Sự kiện theo loại", "", "| kind | số lượng | actor |", "|---|---|---|"]
    out += [f"| {k} | {n} | {_cell(', '.join(f'{a} {m}' for a, m in s[8]['events_actors'][k].items()))} |"
            for k, n in s[8]["events_by_kind"].items()]
    out += ["", "## Kiểm tra cuối", "",
            f"- BuRepayment tổng: {ck['repayments_total']}; theo vai đang chạy: {_cell(ck['repayments_by_role'])}",
            f"- BuRepayment do actor `agent5` tạo: **{ck['repayments_by_agent5']}**",
            f"- Vi phạm quyền (`capabilities`): **{len(ck['capability_violations'])}**; các lần kiểm: "
            f"{_cell(ck['capability_calls'])}",
            f"- Báo cáo có `chain_tx`: {ck['reports_with_chain_tx']}/{ck['reports_total']}",
            f"- Kết luận: **{'ĐẠT' if ck['ok'] else 'KHÔNG ĐẠT'}**", ""]
    return "\n".join(out)


def main() -> int:
    try:
        ev = run()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
        try:
            TMP_PARENT.rmdir()  # only when empty (another run may be using it)
        except OSError:
            pass
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    stem = EVIDENCE / f"seller_services-{datetime.now():%Y%m%d-%H%M}"
    stem.with_suffix(".json").write_text(json.dumps(ev, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    stem.with_suffix(".md").write_text(markdown(ev), encoding="utf-8")
    print(f"{'PASS' if ev['checks']['ok'] else 'FAIL'} {stem}.json {stem}.md")
    return 0 if ev["checks"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
