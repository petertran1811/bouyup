# Agent 4 · Giải ngân & Thu nợ

> **Cập nhật 14/10/2026 (loan circle):** Agent 4 không còn chia ngân hàng (tỷ lệ do vòng duyệt song song chốt: 40/30/30 hoặc 30/70) và không trích theo tỷ lệ mỗi lần tiền về. Giải ngân qua tài khoản trung gian tại WeBank; thu nợ vào ngày trả (lãi phạt → lãi → gốc, lãi theo ngày thực tế), trả tối thiểu, 3 ngày ân hạn rồi lãi phạt, quá hạn 30 ngày báo trung tâm tín dụng, trả trước không phí, giám sát chi tiêu tài khoản kinh doanh. Bỏ ký duyệt ngân hàng sau phê duyệt (`agent4_signoff`). Chi tiết: `LOAN_CIRCLE_CHANGES.md`. Khi đặc tả dưới đây mâu thuẫn với loan circle, code theo loan circle.


> Từ lúc người bán bấm chấp nhận tới khi tất toán.

## 0. Tóm tắt

Agent 4 lo ba việc sau phê duyệt: **giải ngân** một lần thẳng tới nhà cung
cấp đã kiểm, **thu nợ** theo dòng tiền bán hàng và giải thích từng lần trích,
và **giám sát** cam kết hằng ngày với cảnh báo xanh, vàng, đỏ. Số tiền giải
ngân, số tiền mỗi lần trích, thứ tự phân bổ và điểm cảnh báo đều do code và
hợp đồng thông minh tính. Agent 4 kích hoạt, theo dõi, giải thích, phân tích
nguyên nhân và soạn phương án; các quyết định nặng (đòi nợ trước hạn, tuyên
bố vỡ nợ, giãn nợ) chỉ khóa của cán bộ làm được trên chuỗi.

Lưu ý: bản v4 chưa có mục chi tiết cho Agent 4. Tài liệu này là thiết kế đầu
tiên, dựng từ các khối giải ngân, thu nợ, giám sát, B9, B11 và Sổ khoản vay
trong v4. Các tham số mới đều gắn nhãn `[Đặt tay]`.

## 1. Vị trí trong luồng

```
cổng phê duyệt ──approval──► người bán bấm chấp nhận ──► Agent 4 ──lệnh──► core banking ──tiền──► nhà cung cấp
                                                            │
                                         Sổ khoản vay (FISCO) ◄── nhà cung cấp ký nhận, công ty vận chuyển ghi vận đơn
                                                            │
sàn trả tiền hàng ──payout──► code trích theo tỷ lệ ──► Sổ khoản vay ──► Agent 4 gửi thông báo giải thích
                                                            │
                                     B11 hằng ngày ──điểm cảnh báo──► Agent 4 ──vàng: phân tích · đỏ: báo cán bộ
```

| | Nội dung |
|---|---|
| Đầu vào | Bản ghi phê duyệt (phương án, số tiền, tỷ lệ trích, ân hạn, sàn lũy kế, cam kết); sự kiện payout của sàn; điểm B11 hằng ngày |
| Đầu ra | Lệnh giải ngân; thông báo từng lần trích; báo cáo cảnh báo; bản nháp giãn nợ |
| Ghi chuỗi | Sổ khoản vay: khoản vay, lệnh giải ngân, xác nhận nhận tiền, vận đơn, từng lần trả, cảnh báo |

## 2. Nguyên tắc thiết kế và lý do

