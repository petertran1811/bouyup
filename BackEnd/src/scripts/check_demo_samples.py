"""Run every demo "Gian hàng mẫu" end to end over HTTP and check it ends as its "expect".

For each account: every sample store from GET /v4/public/demo-stores, with the borrower type the store is
registered for, the way the seller app does it (connect the store: POST /v4/shops/connect/start, then the code
the app shows as the SMS to the store's registered phone → /verify; "other" gets no code, so it stops there →
create from the connection → CCCD scan of the sample card → identity → consent →
plan as suggested, with the declaration → verify → answers). An approved limit is then taken: select → contract
→ wait the reading time → sign → disbursed. Round 1 settles each loan with the free prepayment (confirm, OTP);
round 2 leaves it open and clears it with the demo reset ("Làm mới khoản vay mẫu", POST /v4/demo/reset-my-loans)
before the next store, as a seller would after the POL-07 message. Each round starts with that reset when a
sample loan is still open (e.g. an account that already borrowed).

The outcome is checked against ``check`` of the store (``sources.SCENARIO_CHECKS``): status, escalation rule
(officer view), rejected rules, limit (computed × the seed ratio of the borrower's history × factor) and the
bank split (Bank of China answers within 30 s on some cases only: both splits are allowed, and the officer
view must show the matching BOC answer). Exit code 1 when any row fails.

    ../.venv/bin/python scripts/check_demo_samples.py --base http://127.0.0.1:8026 \\
        --account lan@buoyup.vn:BuoyUp@2026 --account someone@example.com:secret --rounds 2

The functions take any client with ``.get/.post/.request`` and relative URLs (``httpx.Client(base_url=…)``
or FastAPI's ``TestClient``), so ``tests/test_demo_samples.py`` runs the same checks offline.
"""

from __future__ import annotations

import argparse
import base64
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

BOXES = ["credit_inquiry", "share_partners", "data_processing"]
SIGN = {"read_ack": True, "webank_account": "6222000012345", "use_of_funds_commitment": True,
        "supplier_account": "88880001", "guarantee": True, "method": "otp"}
CCCD_DIR = Path(__file__).resolve().parents[3] / "Frontend" / "giaodien" / "mau-cccd"


class StepFailed(Exception):
    pass


def _ok(r: Any, what: str) -> dict[str, Any]:
    if r.status_code >= 300:
        raise StepFailed(f"{what}: HTTP {r.status_code} {r.text[:300]}")
    return r.json()


def login(client: Any, email: str, password: str) -> dict[str, str]:
    r = client.post("/v4/auth/login", json={"email": email, "password": password})
    return {"Authorization": "Bearer " + _ok(r, f"đăng nhập {email}")["token"]}


def fmt(n: Any) -> str:
    return f"{int(n):,}".replace(",", ".")


# --- one store ------------------------------------------------------------------------------------------------

def connect(client: Any, h: dict[str, str], store: dict[str, Any]) -> dict[str, Any]:
    """"Kết nối cửa hàng": a code to the store's registered phone. In dev/demo the server returns it as
    ``dev_code`` (what the app shows as the incoming SMS) unless the phone is someone else's ("other")."""
    s = _ok(client.post("/v4/shops/connect/start", headers=h, json={"url": store["url"]}), "kết nối cửa hàng")
    if "dev_code" not in s:
        return {"blocked": True, "phone_masked": s.get("phone_masked"), "shop": s.get("shop")}
    v = _ok(client.post(f"/v4/shops/connect/{s['connect_id']}/verify", headers=h, json={"code": s["dev_code"]}),
            "xác nhận mã cửa hàng")
    return v["connection"]


