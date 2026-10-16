# Chuyển BuoyUp sang quy trình "loan circle" — nhật ký thay đổi

Căn cứ: `docs/BuoyUp loan circle .docx` (10 giai đoạn) và 4 điểm đội chốt ngày 14/10/2026 (xem `LOAN_CIRCLE_PLAN.md`).
Bản sao trước khi đổi: `../fintech_new_backup_20261014_171159_before_loancircle`. *(Đã xóa ngày 14/10/2026 để repo nhẹ hơn; các lệnh khôi phục từ bản sao này không còn dùng được.)*
Kết quả kiểm thử: **256 test backend đạt** (`cd BackEnd/src && ../.venv/bin/python -m pytest -q`); 4 bộ kiểm giao diện đạt
(`Frontend/tests`: v4-api-check.py — 11 kịch bản và luồng Lan chọn → hợp đồng → ký → giải ngân → trả nợ → tất toán; v4-ui-check.mjs 33 nhóm;
c1-api-check.py; c1-check.mjs 14 nhóm). Máy chủ demo đã chạy lại với DB mới (`data/buoyup.db`; DB cũ lưu ở
`data/buoyup_before_loancircle_20261014.db`).

> Cơ sở dữ liệu cũ (`data/buoyup.db`) chứa hồ sơ và khoản vay theo mô hình cũ, không đọc được bằng code mới: cần
> tạo lại (`reset_db` + `seed`, hoặc xóa file rồi khởi động lại).

## 1. Bốn điểm đội đã chốt và cách code làm

| Điểm | Quyết định | Ở đâu trong code |
|---|---|---|
| Không đối tác nào đồng ý trong 30 giây | WeBank không cho vay một mình: thử lại ở 70%, 50% hạn mức, vẫn không ai nhận → từ chối (`NO_PARTNER`) | `app/banks/syndicate.py` `run()`; tham số `syndicate.retry_steps` |
| Tỷ lệ trả theo doanh thu | Giải thuật tính theo hồ sơ: đủ trả gốc + lãi trong kỳ hạn trên doanh thu thận trọng, không vượt trần B5. Tối thiểu = lãi kỳ + 30% gốc một kỳ trả góp đều | `algorithm.revenue_rate()`, `algorithm.min_payment()`; Agent 4 `_process_due()` |
| Ngưỡng trả thẳng nhà cung cấp | Phần vượt 100.000 tệ | `repay.supplier_direct_threshold`; `advise.payee_for()`; POL-05 |
| Khung kỳ hạn | Hộ kinh doanh 3/6/12; doanh nghiệp 3/6/12/24/36 | `product.tenors` |

## 2. Theo giai đoạn

**Giai đoạn 1 – nộp hồ sơ.** Loại người vay chọn khi tạo hồ sơ, phải khớp đăng ký (lệch → `POL_BORROWER_TYPE`). Ba ô đồng ý riêng, không đánh sẵn, mỗi ô có văn bản (`Frontend/giaodien/van-ban/*.html`); thiếu ô → 400. Ký bằng khuôn mặt hoặc OTP (`consent.sign_method`). Không còn khai tài khoản nhận tiền.

**Giai đoạn 2 – thẩm định và duyệt.** Agent 1 lấy doanh thu từ thuế (`pull_revenue`), báo cáo tín dụng, FATE, lịch sử với BuoyUp (`network_history`: từng quá hạn ≥ 30 ngày → nhóm 4; đã tất toán tốt → nhóm 1). Ảnh doanh thu tự nộp (≤ 6 tháng): lệch thuế ≤ 15% → dùng, hệ số thận trọng +5%; 15–30% → không dùng; > 30% → cờ `RISK_STATEMENT_MISMATCH`, chuyển cán bộ. Bỏ toàn bộ dữ liệu dòng tiền ngân hàng khác (cờ inflow gap, pass-through, cửa hàng không khai).
Hạn mức = min(khả năng trả trong kỳ hạn dài nhất, trần theo nhóm, trần loại người vay 200.000 cho hộ kinh doanh). Agent 2 đề xuất ngay hạn mức đầy đủ; Agent 3 rà và cổng duyệt **hạn mức** (cổng ra "nhỏ hơn" thì gửi ngân hàng phương án nhỏ hơn, người vay không phải nhận lại). Bộ điều phối kiểm quy tắc cứng (danh sách trắng, địa bàn, tập trung 25%/50%, ngân sách tháng, hạn mức còn lại) rồi hỏi các ngân hàng song song; mỗi ngân hàng tự quyết theo chính sách của mình và danh mục trên chuỗi (hạng, số tiền, ngành, loại người vay, trễ hạn, điểm và tuổi cửa hàng, trần lãi), trả lời quá 30 giây = từ chối. Kỳ hạn tối đa của các ngân hàng tham gia giới hạn khung kỳ hạn. Hạn mức hiệu lực 7 ngày (`expired`).

**Giai đoạn 3 – chọn khoản vay.** `/select`: số tiền ≤ hạn mức, kỳ hạn, hình thức (trả góp / theo doanh thu, chọn một lần), ngày trả 1–28; `/quote` xem lịch từng lựa chọn; không duyệt lại. Một người một khoản vay (POL-07 ở Agent 3 và kiểm lại khi chọn, ký).

