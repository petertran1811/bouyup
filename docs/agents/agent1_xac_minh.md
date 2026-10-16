# Agent 1 · Xác minh

> **Cập nhật 14/10/2026 (loan circle):** Agent 1 không còn đọc dòng tiền các tài khoản ngân hàng: doanh thu lấy từ thuế (`pull_revenue`), thêm ảnh doanh thu tự nộp (`verify_statements`), loại người vay phải khớp đăng ký, ba ô đồng ý ký bằng khuôn mặt hoặc OTP, lịch sử với BuoyUp (`network_history`). Bỏ cờ RISK_INFLOW_GAP, RISK_PASS_THROUGH, RISK_UNDECLARED_STORE. Chi tiết: `LOAN_CIRCLE_CHANGES.md`. Khi đặc tả dưới đây mâu thuẫn với loan circle, code theo loan circle.


> Cửa hàng có thật không, lập lâu chưa, doanh số có thật và tốt không, có gian lận không. Không bàn chuyện tiền.
> **Phiên bản 3 (12/10/2026): không kết nối cửa hàng, không nộp hồ sơ. Chỉ phục vụ người bán trên sàn thương mại điện tử.**

## 0. Tóm tắt

Agent 1 xác minh người bán **mà không cần kết nối vào cửa hàng và không cần
người bán nộp giấy tờ**. Người bán chỉ dán đường link cửa hàng, quét CCCD và
khuôn mặt, ký một màn hình ủy quyền; vay Tầng 2 thì điền thêm một biểu mẫu
kế hoạch có sẵn giá trị gợi ý.

Ý chính: **không hỏi sàn, mà nhìn vào nơi giấy phép và tiền để lại dấu vết.**

| Câu hỏi | Trả lời bằng |
|---|---|
| Cửa hàng có tồn tại không | Thông tin giấy phép mà sàn buộc phải công khai trên trang cửa hàng, đối chiếu với hệ thống đăng ký doanh nghiệp quốc gia |
| Cửa hàng lập lâu chưa | Ngày đầu tiên tiền thanh toán từ sàn về tài khoản người bán |
| Doanh số có thật và tốt không | Tiền thanh toán từ sàn thực về tài khoản 24 tháng, đối chiếu doanh thu khai thuế |

Nguyên tắc giữ nguyên: **mô hình ngôn ngữ điều phối và giao tiếp; mọi phán
quyết "thật hay giả" là kết quả của công cụ cố định.**

### Thay đổi qua các phiên bản

| | Phiên bản 1 | Phiên bản 2 | Phiên bản 3 |
|---|---|---|---|
| Cách lấy dữ liệu cửa hàng | Người bán xuất file và nộp | Kết nối cửa hàng qua ủy quyền của sàn | Không lấy dữ liệu trong cửa hàng; dùng dữ liệu công khai và dòng tiền |
| Người bán làm gì | Nộp 6 loại giấy (Tầng 1), thêm 9 loại (Tầng 2) | 3 thao tác, Tầng 2 thêm biểu mẫu | Như phiên bản 2, thay "kết nối cửa hàng" bằng "dán link cửa hàng" |
| Kiểm đơn có thật | Người bán nộp mã vận đơn, tra hãng vận chuyển | Lấy mã vận đơn từ sàn, tra hãng | Không có mã vận đơn; phát hiện thổi đơn qua dòng tiền ra |
| Rủi ro kết nối (pháp lý 断直连, điều khoản sàn, bảo mật mã truy cập) | Không có | Có | Không có |

## 1. Phạm vi phục vụ

