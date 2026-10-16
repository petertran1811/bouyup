# BuoyUp API v4 — hợp đồng giữa backend và frontend

Base: cùng origin với frontend (`http://localhost:8000`), prefix `/v4`. JSON UTF-8.
Tiền là số nguyên đơn vị tiền tệ (CNY cho ca Trung Quốc). Tỷ lệ là số thập phân (0.63 = 63%).
Thời gian ISO-8601 có múi giờ.

## 0. Quy ước chung

**Xác thực.** `Authorization: Bearer <token>`. Token lấy từ `/v4/auth/login` hoặc `/register`.
Frontend lưu ở `localStorage["bu_token"]`, người dùng ở `localStorage["bu_user"]`.

**Lỗi.** Mọi lỗi trả:
```json
{"error": {"code": "AUTH_REQUIRED", "message": "Vui lòng đăng nhập.", "details": {}}}
```
| HTTP | code |
|---|---|
| 400 | `VALIDATION_ERROR`, `INVALID_STATE` (hành động không hợp lệ ở trạng thái hiện tại), `INVALID_OPTION` |
| 401 | `AUTH_REQUIRED`, `INVALID_CREDENTIALS`, `SESSION_EXPIRED` |
| 403 | `FORBIDDEN` |
| 404 | `NOT_FOUND` |
| 409 | `CONFLICT` (email đã có, requestId dùng lại với dữ liệu khác) |
| 429 | `RATE_LIMITED` |
| 503 | `CHAIN_UNAVAILABLE` (chế độ chuỗi remote: dịch vụ chuỗi không trả lời; `details.kind` = mã lỗi của dịch vụ, ví dụ `unreachable`, `chain`, `not_configured`) |

**Vai.** `seller` · `officer` · `bank` · `admin`. Bảng quyền ở cuối mỗi mục.

**Nhãn mô phỏng.** Mọi phản hồi có nguồn dữ liệu giả lập kèm `"simulated": true` ở mức gốc hoặc từng
lời gọi công cụ. Frontend phải hiện huy hiệu "Mô phỏng" ở đó.

## 1. Auth — `/v4/auth`

### POST /v4/auth/register  (công khai, chỉ tạo vai seller)
Vào:
```json
{"email": "lan@example.com", "password": "≥8 ký tự, có chữ và số", "display_name": "Lâm Lan",
 "phone": "+86 138 0000 0000", "accept_terms": true}
```
Ra 201:
```json
{"token": "…", "expires_at": "…", "user": USER}
```
`USER` = `{"id": "usr_…", "email": "…", "display_name": "…", "role": "seller", "bank_code": null, "created_at": "…"}`
Tùy chọn `"face_enroll_id": "…"`: một phiên quét khuôn mặt đã `done` (§1a); khuôn mặt được lưu cho tài khoản
mới để đăng nhập bằng khuôn mặt. Phiên hết hạn/chưa xong: 400 `VALIDATION_ERROR` (`field: face_enroll_id`);
khuôn mặt đã thuộc tài khoản khác: 409 `FACE_ALREADY_REGISTERED`. Mỗi phiên quét chỉ dùng cho một lần đăng ký.
Khi mô hình đã nạp (`required_at_signup` ở §1a), thiếu `face_enroll_id` → 400 (`field: face_enroll_id`); máy chủ chưa có
mô hình thì đăng ký không cần khuôn mặt.

### POST /v4/auth/login
Vào `{"email": "…", "password": "…"}` → 200 `{"token", "expires_at", "user": USER}`.
Sai: 401 `INVALID_CREDENTIALS`. Quá 5 lần sai/15 phút/email: 429.

### POST /v4/auth/logout → 204 (thu hồi token hiện tại)
### GET /v4/auth/me → 200 `{"user": USER}`

Ở môi trường `dev`/`demo`/`test`, người bán có hồ sơ dựng sẵn (`app/buoyup/profiles/*.json`, vd `lan@buoyup.vn`)
nhận thêm `"demo_profile": {"profile": "lan", "store_url": "…", "accounts": [{"bank": "WeBank", "tail": "8826"}]}`
để giao diện điền sẵn link gian hàng và tài khoản. Môi trường khác không bao giờ trả trường này.

**Tài khoản mẫu** (seed khi khởi động nếu chưa có, mật khẩu chung `BuoyUp@2026`; chỉ khi `APP_ENV`
là `dev`/`demo`):
| email | vai | ghi chú |
|---|---|---|
| `lan@buoyup.vn` | seller | chị Lan, đã có sẵn 0 hồ sơ |
| `officer@buoyup.vn` | officer | |
| `admin@buoyup.vn` | admin | |
| `webank@buoyup.vn` | bank | bank_code WEBANK |
| `cmb@buoyup.vn` | bank | CMB |
| `icbc@buoyup.vn` | bank | ICBC |
| `vcb@buoyup.vn` | bank | VCB |

## 1a. Xác thực khuôn mặt — `/v4/face`  (công khai; InsightFace buffalo_l, mã ở `BackEnd/src/Reid`)

Trình duyệt gửi từng khung hình webcam (chỉ JPEG, base64, nhận cả data URL, tối đa 2000×2000) và đợi phản hồi rồi mới
gửi khung tiếp (cách nhau ≥ 50 ms, không thì 429). Khung trùng byte với khung đã gửi không được xử lý (`hint: STILL_FRAME`).
Máy chủ chưa có insightface/mô hình, đang tải mô hình, hoặc `FACE_AUTH_ENABLED=false`: 503 `FACE_UNAVAILABLE`.

### GET /v4/face/status
→ `{"enabled", "available", "required_at_signup", "enrolled_users", "model": "buffalo_l", "installed", "loaded", "provider", "error"}`.

### POST /v4/face/enroll → `{"enroll_id", "expires_in": 300, ...ENROLL_STATE}` (tối đa 20 lần/ip/15 phút: 429)
### POST /v4/face/enroll/{enroll_id}/frame
Vào `{"image": "<base64 jpeg>"}` → `{"enroll_id", ...ENROLL_STATE}`.
`ENROLL_STATE` = `{"stage": "center"|"turn"|"done", "hint": "OK"|"NO_FACE"|"MULTIPLE_FACES"|"TOO_FAR"|"TOO_CLOSE"|
"OFF_CENTER"|"LOW_QUALITY"|"LOOK_STRAIGHT"|"FACE_CHANGED", "message": "<tiếng Việt>", "face": [x, y, w, h] (0–1, ảnh gốc) | null,
"center": 0–3, "center_needed": 3, "segments": [8 × bool], "next_segment": 0–7 | null, "progress": 0–1, "done": bool}`.
Ba khung nhìn thẳng, rồi xoay đầu một vòng đủ 8 hướng. Hướng `i` = `i×45°` ngược chiều kim đồng hồ từ bên phải
màn hình **khi video hiển thị lật gương** (0 phải, 2 trên, 4 trái, 6 dưới). Kiểm tra trùng khuôn mặt chạy lúc
`/auth/register` (không ở đây, để phiên quét không dùng được để dò ai có tài khoản). Phiên hết hạn: 404 `NOT_FOUND`.

### POST /v4/face/login
Vào `{"email": ""}` (bỏ trống = nhận diện trên mọi tài khoản 1:N; có email = so 1:1) →
`{"login_id", "expires_in": 120, ...LOGIN_STATE}`. Quá 30 lần thất bại/ip/15 phút: 429.
### POST /v4/face/login/{login_id}/frame
Vào `{"image": "…"}` → `{"login_id", ...LOGIN_STATE}`; `LOGIN_STATE` = `{"stage": "frontal"|"turn"|"done", "hint",
"message", "face", "challenge": null|"left"|"right", "done", "failed"}`. Nhận diện ở khung nhìn thẳng (2 khung liền khớp,
cosine ≥ `FACE_MATCH_THRESHOLD`), sau đó mới lộ thử thách quay mặt trái/phải ngẫu nhiên; cú quay phải đi qua góc trung gian
(6–20°) trước khi tới ≥ 20°, khuôn mặt không được nhảy chỗ giữa hai khung (chống thay ảnh). Không phải chống giả mạo được chứng nhận.
Thành công: thêm `{"token", "expires_at", "user": USER}` như `/v4/auth/login`. Thất bại: 401 `FACE_NOT_RECOGNIZED`,
`FACE_LIVENESS_FAILED` hoặc `FACE_TIMEOUT` (phiên kết thúc, bắt đầu lại bằng `POST /v4/face/login`).

