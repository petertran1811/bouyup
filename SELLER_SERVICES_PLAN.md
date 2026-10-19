# Kế hoạch triển khai · "Sau khi vay": theo dõi dòng tiền, nhắc nợ, báo cáo cho người bán

Ngày lập: 17/10/2026. Người lập: review FABLE (seller khó tính) trên bản code tại commit `af0b809` + thay đổi chưa commit.
Người thực hiện dự kiến: Opus 5.5. Văn bản này là đặc tả đủ để code mà không cần hỏi lại; chỗ nào còn phải chọn
được ghi rõ ở mục 9.

Đề bài gốc: 9 việc cho Agent 3, 4, 5 (xem `docs/` hoặc tin nhắn của chủ dự án). Kế hoạch này giữ nguyên 9 việc,
thêm **một việc nền (P0)** mà nếu thiếu thì 9 việc kia không đến được người bán, và sửa 3 chỗ đề xuất gốc nói chưa
chính xác so với code hiện có.

---

## 0. Tóm tắt cho người đọc vội

| # | Việc | Module chính | Mới / sửa | Ước lượng |
|---|---|---|---|---|
| P0 | Trung tâm thông báo cho người bán + hộp xác nhận khi trả tiền + phân nhóm chi phí | `api/me_notices.py` (mới), `core/cashflow.py` (mới), `workspace-v4.js` | mới + sửa | 2 ngày |
| 1 | Agent 3 giải thích vì sao bị từ chối / vay ít, và cách cải thiện | `agents/agent3_control.py` → `explain_for_seller()` | sửa | 1 ngày |
| 2 | Agent 4 dự báo thiếu tiền 7 ngày trước kỳ trả | `agents/agent4b_monitor.py` → `_forecast_shortfall()` | sửa | 0,5 ngày |
| 3 | Agent 4 báo khi tiền trả nợ > 20 % doanh thu tháng | `agent4b_monitor.py` → `_debt_service_check()` | sửa | 0,5 ngày |
| 4 | Agent 4 báo ngay khi một khoản chi làm số dư < kỳ tới | `agent4b_monitor.simulate_transfer`, `api/webank.py` (outflow hook) | sửa | 0,5 ngày |
| 5 | Agent 5 báo cáo tháng | `agents/agent5_seller_reports.py` (mới) | mới | 2 ngày |
| 6 | Agent 5 báo cáo quý | cùng module | mới | 1 ngày |
| 7 | Agent 5 báo cáo năm / khi tất toán | cùng module | mới | 1 ngày |
| 8 | Agent 5 nhắc người bán cá nhân sắp chạm 100.000 tệ/năm | cùng module + `core/legal.py` | mới | 0,5 ngày |
| 9 | Mọi báo cáo ghi "% doanh thu đã tính được" | cùng module (hàm `coverage()`) | mới | 0,25 ngày |
| — | Test, nhật ký demo, tài liệu | `tests/test_seller_services.py`, `scripts/demo_seller_services.py` | mới | 1,5 ngày |

Tổng: **~11 ngày công** cho một người, chia được 2 luồng song song (backend agent 4/5 và frontend P0) sau ngày đầu.

---

## 1. Đánh giá đề xuất 9 việc (góc nhìn người dùng khó tính + đối chiếu code)

**Đồng ý với hướng đi.** Khi dùng thử, điểm tôi bực nhất không phải ở lúc vay mà ở lúc *sau khi bấm*: bị chuyển cán bộ
mà không biết vì sao; hạn mức được duyệt mà không có một dòng thông báo; chat không trả lời được "bán ế thì sao".
Chín việc này đánh đúng chỗ hổng đó. Nhưng bản đề xuất có mấy chỗ nói chưa đúng với code, phải sửa trước khi giao dev:

1. **"Không cần dữ liệu mới" là lạc quan quá.**
   - Việc 5 (chia chi vào 6 nhóm) hiện chỉ có 5 loại giao dịch ra do *người bán tự chọn* khi mô phỏng
     (`TRANSFER_KINDS` trong `agent4b_monitor.py`: supplier / personal / securities / real_estate / other). WeBank mới
     có webhook **tiền vào** (`POST /v4/webank/inflows`), chưa có tiền ra. Phải thêm webhook tiền ra có `memo` và
     `payee`, rồi mới phân nhóm bằng luật từ khóa. Trong demo, dùng `bank_statement.outflows` của hồ sơ mẫu
     (có `to.kind` và `memo`, ví dụ "Lương cộng tác viên") để nạp.
   - Việc 6 ("khách trả hàng nhiều không, đánh giá tốt lên hay xấu đi") cần **chuỗi thời gian** điểm cửa hàng và tỷ
     lệ hoàn. Hiện `lookup_public_store` chỉ chụp một lần lúc xác minh; không có dữ liệu hoàn hàng ngoài tham số ngành
     `tier1.industry_return_rate`. Kế hoạch này thêm snapshot cửa hàng hằng tháng (Agent 4 đọc, chỉ xem) và ghi rõ trên báo
     cáo khi chưa đủ dữ liệu, thay vì bịa xu hướng.
