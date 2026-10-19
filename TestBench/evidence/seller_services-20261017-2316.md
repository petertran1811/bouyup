# Nhật ký demo dịch vụ sau khi vay · 2026-10-17T23:16:34

Theo SELLER_SERVICES_PLAN.md mục 8. SQLite tạm, LLM tắt, chuỗi `local`, autopilot tắt. Kiểm tra cuối: **ĐẠT**.

| Bước | Nội dung | Kết quả |
|---|---|---|
| 1 | Đăng ký người bán, hồ sơ lan, giá khai 120 tệ | trạng thái `offered`, quyết định `approve`, hạn mức 70000 |
| 2 | Duyệt, ký, giải ngân 60.000 tệ / 12 tháng | cổng tự động (không cần cán bộ: đủ 5 điều kiện); khoản vay 60000 / 12 tháng, kỳ 1 2026-11-28 |
| 3 | 20 ngày tiền về, 4 khoản chi 4 nhóm qua webhook có HMAC | 20 lần tiền về, 4 khoản chi (platform, logistics, marketing, goods); không chữ ký → HTTP 401 |
| 4 | Tới 21/11 (kỳ 1 − 7 ngày) rồi tới 01/12/2026 | thông báo: shortfall_forecast, reminder, reminder, due, month |
| 5 | Thêm 3 tháng, tới 01/03/2027: báo cáo quý | báo cáo quý: Báo cáo quý 4/2026 |
| 6 | Trả hết (prepay, confirm: true) → báo cáo tất toán | thiếu confirm → `CONFIRM_REQUIRED`; khoản vay `closed`; Báo cáo tất toán khoản vay |
| 7 | Người bán cá nhân, doanh thu năm nay 85.000 tệ → nhắc đăng ký kinh doanh | `individual`; báo cáo tạo: registration |
| 8 | Sự kiện theo loại và chain_tx của các báo cáo | 124 sự kiện, 9 báo cáo có hash |

## 1. Lời giải thích quyết định (việc 1, nguyên văn)

**Ngân hàng đã duyệt hạn mức 70.000 tệ, thấp hơn mức đề xuất**

- Vì sao: Mô hình kiểm soát độc lập đánh giá kế hoạch thận trọng hơn, nên hạn mức gửi ngân hàng là phương án nhỏ hơn.
- Vì sao: Giá nhập bạn khai (120 tệ) cao hơn giá trên hóa đơn mua vào ba tháng gần nhất (62 tệ) 94%, nên số tiền được tính theo giá hóa đơn.
- Vì sao: Ngân hàng Nông thương Quảng Châu chưa nhận hồ sơ: chỉ nhận hạng A trở lên.
- Vì sao: Bank of China không trả lời kịp nên được tính là chưa đồng ý.
- Bạn có thể: Muốn xét mức đầy đủ thì gửi khiếu nại hoặc nhắn trợ lý để gặp cán bộ.
- Bạn có thể: Tải hóa đơn mua vào hoặc báo giá của xưởng cho lô hàng này.
- Bạn có thể: Đây là điều kiện riêng của từng ngân hàng; bạn không cần làm gì, các ngân hàng khác vẫn cấp vốn.

Đoạn tư vấn của Agent 2 sau vòng ngân hàng (template): Hạn mức của bạn là 70.000 tệ, lãi 10% một năm, kỳ hạn tối đa 12 tháng, không thu phí nào ngoài lãi. Các ngân hàng đối tác duyệt hạn mức 70.000 tệ, thấp hơn mức 100.000 tệ BuoyUp tính được. Mức này thấp hơn 600.000 bạn xin vì bốn lý do. Thứ nhất, giá nhập được tính theo hóa đơn mua vào ba tháng gần nhất là 62 tệ, thay vì giá bạn khai 120 tệ, nên nhu cầu vay giảm 290.000. Thứ hai, phần tồn kho bạn đang có và vốn bạn tự bỏ vào được trừ khỏi nhu cầu vay, giảm 100.000. Thứ ba, hộ kinh doanh vay hoàn toàn trực tuyến được tối đa 200.000 tệ, nên giảm thêm 10.000. Thứ tư, đây là khoản vay đầu tiên của bạn với BuoyUp nên hạn mức bằng 50% mức tính được 200.000 tệ, giảm 100.000.

## Thông báo sau bước 1

- **Ngân hàng đã duyệt hạn mức** (limit_approved, info): Ngân hàng đã duyệt hạn mức 70.000 tệ, hiệu lực đến 24/10. Mời bạn chọn số tiền và ngày trả.
- **Kết quả xét hồ sơ** (decision, info): Ngân hàng đã duyệt hạn mức 70.000 tệ, thấp hơn mức đề xuất · Mô hình kiểm soát độc lập đánh giá kế hoạch thận trọng hơn, nên hạn mức gửi ngân hàng là phương án nhỏ hơn.