def apply(client: Any, h: dict[str, str], store: dict[str, Any], cccd: Path | None = None) -> dict[str, Any]:
    """The seller app's steps up to the banks' answer. Returns the seller view of the application (or, for a
    store the seller could not connect, ``{"status": "not_connected", ...}`` without an application)."""
    conn = connect(client, h, store)
    if conn.get("blocked"):
        return {"id": None, "status": "not_connected", "borrower_type": store["borrower_type"], "connect": conn}
    a = _ok(client.post("/v4/applications", headers=h, json={
        "tier": 2, "borrower_type": store["borrower_type"], "shop_connection_id": conn["id"]}), "tạo hồ sơ")
    app_id = a["id"]

    def step(method: str, tail: str, body: Any = None) -> None:
        nonlocal a
        if a["status"] in ("rejected", "out_of_scope"):
            return
        a = _ok(client.request(method, f"/v4/applications/{app_id}{tail}", headers=h, json=body), tail)

    if cccd is not None and a["status"] == "draft":
        for side, name in (("front", "mat-truoc.png"), ("back", "mat-sau.png")):
            image = "data:image/png;base64," + base64.b64encode((cccd / name).read_bytes()).decode()
            _ok(client.post(f"/v4/applications/{app_id}/cccd", headers=h, json={"image": image, "side": side}),
                f"quét CCCD {side}")
    step("POST", "/identity", {"cccd": True, "face": True})
    step("POST", "/consent", {"scopes": BOXES, "method": "otp"})
    if a["status"] == "consented":
        plan = {k: v for k, v in a["plan"]["suggested"].items() if k not in ("supplier", "brand", "auth")}
        if plan.get("group") != "khác":
            plan["group_other"] = ""
        plan["declaration"] = True
        step("PUT", "/plan", plan)
        step("POST", "/verify", {})
    for _ in range(5):
        if a["status"] != "needs_answer":
            break
        q = a["verification"]["questions"][0]
        step("POST", "/answers", {"flag": q["flag"], "choice": q["choices"][0]["key"]})
    return a


def take_loan(client: Any, h: dict[str, str], a: dict[str, Any], wait_read: Callable[[str, int], None],
              settle: bool) -> str:
    """offered → selected → contract → signed → disbursed, then (``settle``) the free prepayment."""
    offer = a["offer"]
    a = _ok(client.post(f"/v4/applications/{a['id']}/select", headers=h, json={
        "amount": offer["limit"], "method": "installment", "due_day": 10}), "chọn khoản vay")
    contract = _ok(client.get(f"/v4/applications/{a['id']}/contract", headers=h), "hợp đồng")
    wait_read(a["id"], int(contract.get("read_seconds") or 20))
    a = _ok(client.post(f"/v4/applications/{a['id']}/sign", headers=h, json=SIGN), "ký")
    if a["status"] != "disbursed" or not a.get("loan_id"):
        raise StepFailed(f"ký xong nhưng trạng thái {a['status']}")
    if not settle:
        return f"giải ngân {fmt(offer['limit'])}, để mở"
    loan = _ok(client.post(f"/v4/loans/{a['loan_id']}/prepay", headers=h,
                           json={"confirm": True, "method": "otp"}), "trả trước")
    if loan.get("status") != "closed":
        raise StepFailed(f"trả trước xong nhưng khoản vay {loan.get('status')}")
    return f"giải ngân {fmt(offer['limit'])}, tất toán"


def reset_if_needed(client: Any, h: dict[str, str]) -> str | None:
    preview = _ok(client.get("/v4/demo/reset-my-loans", headers=h), "xem làm mới")
    if not preview["needed"]:
        return None
    out = _ok(client.post("/v4/demo/reset-my-loans", headers=h, json={}), "làm mới khoản vay mẫu")
    if out["open_loans_left"]:
        raise StepFailed(f"làm mới xong vẫn còn {out['open_loans_left']} khoản vay mở")
    return f"làm mới: tất toán {len(out['settled'])} khoản, rút {len(out['withdrawn'])} hồ sơ"


# --- the check ------------------------------------------------------------------------------------------------

def _split_text(split: list[dict[str, Any]]) -> str:
    return "/".join(f"{s['bank']} {round(s['pct'] * 100)}" for s in split)


def describe(a: dict[str, Any], full: dict[str, Any] | None) -> str:
    st, dec = a["status"], a.get("decision") or {}
    if st == "not_connected":
        return (f"không kết nối được: mã gửi tới số đăng ký của chủ cửa hàng {a['connect'].get('phone_masked')}, "
                "người dán link không nhận được mã")
    if st == "offered":
        syn = a.get("syndicate") or {}
        return f"duyệt {fmt(a['offer']['limit'])} · {_split_text(syn.get('split') or [])}"
    if st == "escalated":
        return "chuyển cán bộ (" + str(((full or {}).get("escalation") or {}).get("why")) + ")"
    if st == "out_of_scope":
        return "ngoài phạm vi, từ " + str((a.get("verification") or {}).get("eligible_from"))
    if st == "rejected":
        flags = [f["code"] for f in (a.get("verification") or {}).get("flags") or [] if f.get("status") == "hard"]
        if flags:
            return "từ chối (" + ", ".join(flags) + ")"
        if dec.get("by") == "orchestrator":
            return "từ chối: không ngân hàng nào nhận, kể cả mức thấp hơn"
        failed = [r["code"] for r in (((full or {}).get("control") or {}).get("phase0") or {}).get("results") or []
                  if r.get("ok") is False and r.get("level") == "reject"]
        return "từ chối" + (f" ({', '.join(failed)})" if failed else f" bởi {dec.get('by')}")
    return st


