# Bộ văn bản luật Trung Quốc cho Agent 3

14 văn bản. Agent 3 không đọc thẳng các file này khi xét hồ sơ; chúng là
nguồn để soạn quy tắc có trích dẫn (xem `docs/agents/agent3_kiem_soat.md`,
mục 3.5). Mọi câu trích trong quy tắc phải có nguyên văn trong các file này.

## Bảy văn bản ban đầu của đội

| File | Văn bản | Hiệu lực | Ghi chú |
|---|---|---|---|
| China_Anti_Money_Laundering_Law_2024.docx | 中华人民共和国反洗钱法（2024年修订） | 2025-01-01 | Ngày hiệu lực cần đối chiếu |
| China_Large_Suspicious_Transactions.docx | 金融机构大额交易和可疑交易报告管理办法 | 2017-07-01 | Bản 2016; kiểm các lần sửa đổi sau |
| China_E_Cigarette_Measures_2022.docx | 电子烟管理办法 | 2022-05-01 | |
| China_Product_Quality_Law_2018.docx | 中华人民共和国产品质量法（2018年修正） | 2018-12-29 | |
| China_Trademark_Law_2026.docx | 中华人民共和国商标法（2026年修订） | 2027-01-01 | Chưa hiệu lực trước 2027 |
| China_Market_Access_Negative_List_2025.docx | 市场准入负面清单（2025年版） | — | Chuyển từ PDF hai cột, lẫn cột |
| China_Prohibited_and_Restricted_Goods_List_2026.docx | 中国禁止及限制经营商品目录汇编 | — | Bản tổng hợp của đội, không phải danh mục chính thức |

## Bảy văn bản bổ sung ngày 12/10/2026

Tải nguyên văn từ trang chính thức; chỉ bỏ thanh điều hướng, chân trang và
dòng phân trang của trang web. Đầu mỗi file ghi nguồn, ngày tải và 16 ký tự
đầu mã băm SHA-256 của trang gốc.

| File | Văn bản | Hiệu lực | Số điều | Nguồn |
|---|---|---|---|---|
| China_Personal_Information_Protection_Law_2021.docx | 中华人民共和国个人信息保护法 | 2021-11-01 | 74 | https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm |
| China_E_Commerce_Law_2018.docx | 中华人民共和国电子商务法 | 2019-01-01 | 89 | https://www.cac.gov.cn/2018-09/01/c_1123362506.htm (3 trang) |
| China_Online_Trading_Supervision_Measures_2021.docx | 网络交易监督管理办法（国家市场监督管理总局令第37号） | 2021-05-01 | 56 | https://www.gov.cn/gongbao/content/2021/content_5602020.htm |
| China_Credit_Reporting_Business_Measures_2021.docx | 征信业务管理办法（中国人民银行令〔2021〕第4号） | 2022-01-01 | 53 | https://www.gov.cn/gongbao/content/2021/content_5654782.htm |
| China_Commercial_Bank_Internet_Loan_Measures_2020.docx | 商业银行互联网贷款管理暂行办法（银保监会令2020年第9号） | 2020-07-12 | 70 | https://www.gov.cn/gongbao/content/2020/content_5541497.htm |
| China_Working_Capital_Loan_Measures_2024.docx | 流动资金贷款管理办法（国家金融监督管理总局令2024年第2号） | 2024-07-01 | 51 + phụ lục | https://www.gov.cn/gongbao/2024/issue_11306/202404/content_6947721.html |
| China_Trademark_Law_2019.docx | 中华人民共和国商标法（2019年修正） | 2019-11-01 | 73 | https://www.cnipa.gov.cn/art/2019/7/30/art_95_28179.html |

## Còn thiếu, nên cân nhắc thêm

| Văn bản | Vì sao |
|---|---|
| 中华人民共和国食品安全法 | Căn cứ gốc cho giấy phép kinh doanh thực phẩm khi bán qua mạng |
| 化妆品监督管理条例 | Người bán mỹ phẩm là nhóm lớn trên sàn |
| 医疗器械监督管理条例 | Phân loại thiết bị y tế I/II/III |
| Danh sách quốc gia rủi ro cao về rửa tiền | Luật Chống rửa tiền Điều 24 có khái niệm nhưng chưa có danh sách |
| 个体工商户条例 | Phần lớn người bán là hộ kinh doanh; xác định cách xếp tài khoản tổ chức hay cá nhân khi tính ngưỡng giao dịch lớn |

## Trích xuất cho Agent 3 (14/10/2026)

Bộ này được trích thành kho điều luật mà code kiểm trích dẫn (Agent 3 §3.5, lớp 1):

```bash
cd BackEnd/src && ../.venv/bin/python scripts/extract_laws.py
```

Kết quả nằm ở `BackEnd/src/app/core/laws/corpus.json` (794 mục: mỗi điều một mục, danh sách tiêu cực giữ toàn văn, danh mục hàng cấm theo từng dòng bảng) và `manifest.json` (mã băm từng file, số điều, cảnh báo, `corpus_hash` neo lên chuỗi khi khởi động). **Mỗi khi sửa hay thêm file ở đây, chạy lại lệnh trên** rồi chạy test: quy tắc nào có câu trích không còn nguyên văn sẽ bị vô hiệu và test báo ngay. Chi tiết: `AGENT3_FIXES.md`.
