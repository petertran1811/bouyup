# Đề xuất đề tài dự thi — FinTechathon 2026, Bảng Quốc tế

> **Tài liệu phân tích lựa chọn đề tài**
> Ngày lập: 12/09/2026 · Hạn nộp bài: **22:59 ngày 20/10/2026 (giờ Việt Nam)**
> Nguồn: `international-topics-rules-en.pages` + khảo sát nghiên cứu học thuật và sản phẩm thương mại

---

## Mục lục

1. [Tóm tắt điều hành](#1-tóm-tắt-điều-hành)
2. [Bối cảnh cuộc thi](#2-bối-cảnh-cuộc-thi)
3. [Phân tích khuôn mẫu thắng giải 7 kỳ trước](#3-phân-tích-khuôn-mẫu-thắng-giải-7-kỳ-trước)
4. [Khung phương pháp chọn đề tài](#4-khung-phương-pháp-chọn-đề-tài)
5. [Đề tài #1 — Topic C: Tài chính xuyên biên giới & du học sinh](#5-đề-tài-1--topic-c-tài-chính-xuyên-biên-giới--du-học-sinh)
6. [Đề tài #2 — Topic D: Trợ lý bảo hiểm](#6-đề-tài-2--topic-d-trợ-lý-bảo-hiểm)
7. [Đề tài #3 — Topic F: Agent Wallet on-chain](#7-đề-tài-3--topic-f-agent-wallet-on-chain)
8. [Lý do loại 3 đề tài còn lại](#8-lý-do-loại-3-đề-tài-còn-lại)
9. [Bảng so sánh tổng hợp](#9-bảng-so-sánh-tổng-hợp)
10. [Khuyến nghị và việc cần làm ngay](#10-khuyến-nghị-và-việc-cần-làm-ngay)
11. [Phụ lục: Danh mục tài liệu tham khảo](#11-phụ-lục-danh-mục-tài-liệu-tham-khảo)

---

## 1. Tóm tắt điều hành

| | |
|---|---|
| **Khuyến nghị chính** | **Topic C — Trợ lý tài chính xuyên biên giới & du học sinh** |
| **Phương án dự phòng** | **Topic D — Trợ lý bảo hiểm** (ít cạnh tranh nhất) |
| **Phương án rủi ro cao** | **Topic F — Agent Wallet on-chain** (chỉ chọn nếu đội có kinh nghiệm deploy mainnet) |
| **Loại bỏ** | Topic A (bão hòa), Topic B (prior art quá dày + rào cản pháp lý), Topic E (thiếu dữ liệu thật) |

> 🔑 **Phát hiện nền tảng:** Bảng Quốc tế 2026 là **kỳ đầu tiên trong lịch sử cuộc thi** — không có tiền lệ để tham khảo, nhưng cũng không đội nào có lợi thế kinh nghiệm. Phân tích 7 kỳ của bảng Trong nước (mục 3) cho thấy **trục "tin cậy · giám sát · kiểm soát rủi ro" là trục thắng giải lặp lại qua mọi kỳ** — xác nhận rằng 30% điểm an toàn/tuân thủ mới là nơi phân định thắng thua, không phải phần tính năng.

**Luận điểm cốt lõi:** Trong một cuộc thi mà mỗi hạng giải chỉ có **1 suất**, lựa chọn đề tài quan trọng ngang với chất lượng thực thi. Ba đề tài được chọn dựa trên ba tiêu chí: *khoảng trống nghiên cứu còn lớn*, *có bề mặt rủi ro thật để ghi 30% điểm an toàn/tuân thủ*, và *tạo được bằng chứng vận hành thuyết phục*.

---

## 2. Bối cảnh cuộc thi

### 2.1. Thông tin nền

| Hạng mục | Nội dung |
|---|---|
| **Chủ đề** | *AI as a Financial Participant* — AI với vai trò một chủ thể tham gia tài chính |
| **Yêu cầu** | Xây dựng AI agent hoàn thành tác vụ thực tế trong tình huống tài chính |
| **Số đề tài** | Chọn 1 trong 6 |
| **Quy mô đội** | 2–5 sinh viên, mỗi người chỉ 1 đội trên cả hai bảng |
| **Ràng buộc đội** | ≥ 60% thành viên không mang quốc tịch Trung Quốc |
| **Ngôn ngữ** | Tiếng Anh (bài nộp, thuyết trình, chấm thi) |
| **Hạn nộp** | 20/10/2026, 23:59 giờ Bắc Kinh = **22:59 ngày 20/10 giờ VN** |
| **Chung kết** | 21–23/11/2026 tại Thâm Quyến (bắt buộc ≥1 thành viên dự trực tiếp) |
| **Giải thưởng** | Tổng 250.000 RMB — Nhất 100k, Nhì 80k, Ba 50k, Sáng tạo 20k, Khuyến khích (nhiều giải) |

### 2.2. Thang điểm — yếu tố chi phối mọi quyết định

| Tiêu chí | Trọng số | Hàm ý khi chọn đề tài |
|---|---|---|
| Hoàn thành tác vụ | **40%** | Cần benchmark/test case đo được bằng số, không chỉ demo đẹp |
| An toàn & tuân thủ | **30%** | Đề tài chỉ "đọc và tư vấn" rất khó ghi điểm mảng này |
| Đổi mới & tương tác | **30%** | Prior art quá dày = mất điểm |
| Điểm thưởng on-chain | **0–5 điểm** | Xem mục 2.3 |

### 2.3. Điểm mơ hồ cần làm rõ — có ảnh hưởng lớn đến chiến lược

Thể lệ có mâu thuẫn nội tại về điểm thưởng on-chain:

- **Mục 2** gắn "0–5 point challenge bonus" riêng vào Topic F.
- **Mục 3** đặt "Challenge bonus (on-chain exploration): 0–5 points" trong bộ tiêu chí *chung cho cả 6 đề tài*, kèm câu khẳng định *"All six topics share the same core capability requirements and scoring criteria"*.

**Cách đọc có lợi nhất:** chọn đề tài A–E rồi bổ sung một thành phần on-chain → vừa tránh cạnh tranh trực diện ở Topic F (nơi tập trung các đội mạnh về DeFi), vừa lấy được điểm thưởng.

> ⚠️ **Hành động bắt buộc:** Gửi email `info@ican-x.com` xác nhận điểm này **trước khi chốt đề tài**. Câu trả lời có thể thay đổi hoàn toàn thứ tự ưu tiên bên dưới.

---

## 3. Phân tích khuôn mẫu thắng giải 7 kỳ trước

### 3.1. Phát hiện then chốt: Bảng Quốc tế 2026 là kỳ ĐẦU TIÊN

Trang chính thức của **IEEE CIS Shenzhen Chapter** xác nhận nguyên văn: cuộc thi *"launches its first-ever **International Track**, open to students enrolled at universities outside China."*

**Hai hệ quả trái chiều:**

| | |
|---|---|
| ❌ **Bất lợi** | Không tồn tại "đề tài chiến thắng của bảng Quốc tế" để tham khảo trực tiếp |
| ✅ **Lợi thế** | Không đội nào có kinh nghiệm bảng này; số đội dự thi nhiều khả năng thấp hơn hẳn bảng Trong nước |

Vì vậy phần dưới phân tích **7 kỳ của bảng Trong nước (2019–2025)** để trích xuất *khuôn mẫu chấm giải* — cùng một BTC, cùng nhóm giám khảo WeBank, cùng triết lý.

### 3.2. Danh sách quán quân các kỳ

| Kỳ | Năm | Quy mô | Hạng mục | Tác phẩm đoạt giải Nhất | Đơn vị |
|---|---|---|---|---|---|
| 2 | 2020 | 700+ SV, 212 trường, 115 tác phẩm | **AI** | **"TAN's fellow"** — phá thành công hệ thống nhận diện khuôn mặt black-box hoàn toàn chưa biết | ĐH Công nghệ Bắc Kinh (BIT) |
| | | | **Blockchain** | **"Time Bank" (紫荆路航)** — nền tảng thiện nguyện chuyển thời gian tình nguyện thành tài sản số cá nhân | ĐH Sư phạm Hoa Nam |
| 3 | 2021 | — | AI | Đề bài mở dựa trên **FATE** (federated learning: joint risk control, marketing) | — |
| | | | Blockchain | Đề bài dựa trên **FISCO BCOS** | — |
| 4 | 2022 | 1.400+ SV, 500+ đội, 364 trường, 230+ tác phẩm | 3 hạng mục | Tác phẩm đoạt giải tập trung vào: **tài trợ chuỗi cung ứng, tái chế công nghiệp, bio-cloud, phát thải carbon, phân quyền dữ liệu, privacy computing** | — |
| 5 | 2023 | 1.500+ SV, ~300 đội, 180 tác phẩm | **AI** | **"OncoFed"** — chẩn đoán khối u dựa trên **FATE** (federated learning) | Đội "Aa100K": ĐH Nam Kinh, Tây An Điện tử, Hoa Đông Sư phạm, Tây Bắc Công nghiệp, Vũ Hán *(5 trường)* |
| | | | **Blockchain** | **"A14C"** — nền tảng vận hành sản phẩm văn hóa số cho sáng tạo AIGC | ĐH Bưu chính Viễn thông Bắc Kinh |
| | | | **Product Manager** | **"Digital Steward Platform for WeBank"** — nền tảng quản gia số dựa trên đối thoại tương tác | Bắc Hàng + ĐH Truyền thông TQ + **ESCP Business School (Pháp)** |
| 6 | 2024 | 2.500+ SV | **Blockchain 🥇** | **AIGC模型可信监管交易溯源平台** — nền tảng giám sát tin cậy và truy vết giao dịch mô hình AIGC | ĐH Công nghệ Bắc Kinh |
| | | | **Blockchain 🥈** | **CipherBridge** — nền tảng tính toán đa bên trên bản mã có thể xác minh | HKUST (Quảng Châu) |
| | | | **Blockchain 🥉** | Hệ thống quản lý bản quyền AIGC toàn vòng đời trên blockchain | ĐH Thiên Tân |
| 7 | 2025 | 1.709 SV, 372 đội, 270 trường | **AI 🥇** | **《灵操盘》** — engine giao dịch định lượng **zero-code**, biến ý tưởng đầu tư bằng ngôn ngữ tự nhiên thành chiến lược kiểm thử và thực thi được | — |
| | | | **Data Analysis 🥇** | **Mô hình Mixture-of-Experts lai có khả năng mở rộng cho phát hiện gian lận chống rửa tiền (AML)** | — |

> ⚠️ **Về độ đầy đủ của dữ liệu:** Không tìm được danh sách giải đầy đủ cho kỳ 2019 (kỳ 1), kỳ 2021, tên cụ thể các đội 2022, và giải Nhì/Ba bảng AI 2025. Trang chính thức cũ `fintech.webank.com` hiện không truy cập được (DNS không phân giải), và một số danh sách trên báo Trung Quốc nằm trong ảnh nên không trích xuất được. Mọi mục ghi ở trên đều có nguồn kiểm chứng (xem Phụ lục).

### 3.3. Bảy khuôn mẫu rút ra

#### Khuôn mẫu #1 — Chủ đề "tin cậy · giám sát · kiểm soát rủi ro" thắng lặp đi lặp lại

Đây là tín hiệu mạnh nhất trong toàn bộ dữ liệu:

| Năm | Tác phẩm thắng | Trục cạnh tranh |
|---|---|---|
| 2020 | Phá hệ thống nhận diện khuôn mặt black-box | An ninh / tấn công đối kháng |
| 2022 | Privacy computing, phân quyền dữ liệu | Bảo mật dữ liệu |
| 2023 | OncoFed — federated learning (dữ liệu y tế không rời bệnh viện) | Bảo vệ quyền riêng tư |
| 2024 | Giám sát & truy vết AIGC 🥇 · Tính toán đa bên **có thể xác minh** 🥈 · Quản lý bản quyền 🥉 | **Cả 3 giải đều là governance/trust** |
| 2025 | Phát hiện gian lận AML 🥇 · 《灵操盘》 có module **风控 (risk control)** | Chống gian lận / kiểm soát rủi ro |

> ✅ **Xác nhận thực nghiệm cho luận điểm của tài liệu này:** trục 30% "an toàn & tuân thủ" không phải mục phụ — **nó là trục thắng giải lịch sử của cuộc thi.**

#### Khuôn mẫu #2 — Winners dùng bộ công nghệ mã nguồn mở của chính WeBank

- **2021:** đề bài xây trực tiếp trên **FATE** và **FISCO BCOS**
- **2023:** quán quân AI **OncoFed "based on FATE"**
- **2024:** cả 3 giải blockchain đều dùng **FISCO BCOS** làm framework

**Bối cảnh giám khảo:** Yang Qiang (杨强), Chief AI Advisor của WeBank — người phát biểu tổng kết 2025 — là một trong những người khai sinh federated learning và đứng sau FATE. Hội đồng chấm gồm *"WeBank industry experts"*. Dùng stack của họ không chỉ là lựa chọn kỹ thuật, đó là **tín hiệu văn hóa**.

> 💡 **Áp dụng cho 2026:** thể lệ bảng Quốc tế không bắt buộc dùng stack WeBank, nhưng nếu kiến trúc có chỗ tự nhiên cho **FATE** hoặc **FISCO BCOS**, đó là điểm cộng gần như chắc chắn. Xem mục 5.5 — Topic C có chỗ đặt FATE mà không hề gượng ép.

#### Khuôn mẫu #3 — Thắng bằng NỀN TẢNG HOÀN CHỈNH, không phải một mô hình

《灵操盘》 2025 phủ trọn chuỗi `xử lý dữ liệu → mô hình hóa chiến lược → kiểm soát rủi ro → giao dịch thực`, dùng **kiến trúc multi-agent** + knowledge graph tài chính động + cơ chế suy luận tin cậy.

Các tác phẩm thắng khác đều là "平台" (nền tảng) hoặc "系统" (hệ thống). **Không tác phẩm nào thắng chỉ nhờ một mô hình đơn lẻ có độ chính xác cao.**

Điều này khớp chính xác yêu cầu 2026: không được làm chatbot, phải làm **agent đi hết vòng đời tác vụ**.

#### Khuôn mẫu #4 — Framing "hạ thấp rào cản" rất được ưa chuộng

《灵操盘》 được mô tả là giải quyết *"量化投资门槛高、策略落地难"* (rào cản đầu tư định lượng cao, chiến lược khó triển khai) — và chữ **"zero-code"** nằm ngay đầu phần mô tả. "Time Bank" 2020 biến thời gian tình nguyện thành tài sản số — cũng là framing dân chủ hóa tiếp cận tài chính.

> 💡 **Áp dụng:** Topic C nên được đóng khung là *"du học sinh mất 6,2% mỗi lần chuyển tiền vì không có công cụ nào tối ưu hóa giúp họ"* — đúng mạch "hạ rào cản".

#### Khuôn mẫu #5 — Đội đa trường, đa quốc gia đã từng thắng

Quán quân AI 2023 gồm **5 trường đại học**; quán quân Product Manager 2023 có **ESCP Business School (Pháp)** trong đội hình. BTC không chỉ chấp nhận đội xuyên trường/xuyên biên giới — họ **đã trao giải Nhất** cho kiểu đội này.

#### Khuôn mẫu #6 — Đường đi của chủ đề qua các năm

```
2020  Bảo mật đối kháng
  ↓
2021  Federated learning (FATE)
  ↓
2022  Privacy computing · Carbon · Chuỗi cung ứng
  ↓
2023  Federated learning ứng dụng y tế · AIGC
  ↓
2024  Quản trị & truy vết AIGC        ← chuyển từ "làm được gì" sang "kiểm soát thế nào"
  ↓
2025  LLM Multi-agent · Chống rửa tiền
  ↓
2026  AI as a Financial Participant   ← agent tự hành động
```

Quỹ đạo rất rõ: BTC đi từ **"công nghệ mới"** → **"quản trị công nghệ mới"**. Chủ đề 2026 là bước tiếp theo hợp logic, và **trục quản trị vẫn sẽ là nơi phân định thắng thua**.

#### Khuôn mẫu #7 — Tiêu chí bất thành văn của giám khảo

Yang Qiang, phát biểu tổng kết 2025:

> *Fintech tương lai cần "**đổi mới công nghệ + triển khai theo kịch bản + tạo ra giá trị**", với nhân tài là động lực cốt lõi.*

Ba vế này ánh xạ gần như 1-1 vào thang điểm 2026: đổi mới (30%) + hoàn thành tác vụ trong kịch bản thật (40%) + giá trị tạo ra. Vế giữa — *"scenario implementation"* — giải thích vì sao thể lệ 2026 **bắt buộc nộp bằng chứng vận hành**: họ không tin demo, họ tin log.

### 3.4. Ba khuôn mẫu này thay đổi gì trong đánh giá đề tài

| Đề tài | Mức khớp với khuôn mẫu thắng giải | Kết luận |
|---|---|---|
| **C — Xuyên biên giới** | 🟢 Framing hạ rào cản (KM#4) · 🟢 Chỗ tự nhiên cho federated learning (KM#2) · 🟢 Nền tảng nhiều tầng (KM#3) · 🟡 Cần đẩy mạnh hơn phần kiểm soát rủi ro (KM#1) | **Giữ vị trí #1** — nhưng tái định vị thành *"cross-border compliance & routing engine"* thay vì *"trợ lý tài chính"* |
| **D — Bảo hiểm** | 🟢 Chống ảo giác = trust/governance (KM#1, đúng mạch 2024) · 🟡 Framing hạ rào cản yếu hơn · 🔴 Ít chỗ cho stack WeBank | Giữ vị trí #2 |
| **F — Agent Wallet** | 🟢 Kiểm soát rủi ro là trung tâm (KM#1) · 🟢 FISCO BCOS khớp hoàn hảo (KM#2) · 🔴 Không có lịch sử bảng Quốc tế để suy ra mức cạnh tranh | Giữ vị trí #3 |

### 3.5. Một con số để hiệu chỉnh kỳ vọng

Kỳ 2025: **372 đội → 10 đội vào chung kết mỗi bảng** ≈ tỷ lệ vào chung kết **2,7%**, và 1 giải Nhất cho mỗi bảng.

Bảng Quốc tế 2026 là kỳ đầu, mở cho sinh viên ngoài Trung Quốc, thi bằng tiếng Anh, yêu cầu ≥60% thành viên không mang quốc tịch Trung Quốc — **nhiều khả năng số đội thấp hơn đáng kể** so với bảng Trong nước. Không có số liệu để khẳng định tỷ lệ cụ thể, nhưng **cơ cấu giải thưởng thì chắc chắn**: bảng Quốc tế có giải Nhất/Nhì/Ba/Sáng tạo **riêng**, không chia chung với bảng Trong nước.

---

## 4. Khung phương pháp chọn đề tài

Thay vì hỏi "đề tài nào hay nhất", tài liệu này sàng lọc 6 đề tài qua 4 câu hỏi bám sát thang điểm:

1. **Có đo được "hoàn thành tác vụ" bằng con số không?** *(40% điểm)*
   Có benchmark công khai để đối chiếu, hoặc có thể tự dựng bộ test case có đáp án tham chiếu?

2. **Có bề mặt rủi ro thật để thiết kế phân tầng quyền không?** *(30% điểm)*
   Agent có thực sự *hành động* và gây hậu quả tài chính, hay chỉ trả lời câu hỏi?

3. **Prior art dày đến mức nào?** *(30% điểm)*
   Nếu đã có hàng chục sản phẩm và hàng chục paper phủ đúng bài toán, điểm đổi mới sẽ thấp.

4. **Có tạo được bằng chứng vận hành thật không?** *(điều kiện nộp bài bắt buộc)*
   Thể lệ yêu cầu log sandbox + video demo (đề tài thường) hoặc tx hash thật (đề tài on-chain).

Một tiêu chí phụ nhưng quan trọng: **mức độ đông đúc dự kiến của thí sinh**. Đề tài dễ hiểu và hào nhoáng sẽ hút phần lớn đội thi, làm giảm xác suất thắng ngay cả khi bài làm tốt.

---

## 5. Đề tài #1 — Topic C: Tài chính xuyên biên giới & du học sinh

> ⭐ **Khuyến nghị mạnh nhất**

### 5.1. Mô tả theo thể lệ

> *"Cross-border & Student Finance Assistant: Solutions addressing real financial pain points of international students and cross-border users, such as remittances, tuition payments, credit building, and multi-currency management."*

### 5.2. Cơ sở lý luận

#### a) Phù hợp với cấu trúc và mục tiêu của bảng đấu

Đây là bảng Quốc tế, yêu cầu ≥60% thành viên không mang quốc tịch Trung Quốc, và BTC nêu rõ mục tiêu *"đảm bảo tính quốc tế của bảng đấu"*. Topic C là đề tài **duy nhất mà bản thân danh tính của đội trở thành lợi thế cạnh tranh** — một đội Việt Nam làm về chuyển tiền xuyên biên giới và tài chính du học sinh có tính xác thực mà đội khác không thể giả lập. Giám khảo chấm 30% "đổi mới & tương tác" sẽ nhận ra điều này.

#### b) Bài toán có số liệu hậu thuẫn mạnh

- Kiều hối toàn cầu đạt **~905 tỷ USD** (2024), **8/10 quốc gia nhận tiền hàng đầu là thị trường mới nổi**.
- Chi phí gửi trung bình toàn cầu vẫn ở mức **6,2%** — cao hơn gấp đôi mục tiêu 3% của SDG 10.c (Liên Hợp Quốc).
- Việt Nam thuộc nhóm 10 nước nhận kiều hối lớn nhất thế giới.

Đây đúng là loại "real financial pain point" mà thể lệ yêu cầu nguyên văn.

#### c) Bề mặt rủi ro lý tưởng cho mảng 30% an toàn/tuân thủ

Chuyển tiền quốc tế chạm trực tiếp vào:
- KYC / AML
- Sanctions screening
- Hạn mức và quy định quản lý ngoại hối theo từng quốc gia
- Ngưỡng khai báo thuế của nước sở tại

Đây là "mỏ vàng" để viết Báo cáo tự đánh giá an toàn — thứ mà đề tài trợ lý chi tiêu cá nhân hoàn toàn không có.

### 5.3. Đã có ai làm chưa?

#### Sản phẩm thương mại — có, nhưng không phải dạng agent

| Nhóm | Ví dụ | Họ làm gì | Họ **không** làm gì |
|---|---|---|---|
| Chuyển tiền | Wise, Remitly, Revolut | Tỷ giá tốt, UX tốt | Không có agent tự lập kế hoạch; người dùng tự quyết định mọi thứ |
| Học phí | Flywire, Convera, PayMyTuition | Kênh đóng học phí chuyên biệt | Silo hoàn toàn, không nối với dòng tiền cá nhân |
| Tín dụng du học sinh | Nova Credit, Deserve, Zolve | Cấp thẻ cho sinh viên không có SSN | Không tư vấn chiến lược xây dựng tín dụng |
| Đa tiền tệ | Wise Multi-currency, Revolut | Giữ nhiều loại tiền | Không tối ưu thời điểm / tuyến đường tự động |

#### Nghiên cứu học thuật — khoảng trống rất lớn

Khi tìm nghiên cứu tại giao điểm *AI agent × kiều hối × tài chính du học sinh*, **gần như không có công trình nào phủ đúng bài toán này**. Chỉ tồn tại các mảnh rời ở tầng khác:

| Công trình | Nội dung | Vị trí so với bài toán |
|---|---|---|
| *From adoption to continuance: Stablecoins in cross-border remittances* (ScienceDirect) | Nghiên cứu hành vi chấp nhận stablecoin trong kiều hối, vai trò của năng lực tài chính số | Tầng hành vi người dùng — không có hệ thống |
| *SoK: Blockchain Agent-to-Agent Payments* (arXiv 2604.03733) | Khảo sát hạ tầng thanh toán agent-to-agent | Tầng giao thức — không phải ứng dụng người dùng |
| *FinMCP-Bench* (arXiv 2603.24943) | Benchmark 613 mẫu đánh giá agent gọi tool tài chính qua MCP | Benchmark tổng quát |
| *Finance Agent Benchmark* (arXiv 2508.00828) | Đánh giá agent trên tác vụ nghiên cứu tài chính thực tế | Benchmark tổng quát |

> ✅ **Kết luận:** Có sản phẩm nhưng là công cụ thủ công rời rạc; có nghiên cứu nhưng ở các tầng khác. **Chưa ai xây agent điều phối toàn bộ bài toán tài chính xuyên biên giới cho du học sinh.** Đây là lý do đề tài này được xếp số 1.

### 5.4. Hướng triển khai đề xuất

**Định vị: *cross-border compliance & routing engine* — agent điều phối tuyến chuyển tiền, KHÔNG phải chatbot tư vấn.**

> Tên gọi quan trọng: theo **Khuôn mẫu #3**, các tác phẩm thắng giải luôn tự gọi mình là "nền tảng"/"engine", không phải "trợ lý". Đặt chữ *compliance* lên trước chữ *routing* để báo hiệu ngay trục cạnh tranh.

Kịch bản mẫu — người dùng nói:

> *"Tôi cần 8.500 USD tới tài khoản trường ở Melbourne trước ngày 15/11, ngân sách phí tối đa 1,5%."*

Agent tự thực hiện:

1. **Quét song song nhiều tuyến** (ngân hàng truyền thống / Wise / stablecoin on-ramp), tính **tổng chi phí thực = phí + chênh lệch tỷ giá + chi phí trượt thời gian**
2. **Kiểm tra ràng buộc tuân thủ theo cặp quốc gia** — hạn mức, giấy tờ cần thiết, ngưỡng khai báo
3. **Lập kế hoạch chia nhỏ theo thời gian** nếu biến động tỷ giá có lợi
4. **Thực thi có phân tầng** — phần dưới ngưỡng tự động; phần trên ngưỡng yêu cầu người dùng phê duyệt

### 5.5. Tầng học liên kết (federated learning) — bổ sung theo Khuôn mẫu #2

Kiến trúc ở mục 5.4 mới có 4 bước điều phối. Dựa trên **Khuôn mẫu #2** (winners dùng stack WeBank) và **Khuôn mẫu #1** (trục kiểm soát rủi ro thắng giải), nên bổ sung một tầng thứ năm:

> **Mô hình đánh giá rủi ro giao dịch xuyên biên giới, huấn luyện bằng federated learning trên FATE.**

Các nút mô phỏng đại diện cho tổ chức tài chính ở những quốc gia khác nhau cùng huấn luyện mô hình phát hiện giao dịch bất thường, **mà không bên nào chia sẻ dữ liệu khách hàng thô**.

**Vì sao đây không phải gắn công nghệ cho đẹp:**

| Lý do | Giải thích |
|---|---|
| **Giải quyết ràng buộc pháp lý có thật** | GDPR và luật cư trú dữ liệu (data residency) của nhiều quốc gia **cấm** chuyển dữ liệu khách hàng qua biên giới. Đây chính là lý do federated learning tồn tại — và là lý do dữ liệu chống rửa tiền xuyên biên giới đến nay vẫn phân mảnh |
| **Đánh trúng 2 khuôn mẫu thắng giải cùng lúc** | KM#1 (kiểm soát rủi ro) + KM#2 (stack FATE của WeBank) |
| **Nối thẳng vào hai quán quân gần nhất** | AML (Data Analysis 🥇 2025) và federated learning (AI 🥇 2023 — OncoFed) |
| **Cho thêm chỉ số định lượng** | Có thêm số liệu để báo cáo ở mảng 40%: so sánh AUC/recall của mô hình federated với mô hình tập trung và mô hình đơn lẻ từng nút |

**Cách demo trong 10 phút:** dựng 3 nút (VN / AU / US), mỗi nút giữ tập giao dịch riêng, chạy vài vòng huấn luyện liên kết, rồi chiếu bảng so sánh: *mô hình từng nút đơn lẻ* vs *mô hình liên kết* vs *mô hình tập trung lý tưởng (không khả thi về pháp lý)*. Thông điệp: đạt gần chất lượng tập trung mà không vi phạm luật.

### 5.6. Bốn đòn bẩy ghi điểm

| Đòn bẩy | Cách làm | Điểm nhắm tới |
|---|---|---|
| **Điểm thưởng on-chain** | Đưa tuyến stablecoin (USDC) vào làm một lựa chọn routing → có **tx hash thật** nộp làm bằng chứng vận hành. Vốn hóa stablecoin đã vượt **300 tỷ USD** (2026) nên đây là lựa chọn thực tế, không phải gimmick | +0–5 điểm |
| **Hoàn thành tác vụ** | Tự xây bộ **~150 test case theo hành lang chuyển tiền** (VN→AU, VN→US, IN→UK, NG→UK...) với đáp án chi phí tham chiếu, báo cáo tỷ lệ agent chọn được tuyến tối ưu | 40% |
| **An toàn & tuân thủ** | Phân tầng quyền 3 cấp: *chỉ đọc → mô phỏng → thực thi có hạn mức*, cộng sanctions screening trước mỗi giao dịch | 30% |
| **Cộng hưởng văn hóa BTC** *(mới)* | Tầng federated learning trên **FATE** (mục 5.5) — đánh trúng Khuôn mẫu #1 và #2, nối thẳng vào hai tác phẩm quán quân gần nhất | 30% + 40% |

### 5.7. Rủi ro và cách phòng ngừa

| Rủi ro | Phòng ngừa |
|---|---|
| Sa đà thành "app so sánh tỷ giá" thay vì agent | Giữ phần **lập kế hoạch đa bước** và **thực thi tự động** làm trung tâm của demo và của slide |
| Khó lấy dữ liệu tỷ giá/phí thời gian thực từ nhiều nhà cung cấp | Dùng API công khai (Wise API, exchangerate API) + bảng phí công bố; ghi rõ nguồn trong tài liệu kỹ thuật |
| Tầng federated learning làm phình phạm vi công việc | Giữ ở quy mô 3 nút mô phỏng, dùng FATE dựng sẵn — mục tiêu là **chứng minh kiến trúc**, không phải đạt SOTA về mô hình |

---

## 6. Đề tài #2 — Topic D: Trợ lý bảo hiểm

> ⭐ **Lựa chọn "đường vòng" — ít cạnh tranh nhất**

### 6.1. Mô tả theo thể lệ

> *"Insurance Assistant: An insurance-scenario assistant capable of policy Q&A, coverage-gap analysis, and claims guidance, helping users understand and manage their insurance portfolios."*

### 6.2. Cơ sở lý luận

#### a) Đề tài ít đội chọn nhất trong 6

Bảo hiểm là lĩnh vực "khô", đòi hỏi kiến thức chuyên môn, nên phần lớn đội sinh viên sẽ đổ về Topic A (dễ hiểu) hoặc Topic F (hào nhoáng). Trong cuộc thi mà mỗi hạng giải chỉ có **1 suất**, chọn đề tài ít người chọn là chiến lược tối ưu xác suất — với điều kiện làm tốt.

#### b) Đề tài duy nhất mà "an toàn & tuân thủ" là bản chất bài toán, không phải phần đắp thêm

Đã có kiện tụng thật liên quan đến **chatbot bảo hiểm ảo giác gây lỗ hổng bảo hiểm** cho người mua. Nếu xây được cơ chế *mọi câu trả lời đều trích dẫn đúng điều khoản hợp đồng, và từ chối trả lời khi không tìm thấy căn cứ* — đó chính là 30% điểm an toàn đã nằm trong tay.

#### c) Có sẵn benchmark công khai để chứng minh bằng số

Lợi thế hiếm: không phải tự bịa ra cách đo hiệu quả. Xem mục 5.3.

### 6.3. Đã có ai làm chưa?

#### Nghiên cứu học thuật — khá dày, nhưng gần như toàn bộ dừng ở tầng hỏi-đáp

| Công trình | Nội dung | Giới hạn |
|---|---|---|
| **InsQABench** (arXiv 2501.10943) | Benchmark hỏi-đáp bảo hiểm tiếng Trung: Commonsense QA, Database QA, Clause QA. RAG-ReAct fine-tuned đưa GLM4-9B-Chat lên **83.63** điểm Clause QA | Chỉ hỏi-đáp, **không có agent hành động** |
| **Benchmarking LLMs for Quebec Insurance** (arXiv 2603.07825) | Benchmark AEPC-QA — 807 câu trắc nghiệm từ sổ tay chứng chỉ quản lý; phân tích *"advice gap"* khi số hóa phân phối bảo hiểm | Trắc nghiệm, không phải tác vụ thực |
| **Industrial-Scale Insurance LLM** (arXiv 2603.14463) | 39k mẫu, 9 chiều đánh giá, 50+ loại tác vụ, pipeline LLM-as-a-Judge, tập trung kiểm soát ảo giác | Là mô hình nền, không phải agent ứng dụng |
| **LLMs and Agentic AI in Insurance Decision-Making** (arXiv 2508.15110) | Khảo sát agentic AI trong quyết định bảo hiểm | Khảo sát, không có hệ thống triển khai |

#### Sản phẩm thương mại — tất cả đứng về phía nhà bảo hiểm

Lemonade (AI Jim xử lý bồi thường), Tractable (đánh giá thiệt hại xe qua ảnh), Shift Technology (phát hiện gian lận), Zelros. **Đây đều là công cụ cho công ty bảo hiểm, không phải trợ lý cho người mua bảo hiểm.**

> ✅ **Kết luận:** Nghiên cứu đã giải quyết *"hiểu điều khoản"*, chưa ai giải quyết *"phân tích lỗ hổng bảo hiểm và hành động"*. Sản phẩm thương mại đứng về phía nhà bảo hiểm. Khoảng trống nằm đúng chỗ thể lệ yêu cầu.

### 6.4. Hướng triển khai đề xuất

**Định vị: agent phân tích danh mục bảo hiểm chéo (cross-policy portfolio analysis).**

Đây là điều **không sản phẩm nào làm được**, vì mỗi công ty bảo hiểm chỉ nhìn thấy hợp đồng của chính mình.

Người dùng upload 4 hợp đồng từ 4 công ty khác nhau (y tế, nhân thọ, xe, du lịch) → agent:

1. **Trích xuất có cấu trúc** từng hợp đồng: phạm vi, hạn mức, loại trừ, thời gian chờ, mức miễn thường
2. **Dựng ma trận phủ sóng** theo `loại rủi ro × mức tổn thất` — chỉ ra:
   - **Chồng lấn** → đang trả phí 2 lần cho cùng một rủi ro
   - **Lỗ hổng** → rủi ro không có hợp đồng nào gánh
3. **Mô phỏng tình huống**: *"Nếu tôi nhập viện 200 triệu ở Nhật thì ai trả bao nhiêu, tôi tự trả bao nhiêu?"* — kèm đường dẫn trích dẫn tới từng điều khoản
4. **Hướng dẫn bồi thường** theo checklist, có thể tự động soạn hồ sơ

### 6.5. Ba đòn bẩy ghi điểm

| Đòn bẩy | Cách làm | Điểm nhắm tới |
|---|---|---|
| **Đo được bằng số** | Chạy trên **InsQABench** để có baseline so sánh trực tiếp với các mô hình đã công bố, cộng bộ test riêng cho phần phân tích lỗ hổng. Có con số đối chiếu với paper là cực kỳ thuyết phục | 40% |
| **Chống ảo giác là tính năng, không phải phụ lục** | Mọi khẳng định gắn với `policy_id + trang + đoạn`; dưới ngưỡng tin cậy thì agent phải nói *"tôi không tìm thấy căn cứ"* thay vì đoán | 30% |
| **On-chain cho điểm thưởng (tùy chọn)** | Neo hash của bản trích xuất hợp đồng và khuyến nghị lên chain → dấu vết kiểm toán bất biến, chứng minh agent đã tư vấn gì, lúc nào, dựa trên bản hợp đồng nào. **Ứng dụng on-chain có lý do tồn tại thật**, khác với gắn blockchain cho có | +0–5 điểm |

### 6.6. Rủi ro và cách phòng ngừa

| Rủi ro | Phòng ngừa |
|---|---|
| Cần dữ liệu hợp đồng bảo hiểm thật bằng tiếng Anh | Dùng mẫu hợp đồng công khai của các hãng lớn tại Mỹ / Anh / Úc, hoặc mẫu do cơ quan quản lý công bố |
| Lĩnh vực khô, khó gây ấn tượng khi thuyết trình | Dùng ma trận phủ sóng dạng trực quan làm hình ảnh trung tâm của slide — chỗ đỏ = lỗ hổng, chỗ vàng = trả phí trùng |

---

## 7. Đề tài #3 — Topic F: Agent Wallet on-chain

> ⭐ **Rủi ro cao, phần thưởng cao**

### 7.1. Mô tả theo thể lệ

> *"Agent Wallet — Autonomous On-chain Wallet: The track's original on-chain topic — build an AI wallet agent that autonomously executes on-chain operations (asset management, transaction execution, risk control). Ambitious ideas are encouraged, with a 0–5 point challenge bonus."*

### 7.2. Cơ sở lý luận

#### a) Đề tài duy nhất được thể lệ ghi rõ có điểm thưởng

Được gọi là *"đề tài gốc của bảng"* — tức BTC coi trọng. Câu *"Ambitious ideas are encouraged"* là tín hiệu rõ ràng rằng giám khảo chấp nhận rủi ro kỹ thuật ở đề tài này.

#### b) Bằng chứng vận hành dễ nhất trong 6 đề tài

Thể lệ yêu cầu *"real on-chain transaction hashes"* — deploy lên testnet/mainnet, chạy agent, nộp hash. **Không cần dựng môi trường sandbox giả lập phức tạp** như 5 đề tài còn lại. Đây là lợi thế hành chính thường bị đánh giá thấp.

#### c) Hạ tầng đã chín muồi đúng thời điểm — lý do quan trọng nhất

| Hạ tầng | Mô tả | Mốc thời gian |
|---|---|---|
| **ERC-8004** | Chuẩn định danh + danh tiếng on-chain cho AI agent, do Ethereum Foundation, MetaMask, Google và Coinbase cùng phát triển | Công bố 8/2025, **lên mainnet 1/2026**, đã có **~24.000 agent đăng ký** |
| **x402** | Giao thức micropayment gốc HTTP (Coinbase / Cloudflare) | Ra mắt 5/2025, xử lý **150+ triệu giao dịch, ~50 triệu USD trong 9 tháng đầu** |
| **Coinbase Agentic Wallets** | Hạ tầng ví đầu tiên thiết kế riêng cho AI agent — có sẵn session cap, transaction limit, operation allowlist, multi-party approval, audit log | 2/2026 |

**Hệ quả:** không phải xây từ số 0, có thể dồn toàn bộ công sức vào tầng agent thay vì tầng hạ tầng.

### 7.3. Đã có ai làm chưa?

#### ⚠️ Câu trả lời trung thực — và cũng là rủi ro lớn nhất: CÓ, rất nhiều

- **Hạ tầng thương mại đã sẵn sàng:** Coinbase AgentKit, Crossmint, Cobo agentic wallet, Safe (Gnosis) modular accounts, Circle agentic payments
- **Thị trường agentic commerce** đạt **8 tỷ USD giá trị giao dịch trong 2026**
- **Nghiên cứu:** *Agent-to-Agent Finance* (arXiv 2607.00245), *SoK: Blockchain Agent-to-Agent Payments* (arXiv 2604.03733)

> ❌ **Nếu chỉ làm "agent ví biết swap và transfer" → đang làm lại AgentKit và sẽ thua.** Phần *thực thi* đã trở thành hàng hóa phổ thông. Điểm số phải nằm ở chỗ khác.

#### Và đây chính là khoảng trống — có nghiên cứu chỉ thẳng vào nó

| Công trình | Phát hiện then chốt |
|---|---|
| **Can Trustless Agents Be Trusted?** (arXiv 2606.26028) | Nghiên cứu thực nghiệm hệ sinh thái ERC-8004 cho thấy **hệ sinh thái agent phi tập trung đang có vấn đề tin cậy thật** |
| **FinHarness** (arXiv 2605.27333) | Khung an toàn theo vòng đời (inline lifecycle safety harness) cho agent tài chính |
| **PAuth** — Precise Task-Scoped Authorization For Agents | Mô hình ủy quyền ngầm: yêu cầu bằng ngôn ngữ tự nhiên chỉ cấp quyền cho đúng thao tác cần thiết → **chặn được thao tác bị prompt injection chèn vào trên AgentDojo với 0 false positive** |
| **AgentDojo** (NeurIPS 2024) | **97 tác vụ thực + 629 test case bảo mật** cho agent dùng tool |
| Phân tích ngành (ARMO) | Ngành tài chính có vấn đề riêng gọi là **"speed-of-harm"**: hàng trăm micro-payment có thể chảy về ví kẻ tấn công *trước khi* hệ thống phân tích gian lận theo lô kịp chạy |

### 7.4. Hướng triển khai đề xuất

**Định vị: đừng thi "agent làm được gì" — hãy thi "agent TỪ CHỐI làm gì".**

Xây agent wallet mà **luận điểm trung tâm là hệ thống kiểm soát rủi ro**:

1. **Phân tầng quyền theo ngưỡng giá trị và độ rủi ro thao tác**
   - Dưới ngưỡng X → tự động
   - Trên ngưỡng X → cần phê duyệt của người dùng
   - Thao tác ngoài allowlist → chặn cứng
2. **Chống prompt injection ở tầng giao dịch**
   Agent đọc dữ liệu từ nguồn không tin cậy (website dự án, tin tức, metadata token) — **dữ liệu đó không bao giờ được nâng cấp thành quyền hành động**. Áp dụng mô hình PAuth.
3. **Chạy AgentDojo để có con số bảo mật khách quan**
   Trình bày tỷ lệ chặn tấn công và tỷ lệ false positive. Trong hàng nghìn đội thi, gần như chắc chắn không đội nào làm điều này.
4. **Nộp cả "nhật ký từ chối"**
   Log các giao dịch agent đã chặn kèm lý do — không chỉ log các giao dịch thành công.

> 💡 **Đây là cách biến một đề tài đông đúc thành đề tài độc nhất:** cạnh tranh ở trục 30% an toàn/tuân thủ, nơi mọi đội khác sẽ bỏ trống vì mải khoe tính năng.

### 7.5. Rủi ro và cách phòng ngừa

| Rủi ro | Mức độ | Phòng ngừa |
|---|---|---|
| Cần năng lực Solidity / Web3 thật | Cao | Chỉ chọn đề tài này nếu đã có người từng deploy contract lên mainnet |
| Demo on-chain fail trực tiếp trên sân khấu chung kết | Cao | Chuẩn bị video demo dự phòng + chạy trước trên testnet ổn định |
| Bị so sánh với các đội đã quen DeFi | Trung bình | Dồn toàn bộ điểm khác biệt vào tầng kiểm soát rủi ro, không đua tính năng DeFi |

---

## 8. Lý do loại 3 đề tài còn lại

### Topic A — Trợ lý tài chính cá nhân ❌

**Lý do loại: tổ hợp tệ nhất — vừa đông thí sinh, vừa đông prior art, vừa ít bề mặt rủi ro.**

- **Sản phẩm:** Mint (đã đóng), Copilot Money, Cleo, Monarch, Rocket Money — thị trường bão hòa
- **Nghiên cứu:** *FinPerMA* (arXiv 2608.04095 — benchmark bộ nhớ cá nhân hóa neo theo sự kiện tài chính/đời sống 2020–2026), *Finance Utility LLM* (Springer — multi-agent quản lý tài chính cá nhân)
- **Điểm chết:** agent chủ yếu *đọc và khuyên*, không *hành động* → rất khó ghi 30% điểm an toàn/tuân thủ

### Topic B — Agent tư vấn đầu tư ❌

**Lý do loại: prior art học thuật cực dày + rào cản pháp lý.**

- **Nghiên cứu:** *FinRobot* (nền tảng agent mã nguồn mở cho ứng dụng tài chính), *FinCon* (quản lý danh mục), *InvestorBench* (arXiv 2412.18174 — benchmark ra quyết định tài chính cho cổ phiếu, crypto, ETF), *TradingAgents*, cộng hẳn một bài survey tại **ACM ICAIF'25** về LLM agent cho quản lý đầu tư
- **Rào cản:** tư vấn đầu tư bị quản lý chặt ở mọi quốc gia → rất khó demo tính "compliant" trong 10 phút thuyết trình
- **Chỉ nên chọn nếu:** đội có chuyên gia tài chính định lượng thật

### Topic E — Copilot tài chính SME ❌

**Lý do loại: không có dữ liệu thật để chạy.**

- **Nghiên cứu đã có:** *Financial Management System for SMEs* (arXiv 2511.03631 — mô hình dự báo dòng tiền module hóa đạt **11,85% MAPE** so với Prophet 159,40% và SVR 166,24% khi dữ liệu khan hiếm), *EnterpriseArena / "Can LLM Agents Be CFOs?"* (arXiv 2603.23638 — benchmark phân bổ nguồn lực doanh nghiệp dài hạn)
- **Điểm chết:** đội không có sổ sách doanh nghiệp thật → "bằng chứng vận hành" sẽ là dữ liệu tự sinh, giám khảo sẽ nhìn ra ngay

---

## 9. Bảng so sánh tổng hợp

| Tiêu chí | **C — Xuyên biên giới** | **D — Bảo hiểm** | **F — Agent Wallet** |
|---|---|---|---|
| **Khoảng trống nghiên cứu** | 🟢 Rất lớn | 🟢 Lớn (nghiên cứu dừng ở QA) | 🟡 Nhỏ ở thực thi, lớn ở an toàn |
| **Mức độ cạnh tranh dự kiến** | 🟡 Trung bình | 🟢 Thấp nhất | 🔴 Cao nhất |
| **Bề mặt cho 30% an toàn/tuân thủ** | 🟢 Mạnh (KYC/AML/FX) | 🟢 Mạnh (chống ảo giác) | 🟢 Mạnh nhất |
| **Đo được 40% hoàn thành tác vụ** | 🟡 Phải tự xây test set | 🟢 Có InsQABench công khai | 🟢 Có AgentDojo |
| **Dễ tạo bằng chứng vận hành** | 🟡 Trung bình | 🟡 Trung bình | 🟢 Dễ nhất (tx hash) |
| **Lợi thế riêng của đội VN** | 🟢 Rất cao | 🟡 Trung tính | 🟡 Trung tính |
| **Khả năng lấy điểm thưởng on-chain** | 🟢 Tự nhiên (stablecoin) | 🟡 Có lý do (audit trail) | 🟢 Mặc định |
| **Yêu cầu kỹ năng đặc thù** | API/fintech | NLP + RAG | Solidity/Web3 |
| **Rủi ro thất bại** | 🟢 Thấp | 🟢 Thấp | 🔴 Cao |
| **Khớp khuôn mẫu thắng giải** *(mục 3)* | 🟢 Khớp 3/4 khuôn mẫu | 🟡 Khớp 2/4 | 🟢 Khớp 3/4 |
| **Chỗ đặt stack WeBank (FATE/FISCO)** | 🟢 FATE cho rủi ro liên kết | 🔴 Ít chỗ | 🟢 FISCO BCOS |

---

## 10. Khuyến nghị và việc cần làm ngay

### 10.1. Khuyến nghị

**Chọn Topic C — Trợ lý tài chính xuyên biên giới & du học sinh.**

Lý do gộp lại:
- Khoảng trống nghiên cứu lớn nhất trong 3 lựa chọn
- Danh tính đội Việt Nam là lợi thế không sao chép được, đúng vào bảng đấu đề cao tính quốc tế
- Đủ bề mặt tuân thủ để ăn trọn 30% điểm an toàn
- Ghép được stablecoin để lấy điểm thưởng on-chain mà **không phải đối đầu trực diện** với các đội DeFi mạnh ở Topic F

**Topic D là dự phòng tốt** nếu đội mạnh về NLP/RAG hơn là hạ tầng thanh toán — và có xác suất thắng cao nhờ ít đội cạnh tranh.

**Chỉ chọn Topic F** nếu trong đội đã có người từng deploy smart contract lên mainnet.

### 10.2. Việc cần làm ngay trong tuần này

- [ ] **Email `info@ican-x.com`** hỏi rõ điểm thưởng on-chain có áp dụng cho đề tài A–E không *(ưu tiên cao nhất — ảnh hưởng tới lựa chọn)*
- [ ] **Kiểm tra thành phần đội** so với ngưỡng ≥60% không mang quốc tịch Trung Quốc
- [ ] **Chốt đề tài trong 3–5 ngày** — còn khoảng 5 tuần, riêng Báo cáo tự đánh giá an toàn + bằng chứng vận hành đã ngốn ít nhất 1 tuần
- [ ] **Dựng thử FATE 3 nút** *(nếu chọn Topic C)* — xác nhận khả thi trong tuần 1, vì đây là hạng mục kỹ thuật rủi ro nhất của kiến trúc
- [ ] **Đăng ký tại `fintechathon.g-ican.com`** *(đăng ký và nộp bài cùng một hạn — không nên để sát ngày)*

### 10.3. Gợi ý phân bổ thời gian còn lại (~5 tuần)

| Tuần | Trọng tâm |
|---|---|
| Tuần 1 (13–19/09) | Chốt đề tài, chốt đội, dựng kiến trúc, chọn bộ benchmark để đo |
| Tuần 2–3 (20/09–03/10) | Xây core agent + tầng công cụ; dựng bộ test case song song |
| Tuần 4 (04–10/10) | Xây tầng phân tầng quyền + kiểm soát an toàn; chạy benchmark lấy số liệu |
| Tuần 5 (11–17/10) | Tài liệu kỹ thuật, Báo cáo tự đánh giá an toàn, thu thập bằng chứng vận hành, quay video demo |
| 18–20/10 | Hoàn thiện slide, tổng duyệt, **nộp sớm ít nhất 24h trước hạn** |

### 10.4. Nhắc lại danh mục nộp bài bắt buộc

1. Tài liệu kỹ thuật (kiến trúc hệ thống, mô tả thuật toán lõi, thiết kế bảo mật)
2. Slide thuyết trình (phần trình bày chung kết ≤ 10 phút)
3. Video demo *(không bắt buộc, ≤ 5 phút)*
4. Mã nguồn (README, link GitHub, hướng dẫn triển khai, test case)
5. Báo cáo tự đánh giá an toàn (phân tầng quyền + danh sách rủi ro đã biết)
6. Bằng chứng vận hành (log sandbox + video demo, hoặc tx hash on-chain thật)

---

## 11. Phụ lục: Danh mục tài liệu tham khảo

### Benchmark & nghiên cứu agent tài chính tổng quát

- [Finance Agent Benchmark: Benchmarking LLMs on Real-world Financial Research Tasks](https://arxiv.org/abs/2508.00828) — arXiv 2508.00828
- [FinMCP-Bench: Benchmarking LLM Agents for Real-World Financial Tool Use under MCP](https://arxiv.org/html/2603.24943v1) — arXiv 2603.24943
- [FinPerMA: Theory-Informed, Event-Grounded Personalized-Memory Benchmark](https://arxiv.org/html/2608.04095) — arXiv 2608.04095
- [Finance Utility LLM: A Multi-Agent LLM Framework for Intelligent Personal Finance Management](https://link.springer.com/chapter/10.1007/978-3-032-20735-7_30) — Springer

### Topic C — Xuyên biên giới & kiều hối

- [SoK: Blockchain Agent-to-Agent Payments](https://arxiv.org/pdf/2604.03733) — arXiv 2604.03733
- [From adoption to continuance: Stablecoins in cross-border remittances](https://www.sciencedirect.com/science/article/pii/S0736585324001345) — ScienceDirect
- [Stablecoins in Emerging Markets: The Cross-Border Payments Playbook for 2026](https://tazapay.com/guides/stablecoins-cross-border-payments-emerging-markets) — Tazapay
- [2026 Cross-Border Payments Trends for Financial Institutions](https://www.jpmorgan.com/insights/payments/fx-cross-border/2026-trends-for-financial-institutions) — J.P. Morgan

### Topic D — Bảo hiểm

- [InsQABench: Benchmarking Chinese Insurance Domain Question Answering](https://arxiv.org/pdf/2501.10943) — arXiv 2501.10943
- [Benchmarking LLMs for Quebec Insurance: From Closed-Book to RAG](https://arxiv.org/html/2603.07825) — arXiv 2603.07825
- [An Industrial-Scale Insurance LLM Achieving Verifiable Domain Mastery](https://arxiv.org/html/2603.14463v1) — arXiv 2603.14463
- [LLMs and Agentic AI in Insurance Decision-Making](https://arxiv.org/pdf/2508.15110) — arXiv 2508.15110

### Topic F — Agent Wallet & an toàn agent

- [Can Trustless Agents Be Trusted? Empirical Study of ERC-8004 Ecosystem](https://arxiv.org/pdf/2606.26028) — arXiv 2606.26028
- [Agent-to-Agent Finance: Blockchain Payments and Trust Infrastructure](https://arxiv.org/html/2607.00245v1) — arXiv 2607.00245
- [FinHarness: An Inline Lifecycle Safety Harness for Finance LLM Agents](https://arxiv.org/pdf/2605.27333) — arXiv 2605.27333
- [x402 & ERC-8004: How AI Agents Pay on the Agentic Web](https://www.chainup.com/blog/x402-erc8004-ai-agent-payments-agentic-web/) — ChainUp
- [Introducing Agentic Wallets](https://www.coinbase.com/developer-platform/discover/launches/agentic-wallets) — Coinbase
- [x402 and Agentic Commerce: Redefining Autonomous Payments](https://aws.amazon.com/blogs/industries/x402-and-agentic-commerce-redefining-autonomous-payments-in-financial-services/) — AWS
- [How Financial Services Teams Should Secure AI Agents in 2026](https://www.armosec.io/blog/financial-services-ai-agent-security/) — ARMO

### Topic B & E — Cơ sở loại bỏ

- [InvestorBench: A Benchmark for Financial Decision-Making Tasks with LLM-based Agent](https://arxiv.org/html/2412.18174) — arXiv 2412.18174
- [LLM Agents for Investment Management: Foundations, Benchmarks, Research Frontiers](https://dl.acm.org/doi/10.1145/3768292.3770387) — ACM ICAIF'25
- [Financial Management System for SMEs: AR and Cash Flow Prediction](https://arxiv.org/pdf/2511.03631) — arXiv 2511.03631
- [Can LLM Agents Be CFOs? Benchmarking Long-Horizon Resource Allocation](https://arxiv.org/html/2603.23638) — arXiv 2603.23638

### Lịch sử giải thưởng các kỳ trước (mục 3)

- [1700+学子竞逐金融梦 2025深圳国际金融科技大赛收官](https://m.dutenews.com/n/article/10315760) — 读特新闻, quán quân 2025
- [2024深圳国际金融科技大赛圆满收官](https://www.fisco.com.cn/en/news_7/862.html) — FISCO, giải blockchain 2024
- [2023深圳國際金融科技大賽在深圳大學落幕](https://hkcd.com/content_app/2023-12/18/content_8615160.html) — 香港商報, giải Nhất 3 hạng mục 2023
- [2024深圳国际金融科技大赛十强名单揭晓](https://news.qq.com/rain/a/20241128A07I3500) — 腾讯新闻
- [2022 深圳国际金融科技大赛圆满收官](https://www.fisco.com.cn/en/news_8/492.html) — FISCO, chủ đề các tác phẩm thắng 2022
- [微众银行第二届金融科技高校技术大赛 (2020)](https://www.oschina.net/news/118005/webank-fintechathon-2020) — OSCHINA, quán quân 2020
- [2025（第七届）深圳国际金融科技大赛启动](https://finance.sina.com.cn/tech/roll/2025-10-09/doc-infthnhk9684233.shtml) — 新浪科技, quy mô và cơ cấu giải
- [以赛带学 — 深圳大学微众银行金融科技学院](https://swift.szu.edu.cn/rcpy/tspy1/ysdx.htm) — trang tổng hợp của đơn vị tổ chức
- [2025 FinTechathon 报名通知](https://iec.swufe.edu.cn/info/1011/2351.htm) — 西南财经大学

### Thông tin cuộc thi

- Website chính thức: `fintechathon.g-ican.com`
- Email: `info@ican-x.com`
- [2026 Shenzhen International FinTech Competition — IEEE CIS Shenzhen Chapter](https://r10.ieee.org/shenzhen-cis/blog/2026/06/17/2026-shenzhen-international-fintech-competition-international-track/)

---

> **Lưu ý về nguồn:** Phần prior art được tổng hợp từ kết quả tìm kiếm học thuật và thông tin ngành tại thời điểm 12/09/2026. Các số liệu thị trường (vốn hóa stablecoin, khối lượng giao dịch x402, số agent ERC-8004) trích từ báo cáo ngành, nên kiểm chứng lại trước khi đưa vào slide thuyết trình chính thức.