def evaluate(store: dict[str, Any], a: dict[str, Any], full: dict[str, Any] | None) -> list[str]:
    """Problems of one outcome against the store's ``check`` (empty: PASS)."""
    check, problems = store["check"], []
    if a.get("borrower_type") != store["borrower_type"]:
        problems.append(f"tư cách {a.get('borrower_type')} ≠ {store['borrower_type']}")
    if a["status"] != check["status"]:
        return problems + [f"trạng thái {a['status']} ≠ {check['status']}"]
    dec = a.get("decision") or {}
    if "why" in check:
        if full is None:
            problems.append("cần tài khoản cán bộ để xem lý do chuyển")
        elif (full.get("escalation") or {}).get("why") != check["why"]:
            problems.append(f"lý do chuyển {(full.get('escalation') or {}).get('why')} ≠ {check['why']}")
    if "decision" in check and dec.get("kind") != check["decision"]:
        problems.append(f"quyết định {dec.get('kind')} ≠ {check['decision']}")
    if "by" in check and dec.get("by") != check["by"]:
        problems.append(f"quyết định bởi {dec.get('by')} ≠ {check['by']}")
    if "rules" in check and full is not None:
        failed = {r["code"] for r in ((full.get("control") or {}).get("phase0") or {}).get("results") or []
                  if r.get("ok") is False}
        if not set(check["rules"]) <= failed:
            problems.append(f"quy tắc trượt {sorted(failed)} thiếu {sorted(set(check['rules']) - failed)}")
    if "flag" in check and check["flag"] not in {f["code"] for f in (a.get("verification") or {}).get("flags") or []}:
        problems.append(f"thiếu cờ {check['flag']}")
    if "eligible_from" in check and (a.get("verification") or {}).get("eligible_from") != check["eligible_from"]:
        problems.append(f"đủ điều kiện từ {(a.get('verification') or {}).get('eligible_from')} ≠ {check['eligible_from']}")
    if check["status"] == "offered":
        problems += _check_offer(check, a, full)
    return problems


def _check_offer(check: dict[str, Any], a: dict[str, Any], full: dict[str, Any] | None) -> list[str]:
    problems = []
    b8 = ((a.get("offer") or {}).get("blocks") or {}).get("B8") or {}
    seed = float((b8.get("seed") or {}).get("ratio") or 1.0)
    if int(b8.get("computed") or 0) != int(check["computed"]):
        problems.append(f"hạn mức tính được {b8.get('computed')} ≠ {check['computed']}")
    want = int(round(int(check["computed"]) * seed * float(check["factor"]) / 100.0)) * 100
    syn = a.get("syndicate") or {}
    banks = [s["bank"] for s in syn.get("split") or []]
    limit = int(a["offer"]["limit"])
    allowed = [list(x) for x in check["banks"]]
    if banks == ["WEBANK"] and check.get("solo") and ["WEBANK"] not in allowed:
        want = min(want, int(check["solo"]))  # nobody agreed: WeBank alone, up to its solo cap
    elif not any(banks[:1] == x[:1] and sorted(banks[1:]) == sorted(x[1:]) for x in allowed):
        problems.append(f"chia {banks} không thuộc {allowed}")  # lead first; partners in answer-time order
    if limit != want:
        problems.append(f"hạn mức {fmt(limit)} ≠ {fmt(want)} (tính được {fmt(check['computed'])} × mồi {seed:g}"
                        f" × {check['factor']:g})")
    pcts = [round(s["pct"] * 100) for s in syn.get("split") or []]
    if pcts not in ([40, 30, 30], [30, 70], [100]):
        problems.append(f"tỷ lệ chia {pcts}")
    if full is not None and "BOC" in {b for x in allowed for b in x}:
        # Bank of China answers in 30 s on some cases only: the split must follow its recorded answer.
        rounds = (full.get("syndicate") or {}).get("rounds") or []
        boc = next((r for r in rounds[0]["responses"] if r["bank"] == "BOC"), None) if rounds else None
        if boc is not None and (boc["decision"] == "approve") != ("BOC" in banks):
            problems.append(f"BOC trả lời {boc['decision']} ({boc.get('ms')} ms) nhưng chia {banks}")
    return problems


