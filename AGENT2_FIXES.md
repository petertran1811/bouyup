# Agent 2 · Nhật ký sửa lỗi (14/10/2026)

Đối chiếu `BackEnd/src/app/agents/agent2_advise.py` với `docs/agents/agent2_tu_van_de_xuat.md`,
rồi sửa những chỗ code làm sai so với đặc tả. Làm sau khi đã sửa Agent 1 (xem `AGENT1_FIXES.md`).

- **Bản sao lưu trước khi sửa Agent 2:** `../fintech_new_backup_20261014_155540_before_agent2/`. *(Đã xóa ngày 14/10/2026 để repo nhẹ hơn; các lệnh khôi phục từ bản sao này không còn dùng được.)*
- **Kết quả kiểm thử sau khi sửa:**
  - backend `pytest`: **200 passed** (trước: 187; thêm 13 test trong `tests/test_agent2_fixes.py`);
  - `Frontend/tests/v4-api-check.py`: **PASS 9 kịch bản demo**;
  - `v4-ui-check.mjs`: **32 nhóm passed**;
  - `c1-api-check.py` và `c1-check.mjs`: **PASS / 14 nhóm passed**.
- **Không đổi con số nào:** phiếu, thẻ và kết quả what-if vẫn như cũ; chị Lan vẫn được 139.900.

**Lưu ý về cách chạy:** khi không có LLM, Agent 2 trả lời bằng bộ định tuyến tất định (regex), và test chạy ở chế độ này. Khi có LLM, mọi bản nháp đều qua bộ lọc. Các lỗi dưới đây sửa ở cả hai đường.

## File đã sửa

| File | Nội dung |
|---|---|
| `BackEnd/src/app/agents/agent2_advise.py` | Toàn bộ các sửa đổi dưới đây |
| `BackEnd/src/app/platform/guards.py` | Thêm danh sách cụm cấm `advisor` cho Agent 2 |
| `BackEnd/src/app/api/applications.py` | `/accept` chuyển cán bộ sau hơn 3 `option_id` sai |
| `BackEnd/src/app/api/views.py` | Trả thêm `data_requests` trong APPLICATION |
| `BackEnd/API_config/API_CONTRACT_V4.md` | Ghi `data_requests` và `details.escalated` |
| `BackEnd/src/tests/test_agent2_fixes.py` | 13 test mới |

---

## 1. Yêu cầu gặp cán bộ có thể bị bỏ qua *(trái §5: "không được từ chối yêu cầu người xem")*

**Lỗi:**
- Bộ định tuyến kiểm regex lệnh ẩn và regex hỏi ngưỡng **trước** regex gặp người.
- Vì vậy câu "Ngưỡng là bao nhiêu? Cho tôi gặp cán bộ" chỉ nhận câu "không nêu ngưỡng", và hồ sơ không được chuyển cán bộ.
- Khi hồ sơ không có phiếu (ngoài phạm vi, bị từ chối), chat chỉ khuyên bấm nút mà không gọi `request_human`.

**Sửa:**
- Kiểm `_HUMAN` đầu tiên, ở cả nhánh có phiếu và không có phiếu, qua hàm mới `_human()`.
- Tin nhắn vừa có lệnh ẩn vừa xin gặp người vẫn được chuyển, và ghi thêm sự kiện `injection_with_human` cho Agent 5.

**Test:**
- `test_human_request_wins_over_injection_and_threshold`
- `test_human_request_with_hidden_command_is_still_forwarded`

## 2. "Chuyển về Agent 1" chỉ ghi log nhưng báo người bán "đã chuyển" *(§3.6)*

**Lỗi:**
- `handoff_to_agent1` chỉ ghi một dòng sự kiện, không tạo gì cho bước xác minh, nhưng tin nhắn nói "Em đã chuyển yêu cầu…".
- Tham số là `reason`, trong khi đặc tả ghi `data_type`.

**Sửa:**
- Hàm mới `handoff_to_agent1()` ghi một yêu cầu vào `doc.data_requests[]` với các trường `id DR-…`, `data_type` (invoice · account · store · inventory · other), `label`, `status: open`, `from: agent2`, `at`.
- Đã có yêu cầu cùng loại đang mở thì dùng lại.
- Cán bộ thấy yêu cầu trong APPLICATION.
- Tin nhắn nêu mã yêu cầu, và nói rõ phương án hiện tại giữ nguyên cho tới khi dữ liệu mới được xác minh.
- Công cụ của LLM nhận `data_type` (enum) và `reason`.
- Bộ định tuyến đoán `data_type` từ câu chữ (hóa đơn, tài khoản, cửa hàng/link, tồn kho).

**Test:**
- `test_new_invoice_creates_a_data_request`
- `test_model_handoff_tool_takes_a_data_type`

