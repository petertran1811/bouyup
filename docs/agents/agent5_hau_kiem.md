# Agent 5 · Hậu kiểm

> **Cập nhật 14/10/2026 (loan circle):** Agent 5 đo tỷ lệ đạt dự báo bằng tiền hàng về tài khoản kinh doanh WeBank trên dự báo tháng × số tháng quan sát; đề xuất `flags.inflow_gap` thay bằng `revenue.statement_bonus`. Chi tiết: `LOAN_CIRCLE_CHANGES.md`. Khi đặc tả dưới đây mâu thuẫn với loan circle, code theo loan circle.


> Nhìn lại để cả hệ thống tốt lên. Chỉ đề xuất; người duyệt, thử nghiệm rồi mới áp dụng.

## 0. Tóm tắt

Agent 5 không xử lý hồ sơ nào. Nó nhìn toàn bộ danh mục theo chu kỳ: so quyết
định lúc duyệt với kết quả trả nợ thật, theo dõi nợ xấu của nhóm duyệt tự
động, phát hiện trôi dữ liệu, đo xem Agent 2 và Agent 3 có còn hoạt động như
thiết kế không, chạy bộ tấn công thử định kỳ, và viết đề xuất cải tiến cho
hội đồng rủi ro. Agent 5 không có quyền ghi vào cấu hình, không bật tắt luồng
tự động; công tắc tắt tự động là code.

Lưu ý: bản v4 chưa có mục chi tiết cho Agent 5. Tài liệu này là thiết kế đầu
tiên dựng từ khối Agent 5 và phần hệ số thận trọng trong v4. Tham số mới gắn
nhãn `[Đặt tay]`.

## 1. Vị trí trong luồng

```
Nhật ký kiểm toán + Sổ khoản vay + tool_calls + kết luận Agent 2/3
                         │ (chỉ đọc)
                         ▼
                     Agent 5 ──báo cáo, đề xuất──► hội đồng rủi ro ──duyệt──► Bảng tham số phiên bản mới (hash lên chuỗi)
                         │
                         └──ca tấn công mới──► bộ kiểm thử của Agent 1, 2, 3

code giám sát nợ xấu ──vượt ngưỡng cứng──► tắt duyệt tự động (không qua Agent 5)
```

| | Nội dung |
|---|---|
| Đầu vào | Toàn bộ dữ liệu đã có ủy quyền mục đích "cải tiến mô hình"; nhật ký mọi agent |
| Đầu ra | Báo cáo tháng, báo cáo quý, đề xuất thay đổi, ca kiểm thử mới |
| Không có | Quyền ghi Bảng tham số, quyền đổi trạng thái khoản vay, quyền bật tắt luồng tự động |

## 2. Nguyên tắc thiết kế và lý do

| Nguyên tắc | Lý do |
|---|---|
| Có một vai chuyên nhìn lại | Hướng dẫn quản trị rủi ro mô hình yêu cầu giám sát liên tục và phân tích kết quả (so dự báo với thực tế). Không ai nhìn lại thì ngưỡng đặt tay sai mãi vẫn sai |
| Chỉ đề xuất, người duyệt | Một agent tự đổi tham số của hệ thống đang cho vay là vòng lặp không có phanh. Thay đổi chính sách tín dụng là quyết định của hội đồng |
| Công tắc tắt tự động là code, không phải Agent 5 | Khi nợ xấu vượt ngưỡng cứng, phản ứng phải chắc chắn và tức thời, không phụ thuộc vào việc một mô hình có đọc đúng số không. Agent 5 cảnh báo sớm hơn ngưỡng cứng |
| Thử nghiệm song song trước khi áp dụng | Thay đổi được chạy ở chế độ bóng (tính cả hai phiên bản, chỉ dùng phiên bản cũ) để đo hậu quả trước khi ảnh hưởng người vay thật |
| Tấn công thử định kỳ | Phòng thủ chống tiêm lệnh và thao túng không phải làm một lần là xong; kẻ tấn công thay đổi cách làm. Kiểm thử đối kháng thường xuyên là thực hành được khuyến nghị cho hệ thống dùng mô hình ngôn ngữ |
| Đo độ độc lập của Agent 3 | Agent kiểm soát có thể dần trở thành con dấu cao su. Tỷ lệ bất đồng và tỷ lệ bị thuyết phục là cách duy nhất để biết |
| Chú ý thiên lệch chọn mẫu | Chỉ hồ sơ được duyệt mới có kết quả trả nợ; nhìn lại chỉ trên nhóm đó dễ đưa tới siết ngưỡng sai hướng |

