# Hỏi đáp về BuoyUp

Mỗi mục `##` là một câu hỏi; phần bên dưới là câu trả lời chatbot đưa ra khi câu hỏi của người dùng khớp.
Sửa file này rồi chạy `python build_kb.py` để chatbot dùng nội dung mới. Số liệu lấy từ `BackEnd/src/app/core/params.py`
và `LOAN_CIRCLE_CHANGES.md`; đổi tham số thì sửa lại ở đây.

## BuoyUp là gì? BuoyUp làm gì?
BuoyUp giúp người bán hàng online (ví dụ chị Lan bán quần áo trên Douyin) vay vốn nhập hàng mà không cần tài sản thế chấp.
- Năm AI agent kiểm tra cửa hàng có thật không, đọc doanh thu khai thuế và lịch sử tín dụng, rồi một công thức cố định tính hạn mức.
- Nhiều ngân hàng (WeBank dẫn đầu cùng các ngân hàng hợp tác) tự xem hồ sơ trong 30 giây và cùng góp vốn cho một khoản vay.
- Người vay tự chọn số tiền, kỳ hạn, cách trả, ký trên điện thoại; hệ thống giải ngân, nhắc trả, tự trích nợ và xử lý trả chậm.
- Các bước quan trọng được ghi dấu (hash) lên blockchain FISCO BCOS để không ai sửa lén được.

Đây là bản demo dự thi FinTechathon 2026; số liệu cửa hàng, thuế, tín dụng và quyết định ngân hàng đều là mô phỏng.

## Quy trình vay (vòng vay / loan circle) gồm những bước nào?
Vòng vay có 10 giai đoạn:
1. **Nộp hồ sơ:** chọn loại người vay, dán link cửa hàng, quét CCCD, đánh dấu ba ô đồng ý, ký bằng khuôn mặt hoặc OTP.
2. **Thẩm định và duyệt:** Agent 1 xác minh, công thức tính hạn mức, Agent 2 đề xuất, Agent 3 kiểm soát, các ngân hàng tự duyệt song song trong 30 giây.
3. **Chọn khoản vay:** số tiền trong hạn mức, kỳ hạn, cách trả (trả góp hoặc theo doanh thu), ngày trả 1–28.
4. **Hợp đồng và ký:** đọc bảng chi phí ít nhất 20 giây rồi ký.
5. **Giải ngân:** tiền các ngân hàng vào tài khoản trung gian ở WeBank, đủ thì chuyển một lần.
6. **Giám sát:** theo dõi tiền vào, tiền ra của tài khoản kinh doanh, cảnh báo sớm.
7. **Thu nợ** vào ngày trả. 8. **Xử lý quá hạn.** 9. **Tất toán.** 10. **Vay lại** dựa trên lịch sử với BuoyUp.

## Ai được vay? Hộ kinh doanh và doanh nghiệp khác nhau thế nào?
BuoyUp phục vụ người bán trên các sàn Douyin, Taobao, Tmall, JD, Pinduoduo, Kuaishou. Có hai loại người vay, chọn khi tạo hồ sơ và phải khớp đăng ký kinh doanh (lệch thì bị chặn):
- **Hộ kinh doanh:** hạn mức tối đa 200.000 tệ; kỳ hạn 3, 6 hoặc 12 tháng.
- **Doanh nghiệp:** hạn mức tối đa 2.000.000 tệ; kỳ hạn 3, 6, 12, 24 hoặc 36 tháng; người đại diện phải ký bảo lãnh.

## Hạn mức được tính như thế nào? Tôi được vay tối đa bao nhiêu?
Hạn mức = số nhỏ nhất trong ba con số:
1. Khả năng trả nợ trong kỳ hạn dài nhất, tính trên doanh thu khai thuế đã nhân hệ số thận trọng theo ngành.
2. Trần theo nhóm tín dụng (nhóm 1: gấp 3 lần, nhóm 2: 1,5 lần, nhóm 3: 0,5 lần, nhóm 4: không cho vay).
3. Trần theo loại người vay (hộ kinh doanh 200.000 tệ, doanh nghiệp 2.000.000 tệ).