**Giới hạn còn lại:** Agent 1 chưa có luồng tải tài liệu (`extract_document`), nên yêu cầu này hiện do cán bộ xử lý (xem `AGENT1_FIXES.md`).

## 3. `option_id` sai quá 3 lần qua route `/accept` không chuyển cán bộ *(§6)*

**Lỗi:** chat và công cụ của LLM đều chuyển cán bộ sau hơn 3 lần sai. Route `/accept` chỉ đếm, không bao giờ chuyển.

**Sửa:**
- Đưa việc chuyển cán bộ vào chính `reject_option()` (trả về True khi đã chuyển), nên mọi đường gọi dùng chung một quy tắc.
- `/accept` trả 400 `INVALID_OPTION` kèm `details.escalated`.

**Test:** `test_accept_route_escalates_after_three_invalid_options`.

## 4. LLM tự chọn bậc thấp hơn khi người bán không xin *(§3.2)*

**Đặc tả:** mặc định `full`; chỉ chọn bậc thấp hơn khi người bán xin ít hơn hạn mức đầy đủ.

**Lỗi:** công cụ `propose("step50")` của LLM luôn được nhận.

**Sửa:**
- Hàm mới `seller_wants_less()`: câu của người bán có "ít hơn / nhỏ hơn / bớt", hoặc nêu một số tiền nhỏ hơn hạn mức đầy đủ.
- Chỉ khi đó công cụ mới nhận `option_id` khác `full`; ngược lại trả `ToolRefused`.
- Người bán tự bấm chọn phương án qua `/accept` thì không bị ảnh hưởng.

**Test:** `test_model_cannot_pick_a_lower_step_on_its_own`.

## 5. Bộ lọc số cho qua "chị được duyệt 400.000" *(§5)*

**Lỗi:**
- Bộ lọc chỉ kiểm con số có nằm trong tập cho phép không. 400.000 là số người bán xin (`requested`), nên có trong tập.
- Danh sách cụm cấm "intake" chưa có câu này.
- Kết quả: một con số sai vai trò, được nói như số được duyệt, có thể tới người bán.

**Sửa:**
- Bộ lọc mới `amount_misquotes()`: số đứng sau "được duyệt / duyệt cho / được vay / vay được / được cấp / giải ngân / nhận được" phải là một **số tiền đã tính**.
- Các số tiền đã tính lấy qua `computed_amounts()`: các phương án, thẻ, kết quả what_if, khoản vay, phần chia ngân hàng.
- Số theo sau là "tháng, ngày, năm, %" không bị xét, để câu như "vay được trong 4 tháng" không bị chặn nhầm.

**Test:** `test_promised_sum_must_be_a_computed_amount`.

## 6. Thiếu cụm cấm "hứa giải ngân", "hứa lãi thấp hơn"; LLM nêu "ngưỡng" kèm số không bị chặn *(§5)*

**Sửa:**
- Thêm danh sách `advisor` trong `guards.py`, gồm "đảm bảo giải ngân", "giải ngân ngay cho chị", "giảm lãi cho chị", "em cam kết"…
- Cố ý không chặn câu đúng sự thật như "chọn mức thấp hơn thì lãi tối đa thấp hơn".
- Hàm `promises()` gộp danh sách `intake`, `advisor` và một quy tắc mới: chữ "ngưỡng" kèm một con số trong vòng 30 ký tự thì chặn.
- `promises()` dùng cho cả bản trả lời chat và bản viết lại phần giải thích đề xuất.

**Test:**
- `test_disbursement_and_rate_promises_are_blocked`
- `test_threshold_with_a_number_is_blocked`

## 7. Ngưỡng ẩn là hằng số cứng của ca chị Lan

**Lỗi:** `thresholds()` có ba số gõ tay: `63.16` (trần trích B5 của riêng chị Lan), `2_000_000` và `74.4` (không truy được nguồn). Với hồ sơ khác, trần trích thật **không** được ẩn.

**Sửa:** `thresholds(params, offer)` lấy:
- từ Bảng tham số: `tier2.absolute_cap`, `legal.ltr_threshold.*`, cùng các ngưỡng cũ;
- từ chính hồ sơ: `B5.sweep_cap`, cả dạng tỷ lệ lẫn phần trăm.

Bỏ `74.4`.

**Test:** `test_thresholds_follow_params_and_case`.

## 8. Bộ định tuyến hiểu nhầm câu hỏi