## Thông báo sau bước 2

- **Đã giải ngân** (disbursed, info): Đã giải ngân 60.000 CNY. Kỳ trả đầu ngày 28/11/2026, khoảng 5.690. Bạn để tiền hàng về tài khoản kinh doanh WeBank để hệ thống tự trích đúng hạn.

## Thông báo sau bước 3 (việc 4)

- **Báo cáo tháng 2026-10** (month, info): Tháng 10 tiền hàng về WeBank 4.800 tệ, bằng 2 % doanh thu dự báo trong hồ sơ vay (200.040 tệ). Chi lớn nhất là chi phí trên sàn 253 tệ. Cuối tháng tài khoản WeBank còn 64.800 tệ, thấp nhất 60.000 tệ hôm 17/10.
- **Số dư thấp hơn kỳ tới** (spend_below_due, warn): Bạn vừa chi 58.000 tệ (Nhập vải lô mới). Số dư còn 3.900 tệ, thấp hơn 5.690 tệ phải trả ngày 28/11. Nhớ để tiền hàng về WeBank trước ngày đó.

## 4. Kỳ 1 − 7 ngày và đầu tháng (việc 2, 3, 5, 9)

Tại ngày kỳ 1 − 7:

- **Có thể thiếu tiền kỳ tới** (shortfall_forecast, warn): Còn 7 ngày đến kỳ 1 (28/11): phải trả 5.690 tệ. Số dư 3.900 tệ; với nhịp tiền về 30 ngày qua, đến ngày trả dự kiến có khoảng 0 tệ, thiếu khoảng 5.700 tệ. Bạn có thể nộp thêm vào tài khoản WeBank hoặc chọn trả tối thiểu 2.190 tệ cho kỳ này.
- **Nhắc kỳ trả sắp tới** (reminder, info): Còn 7 ngày đến kỳ 1 (28/11/2026): khoảng 5.690. Số dư tài khoản kinh doanh 3.900.

Tới 2026-12-01:

- **Nhắc kỳ trả sắp tới** (reminder, info): Còn 1 ngày đến kỳ 1 (28/11/2026): khoảng 5.690. Số dư tài khoản kinh doanh 28.900.
- **Đã trích kỳ trả** (due, info): Kỳ 1 ngày 28/11/2026: đã trích 5.690 (lãi 690 cho 42 ngày, gốc 5.000). Dư nợ gốc còn 55.000.
- **Báo cáo tháng 2026-11** (month, info): Tháng 11 tiền hàng về WeBank 26.600 tệ, bằng 13 % doanh thu dự báo trong hồ sơ vay (200.040 tệ). Chi lớn nhất là hàng hóa và nguyên liệu 58.000 tệ; trả nợ BuoyUp 5.690 tệ. Cuối tháng tài khoản WeBank còn 23.210 tệ, thấp nhất 3.900 tệ hôm 05/11.

## 5. Ba tháng sau (việc 6)

Phần cửa hàng trong báo cáo quý:

- snapshots: 2
- from: 2026-11
- to: 2026-12
- rating: {'from': 4.6, 'to': 4.6, 'change': 0.0}
- returns: Sàn chưa cung cấp tỷ lệ hoàn hàng (chưa có)
- Ghi chú: Báo cáo tính được 11 % doanh thu của cửa hàng (so với doanh thu dự báo trong hồ sơ vay); phần còn lại về tài khoản khác, BuoyUp không thấy.
- Ghi chú: Phí sàn ước tính theo biểu phí 5 % của Douyin.