| Điều kiện | Kiểm bằng | Lý do |
|---|---|---|
| Cửa hàng trên sàn được hỗ trợ: Douyin, Taobao/Tmall, JD, Pinduoduo, Kuaishou | Tên miền của link; đối tác chuyển tiền trong dòng tiền là công ty thanh toán của sàn đó | Mỗi sàn có trang công khai và công ty thanh toán riêng |
| Tiền từ sàn về tài khoản ít nhất 12 tháng | `analyze_platform_inflows` | Dự báo B4 cần ít nhất một mùa cao điểm; Tầng 2 cần hai mùa |
| Chủ thể đăng ký tại Trung Quốc đại lục, đang hoạt động | `lookup_business_registry` | Định danh, tín dụng, thuế chỉ có ở đó |
| Không phục vụ: bán ngoại tuyến, cửa hàng dưới 12 tháng, chỉ bán qua mạng xã hội | | Không có dấu vết công khai và dòng tiền từ sàn để thay cho giấy tờ |

## 2. Người bán làm gì

| # | Thao tác | Tầng | Thay cho |
|---|---|---|---|
| 1 | **Dán link cửa hàng**, khai mọi cửa hàng đang bán (mỗi cửa hàng một link) | 1 và 2 | GPKD, file cửa hàng |
| 2 | **Quét CCCD và khuôn mặt**; bỏ qua nếu đã là khách WeBank đã xác thực | 1 và 2 | Bản chụp CCCD |
| 3 | **Ký một màn hình ủy quyền**, liệt kê từng nguồn và mục đích; kê khai các tài khoản nhận tiền hàng | 1 và 2 | Sao kê, giấy ủy quyền riêng |
| 4 | **Biểu mẫu kế hoạch** có giá trị gợi ý: sự kiện, mặt hàng và số lượng, giá dự kiến, nhà cung cấp, tồn kho, vốn tự có, có vay nơi khác không | chỉ 2 | Kế hoạch văn bản, hợp đồng nhà cung cấp, bảng kê |

Tầng 1 khoảng 3 phút, Tầng 2 khoảng 6 phút. Chỉ tải lên khi bị gắn cờ mà
không công cụ nào kiểm được (mục 6.6).

## 3. Nguồn dữ liệu

| Dữ liệu | Từ | Cần ủy quyền | Dùng ở |
|---|---|---|---|
| Tên chủ thể, số đăng ký trên trang cửa hàng | Trang công khai của cửa hàng (sàn buộc phải công khai theo Luật Thương mại điện tử, Điều 15) | Không, dữ liệu công khai | Định danh, tra đăng ký |
| Điểm đánh giá công khai, ngành hàng | Trang công khai của cửa hàng | Không | B6, kỳ thanh toán B9 |
| Chủ thể có thật, ngày đăng ký, trạng thái hoạt động | Hệ thống công khai thông tin tín dụng doanh nghiệp quốc gia (gsxt.gov.cn) | Không, dữ liệu công khai | Phạm vi, từ chối nếu đã bị thu hồi |
| Tiền về từ công ty thanh toán của sàn, theo ngày, 24 tháng; tiền ra | Nền tảng thông tin dòng tiền; giao dịch tại WeBank | Có | Tuổi cửa hàng, doanh số, B2, B4, B8, phát hiện thổi đơn |
| Doanh thu khai thuế, hóa đơn bán ra và mua vào, nhà cung cấp | Thuế, qua chương trình 银税互动 | Có | Đối chiếu doanh số, B3, B5, nhà cung cấp |
| Trễ hạn, nợ, số lần tra cứu | Tổ chức tín dụng thông tin | Có | B1, B6 |
| Điểm liên ngân hàng | FATE | Có | B6 |

**Không dùng:** dữ liệu trong cửa hàng (đơn hàng, vận đơn, đối soát, tỷ lệ
hoàn), mã truy cập cửa hàng, file người bán tự xuất.

### Đại lượng tính ra từ dòng tiền và thuế