Hạn mức tối thiểu 10.000 tệ và có hiệu lực 7 ngày. Con số do công thức cố định B1–B9 tính, AI không được tạo hay sửa số.

## Lãi suất bao nhiêu? Có mất phí không?
Lãi năm theo hạng hồ sơ: A 8%, B 10%, C 12%, D 15%, không thấp hơn chi phí vốn cộng chi phí xử lý và không vượt trần 24%.
Phí bằng 0: lãi năm trong bảng chi phí là toàn bộ chi phí. Lãi tính theo số ngày thực tế trên dư nợ gốc. Trả trước hạn không mất phí, chỉ trả lãi những ngày đã dùng tiền.

## Nhiều ngân hàng cùng cho vay như thế nào? Tỷ lệ chia vốn ra sao?
WeBank dẫn đầu. Bộ điều phối kiểm các quy tắc cứng rồi gửi hồ sơ song song cho các ngân hàng hợp tác; mỗi ngân hàng tự quyết theo chính sách của mình và danh mục trên chuỗi. Ngân hàng nào trả lời quá 30 giây coi như từ chối.
- Hai ngân hàng đồng ý: WeBank 40%, mỗi ngân hàng 30%.
- Một ngân hàng đồng ý: WeBank 30%, ngân hàng đó 70%.
- Không ai đồng ý: thử lại ở 70% rồi 50% hạn mức; vẫn không ai nhận thì từ chối (NO_PARTNER). WeBank không cho vay một mình.

Trong demo, chị Lan được hạn mức 200.000 tệ, chia WeBank 40% / CMB 30% / ICBC 30%. Tên ngân hàng chỉ là đối tác giả định.

## Trả nợ theo doanh thu là gì? Khác trả góp thế nào?
Người vay chọn một trong hai cách, chọn một lần khi chọn khoản vay:
- **Trả góp đều:** mỗi kỳ trả gốc đều cộng lãi.
- **Trả theo doanh thu:** số tiền mỗi kỳ tính theo hồ sơ, đủ trả hết gốc và lãi trong kỳ hạn trên doanh thu thận trọng.

Có thể xem lịch trả của từng lựa chọn trước khi chọn. Kỳ trả đầu cách ngày giải ngân ít nhất 15 ngày; ngày trả chọn từ 1 đến 28.

## Trả tối thiểu là gì? Nếu tháng này tôi không đủ tiền thì sao?
Với khoản trả góp kỳ hạn từ 3 tháng, người vay có thể trả tối thiểu = lãi của kỳ + 30% gốc của một kỳ trả góp đều. Được trả tối thiểu tối đa 2 kỳ liền; phần gốc hoãn chia đều vào các kỳ sau.
Trước ngày trả 7 ngày và 1 ngày hệ thống nhắc; nếu số dư không đủ cho kỳ tới thì có cảnh báo sớm.

## Trả chậm hoặc quá hạn thì bị xử lý thế nào?
- Có 3 ngày ân hạn sau ngày trả.
- Sau đó tính lãi phạt bằng 1,5 lần lãi (không vượt 24%/năm). Tiền trả được phân bổ: lãi phạt trước, rồi lãi, rồi gốc, chia các ngân hàng theo tỷ lệ góp vốn.
- Quá hạn 30 ngày thì báo trung tâm thông tin tín dụng; nhóm ngân hàng nắm từ 2/3 dư nợ trở lên quyết định bước tiếp.
- Lần vay sau, người từng quá hạn từ 30 ngày bị xếp nhóm 4 (không được vay).

## Tiền vay được giải ngân vào đâu? Trả thẳng nhà cung cấp là sao?
Các ngân hàng chuyển phần vốn của mình vào tài khoản trung gian tại WeBank; đủ tiền mới giải ngân một lệnh:
- Tối đa 100.000 tệ vào tài khoản kinh doanh WeBank của người vay.
- Phần vượt 100.000 tệ trả thẳng cho nhà cung cấp (phải có hóa đơn, không liên kết với người vay).

Trước khi chuyển, Agent 4 kiểm lại ủy quyền còn hiệu lực và người nhận đúng như hợp đồng. Hash hợp đồng, quyết định và lệnh giải ngân được ghi lên chuỗi.