### POST /v4/face/verify  (đã đăng nhập: xác minh lại khuôn mặt cho bước danh tính)
→ `{"verify_id", "expires_in": 120, ...LOGIN_STATE}`. Tài khoản chưa đăng ký khuôn mặt: 409 `FACE_NOT_ENROLLED`.
Quá 10 lần thất bại/tài khoản/15 phút: 429.
### POST /v4/face/verify/{verify_id}/frame
Như `/v4/face/login/{id}/frame` nhưng so 1:1 với khuôn mặt của chính tài khoản. Thành công: `{"verify_id", ...LOGIN_STATE,
"score"}`; `verify_id` dùng được một lần trong 10 phút ở `POST /v4/applications/{id}/identity`. Thất bại: **403**
`FACE_NOT_RECOGNIZED` / `FACE_LIVENESS_FAILED` / `FACE_TIMEOUT` (phiên đăng nhập vẫn giữ).

## 2. Công khai — `/v4/public`

### GET /v4/public/overview
```json
{"stats": {"sellers": 3, "applications": 12, "loans_active": 4, "disbursed_total": 559600,
           "banks": 10, "chain_blocks": 51, "agents": 5},
 "banks": [{"code": "WEBANK", "name": "WeBank", "region": "CN"}],
 "agents": [{"id": 1, "name": "Xác minh", "summary": "…"}],
 "simulated": true}
```

### GET /v4/public/demo-stores  (chỉ dev/demo)
Danh sách link cửa hàng mẫu cho 9 kịch bản:
```json
{"stores": [{"scenario": "lan", "label": "Chị Lan, hồ sơ chuẩn", "url": "https://haohuo.jinritemai.com/views/shop/index?id=58812",
             "expect": "Duyệt 139.900"}]}
```

## 3. Hồ sơ vay (người bán) — `/v4/applications`

### Trạng thái `status` (loan circle, 14/10/2026)
`draft` → `identified` → `consented` → `verifying` → `needs_answer` / `verified` / `rejected` / `out_of_scope` / `escalated`
→ (`verified`, Agent 2 dựng phiếu, Agent 3 + cổng duyệt **hạn mức**, các ngân hàng duyệt song song) `offered` · `rejected` · `escalated`
→ (`offered`) `selected` → `signed` → `disbursed` → `closed`; `offered`/`selected` quá 7 ngày → `expired`.

### Chuyển trạng thái (ai đổi)
| Từ | Sang | Ai / khi nào |
|---|---|---|
| — | `draft` | seller `POST /applications` (Agent 1 bước 1–2; loại người vay phải khớp đăng ký, lệch → `rejected` POL_BORROWER_TYPE) |
| `draft` | `identified` / `rejected` | `/identity` |
| `identified` | `consented` | `/consent` (đủ 3 ô) |
| `consented` | `offered` · `needs_answer` · `rejected` · `out_of_scope` · `escalated` | `/verify`: Agent 1 → Agent 2 (phiếu, đề xuất `full`) → Agent 3 + cổng → bộ điều phối gửi ngân hàng song song |
| `needs_answer` | như trên | `/answers` |
| `escalated` | `offered` · `rejected` | officer `/decision` (`approve`/`smaller_offer` = duyệt hạn mức rồi gửi ngân hàng) |
| `offered` / `selected` | `selected` | `/select` (chọn lại được đến khi ký) |
| `selected` | `signed` → `disbursed` | `/sign` (giữ chỗ hạn mức ngân hàng, tài khoản trung gian, giải ngân trong cùng request) |
| `disbursed` | `closed` | Agent 4 khi trả hết (đến hạn, trả trước) |

Không còn `approved`, `smaller_offer`, `/accept`, `/accept-smaller`. Cổng ra "phương án nhỏ hơn" thì hạn mức gửi ngân hàng
là phương án đó (`decision.option_id = "step70"`), người vay không phải nhận lại.

`next_action.key` ∈ `identity` · `consent` · `plan` · `verify` · `answer` · `wait_banks` · `select` · `sign` · `wait_payout` ·
`wait_officer` · `reapply` · `view_loan` · `none`.

APPLICATION có thêm: `borrower_type`, `statements`, `syndicate` (người bán: `{status, limit, split, reduced, approved_at,
expires_at, hash}`; cán bộ: thêm `rounds` với câu trả lời và thời gian từng ngân hàng), `selection` (thẻ chi phí + lịch),
`contract` (bảng chi phí, điều khoản, lịch, ngân hàng, `legs` sau khi ký). `offer` có `limit`, `suggested`, `need`,
`binding_cap` (`affordability|group_cap|type_cap`), `tenors`, `tenor_max`, `methods`, `expires_at`, `banks`.

### Người bán thấy gì (bản rút gọn, bắt buộc)
Khi người gọi là seller, APPLICATION bỏ: `control.phase0`, `control.phase1`, `control.phase2.resolved`,
`control.legal`, mọi giá trị ngưỡng, `verification.flags[].code` thuộc nhóm AML (`AML-*`, `RISK_PASS_THROUGH`)
và `llm_notes`. Người bán chỉ thấy `decision.reason` / `verification.reason` (REASON hoặc `null`) và
`control.gate.decision`. Cán bộ/admin thấy đủ.

### APPLICATION (dạng trả về đầy đủ)
```json
{
  "id": "app_…", "code": "APP-2026-1013-0001", "status": "offered", "tier": 2,
  "created_at": "…", "updated_at": "…", "seller": {"id": "usr_…", "display_name": "Lâm Lan"},
  "stores": [{"url": "…", "platform": "douyin", "entity": "Hộ kinh doanh Lâm Lan", "reg_no": "92440106MA9…",
              "rating": 4.6, "category": "Thời trang nữ", "registry": {"status": "active", "registered": "2023-05-18"}}],
  "identity": {"cccd": true, "face": true, "result": {"face_match": true, "entity_match": true, "account_owner_match": true}},
  "consent": CONSENT,
  "plan": PLAN | null,
  "verification": VERIFICATION | null,
  "offer": OFFER | null,
  "proposal": {"option_id": "full", "amount": 139900, "rationale": [{"claim": "…", "evidence_ref": "sheet.B3.unit_price_used"}]} | null,
  "control": CONTROL | null,
  "decision": DECISION | null,
  "loan_id": "loan_…" | null,
  "signoff": {"status": "pending|signed|overridden|failed", "split": [{"bank": "WEBANK", "pct": 0.4, "amount": 55960}],
              "declined": [], "at": "…"} | null,
  "next_action": {"key": "verify", "label": "Chạy xác minh"},
  "simulated": true
}
```
`CONSENT` (ba ô riêng, ký Ed25519 trên `signed`; `sign_method` = `face|otp`; `signature.simulated: true` = khóa demo):
```json
{"id": "CS-286cd3", "scopes": [{"key": "credit_inquiry", "title": "…", "covers": "…", "doc": "/app/giaodien/van-ban/tra-cuu-tin-dung.html"}],
 "accounts": [], "sign_method": "face",
 "signed_at": "2026-10-13T07:12:26Z", "expires_at": "2027-01-11T07:12:26Z", "revoked_at": null,
 "signature": {"alg": "ed25519", "public_key": "<64 hex>", "sig": "<128 hex>", "simulated": true, "method": "face"},
 "signed": {"consent_id": "CS-286cd3", "application": "APP-2026-1013-0001",
            "scopes": ["credit_inquiry", "share_partners", "data_processing"], "accounts": [], "signed_at": "…", "expires_at": "…"},
 "chain_tx": "0x…", "hash": "sha256:…"}
```
Ủy quyền dùng được khi: chưa rút, chưa hết hạn (`consent.ttl_days` = 90), chữ ký đúng trên `signed`, đủ ba ô.
Thiếu điều kiện → `/verify`, `/answers`, `/select`, `/sign` trả 400 `INVALID_STATE` `details.consent ∈ revoked|expired|signature|scope`
(không công cụ dữ liệu nào chạy, kể cả FATE); Agent 4 kiểm lại ngay trước giải ngân.

