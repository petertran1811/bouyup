# Năm agent của SellerGraph v4 — mục lục

Mỗi agent một tài liệu. Cả năm đều theo cùng một khuôn: vị trí trong luồng,
nguyên tắc thiết kế, từng tác vụ (làm gì · vì sao cần · làm thế nào · dùng
gì · ví dụ), bộ công cụ, đầu ra mẫu, quyền hạn, xử lý lỗi, ví dụ trọn vẹn
với chị Lan, kiểm thử, câu hỏi mở cho đội, và nguồn.

| File | Agent | Một câu |
|---|---|---|
| [agent1_xac_minh.md](agent1_xac_minh.md) | Agent 1 · Xác minh | Phiên bản 3: không kết nối cửa hàng, không nộp hồ sơ; kiểm cửa hàng qua thông tin công khai, đo doanh số bằng tiền từ sàn về |
| [agent2_tu_van_de_xuat.md](agent2_tu_van_de_xuat.md) | Agent 2 · Tư vấn & Đề xuất | Chọn phương án trong danh sách giải thuật, giải thích cho người bán |
| [agent3_kiem_soat.md](agent3_kiem_soat.md) | Agent 3 · Kiểm soát | Phản biện độc lập hai pha, sàn kết luận, niêm phong; kiểm hàng hóa và chống rửa tiền theo bộ luật TQ |
| [agent4_giai_ngan_thu_no.md](agent4_giai_ngan_thu_no.md) | Agent 4 · Giải ngân & Thu nợ | Chuyển tiền thẳng nhà cung cấp, giải thích từng lần trích, cảnh báo ba mức |
| [agent5_hau_kiem.md](agent5_hau_kiem.md) | Agent 5 · Hậu kiểm | So quyết định với kết quả thật, tấn công thử, đề xuất cải tiến có người duyệt |

## Nguyên tắc chung cho cả năm agent

1. **Mọi con số do giải thuật cố định tính.** Agent chọn, giải thích, đối
   chiếu; không agent nào tạo, sửa hay đề xuất một con số tiền.
2. **Mọi phán quyết "đạt / không đạt" do code kiểm lại.** Agent có thể đề
   nghị; code mới đổi trạng thái.
3. **Mỗi agent một bộ công cụ hẹp.** Không có công cụ nào nhận số tiền tự do.
4. **Mọi đầu vào, đầu ra có vết**, hash ghi Nhật ký kiểm toán trên FISCO BCOS.
5. **Lỗi thì dừng và chuyển người, không đoán.**

## Cách đọc nhãn

`[Tiền lệ]` có nguồn; `[Đặt tay]` tham số do nhóm chọn, cần hội đồng duyệt;
`[Ví dụ]` số giả định của câu chuyện chị Lan; `[Tính ra]` kết quả công thức.
Các mục "Nguồn" tách hai loại: nguồn nội bộ (tài liệu và mã trong repo) và
nguồn ngoài (quy định, nghiên cứu). **Nguồn ngoài cần đội mở và đối chiếu
nguyên văn trước khi trích trong bài nộp**; tên và năm đã kiểm, điều khoản cụ
thể ghi theo hiểu biết hiện có.

## Đã đồng bộ với

`docs/SellerGraph_core_tech_v4.html`, các mục `#agent-1`, `#agent-2`,
`#agent-3` (ngày 10–11/10/2026). Agent 4 và 5 chưa có mục chi tiết trong
HTML; tài liệu ở đây là bản thiết kế đầu tiên.