2. **Việc 2 và 4 trùng một phần với cái đã có.** `assess()` đã có tín hiệu `low_balance` (≤ 7 ngày trước kỳ, số dư <
   khoản phải trả) và `_reminders()` đã nhắc ở ngày 7 và 1 kèm câu "Số dư chưa đủ". Giá trị mới của việc 2 là **dự báo**
   (cộng tiền hàng dự kiến về trong 7 ngày) chứ không phải so số dư hiện tại; giá trị mới của việc 4 là **ngay sau khoản
   chi** chứ không đợi vòng 5 phút. Phải có khử trùng lặp: một kỳ trả chỉ nhận mỗi loại cảnh báo một lần.
3. **Việc 3 với mẫu số sai sẽ báo động giả.** Với tôi, tiền hàng về WeBank chỉ 7.437 tệ trong khi doanh thu thuế 166.700
   (độ phủ 4 %). Nếu lấy "tiền trả nợ / tiền về WeBank" thì tỷ lệ là 275 % và tháng nào cũng đỏ. Mẫu số phải là
   `max(tiền về WeBank, doanh thu thuế gần nhất × độ phủ đã biết)` và thông báo phải nói rõ đang tính trên bao nhiêu % doanh
   thu (đây chính là lý do việc 9 phải làm trước việc 3).
4. **Việc 1 không phải viết mới mà là "nói thật".** Backend đã có `seller_reason()` và bảng `_ESCALATE_REASONS`; vấn đề
   là câu `CHAL-01` chung chung ("Một số tín hiệu của kế hoạch và chứng từ cần cán bộ xem thêm") trong khi hệ thống biết
   rất rõ: giá khai 120 cao hơn hóa đơn 62 (94 %), CMB chê điểm 4,6 < 4,7, ICBC chê 26 tháng < 36. Người bán cần đúng
   những câu đó, trừ các cờ AML và xác suất vỡ nợ (giữ kín theo thiết kế).
5. **Thiếu kênh giao hàng.** Trang "Thông báo" hiện chỉ đọc `loan.notices` của khoản vay đang mở; không có thông báo cấp
   hồ sơ (duyệt hạn mức, yêu cầu bổ sung hóa đơn `data_requests` đã tạo mà không ai thấy), không có trạng thái đã đọc,
   không có chỗ cho báo cáo. 9 việc đều "gửi thông báo / gửi báo cáo" nên phải làm kênh này trước (P0).
6. **Thiếu một việc an toàn bắt buộc.** Cảnh báo 2, 3, 4 sẽ dẫn người bán tới nút "Trả tối thiểu" / "Trả hết hôm nay".
   Hiện hai nút này **thực hiện ngay, không hộp xác nhận, không OTP** (tôi mất 60.000 tệ bằng một cú click khi thử). Phải
   thêm bước xác nhận trước khi tăng lưu lượng vào đó (P0).
7. **Việc 8 cần trích luật đúng.** Mốc 100.000 tệ/năm nằm ở Điều 50 「市场主体登记管理条例实施细则」(2022): giao dịch nhỏ
   lẻ "年交易额累计不超过10万元" không phải đăng ký chủ thể thị trường; vượt thì phải đăng ký. Bộ luật thương mại điện tử
   Điều 10 chỉ nói "零星小额交易" không nêu số. Trích đúng điều, có trong kho RAG (`app/core/laws/corpus.json`) để
   Agent 3 kiểm được như các trích dẫn khác.
8. **Xưng hô.** Mọi mẫu câu hiện gọi "chị" cứng (kể cả với tôi, FABLE). Mọi câu mới dùng "bạn"; đưa xưng hô vào một hằng
   `SELLER_ADDRESS` để sửa dần chỗ cũ.

Kết luận: giữ 9 việc, thêm P0, đổi mẫu số việc 3, đổi việc 1 từ "viết lời giải thích" thành "lộ các yếu tố đã có", và
nói thật trên báo cáo quý khi chưa đủ dữ liệu xu hướng.

---

## 2. Nguyên tắc kiến trúc (không đổi so với hệ thống hiện tại)

- Vẫn 5 tác tử. Agent 1, 2 không sửa. Việc mới nằm trong `agent3_control.py`, `agent4b_monitor.py`, module mới
  `agent5_seller_reports.py` (vẫn là Agent 5, chạy trong `autopilot.loop`).
- **Chỉ đọc và gửi thông báo.** Không hàm nào mới gọi `_collect`, `_pay_banks`, `prepay`, `change_receiving_account`.
  Bọc mọi đoạn mới bằng `capabilities.acting("agent4b")` như `tick()` đang làm; thêm vai `"agent5"` (chỉ đọc, không `debit`)
  vào `ROLES` trong `platform/capabilities.py` và bọc module báo cáo bằng `capabilities.acting("agent5")`, để bộ kiểm quyền
  chặn nếu ai đó vô tình gọi hàm chuyển tiền.
- Mọi con số do code tính. LLM (nếu dùng) chỉ **viết lời** cho thông báo/báo cáo, qua bộ lọc số `agent2_advise.blocked()`
  và `guards.forbidden_phrases()` như `agent4_llm.write_notice`. Thiếu LLM thì dùng mẫu. Bộ lọc số phải nhận cả
  định dạng "50,000" và "50.000" (lỗi tôi gặp khi hỏi tiếng Anh: bịa "50,000 CNY" mà lọt).
- Ngưỡng là tham số trong `core/params.py` (đổi qua quy trình đề xuất của Agent 5, không sửa tay).
- Mỗi báo cáo và mỗi cảnh báo mới ghi `events.log(...)` và báo cáo thì `chain.record(session, <seller_user_id>, "seller_report", data)`
  để có hash trên chuỗi như `postaudit_report`.