## 3. Các tác vụ

### 3.1 So quyết định với kết quả

- **Làm gì.** Theo từng nhóm (tầng, hạng, nhóm khách, ngành, tháng duyệt), so
  dự báo lúc duyệt với kết quả: tỷ lệ trả đúng hạn, tỷ lệ quá hạn 30 ngày, tỷ
  lệ thiếu sàn, tiền thực nhận so với dự báo thận trọng.
- **Vì sao cần.** Đây là cách duy nhất biết bảng điểm, bảng lãi, hệ số thận
  trọng có đúng không. Hạng C mà nợ xấu cao hơn hạng D là dấu hiệu bảng điểm sai.
- **Làm thế nào.** `query_cohorts(dimensions, period)` là truy vấn SQL cố định
  trả bảng số; mô hình đọc bảng và viết nhận xét có tham chiếu từng ô.
- **Ví dụ** (số giả định):

| Hạng | Số khoản | Quá hạn 30 ngày | Tiền thực nhận ÷ dự báo thận trọng, trung vị |
|---|---|---|---|
| A | 120 | 0,8% | 1,21 |
| B | 210 | 1,9% | 1,12 |
| C | 180 | 3,9% | 1,04 |
| D | 60 | 3,3% | 0,98 |

> "Hạng D có tỷ lệ quá hạn thấp hơn hạng C (ô D-quá hạn, C-quá hạn). Với 60
> khoản ở hạng D, khoảng tin cậy rộng; đề nghị theo dõi thêm một quý trước khi
> đề xuất đổi ngưỡng hạng."

### 3.2 Theo dõi nợ xấu nhóm duyệt tự động

- **Làm gì.** Tính tỷ lệ quá hạn của các khoản duyệt tự động, so với ngưỡng
  cảnh báo và ngưỡng cứng.
- **Vì sao cần.** Duyệt tự động là nơi rủi ro lan nhanh nhất; nếu có lỗ hổng,
  nó lặp lại trên mọi hồ sơ.
- **Làm thế nào.** Code tính hằng ngày. Ngưỡng cứng `[Đặt tay]`: quá hạn 30
  ngày trên nhóm tự động > 4% → code tắt duyệt tự động, mọi hồ sơ mới vào kênh
  thủ công, ghi sự kiện lên chuỗi. Ngưỡng cảnh báo `[Đặt tay]`: > 3% hoặc
  tăng hai tháng liên tiếp → Agent 5 viết báo cáo phân tích gửi hội đồng.
- **Ví dụ.**

```json
{"date": "2027-01-31", "auto_cohort_dpd30": 0.031, "warn": 0.03, "hard": 0.04,
 "trend": [0.018, 0.024, 0.031], "status": "warn",
 "top_contributors": [{"segment": "tier2/group2/fashion", "dpd30": 0.058, "evidence_ref": "Q-cohort-77"}]}
```

### 3.3 Đề nghị chạy lại hệ số thận trọng

- **Làm gì.** Theo dõi tỷ lệ người bán đạt từ hệ số thận trọng × dự báo trở
  lên; thấp hơn 80% hai kỳ liên tiếp thì đề nghị chạy kiểm định ngược.
- **Vì sao cần.** Hệ số thận trọng quyết định trần dòng tiền, tức thường quyết
  định hạn mức. Đây là quy trình đã thiết kế trong v4.
