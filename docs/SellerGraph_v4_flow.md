# SellerGraph v4 — luồng xử lý và hồ sơ người vay cần nộp

Bản viết lại bằng lời của `docs/SellerGraph_core_tech_v4.html`, để đọc không
cần mở trình duyệt. Phần 1 là luồng tám bước. Phần 2 là danh sách người vay
phải cung cấp cho WeBank, chia theo tầng vay. Phần 3 là những gì WeBank tự
lấy mà người vay không phải nộp, chỉ phải ủy quyền.

Ví dụ xuyên suốt: chị Lan bán áo khoác trên Douyin, xin vay để nhập 5.000 áo
giá khai 80 tệ cho ngày 11/11.

---

## Phần 1 · Luồng tám bước

Nguyên tắc chung của v4: **mọi con số do giải thuật cố định tính**, agent
chỉ đọc, đối chiếu, viết và giải thích; FATE để đối chiếu với đối tác mà
không ai đưa dữ liệu gốc; FISCO BCOS là sổ chung giữ bằng chứng; khoản Tầng 2
và khoản có cờ do con người ký; mọi ngưỡng đặt tay có lộ trình hiệu chuẩn
qua khối B0.

### Bước 1 · Nộp hồ sơ và ủy quyền

Người bán nộp giấy tờ, dữ liệu cửa hàng, kế hoạch nếu vay Tầng 2, và ký ủy
quyền. **Agent 1** làm việc như nhân viên quầy: kiểm tra đủ giấy chưa, các
giấy có khớp nhau không, thiếu thì yêu cầu bổ sung. Ngay lúc nộp, hệ thống
xin ủy quyền tra cứu và trích nợ, để các bước sau tra cứu hợp lệ.

Đầu ra: hồ sơ đủ, hash của ủy quyền ghi vào **Sổ ủy quyền** trên FISCO BCOS.

Chị Lan: nộp CCCD, dữ liệu cửa hàng Douyin, kế hoạch nhập 5.000 áo, ký ủy
quyền. Ủy quyền của chị được ghi lên chuỗi.

### Bước 2 · Thu thập và xác minh dữ liệu

Luật 断直连 từ 2021 cấm sàn đưa thẳng dữ liệu người dùng cho ngân hàng, nên
WeBank chỉ lấy từ năm đường hợp pháp: người bán tự nộp, dữ liệu WeBank tự
có, báo cáo tín dụng, nền tảng thông tin dòng tiền của ngân hàng trung ương,
và FATE với đối tác.

Tài liệu người bán nộp đi qua **mô hình trích xuất** chỉ điền vào các ô cố
định như tên, số tiền, ngày. Mô hình này không có công cụ nào khác, nên lệnh
ẩn trong tài liệu không làm gì được. Sau đó hệ thống tự đối chiếu: đơn hàng
với vận đơn, thanh toán với dòng tiền.

**FATE** chạy khi ủy quyền còn hiệu lực trên chuỗi, mỗi lần chạy ghi vào
**Sổ lần chạy FATE**:

- Việc 1, đối chiếu vận đơn với công ty vận chuyển bằng PSI. Chị Lan khai
  1.000 mã, công ty vận chuyển xác nhận 870, tức 87%.
- Việc 2, hỏi bên hóa đơn điện tử giá nhập trung bình ba tháng của chính
  người bán. Chị Lan khai 80 tệ, hóa đơn cho thấy 62 tệ.
- Việc 3, tùy chọn, điểm hóa đơn cho người hồ sơ mỏng bằng học liên kết.

Đầu ra: kho dữ liệu đã xác minh, cộng hai con số từ FATE.

### Bước 3 · Giải thuật tính mọi con số

**Bộ điều phối** là code cố định, không phải AI. Nó gọi các khối B1 đến B11
theo thứ tự, mỗi khối là công thức hoặc luật, cùng đầu vào thì cùng đầu ra.