- Dữ liệu người bán nằm trong `BuLoan.doc` (như `notices`, `reminders`, `account`) và một bảng mới `bu_seller_reports`.
  Không migration: bảng mới tự tạo, cột mới có mặc định.
- Giao diện: thêm trang, không đổi wizard. Mobile 390 px không tràn ngang (kiểm bằng `Frontend/tests/v4-ui-check.mjs`).

---

## 3. P0 · Việc nền (làm trước, 2 ngày)

### 3.1 Trung tâm thông báo cho người bán

**Backend** · file mới `app/api/me_notices.py`, router prefix `/me` (gộp với `my_bank.py` nếu muốn):

- `GET /v4/me/notices` → `{"items": [NOTICE], "unread": n}`. Gộp từ ba nguồn, sắp theo `at` giảm dần, tối đa 100:
  1. `loan.doc.notices` của **mọi** khoản vay của người bán (không chỉ khoản đang mở) → `scope: "loan"`, `loan_id`;
  2. `application.doc.seller_notices` (danh sách mới, xem 3.1.b) → `scope: "application"`, `application_id`;
  3. `bu_seller_reports` (mục 7) → `scope: "report"`, `report_id`, `text` = một dòng tóm tắt.
- `POST /v4/me/notices/read` body `{"ids": [...]}` → đánh dấu đã đọc: ghi `read_at` vào chính phần tử trong doc
  (loan hoặc application) hoặc cột `read_at` của báo cáo. Trả `{"unread": n}`.
- `NOTICE` = `{"id","scope","kind","level":"info|warn|danger","title","text","at","read_at","action":{"view":"loan|report|apply|chat","id":...}|null,"question"?,"answer"?}`.
  `title` là chuỗi ngắn do code đặt theo `kind` (bảng `NOTICE_TITLES` trong module), ví dụ `shortfall_forecast` → "Có thể thiếu tiền kỳ tới".

**3.1.b Thông báo cấp hồ sơ.** Thêm helper `app/agents/notify.py`:

```python
def push_app_notice(doc: dict, kind: str, text: str, level: str = "info", action: dict | None = None) -> dict
```
Ghi vào `doc["seller_notices"]` (giữ 50 phần tử), cùng cấu trúc với `_notice()` của agent4b. Gọi tại:
- `agent3_control._decide()` khi `kind in ("approve","smaller_offer","escalate","reject")` → kind `decision` (nội dung từ việc 1);
- `banks/syndicate.py` khi vòng duyệt xong → kind `limit_approved` ("Ngân hàng đã duyệt hạn mức 100.000 tệ, hiệu lực đến 24/10");
- `agent2_advise` khi tạo `data_requests` → kind `data_request` kèm `action: {"view": "apply"}` (hiện người bán không bao giờ thấy yêu cầu bổ sung hóa đơn);
- `api/applications.py` `/sign` xong → kind `disbursed` (hiện đã có ở loan notices, để nguyên, không nhân đôi).

**Frontend** `Frontend/src/nguoi-ban/workspace-v4.js`:
- `renderNotices()` đọc `/v4/me/notices` thay vì `state.loan.notices`; mỗi mục có `title`, `text`, nút hành động theo
  `action.view`; mục chưa đọc có chấm; mở trang thì gọi `/read` cho các id đang hiển thị.
- `noticeCount()` dùng `unread` từ API (hiện chỉ đếm câu hỏi vàng). Badge trên tile "Thông báo" và mục sidebar.
- Polling: dùng chính vòng 60 giây đang có (`loanSignature`), thêm `unread` vào chữ ký.

### 3.2 Hộp xác nhận cho hành động tiền

- `loan-minimum`, `loan-prepay` (dòng ~762-763 và ~822 trong `workspace-v4.js`): mở `<dialog>` xác nhận hiển thị số tiền,
  phần lãi/gốc (`minimum.quote`, `prepay_quote` đã có trong LOAN), hộp tích "Tôi hiểu tiền sẽ trích ngay", chọn ký
  bằng khuôn mặt (nếu tài khoản có) hoặc OTP, rồi mới gọi API.
- Backend: `POST /v4/loans/{id}/prepay` và `/minimum` nhận thêm `confirm: true` (bắt buộc, thiếu → 400 `CONFIRM_REQUIRED`)
  và tùy chọn `face_verify_id`. Sửa `tests/test_money_api.py` cho khớp.

### 3.3 Phân nhóm chi phí (dùng lại cho việc 3, 5, 6, 7)

File mới `app/core/cashflow.py`:

```python
EXPENSE_GROUPS = ("goods", "platform", "marketing", "logistics", "staff", "tax")   # thứ tự cố định
GROUP_LABELS = {"goods": "Hàng hóa và nguyên liệu", "platform": "Chi phí trên sàn", "marketing": "Tiếp thị ngoài sàn",
                "logistics": "Vận chuyển và kho bãi", "staff": "Nhân sự và vận hành", "tax": "Thuế và phí kinh doanh"}
def classify(transfer: dict) -> str | None      # None = không phải chi phí kinh doanh (personal, securities, real_estate)
def month_summary(loan_docs: list[dict], repayments: list, month: str) -> dict
```
- `classify`: ưu tiên `transfer["group"]` nếu đã có; rồi `kind` (`supplier` → goods); rồi từ khóa trên `memo`/`label`/`payee.name`
  (bảng `_KEYWORDS` tiếng Việt + Trung + Anh: "lương/工资/salary" → staff; "quảng cáo/推广/ads/巨量" → marketing;
  "vận chuyển/快递/物流/kho" → logistics; "thuế/税/phí sàn/佣金" → tax hoặc platform; "nhập hàng/xưởng/进货/供应商" → goods);
  không khớp → `"goods"` nếu `payee.kind == "supplier"` ngược lại `"other"` (nhóm thứ 7 chỉ dùng nội bộ, hiển thị "Chưa phân loại").
