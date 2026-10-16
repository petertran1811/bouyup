# Agent 4 và Agent 5 · Nhật ký sửa lỗi (14/10/2026)

Đối chiếu code với `docs/agents/agent4_giai_ngan_thu_no.md` và `docs/agents/agent5_hau_kiem.md`, rồi sửa những chỗ code làm sai so với đặc tả. Làm sau Agent 1, 2, 3 (xem `AGENT1_FIXES.md`, `AGENT2_FIXES.md`, `AGENT3_FIXES.md`).

- **Bản sao lưu trước khi sửa:** `../fintech_new_backup_20261014_161731_before_agent45/`. *(Đã xóa ngày 14/10/2026 để repo nhẹ hơn; các lệnh khôi phục từ bản sao này không còn dùng được.)*
- **Kết quả kiểm thử sau khi sửa:**
  - backend `pytest`: **232 passed** (trước: 214; thêm 10 test trong `tests/test_agent4_fixes.py` và 8 test trong `tests/test_agent5_fixes.py`);
  - `v4-api-check.py`: **PASS 9 kịch bản demo**;
  - `v4-ui-check.mjs`: **32 nhóm passed**;
  - `c1-api-check.py` và `c1-check.mjs`: **PASS / 14 nhóm passed**.
- **Luồng demo không đổi:** chị Lan vẫn được giải ngân 139.900 cho SUP-0091, chia WeBank 100%.

## File đã sửa

| File | Nội dung |
|---|---|
| `BackEnd/src/app/agents/agent4_disburse.py` | Mục A1–A8; công tắc tắt duyệt tự động ở B6 |
| `BackEnd/src/app/api/loans.py` | `payout_id` trong `simulate-inflow` |
| `BackEnd/src/app/blockchain/chain.py` | Hàng chờ bỏ lệnh giải ngân thì chuyển cán bộ |
| `BackEnd/src/app/agents/agent5_postaudit.py` | Mục B1–B7 |
| `BackEnd/src/app/agents/agent5_llm.py` | Kiểm số trong lý do, bước 0,04, sinh lại tóm tắt |
| `BackEnd/src/app/platform/config.py`, `BackEnd/API_config/.env.example` | `BUOYUP_AGENT5_MIN_SAMPLE` (mặc định 30) |
| `BackEnd/API_config/API_CONTRACT_V4.md` | `payout_id`, thông báo trích nợ, các trường mới của báo cáo hậu kiểm |
| `tests/test_agent4_fixes.py`, `tests/test_agent5_fixes.py` **(mới)** | 18 test |
| `tests/test_money_agent4.py`, `test_agent4_duties.py`, `test_agents45_llm.py`, `test_autopilot.py`, `test_money_api.py`, `test_ruleset_postaudit.py`, `Frontend/tests/v4-api-check.py` | Cập nhật theo hành vi đúng (xem từng mục) |

---

## A. Agent 4 · Giải ngân và thu nợ

### A1. Trích nợ hai lần cho cùng một lần tiền về *(nghiêm trọng; §3.4, §6 "Payout trùng mã: code bỏ qua")*

**Lỗi:** `simulate_inflow` không có mã payout. Gọi lại API là trích thêm lần nữa, và người bán cũng gọi được API này.

**Sửa:**
- API nhận `payout_id`.
- Mã đã xử lý thì bỏ qua: không trích, không ghi chuỗi, chỉ ghi sự kiện `payout_duplicate`.
- Mã payout nằm trong bản ghi `repayment` trên chuỗi.
- Danh sách mã đã xử lý lưu ở `loan.doc.payout_ids` (không cần đổi bảng, vì hệ thống không có migration).

**Test:** `test_duplicate_payout_id_is_swept_once`.

### A2. Kiểm tra dùng vốn lấy dữ liệu demo của chị Lan khi hồ sơ thiếu dữ liệu *(nghiêm trọng)*

**Lỗi:** `check_use_of_funds` dùng `data or SCENARIOS["lan"]`, nên khoản vay của người khác có thể bị đánh "ok" dựa trên hóa đơn của chị Lan.