## Hợp đồng ký thế nào? Cần chuẩn bị gì khi ký?
Hợp đồng hiện bảng chi phí: lãi năm (toàn bộ chi phí, phí 0), lãi phạt, quy tắc trả tối thiểu, các ngân hàng và phần vốn, kênh khiếu nại, lịch trả. Phải mở đọc ít nhất 20 giây mới ký được.
Khi ký cần: tài khoản kinh doanh WeBank, cam kết dùng vốn đúng mục đích, tài khoản nhà cung cấp nếu vay trên 100.000 tệ, bảo lãnh của người đại diện nếu là doanh nghiệp. Lúc ký mới giữ chỗ hạn mức của từng ngân hàng; mỗi ngân hàng một số hợp đồng.

## Ba ô đồng ý là gì? Tôi có rút lại sự đồng ý được không?
Khi nộp hồ sơ có ba ô đồng ý riêng, không đánh sẵn, mỗi ô có văn bản giải thích: (1) xử lý khuôn mặt và dữ liệu tài chính, (2) ủy quyền tra cứu tín dụng, (3) chuyển hồ sơ cho các ngân hàng hợp tác. Thiếu ô nào thì không nộp được. Ký bằng khuôn mặt hoặc OTP.
Người vay rút đồng ý bất cứ lúc nào; khi đó mọi tra cứu dừng và không thể chọn hay ký khoản vay. Ủy quyền có hiệu lực 90 ngày.

## Agent 1 làm gì?
Agent 1 · Người thẩm tra: kiểm cửa hàng có thật và đúng chủ, lấy doanh thu từ dữ liệu thuế, báo cáo tín dụng, điểm FATE và lịch sử vay với BuoyUp.
Người vay có thể nộp thêm ảnh sao kê doanh thu (tối đa 6 tháng): lệch so với thuế ≤ 15% thì dùng và được cộng 5% hệ số thận trọng; 15–30% thì bỏ qua; trên 30% thì bật cờ RISK_STATEMENT_MISMATCH và chuyển cán bộ. Thấy điểm lạ thì hỏi lại người vay trước. Mọi kết luận thật/giả do công cụ cố định đưa ra, không do mô hình ngôn ngữ.

## Agent 2 làm gì?
Agent 2 · Người tư vấn: nhận phiếu hạn mức từ công thức, đề xuất hạn mức đầy đủ, gợi ý vay vừa đủ theo kế hoạch nhập hàng, báo giá từng lựa chọn kỳ hạn và cách trả, và trả lời chat của người bán. Agent 2 chỉ chọn và giải thích, không bao giờ tạo hay đổi con số, không được hứa hẹn.

## Agent 3 làm gì?
Agent 3 · Người kiểm soát: rà độc lập toàn bộ hồ sơ theo bộ quy tắc rủi ro và pháp lý có trích dẫn điều luật (bộ rules-v1.2), không nghe theo lời thuyết phục của Agent 2.
- Pha 0: code chạy các quy tắc và tính "sàn kết luận".
- Pha 1: Agent 3 tự đánh giá khi chưa thấy lập luận của Agent 2; kết luận được niêm phong bằng hash trên chuỗi.
- Pha 2: đọc lập luận của Agent 2 rồi kết luận cuối, không bao giờ nhẹ hơn sàn.

Sau đó cổng duyệt quyết định; hạn mức trên 500.000 tệ thì cán bộ duyệt. Agent 3 dùng RAG để tìm điều luật làm căn cứ.

## Agent 4 làm gì?
Agent 4 · Người quản lý khoản vay: giải ngân qua tài khoản trung gian, nhắc trả trước 7 và 1 ngày, trích nợ vào ngày trả, xử lý trả tối thiểu, ân hạn, lãi phạt, quá hạn 30 ngày, trả trước, theo dõi tiền vay dùng đúng mục đích và báo cáo hằng ngày cho ngân hàng. Agent 4 tự chạy mỗi 5 phút. Các quyết định nặng (đòi nợ trước hạn, giãn nợ) chỉ cán bộ làm được.