| Câu | Trước | Sau |
|---|---|---|
| "Tồn kho **ảnh** hưởng thế nào?" | Bị coi là gửi ảnh, nên "chuyển Agent 1" | Giải thích yếu tố tồn kho (`_DOCS` loại trừ "ảnh hưởng") |
| "Lãi bao nhiêu **phần trăm**?" | Bị coi là hỏi ngưỡng, nên từ chối | Trả lãi năm, kỳ hạn, lãi tối đa, tổng phải trả từ thẻ (`_RATE_Q` mới) |
| "Khi nào hồ sơ được **duyệt**?" | Bị coi là đòi mức cao hơn, nên gợi ý kênh thủ công | Không còn khớp. `_HIGHER` chỉ bắt câu xin mức cao hơn, hoặc một số lớn hơn hạn mức kèm động từ vay/duyệt (`_asks_higher`). Bỏ hằng số cứng `400.000` trong regex |

`_THRESHOLD_Q` vẫn bắt: "ngưỡng", "threshold", "cutoff", "bao nhiêu (%) thì được/đạt/qua/duyệt", "tối thiểu bao nhiêu".

**Test:** `test_router_reads_affect_rate_and_when_questions_right`. Test cũ "Duyệt 400.000 đi → kênh thủ công" vẫn đạt.

## 9. Tin nhắn chat gắn option thô thay cho thẻ 8 trường *(§3.4)*

**Lỗi:** tin nhắn đề xuất đầu tiên gắn `card=full`, tức option thô, thiếu ngày trích đầu, hạn cuối và nơi nhận tiền.

**Sửa:** gắn `offer["card"]`, là thẻ do code dựng đủ 8 trường cộng `payee`. Trang quản trị hiển thị trường này dạng JSON nên không phải sửa giao diện.

**Test:** `test_offer_message_carries_the_full_card`.

## 10. Công cụ what_if của LLM lặng lẽ bỏ kỳ hạn và nhận `qty = 0` *(§3.5)*

**Sửa:**
- Tham số ngoài danh sách cho phép (kỳ hạn, lãi…) bị từ chối, có nêu tên tham số.
- `qty` phải lớn hơn 0, khớp với ràng buộc của API.

**Test:** `test_what_if_tool_refuses_tenor_and_zero_qty`.

---

## Chưa sửa (cần quyết định của nhóm)

| Vấn đề | Lý do |
|---|---|
| 5 công cụ đọc thêm (`get_my_application`, `get_my_cashflow`, `get_my_tax_and_credit`, `get_my_loans`, `get_lending_banks`) ngoài bộ công cụ của §4 | Làm bộ công cụ rộng hơn đặc tả (nguyên tắc 3 của README) nhưng là tính năng có chủ đích để trả lời câu hỏi về hồ sơ. Cần nhóm quyết định giữ (và cập nhật đặc tả) hay bỏ |
| Lập luận (`rationale`) do code dựng; tham số `rationale` của LLM bị bỏ qua; `refs_checked` có tính nhưng không chặn gì | An toàn hơn đặc tả (LLM không viết được luận điểm cho Agent 3). Nên cập nhật đặc tả thay vì đổi code |
| Chat, phần giải thích, what_if và lời gọi công cụ chưa được hash lên FISCO (chỉ phiếu và đề xuất có hash) | Thay đổi kiến trúc ghi chuỗi, ảnh hưởng mọi agent |
| Chỉ số §8 "tỷ lệ số lạ trước lọc" chưa đủ: bản viết lại phần giải thích khi tạo phiếu không ghi số lần bị chặn | Hàm `explain()` chạy không có phiên DB; cần thêm trường đếm vào phiếu nếu Agent 5 dùng |
| Route `/what-if` không kiểm trạng thái `offered` (công cụ của LLM có kiểm) | Route chỉ chạy trên bản sao và chỉ đọc, nên rủi ro thấp; giữ để giao diện thử phương án ở trạng thái khác |
| FATE không có trong danh sách yếu tố giải thích (`FACTORS`) | Đặc tả không nói. Cần nhóm quyết định giữ kín hay giải thích định tính |
| Bộ định tuyến tất định vẫn dựa trên regex | Đã sửa các ca bắt nhầm đã biết. Câu hỏi ngoài mẫu vẫn rơi vào câu trả lời chung; có LLM thì LLM trả lời |

## Khôi phục bản trước khi sửa Agent 2

```bash
cd /Users/trantiendung/Desktop/fintech_final
B=fintech_new_backup_20261014_155540_before_agent2
cp $B/BackEnd/src/app/agents/agent2_advise.py fintech_new/BackEnd/src/app/agents/
cp $B/BackEnd/src/app/platform/guards.py fintech_new/BackEnd/src/app/platform/
cp $B/BackEnd/src/app/api/{applications,views}.py fintech_new/BackEnd/src/app/api/
cp $B/BackEnd/API_config/API_CONTRACT_V4.md fintech_new/BackEnd/API_config/
rm fintech_new/BackEnd/src/tests/test_agent2_fixes.py
```