- **Làm thế nào.** `run_backtest(industry, period)` là giải thuật cố định (5
  bước trong v4: lấy mẫu, đứng ở ngày trước chiến dịch, chạy B4, tính tỷ số,
  lấy phân vị 20%). Agent 5 gọi công cụ và viết báo cáo vì sao hệ số đổi.
- **Ví dụ.** Thời trang quý 1: 71% người bán đạt (dưới 80%) hai kỳ. Kiểm định
  ngược ra hệ số 0,64. Đề xuất: 0,70 → 0,66 (bước tối đa 0,04 mỗi quý
  `[Đặt tay]`), kèm bảng hồ sơ quý trước sẽ đổi hạn mức.

### 3.4 Phát hiện trôi dữ liệu

- **Làm gì.** So phân phối đặc trưng đầu vào và phân phối điểm tháng này với
  lúc thiết lập ngưỡng.
- **Vì sao cần.** Khi người nộp hồ sơ thay đổi (sàn mới, ngành mới, mùa vụ
  khác), ngưỡng cũ có thể không còn hợp; kết quả trả nợ thì đến chậm vài
  tháng, trôi dữ liệu thì thấy ngay.
- **Làm thế nào.** Chỉ số ổn định dân số (PSI) theo khoảng cho từng đặc trưng
  chính và cho điểm B6. PSI > 0,25 thì báo `[Tiền lệ thực hành]`.
- **Ví dụ.** PSI của tỷ lệ tiền hàng về tài khoản đã khai tháng 3 là 0,31:
  nhiều hồ sơ mới nhận tiền qua một ví điện tử chưa có trong nền tảng thông
  tin dòng tiền. Đề xuất: thêm nguồn đó, hoặc yêu cầu nhận tiền hàng qua
  tài khoản WeBank.

### 3.5 Đo hành vi của Agent 2 và Agent 3

- **Làm gì.** Theo dõi tỷ lệ bất đồng giữa Agent 2 và 3, tỷ lệ Agent 3 đổi ý ở
  pha 2, quy tắc nào hay bị viện dẫn, tỷ lệ số lạ trong tin nhắn Agent 2 trước
  lọc, tỷ lệ lời gọi công cụ không hợp lệ.
- **Vì sao cần.** Agent kiểm soát quá dễ dãi là rủi ro im lặng. Mô hình nền
  được nâng cấp cũng có thể đổi hành vi mà không ai nhận ra.
- **Làm thế nào.** Truy vấn cố định trên `tool_calls`, kết luận pha 1 và pha
  2. Ngưỡng báo `[Đặt tay]`: bất đồng < 2% hoặc > 30% trong một tháng; đổi ý
  từ nghiêm sang nhẹ > 50% số lần bất đồng.
- **Ví dụ.**

```json
{"month": "2027-01", "n": 812, "disagree_rate": 0.011, "phase2_loosen_rate": 0.67,
 "flag": "Agent 3 bất đồng quá ít và khi bất đồng thì phần lớn bị thuyết phục; đề nghị chạy bộ ca đối kháng"}
```

### 3.6 Tấn công thử định kỳ

- **Làm gì.** Chạy bộ ca tấn công vào môi trường thử: tài liệu có lệnh ẩn,
  chat thao túng Agent 2, ghi chú nhắm vào Agent 3, lập luận hay nhưng sai, đổi
  tài khoản nhà cung cấp, cấu kết người bán với nhà cung cấp.
- **Vì sao cần.** Giám khảo chấm an toàn; người vay thật sẽ thử những thứ này.
  Mỗi ca thất bại là một lỗ hổng phải vá trước khi kẻ gian tìm ra.
- **Làm thế nào.** `run_redteam_suite(version)` chạy bộ ca cố định cộng ca mới
  do Agent 5 sinh từ mẫu (biến thể câu chữ, ngôn ngữ, vị trí trong tài liệu).
  Mọi ca chạy trên bản sao, không chạm dữ liệu thật. Kết quả so với đáp án:
  bị chặn hay không, chặn ở lớp nào.