## Agent 5 làm gì?
Agent 5 · Người hậu kiểm: không xử lý hồ sơ nào. Nó nhìn lại cả danh mục theo chu kỳ (mỗi 6 giờ): so quyết định lúc duyệt với kết quả trả nợ thật, theo dõi nợ xấu, phát hiện trôi dữ liệu, đo hành vi của Agent 2 và Agent 3, rồi đề xuất chỉnh tham số. Người duyệt mới được áp dụng; Agent 5 không có quyền sửa cấu hình.

## AI có tự quyết định cho vay hay tự chuyển tiền không?
Không. Mọi con số (hạn mức, lãi, hạng, lịch trả) do công thức cố định tính. Tiền do hệ thống ngân hàng chuyển theo hợp đồng. Mỗi ngân hàng tự duyệt phần của mình.
Mô hình ngôn ngữ chỉ điều phối, giải thích và soạn câu chữ; đầu ra đi qua bộ lọc chặn bịa số, hứa hẹn và lời nhắm vào agent khác. Máy mô hình ngôn ngữ ngừng thì hệ thống vẫn chạy bằng câu mẫu.

## Giám sát tiền vay dùng đúng mục đích như thế nào?
Agent 4 theo dõi tài khoản kinh doanh WeBank:
- Chuyển tiền sang chứng khoán hoặc bất động sản: cảnh báo đỏ và ghi lên chuỗi.
- Chuyển cho cá nhân trên 30% khoản vay: cảnh báo vàng.
- Cảnh báo sớm khi doanh số thấp, điểm cửa hàng giảm, số dư thấp trước kỳ trả, có tra cứu tín dụng mới, điểm FATE xấu đi.

## FATE là gì? BuoyUp dùng FATE thế nào?
FATE là nền tảng học liên kết (federated learning) mã nguồn mở của WeBank: các bên cùng chấm điểm mà không trao đổi dữ liệu gốc. BuoyUp dùng điểm FATE liên ngân hàng như một nguồn của Agent 1 và trong bảng điểm hồ sơ. Trong bản demo, điểm FATE lấy từ dữ liệu mẫu và giao diện ghi rõ "Dữ liệu mẫu".

## Blockchain FISCO BCOS dùng vào việc gì?
BuoyUp ghi dấu vân tay (hash) của từng bước lên FISCO BCOS: ủy quyền, biên bản xác minh, niêm phong Agent 3, quyết định, hợp đồng, giải ngân, thu nợ, báo tín dụng. Lệnh giải ngân được mã hóa theo từng ngân hàng, mỗi ngân hàng chỉ giải mã được phần của mình. Danh mục chính sách của các ngân hàng cũng đọc từ chuỗi. Chạy không có chuỗi thật thì dùng sổ mô phỏng, giao diện ghi nhãn "Mô phỏng".

## RAG là gì? Tra cứu luật hoạt động thế nào?
RAG nghĩa là "tìm rồi mới trả lời": trước khi kết luận, hệ thống tìm đúng điều luật trong kho đã nạp và đưa nguyên văn ra để đối chiếu.
- Hai kho: Trung Quốc (794 điều, 14 văn bản) và Việt Nam (1.147 mục, 5 văn bản).
- Tìm theo chữ (BM25) và theo nghĩa (mô hình đa ngôn ngữ e5-large chạy trên máy), rồi trộn kết quả.
- RAG không quyết định; duyệt hay từ chối vẫn do bộ quy tắc và cán bộ.

Thử ngay ở tab **Tra cứu luật (RAG)**: gõ câu hỏi, chọn kho Việt Nam hoặc Trung Quốc, bấm Tìm.

## Dùng bản demo này thế nào?
- Tab **Demo vòng vay**: chọn một trong 11 kịch bản có sẵn để xem từng bước, hoặc chọn **Tự điền** để tự nhập hồ sơ trên điện thoại giả lập, từ dán link cửa hàng đến giải ngân.
- Tab **Luồng mới so với bản trước**: sơ đồ vòng vay và các thay đổi.
- Tab **BuoyUp nói dễ hiểu**: giải thích bằng lời thường.
- Tab **Tra cứu luật (RAG)**: tra điều luật Việt Nam và Trung Quốc.
- Tab **Hỏi đáp BuoyUp**: hỏi chatbot về bất cứ phần nào của BuoyUp.
- Tab **Góp ý**: ghi nhận xét của bạn; góp ý được lưu lại và hiện trong bảng.