`PLAN` = `{"event": "11.11", "item": "Áo khoác nữ", "group": "quần áo", "brand": "", "auth": "Tôi là chủ nhãn hiệu",
"flavor": null, "qty": 5000, "price": 80, "supplier": "SUP-0091", "inventory": 40000, "own_capital": 60000,
"other_loans": 0, "statements": [{"month", "revenue", "cost"}] | null, "suggested": {…}}`
`group` ∈ `quần áo, thực phẩm đóng gói, thực phẩm rời, thực phẩm chức năng, dược, thiết bị y tế I, thiết bị y tế II, thiết bị y tế III, thuốc lá điện tử, dịch thuốc lá điện tử, điện tử, khác`.

`VERIFICATION`:
```json
{"state": "VERIFIED",
 "steps": [{"n": 5, "key": "revenue", "title": "Doanh thu theo thuế", "tool": "pull_revenue(tax)", "status": "ok", "summary": "…"}],
 "flags": [FLAG], "questions": [QUESTION],
 "derived": {"first_sale_month": "2024-08", "months": 26, "monthly_avg_12m": 166700, "growth_3m": 0.20,
             "peak_seasons": 2, "last_peak": 276870, "spike_ratio": 1.1, "invoice_unit_price_3m": 62,
             "gross_margin": 0.40, "interbank_score": 3, "late_12m": 0,
             "statements": {"verdict": "verified|unverified|mismatch", "deviation": 0.05, "months": 3} | null},
 "tool_calls": [{"id": "TC-101", "tool": "pull_revenue", "input": {}, "output": {}, "at": "…", "simulated": true}],
 "record_hash": "sha256:…", "chain_tx": "0x…", "reason": REASON | null}
```
`FLAG` = `{"code": "RISK_SALES_SPIKE|RISK_STATEMENT_MISMATCH|DATA_STATEMENT_UNUSED|RISK_PRICE_DEVIATION|RISK_INVENTORY_HIGH|RISK_SUPPLIER_LINKED|DATA_SOURCE_GAP|DATA_PARTNER_MISSING", "status": "open|resolved_by_check|explained_unverified|hard", "evidence_tool_call": "TC-121", "penalty": "downgrade_1", "note": "…"}`
`QUESTION` = `{"flag": "RISK_INVENTORY_HIGH", "text": "…", "choices": [{"key", "label"}]}`
`REASON` (lý do 3 phần, LAW-03) = `{"law": "…", "factor": "…", "fix": "…"}`; `null` khi phải giữ kín (AML).

`OFFER`:
```json
{"options": [OPTION], "limit": 200000, "suggested": 200000, "requested": 400000, "need": 210000,
 "binding_cap": "affordability|group_cap|type_cap",
 "reason_codes": [{"code": "PRICE_FROM_INVOICE", "impact": -90000, "block": "B3", "text": "…"}],
 "grade": "B", "score": 80, "group": 2, "rate": 0.10, "tenors": [3, 6, 12], "tenor_max": 12,
 "methods": [{"key": "installment", "label": "Trả góp cố định theo tháng"}, {"key": "revenue", "label": "Trả theo doanh thu"}],
 "borrower_type": "individual_business", "currency": "CNY",
 "blocks": {"B3": {"unit_price_used": 62, "need": 210000}, "B4": {"forecast": 200040, "prudent": 140028},
            "B5": {"sweep_cap": 0.6316, "sweep_usable": 0.63}, "B6": {"score": 80, "grade_before": "B", "grade": "B"},
            "B7": {"rate": 0.10}, "B8": {"affordability": 962374, "group_cap": 250050, "type_cap": 200000,
            "binding_cap": "type_cap", "limit": 200000, "suggested": 200000},
            "B9": {"tenors": [3, 6, 12], "tenor_max": 12, "revenue_rate_max_tenor": 0.14, "min_principal_share": 0.3}},
 "slider": {"min": 10000, "max": 200000, "step": 100}, "due_day_max": 28,
 "expires_at": "2026-10-21T…Z", "banks": [{"bank": "WEBANK", "pct": 0.4, "role": "lead", "name": "WeBank"}],
 "card": {"amount", "rate", "apr", "fees": 0, "tenor_m", "method", "due_day", "first_payment", "total_interest",
          "total_due", "first_due_date", "final_due_date", "payee", "payee_split"},
 "explanation": "…", "explanation_source": "template|llm"}
```
`OPTION` = `{"id": "full|step70|step50", "amount": 200000, "rate": 0.10, "tenor_m": 12, "max_interest": 10833, "total_due": 210833, "monthly_principal": 16666, "label": "Hạn mức đầy đủ"}` (lãi ước tính; lịch chính xác theo ngày giải ngân và ngày trả)

`CONTROL`:
```json
{"phase0": {"ruleset_version": "rules-v1.2", "results": [{"code": "RISK-04", "ok": false, "level": "warn", "value": 0.29, "what": "…"}], "floor": "approve"},
 "phase1": {"verdict": "smaller", "option_id": "step70", "concerns": [{"rule": "RISK-04", "note": "…", "citations": []}],
            "checked_ok": ["…"], "seal": {"hash": "sha256:…", "chain_tx": "0x…", "at": "…"}},
 "phase2": {"verdict": "approve", "option_id": "full", "resolved": [{"rule": "RISK-04", "by": ["sheet.B3.unit_price_used"], "note": "…"}],
            "asked_agent2": false, "final_hash": "sha256:…", "chain_tx": "0x…"},
 "bank_policies": [{"bank": "BOC", "eligible": false, "reason": "Chỉ nhận hạng B trở lên"}],
 "legal": [{"code": "POL-05", "ok": false, "action": "Bắt buộc trả nhà cung cấp SUP-0091", "citations": [{"article_id": "WCLOAN-2024#30", "quote": "…"}]}],
 "gate": {"conditions": [{"text": "Biên bản VERIFIED; mỗi cờ đóng có bằng chứng", "ok": true}], "decision": "approve"}}
```

`CONTROL.gate` có thêm `"auto_group": "thời trang|t2"`, `"auto_enabled": true`; điều kiện 5 sai khi nhóm duyệt tự động bị
tắt do nợ xấu. `CONTROL.phase0` có thêm `"event": {"event": "11.11", "loans": 5, "exposure": …, "shortfall": …, "ratio": 0.3505,
"fires": true} | null` (quy tắc EVENT-01). `CONTROL.phase1` có thêm `"judgment_source": "code|llm"`, khi `llm`:
`"llm_verdict"`, `"llm_tool_calls": [{"id": "TC-L1", "tool": "search_articles", "input": {…}}]`; băn khoăn do mô hình nêu có
`"source": "llm"` (trích dẫn sai/chưa hiệu lực → băn khoăn bị bỏ, ghi sự kiện `citation_rejected`).

`DECISION` = `{"kind": "approve|smaller_offer|escalate|reject", "option_id": "full", "amount": 139900, "by": "gate|officer", "reason": REASON | null, "at": "…"}`