# --- rounds ---------------------------------------------------------------------------------------------------

def run_account(client: Any, email: str, password: str, *, rounds: int = 2, officer: dict[str, str] | None = None,
                wait_read: Callable[[str, int], None] | None = None, cccd: Path | None = None,
                only: list[str] | None = None, log: Callable[[str], None] = print) -> list[dict[str, Any]]:
    """Every sample store for one account, ``rounds`` times. Returns one row per store and round."""
    wait_read = wait_read or (lambda _id, s: time.sleep(s + 0.5))
    stores = _ok(client.get("/v4/public/demo-stores"), "danh sách gian hàng mẫu")["stores"]
    stores = [s for s in stores if not only or s["scenario"] in only]
    h = login(client, email, password)
    rows = []
    for rnd in range(1, rounds + 1):
        try:
            note = reset_if_needed(client, h)
            if note:
                log(f"  [{email} vòng {rnd}] {note}")
        except StepFailed as exc:
            log(f"  [{email} vòng {rnd}] làm mới lỗi: {exc}")
        for store in stores:
            t0 = time.time()
            row = {"account": email, "round": rnd, "scenario": store["scenario"], "expect": store["expect"],
                   "borrower_type": store["borrower_type"]}
            try:
                if rnd > 1:  # round 2: what the seller does after the POL-07 message
                    note = reset_if_needed(client, h)
                    if note:
                        row["reset"] = note
                a = apply(client, h, store, cccd)
                full = (client.get(f"/v4/applications/{a['id']}", headers=officer).json()
                        if officer and a.get("id") else None)
                problems = evaluate(store, a, full)
                row["result"] = describe(a, full)
                if not problems and a["status"] == "offered":
                    row["result"] += " · " + take_loan(client, h, a, wait_read, settle=rnd == 1)
                row["problems"] = problems
            except StepFailed as exc:
                row["result"], row["problems"] = "lỗi bước", [str(exc)]
            row["ok"] = not row["problems"]
            row["seconds"] = round(time.time() - t0, 1)
            rows.append(row)
            log(f"  {'PASS' if row['ok'] else 'FAIL'} {email} v{rnd} {store['scenario']}: {row['result']}"
                + (f" · {'; '.join(row['problems'])}" if row["problems"] else "") + f" ({row['seconds']} s)")
    return rows


def table(rows: list[dict[str, Any]], title: str = "") -> str:
    out = [f"### {title}" if title else "", "",
           "| Tài khoản | Vòng | Kịch bản | Tư cách | Expect | Kết quả | PASS/FAIL |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        result = r["result"] + (f" — {'; '.join(r['problems'])}" if r["problems"] else "")
        out.append(f"| {r['account']} | {r['round']} | {r['scenario']} | {r['borrower_type']} | {r['expect']} | "
                   f"{result} | {'PASS' if r['ok'] else 'FAIL'} |")
    passed = sum(r["ok"] for r in rows)
    out += ["", f"Tổng: {passed}/{len(rows)} PASS"]
    return "\n".join(x for x in out if x is not None)


def main(argv: list[str] | None = None) -> int:
    import httpx

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="http://127.0.0.1:8026")
    ap.add_argument("--account", action="append", required=True, help="email:mật khẩu (lặp lại cho nhiều tài khoản)")
    ap.add_argument("--officer", default="officer@buoyup.vn:BuoyUp@2026", help="email:mật khẩu cán bộ ('' để bỏ)")
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--only", default="", help="chỉ các kịch bản này, cách nhau bằng dấu phẩy")
    ap.add_argument("--no-cccd", action="store_true", help="không quét CCCD mẫu (Frontend/giaodien/mau-cccd)")
    ap.add_argument("--title", default="")
    args = ap.parse_args(argv)
    client = httpx.Client(base_url=args.base.rstrip("/"), timeout=600)
    officer = login(client, *args.officer.split(":", 1)) if args.officer else None
    cccd = None if args.no_cccd or not CCCD_DIR.is_dir() else CCCD_DIR
    rows = []
    for acc in args.account:
        email, password = acc.split(":", 1)
        rows += run_account(client, email, password, rounds=args.rounds, officer=officer, cccd=cccd,
                            only=[x for x in args.only.split(",") if x] or None)
    print(table(rows, args.title))
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