- **Phí sàn** không có giao dịch riêng vì tiền về đã trừ phí (`settlement.day_amount` × 0,95). Tính
  `platform_fee = inflow_net × fee/(1−fee)` với `fee` từ `tax.platform_fee_schedule[platform]` của hồ sơ, mặc định 0,05.
  Ghi rõ "ước tính theo biểu phí sàn" trên báo cáo.
- Mở rộng `TRANSFER_KINDS` thêm `marketing`, `logistics`, `staff`, `tax`, `platform` (giữ 5 loại cũ để test cũ không vỡ);
  `simulate_transfer` lưu thêm `group = classify(item)`.
- Webhook tiền ra: `POST /v4/webank/outflows` trong `api/webank.py`, body `{"account_number","amount","transfer_id","payee":{"kind","name"},"memo"}`,
  xác thực HMAC như inflows, gọi `agent4.record_outflow(session, loan, ...)` (hàm mới, bọc `simulate_transfer` với `kind="other"`
  + `memo` + `payee`, idempotent theo `transfer_id` như `payout_ids`). Đây là chỗ sau này WeBank thật nối vào.
- Demo: `autopilot/settlement.py` thêm `spend()` chạy cùng nhịp `settle()`: mỗi ngày nạp 0–2 khoản chi lấy từ
  `bank_statement.outflows` của hồ sơ mẫu (xoay vòng theo chỉ số), giữ tổng chi ≤ 70 % tiền về trong tháng. Bật cùng
  cờ `PLATFORM_PAYOUT_FEED`.

---

## 4. Việc 1 · Agent 3 giải thích quyết định cho người bán (1 ngày)

**Vị trí:** `app/agents/agent3_control.py`, hàm mới `explain_for_seller(doc) -> dict` gọi từ `_decide()` ngay sau khi
`doc["decision"]` được ghi (mọi `kind`, kể cả approve để nói "vì sao 100.000 chứ không phải 360.000").

**Đầu ra** (lưu `doc["decision"]["explanation"]`, người bán thấy qua `views.py`; cán bộ thấy nguyên bản):

```json
{"headline": "Hồ sơ cần cán bộ xem thêm",
 "because": [{"text": "Giá nhập bạn khai (120 tệ) cao hơn hóa đơn mua vào 3 tháng gần nhất (62 tệ) 94 %.", "ref": "sheet.B3.unit_price_used"},
             {"text": "China Merchants Bank chỉ nhận cửa hàng từ 4,7 điểm; cửa hàng bạn 4,6.", "ref": "syndicate.rounds[0].CMB"},
             {"text": "ICBC cần cửa hàng hoạt động từ 36 tháng; cửa hàng bạn 26 tháng.", "ref": "syndicate.rounds[0].ICBC"}],
 "improve": [{"text": "Tải hóa đơn mua vào hoặc báo giá của xưởng cho lô hàng này.", "action": {"view": "apply", "data_type": "invoice"}},
             {"text": "Để tiền hàng về tài khoản WeBank đều 3 tháng: hạn mức lần sau tăng từ 50 % lên 75 % mức tính được.", "action": null}],
 "hidden": false, "source": "template|llm"}
```

**Nguồn từng câu (chỉ dùng cái đã có trong doc, không tính thêm):**
- `offer.reason_codes[]` (PRICE_FROM_INVOICE, INVENTORY_AND_OWN_CAPITAL, SEED_LOAN…) → câu "vì sao số này" cho mọi quyết định.
- `control.phase1.concerns[]` với `rule` có trong bảng trắng `SELLER_SAFE_RULES = {"RISK-04","RISK-05","LAW-IP-02","POL-06","EVENT-01",...}`:
  dùng `note` nhưng **lọc số qua `blocked()`** với tập số cho phép từ phiếu; `CHAL-01` → chỉ nói
  "Mô hình kiểm soát độc lập muốn cán bộ xem lại kế hoạch" (không PD, không đặc trưng).
- `syndicate.rounds[-1].responses[]` có `decision in ("decline","timeout")` → câu theo ngân hàng (có sẵn `reason`).
- `verification.flags[]` trạng thái `explained_unverified`/`hard` (bỏ nhóm AML, giống `views._seller_verification`).
- `improve` từ bảng `IMPROVE_BY_CODE` (code → câu + action), ví dụ RISK-04 → tải hóa đơn; SEED_LOAN → tiền về WeBank
  đều (`seed.min_webank_months`, `seed.min_inflow_share`); bank decline theo tiêu chí điểm/tuổi → "điều kiện của X; không
  cần làm gì, các ngân hàng khác vẫn cấp" hoặc "nộp lại sau tháng …" (tính từ `stores[0].registry.registered` + 36 tháng).
- `hidden_reason(doc)` đúng (AML) → `headline` chung, `because` rỗng, `improve` chỉ "Cán bộ sẽ liên hệ".

