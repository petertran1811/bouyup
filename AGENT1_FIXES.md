# Agent 1 · Nhật ký sửa lỗi (14/10/2026)

Đối chiếu `BackEnd/src/app/agents/agent1_verify.py` và các nguồn dữ liệu với
`docs/agents/agent1_xac_minh.md`, rồi sửa những chỗ code làm sai so với đặc tả.

- **Bản sao lưu trước khi sửa:** `../fintech_new_backup_20261014_154435/` (thư mục này không phải git repo). *(Đã xóa ngày 14/10/2026 để repo nhẹ hơn; các lệnh khôi phục từ bản sao này không còn dùng được.)*
- **Kết quả kiểm thử sau khi sửa:**
  - backend `pytest`: **187 passed** (trước khi sửa: 177; thêm 10 test mới);
  - `Frontend/tests/v4-api-check.py`: **PASS 9 kịch bản demo**;
  - `Frontend/tests/v4-ui-check.mjs`: **32 nhóm passed**.
- **Con số demo không đổi:** chị Lan vẫn được **139.900**, vì trong luồng demo chị khai thêm tài khoản CMB ••1203 khi được hỏi.
- **Môi trường:** đã tạo `BackEnd/.venv` (Python 3.12, qua `uv`) để chạy test. `.gitignore` đã bỏ qua thư mục này; nó cũng chính là đường dẫn `run-local.sh` dùng.

## File đã sửa

| File | Nội dung |
|---|---|
| `BackEnd/src/app/data_sources/profiles.py` | Tính dòng tiền theo tài khoản đã khai |
| `BackEnd/src/app/data_sources/sources.py` | Đọc dòng tiền theo tài khoản; khớp tài khoản khai thêm |
| `BackEnd/src/app/agents/agent1_verify.py` | Cờ cửa hàng chưa khai, nguồn lỗi, biên bản, đồng hồ 3 ngày |
| `BackEnd/src/tests/test_profiles.py` | Cập nhật theo ngữ nghĩa mới, thêm 2 test |
| `BackEnd/src/tests/test_pipeline_algorithm.py` | Fixture dùng số liệu sau khi khai CMB |
| `BackEnd/src/tests/test_sources_fate.py` | Thêm 8 test |

---

## 1. Dòng tiền cộng cả tài khoản chưa khai *(nghiêm trọng: làm tăng hạn mức)*

**Đặc tả (§3, §6.2):** tuổi cửa hàng, doanh số và mọi đại lượng dòng tiền tính trên tiền về **tài khoản đã khai**.

**Lỗi:**
- `profiles.derive` có dựng tập `declared` nhưng `by_month` vẫn cộng mọi khoản tiền về.
- Vì vậy `monthly_avg_12m`, `last_campaign`, `two_peak_avg`, `inflow_20d`, `growth_3m`… gồm cả tài khoản CMB ••1203 mà người bán không khai và không ủy quyền.
- Các số này là đầu vào của B2, B4, B8 và tỷ lệ nợ/dòng tiền.
- `analyze_platform_inflows` nhận danh sách tài khoản trong ủy quyền nhưng bỏ qua.

**Mức sai lệch với hồ sơ chị Lan:**

| Đại lượng | Chỉ tài khoản đã khai | Cũ (mọi tài khoản) |
|---|---|---|
| Bình quân tháng | 145.029 | 166.700 |
| Chiến dịch năm trước | 237.979 | 300.000 |
| Trung bình 2 mùa cao điểm | 285.021 | 330.000 |
| Tiền về 20 ngày | 94.669 | 111.100 |
| Nợ/dòng tiền | 0,17 | 0,15 |

**Sửa:**
- `profiles.py`:
  - Tách hàm `_volume()`. `derive()` tính các đại lượng chỉ trên tài khoản `declared`.
  - Thêm `hidden_accounts` (ngân hàng, 4 số cuối, tỷ trọng trên doanh thu thuế) và `with_hidden` (cùng các đại lượng khi tính cả tài khoản ẩn).
  - Lưu `credit.monthly_installments` để tính lại tỷ lệ nợ/dòng tiền.
- `sources.py`:
  - Thêm `matched_hidden_accounts()` và `include_hidden_accounts()`.
  - `analyze_platform_inflows()` giờ đọc theo danh sách tài khoản. Khi **mọi** tài khoản ẩn đã được khai, các đại lượng chuyển sang số liệu gồm các tài khoản đó, và `debt_to_inflow` được tính lại. Khi mới khai một phần, số liệu vẫn giữ trên các tài khoản đã khai (hướng thận trọng); chỉ tỷ lệ phủ doanh thu thuế tăng lên.
  - Kịch bản biến thể (`_variant`) ghi đè đại lượng dòng tiền thì ghi đè cả bản `with_hidden`.
- `agent1_verify.py`: sau khi người bán khai thêm tài khoản, `verification.derived` cập nhật lại các đại lượng.

**Hệ quả:**
- Khai CMB ngay trong màn hình ủy quyền thì không bật `RISK_INFLOW_GAP`, và số liệu tính trên cả hai tài khoản.
- Trả lời "Tiền mặt" hoặc "Khác" thì số liệu giữ trên tài khoản đã khai, nên hạn mức thấp hơn.