- **Nhắc kỳ trả sắp tới** (reminder, info): Còn 7 ngày đến kỳ 2 (28/12/2026): khoảng 5.452. Số dư tài khoản kinh doanh 41.210.
- **Nhắc kỳ trả sắp tới** (reminder, info): Còn 1 ngày đến kỳ 2 (28/12/2026): khoảng 5.452. Số dư tài khoản kinh doanh 50.210.
- **Đã trích kỳ trả** (due, info): Kỳ 2 ngày 28/12/2026: đã trích 5.452 (lãi 452 cho 30 ngày, gốc 5.000). Dư nợ gốc còn 50.000.
- **Báo cáo tháng 2026-12** (month, info): Tháng 12 tiền hàng về WeBank 36.000 tệ, bằng 18 % doanh thu dự báo trong hồ sơ vay (200.040 tệ). Chi lớn nhất là chi phí trên sàn 1.895 tệ; trả nợ BuoyUp 5.452 tệ. Cuối tháng tài khoản WeBank còn 53.758 tệ, thấp nhất 23.210 tệ hôm 01/12.
- **Báo cáo quý 2026-Q4** (quarter, info): Quý 4/2026 tiền hàng về WeBank 67.400 tệ. Chi lớn nhất là hàng hóa và nguyên liệu 58.000 tệ. Cuối quý tài khoản WeBank còn 53.758 tệ, đủ chi khoảng 2,6 tháng theo mức chi của quý.
- **Nhắc kỳ trả sắp tới** (reminder, info): Còn 7 ngày đến kỳ 3 (28/01/2027): khoảng 5.425. Số dư tài khoản kinh doanh 71.758.
- **Nhắc kỳ trả sắp tới** (reminder, info): Còn 1 ngày đến kỳ 3 (28/01/2027): khoảng 5.425. Số dư tài khoản kinh doanh 71.758.
- **Đã trích kỳ trả** (due, info): Kỳ 3 ngày 28/01/2027: đã trích 5.425 (lãi 425 cho 31 ngày, gốc 5.000). Dư nợ gốc còn 45.000.
- **Báo cáo tháng 2027-01** (month, info): Tháng 1 tiền hàng về WeBank 27.000 tệ, bằng 14 % doanh thu dự báo trong hồ sơ vay (200.040 tệ). Chi lớn nhất là chi phí trên sàn 1.421 tệ; trả nợ BuoyUp 5.425 tệ. Cuối tháng tài khoản WeBank còn 75.333 tệ, thấp nhất 53.758 tệ hôm 01/01.
- **Nhắc kỳ trả sắp tới** (reminder, info): Còn 7 ngày đến kỳ 4 (28/02/2027): khoảng 5.382. Số dư tài khoản kinh doanh 93.333.
- **Nhắc kỳ trả sắp tới** (reminder, info): Còn 1 ngày đến kỳ 4 (28/02/2027): khoảng 5.382. Số dư tài khoản kinh doanh 93.333.
- **Đã trích kỳ trả** (due, info): Kỳ 4 ngày 28/02/2027: đã trích 5.382 (lãi 382 cho 31 ngày, gốc 5.000). Dư nợ gốc còn 40.000.
- **Báo cáo tháng 2027-02** (month, info): Tháng 2 tiền hàng về WeBank 18.000 tệ, bằng 9 % doanh thu dự báo trong hồ sơ vay (200.040 tệ). Chi lớn nhất là chi phí trên sàn 947 tệ; trả nợ BuoyUp 5.382 tệ. Cuối tháng tài khoản WeBank còn 87.951 tệ, thấp nhất 75.333 tệ hôm 01/02.
- **Báo cáo năm 2026** (year, info): Năm 2026 tờ khai thuế ghi khoảng 1.421.800 tệ doanh thu (9 tháng); tiền hàng về WeBank 67.400 tệ. 3 tháng đầu sau giải ngân, tiền hàng về WeBank 67.400 tệ. Nếu 3 tháng tới tiền hàng về WeBank ≥ 80 %, hạn mức lần sau có thể tới 150.000 tệ.

## 6. Tất toán (việc 7)

- **Đã trả trước** (prepay, info): Trả trước 40.011 không mất phí: lãi 11 cho 1 ngày đã dùng, gốc 40.000. Dư nợ gốc còn 0.
- **Đã tất toán khoản vay** (closed, info): Bạn đã trả hết khoản vay. BuoyUp đã báo trung tâm thông tin tín dụng. Từ giờ bạn có thể đổi tài khoản nhận tiền hàng; khi cần vốn, bạn vay lại với hồ sơ cập nhật.
- **Báo cáo tất toán** (closing, info): Bạn đã tất toán khoản vay 60.000 tệ sau 135 ngày, tổng lãi thật 1.960 tệ, không trễ kỳ nào. 3 tháng đầu sau giải ngân, tiền hàng về WeBank 67.400 tệ. Nếu 3 tháng tới tiền hàng về WeBank ≥ 80 %, hạn mức lần sau có thể tới 150.000 tệ.

## 7. Nhắc đăng ký kinh doanh (việc 8)