**LLM tùy chọn:** sau khi code dựng xong danh sách, mô hình chỉ được *viết lại cho trôi* với đúng các con số trong danh
sách (lọc `blocked()`), tối đa 1 lần thử, timeout ngắn; thất bại → giữ mẫu. Không cho mô hình thêm lý do.

**Gửi:** `notify.push_app_notice(doc, "decision", explanation["headline"] + " · " + because[0].text, ...)`; đồng thời
`agent2_advise.append_system_message(doc, text)` (hàm mới, ghi một `MESSAGE` `from: "system"` vào luồng chat) để khi người bán hỏi "vì sao bị chuyển cán bộ" thì chat có ngữ cảnh
thật thay vì trả lời mẫu (sửa luôn intent: câu có "vì sao/tại sao" **không** được coi là yêu cầu gặp người).

**UI:** màn hình bước 7 "Chờ chút nhé" và màn `rejected`/`out_of_scope` (workspace-v4.js ~dòng 194) hiện `because` dưới
dạng danh sách, `improve` dưới dạng nút hành động. Tab Agent 3 của cán bộ hiện thêm khối "Người bán đã được nói gì".

**Tham số:** `explain.max_because: 4`, `explain.max_improve: 3`.

**Test:** `tests/test_seller_services.py::test_explanation_lists_price_and_bank_reasons` (kịch bản `lan` với giá 120 →
có câu giá 120/62, có câu CMB 4,7, có câu ICBC 36 tháng, không có chuỗi "65" hay "PD"); `::test_explanation_hidden_for_aml`
(kịch bản `company` → `because == []`).

---

## 5. Việc 2, 3, 4 · Agent 4b (1,5 ngày)

Tất cả trong `app/agents/agent4b_monitor.py`, gọi từ `_monitor_one()` sau `assess()`; **không** đụng `service()`.
Khử trùng lặp bằng `doc["sent_alerts"]`: tập khóa `"{kind}:{k}"` (k = kỳ trả) hoặc `"{kind}:{YYYY-MM}"`.

### 5.1 Việc 2 · `_forecast_shortfall(doc, params, as_of) -> dict | None`

- Chỉ chạy khi `days_left ∈ params["repay"]["forecast_days"]` (mặc định `[7, 3]`) với `row = next_row(doc)`.
- `daily_in` = trung bình tiền về/ngày trong `params["repay"]["forecast_lookback_days"]` (30) từ `account.inflows`
  (nếu < 7 ngày dữ liệu → dùng `doc["forecast_monthly"] / 30 × độ phủ`, xem 7.4).
- `expected_out` = tổng chi trung bình/ngày cùng kỳ (từ `account.transfers`, chỉ nhóm chi phí kinh doanh).
- `projected = balance + (daily_in − expected_out) × days_left`.
- Nếu `projected < row["payment_est"]`: thông báo `kind="shortfall_forecast"`, `level="warn"`:
  "Còn 7 ngày đến kỳ 1 (15/11): phải trả 20.477 tệ. Số dư 7.437 tệ; với nhịp tiền về 30 ngày qua, đến ngày trả dự kiến
  có khoảng 14.900 tệ, thiếu khoảng 5.600 tệ. Bạn có thể nộp thêm vào tài khoản WeBank hoặc chọn trả tối thiểu
  6.477 tệ cho kỳ này." Kèm `action: {"view": "loan"}` và, nếu `minimum_allowed()`, nút "Xem trả tối thiểu" (mở hộp xác nhận ở 3.2, không tự chọn).
- Gộp với `_reminders()` hiện có: khi forecast đã gửi ở ngày 7 thì reminder ngày 7 không gửi thêm câu "Số dư chưa đủ".

### 5.2 Việc 3 · `_debt_service_check(doc, app_doc, params, as_of)`

- Chạy ở vòng đầu tiên của tháng mới (`as_of.day == 1` hoặc lần đầu `sent_alerts` chưa có khóa `dsr:{tháng trước}`), tính cho **tháng trước**.
- `payments` = tổng `BuRepayment.swept` trong tháng + phần kỳ đã đến hạn chưa trả.
- `revenue_base = max(webank_in_month, tax_month × coverage)` trong đó `tax_month` = tháng tương ứng trong
  `internal.data.revenue.monthly_12m` (hoặc `forecast_monthly`), `coverage` theo 7.4.
- `ratio = payments / revenue_base`; nếu `ratio > params["early_warning"]["dsr_max"]` (0,20): thông báo `kind="dsr_high"`,
  `level="warn"`: "Tháng 10: tiền trả nợ 20.477 tệ bằng 23 % doanh thu ước tính (88.000 tệ, tính trên 45 % doanh thu đi qua
  WeBank). Trên 20 % là mức BuoyUp coi là nặng. Để tiền hàng về WeBank đầy đủ sẽ cho con số chính xác hơn." Thêm
  tín hiệu `dsr_high` trọng số 0,0 vào `result["signals"]` để cán bộ thấy trong cảnh báo (không đổi mức màu).

### 5.3 Việc 4 · hook trong `simulate_transfer` / `record_outflow`