### Endpoint
| Method | Path | Vào | Ra | Ghi chú |
|---|---|---|---|---|
| POST | `/v4/applications` | `{"tier": 2, "borrower_type": "individual_business|company", "store_urls": ["…"]}` | 201 APPLICATION | Link không đọc được → 400 `details.fallback = "reg_no"` |
| GET | `/v4/applications` | `?status=` `&seller=` | `{"items": [APPLICATION_SUMMARY]}` | |
| GET | `/v4/applications/{id}` | | APPLICATION | seller chỉ của mình (403) |
| POST | `/v4/applications/{id}/identity` | `{"cccd": true, "face": true, "face_verify_id"?}` | APPLICATION | Tài khoản đã đăng ký khuôn mặt (và máy chủ có mô hình): bắt buộc `face_verify_id` từ `/v4/face/verify`, thiếu/hết hạn → 400 `field: face_verify_id` |
| POST | `/v4/applications/{id}/consent/draft` | `{"scopes": ["credit_inquiry","share_partners","data_processing"], "method": "face|otp"}` | `{"document", "message", "alg": "ed25519", "boxes"}` | bản để ký |
| POST | `/v4/applications/{id}/consent` | như trên + `"signature"` (tùy chọn ở dev/demo) | APPLICATION | thiếu ô → 400 `details.missing`; `consent.sign_method` |
| POST | `/v4/applications/{id}/consent/revoke` | `{}` | APPLICATION | |
| PUT | `/v4/applications/{id}/plan` | PLAN + `"statements": [{"month": "2026-09", "revenue": 188800, "cost": 0}]` (tùy chọn, ≤ 6) | APPLICATION | ảnh doanh thu lệch thuế ≤ 15%: được dùng (+5% hệ số thận trọng); > 30%: cờ RISK_STATEMENT_MISMATCH, chuyển cán bộ |
| POST | `/v4/applications/{id}/verify` | `{}` | APPLICATION | |
| POST | `/v4/applications/{id}/answers` | `{"flag": "RISK_SALES_SPIKE", "choice": "wholesale"}` | APPLICATION | |
| GET | `/v4/applications/{id}/offer` | | OFFER | |
| POST | `/v4/applications/{id}/quote` | `{"amount": 150000, "tenor_m": 6, "method": "installment|revenue", "due_day": 10}` | thẻ chi phí + `schedule` | chỉ đọc; `fees` = 0; `apr` = `rate` |
| POST | `/v4/applications/{id}/what-if` | `{"own_capital", "inventory", "qty", "supplier"}` | `{"need", "suggested", "limit", …}` | ước tính |
| GET | `/v4/applications/{id}/messages` | | `{"items": [MESSAGE]}` | |
| POST | `/v4/applications/{id}/messages` | `{"text": "…"}` | `{"items": [MESSAGE]}` | Agent 2 |
| POST | `/v4/applications/{id}/select` | `{"amount", "tenor_m", "method", "due_day"}` | APPLICATION (`selected`) | trong hạn mức, kỳ hạn theo loại người vay, ngày 1–28; hạn mức hết hạn → 400 `LIMIT_EXPIRED` (+ `expired`); đang có khoản vay → 400 `ONE_LOAN_AT_A_TIME` |
| GET | `/v4/applications/{id}/contract` | | CONTRACT | người bán mở → bắt đầu đồng hồ đọc `read_seconds` (20) |
| POST | `/v4/applications/{id}/sign` | `{"read_ack": true, "webank_account": "6222…", "use_of_funds_commitment": true, "supplier_account": "…" (khi > 100.000), "guarantee": true (doanh nghiệp), "method": "face|otp"}` | APPLICATION (`disbursed`, `loan_id`) | đọc chưa đủ → 400 `READ_TIME` |
| POST | `/v4/applications/{id}/manual-channel` | `{}` | APPLICATION → `escalated` | khi `offered`/`selected` |
| POST | `/v4/applications/{id}/request-human` | `{"reason": "…"}` | APPLICATION | |
| GET | `/v4/applications/{id}/flow` | | FLOW (B1, B3–B9, B10, B12 vòng duyệt ngân hàng, `selection`, `contract`, B11 lịch trả) | officer/admin |
| GET | `/v4/applications/{id}/trace` | | | |

`CONTRACT` = `{"id": "HD-…", "amount", "rate", "apr", "fees": 0, "penalty_rate": 0.15, "tenor_m", "method", "due_day",
"first_due_date", "final_due_date", "total_interest", "total_due", "schedule": [{k, due_date, days, principal, interest, payment, outstanding_after}],
"payee": {"kind": "business_account|split", "to_account", "to_supplier", "supplier"}, "banks": [{bank, name, pct, amount}],
"terms": ["…"], "complaint_channel", "read_seconds": 20, "issued_at", "needs": {"supplier_account", "guarantee"}, "hash",
"signed_at", "legs": [{bank, pct, amount, contract_id}], "chain_tx"}`

`MESSAGE` = `{"id", "from": "seller|agent2|system", "text", "card": OPTION | null, "blocked_numbers": 0, "at"}`
(`blocked_numbers` = số con số/lời hứa bị chặn trong các bản nháp của mô hình; sau 3 bản nháp bị chặn, tin trả lời là lời
giải thích mẫu.) `QUESTION` có thêm `"text_source": "llm"` khi câu hỏi được mô hình viết lại (giữ nguyên mọi con số).

## 4. Khoản vay — `/v4/loans`
`LOAN`:
```json
{"id": "loan_…", "application_id": "app_…", "status": "active|overdue|closed", "currency": "CNY",
 "amount": 150000, "rate": 0.10, "apr": 0.10, "penalty_rate": 0.15, "tenor_m": 6, "method": "installment|revenue",
 "due_day": 10, "revenue_rate": null, "start_date", "first_due_date", "final_due_date", "total_interest", "total_due",
 "contract_id": "HD-…", "payee": {"kind": "split", "to_account": 100000, "to_supplier": 50000, "supplier": "SUP-0091"},
 "schedule": [{"k": 1, "due_date": "2026-11-10", "principal": 25000, "interest_est", "payment_est",
               "status": "upcoming|paid|minimum|overdue|paid_late|prepaid", "choice": "minimum"|null,
               "interest", "principal_due", "amount_due", "paid", "revenue_base"}],
 "principal_outstanding": 150000, "arrears": {"penalty", "interest", "principal", "since", "penalty_to"}, "owed_now": 0,
 "overdue_days": 0, "max_overdue_days": 0, "bureau": [{"kind": "overdue_30|closed", "as_of", "tx"}],
 "majority": {"banks": ["WEBANK","CMB"], "share": 0.7, "need": 0.6667, "text"} | null,
 "account": {"bank": "WeBank", "number", "balance", "inflow_total", "transfers": [{on, amount, kind, label, flag*}]},
 "receiving_account": {"bank", "number", "locked": true}, "clock": "2026-10-14",
 "next_due": ROW | null, "minimum": {"allowed", "why", "quote": {k, interest, principal, payment, deferred}},
 "prepay_quote": {"as_of", "overdue", "interest_days", "interest", "principal", "total", "fee": 0},
 "shares": [{"bank", "name", "pct", "amount", "repaid", "contract_id", "outstanding"}],
 "repaid", "outstanding", "repayments": [{"id", "at", "amount", "split": [{bank, amount}], "detail": {kind, penalty, interest, principal, as_of}, "chain_tx"}],
 "withdrawal_id", "alerts"*, "early_warning", "fate"*, "bank_report"*, "reminders", "notices", "use_of_funds"}
```
(* chỉ cán bộ.) Thu nợ: ngày trả trích tài khoản kinh doanh WeBank, phân bổ lãi phạt → lãi → gốc, lãi theo ngày thực tế
(năm 365), chia các ngân hàng theo tỷ lệ góp. 3 ngày ân hạn rồi lãi phạt (1,5 × lãi, ≤ 24%); quá hạn 30 ngày báo trung tâm
tín dụng và ghi nhóm ngân hàng nắm ≥ 2/3 dư nợ. Trả tối thiểu: chỉ trả góp, kỳ hạn ≥ 3, tối đa 2 kỳ liền, phần gốc hoãn chia
đều các kỳ sau. Trả trước không phí.