**Giai đoạn 4 – hợp đồng và ký.** `/contract`: bảng chi phí (lãi năm = toàn bộ chi phí, phí 0, lãi phạt, quy tắc trả tối thiểu, ngân hàng và phần vốn, kênh khiếu nại, lịch trả); đọc ít nhất 20 giây (`READ_TIME`). `/sign`: tài khoản kinh doanh WeBank, cam kết dùng vốn, tài khoản nhà cung cấp khi > 100.000, bảo lãnh người đại diện nếu là doanh nghiệp. Khi ký mới giữ chỗ hạn mức và ngân sách của từng ngân hàng (`reserve_at_signing`), mỗi ngân hàng một số hợp đồng; hợp đồng lên chuỗi (`contract_signed`). Ủy quyền bị rút/hết hạn → không cho chọn, ký.

**Giai đoạn 5 – giải ngân.** Kiểm nhẹ trước khi chuyển tiền (ủy quyền còn hiệu lực, người nhận đúng như hợp đồng, nhà cung cấp có hóa đơn và không liên kết). Các ngân hàng chuyển vào tài khoản trung gian (`escrow_funded`), đủ tiền mới giải ngân một lệnh: ≤ 100.000 vào tài khoản kinh doanh, phần còn lại trả nhà cung cấp; hash hợp đồng, quyết định, lệnh lên chuỗi. Dừng giải ngân → trả lại hạn mức đã giữ.

**Giai đoạn 6 – giám sát.** Tiền hàng về tài khoản kinh doanh (`simulate-inflow`); chi ra (`simulate-transfer`): chứng khoán/bất động sản → cảnh báo đỏ và ghi chuỗi; chuyển cá nhân > 30% khoản vay → vàng. Cảnh báo sớm: doanh số thấp, điểm cửa hàng, số dư thấp trước kỳ trả, tra cứu mới, FATE xấu đi, chuyển lớn ra cá nhân. Báo cáo trạng thái hằng ngày cho ngân hàng (`bank_report`).

**Giai đoạn 7–8 – thu nợ, quá hạn.** Nhắc trước 7 và 1 ngày. Ngày trả: lãi theo ngày thực tế trên dư nợ gốc, phân bổ lãi phạt → lãi → gốc, chia các ngân hàng theo tỷ lệ. Trả tối thiểu (trả góp, kỳ hạn ≥ 3, tối đa 2 kỳ liền; gốc hoãn chia đều các kỳ sau). 3 ngày ân hạn rồi lãi phạt 1,5 × lãi (≤ 24%). Quá hạn 30 ngày → báo trung tâm tín dụng, ghi nhóm ngân hàng nắm ≥ 2/3 dư nợ quyết định. Trả trước không phí, chỉ trả lãi số ngày đã dùng. `simulate-advance` cho thời gian trôi trong demo.

**Giai đoạn 9–10 – tất toán, vay lại.** Trả hết → `closed`, báo trung tâm tín dụng, trả hạn mức ngân hàng, Agent 5 được báo; người vay đổi được tài khoản nhận tiền hàng. Vay lại dùng lịch sử với BuoyUp (nhóm 1 hoặc 4).

## 3. Tệp đã đổi

- Mới: `app/banks/syndicate.py`, `app/agents/contract.py`, `tests/lc.py`, `tests/test_loan_circle.py`, `Frontend/giaodien/van-ban/*.html`, tài liệu này.
- Viết lại: `app/core/algorithm.py`, `app/agents/agent1_verify.py`, `app/agents/agent4_disburse.py`, `app/core/flow.py` (B1, B3–B9, B12 vòng duyệt, B11 lịch trả), `Frontend/src/nguoi-ban/workspace-v4.js`.
- Sửa: `params.py` (product, revenue, repay, syndicate, contract), `consent.py`, `sources.py`, `profiles.py` (tỷ lệ nợ tính trên doanh thu thuế), `agent2_advise.py`, `agent3_control.py` (POL-02/04/05/07, cổng, `approve` → bộ điều phối), `legal.py` (`rules-v1.2`), `stress.py`, `agent4_llm.py`, `agent5_postaudit.py`, `seed.py`, các API `applications`, `loans`, `banks`, `views`, `officer`; `chain_remote.py`, `chain.py` (loại bản ghi mới); quản trị `admin-v4.js`, ngân hàng `bank.js`, `api.js`; `API_CONTRACT_V4.md`, `HANDOVER.md`.
- Bỏ: `agent4_signoff.py` và `/v4/bank/approvals` (ngân hàng duyệt ở vòng song song), `/accept`, `/accept-smaller`, trạng thái `approved`/`smaller_offer`, mô hình chia B12 bằng mô hình ngôn ngữ, trích theo tỷ lệ mỗi lần tiền về.

## 4. Tham số tự đặt (cần đội duyệt, nhãn `[Đặt tay]`)

Hạn mức tối thiểu 10.000; hệ số trần nhóm 3,0/1,5/0,5/0; bước 70%/50%; kỳ đầu cách giải ngân ≥ 15 ngày; ngày trả ≤ 28; ngưỡng ảnh doanh thu 15%/30% và thưởng +5%; 3 ngày ân hạn; lãi phạt 1,5×; nhắc 7 và 1 ngày; chuyển cá nhân > 30%; đọc hợp đồng 20 giây; chính sách mô phỏng từng ngân hàng (thời gian trả lời, ngành loại trừ, ngân sách, vốn cấp một) trong `seed.py`.

## 5. Còn để ngỏ

- Quyết định của ngân hàng là mô phỏng theo chính sách (`bank_decides`); triển khai thật thay bằng lời gọi hệ thống ngân hàng.
- Agent 5 đo "tỷ lệ đạt dự báo" bằng tiền về tài khoản kinh doanh trên dự báo tháng × số tháng quan sát.
- Demo artifact đã chia sẻ trước đây phản ánh mô hình cũ; cần dựng lại từ dữ liệu mới.