| Nguyên tắc | Lý do |
|---|---|
| Tiền đi thẳng tới nhà cung cấp, không qua người bán | Đây là hình thức "thanh toán ủy thác" (受托支付) của ngân hàng: ngân hàng trả thẳng cho đối tác giao dịch theo mục đích vay, để tiền vay không bị dùng sai mục đích. Với cho vay vốn nhập hàng, nó cũng biến khoản vay thành hàng hóa có thật |
| Số tiền giải ngân lấy từ bản ghi phê duyệt, Agent 4 không nhập | Bước chuyển tiền là bước gây thiệt hại trực tiếp nếu sai. Không có tham số số tiền thì không thể bị thao túng ở đây |
| Kiểm nhà cung cấp lần cuối ngay trước cú bấm | Thông tin nhà cung cấp có thể đổi giữa lúc duyệt và lúc giải ngân (đổi tài khoản nhận là kiểu lừa đảo phổ biến). Kiểm lại ngay trước khi chuyển đóng khe hở đó |
| Trả nợ bằng tỷ lệ cố định trên tiền hàng về | Mô hình trả theo doanh thu đã được các nền tảng như Shopify Capital, PayPal Working Capital dùng: bán ít thì trả ít, bán nhiều thì trả nhanh, hợp với doanh thu mùa vụ. Trần tỷ lệ bằng phần giá vốn bảo đảm người bán còn phần lãi để vận hành |
| Sàn lũy kế | Trả theo doanh thu có điểm yếu: người bán có thể chuyển dòng tiền đi chỗ khác. Sàn lũy kế bảo đảm tổng đã trả không tụt quá xa so với dự báo thận trọng |
| Hợp đồng thông minh tự phân bổ quá hạn → lãi → gốc | Thứ tự phân bổ là điều khoản hợp đồng; để code trên chuỗi áp thì cả hai bên đối chiếu được, không ai tranh cãi |
| Thông báo giải thích từng lần trích | Người bán thấy tiền bị trừ mà không hiểu vì sao là nguồn khiếu nại lớn nhất trong cho vay trích nợ tự động |
| Quyết định nặng chỉ khóa cán bộ | Đòi nợ trước hạn, tuyên bố vỡ nợ, giãn nợ ảnh hưởng lớn tới người vay và có hệ quả pháp lý; không để agent quyết |
| Vàng thì phân tích, đỏ thì báo người | Theo dõi khoản vay sau giải ngân là nguyên tắc cơ bản của quản trị rủi ro tín dụng; phát hiện sớm cho phép giãn nợ trước khi thành nợ xấu |

## 3. Các tác vụ

### 3.1 Kiểm nhà cung cấp lần cuối

- **Làm gì.** Ngay trước khi phát lệnh: nhà cung cấp còn tồn tại, tài khoản
  nhận trùng với tài khoản đã kiểm lúc duyệt, không cùng nhóm liên kết với
  người bán, giá trên hợp đồng khớp giá đã dùng ở B3.
- **Vì sao cần.** Xem nguyên tắc ở mục 2. Thêm nữa, nhóm liên kết có thể thay
  đổi khi có hồ sơ mới vào hệ thống sau lúc duyệt.
- **Làm thế nào.** `check_supplier_final(approval_id)` chạy lại `link_entities`
  và so tài khoản. Lệch bất kỳ điểm nào: dừng, chuyển cán bộ.
- **Dùng gì.** Hàm Python; dữ liệu Agent 1 đã kiểm; union-find.
- **Ví dụ.**

```json
{"supplier_id": "SUP-0091", "exists": true, "account_match": true,
 "linked_to_seller": false, "price_match": {"contract": 62.0, "used_in_B3": 62.0}, "ok": true}
```

### 3.2 Phát lệnh giải ngân

- **Làm gì.** Tạo một lệnh chuyển tiền, đúng số đã duyệt, tới tài khoản nhà
  cung cấp; ghi Sổ khoản vay.
- **Vì sao cần.** Một lần, đúng số, đúng người nhận là điều kiện để khoản vay
  gắn với hàng hóa cụ thể.
- **Làm thế nào.** `create_disbursement(approval_id)`: code đọc số tiền và tài
  khoản từ bản ghi phê duyệt, gửi lệnh tới core banking (mock trong demo), ghi
  `disburse` lên Sổ khoản vay. Hợp đồng từ chối giải ngân khoản vượt ngưỡng tự
  động nếu chưa có chữ ký cán bộ, và từ chối giải ngân lần hai.
- **Dùng gì.** Hợp đồng Sổ khoản vay (đội đã build); `FiscoChain`; mock core banking.
- **Ví dụ.**

```json
{"loan_id": "L-2026-0042", "amount": 139900, "to": "SUP-0091",
 "core_ref": "CB-88120", "chain_tx": "0x3f…", "at": "2026-10-11T10:06:40+08:00"}
```

### 3.3 Theo dõi giao hàng

- **Làm gì.** Theo dõi nhà cung cấp ký nhận tiền và công ty vận chuyển ghi vận
  đơn giao cho người bán trong số ngày cam kết.
- **Vì sao cần.** Tiền đã trả mà hàng không đến là rủi ro lớn nhất của cho vay
  nhập hàng: nhà cung cấp lừa, hoặc người bán và nhà cung cấp cấu kết.