**Test:**
- `test_lan_figures_come_from_raw_rows` (cập nhật)
- `test_unrelated_account_does_not_count`
- `test_both_accounts_declared_upfront_uses_both`
- Fixture `_facts` trong `test_pipeline_algorithm.py` giờ mô phỏng hồ sơ sau khi đã khai CMB, khớp với `penalties=1`.

## 2. `RISK_UNDECLARED_STORE` đóng với link bất kỳ *(gian lận lọt qua)*

**Đặc tả (§6.6):** cờ bật khi có tiền từ sàn chưa khai; đóng khi người bán khai thêm link cửa hàng *trên sàn đó*.

**Lỗi:**
- Dán link của sàn được hỗ trợ bất kỳ là cờ chuyển `resolved_by_check`.
- Cửa hàng mới chép nguyên tên chủ thể và số ĐKKD của cửa hàng đầu tiên.

**Sửa** (`_apply_flag_table`, `_answer_undeclared`):
- Cờ ghi lại danh sách `platforms` đang chưa khai.
- Link phải thuộc một trong các sàn đó. Sai sàn trả lỗi 400 kèm `details.platforms`.
- Link trùng cửa hàng đã khai trả lỗi 400.
- Chủ thể và số ĐKKD đọc từ `lookup_public_store` phải khớp người vay. Không khớp thì cờ vẫn `open`, kèm ghi chú.
- Còn sàn chưa khai khác thì cờ vẫn `open`.

**Test:**
- `test_undeclared_store_needs_a_link_on_that_platform`
- `test_undeclared_store_of_another_entity_does_not_close`

## 3. `RISK_INFLOW_GAP` đóng khi khai một tài khoản bất kỳ

**Đặc tả (§6.6):** đóng khi `analyze_platform_inflows` **trên tài khoản mới** nâng tỷ lệ lên ≥ 95%.

**Lỗi:** khai một tài khoản bất kỳ (ví dụ BOC ••0000) là cộng nguyên `hidden_account_share`, nên cờ luôn đóng.

**Sửa:**
- Chỉ cộng tỷ trọng của tài khoản trùng một tài khoản có thật trong sao kê. So tên ngân hàng không phân biệt hoa thường và 4 số cuối.
- Khai lại lần nữa không cộng thêm.
- Kết quả công cụ ghi rõ `matched_accounts` và `added_share`.

**Test:** `test_unrelated_account_does_not_count`.

## 4. Nguồn thuế hoặc tín dụng lỗi không được bắt *(trái nguyên tắc 5: lỗi thì dừng, chuyển người)*

**Lỗi:** `pull_tax_data` hoặc `get_credit_report` ném lỗi thì exception văng thẳng ra API. Hồ sơ không có trạng thái rõ ràng.

**Sửa:**
- Bọc hai lời gọi bằng `guarded()`. Lỗi `SourceUnavailable` được ghi thành kết quả công cụ có `error`.
- Hàm mới `_source_gap()`:
  - bật cờ `DATA_SOURCE_GAP` (`open`, kèm `sources`);
  - đánh dấu bước 6 `fail`;
  - kết luận `ESCALATED` (có hash lên chuỗi) và đặt `escalation.why = DATA_SOURCE_GAP`.
- Không tính số nào khi thiếu dữ liệu.
- **Quy ước cho nguồn thật:** adapter phải ném `sources.SourceUnavailable` khi đối tác không trả lời, giống `HttpFateSource`.

**Test:** `test_tax_source_down_stops_and_escalates`.

## 5. Thiếu hóa đơn mua vào làm Agent 1 crash, và `DATA_SOURCE_GAP` xử lý lệch với `DATA_PARTNER_MISSING`

**Lỗi 5a (phát hiện khi viết test):**
- Hồ sơ tầng 2 không có hóa đơn mua vào cho mặt hàng (`invoice_unit_price_3m = None`) làm câu tóm tắt bước 6 gọi `_fmt(None)`, gây `TypeError` và lỗi 500.
- Hệ quả: nhánh dự phòng "giá khai × (1 − 0,15)" trong B3 (đặc tả §10) chưa bao giờ chạy được.

**Lỗi 5b:**
- Đặc tả gộp `DATA_SOURCE_GAP` và `DATA_PARTNER_MISSING` chung một dòng: "không hỏi; không đóng; cổng không duyệt tự động".
- Code lại đặt `DATA_SOURCE_GAP` là `open`, nên hồ sơ bị ESCALATED ngay. Trong khi đó `DATA_PARTNER_MISSING` là `explained_unverified`, nên hồ sơ vẫn được đề xuất.

**Sửa:**
- Câu tóm tắt bước 6 ghi "Chưa có hóa đơn mua vào cho mặt hàng".
- Trường hợp thiếu hóa đơn đặt `DATA_SOURCE_GAP` là `explained_unverified`, giống `DATA_PARTNER_MISSING`:
  - vẫn có phiếu đề xuất, B3 dùng giá khai trừ hệ số;
  - quy tắc RISK-02 của Agent 3 chặn duyệt tự động.