## Dữ liệu trong demo có thật không? Các ngân hàng có hợp tác thật không?
Không. Mọi số liệu cửa hàng, thuế, tín dụng, điểm FATE và quyết định ngân hàng là mô phỏng. Tên WeBank, China Merchants Bank, ICBC… chỉ dùng làm đối tác giả định trong kịch bản, chưa có hợp tác thật.

## BuoyUp dự thi đề tài nào?
BuoyUp dự thi FinTechathon 2026, bảng Quốc tế, đề tài E · SME Finance Copilot (trợ lý tài chính cho doanh nghiệp nhỏ): ghép phương án vay vốn, quản lý và cảnh báo dòng tiền, phân tích tài chính kinh doanh. Thang điểm: hoàn thành tác vụ 40%, an toàn và tuân thủ 30%, đổi mới và tương tác 30%, cộng tối đa 5 điểm cho khám phá blockchain.

## Tất toán và vay lại thế nào?
Trả hết nợ thì khoản vay chuyển sang "đã tất toán", hệ thống báo trung tâm tín dụng, trả lại hạn mức cho các ngân hàng, và người vay được đổi tài khoản nhận tiền hàng. Mỗi người chỉ có một khoản vay đang mở. Khi vay lại, lịch sử với BuoyUp được dùng: đã tất toán tốt thì xếp nhóm 1, từng quá hạn từ 30 ngày thì nhóm 4.

## Vì sao hồ sơ bị từ chối hoặc hạn mức bị giảm?
Một số lý do thường gặp:
- Không ngân hàng nào đồng ý ngay cả ở 70% và 50% hạn mức (NO_PARTNER).
- Nhóm tín dụng 4 (ví dụ từng quá hạn từ 30 ngày).
- Loại người vay không khớp đăng ký kinh doanh.
- Mặt hàng bị cấm hoặc cần giấy phép mà không có (Agent 3 kiểm theo luật, ví dụ thuốc lá điện tử vị hoa quả).
- Sao kê tự nộp lệch thuế trên 30%.
- Cổng duyệt ra "nhỏ hơn": ngân hàng nhận phương án hạn mức nhỏ hơn, người vay không phải xác nhận lại.

## Hệ thống được xây bằng công nghệ gì?
Backend Python FastAPI một tiến trình, dữ liệu trong SQLite; giao diện web tĩnh (người bán, cán bộ/quản trị, ngân hàng). Năm agent trong `app/agents/`, công thức B1–B9 trong `app/core/algorithm.py`, bộ điều phối ngân hàng `app/banks/syndicate.py`, RAG `app/core/rag.py`, chuỗi FISCO BCOS qua dịch vụ riêng. Chạy bằng Docker; có hơn 250 bài kiểm thử tự động. Bản demo này dựng bằng Gradio.

## Có những vai trò người dùng nào?
Bốn vai, tách quyền: người bán (trang workspace, có chat với Agent 2), cán bộ tín dụng và quản trị (trang admin: hồ sơ, toàn bộ luồng, chuỗi, hậu kiểm, tra cứu luật), ngân hàng đối tác (cổng ngân hàng: xem hồ sơ của mình, giải mã lệnh giải ngân phần của mình).

## Bạn là ai? Chatbot này trả lời được những gì?
Mình là trợ lý hỏi đáp của bản demo BuoyUp. Mình tìm câu trả lời trong tài liệu của đội (hỏi đáp, trang "BuoyUp nói dễ hiểu", nhật ký vòng vay, tài liệu bàn giao, đặc tả năm agent) và trích lại nguyên văn, kèm nguồn. Bạn có thể hỏi về quy trình vay, hạn mức, lãi, cách trả nợ, các agent, ngân hàng, FATE, blockchain, RAG hay cách dùng demo. Câu hỏi về luật sẽ kèm các điều luật gần nhất. Câu nào mình chưa trả lời được, bạn ghi ở tab **Góp ý**.