**Sửa:**
- Không có dữ liệu thuế thì không kiểm được: trước hạn giữ `pending`, quá hạn thì `unverifiable`.
- Kèm tín hiệu "Không có dữ liệu hóa đơn để kiểm việc dùng vốn" (WCLOAN-2024#10) để cán bộ xem.

**Test:** `test_use_of_funds_without_data_is_unverifiable_not_ok`.

### A3. Không có lần kiểm nhà cung cấp cuối trước khi giải ngân *(§3.1, §7.2 "đổi tài khoản nhận")*

**Sửa:** hàm mới `check_supplier_final`, chạy ngay trước lệnh giải ngân:
- Người nhận tiền phải trùng người nhận đã ghi trong bản ghi `gate_decision` trên chuỗi lúc duyệt. Bắt được kiểu lừa "nhà cung cấp đổi tài khoản".
- Nếu người nhận là nhà cung cấp: nhà cung cấp đó phải có trong lịch sử hóa đơn của người bán, và không cùng nhóm liên kết (chạy lại `link_entities`).
- Không đạt thì **không giải ngân**, hồ sơ chuyển cán bộ (`escalation.why = SUPPLIER_CHECK_FAILED`, kèm từng điểm kiểm).

**Test:**
- `test_payee_swapped_after_approval_is_not_paid`
- `test_linked_supplier_is_not_paid`

**Test cũ đã sửa:** `test_use_of_funds_check` trước đây giải ngân thẳng cho SUP-0137, là nhà cung cấp **cùng nhóm liên kết** và không có hóa đơn. Lần kiểm mới chặn đúng việc này. Test giờ trả tiền cho người vay với kế hoạch dùng SUP-0137.

**Fixture test:** `lan_doc` trong `test_money_agent4.py` có thêm `internal.data` (dữ liệu Agent 1 đã kiểm). Hồ sơ thật luôn có phần này.

### A4. Bước giải ngân không kiểm lại ngưỡng 500.000 *(§3.2: "từ chối giải ngân khoản vượt ngưỡng tự động nếu chưa có chữ ký cán bộ")*

**Sửa:**
- `disburse()` từ chối số tiền ≥ `gate.auto_limit` khi quyết định không do cán bộ (`decision.by != "officer"`).
- Trước đây chỉ cổng của Agent 3 chặn việc này.

**Test:** `test_large_amount_needs_an_officer_at_payout`.

### A5. Không chặn khoản vay thứ hai cho cùng hồ sơ *(§3.2 "từ chối giải ngân lần hai")*

**Sửa:** trước khi tạo khoản vay, code tìm khoản vay đã có của hồ sơ. Có thì trả 409.

**Ghi chú:** SQLite chỉ cho một tiến trình ghi một lúc, nên hai yêu cầu đồng thời khó tạo trùng. Khi chuyển sang Postgres nên thêm ràng buộc duy nhất trên `bu_loans.application_id`.

**Test:** `test_second_loan_for_an_application_is_refused`.

### A6. Lệnh giải ngân trong hàng chờ bị bỏ thì hồ sơ kẹt ở "approved" *(§6 "báo cán bộ")*

**Lỗi:**
- Bị dịch vụ chuỗi từ chối (4xx) hoặc hết 20 lượt thử thì hàng chờ chỉ đặt `failed`.
- Không ai được báo; hồ sơ nằm ở `approved` mà không có khoản vay.

**Sửa:** hàm `disburse_failed` chuyển hồ sơ sang cán bộ (`DISBURSE_FAILED`).
- Lệnh bị **từ chối** vẫn không thử lại.
- Lỗi **mạng/chuỗi sập** vẫn thử lại tới 20 lần với cùng `requestId`, nên không chi hai lần. Đây là sự cố hạ tầng, khác với "core banking từ chối lệnh" trong đặc tả.

**Test:** `test_failed_payout_in_outbox_escalates`.

### A7. Không giải thích từng lần trích *(§3.5)*

**Sửa:**
- Mỗi lần tiền về có một thông báo (`level: "info"`, `kind: "sweep"`, do code dựng). Ví dụ: "Tiền hàng về 20.000 CNY. Hệ thống trích 63% là 12.600 CNY để trả nợ; chị giữ 7.400 CNY. Dư nợ còn 132.896 CNY."
- Trong ân hạn: thông báo chưa trích và ngày bắt đầu trích.
- Hàm `push_notice` giữ tối đa 20 thông báo nhưng **không bao giờ đẩy mất câu hỏi người bán chưa trả lời**. Trước đây thông báo mới có thể đẩy câu hỏi cảnh báo vàng ra khỏi danh sách.

**Test:**
- `test_each_sweep_is_explained`
- `test_push_notice_never_drops_an_open_question`

### A8. B11: điểm FATE "chấm lại" được suy từ việc trả thiếu sàn, nên đếm hai lần

**Lỗi:**
- Điểm FATE "hiện tại" được tính bằng `baseline + 1` khi có thiếu sàn hoặc quá hạn.
- Vì vậy thiếu sàn dù một đồng là tín hiệu `fate_worse` (0,20) bật, trong khi B11 đã tính thiếu sàn riêng.

**Sửa:**
- Mỗi vòng giám sát hỏi lại FATE thật qua `sources.fate_source`: dịch vụ FATE khi có `FATE_URL`, nếu không thì dữ liệu mẫu.
- FATE không trả lời thì giữ giá trị cũ.
- `fate.simulated` chỉ còn là `true` khi không có `FATE_URL`.

**Test:** `test_fate_worse_comes_from_a_real_rescore`. Test cũ `test_floor_and_tick_alerts` sửa assert: tín hiệu `fate_worse` không còn bật chỉ vì thiếu sàn.

---

## B. Agent 5 · Hậu kiểm

### B1. Mỗi lần hậu kiểm lại sinh thêm một đề xuất `prudence.*` trùng

**Lỗi:**
- `_proposals_from` không kiểm đề xuất đang chờ, khác với `cohort_proposals`.
- Vòng tự chạy tạo thêm bản trùng mỗi khi có khoản vay đổi. Duyệt một bản thì các bản còn lại hỏng `from_value`.

**Sửa:** đã có đề xuất đang chờ cho tham số đó thì không tạo thêm.

**Test:** `test_reruns_do_not_pile_up_prudence_proposals`.

### B2. Đề xuất đổi hệ số thận trọng trên mẫu quá nhỏ *(§6, §8: "Cỡ mẫu ngành dưới 30 → không đề xuất")*

**Lỗi:** 20 mẫu tổng hợp và 0 khoản vay thật vẫn ra đề xuất. Có cả test khẳng định "the synthetic backtest always proposes".

**Sửa:**
- Dưới `BUOYUP_AGENT5_MIN_SAMPLE` mẫu (mặc định **30**) thì phát hiện ghi "Chưa đủ mẫu (20/30): không đề xuất".
- Mỗi phát hiện ghi rõ số khoản vay thật và số mẫu tổng hợp.

**Ảnh hưởng tới demo:** với cấu hình mặc định, trang Quản trị sẽ **không còn đề xuất hệ số thận trọng** sau hậu kiểm, vì mẫu tổng hợp chỉ có 20 dòng. Muốn trình diễn luồng đề xuất và duyệt, đặt `BUOYUP_AGENT5_MIN_SAMPLE=20` trong `.env`. Đề xuất khi đó ghi rõ "… mẫu tổng hợp". `Frontend/tests/v4-api-check.py` đặt 20 vì nó ghi lại dữ liệu demo cho kiểm tra giao diện.

**Test:**
- `test_small_sample_reports_but_does_not_propose`
- Bốn test quy trình duyệt cũ đặt `MIN_SAMPLE = 20`, kèm ghi chú lý do.

### B3. Không có giới hạn bước 0,04 mỗi quý *(§3.3)*

**Sửa:**
- Đề xuất của code bị kẹp trong phần bước còn lại của quý. Ví dụ kiểm định ngược ra 0,55 thì đề xuất 0,70 → 0,66.
- Đã dùng hết bước của quý thì không đề xuất tiếp.
- Mô hình đề xuất `prudence.*` lệch quá 0,04 thì bị từ chối.
- Lúc duyệt, code cộng mọi thay đổi đã duyệt của tham số trong 90 ngày. Vượt 0,04 thì trả 400.

**Test:**
- `test_prudence_step_is_capped`
- `test_quarter_cap_holds_across_approvals`

### B4. Số bịa trong lý do (`why`) của mô hình lọt vào bằng chứng của đề xuất *(§3.7, §6)*

**Sửa:**
- Số trong `why` phải có trong báo cáo hoặc bảng tham số. Không có thì công cụ từ chối và nêu số sai để mô hình viết lại.
- Tóm tắt có số lạ được **sinh lại một lần**, sau đó mới bỏ. Trước đây bỏ ngay.

**Test:**
- `test_model_reason_with_an_invented_number_is_refused`
- `test_summary_with_an_invented_number_is_written_again`

### B5. Nội dung đề xuất và quyết định không có trên chuỗi *(README, nguyên tắc 4)*

**Sửa:**
- Báo cáo được băm giờ chứa `proposals`: tham số, giá trị cũ, giá trị mới và bằng chứng của **mọi** đề xuất, của code lẫn của mô hình.
- Báo cáo cũng chứa `llm_tool_calls`.
- Từ chối đề xuất được ghi chuỗi (`proposal_decision`). Trước đây chỉ có duyệt được ghi.
- Công tắc tắt hoặc bật lại duyệt tự động được ghi chuỗi (`auto_switch`).

**Test:**
- `test_report_hash_covers_proposals_and_decisions`
- `test_auto_cohort_and_switch_on_chain`

### B6. Công tắc tắt duyệt tự động tính cả khoản cán bộ duyệt; không có ngưỡng cảnh báo *(§3.2)*

**Sửa:**
- Công tắc chỉ đếm khoản vay **cổng tự duyệt**.
- Báo cáo có `auto_cohort`: số khoản, tỷ lệ nợ xấu, ngưỡng cảnh báo (bằng 3/4 ngưỡng cứng, tương ứng 3% so với 4% trong đặc tả) và trạng thái `ok`, `warn` hoặc `hard`.

**Ngưỡng cứng chưa đổi:** hiện là 8% nợ quá hạn 90 ngày trong Bảng tham số; đặc tả ghi 4% quá hạn 30 ngày. Xem mục cần quyết định bên dưới.

### B7. Chạy song song chưa có *(§3.7 `shadow_run`)*

**Sửa:**
- Hàm `shadow_run` chạy lại giải thuật trên tối đa 200 hồ sơ gần nhất với giá trị đề xuất, chỉ đọc, không ghi gì.
- Kết quả được thêm vào bằng chứng của mỗi đề xuất, ví dụ: "Chạy song song trên N hồ sơ gần nhất: K hồ sơ đổi hạn mức, tổng thay đổi …".

### B8. Nhãn "mô phỏng" luôn là true

**Sửa:**
- Báo cáo chỉ ghi `simulated: true` khi có phát hiện dựa vào mẫu tổng hợp.
- Mỗi phát hiện có `synthetic_samples` và `own_loans`.
- Bằng chứng của đề xuất ghi rõ số mẫu tổng hợp.

---

## Chưa sửa (cần quyết định của nhóm hoặc là tính năng mới)

| Agent | Vấn đề | Lý do |
|---|---|---|
| 4 | **Tiền mặc định trả cho người vay**, chỉ trả thẳng nhà cung cấp khi POL-05 áp dụng; đặc tả §2 nói "tiền đi thẳng tới nhà cung cấp" | Quyết định sản phẩm và pháp lý: thanh toán ủy thác bắt buộc theo WCLOAN-2024#30 chỉ trong một số trường hợp. Tầng 1 không có nhà cung cấp. Cần nhóm chốt |
| 4 | Lãi cố định tối đa, chưa tính lãi theo ngày; chưa phân bổ quá hạn → lãi → gốc (§3.4) | Đổi mô hình tiền của khoản vay và hợp đồng trên chuỗi; đặc tả §9 vẫn để ngỏ câu hỏi này |
| 4 | Trích bổ sung khi thiếu sàn (§3.6), theo dõi vận đơn (§3.3), soạn phương án giãn nợ (§3.8) | Tính năng mới; cần dữ liệu vận đơn và hợp đồng giãn nợ |
| 4 | Trọng số và điều kiện B11 khác bảng đề xuất ở §3.7 (dòng tiền 0,15 so với 0,20; tra cứu 0,15 so với 0,10; dùng FATE thay cho tỷ lệ hoàn hàng) | Đây là tham số `[Đặt tay]` trong Bảng tham số. Đổi phải qua hội đồng và có phiên bản mới; đặc tả §9 cũng hỏi "trọng số có dùng được không" |
| 4 | Dữ liệu theo dõi (doanh số, điểm cửa hàng) đứng yên sau giải ngân | Cần nguồn dữ liệu cập nhật sau giải ngân |
| 4 | Vàng chưa phân tích nguyên nhân bằng công cụ (`get_sales_trend`…); đỏ chưa có `notify_officer` riêng | Hiện hỏi người bán chọn nguyên nhân; cán bộ xem danh sách cảnh báo |
| 5 | Ngưỡng cứng tắt duyệt tự động: 8% quá hạn 90 ngày (tham số) so với 4% quá hạn 30 ngày (đặc tả) | Tham số chính sách, đổi qua hội đồng |
| 5 | PSI (§3.4), bộ tấn công thử (§3.6), agent phản biện (§3.7), `add_test_case` | Tính năng mới |
| 5 | Một admin duyệt được đề xuất của lượt tự chạy; đặc tả nói "hội đồng" | Hiện chỉ chặn người chạy tự duyệt. Muốn nhiều chữ ký thì cần quy trình duyệt mới |
| 5 | Chưa lọc theo ủy quyền mục đích "cải tiến mô hình" (§5) | Bản ủy quyền hiện không có phạm vi này |
| 5 | Vòng tự chạy giữ khóa autopilot trong lúc gọi mô hình (tối đa 10 bước) | Không giữ khóa ghi DB, vì trước lời gọi mô hình chỉ có truy vấn đọc. Nhưng vòng Agent 4 phải chờ trong lúc đó; nên tách khi chuyển sang tiến trình riêng |
| 5 | Chỉ số §3.5 (tỷ lệ đổi ý pha 2, số lạ, lời gọi lỗi) chưa tính trên đúng mẫu số | Cần thống nhất định nghĩa chỉ số |

## Khôi phục bản trước khi sửa Agent 4 và 5

```bash
cd /Users/trantiendung/Desktop/fintech_final
B=fintech_new_backup_20261014_161731_before_agent45
for f in app/agents/agent4_disburse.py app/agents/agent5_llm.py app/agents/agent5_postaudit.py app/api/loans.py \
         app/blockchain/chain.py app/platform/config.py tests/test_agent4_duties.py tests/test_agents45_llm.py \
         tests/test_autopilot.py tests/test_money_agent4.py tests/test_money_api.py tests/test_ruleset_postaudit.py; do
  cp $B/BackEnd/src/$f fintech_new/BackEnd/src/$f
done
cp $B/BackEnd/API_config/{.env.example,API_CONTRACT_V4.md} fintech_new/BackEnd/API_config/
cp $B/Frontend/tests/v4-api-check.py fintech_new/Frontend/tests/
rm fintech_new/BackEnd/src/tests/test_agent4_fixes.py fintech_new/BackEnd/src/tests/test_agent5_fixes.py
```