- **Ví dụ** kết quả:

| Nhóm ca | Số ca | Bị chặn | Lớp chặn |
|---|---|---|---|
| Lệnh ẩn trong hóa đơn | 40 | 40 | trích xuất không có công cụ; cờ `RISK_INJECTION_SUSPECT` |
| Chat đòi số tiền | 30 | 30 | không có công cụ nhận số tiền |
| Ghi chú nhắm vào Agent 3 | 20 | 19 | RISK-06; 1 ca lọt pha 1, bị cổng chặn vì sàn |
| Lập luận hay nhưng sai | 25 | 22 | luật đổi ý; 3 ca Agent 3 nới nhưng code bác |
| Đổi tài khoản nhà cung cấp | 10 | 10 | `check_supplier_final` |

### 3.7 Viết đề xuất cải tiến

- **Làm gì.** Gom các phát hiện thành đề xuất có cấu trúc gửi hội đồng.
- **Vì sao cần.** Hội đồng cần biết: đổi gì, vì sao, ảnh hưởng ai, rủi ro nếu không đổi.
- **Làm thế nào.** `draft_proposal` theo mẫu cố định: tham số, giá trị cũ, giá
  trị mới, bằng chứng (tham chiếu truy vấn), kết quả chạy song song trên hồ sơ
  quý trước (bao nhiêu hồ sơ đổi quyết định, tổng hạn mức đổi bao nhiêu). Mọi
  con số trong đề xuất phải khớp đầu ra công cụ (kiểm tự động). Một agent phản
  biện, có thể là Agent 3 ở chế độ khác, viết lý do không nên đổi.

## 4. Bộ công cụ

| Công cụ | Trả về |
|---|---|
| `query_cohorts` | bảng chỉ số theo nhóm |
| `get_auto_cohort_npl` | tỷ lệ quá hạn nhóm tự động, xu hướng |
| `run_backtest` | hệ số thận trọng theo ngành |
| `compute_psi` | chỉ số ổn định theo đặc trưng |
| `get_agent_behavior_stats` | tỷ lệ bất đồng, đổi ý, số lạ, lời gọi lỗi |
| `run_redteam_suite` | kết quả từng ca |
| `shadow_run` | chạy song song phiên bản tham số mới trên hồ sơ cũ |
| `draft_proposal` | bản đề xuất chờ hội đồng |
| `add_test_case` | thêm ca vào bộ kiểm thử của agent tương ứng (chờ người duyệt) |

## 5. Quyền hạn

| Không được | Được |
|---|---|
| ghi Bảng tham số, bộ quy tắc | đọc mọi dữ liệu có ủy quyền cải tiến mô hình |
| bật tắt duyệt tự động | đề nghị tắt sớm hơn ngưỡng cứng |
| đổi trạng thái khoản vay | chạy kiểm định ngược, chạy song song |
| chạy tấn công thử trên dữ liệu thật | chạy tấn công thử trên bản sao |
| đọc dữ liệu không có ủy quyền cải tiến | đề xuất thêm ca kiểm thử |

## 6. Xử lý lỗi

| Lỗi | Xử lý |
|---|---|
| Truy vấn trả cỡ mẫu quá nhỏ | Báo "chưa đủ mẫu", không đề xuất |
| Mô hình ngừng | Truy vấn và công tắc vẫn chạy (code); báo cáo chờ |
| Số trong đề xuất không khớp đầu ra công cụ | Chặn đề xuất, sinh lại |
| Bộ tấn công thử có ca lọt | Báo ngay cho đội kỹ thuật, không đợi báo cáo tháng |

## 7. Ví dụ trọn vẹn: một quý sau khi ra mắt