| Đại lượng | Cách tính |
|---|---|
| Tuổi cửa hàng | Từ ngày đầu tiên có tiền của công ty thanh toán của sàn về tài khoản đã khai |
| Tiền thực nhận cùng chiến dịch năm trước | Tổng tiền từ sàn về trong cửa sổ sự kiện năm trước, cộng thêm kỳ thanh toán của sàn |
| Trung bình 2 mùa cao điểm | Trung bình hai cửa sổ sự kiện gần nhất |
| Tiền thực nhận bình quân tháng | Tổng 12 tháng ÷ 12 |
| Tăng trưởng 3 tháng | 3 tháng gần nhất ÷ cùng kỳ năm trước − 1, kẹp −30% đến +50% |
| Doanh số 20 ngày (đầu vào B2, Tầng 1) | Tiền từ sàn về 20 ngày gần nhất |
| Tỷ lệ hoàn hàng | Trung bình của ngành hàng `[Đặt tay]` vì không có dữ liệu trong cửa hàng |
| Tỷ lệ phí sàn | Biểu phí công khai của sàn theo ngành hàng |
| Biên lãi gộp | 1 − hóa đơn mua vào ÷ hóa đơn bán ra, 12 tháng |
| Tỷ lệ tiền hàng về tài khoản đã khai | Tiền từ sàn về các tài khoản đã khai ÷ doanh thu bán ra trên thuế cùng kỳ |

## 4. Nguyên tắc thiết kế và lý do

| Nguyên tắc | Lý do |
|---|---|
| Không kết nối cửa hàng | Tránh ba rủi ro: pháp lý (dữ liệu cửa hàng của hộ cá nhân có thể là thông tin cá nhân chịu 断直连), điều khoản của sàn (sàn có thể thu hồi quyền truy cập bất cứ lúc nào), và bảo mật (giữ mã truy cập cửa hàng của hàng nghìn người bán là mục tiêu tấn công) |
| Dùng tiền thật thay cho số liệu trên sàn | Doanh số trên sàn có thể bị thổi bằng đơn ảo (刷单); tiền về tài khoản là tiền thật. Các khối B4, B8 vốn đã tính theo tiền thực nhận, nên đây là đầu vào đúng nhất |
| Đối chiếu dòng tiền với doanh thu khai thuế | Hai nguồn độc lập, do hai cơ quan khác nhau giữ. Lệch nhiều là dấu hiệu tiền hàng đi qua tài khoản chưa khai, tức WeBank không thấy và không trích nợ được |
| Dùng thông tin công khai bắt buộc | Thông tin giấy phép trên trang cửa hàng là nghĩa vụ công khai của người bán; tra cứu đăng ký doanh nghiệp là dịch vụ công. Không cần ủy quyền, không vướng điều khoản. Chỉ đọc đúng trang người bán dán, một lần mỗi hồ sơ |
| Không đọc văn bản gốc; phán quyết do công cụ | Giữ từ phiên bản 1: chống tiêm lệnh, tách người xác minh khỏi người đề xuất |
| Chưa ủy quyền thì không tra dữ liệu có ủy quyền | Luật Bảo vệ thông tin cá nhân; tra cứu tín dụng cần đồng ý riêng |

## 5. Các bước