- **Làm thế nào.** Hợp đồng tự chuyển trạng thái "vi phạm cam kết" khi quá hạn
  chưa có vận đơn. Agent 4 nhận sự kiện, nhắc nhà cung cấp và người bán, báo
  cán bộ nếu vẫn không có sau 3 ngày `[Đặt tay]`.
- **Lưu ý.** Bản v4 ghi hạn vận đơn là 10 ngày ở phiếu đề xuất và 7 ngày ở mục
  Từ ngữ. Đội cần chốt một con số.

### 3.4 Trích nợ khi tiền hàng về

- **Làm gì.** Mỗi lần sàn trả tiền hàng về tài khoản WeBank, trích theo tỷ lệ
  đã chốt; hợp đồng phân bổ quá hạn → lãi → gốc.
- **Vì sao cần.** Xem nguyên tắc trả theo doanh thu ở mục 2.
- **Làm thế nào.** Sự kiện payout kích hoạt code (không qua Agent 4):
  `sweep = payout × tỷ lệ trích`, không vượt dư nợ. Ghi `repay` lên Sổ khoản
  vay; hợp đồng phân bổ. Trong ân hạn không trích. Chống trích hai lần bằng
  mã payout duy nhất, như trong repo hiện có.
- **Ví dụ** lần trích đầu của chị Lan, ngày 30 sau giải ngân, payout 20.000 `[Ví dụ]`:

```json
{"payout_id": "DY-PO-771", "payout": 20000, "rate": 0.63, "sweep": 12600,
 "allocation": {"overdue": 0, "interest": 1380, "principal": 11220},
 "interest_basis": "139.900 × 12% × 30/365 = 1.380",
 "balance_after": 128680, "chain_tx": "0x6a…"}
```

### 3.5 Giải thích từng lần trích

- **Làm gì.** Gửi người bán thông báo: trích bao nhiêu, vì sao, còn nợ bao nhiêu.
- **Vì sao cần.** Minh bạch giảm khiếu nại; người bán thấy phần mình giữ lại.
- **Làm thế nào.** Code dựng phần số; mô hình viết một câu dẫn; bộ lọc số như
  Agent 2. `explain_sweep(sweep_id)`.
- **Ví dụ.**

> "Hôm nay Douyin trả 20.000 tệ tiền hàng. WeBank trích 63% là 12.600 tệ:
> 1.380 tệ lãi 30 ngày và 11.220 tệ gốc. Chị giữ 7.400 tệ. Dư nợ còn 128.680 tệ."

### 3.6 Kiểm sàn lũy kế

- **Làm gì.** So tổng đã trả với sàn lũy kế; thiếu thì trích tài khoản WeBank
  rồi các tài khoản đã ủy quyền.
- **Vì sao cần.** Chặn việc chuyển dòng tiền khỏi WeBank để né trích nợ.
- **Làm thế nào.** Code tính `sàn = tỷ lệ trích × hệ số thận trọng × tiền thực
  nhận dự báo cộng dồn`. Thiếu thì phát lệnh trích bổ sung theo thứ tự; thiếu
  quá 30% `[Đặt tay]` là đỏ ngay ở B11.
- **Ví dụ.** Hết tháng đầu, dự báo cộng dồn 165.000 → sàn 0,63 × 0,70 ×
  165.000 = 72.765. Đã trả 60.000 → thiếu 12.765, tức 17,5%: chưa đỏ, trích
  bổ sung 12.765 từ tài khoản WeBank của chị Lan, gửi thông báo giải thích.

### 3.7 Giám sát cam kết và cảnh báo ba mức

- **Làm gì.** Hằng ngày đọc điểm B11; xanh tự theo dõi, vàng phân tích nguyên
  nhân, đỏ báo cán bộ.
- **Vì sao cần.** Phát hiện sớm cho phép can thiệp nhẹ (nhắc, giãn nợ) trước
  khi phải can thiệp nặng.
- **Làm thế nào.** B11 là code. Điểm = tổng trọng số các điều kiện đang đúng.
  Bản v4 có ngưỡng 0,2 và 0,5 nhưng chưa ghi trọng số; đề xuất `[Đặt tay]`:

| Điều kiện | Trọng số |
|---|---|
| Doanh số tháng < 3 × khoản trả tháng | 0,30 |
| Điểm cửa hàng < 4,0 | 0,20 |
| Tỷ lệ dòng tiền về WeBank giảm > 20% so với tháng trước | 0,20 |
| Có tra cứu tín dụng mới ở nơi khác | 0,10 |
| Tỷ lệ hoàn hàng tăng > 50% so với trung bình 3 tháng | 0,20 |

  Vàng: Agent 4 gọi `get_sales_trend`, `get_refund_trend`,
  `get_rating_history`, viết phân tích nguyên nhân có tham chiếu. Đỏ:
  `notify_officer` kèm phân tích.