- Sau khi trừ số dư: nếu có `row = next_row(doc)` và `balance_after < row["payment_est"]` và
  `amount ≥ params["repay"]["large_spend_share"] (0,30) × row["payment_est"]` và chưa có khóa `spend_below_due:{k}`:
  thông báo `kind="spend_below_due"`, `level="warn"`, gửi **ngay trong request** (không đợi vòng 5 phút):
  "Bạn vừa chi 15.000 tệ (Trả nhà cung cấp). Số dư còn 4.300 tệ, thấp hơn 20.477 tệ phải trả ngày 15/11. Nhớ để tiền hàng về
  WeBank trước ngày đó." Không hỏi nguyên nhân (đây không phải cảnh báo vàng).
- Gọi `autopilot.assess_loan(loan.id, "transfer")` sau commit (như `loans.post_inflow`) để `low_balance` cập nhật.

**Tham số mới trong `core/params.py` (kèm nhãn nguồn như các tham số khác):**
```python
"repay": {..., "forecast_days": [7, 3], "forecast_lookback_days": 30, "large_spend_share": 0.30},
"early_warning": {..., "dsr_max": 0.20},
```

**Test:** `test_forecast_shortfall_fires_7_days_before` (loan 60.000/3 tháng; `simulate-advance` tới `due−7`; không tiền về →
có notice `shortfall_forecast`, một lần duy nhất khi advance tiếp tới `due−6`); `test_dsr_notice_uses_tax_base`
(tiền về 7.437, thuế 166.700 → không cảnh báo; thuế 60.000 → cảnh báo với "20 %" trong text); `test_spend_below_due_immediate`
(transfer 56.000 → notice ngay trong response GET loan). Tất cả không gọi LLM (`LLM_ENABLED=false` sẵn trong conftest).

---

## 6. Việc 5, 6, 7, 8, 9 · Agent 5 báo cáo cho người bán (4,75 ngày)

### 6.1 Lưu trữ

`app/platform/tables.py`:
```python
class BuSellerReport(Base):
    __tablename__ = "bu_seller_reports"
    id: str (pk, "srp_" + hex)          seller_user_id: str (index)
    kind: str  # month | quarter | year | closing | registration
    period: str  # "2026-10" | "2026-Q4" | "2026" | loan_id
    data: JSON   at: datetime   read_at: datetime | None   hash: str   chain_tx: str | None
```
Unique theo `(seller_user_id, kind, period)`: chạy lại cùng kỳ thì **ghi đè data** (báo cáo tháng sinh ngày 1 có thể cập
nhật khi webhook về muộn), không tạo bản mới.

### 6.2 Module `app/agents/agent5_seller_reports.py`

```python
def coverage(session, user_id, month) -> dict        # việc 9: {"share": 0.45, "webank_in": ..., "tax_revenue": ..., "basis": "tax|forecast|none"}
def build_month(session, user_id, month) -> dict     # việc 5
def build_quarter(session, user_id, quarter) -> dict # việc 6
def build_year(session, user_id, year, closing_loan_id=None) -> dict   # việc 7
def registration_check(session, user_id, as_of) -> dict | None         # việc 8
def run_due(session, as_of) -> list[BuSellerReport]  # gọi từ autopilot: sinh mọi báo cáo đến hạn cho mọi người bán có khoản vay
def report_view(r: BuSellerReport) -> dict           # cho API
```

**Dữ liệu vào (chỉ cái đã có):** `BuLoan.doc.account.inflows/transfers`, `BuRepayment`, `schedule`,
`BuApplication.doc.internal.data.revenue.monthly_12m`, `goods_mix`, `stores[0].rating`, `plan`, `borrower_type`,
`derived.history.webank_share_of_tax`; snapshot cửa hàng tháng (mới, 6.3).

**Nội dung báo cáo tháng (`data` của kind `month`):**
```json
{"period": "2026-10", "currency": "CNY", "coverage": {...},
 "sales": {"webank_in": 67437, "tax_revenue": 166700, "estimate": 166700, "basis": "tax", "vs_prev": -0.12},
 "expenses": {"groups": [{"key": "goods", "label": "Hàng hóa và nguyên liệu", "amount": 42000, "share": 0.62}, ...], "unclassified": 0, "platform_fee_estimated": true},
 "cash": {"opening": 0, "in": 67437, "loan_in": 60000, "repay": 60000, "out": 15000, "closing": 7437, "lowest": 4300},
 "loan": {"outstanding": 0, "paid_this_month": 60000, "next_due": null, "status": "closed"},
 "flags": ["Tiền trả nợ bằng 36 % doanh thu ước tính"],
 "notes": ["Phí sàn ước tính theo biểu phí 5 % của Douyin.", "Báo cáo tính được 45 % doanh thu của cửa hàng; phần còn lại về tài khoản khác."],
 "summary": "…3 câu…", "summary_source": "template|llm", "simulated": true}
```
`summary` mẫu: "Tháng 10 bạn bán được khoảng 166.700 tệ (−12 % so tháng 9). Chi lớn nhất là hàng hóa 42.000 tệ. Cuối tháng
tài khoản WeBank còn 7.437 tệ, thấp nhất 4.300 tệ hôm 20/10." LLM viết lại tùy chọn, lọc số.

**Báo cáo quý** thêm: `trend.revenue` (3 tháng, hướng ▲▼ và %), `runway_months = closing / avg_monthly_out` (ghi "∞" nếu chi = 0),
`returns` và `rating` **chỉ khi có ≥ 2 snapshot** (6.3), nếu không ghi `"unavailable": "Chưa đủ dữ liệu đánh giá và hoàn hàng từ sàn"`.
Không bịa xu hướng.