- Nguồn **không trả lời** (mục 4) vẫn là `open` và chuyển cán bộ, vì khi đó không tính được gì.

**Test:** `test_missing_purchase_invoices_offer_but_never_auto_approve`.

## 6. Biên bản xác minh thiếu khối `credit` và `interbank_score` (§8)

**Sửa:**
- Biên bản (`conclude`, phần được hash lên chuỗi) có thêm:
  - `credit: {late_12m, active_npl}`;
  - `interbank_score: {value, source, run_id}`, với `source = "fate"`, hoặc `"fallback"` khi FATE không trả điểm.
- Hồ sơ bị dừng trước bước 6 ghi `null` cho hai khối này.

**Test:** `test_record_carries_credit_and_interbank_blocks`.

## 7. Đồng hồ "cờ open quá 3 ngày" đếm sai mốc (§5 bước 10)

**Lỗi:** `escalate_overdue` đếm từ `updated_at` của hồ sơ. Một tin nhắn chat hay một lần ký lại ủy quyền là đặt lại đồng hồ, nên hồ sơ có thể treo mãi ở `needs_answer`.

**Sửa:**
- Mỗi cờ có `opened_at` lúc được bật.
- `escalate_overdue` đếm từ cờ `open` cũ nhất; hồ sơ cũ chưa có trường này thì dùng `updated_at`.

**Test:** `test_open_flag_clock_starts_when_the_flag_opens`.

## 8. Test còn thiếu (đã bổ sung)

- `test_revoked_entity_is_rejected_at_step_2`: `POL_ENTITY_INACTIVE`.
- `test_verify_without_any_consent_reads_nothing`: chưa từng ký ủy quyền thì gọi `/verify` bị từ chối, không có lời gọi công cụ dữ liệu nào.

---

## Chưa sửa (cần quyết định của nhóm hoặc nguồn thật)

| Vấn đề | Lý do chưa sửa |
|---|---|
| `verify_identity`: `face_match` luôn True; `account_owner_match` chỉ chép lại `entity_match` | Hồ sơ mẫu không có dữ liệu chủ tài khoản hay khuôn mặt; cần dịch vụ định danh thật của ngân hàng. Bước 3 cũng chạy trước bước khai tài khoản, nên muốn kiểm chủ tài khoản phải chuyển phần kiểm này sang bước ủy quyền. |
| Bỏ qua bước 3 cho khách WeBank đã xác thực | Tính năng mới, cần nguồn trạng thái KYC. |
| Sàn không hỗ trợ trả lỗi 400 (gợi ý nhập số ĐKKD) thay vì `POL_OUT_OF_SCOPE` | Đổi luồng tạo hồ sơ và giao diện; cần nhóm chọn cách xử lý. |
| Không kiểm chủ thể đăng ký tại Trung Quốc đại lục; không đối chiếu "đối tác chuyển tiền = công ty thanh toán của sàn" | Dữ liệu đăng ký và dòng tiền mẫu không có các trường này. |
| `RISK_UNDECLARED_STORE` nhánh "kênh bán trên thuế chưa khai" | Dữ liệu thuế mẫu không có kênh bán. Hiện không kịch bản nào bật cờ này (`undeclared_platforms` luôn rỗng); test phải monkeypatch. |
| `RISK_PASS_THROUGH` chọn "Lương" không bao giờ đóng (`payroll.matches_transfers` cứng là False) | Giới hạn của dữ liệu mẫu. |
| `RISK_SALES_SPIKE` đóng khi tỷ trọng bán sỉ > 30%, không đo phần tăng | Cần dữ liệu hóa đơn theo tháng. |
| `extract_document`, luồng tải tài liệu lên (`uploads` luôn rỗng) | Tính năng mới. |
| `write_notes` của LLM không có code kiểm số mới trong ghi chú | Ghi chú chỉ cán bộ đọc và Agent 3 đã quét lời tiêm lệnh (RISK-06); nên thêm bộ lọc số như Agent 2. |
| Từng lời gọi công cụ chưa được hash riêng lên FISCO (chỉ biên bản tổng có hash) | Thay đổi kiến trúc ghi chuỗi, ảnh hưởng mọi agent. |
| Agent 3: RISK-02 có sàn "smaller" nhưng cổng đòi sàn "approve", nên hồ sơ có cờ `explained_unverified` luôn bị chuyển cán bộ | Lỗi của Agent 3, ngoài phạm vi lần sửa này. |

## Khôi phục bản cũ

```bash
cd /Users/trantiendung/Desktop/fintech_final
cp fintech_new_backup_20261014_154435/BackEnd/src/app/agents/agent1_verify.py fintech_new/BackEnd/src/app/agents/
cp fintech_new_backup_20261014_154435/BackEnd/src/app/data_sources/{profiles,sources}.py fintech_new/BackEnd/src/app/data_sources/
cp fintech_new_backup_20261014_154435/BackEnd/src/tests/{test_profiles,test_pipeline_algorithm,test_sources_fate}.py fintech_new/BackEnd/src/tests/
```