- **Ví dụ** báo cáo vàng:

```json
{"loan_id": "L-2026-0042", "date": "2026-12-02", "score": 0.30, "level": "yellow",
 "triggers": ["sales_below_3x_payment"],
 "analysis": [
   {"finding": "Doanh số tháng 11 thấp hơn dự báo thận trọng 18%", "evidence_ref": "tool.get_sales_trend.TC-901"},
   {"finding": "Tỷ lệ hoàn hàng không đổi; điểm cửa hàng 4,6 không đổi", "evidence_ref": "tool.get_refund_trend.TC-902"}
 ],
 "assessment": "Doanh số thấp nhưng không có dấu hiệu chất lượng giảm; khả năng do mùa đông đến muộn",
 "action": "theo dõi hằng ngày, nhắc lịch trả"}
```

### 3.8 Soạn phương án giãn nợ

- **Làm gì.** Khi người bán gặp khó khăn thật, soạn phương án giãn nợ để cán bộ duyệt.
- **Vì sao cần.** Giãn nợ đúng lúc giữ được khách tốt gặp khó tạm thời và
  thường thu hồi được nhiều hơn so với đẩy thành nợ xấu.
- **Làm thế nào.** Giải thuật tính sẵn các phương án cố định (kéo dài kỳ hạn
  1 hoặc 2 tháng, hạ tỷ lệ trích về mức giữ đúng tổng phải trả)
  `[Đặt tay]`. Agent 4 chọn phương án và viết lý do có tham chiếu bằng
  `draft_restructure`. Cán bộ ký bằng khóa của mình trên chuỗi mới có hiệu lực.

## 4. Bộ công cụ

| Công cụ | Ai kích hoạt | Trả về |
|---|---|---|
| `check_supplier_final` | Agent 4 | đạt / không đạt từng điểm |
| `create_disbursement` | Agent 4, sau khi người bán chấp nhận | `core_ref`, `chain_tx` |
| `get_loan_state` | Agent 4 | trạng thái trên Sổ khoản vay |
| `process_payout` | code, theo sự kiện | lần trích, phân bổ |
| `explain_sweep` | Agent 4 | dữ liệu cho thông báo |
| `check_cumulative_floor` | code, hằng ngày | thiếu bao nhiêu |
| `get_alert` | Agent 4 | điểm B11, điều kiện đang đúng |
| `get_sales_trend`, `get_refund_trend`, `get_rating_history` | Agent 4 | chuỗi số liệu |
| `notify_officer` | Agent 4 | mã yêu cầu |
| `draft_restructure` | Agent 4 | bản nháp chờ ký |

## 5. Quyền hạn

| Không được | Được |
|---|---|
| nhập số tiền giải ngân hay số tiền trích | kích hoạt giải ngân sau khi người bán chấp nhận |
| giải ngân khi kiểm nhà cung cấp không đạt | dừng giải ngân và báo cán bộ |
| đổi tài khoản nhận | giải thích từng lần trích |
| đòi nợ trước hạn, tuyên bố vỡ nợ, giãn nợ | phân tích nguyên nhân khi vàng |
| đổi trọng số, ngưỡng cảnh báo | soạn phương án giãn nợ cho cán bộ |
| liên hệ người thứ ba ngoài phạm vi ủy quyền | nhắc lịch, nhắc vận đơn |

## 6. Xử lý lỗi

| Lỗi | Xử lý |
|---|---|
| Core banking từ chối lệnh | Không ghi chuỗi; báo cán bộ; không thử lại tự động quá 1 lần |
| Ghi chuỗi thất bại sau khi tiền đã đi | Ghi hàng đợi đối soát; báo cán bộ; đối soát cuối ngày |
| Payout trùng mã | Code bỏ qua, ghi sự kiện |
| Tài khoản ủy quyền không đủ số dư | Ghi thiếu sàn; tính vào B11 |
| Mô hình ngừng | Trích nợ, kiểm sàn, B11 vẫn chạy (code); thông báo dùng mẫu cố định |

## 7. Ví dụ trọn vẹn

### 7.1 Chị Lan