**Báo cáo năm / tất toán** thêm: tổng 12 tháng; `before_after`: 3 tháng trước giải ngân vs 3 tháng sau (doanh thu, tiền về
WeBank); `loan_summary`: số vay, tổng lãi thật, số ngày, trễ hạn; `next_time`: gợi ý vay lần sau = `algorithm` tính lại với
`seed.ratio` bậc tiếp theo nếu đủ `min_webank_months` ("Nếu 3 tháng tới tiền hàng về WeBank ≥ 80 %, hạn mức lần sau có thể tới
150.000 tệ") — lấy từ `offer.blocks.B8` của hồ sơ gần nhất, không tính mới. Kích hoạt khi `_maybe_close()` đóng khoản vay
(gọi `autopilot.mark_reports_due(user_id, "closing")`) hoặc ngày 1/1.

**Việc 8 · `registration_check`:** chỉ `borrower_type == "individual"`. `ytd = Σ monthly_12m trong năm hiện tại`
(fallback: tiền về WeBank / coverage). Nếu `ytd ≥ params["legal"]["individual_registration_threshold"] × params["legal"]["individual_registration_warn_share"]`
(100.000 × 0,8) và chưa gửi trong năm → `BuSellerReport(kind="registration")` + thông báo `level="warn"`:
"Doanh thu năm nay của bạn khoảng 83.000 tệ. Theo Điều 50 Thực hiện chi tiết Điều lệ quản lý đăng ký chủ thể thị trường (2022),
bán hàng qua mạng với doanh thu năm trên 100.000 tệ phải đăng ký kinh doanh. Đăng ký xong, hạn mức BuoyUp cho hộ kinh doanh tới
200.000 tệ thay vì 50.000." Trích dẫn lấy từ `core/legal.py` (thêm quy tắc `LAW-REG-01`, `citations` trỏ `corpus.json`,
kiểm nguyên văn bằng `legal.verify_citation(article_id, quote, review_date)` như quy tắc khác). Thêm điều luật vào corpus nếu chưa có (chạy
`scripts/extract_laws.py` lại, hash corpus lên chuỗi).

**Việc 9 · `coverage(month)`:** `share = min(1, webank_in_month / tax_revenue_month)`; không có thuế tháng đó → dùng
`forecast_monthly` với `basis: "forecast"`; không có gì → `basis: "none"`, share `null`. Mọi báo cáo và thông báo DSR
(5.2) in câu `notes[0]`. Dashboard: thẻ "Tiền hàng về tháng này" thêm dòng nhỏ "≈ 45 % doanh thu của bạn".

### 6.3 Snapshot cửa hàng hằng tháng (dữ liệu cho báo cáo quý)

Trong `_monitor_one()`: ngày đầu tháng, với mỗi khoản vay mở, gọi `sources.lookup_public_store(data, url)` (dữ liệu mẫu,
đã có) và ghi `doc["store_snapshots"].append({"month", "rating", "followers", "returns_rate": data.get(...)})`
(giữ 24). Agent 4 **chỉ đọc**. Hồ sơ mẫu chưa có `returns_rate` → `null` cho tới khi nguồn thật có; báo cáo nói "chưa có".

### 6.4 Lịch chạy (`app/autopilot/loop.py`)

- Thêm `_state["reports"]` và `run_reports(reason)`: gọi `agent5_seller_reports.run_due(session, today())` trong một
  transaction ngắn mỗi người bán. Gọi trong `loop()` mỗi `BUOYUP_REPORTS_INTERVAL_SECONDS` (mặc định 3600) và ngay sau
  `mark_reports_due()`. Idempotent nhờ unique `(seller, kind, period)`.
- `simulate-advance` (demo) gọi `run_due` với ngày giả định sau mỗi ngày trôi, để demo thấy báo cáo tháng/quý ngay.
- `GET /v4/autopilot/status` thêm khối `reports`.

### 6.5 API & UI

- `GET /v4/me/reports` → danh sách rút gọn; `GET /v4/me/reports/{id}` → `report_view`; cán bộ/admin: `GET /v4/officer/sellers/{user_id}/reports`.
- Trang mới "Báo cáo" trong sidebar và tile dashboard (icon biểu đồ). Mỗi báo cáo: tiêu đề kỳ, dòng độ phủ (việc 9), 3 thẻ số
  (bán được / chi / còn lại), biểu đồ `BU.charts.hbars` cho 6 nhóm chi, `BU.charts.grouped` tiền vào–trả nợ–chi theo tháng
  (quý/năm), đoạn `summary`, danh sách `notes`. Nút "Tải PDF" **không làm** ở vòng này (in trình duyệt `window.print()` với CSS
  `@media print` là đủ).
- Thông báo (P0) sinh một mục `scope: "report"` khi báo cáo mới tạo, `action: {"view": "report", "id": ...}`.

### 6.6 Test

`tests/test_seller_reports.py`:
- `test_month_report_groups_expenses_and_coverage`: loan 60.000; `simulate-inflow` 30.000 (`payout_id` khác nhau);
  `simulate-transfer` 12.000 `supplier`, 3.000 `kind="staff"`; `simulate-advance` sang ngày 1 tháng sau → có báo cáo
  `month` với `goods == 12000`, `staff == 3000`, `coverage.basis == "tax"`, `notes` chứa "%".