| Khối | Tính gì | Chị Lan |
|---|---|---|
| B1 Nhóm khách hàng | Bốn nhóm theo lịch sử với WeBank và tín dụng nơi khác | Nhóm 2, có tín dụng nơi khác |
| B2 Hạn mức Tầng 1 | Tiền đơn đã thanh toán chưa hoàn 20 ngày × 0,80 × (1 − tỷ lệ hoàn) | Không dùng, chị vay Tầng 2 |
| B3 Giá nhập hợp lý, nhu cầu vốn | Giá khai vượt 1,2 lần giá hóa đơn thì dùng giá hóa đơn; nhu cầu = giá trị nhập − tồn kho − vốn tự có − vay khác | 5.000 × 62 = 310.000; nhu cầu 210.000 |
| B4 Dự báo thận trọng | Nhỏ hơn của (năm trước × tăng trưởng) và (trung bình hai mùa) × hệ số thận trọng ngành | 330.000 × 0,70 = 231.000 |
| B5 Trần trích nợ | (1 − biên lãi gộp) ÷ (1 − phí sàn) | 63,16% |
| B6 Bảng điểm → hạng | Cộng điểm từng chỉ số, ra hạng A đến E; khớp vận đơn dưới 95% thì hạ một hạng | Hạng C |
| B7 Lãi suất | Tra bảng theo hạng, có sàn chi phí | 12% một năm |
| B8 Hạn mức Tầng 2 | Nhỏ nhất của nhu cầu, trần dòng tiền, trần theo nhóm, trần tuyệt đối | 140.288 |
| B9 Tỷ lệ trích và lịch trả | Tỷ lệ = (hạn mức + lãi) ÷ dự báo, làm tròn lên 1%, phải dưới trần; không đạt thì hạ hạn mức | Hạn mức 139.900, trích 63%, ân hạn 23 ngày |
| B10 Gian lận | Gom nhóm theo CCCD, điện thoại, địa chỉ, mã số thuế, tài khoản; cờ giá lệch, vận đơn thấp | Hai cờ: giá lệch 29%, vận đơn 87% |
| B11 Cảnh báo sớm | Chạy sau giải ngân | Chưa áp dụng |
| B0 Hiệu chuẩn tham số | Chạy mỗi quý trên hồ sơ đã hoàn thành, đề xuất lại các ngưỡng đặt tay, hội đồng ký | Không chạy cho từng hồ sơ |

Đầu ra: **phiếu đề xuất** gồm tầng, nhóm, hạng, hạn mức, lãi, kỳ hạn, tỷ
lệ trích, ân hạn, sàn lũy kế, cờ, lý do từng khối, và kết luận có cần cán
bộ không.

### Bước 4 · Agent thẩm định và phản biện

**Agent 2** đọc phiếu đề xuất, kế hoạch và hợp đồng, chỉ các trường đã
trích, viết tờ trình và đề xuất số tiền không vượt trần. **Agent 3** đánh
giá độc lập trước khi đọc tờ trình, chủ động tìm lý do từ chối. Cả hai
không tự tính số, không vượt trần, không tự phê duyệt, không đọc văn bản gốc.

Đầu ra: tờ trình, phản biện, và cờ "hai agent bất đồng" nếu có.

### Bước 5 · Phân luồng, cổng con người, kết quả

Tầng 1, vay theo đơn đã có tiền: tự động hoàn toàn nếu dưới ngưỡng số tiền
và không có cờ. Tầng 2, vay trước khi có đơn: cán bộ ký bắt buộc.

Chuyển cán bộ khi: số tiền vượt ngưỡng; Agent 2 và 3 bất đồng; hạng sát
ngưỡng từ chối kèm cờ gian lận; người bán yêu cầu; hoặc nợ xấu của nhóm
duyệt tự động vượt mức.

Kết quả là đề xuất gồm hạn mức, lãi, lịch trả, hoặc từ chối kèm luật đã áp
theo Điều 24 Luật Bảo vệ thông tin cá nhân, gợi ý hạn mức thấp hơn hoặc lộ
trình cải thiện. Quyết định vào nhật ký, dấu vân tay tổng định kỳ neo lên
FISCO BCOS.

Chị Lan: Tầng 2 cộng hai cờ nên bắt buộc cán bộ. Chị giải thích 130 đơn là
khách tự đến lấy, nộp chứng từ, cán bộ chấp nhận nhưng giữ việc hạ hạng.
Đề xuất 139.900 tệ, lãi 12%, kỳ hạn 4 tháng.

### Bước 6 · Giải ngân thẳng tới nhà cung cấp

Người bán bấm chấp nhận. **Agent 4** kiểm tra nhà cung cấp lần cuối: có tồn
tại, không cùng nhóm liên kết với người bán, giá hợp lý. Rồi giải ngân một
lần, thẳng cho nhà cung cấp, không qua tay người bán. Lệnh ghi vào **Sổ theo
dõi giải ngân** trên chuỗi; nhà cung cấp ký xác nhận đã nhận tiền; công ty
vận chuyển ghi vận đơn giao hàng. Quá số ngày cam kết mà chưa có vận đơn thì
hợp đồng thông minh tự chuyển thành vi phạm cam kết.