1. Chị bấm chấp nhận. `check_supplier_final`: đạt.
2. `create_disbursement`: 139.900 tới SUP-0091; hash lên Sổ khoản vay.
3. Nhà cung cấp ký nhận; công ty vận chuyển ghi vận đơn ngày thứ 6.
4. Ân hạn 23 ngày. Ngày 30, payout 20.000 → trích 12.600, thông báo gửi chị.
5. Hết tháng đầu, thiếu sàn 17,5% → trích bổ sung 12.765 từ tài khoản WeBank.
6. Ngày 2/12, B11 vàng 0,30; Agent 4 phân tích: doanh số thấp, chất lượng không đổi; theo dõi.
7. Tháng 12 doanh số hồi phục; tất toán tháng 2; hạn mức lần sau tăng.

### 7.2 Ca xấu: đổi tài khoản nhận

Sau khi duyệt, có email "từ nhà cung cấp" đề nghị đổi tài khoản nhận.
`check_supplier_final`: `account_match = false`. Agent 4 không giải ngân, báo
cán bộ. Không có công cụ nào cho Agent 4 đổi tài khoản.

## 8. Kiểm thử và chỉ số

| Ca | Kết quả đúng |
|---|---|
| Giải ngân đúng | Một lệnh, đúng số, đúng tài khoản; một bản ghi chuỗi |
| Bấm chấp nhận hai lần | Hợp đồng từ chối lần hai |
| Khoản > 500.000 chưa có chữ ký cán bộ | Hợp đồng từ chối |
| Tài khoản nhận đổi | Không giải ngân |
| Quá hạn vận đơn | Hợp đồng chuyển "vi phạm cam kết"; Agent 4 nhắc rồi báo |
| Payout trong ân hạn | Không trích |
| Payout trùng | Không trích hai lần |
| Thiếu sàn 35% | Đỏ ngay |
| Agent 4 được yêu cầu giãn nợ qua chat | Chỉ soạn bản nháp; không có hiệu lực khi chưa có chữ ký cán bộ |

Chỉ số: tỷ lệ giải ngân đúng lần đầu; thời gian từ chấp nhận đến tiền tới nhà
cung cấp; tỷ lệ thông báo trích có số khớp sổ; tỷ lệ cảnh báo vàng chuyển
thành đỏ (đo chất lượng cảnh báo).

## 9. Câu hỏi mở cho đội

- Hạn vận đơn 7 hay 10 ngày?
- Trọng số B11 đề xuất ở 3.7 có dùng được không?
- Lãi tính theo ngày trên dư nợ hay cố định trên hạn mức? Phiếu v4 ghi "lãi tối
  đa = hạn mức × lãi × kỳ hạn", ví dụ ở 3.4 tính theo dư nợ thực tế.
- Có tài khoản ủy quyền nào ngoài WeBank trong demo không?

## 10. Nguồn

**Nội bộ**
- `docs/SellerGraph_core_tech_v4.html`: khối giải ngân, thu nợ, giám sát, B9, B11, Sổ khoản vay, phiếu đề xuất.
- Tài liệu gốc "SellerGraph, toàn cảnh mô hình" 28.09.2026, phần 8.2 (cam kết), 10.2 (thiếu sàn), 10.3 (trần trích, kỳ thanh toán Douyin), theo trích dẫn trong v4.
- Repo: `src/sellergraph/services/lending.py` (chống trích nợ hai lần bằng bảng payout), `src/sellergraph/chain/fisco.py`, `fisco/README.md`.

**Quy định**
- 流动资金贷款管理办法 (Biện pháp quản lý cho vay vốn lưu động), bản sửa đổi 2024 của Cục Quản lý Giám sát Tài chính Quốc gia: thanh toán ủy thác (受托支付) cho khoản vay trên ngưỡng.
- 商业银行互联网贷款管理暂行办法, CBIRC, 2020: quản lý sau cho vay, theo dõi mục đích sử dụng vốn.
- Basel Committee on Banking Supervision, "Principles for the Management of Credit Risk", 2000: giám sát từng khoản tín dụng, phát hiện sớm khoản có vấn đề.

**Tiền lệ sản phẩm**
- Shopify Capital và PayPal Working Capital: trả nợ bằng một tỷ lệ cố định trên doanh số (theo mô tả công khai của hai sản phẩm).
- 仲裁链 của WeBank cùng Ủy ban Trọng tài Quảng Châu trên FISCO BCOS, 2018: chứng cứ trên chuỗi dùng khi phân xử (theo trích dẫn trong v4).