- `test_quarter_report_says_unavailable_without_snapshots`.
- `test_year_report_on_closing`: `prepay` → báo cáo `closing` có `loan_summary.total_interest == 0` và `before_after`.
- `test_registration_notice_for_individual_only`: kịch bản `individual` (có sẵn) với `monthly_12m` ép tổng 85.000 → có
  notice `registration`; kịch bản `lan` (hộ kinh doanh) → không.
- `test_reports_idempotent_and_hashed`: chạy `run_due` hai lần → 1 bản, `hash` không đổi, có `chain_tx` (chuỗi `local`).
- `test_reports_never_move_money`: bọc `capabilities` ở chế độ nghiêm; `run_due` không gọi `_collect/_pay_banks` (dùng
  `monkeypatch` gắn cờ vào hai hàm đó).

---

## 7. Thứ tự làm và điểm dừng kiểm tra

| Pha | Việc | Điểm dừng (phải xanh trước khi sang pha sau) |
|---|---|---|
| A (ngày 1–2) | P0: notices API + trang Thông báo + hộp xác nhận + `cashflow.classify` + webhook outflows | 177 test cũ + `test_money_api` sửa đều pass; `v4-ui-check.mjs` thêm nhóm "notices"; bấm "Trả hết" phải qua hộp xác nhận |
| B (ngày 3) | Việc 1 | Kịch bản `lan` giá 120 → thông báo `decision` có 3 câu lý do, không lộ PD; chat trả lời "vì sao" bằng đúng các câu đó |
| C (ngày 4–5) | Việc 2, 3, 4 + snapshot cửa hàng | 3 test mục 5 pass; `simulate-advance` 30 ngày không sinh thông báo trùng |
| D (ngày 6–9) | Việc 5, 9 → 6 → 7 → 8 + trang Báo cáo | 6 test mục 6.6 pass; báo cáo có `chain_tx`; mobile 390 px không tràn |
| E (ngày 10–11) | Nhật ký demo, tài liệu, rà soát | `scripts/demo_seller_services.py` chạy sạch; cập nhật `API_CONTRACT_V4.md`, `HANDOVER.md`; `./run-local.sh test` xanh |

Mỗi pha một commit riêng, message tiếng Việt theo mẫu repo, kèm dòng `Co-Authored-By`.

---

## 8. Nhật ký demo nộp kèm bài thi (`scripts/demo_seller_services.py`)

Chạy trên DB tạm (`DATABASE_URL=sqlite:///...`, `LLM_ENABLED=false`, chuỗi `local`), in JSON từng bước ra
`TestBench/evidence/seller_services-<ngày>.json` và một bản Markdown đọc được:

1. Đăng ký người bán, hồ sơ `lan` với giá khai 120 → `decision.explanation` (việc 1) in nguyên văn.
2. Cán bộ duyệt; ký; giải ngân 60.000/3 tháng.
3. 20 ngày tiền về mỗi ngày (feed), 4 khoản chi 4 nhóm (webhook outflows có HMAC) → thông báo `spend_below_due` (việc 4).
4. `simulate-advance` tới `due−7` → `shortfall_forecast` (việc 2); tới ngày 1 tháng sau → báo cáo tháng (việc 5, 9) và `dsr_high` nếu có (việc 3).
5. Advance 3 tháng → báo cáo quý (việc 6, có dòng "chưa đủ dữ liệu đánh giá").
6. `prepay` qua `confirm: true` → báo cáo tất toán (việc 7).
7. Người bán cá nhân với doanh thu 85.000 → thông báo đăng ký kinh doanh (việc 8) kèm trích dẫn đã kiểm.
8. Danh sách `events` theo `kind` và `chain_tx` của 3 báo cáo.

Kiểm tra cuối: không có bản ghi `BuRepayment` nào được tạo bởi actor `agent5`; `capabilities` không ghi vi phạm.

---

## 9. Quyết định mở (chủ dự án chốt, mặc định đã chọn trong ngoặc)

1. Mẫu số DSR: `max(WeBank, thuế × độ phủ)` (**mặc định**) hay chỉ WeBank kèm chú thích độ phủ.
2. Ngày dự báo thiếu tiền: `[7, 3]` (**mặc định**) hay chỉ `[7]` như đề xuất.
3. Hộp xác nhận trả tiền: bắt khuôn mặt/OTP (**mặc định: OTP mô phỏng như ký ủy quyền**) hay chỉ hộp tích.
4. Báo cáo PDF: chưa làm (**mặc định**) hay thêm `weasyprint` (ảnh hưởng image Docker ~60 MB).
5. Xưng hô: đổi toàn bộ mẫu câu cũ sang "bạn" ngay trong pha A (**mặc định**) hay chỉ câu mới.
6. Snapshot cửa hàng hằng tháng có cần ủy quyền riêng không (**mặc định: thuộc phạm vi `data_processing` đã ký**, ghi rõ trong văn bản `xu-ly-du-lieu.html`).

---

## 10. Những gì KHÔNG làm trong kế hoạch này

- Không sửa Agent 1, Agent 2 (ngoài hai dòng: thêm system message ngữ cảnh ở việc 1 và sửa intent "vì sao" ≠ "gặp người").
- Không đổi công thức B1–B12, không đổi vòng duyệt ngân hàng, không đổi `service()`/trích nợ.
- Không nối WeBank thật; chỉ chuẩn bị webhook tiền ra cùng chuẩn HMAC với tiền vào.
- Không làm gợi ý vay bằng mô hình; "lần sau nên vay bao nhiêu" lấy từ khối B8 đã tính.