1. Tháng 12: nhóm tự động quá hạn 1,8% → 2,4%. Bình thường.
2. Tháng 1: 3,1%, vượt ngưỡng cảnh báo. Agent 5 phân tích: đóng góp lớn nhất là
   Tầng 2, nhóm 2, thời trang (5,8%). Tiền thực nhận ÷ dự báo thận trọng trung
   vị của nhóm này là 0,93, thấp hơn mức đủ trả.
3. Agent 5 gọi `run_backtest(fashion)`: hệ số 0,64. Đề xuất 0,70 → 0,66 kèm
   `shadow_run`: 14% hồ sơ thời trang quý trước sẽ giảm hạn mức, trung bình 6%.
4. Đồng thời `get_agent_behavior_stats` cho thấy Agent 3 bất đồng 1,1%, nới ở
   pha 2 trong 67% lần bất đồng. Agent 5 chạy bộ ca đối kháng: 3/25 ca Agent 3
   nới sai, đều bị code bác. Đề xuất: xem lại lời nhắc của Agent 3.
5. Hội đồng duyệt hệ số 0,66; Bảng tham số lên phiên bản mới, hash lên chuỗi.
   Lời nhắc của Agent 3 được sửa, chạy lại bộ ca, rồi mới đưa vào dùng.
6. Tháng 2: 2,7%. Không chạm ngưỡng cứng; duyệt tự động không bị tắt.

## 8. Kiểm thử và chỉ số

| Ca | Kết quả đúng |
|---|---|
| Nợ xấu nhóm tự động vượt ngưỡng cứng | Code tắt tự động, không chờ Agent 5 |
| Cỡ mẫu ngành dưới 30 | Không đề xuất hệ số mới |
| Đề xuất có số không khớp truy vấn | Bị chặn |
| Agent 5 thử ghi Bảng tham số | Không có công cụ; bị từ chối ở tầng quyền |
| Bộ tấn công thử | Chạy trên bản sao, không có ghi vào dữ liệu thật |

Chỉ số: thời gian từ khi một nhóm xấu đi đến khi có báo cáo; tỷ lệ đề xuất
được hội đồng chấp nhận; số lỗ hổng tìm thấy trước khi xảy ra thật; độ phủ
của bộ tấn công thử.

## 9. Câu hỏi mở cho đội

- Ngưỡng cảnh báo 3% và ngưỡng cứng 4% quá hạn 30 ngày cho nhóm tự động có hợp không?
- Có làm dải thăm dò (duyệt một phần nhỏ hồ sơ ngay dưới ngưỡng) để giảm thiên lệch chọn mẫu không?
- Agent 5 có cần tự sinh ca tấn công mới, hay chỉ chạy bộ cố định cho bài nộp?

## 10. Nguồn

**Nội bộ**
- `docs/SellerGraph_core_tech_v4.html`: khối Agent 5, phần "Hệ số thận trọng lấy ở đâu" (kiểm định ngược 5 bước), cổng phê duyệt (tắt tự động khi nợ xấu vượt mức).
- `fate/SCORECARD_WOE_README.md`, mục chỉ số ổn định dân số.

**Quy định và hướng dẫn**
- Federal Reserve và OCC, SR 11-7, 2011: giám sát liên tục, phân tích kết quả, kiểm định ngược.
- NIST AI Risk Management Framework 1.0, 2023, NIST AI 100-1: chức năng Measure và Manage.
- Liên minh châu Âu, Quy định (EU) 2024/1689 (Đạo luật AI), Điều 72: giám sát sau khi đưa ra thị trường đối với hệ thống rủi ro cao.

**Nghiên cứu và thực hành**
- Ganguli và cộng sự, "Red Teaming Language Models to Reduce Harms", 2022, arXiv:2209.07858.
- OWASP Top 10 for LLM Applications, genai.owasp.org.
- Siddiqi, N., "Credit Risk Scorecards", Wiley, 2006: chỉ số ổn định dân số, thiên lệch chọn mẫu và suy luận cho hồ sơ bị từ chối.