| Bước | Làm thế nào | Ai | Đầu ra |
|---|---|---|---|
| 1 · Đọc link | `lookup_public_store(url)`: sàn, tên chủ thể, số đăng ký, điểm, ngành hàng | Code | Thông tin công khai |
| 2 · Tra đăng ký | `lookup_business_registry(reg_no)`: có thật, đang hoạt động, ngày đăng ký | Code | Đã thu hồi hoặc giải thể → `POL_ENTITY_INACTIVE` |
| 3 · Định danh | `verify_identity()`: khuôn mặt ↔ CCCD ↔ chủ thể trên trang cửa hàng ↔ chủ tài khoản đã khai | Code | Lệch → `LAW_ID_MISMATCH` |
| 4 · Ủy quyền | `request_consent(scope)` một màn hình; hash lên chuỗi | Code | `consent_id` |
| 5 · Dòng tiền | `analyze_platform_inflows(accounts)`: chuỗi tiền về theo ngày từ công ty thanh toán của sàn, ngày đầu tiên, tiền ra | Code | Tuổi cửa hàng, doanh số; dưới 12 tháng → `POL_OUT_OF_SCOPE` |
| 6 · Thuế, tín dụng, FATE | `pull_tax_data`, `get_credit_report`, `get_interbank_score`, `link_entities` | LLM gọi, code trả kết quả | Kết quả công cụ |
| 7 · Biểu mẫu (Tầng 2) | Code điền giá trị gợi ý; người bán sửa khi khác | Code, LLM trả lời thắc mắc | Kế hoạch có cấu trúc |
| 8 · Tính và gắn cờ | `derive_financials`; code áp bảng cờ | Code | Đại lượng, cờ |
| 9 · Xử lý cờ | LLM hỏi một câu chọn sẵn; công cụ kiểm theo câu trả lời; chỉ code đổi trạng thái | Code và LLM | Cờ `resolved_by_check` · `explained_unverified` · `open` |
| 10 · Kết luận | Mã từ chối cứng → `REJECTED`; ngoài phạm vi → `OUT_OF_SCOPE`; cờ `open` quá 3 ngày `[Đặt tay]` → `ESCALATED`; còn lại `VERIFIED`; hash lên Nhật ký kiểm toán | Code | Biên bản xác minh |

## 6. Các tác vụ: làm gì, vì sao, làm thế nào

### 6.1 Cửa hàng có tồn tại không

- **Vì sao cần.** Chặn hồ sơ dựng cửa hàng giả hoặc mượn cửa hàng người khác.
- **Làm thế nào.** Đọc phần thông tin giấy phép trên trang cửa hàng (người bán
  trên sàn phải công khai liên tục trên trang chủ); tra số đăng ký trên hệ
  thống đăng ký doanh nghiệp; khớp tên chủ thể với CCCD và chủ tài khoản nhận
  tiền. Nếu đội muốn tránh cả việc đọc trang, người bán nhập số đăng ký, công
  cụ tra hệ thống đăng ký; cửa hàng vẫn được xác nhận gián tiếp qua dòng tiền
  từ công ty thanh toán của sàn.
- **Ví dụ.**

```json
{"tool": "lookup_public_store", "input": {"url": "https://haohuo.jinritemai.com/…/shop?id=58812"},
 "output": {"platform": "douyin", "entity_name": "Hộ kinh doanh Lâm Lan", "reg_no": "92440106MA9…", "rating": 4.6, "category": "women_apparel"}}
{"tool": "lookup_business_registry", "input": {"reg_no": "92440106MA9…"},
 "output": {"exists": true, "status": "active", "registered": "2023-05-18", "type": "individual_business"}}
```

### 6.2 Cửa hàng lập lâu chưa

- **Vì sao cần.** Điều kiện 12 tháng và hai mùa cao điểm. Ngày đăng ký chủ thể
  không đủ, vì chủ thể có thể đăng ký từ lâu nhưng mới mở cửa hàng.
- **Làm thế nào.** Ngày đầu tiên có tiền từ công ty thanh toán của sàn về tài
  khoản đã khai. Kiểm thêm tiền về đều qua các tháng, không phải vài khoản lẻ.
- **Ví dụ.** Tiền Douyin về lần đầu ngày 2/8/2024; 26 tháng có tiền về; đã qua
  hai mùa 11/11 năm 2024 và 2025.

### 6.3 Doanh số có thật và tốt không

- **Vì sao cần.** Đầu vào chính của Tầng 1 (B2) và Tầng 2 (B4, B8).
- **Làm thế nào.** Chuỗi tiền về theo ngày từ công ty thanh toán của sàn;
  tính các đại lượng ở mục 3. Đối chiếu với doanh thu bán ra trên thuế cùng kỳ.
- **Ví dụ.**

