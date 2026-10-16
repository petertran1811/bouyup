# Chuyển BuoyUp sang quy trình "loan circle"

Căn cứ: `docs/BuoyUp loan circle .docx` (10 giai đoạn, sửa 14/10/2026) và 4 điểm đội đã chốt ngày 14/10/2026:

| Điểm cần chốt | Quyết định |
|---|---|
| Không đối tác nào đồng ý trong 30 giây | WeBank **không** cho vay một mình: thử lại với hạn mức thấp hơn (70%, rồi 50%), vẫn không ai nhận thì từ chối |
| Tỷ lệ cho hình thức trả theo doanh thu | Giải thuật tính theo hồ sơ: đủ trả hết gốc và lãi trong kỳ hạn theo doanh thu dự báo thận trọng, không vượt trần B5. Mức tối thiểu = lãi tháng + 30% gốc của một kỳ trả góp đều |
| Ngưỡng trả thẳng nhà cung cấp | Phần vượt **100.000 tệ** |
| Khung kỳ hạn | Hộ kinh doanh: 3, 6, 12 tháng. Doanh nghiệp: 3, 6, 12, 24, 36 tháng |

Mọi tham số khác do mình đặt đều gắn nhãn `[Đặt tay]` trong Bảng tham số để đội duyệt.

## Khác biệt chính so với v4 hiện tại

| | v4 hiện tại | Loan circle |
|---|---|---|
| Sản phẩm | Ứng vốn mùa vụ, kỳ hạn 4 tháng, trả bằng trích mỗi lần tiền hàng về | Khoản vay 3–36 tháng, trả hằng tháng; hai hình thức trả, chọn một lần |
| Nguồn dữ liệu | Dòng tiền từ sàn về các tài khoản (kể cả ngân hàng khác) | Chỉ báo cáo tín dụng, FATE, thuế có ủy quyền; tùy chọn ảnh doanh thu do người bán nộp |
| Người duyệt | BuoyUp tính và duyệt, rồi chia cho ngân hàng | Lõi quyết định ra hạn mức; các ngân hàng **tự duyệt song song trong 30 giây** |
| Chia vốn | Ngân hàng đủ điều kiện, tối thiểu 30% | Hai đối tác đồng ý: WeBank 40 / 30 / 30; một đối tác: WeBank 30 / đối tác 70 |
| Thứ tự | Người bán chọn số tiền rồi mới kiểm soát | Kiểm soát và ngân hàng duyệt **hạn mức** trước; người bán chọn trong hạn mức, không duyệt lại |
| Giải ngân | Lệnh chia theo ngân hàng | Ngân hàng chuyển vào tài khoản trung gian tại WeBank, đủ tiền mới giải ngân; phần vượt 100.000 trả thẳng nhà cung cấp |
| Thu nợ | Trích theo tỷ lệ mỗi lần tiền về | Trích vào ngày trả; phân bổ lãi phạt → lãi → gốc; lãi theo ngày thực tế; trả trước miễn phí |
| Quá hạn | Cảnh báo đỏ | Trả tối thiểu (tối đa 2 kỳ liền), 3 ngày ân hạn rồi lãi phạt, quá hạn 30 ngày báo trung tâm tín dụng, quyết định theo 2/3 dư nợ |

## Các giai đoạn làm

1. **Tham số và giải thuật.** Bảng tham số mới (loại người vay, kỳ hạn, trần hộ kinh doanh, trả tối thiểu, lãi phạt, ngưỡng trả thẳng); doanh thu từ thuế; hạn mức theo khả năng trả; lịch trả hai hình thức; lãi theo ngày.
2. **Giai đoạn 1–2 phía người vay.** Loại người vay; 3 ô đồng ý riêng, ký bằng khuôn mặt hoặc mã OTP; ảnh doanh thu tùy chọn; Agent 1 bỏ dữ liệu dòng tiền ngân hàng khác.
3. **Giai đoạn 2 phía ngân hàng.** Agent 3 rà gói hồ sơ ở mức hạn mức; bộ điều phối gửi song song; ngân hàng tự duyệt trong 30 giây; quy tắc cứng (30%, tập trung 25%/50%, địa bàn, danh sách trắng, ≤ 24%, không phí); hạn mức hiệu lực 7 ngày.
4. **Giai đoạn 3–5.** Chọn số tiền, kỳ hạn, hình thức, ngày trả; một khoản vay một lúc; bảng chi phí có thời gian đọc bắt buộc; hợp đồng từng ngân hàng; kiểm tra nhẹ; ký; tài khoản trung gian; giải ngân.
5. **Giai đoạn 6–8.** Giám sát giao dịch tài khoản kinh doanh (chứng khoán, bất động sản, chuyển lớn ra cá nhân); nhắc 7 ngày và 1 ngày; trích ngày trả; trả tối thiểu; lãi phạt; quá hạn 30 ngày; trả trước.
6. **Giai đoạn 9–10.** Tất toán, báo trung tâm tín dụng, Agent 5; vay lại với dữ liệu mới.
7. **Giao diện** người bán, quản trị, ngân hàng; tài liệu (HANDOVER, hợp đồng API, đặc tả agent); demo.

Mỗi giai đoạn có test; tiến độ và quyết định ghi ở `LOAN_CIRCLE_CHANGES.md`.