| Method | Path | Vai | Ghi chú |
|---|---|---|---|
| GET | `/v4/loans` | seller (của mình), officer, admin | `{"items": [LOAN]}` |
| GET | `/v4/loans/{id}` | như trên | LOAN |
| POST | `/v4/loans/{id}/simulate-inflow` | seller, officer, admin (dev/demo) | `{"amount", "payout_id"?}`: tiền hàng về tài khoản kinh doanh; đang quá hạn thì trích ngay |
| POST | `/v4/loans/{id}/simulate-transfer` | như trên | `{"amount", "kind": "supplier|personal|securities|real_estate|other", "note"}`; chứng khoán/bất động sản → cảnh báo đỏ; chuyển cá nhân > 30% khoản vay → vàng |
| POST | `/v4/loans/{id}/simulate-advance` | như trên | `{"to": "YYYY-MM-DD"}`: Agent 4 chạy từng ngày tới ngày đó |
| POST | `/v4/loans/{id}/minimum` | seller | kỳ tới chỉ trả tối thiểu (lãi + 30% gốc kỳ) |
| POST | `/v4/loans/{id}/prepay` | seller | `{"amount"?}` (bỏ trống = trả hết) từ số dư tài khoản kinh doanh |
| PUT | `/v4/loans/{id}/receiving-account` | seller | `{"bank", "number"}`; chỉ sau khi tất toán |
| GET | `/v4/autopilot/status` | officer, admin | `{"enabled", "agent4": {"interval_seconds", "last_run_at", "last_reason", "loans", "alerts", "error", "next_run_at"}, "agent5": {"interval_seconds", "last_run_at", "last_reason", "report_id", "proposals", "skipped", "error", "next_run_at", "due_reason"}}`. Agent 4 tự giám sát mọi khoản vay mở mỗi `BUOYUP_AGENT4_INTERVAL_SECONDS` (mặc định 300) và ngay sau mỗi lần tiền về; Agent 5 tự hậu kiểm mỗi `BUOYUP_AGENT5_INTERVAL_SECONDS` (mặc định 21600) và sớm hơn sau khi có khoản tất toán hoặc cảnh báo đỏ; tắt bằng `BUOYUP_AUTOPILOT=false`, luôn tắt khi `APP_ENV=test` |
| POST | `/v4/loans/{id}/notices/{notice_id}/answer` | seller (của mình) | `{"choice": "seasonal", "note": ""}` → LOAN; trả lời câu hỏi nguyên nhân của Agent 4 (cảnh báo vàng). `choice` ∈ `seasonal`, `other_account`, `paused`, `invoice_pending`, `other`; trả lời lần hai → 409 |
| POST | `/v4/monitoring/tick` | officer, admin | vào `{"as_of": "YYYY-MM-DD"}` (tùy chọn). Chạy B11, FATE chấm lại (chỉ khi ủy quyền còn hiệu lực; không thì `loan.fate.skipped = "consent"`), kiểm tra dùng vốn (WCLOAN-2024#10: quá `use_of_funds.days` = 15 ngày chưa có hóa đơn mua hàng khớp → `use_of_funds.status = "missing"` + cảnh báo vàng tín hiệu `use_of_funds`), cập nhật công tắc duyệt tự động, và chuyển hồ sơ `needs_answer` quá `flags.open_days` (3) ngày sang `escalated`. Ra `{"alerts": [ALERT], "checked": 1, "escalated": ["app_…"], "simulated": true}` |
| GET | `/v4/alerts` | officer, admin | `ALERT` = `{"id","loan_id","level":"yellow|red","signals":[…],"text","at","acked":false}` |
| POST | `/v4/alerts/{id}/ack` | officer, admin | |

## 5. Cán bộ — `/v4/officer`
| Method | Path | Ra |
|---|---|---|
| GET | `/v4/officer/queue` | `{"items": [APPLICATION_SUMMARY + {"why": "AML-STR-01|RISK-06|…"}]}` hồ sơ `escalated`/`needs_answer` quá hạn. `why` mới: `EVENT_CONCENTRATION` (EVENT-01), `AUTO_APPROVAL_OFF` (nhóm bị tắt duyệt tự động), `BANK_DECLINED` (ngân hàng từ chối ký, không còn phương án chia), `NO_ELIGIBLE_BANK`, mã cờ (`RISK_INFLOW_GAP`, … khi tự chuyển do quá hạn trả lời) |
| POST | `/v4/officer/applications/{id}/decision` | vào `{"decision": "approve|reject|smaller_offer|continue", "option_id": "full", "note": "…"}` → APPLICATION. `approve`/`smaller_offer` chỉ khi hồ sơ đã có `offer`; hồ sơ bị chuyển ở bước xác minh dùng `continue` (cán bộ xác nhận, hồ sơ đi tiếp sang `offered`); `override_signoff` chỉ khi hồ sơ `approved` đang chờ ngân hàng ký → giải ngân ngay (ghi chuỗi `officer_decision`) |
| POST | `/v4/officer/applications/{id}/reauthorize-payout` | → APPLICATION. Hồ sơ đã ký mà giải ngân dừng (quyền giải ngân một lần hết hạn, lệnh lỗi): cán bộ cấp quyền mới cho Agent 4a, 4a chạy một lần; thành công thì bỏ `escalation` |
| GET | `/v4/portfolio` | `{"kpis": {"loans_active", "outstanding", "disbursed_total", "approval_rate", "avg_amount", "red_alerts"}, "by_bank": [{"bank","outstanding","share_pct"}], "by_grade": […], "by_event": [{"event":"11.11","exposure","shortfall_50pct","shortfall_ratio"}], "auto_approval": [AUTO_SWITCH], "simulated": true}` |

`AUTO_SWITCH` = `{"group": "thời trang|t2", "enabled": true, "manual": false, "npl_ratio": 0.0, "loans": 1, "bad": 0, "reason": null, "updated_at": "…"}`.
Nhóm = ngành (thời trang, mỹ phẩm, tạp hóa, điện tử, khác) × tầng ([INFER], C12). Tự tắt khi nhóm có ≥ `gate.npl_min_loans` (10)
khoản và tỷ lệ nợ xấu (quá hạn ≥ 90 ngày, cảnh báo đỏ hoặc xóa nợ) ≥ `gate.npl_off_ratio` (8%); công tắc admin đặt tay
(`manual: true`) không bị ghi đè.

`APPLICATION_SUMMARY` = `{"id","code","status","tier","seller_name","store_entity","amount_requested","amount_offered","grade","updated_at","flags_open"}`

## 5b. Khiếu nại — `/v4/complaints`  (bàn khiếu nại, rà soát 16/10/2026 mục 4)

Người vay gửi từ ứng dụng; cán bộ ghi thay khiếu nại nhận qua tổng đài 95384 hoặc email (`channel`, `seller_email`).
Tiếp nhận là xác nhận ngay; lý do đã ghi của quyết định bị khiếu nại được đính kèm ngay (`reasons`: lý do, mã giảm
hạn mức B8, `SEED_LOAN`, `THIN_FATE_CAP`); ca AML chỉ nhận lời văn trung tính (`reasons.hidden: true`). Người xem xét
phải khác cán bộ đã quyết định. Trả lời có lý do trong `complaint.answer_days` ngày làm việc (mặc định 5), gia hạn có
báo trước tới `complaint.max_days` (15); quá hạn → `status: "escalated"` (trưởng nhóm). Mở và trả lời ghi lên chuỗi
(`complaint_opened`, `complaint_answered`).

| Phương thức | Đường dẫn | Ai | Vào → Ra |
|---|---|---|---|
| POST | `/v4/complaints` | seller (ứng dụng); officer, admin (ghi thay) | `{"category": "rejection|limit|fees|debit|data|other", "text", "application_id"?, "loan_id"?, "channel"?, "seller_email"?}` → 201 COMPLAINT |
| GET | `/v4/complaints?status=` | seller (của mình); officer, admin (tất cả) | → `{"items": [COMPLAINT], "channel", "deadlines"}` |
| GET | `/v4/complaints/{id}` | chủ khiếu nại; officer, admin | → COMPLAINT |
| POST | `/v4/complaints/{id}/assign` | officer, admin (không phải người đã quyết định: 403) | → COMPLAINT (`in_review`) |
| POST | `/v4/complaints/{id}/extend` | cán bộ đang xem | `{"days": 1..10, "note"}` → COMPLAINT; không quá `max_due` |
| POST | `/v4/complaints/{id}/answer` | cán bộ đang xem | `{"outcome": "upheld|changed|reopened", "text"}` → COMPLAINT; `reopened` đưa hồ sơ bị từ chối về hàng đợi cán bộ (`escalation.why = "COMPLAINT"`) |

`COMPLAINT` = `{"id": "KN-…", "category", "category_label", "channel", "text", "status": "acknowledged|in_review|escalated|answered",
"application_id", "loan_id", "reasons", "created_at", "ack_at", "answer_due", "max_due", "answered_at", "outcome", "outcome_label",
"answer", "overdue"}`; cán bộ thấy thêm `seller_user_id`, `decided_by`, `assigned_to`, `history`.
Hồ sơ `escalated` có `expected_review_at` = lúc chuyển + `complaint.review_days` ngày làm việc.

## 6. Hậu kiểm (Agent 5) — `/v4/postaudit`
| Method | Path | Vai | Ghi chú |
|---|---|---|---|
| POST | `/v4/postaudit/run` | officer, admin | tạo báo cáo + đề xuất từ dữ liệu khoản vay → `{"report": REPORT, "proposals": [PROPOSAL]}`. Có mô hình: Agent 5 đọc báo cáo, có thể thêm đề xuất qua `propose_change` (chỉ `prudence.*`, `flags.*`, `gate.auto_limit`, `scorecard.grades.*`; đổi tối đa ±25%; cần `evidence_ref` là một mục của báo cáo; evidence bắt đầu `[Agent 5 · mô hình]`) và viết `REPORT.summary = {"text", "source": "llm", "proposals": [id]}` (null nếu không có mô hình hoặc tóm tắt có số không có trong báo cáo); tóm tắt nằm trong báo cáo trước khi băm lên chuỗi. Tóm tắt có số lạ được sinh lại một lần rồi mới bỏ. `REPORT.proposals` (tham số, cũ, mới, bằng chứng) và `REPORT.llm_tool_calls` nằm trong phần được băm; `REPORT.auto_cohort = {loans, bad_rate, warn, hard, status}`; mỗi đề xuất có kết quả chạy song song trong `evidence`. Ngành có dưới `BUOYUP_AGENT5_MIN_SAMPLE` (mặc định 30) mẫu: không đề xuất hệ số thận trọng; `prudence.*` đổi tối đa 0,04 mỗi 90 ngày |
| GET | `/v4/postaudit/reports` | officer, admin | |
| GET | `/v4/postaudit/proposals` | officer, admin | |
| POST | `/v4/postaudit/proposals/{id}/decision` | admin (officer chỉ đề nghị) | `{"decision": "approve|reject", "note"}` → khi approve: tạo phiên bản tham số mới, hash lên chuỗi. Người đã chạy lần hậu kiểm sinh ra đề xuất không được tự quyết → 403 `FORBIDDEN` (NETLOAN-2020#39). Từ chối cũng ghi chuỗi (`proposal_decision`). Duyệt `prudence.*` vượt 0,04 cộng dồn trong 90 ngày → 400 `INVALID_STATE` |
| GET | `/v4/params` | officer, admin | `{"version": "v4.0", "hash": "sha256:…", "chain_tx", "params": {...}, "history": [...], "ruleset": {"version": "rules-v1.2", "hash": "sha256:811f…", "chain_tx": "0x3ded…", "anchored_hash": "sha256:811f…"}}` (bộ quy tắc Agent 3 được ghi lên chuỗi `system`/`ruleset` khi khởi động nếu đổi; kho luật trích từ docs/agents/TQ ghi `system`/`law_corpus` với `corpus_hash`) |

`REPORT` = `{"id","at","cohort":{"loans":n,"closed":n},"findings":[{"metric":"prudent_hit_rate","segment":"thời trang","value":0.74,"target":0.80,"text":"…"}],"rule_stats":[{"rule":"RISK-04","fired":n}],"manipulation_blocked":n,
"citation_rejected":[{"rule":"RISK-05","count":1}],"persuaded_wrong":0,
"a2_a3_disagreement":{"rate":1.0,"cases":1,"disagree":1,"band":[0.05,0.6],"flag":true},"a2_a3_disagreement_rate":1.0,
"legal_rule_hits":[{"rule":"POL-05","hits":1}],"requested_by":"usr_…"}`
(`persuaded_wrong` = số ca pha 2 nhẹ hơn pha 1 mà khoản vay sau đó xấu; `flag` = tỷ lệ bất đồng pha 1 Agent 3 / đề xuất Agent 2 nằm ngoài `band`.)
`PROPOSAL` = `{"id","param":"prudence.thời trang","from":0.70,"to":0.66,"evidence":"…","status":"pending|approved|rejected","decided_by","decided_at"}`.
`param` có thể là `prudence.<ngành>`, `gate.auto_limit` (khoản duyệt tự động có tỷ lệ xấu ≥ `agent5.bad_rate_trigger`, ví dụ 500000 → 400000),
`scorecard.grades.<A-D>` (+5 điểm khi hạng đó xấu ≥ 2× ngưỡng), `revenue.statement_bonus` (−0,02 khi hồ sơ nâng hạn mức nhờ ảnh doanh thu trả kém). Chỉ một đề xuất `pending` cho mỗi tham số.

## 7. Ngân hàng — `/v4/banks`, `/v4/bank`
`BANK` = `{"code":"WEBANK","name":"WeBank","region":"CN","currency":"CNY","active":true,"limit_total":5000000,"limit_used":55960,
"policy":{"min_grade":"C","tiers":[1,2],"min_amount":10000,"max_amount":2000000,"max_rate":0.15,"excluded_groups":["thuốc lá điện tử"],"min_share":0.30},
"contract_id":"BU-WEBANK-2026-01","public_key":"hex…"}`

| Method | Path | Vai |
|---|---|---|
| GET | `/v4/banks` | mọi vai đã đăng nhập (seller thấy tên + khu vực) |
| GET | `/v4/banks/{code}` | officer, admin, bank (của mình) |
| PUT | `/v4/banks/{code}/policy` | admin, bank (của mình). Ra BANK + `"policy_chain_tx": "0x…"` (bản trước/sau ghi lên chuỗi `system`/`bank_policy`). Chính sách có thể có `cost_of_funds` (ví dụ 0.05) dùng cho sàn lãi B7 |
| PUT | `/v4/banks/{code}/public-key` | admin, bank (của mình). Vào `{"public_key": "<64 hex X25519>"}` → BANK + `"keys": [{"public_key","active_from","retired_at"}]`. Lệnh mới khóa bằng khóa mới; lệnh cũ chỉ mở bằng khóa cũ; máy chủ không giữ khóa riêng mới (bank portal hiện `locked: true` tới khi ngân hàng dán khóa). Không ghi lên chuỗi; chế độ remote chuyển tiếp tới dịch vụ chuỗi. Sai định dạng → 400; khóa đang dùng → 400 |
| GET | `/v4/bank/portfolio` | bank: `{"bank": BANK, "shares": [{"loan_id","amount","repaid","status"}], "totals": {…}}` |
| GET | `/v4/bank/withdrawals` | bank: các lệnh có phần của mình, đã giải mã phần tóm tắt + phần của mình: `{"items":[{"id","at","summary":{…},"my_piece":{"pct","amount","contract_id"},"fingerprint_ok":true}]}` |
| GET | `/v4/bank/syndicate` | bank: các hồ sơ bộ điều phối đã gửi, câu trả lời của ngân hàng mình từng vòng (`decision approve|decline|timeout|not_sent`, `ms`, `reason`), kết quả và phần của mình |
| ~~GET~~ | ~~`/v4/bank/approvals?status=pending`~~ (đã bỏ: ngân hàng duyệt ở vòng song song) | bank: gói phê duyệt phần của mình (chỉ có khi bật `banks.require_signoff`, mặc định tắt): `{"items": [APPROVAL], "enabled": false}` |
| ~~POST~~ | ~~`/v4/bank/approvals/{id}/sign`~~ (đã bỏ) | bank (của mình, khác → 404): `{"decision": "sign|decline", "signature": {…} (tùy chọn), "note": "…"}` → APPROVAL + `{"application_status": "approved|disbursed|escalated", "loan_id"}`. Đủ chữ ký → Agent 4 giải ngân đúng phương án đã ký; từ chối → chạy lại B12 không có ngân hàng đó (ngân hàng đã ký cùng phần giữ chữ ký), hết phương án → `escalated` (`why = BANK_DECLINED`). Ký lại phần đã quyết → 400 |

`APPROVAL` = `{"id": "ba_…", "application_id", "application_code", "bank": "WEBANK", "pct": 0.4, "amount": 55960, "status": "pending|signed|declined|superseded", "chain_tx", "at",
"packet": {"verification": {"state","record_hash","chain_tx","flags","derived"} (đã bỏ AML và llm_notes), "offer": {"grade","score","group","currency","card","blocks","hash"},
"decision": DECISION, "agent3": {"verdict","final_hash","gate"}, "duties": [{"code": "POL-05", "action": "Bắt buộc trả nhà cung cấp SUP-0091"}], "payee": {…}}, "simulated": true}`

## 7b. Kho luật và truy xuất (RAG) — `/v4/legal`  (officer, admin)
Hai kho: `CN` — 794 điều tiếng Trung từ 14 văn bản (`app/core/laws/corpus.json`); `VN` — 1.147 mục từ 5 văn bản
Việt Nam (`app/core/laws/vn/corpus.json`: Luật PCRT 2022, Luật Đầu tư 2025 kèm phụ lục, NĐ 98/2020 bản hợp nhất,
NĐ 59/2006 và NĐ 173/2024; mục bị bãi bỏ có `status: repealed`, `repealed_on`). Kho VN tìm theo âm tiết, cặp âm
tiết và dạng không dấu. Hồ sơ vùng `VN` được truy xuất trên kho VN. Tìm lai: BM25 theo cặp ký tự Trung + bảng
thuật ngữ Việt/Anh → Trung, cộng embedding đa ngôn ngữ chạy trên máy (`BUOYUP_RAG_MODEL`, mặc định
`intfloat/multilingual-e5-large`), trộn RRF. Không có mô hình thì chỉ BM25. Truy xuất chỉ để tìm và hiển thị căn cứ;
quyết định vẫn do quy tắc, trích dẫn vẫn phải khớp nguyên văn và còn hiệu lực.

| Method | Path | Ra |
|---|---|---|
| GET | `/v4/legal/corpora` | `{"items": [{"jurisdiction": "CN\|VN", "name", "articles", "passages", "mode", "corpus_hash", "laws": [...]}], "model"}` |
| GET | `/v4/legal/search?q=&k=5&jurisdiction=CN\|VN&law=&as_of=&use=auto\|bm25\|dense\|hybrid` | `{"query", "mode": "hybrid\|bm25", "corpus_hash", "items": [{"article_id": "ECIG-2022#26", "law", "law_id", "score", "snippet" (đoạn tiếng Trung), "lexical"?, "dense"? (thứ hạng), "in_force", "terms"}]}` |
| GET | `/v4/legal/articles/{article_id}` | `{"article_id", "jurisdiction", "law", "effective", "status", "repealed_on", "repealed_by", "text"}` (mã có `#`: mã hóa thành `%23`) |

Agent 3 lưu kết quả truy xuất theo từng hồ sơ ở `control.retrieval` (chỉ nhân viên thấy):
`{"mode", "model", "queries": [{"topic": "goods|licence|trademark|aml|consent|purpose|payment", "q", "hits": [...]}],
"rule_checks": [{"rule": "LAW-GOODS-01", "cited": [...], "retrieved": [...], "agrees": true}]}`.

## 8. Chuỗi — `/v4/chain`  (đã đăng nhập; mô phỏng FISCO BCOS 4 node nếu không cấu hình chuỗi thật)
| Method | Path | Ra |
|---|---|---|
| GET | `/v4/chain/status` | local: `{"mode":"local","nodes":[{"id":"node0","status":"up","leader":true}],"height":15,"group":1,"consensus":"PBFT","hash_alg":"sha3-256 (mô phỏng)","simulated":true,"withdrawals":2}`. remote: `{"mode":"remote","url":"https://fs.buoyup.app","backend":"fisco-bcos","height":120,"group":1,"consensus":"PBFT","nodes":[{"id":"node0","status":"up|down","leader":false,"sealer":true,"block":120}],"contracts":{"AuditTrail":"0x…","WithdrawalLedger":"0x…"},"explorer_url":"https://fs.buoyup.app/explorer/","catalog_sync":{"at","ok","banks","keys","changed","error"},"hash_alg":"keccak256","outbox_pending":false,"simulated":false,"withdrawals":n}`; remote không trả lời → 503 `CHAIN_UNAVAILABLE` |
| GET | `/v4/chain/blocks?limit=20` | `{"items":[{"height","hash","prev","sealer","txs":[{"tx","kind","ref"}],"at"}]}` |
| GET | `/v4/chain/withdrawals` | `{"items":[{"id","at","pieces":4,"size":3600,"tx","block","merkle_root","piece_fingerprints":["0x…"]}]}` công khai: không lộ ngân hàng |
| GET | `/v4/chain/withdrawals/{id}` | như trên + `slots: n` (+ `remote: {"sealedBy","submittedTo","confirmedNodes","totalNodes","explorerUrl","verifyUrl",…}` và `explorer_url` khi lệnh nằm trên chuỗi remote; `simulated` theo từng lệnh) |
| GET | `/v4/chain/withdrawals/{id}/envelope` | bản mã đúng như đã neo: `{"id","envelope":{"version":1,"alg","withdrawal_id","pieces":[{"index","nonce","ct"}],"slots":[{"epk","nonce","ct"}]},"piece_fingerprints":[…],"merkle_root","tx","block"}` (đầu vào của script tự giải mã; lệnh remote → 400 kèm link explorer của dịch vụ) |
| GET | `/v4/chain/decrypt_withdrawal.py` | công khai (không cần đăng nhập), `text/x-python`: script độc lập `python decrypt_withdrawal.py --api http://localhost:8000 --token <bearer> --id WD-… --key <64 hex>` (hoặc `--file record.json`) mở ô khóa, giải mã, kiểm dấu vân tay + Merkle |
| POST | `/v4/chain/withdrawals/{id}/decrypt` | vào `{"private_key_hex": "…"}` (tùy chọn; bank dùng khóa của mình nếu bỏ trống) → `{"opened": ["summary","WEBANK"], "pieces": {...}, "fingerprints_ok": true}` hoặc `{"opened": [], "message": "Khóa này không mở được ô nào"}` |
| GET | `/v4/chain/cases/{application_id}/verify` | officer/admin: `{"ok": true, "entries": n, "broken_at": null, "reason": null, "chain": [CHAIN_ENTRY]}`; remote thêm `"remote": {"valid": true, "records": n, "head": "0x…", "broken_at": null}` (`ok` = cả hai). Dùng `system` để kiểm chuỗi tham số / bộ quy tắc / chính sách ngân hàng |
| GET | `/v4/chain/verify` | admin: kiểm toàn bộ |
| GET | `/v4/chain/keys` | admin, chỉ dev/demo: khóa demo (để thử giải mã): `{code, public_key, private_key_hex}` mở lệnh mô phỏng cục bộ; ở chế độ remote thêm `chain_public_key, chain_private_key_hex` mở lệnh trên chuỗi thật |
| GET | `/v4/chain/outbox?status=pending` | admin: `{"items": [OUTBOX]}` các lần ghi chuỗi remote |
| POST | `/v4/chain/sync` | admin, chỉ khi `BUOYUP_CHAIN_BACKEND=remote`: kéo danh mục ngân hàng từ dịch vụ chuỗi (hạn mức → `policy.min_rate/max_rate/max_share/max_share_amount/min_share_amount/max_tenor_days/min_store_age_months/min_store_rating/fee_pct`, `contract.creditLine` → `limit_total`, chính sách viết → `policy.chain`, khóa mã hóa → `bu_chain_keys`); cũng chạy khi khởi động → `{"at","ok":true,"banks":10,"keys":10,"changed":["CMB"],"error":null,"chain_tx":"0x…"|null}`; chuỗi không trả lời → 503 |
| POST | `/v4/chain/outbox/flush` | admin: gửi lại các mục `pending` → `{"processed": 1, "counts": {"sent": n, "pending": 0, "failed": 0}, "items": [OUTBOX]}` |

`OUTBOX` = `{"id", "case_id": "app_…", "kind": "verification|…|disburse", "status": "sent|pending|failed", "attempts": 2, "remote_tx": "0x…", "last_error", "updated_at"}`.
**Chế độ remote** (`BUOYUP_CHAIN_BACKEND=remote`, `BUOYUP_CHAIN_URL`, `BUOYUP_CHAIN_TOKEN`): mỗi CHAIN_ENTRY vẫn ghi ở máy
chủ và được neo lên dịch vụ chuỗi (`POST /v1/audit/anchors`); CHAIN_ENTRY trong `/trace` và `/cases/…/verify` có thêm
`"remote": {"tx": "0x…", "block": 101, "status": "sent|pending|failed"}`. Neo `agent3_phase1_seal`, `agent3_conclusion`,
`gate_decision` thất bại → cả yêu cầu `/verify` trả 503 `CHAIN_UNAVAILABLE`, hồ sơ giữ `offered` (không qua pha 2, không duyệt).
Neo khác thất bại → vào outbox. Giải ngân: gửi yêu cầu rõ (người nhận, tài khoản, số tiền theo đơn vị nhỏ nhất — CNY tính
bằng fen — khu vực, tỉnh, `bankSplit`, actor) tới `POST /v1/withdrawals`, dịch vụ mã hóa và neo; chuỗi không trả lời → hồ sơ
giữ `approved`, outbox `disburse`, flush gửi lại cùng `requestId` (`disburse:<application_id>`) nên không bao giờ chi hai lần.

`CHAIN_ENTRY` = `{"seq","kind":"consent|consent_revoked|verification|offer|proposal|agent3_phase1_seal|agent3_conclusion|gate_decision|bank_signoff|officer_decision|disbursement|repayment|params|ruleset|bank_policy|postaudit_report","fingerprint":"sha256:…","head":"…","tx":"0x…","block":n,"at":"…"}`
(Payload `disbursement` có thêm `duties`: nghĩa vụ pháp lý kèm khoản giải ngân, ví dụ POL-05, AML-LTR-01 báo cáo giao dịch lớn trong 5 ngày làm việc; ngưỡng AML-LTR-01 theo loại người nhận: tổ chức 2.000.000, cá nhân 500.000 CNY.)
(Lệnh giải ngân mã hóa được niêm phong thành tx kind `withdrawal` ref = mã `WD-…`; chuỗi của hồ sơ ghi kind `disbursement` trỏ tới nó.)

**Bổ sung từ backend B:** `POST /v4/monitoring/tick` nhận tùy chọn `{"as_of": "YYYY-MM-DD"}` để mô phỏng ngày sau;
LOAN có thêm `application_code`, `seller_name`, `inflow_total`, `fate` (chỉ cán bộ); decrypt trả thêm `merkle_ok`,
`failed_pieces`; `GET /v4/chain/verify` có `broken_withdrawals`. Mô phỏng tiền về trích ngay cả trong ân hạn (để demo
thấy kết quả), sàn lũy kế và cảnh báo vẫn theo ngày.

## 9. Admin — `/v4/admin`
| Method | Path | Ghi chú |
|---|---|---|
| GET | `/v4/admin/users` | `{"items":[USER + {"active":true,"last_login_at"}]}` |
| POST | `/v4/admin/users` | tạo officer/bank/admin: `{"email","password","display_name","role","bank_code"}` |
| PATCH | `/v4/admin/users/{id}` | `{"active": false}` hoặc `{"role": "officer"}` |
| GET | `/v4/admin/audit` | sự kiện hệ thống gần nhất |
| PUT | `/v4/admin/auto-approval/{group}` | `group` mã hóa URL, ví dụ `th%E1%BB%9Di%20trang%7Ct2`. Vào `{"enabled": false, "note": "tạm dừng"}` (đặt tay, `manual: true`) hoặc `{"mode": "auto"}` (trả về quy tắc nợ xấu) → AUTO_SWITCH. Nhóm sai dạng `<ngành>|t<tầng>` → 400 |

## 10. Khu vực và lệnh giải ngân của nhân viên (Agent 4)
| Method | Path | Vai | Vào → Ra |
|---|---|---|---|
| GET | `/v4/regions` | mọi vai đã đăng nhập | `{"regions": [{"code": "CN", "name": "Trung Quốc", "currency": "CNY", "provinces": [{"code": "CN-GD", "name": "Quảng Đông"}, …]}, {"code": "VN", "name": "Việt Nam", "currency": "VND", "provinces": [{"code": "VN-HN", "name": "Hà Nội"}, …]}], "source": "local|remote"}` (mã tỉnh giống dịch vụ chuỗi; hồ sơ chị Lan có `stores[].province = "CN-GD"`) |
| POST | `/v4/withdrawals/manual` | officer, admin (seller/bank → 403) | WITHDRAWAL_IN → 201 STAFF_WITHDRAWAL. Gửi lại đúng dữ liệu cùng `requestId` → cùng lệnh; khác dữ liệu → 409 `CONFLICT`. Chia sai (tổng ≠ 100,00%, > 2 chữ số thập phân theo %, ngân hàng khác khu vực, dưới phần tối thiểu, vượt hạn mức còn lại) → 400 `details.problems`. Tiền tệ ≠ khu vực, tỉnh lạ, thiếu `reason` → 400. `demo: true`: tối đa 10.000.000 VND / 50.000 CNY (400 `details.max`), người yêu cầu ghi `DEMO`. Lệnh thủ công không trừ hạn mức ngân hàng |
| GET | `/v4/withdrawals?limit=50` | officer, admin | `{"items": [STAFF_WITHDRAWAL]}` (giải bằng khóa chủ; production không có khóa chủ trên máy chủ → `locked: true`) |
| GET | `/v4/withdrawals/{id}/verify` | officer, admin | `{"id","ok":true,"merkle_ok":true,"fingerprints_ok":true,"split_total_pct":100.0,"amounts_ok":true,"record_ok":true,"nodes":[{"id":"node0","holds":true}],"simulated":true}` (remote: thêm `checks` của dịch vụ chuỗi) |

`WITHDRAWAL_IN`:
```json
{"requestId": "manual-0001", "user": "U-102938", "account": "6222020200112233", "amount": 100000,
 "currency": "CNY", "region": "CN", "province": "CN-GD",
 "split": [{"bank": "WEBANK", "pct": 0.6}, {"bank": "CMB", "pct": 0.4}],
 "reason": "Agent 4 lỗi sau khi duyệt", "demo": false}
```
`STAFF_WITHDRAWAL` = public withdrawal (§8) +
```json
{"request_id": "manual-0001", "loan_id": null, "amount": 100000, "currency": "CNY", "region": "CN", "province": "CN-GD",
 "requester": "staff:usr_1d43…", "reason": "Agent 4 lỗi sau khi duyệt",
 "shares": [{"bank": "WEBANK", "pct": 0.6, "amount": 60000, "contract_id": "BU-WEBANK-2026-01"},
            {"bank": "CMB", "pct": 0.4, "amount": 40000, "contract_id": "BU-CMB-2026-01"}],
 "fingerprints_ok": true, "locked": false}
```
`reason` chỉ nằm trong phần tóm tắt đã mã hóa (không công khai).

## 11. Cấu hình (backend) liên quan tới giao diện
| Biến / tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `BUOYUP_CHAIN_BACKEND` | `local` | `remote` dùng dịch vụ chuỗi thật |
| `BUOYUP_CHAIN_URL`, `BUOYUP_CHAIN_TOKEN`, `BUOYUP_CHAIN_TIMEOUT_SECONDS` | rỗng, rỗng, 10 | địa chỉ, bearer token (tùy chọn), timeout |
| `LLM_HOST`/`LLM_MODEL_NAME` (+ `LLM_AGENT3_MODEL_NAME`) | rỗng | mô hình cho Agent 1–3; rỗng = đường tất định (`explanation_source: "template"`, `judgment_source: "code"`) |
| `FATE_URL` | rỗng | dịch vụ FATE; rỗng = dữ liệu kịch bản (mô phỏng). FATE không trả điểm → cờ `DATA_PARTNER_MISSING` (không duyệt tự động) |
| `FACE_AUTH_ENABLED`, `FACE_MATCH_THRESHOLD` | `true`, 0.45 | bật xác thực khuôn mặt; ngưỡng cosine ArcFace (cũng là ngưỡng chặn trùng mặt khi đăng ký) |
| `FACE_MODEL_ROOT`, `FACE_DATA_DIR` | `BackEnd/src/Reid`, `BackEnd/src/Reid/data` | buffalo_l tải về `<root>/models/buffalo_l`; mỗi người dùng một thư mục mẫu khuôn mặt |
| `FACE_REQUIRED_AT_SIGNUP` | `true` | khi mô hình đã nạp, đăng ký bắt buộc có phiên quét khuôn mặt |
| `FACE_SAVE_CROPS`, `FACE_DET_SIZE`, `FACE_WARMUP` | `true`, 320, `true` | lưu ảnh mặt 112×112 đã căn chỉnh; cỡ ảnh dò SCRFD; nạp mô hình khi khởi động |
| `banks.require_signoff` | `false` | bật gói phê duyệt cho ngân hàng (§7) |
| `legal.rate_cap`, `legal.ltr_threshold` | 0.24; 2.000.000 / 500.000 | LAW-02, AML-LTR-01 |
| `consent.ttl_days`, `chat.max_per_minute`, `use_of_funds.days` | 90, 12, 15 | |