- **Ngân hàng đã duyệt hạn mức** (limit_approved, info): Ngân hàng đã duyệt hạn mức 25.000 tệ, hiệu lực đến 24/10. Mời bạn chọn số tiền và ngày trả.
- **Kết quả xét hồ sơ** (decision, info): Ngân hàng đã duyệt hạn mức 25.000 tệ · Giá nhập bạn khai (80 tệ) cao hơn giá trên hóa đơn mua vào ba tháng gần nhất (62 tệ) 29%, nên số tiền được tính theo giá hóa đơn.
- **Nhắc đăng ký kinh doanh** (registration, warn): Doanh thu năm nay của bạn khoảng 85.000 tệ. Theo Điều 8 Quy định giám sát giao dịch trực tuyến (2021), bán hàng qua mạng với doanh thu năm trên 100.000 tệ phải đăng ký kinh doanh. Đăng ký xong, hạn mức BuoyUp cho hộ kinh doanh tới 200.000 tệ thay vì 50.000.
- Trích dẫn: Quy định giám sát giao dịch trực tuyến, Điều 8 · đã kiểm: True
- Trích dẫn: Quy định giám sát giao dịch trực tuyến, Điều 8 · đã kiểm: True
- Trích dẫn: Luật Thương mại điện tử, Điều 10 · đã kiểm: True

## 8. Báo cáo trên chuỗi

| Loại | Kỳ | Tiêu đề | hash | chain_tx |
|---|---|---|---|---|
| month | 2026-10 | Báo cáo tháng 10/2026 | `sha256:23db4ed3e4a560ad7…` | `0x45cd56a65d99c6a63608c55865288c240de27fbd` |
| month | 2026-11 | Báo cáo tháng 11/2026 | `sha256:b4cbb6bfaec19314a…` | `0x989035f1bb1635ef41fc27029edcc1833ab154cb` |
| month | 2026-12 | Báo cáo tháng 12/2026 | `sha256:e0ac85968c9ff7870…` | `0xb2d6013ce9bdd200979234917aae0cf6fb80e952` |
| quarter | 2026-Q4 | Báo cáo quý 4/2026 | `sha256:ddc8f80cfaacb40ad…` | `0xfbd9d1a733a76395d459950b26092da0e344e37a` |
| month | 2027-01 | Báo cáo tháng 1/2027 | `sha256:5f94033f28d9c8ed2…` | `0x267e4e08cb45f51143acf9f053313113a8413894` |
| month | 2027-02 | Báo cáo tháng 2/2027 | `sha256:aa34b3375c5cce9ec…` | `0x76cf6db14930e969889b44eea807d7cf69e7a288` |
| year | 2026 | Báo cáo năm 2026 | `sha256:f685c385daa5043a7…` | `0x206a33ed98493404861bcd61a6ea2db1c7b5b721` |
| closing | loan_affeb64e728e9769 | Báo cáo tất toán khoản vay | `sha256:f75b06b82ad2496e5…` | `0x8267dafdbf5f0fb986548169e827fbf6be69c02a` |
| registration | 2026 | Nhắc đăng ký kinh doanh 2026 | `sha256:ca4528427e8474fb9…` | `0x4b7b103b90385e306d76da68280d43d60c48b34f` |

## 8. Sự kiện theo loại

| kind | số lượng | actor |
|---|---|---|
| approve | 2 | gate 2 |
| bank_answer | 8 | bank 8 |
| bureau_report | 1 | agent4 1 |
| conclusion | 4 | agent1 2, agent3 2 |
| consent | 2 | agent1 2 |
| contract_issued | 1 | orchestrator 1 |
| contract_signed | 1 | seller 1 |
| disbursed | 1 | agent4 1 |
| escrow_funded | 1 | agent4 1 |
| flags | 2 | agent1 2 |
| gate | 2 | gate 2 |
| get_offer_sheet | 2 | agent2 2 |
| identity | 2 | agent1 2 |
| inflow | 30 | agent4 30 |
| offer_sheet | 2 | code 2 |
| payment_confirmed | 1 | seller 1 |
| payout_grant | 1 | agent4a 1 |
| phase0 | 2 | agent3 2 |
| phase1_seal | 2 | agent3 2 |
| propose | 2 | agent2 2 |
| repayment | 5 | agent4 5 |
| select | 1 | seller 1 |
| seller_alert | 2 | agent4 2 |
| seller_report | 17 | agent5 17 |
| steps_1_2 | 2 | agent1 2 |
| syndicate | 2 | orchestrator 2 |
| tool_call | 22 | agent1 22 |
| transfer | 4 | agent4 4 |

## Kiểm tra cuối

- BuRepayment tổng: 5; theo vai đang chạy: {'standing_order': 4, 'không vai (yêu cầu của người bán)': 1}
- BuRepayment do actor `agent5` tạo: **0**
- Vi phạm quyền (`capabilities`): **0**; các lần kiểm: {'payout:agent4a': 1, 'debit:standing_order': 8, 'debit:không vai': 1}
- Báo cáo có `chain_tx`: 9/9
- Kết luận: **ĐẠT**