Chị Lan: 139.900 tệ chuyển tới nhà cung cấp áo khoác. Vận đơn phải có trong
10 ngày.

### Bước 7 · Thu hồi theo dòng tiền và giám sát

Mỗi lần sàn trả tiền hàng về tài khoản WeBank, trích theo tỷ lệ đã chốt,
không vượt trần, tức chỉ lấy lại phần giá vốn. Dưới sàn lũy kế thì trích tài
khoản WeBank, rồi các tài khoản đã ủy quyền. Hash từng lần trích ghi vào
**Biên nhận trích nợ**.

**Agent 5 và 6** kiểm tra cam kết hằng ngày theo khối B11: xanh tự theo dõi,
vàng phân tích nguyên nhân, đỏ chuyển cán bộ. Nhắc lịch, giãn nợ nếu khó
khăn là thật.

Chị Lan: sau 23 ngày ân hạn, trích 63% mỗi lần tiền về. Cuối kỳ tổng trả
không quá 145.496 tệ.

### Bước 8 · Vòng vay mới

Trả tốt và dẫn dòng tiền về WeBank ổn định thì hạn mức cao hơn, lãi thấp
hơn, quay lại bước 1. Hồ sơ đã hoàn thành trở thành dữ liệu cho B0 hiệu
chuẩn ngưỡng ở quý sau, nếu người bán đã ủy quyền mục đích cải tiến mô hình.

---

## Phần 2 · Người vay phải nộp gì cho WeBank

### 2.1 Mọi người vay, bất kể tầng

| Nộp gì | Vì sao cần | Dùng ở đâu |
|---|---|---|
| CCCD của chủ cửa hàng, giấy phép kinh doanh nếu có, mã số thuế | Định danh, khóa khớp cho FATE, gom nhóm liên kết chống gian lận | Agent 1, B10, FATE Việc 2 |
| Dữ liệu cửa hàng ít nhất 12 tháng xuất từ sàn: doanh số, số đơn, tỷ lệ hoàn, tỷ lệ hủy, điểm cửa hàng, ngày mở | Đầu vào của bảng điểm và dự báo | B6, B4, B11 |
| File đối soát thanh toán của sàn: tiền đơn đã thanh toán, đơn hoàn, phí sàn | Tính hạn mức Tầng 1, trần trích nợ, đối chiếu với dòng tiền | B2, B5, bước 2 |
| Số tài khoản nhận tiền hàng và các tài khoản ngân hàng khác đang dùng | Dẫn dòng tiền về WeBank, trích nợ khi thiếu sàn | Bước 7 |
| Danh sách mọi cửa hàng đang vận hành, kể cả sàn khác | Cam kết khai báo đầy đủ, chống tách doanh số | B10, cam kết |
| Bộ ủy quyền, xem phần 3 | Không có thì WeBank không tra cứu, không chạy FATE, không trích nợ được | Bước 1, 2, 7 |

### 2.2 Thêm cho Tầng 1, vay theo đơn đã có tiền

Không cần gì thêm ngoài mục 2.1. Hạn mức tính từ tiền đơn đã thanh toán chưa
hoàn trong 20 ngày gần nhất. Kỳ hạn 1 tháng, trích theo từng đơn khi tiền đơn
đó về.

### 2.3 Thêm cho Tầng 2, vay trước khi có đơn

Điều kiện vào Tầng 2: đã bán qua ít nhất hai mùa cao điểm, và không thuộc
nhóm 3 chưa từng vay hoặc nhóm 4 từng trễ hạn.

| Nộp gì | Vì sao cần | Dùng ở đâu |
|---|---|---|
| Kế hoạch chiến dịch: sự kiện nào, ngày nào, mặt hàng, số lượng định nhập, đơn giá khai | Tính giá trị nhập và nhu cầu vốn | B3 |
| Thông tin nhà cung cấp: tên, mã số thuế, tài khoản nhận tiền, số ngày giao hàng, hợp đồng hoặc báo giá | Kiểm tra nhà cung cấp, giải ngân thẳng, tính ân hạn | B10, Agent 4, B9 |
| Danh sách mã vận đơn của các đơn gần đây, ví dụ tháng trước | Đối chiếu với công ty vận chuyển qua PSI | FATE Việc 1, B6, B10 |
| Tồn kho dùng được cho chiến dịch, theo giá vốn | Trừ khỏi nhu cầu vốn | B3 |
| Vốn tự có bỏ vào chiến dịch | Trừ khỏi nhu cầu vốn | B3 |
| Khoản vay khác dành cho chính chiến dịch này | Trừ khỏi nhu cầu vốn, đối chiếu báo cáo tín dụng | B3 |
| Tiền thực nhận của cùng chiến dịch năm trước | Gốc của dự báo | B4 |
| Tiền thực nhận của hai mùa cao điểm gần nhất | Trần của dự báo | B4 |
| Tiền thực nhận bình quân tháng 12 tháng qua | Trần theo nhóm khách hàng | B8 |
| Biên lãi gộp ước tính, nếu không lấy được qua FATE hóa đơn | Trần trích nợ | B5 |
| Chứng từ giá nhập ba tháng gần nhất, nếu không có bên hóa đơn điện tử | Thay cho FATE Việc 2 | B3 |