```json
{"tool": "analyze_platform_inflows", "output": {
  "first_inflow": "2024-08-02", "months_with_inflow": 26,
  "monthly_avg_12m": 166700, "last_campaign": 300000, "two_peak_avg": 330000,
  "growth_3m": 0.20, "inflow_20d": 111100,
  "to_declared_accounts_vs_tax_sales": 0.87,
  "pass_through": {"share_to_individuals_24h": 0.04, "distinct_individuals": 6}}}
```

### 6.4 Phát hiện thổi đơn khi không có vận đơn

- **Vì sao cần.** Mất mã vận đơn là mất cách kiểm đơn ảo trực tiếp. Nhưng thổi
  đơn để lại dấu vết trên dòng tiền: tiền từ sàn về rồi nhanh chóng chuyển ra
  cho nhiều cá nhân (trả lại cho người mua ảo).
- **Làm thế nào.** `analyze_platform_inflows` tính tỷ lệ tiền từ sàn được
  chuyển ra cho cá nhân trong 24 giờ và số cá nhân nhận. Vượt 15% và trên 20
  người `[Đặt tay]` → `RISK_PASS_THROUGH`.
- **Ví dụ.** Người bán B: 38% tiền Douyin về được chuyển cho 214 tài khoản cá
  nhân trong ngày → cờ; người bán chọn "trả hoa hồng cho người livestream";
  không công cụ nào kiểm được → `explained_unverified`, không duyệt tự động.

### 6.5 Đối chiếu thuế, tín dụng, FATE, nhà cung cấp

Như phiên bản trước: hóa đơn mua vào qua 银税互动 cho giá nhập và nhà cung
cấp; báo cáo tín dụng; điểm FATE; nhóm liên kết giữa người bán và nhà cung cấp.

### 6.6 Bảng cờ: hỏi trước, tải lên sau cùng

| Mã | Bật khi | Agent 1 hỏi | Đóng bằng kiểm tra khi |
|---|---|---|---|
| `RISK_INFLOW_GAP` | tiền từ sàn về tài khoản đã khai < 95% doanh thu bán ra trên thuế `[Đặt tay]` | "Phần tiền hàng còn lại về tài khoản nào?" | Người bán khai và ủy quyền thêm tài khoản; `analyze_platform_inflows` trên tài khoản mới nâng tỷ lệ ≥ 95%. Vẫn phạt hạ 1 hạng `[Đặt tay]` vì khai thiếu từ đầu |
| `RISK_PASS_THROUGH` | > 15% tiền từ sàn chuyển cho > 20 cá nhân trong 24 giờ `[Đặt tay]` | "Các khoản chuyển này là gì?" Lương · hoa hồng · khác | Lương: có trên kê khai thuế thu nhập; còn lại `explained_unverified` |
| `RISK_SALES_SPIKE` | tháng gần nhất > 3 × trung bình 6 tháng `[Đặt tay]` | "Vì sao tăng?" | Hóa đơn bán ra cho doanh nghiệp (đơn sỉ) giải thích được phần tăng; còn lại `explained_unverified` |
| `RISK_UNDECLARED_STORE` | có tiền từ công ty thanh toán của sàn khác, hoặc kênh bán trên thuế chưa khai | "Chị còn bán ở kênh khác?" | Khai thêm link cửa hàng |
| `RISK_PRICE_DEVIATION` | giá khai > 1,2 × giá hóa đơn `[Đặt tay]` | không hỏi | Tự đóng: B3 dùng giá hóa đơn |
| `RISK_INVENTORY_HIGH` | tồn kho khai > 1,5 × ước tính từ hóa đơn `[Đặt tay]` | "Sửa số hay giữ?" | Sửa thì tính lại; giữ thì lúc này mới đề nghị tải lên ảnh kho hoặc phiếu nhập |
| `DATA_SOURCE_GAP`, `DATA_PARTNER_MISSING` | một nguồn hoặc FATE không trả lời | không hỏi | Không đóng; cổng không duyệt tự động |
| `LAW_ID_MISMATCH` | người, chủ thể, chủ tài khoản không khớp | | Từ chối |
| `POL_ENTITY_INACTIVE` | chủ thể bị thu hồi hoặc đã giải thể | | Từ chối |
| `POL_OUT_OF_SCOPE` | sàn không hỗ trợ, tiền từ sàn chưa đủ 12 tháng | | Ngoài phạm vi, nói rõ khi nào đủ |
| `RISK_SUPPLIER_LINKED` | nhà cung cấp cùng nhóm liên kết | | Loại nhà cung cấp, chọn nhà khác một lần |
| `POL_ACTIVE_NPL` | đang nợ xấu | | Từ chối |

## 7. Bộ công cụ

| Công cụ | Trả về | Nguồn | Demo |
|---|---|---|---|
| `lookup_public_store` | sàn, chủ thể, số đăng ký, điểm, ngành | trang công khai của cửa hàng | dữ liệu tổng hợp |
| `lookup_business_registry` | có thật, trạng thái, ngày đăng ký | hệ thống đăng ký doanh nghiệp | mock |
| `verify_identity` | khớp người, chủ thể, chủ tài khoản | định danh từ xa của WeBank | mock |
| `request_consent` | `consent_id`, tx | Nhật ký kiểm toán / Sổ ủy quyền | FISCO 4 nút |
| `analyze_platform_inflows` | chuỗi tiền về, ngày đầu, tiền ra | nền tảng dòng tiền, WeBank | dữ liệu tổng hợp |
| `pull_tax_data` | doanh thu, hóa đơn vào ra, nhà cung cấp | 银税互动 | dữ liệu tổng hợp |
| `derive_financials` | đại lượng ở mục 3 | code | như thật |
| `get_credit_report` | trễ hạn, nợ, tra cứu, nợ xấu | tổ chức tín dụng thông tin | mock |
| `get_interbank_score` | điểm 1–5, `run_id` | FATE | FATE standalone |
| `link_entities` | nhóm liên kết | union-find | như thật |
| `extract_document` | trường cố định | Qwen3-VL không có công cụ | chỉ cho ngoại lệ |

## 8. Biên bản xác minh

```json
{
  "application_id": "APP-2026-1011-0042", "tier": 2, "scope": "in", "consent_id": "CS-7f3a",
  "store": {"platform": "douyin", "url": "…shop?id=58812", "entity": "Hộ kinh doanh Lâm Lan",
            "registry": {"status": "active", "registered": "2023-05-18"}, "rating_public": 4.6},
  "identity": {"face_match": true, "entity_match": true, "account_owner_match": true},
  "inflows": {"first_inflow": "2024-08-02", "months": 26, "monthly_avg_12m": 166700,
              "last_campaign": 300000, "two_peak_avg": 330000, "growth_3m": 0.20, "inflow_20d": 111100,
              "declared_vs_tax": {"before": 0.87, "after_followup": 1.00}},
  "tax": {"invoice_unit_price_3m": 62, "gross_margin": 0.40},
  "plan": {"event": "11.11", "qty": 5000, "declared_unit_price": 80, "supplier": "SUP-0091",
           "inventory": 40000, "own_capital": 60000, "other_loans": 0},
  "credit": {"late_12m": 0, "active_npl": false},
  "interbank_score": {"value": 3, "source": "fate"},
  "flags": [
    {"code": "RISK_INFLOW_GAP", "status": "resolved_by_check", "evidence_tool_call": "TC-121", "penalty": "downgrade_1"},
    {"code": "RISK_PRICE_DEVIATION", "status": "resolved_by_check", "evidence_tool_call": "TC-112"}
  ],
  "uploads": [],
  "state": "VERIFIED",
  "llm_notes": "Người bán cho biết 13% tiền hàng về tài khoản ở ngân hàng khác; đã khai và ủy quyền thêm.",
  "record_hash": "sha256:…", "audit_tx": "0x…"
}
```

## 9. Quyền hạn