Chị Lan nộp: kế hoạch 5.000 áo giá 80 tệ cho 11/11, nhà cung cấp giao trong
7 ngày, 1.000 mã vận đơn tháng trước, tồn kho 40.000, vốn tự có 60.000,
không vay nơi khác, 11/11 năm trước thu 300.000, hai mùa gần nhất trung bình
330.000, bình quân tháng 166.700, biên lãi gộp 40%, phí sàn 5%.

### 2.4 Cam kết ký kèm khi nhận tiền

- Doanh số tháng ít nhất 3 lần khoản trả tháng.
- Điểm cửa hàng không dưới 4,0.
- Dẫn dòng tiền bán hàng về tài khoản WeBank suốt kỳ vay.
- Tiếp tục chia sẻ dữ liệu cửa hàng hằng tháng.
- Khai báo mọi cửa hàng, báo ngay khi mở cửa hàng mới.
- Vận đơn giao hàng phải có trong 10 ngày sau khi nhà cung cấp nhận tiền.

Vi phạm cam kết là tín hiệu cho B11, không tự động là vỡ nợ.

---

## Phần 3 · Người vay không phải nộp, chỉ phải ủy quyền

Bộ ủy quyền ký ở bước 1, hash ghi lên Sổ ủy quyền, có phạm vi và thời hạn,
rút được bất kỳ lúc nào. Rút thì FATE dừng chạy ngay từ lần sau.

| Ủy quyền cho WeBank | Để lấy gì | Từ đâu |
|---|---|---|
| Tra cứu báo cáo tín dụng | Trễ hạn, số lần tra cứu, nợ hiện có, phân nhóm khách hàng | Trung tâm thông tin tín dụng |
| Tra cứu nền tảng thông tin dòng tiền | Tiền thực về tài khoản, để xác nhận số người bán tự khai | Nền tảng của ngân hàng trung ương |
| Đối chiếu với công ty vận chuyển | Tỷ lệ vận đơn khai có thật | FATE Việc 1 |
| Đối chiếu với bên hóa đơn điện tử | Giá nhập trung bình ba tháng, biên lãi gộp | FATE Việc 2 |
| Trích nợ các tài khoản đã kê khai | Thu hồi khi tiền hàng về và khi thiếu sàn | Bước 7 |
| Mục đích cải tiến mô hình, tùy chọn | Hồ sơ sau khi hoàn thành được dùng để hiệu chuẩn ngưỡng | B0 |

Người vay **không** phải nộp: sao kê ngân hàng khác, hóa đơn mua hàng gốc,
danh sách khách hàng, dữ liệu của công ty vận chuyển. Những thứ này hoặc
WeBank tự có, hoặc đối tác giữ và chỉ trả lời qua FATE.

---

## Phần 4 · Tóm tắt một trang cho người bán

1. Chuẩn bị CCCD, giấy phép, xuất dữ liệu cửa hàng 12 tháng và file đối soát.
2. Vay Tầng 1 thì xong ở đây, tiền về trong ngày nếu hồ sơ sạch.
3. Vay Tầng 2 thì thêm kế hoạch chiến dịch, nhà cung cấp, mã vận đơn tháng
   trước, số tồn kho, vốn tự có, số liệu mùa trước.
4. Ký ủy quyền tra cứu và trích nợ. Không ký thì không vay được.
5. Nhận phiếu đề xuất có giải thích từng con số. Thấy chưa đúng thì yêu cầu
   cán bộ xem lại.
6. Bấm chấp nhận, tiền đi thẳng tới nhà cung cấp.
7. Bán hàng, tiền về WeBank, hệ thống trích đúng phần giá vốn, phần lãi giữ lại.
8. Trả tốt thì lần sau hạn mức cao hơn, lãi thấp hơn.