| Không được | Được |
|---|---|
| kết nối vào cửa hàng hay giữ mã truy cập cửa hàng | đọc trang công khai người bán đã dán, một lần |
| đọc văn bản gốc tài liệu | chọn thứ tự gọi công cụ trong danh sách bắt buộc |
| tạo, xóa, đổi trạng thái cờ | hỏi người bán theo danh sách câu hỏi của từng cờ |
| tính, sửa, đề xuất con số tiền | đề nghị khai thêm cửa hàng hoặc tài khoản |
| tra dữ liệu có ủy quyền khi chưa có ủy quyền | đề nghị tải lên khi không còn công cụ nào kiểm được |
| đòi giấy tờ ngoài danh sách cho phép | ghi `llm_notes` |

## 10. Xử lý lỗi

| Lỗi | Xử lý |
|---|---|
| Trang cửa hàng không đọc được | Người bán nhập số đăng ký; tra hệ thống đăng ký |
| Nền tảng dòng tiền không trả chi tiết theo đối tác | Chỉ dùng giao dịch tại WeBank và doanh thu thuế; bật `DATA_SOURCE_GAP`; khuyến khích nhận tiền hàng qua tài khoản WeBank |
| Thuế không trả dữ liệu | Giá nhập dùng giá khai × 0,85 `[Đặt tay]`; `DATA_SOURCE_GAP` |
| Mô hình ngừng | Bước 1–5 và 8 là code nên vẫn chạy; hồ sơ dừng ở bước hỏi |
| FATE không trả lời | `fallback`, `DATA_PARTNER_MISSING` |

## 11. Ví dụ trọn vẹn: chị Lan

1. Chị dán link cửa hàng Douyin. Trang công khai: chủ thể "Hộ kinh doanh Lâm
   Lan", số đăng ký, điểm 4,6, thời trang nữ. Hệ thống đăng ký: đang hoạt động.
2. Quét CCCD và khuôn mặt: khớp chủ thể. Chị khai một tài khoản nhận tiền
   hàng tại WeBank, ký một màn hình ủy quyền; hash lên chuỗi.
3. Dòng tiền: tiền Douyin về lần đầu tháng 8/2024, 26 tháng, đã qua hai mùa →
   đủ Tầng 2. Mùa 11/11 năm trước 300.000; hai mùa trung bình 330.000; bình
   quân tháng 166.700; tăng trưởng 20%. Tiền ra cho cá nhân 4%: bình thường.
4. Thuế: giá nhập áo khoác 3 tháng 62 tệ; biên lãi gộp 40%; doanh thu bán ra
   cao hơn tiền về tài khoản đã khai, tỷ lệ 87% → `RISK_INFLOW_GAP`.
5. Biểu mẫu Tầng 2 có sẵn gợi ý; chị điền 5.000 áo, giá 80, tồn kho 40.000,
   vốn tự có 60.000. Giá 80 > 74,4 → `RISK_PRICE_DEVIATION`, tự đóng.
6. LLM hỏi phần tiền hàng còn lại về đâu. Chị chọn "tài khoản ở ngân hàng
   khác", khai và ủy quyền thêm. `analyze_platform_inflows` trên tài khoản đó:
   đủ 13% còn lại. Cờ `resolved_by_check`, phạt hạ 1 hạng.
7. Biên bản `VERIFIED`, `uploads` rỗng. Bảng điểm ra B, hạ 1 hạng thành C;
   các số phía sau không đổi: 139.900 tệ, 12%, trích 63%.

## 12. Kiểm thử và chỉ số

| Ca | Kết quả đúng |
|---|---|
| Link cửa hàng của người khác | `LAW_ID_MISMATCH` |
| Chủ thể đã bị thu hồi | `POL_ENTITY_INACTIVE` |
| Tiền từ sàn mới 8 tháng | `OUT_OF_SCOPE`, nói rõ khi nào đủ |
| Hồ sơ sạch Tầng 1 | `VERIFIED`, không câu hỏi, `uploads` rỗng |
| Tiền hàng về tài khoản chưa khai | `RISK_INFLOW_GAP`; khai thêm thì đóng bằng kiểm tra |
| Thổi đơn, tiền chuyển ra hàng trăm cá nhân | `RISK_PASS_THROUGH`, không duyệt tự động |
| Có tiền từ Pinduoduo nhưng chỉ khai Douyin | `RISK_UNDECLARED_STORE` |
| Nền tảng dòng tiền không có chi tiết đối tác | `DATA_SOURCE_GAP` |
| Chưa ủy quyền | Chỉ bước 1–3 chạy (dữ liệu công khai và định danh) |

Chỉ số: số thao tác của người bán; tỷ lệ hồ sơ có `uploads` rỗng (mục tiêu
trên 90%); thời gian đến biên bản; tỷ lệ bỏ dở; tỷ lệ ca thổi đơn bị bắt
trong bộ dữ liệu tổng hợp có cài sẵn ca xấu.

## 13. Cái mất và câu hỏi mở

| Mất so với phiên bản 2 | Ảnh hưởng | Bù |
|---|---|---|
| Vận đơn | Không kiểm trực tiếp đơn ảo | `RISK_PASS_THROUGH` trên dòng tiền ra |
| Tỷ lệ hoàn, số đơn của chính cửa hàng | B2, B6 kém chính xác | Trung bình ngành; bỏ khỏi B6 |
| Tiền đơn đã bán nhưng sàn chưa trả | Tầng 1 tính theo tiền đã về 20 ngày, không theo tiền đang chờ | Giữ hệ số 0,80 và chiết khấu nhóm |
| Phí sàn chính xác | B5 kém chính xác | Biểu phí công khai |

Câu hỏi cho đội:
- Nền tảng thông tin dòng tiền có trả chi tiết theo đối tác chuyển tiền không? Nếu không, nguồn chính là giao dịch tại WeBank, cần yêu cầu tài khoản nhận tiền hàng ở WeBank.
- 银税互动 có mở cho hộ kinh doanh cá nhân không?
- Đọc trang công khai của cửa hàng tự động có vướng điều khoản sàn không? Nếu có, dùng phương án người bán nhập số đăng ký.

## 14. Nguồn

**Nội bộ**
- `docs/SellerGraph_core_tech_v4.html`: tầng dữ liệu, bảng đại lượng, B1–B11, mục `#agent-1`.
- Tài liệu gốc "SellerGraph, toàn cảnh mô hình", 28.09.2026 (theo trích dẫn trong v4): kỳ thanh toán Douyin, tỷ lệ ứng 0,80.
- `src/sellergraph/services/risk.py`, `fate/pipeline/predict_test.py`, `fate/SCORECARD_WOE_README.md`.

**Quy định và dịch vụ công**
- Luật Thương mại điện tử nước CHND Trung Hoa (电子商务法), 2018, hiệu lực 2019, Điều 15: người kinh doanh thương mại điện tử phải công khai liên tục thông tin giấy phép kinh doanh ở vị trí nổi bật trên trang chủ.
- Hệ thống công khai thông tin tín dụng doanh nghiệp quốc gia (国家企业信用信息公示系统), gsxt.gov.cn.
- Luật Bảo vệ thông tin cá nhân (个人信息保护法), 2021, Điều 13, 14, 24.
- 征信业务管理办法, Ngân hàng Nhân dân Trung Quốc, 2021: cơ sở của 断直连, lý do tránh kết nối cửa hàng.
- Chương trình 银税互动, Tổng cục Thuế Nhà nước và cơ quan quản lý ngân hàng, từ 2015.

**Nghiên cứu và chuẩn**
- Greshake và cộng sự, 2023, arXiv:2302.12173; OWASP Top 10 for LLM Applications, LLM01.

Nguồn ngoài cần đội mở và đối chiếu nguyên văn trước khi trích trong bài nộp.
