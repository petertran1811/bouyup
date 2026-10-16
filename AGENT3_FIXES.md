# Agent 3 · Nhật ký sửa lỗi và trích xuất kho luật TQ (14/10/2026)

Đối chiếu `BackEnd/src/app/agents/agent3_control.py` và `app/core/legal.py` với
`docs/agents/agent3_kiem_soat.md`, rồi sửa những chỗ code làm sai so với đặc tả. Làm cùng đợt là
**trích xuất bộ văn bản luật `docs/agents/TQ`** thành kho điều luật mà code kiểm trích dẫn
(lớp 1 ở mục 3.5 của đặc tả). Làm sau Agent 1 và Agent 2 (xem `AGENT1_FIXES.md`, `AGENT2_FIXES.md`).

- **Bản sao lưu trước khi sửa:** `../fintech_new_backup_20261014_160358_before_agent3/`. *(Đã xóa ngày 14/10/2026 để repo nhẹ hơn; các lệnh khôi phục từ bản sao này không còn dùng được.)*
- **Kết quả kiểm thử sau khi sửa:**
  - backend `pytest`: **214 passed** (trước: 200; thêm 13 test trong `tests/test_agent3_fixes.py` và 1 test trong `tests/test_chain_remote.py`);
  - `v4-api-check.py`: **PASS 9 kịch bản demo**;
  - `v4-ui-check.mjs`: **32 nhóm passed**;
  - `c1-api-check.py` và `c1-check.mjs`: **PASS / 14 nhóm passed**.
- **Kịch bản demo không đổi kết quả:** chị Lan vẫn được duyệt 139.900, thuốc lá điện tử bị từ chối, trà rời chuyển cán bộ, v.v.
- **Bộ quy tắc lên `rules-v1.1`:** câu trích đã đổi sang đúng nguyên văn, và có thêm căn cứ. Phiên bản mới được ghi lên chuỗi ở lần khởi động đầu tiên.

## File đã sửa hoặc thêm

| File | Nội dung |
|---|---|
| `BackEnd/src/scripts/extract_laws.py` **(mới)** | Script trích xuất bộ TQ (chỉ dùng thư viện chuẩn) |
| `BackEnd/src/app/core/laws/corpus.json`, `manifest.json` **(mới)** | Kho 794 mục và manifest |
| `BackEnd/src/app/core/legal.py` | Đọc kho đã trích thay cho chuỗi gõ tay; sửa và thêm trích dẫn; `search_articles(query, law_ids)` |
| `BackEnd/src/app/platform/seed.py` | `ensure_law_corpus`: neo `corpus_hash` lên chuỗi |
| `BackEnd/src/app/agents/agent3_control.py` | Các lỗi ở mục B |
| `BackEnd/src/app/agents/llm_tools.py` | `JudgeFailed`: tách "không có mô hình" với "mô hình lỗi" |
| `BackEnd/src/app/blockchain/chain.py` | Thử lại một lần khi ghi neo quan trọng thất bại |
| `BackEnd/API_config/API_CONTRACT_V4.md`, `docs/agents/TQ/README.md` | Phiên bản bộ quy tắc; cách chạy lại trích xuất |
| `tests/test_agent3_fixes.py` **(mới)**, `test_chain_remote.py`, `test_llm_agents.py`, `test_ruleset_postaudit.py` | Test |

---

## A. Trích xuất kho luật TQ (đặc tả §3.5, lớp 1)

### Vấn đề trước khi sửa

`legal.py` có một từ điển `ARTICLES` gồm **các câu gõ tay**, không lấy từ file docx:
- `verify_citation` chỉ so câu trích với chính chuỗi đó, tức là kiểm vòng tròn.
- Điều 5 của quy định PBOC được "lưu" thành `"200万元 50万元"`, ghép hai ngưỡng thành một chuỗi không có trong văn bản. Nhờ vậy câu trích `"200万元"` của AML-LTR-01 "đạt", trong khi văn bản thật viết `200 万元` (có dấu cách, do chuyển từ PDF).
- Không có manifest, không có mã băm nguồn, không neo gì lên chuỗi.

### Đã làm

**Script `scripts/extract_laws.py`.** Đọc thẳng file docx (zip + XML), không cần thư viện ngoài:
- **Luật và quy định:** tách theo `第X条` ở đầu dòng. Chỉ mở điều mới khi số điều **tăng đúng 1**, nên câu viện dẫn bị ngắt dòng không mở điều mới (gặp thật 1 lần trong văn bản PBOC). Giữ tên chương. Dòng bị ngắt giữa câu được nối lại; chỉ giữ xuống dòng sau dấu kết câu.
- **Lọc tiêu đề trang lặp lại** do chuyển từ PDF (PBOC: `中国人民银行发布`, `中国人民银行规章` chen giữa điều 5 và điều 14).
- **Phụ lục** của quy định vốn lưu động được tách thành mục `WCLOAN-2024#appendix`.
- **Danh sách tiêu cực** (lẫn hai cột): giữ toàn văn thành một mục `NEG-2025`, chỉ để kiểm câu trích.
- **Danh mục hàng cấm:** đọc 4 bảng, mỗi dòng là một mục `GOODS-2026#P{bảng}-{dòng}`, có tên cột và các ô.
- **Manifest:** mỗi file có SHA-256, tiêu đề, dòng nguồn, ngày hiệu lực, số điều đếm được so với số README ghi, và cảnh báo. `corpus_hash` là SHA-256 của toàn kho.

**Neo lên chuỗi.** `seed.ensure_law_corpus` ghi bản ghi `system/law_corpus` (`corpus_hash`, mã băm từng file) mỗi khi kho đổi.

**`legal.py` đọc `corpus.json`:**
- `verify_citation` kiểm câu trích có **nguyên văn** trong điều thật, và điều có hiệu lực vào ngày xét. Văn bản không ghi ngày hiệu lực thì được coi là đang hiệu lực, kèm ghi chú.
- `search_articles(query, law_ids)` tra toàn bộ kho, có lọc theo văn bản và trả đoạn quanh chỗ khớp, đúng như §3.5 mô tả.

**Chạy lại khi bộ TQ đổi:** `cd BackEnd/src && ../.venv/bin/python scripts/extract_laws.py`.

### Đặc trưng các văn bản đã trích (manifest)

Tổng **794 mục** · `corpus_hash` = `sha256:9cc2c4bf7f753442c44049cb94af764a07da1bcd9d8e12a7ef09f37938aa1e2c`.

| Mã | File | Văn bản | Hiệu lực | Đơn vị trích | SHA-256 (16 ký tự) | Quy tắc dùng | Cảnh báo |
|---|---|---|---|---|---|---|---|
| `AML-2024` | China_Anti_Money_Laundering_Law_2024.docx | 中华人民共和国反洗钱法 | 2025-01-01 | 65 điều | `0dd8b2cfe6e3a44e` | AML-CDD-01, AML-STR-01 | Ngày hiệu lực cần đối chiếu nguồn chính thức |
| `PBOC-LST-2016` | China_Large_Suspicious_Transactions.docx | 金融机构大额交易和可疑交易报告管理办法 | 2017-07-01 | 30 điều | `83b9980ea580af0e` | AML-LTR-01, AML-STR-01 | Bản 2016; đã bỏ tiêu đề trang lặp; 1 câu viện dẫn đầu dòng giữ trong điều trước |
| `ECIG-2022` | China_E_Cigarette_Measures_2022.docx | 电子烟管理办法（2022） | 2022-05-01 | 45 điều | `004d3a3152e5ac2c` | LAW-GOODS-01, LAW-GOODS-02 | — |
| `PQL-2018` | China_Product_Quality_Law_2018.docx | 中华人民共和国产品质量法（2018年修正） | 2018-12-29 | 74 điều | `16b5d109ed6640da` | LAW-IP-01, LAW-IP-02 | — |
| `TM-2026` | China_Trademark_Law_2026.docx | 中华人民共和国商标法（2026年修订） | 2027-01-01 | 87 điều | `a5cbc156e6ea5465` | LAW-IP-01 | Chưa hiệu lực trước 2027-01-01 |
| `TM-2019` | China_Trademark_Law_2019.docx | 中华人民共和国商标法（2019年修正） | 2019-11-01 | 73 điều | `3235aec9dc3b4324` | LAW-IP-01 | — |
| `NEG-2025` | China_Market_Access_Negative_List_2025.docx | 市场准入负面清单（2025年版） | — | toàn văn (2.355 đoạn) | `089021af82672590` | LAW-LIC-01/02/03 | Lẫn hai cột từ PDF; không ghi ngày hiệu lực |
| `GOODS-2026` | China_Prohibited_and_Restricted_Goods_List_2026.docx | 中国禁止及限制经营商品目录汇编 | — | 25 dòng bảng | `50f331f0c6b5aec0` | — (để tra cứu) | Bản tổng hợp của đội, không phải danh mục chính thức |
| `PIPL-2021` | China_Personal_Information_Protection_Law_2021.docx | 中华人民共和国个人信息保护法 | 2021-11-01 | 74 điều | `f9eb5480b3789dd9` | LAW-01, LAW-03 | — |
| `ECOM-2018` | China_E_Commerce_Law_2018.docx | 中华人民共和国电子商务法 | 2019-01-01 | 89 điều | `bd7ce28ec3196f5f` | LAW-LIC-01/02/03 | — |
| `NETTRADE-2021` | China_Online_Trading_Supervision_Measures_2021.docx | 网络交易监督管理办法 | 2021-05-01 | 56 điều | `9fbd457847dd5a6b` | LAW-LIC-01/02/03 | — |
| `CREDIT-2021` | China_Credit_Reporting_Business_Measures_2021.docx | 征信业务管理办法 | 2022-01-01 | 53 điều | `e6322ad3ea821533` | LAW-01 | — |
| `NETLOAN-2020` | China_Commercial_Bank_Internet_Loan_Measures_2020.docx | 商业银行互联网贷款管理暂行办法 | 2020-07-12 | 70 điều | `6e79aaffa72c3cfc` | POL-05 | — |
| `WCLOAN-2024` | China_Working_Capital_Loan_Measures_2024.docx | 流动资金贷款管理办法 | 2024-07-01 | 51 điều + phụ lục | `28b340eb3a242a9e` | POL-05, POL-06 | — |

Số điều của cả 12 văn bản tách theo điều đều **khớp** số mà README TQ và đặc tả §3.5 ghi. Danh mục hàng cấm đúng 25 dòng như đặc tả ghi.

### Trích dẫn đã sửa hoặc bổ sung (bộ quy tắc `rules-v1.1`)

| Quy tắc | Thay đổi |
|---|---|
| AML-LTR-01 | `"200万元"` (không có nguyên văn) → `"200 万元以上（含200 万元）"` và `"50 万元以上（含50 万元）"`; thêm `PBOC-LST-2016#8` `"5 个工作日内"` (đặc tả có, code thiếu) |
| AML-CDD-01 | Thêm `AML-2024#19`. **Câu trích đặc tả ghi `"本法所称受益所有人"` không có nguyên văn**; văn bản thật là `"本法所称法人、非法人组织的受益所有人"`, đã dùng câu này. **Cần sửa đặc tả** |
| AML-STR-01 | Thêm `PBOC-LST-2016#14` `"人工分析、识别，并记录分析过程"` |
| LAW-IP-01 | Thêm `PQL-2018#50` (tịch thu, phạt theo giá trị hàng) |
| LAW-LIC-01/02/03 | Thêm `ECOM-2018#15` cho 02/03, và `NETTRADE-2021#12` cho cả ba |
| POL-05 | Thêm câu thứ hai của `WCLOAN-2024#30` (một lần chi trên 10 triệu tệ) và `NETLOAN-2020#28` `"受托支付"` |
| POL-06 | Thêm `WCLOAN-2024#10` `"流动资金贷款禁止挪用"` |

Cả 26 quy tắc nạp được, **không quy tắc nào bị vô hiệu**. Câu trích bịa vẫn làm quy tắc bị vô hiệu như trước (test cũ vẫn đạt).

**Test:**
- `test_corpus_counts_match_the_sources`
- `test_extraction_handles_pdf_artifacts`
- `test_every_rule_citation_is_verbatim_in_the_corpus`
- `test_search_articles_filters_by_law`
- `test_corpus_hash_is_anchored_on_the_chain`

---

## B. Các lỗi Agent 3 đã sửa

### B1. LLM lỗi ở pha 1 mà hồ sơ vẫn được duyệt tự động *(nghiêm trọng; trái §6 và §3.4)*

**Đặc tả:** "Mô hình lỗi ở pha 1 → không niêm phong được → chuyển cán bộ"; "Agent 3 lỗi hoặc quá hạn: chuyển cán bộ".

**Lỗi:**
- `llm_tools.judge` trả `None` trong cả hai trường hợp: không cấu hình mô hình, và mô hình lỗi.
- Vì vậy khi mô hình lỗi, pha 1 chạy đường code và cổng **vẫn duyệt, giải ngân**. Có cả test khẳng định điều này.

**Sửa:**
- `judge` ném `JudgeFailed` khi mô hình **đã cấu hình** mà lỗi hoặc trả sai lược đồ.
- Pha 1 ghi băn khoăn `AGENT3` "Mô hình lỗi ở pha 1", kết luận `escalate`, `judgment_source = "llm_failed"`, và ghi sự kiện `llm_failed`.
- Không cấu hình mô hình (`LLM_ENABLED=false`, chạy bằng code) vẫn là chế độ hợp lệ như HANDOVER mô tả.

**Test:** đổi tên và sửa `test_provider_failure_template_for_agent2_officer_for_agent3`.

### B2. Cổng điều kiện 1 lỏng *(§3.4: "mỗi cờ resolved_by_check trỏ tới tool_calls đạt")*

**Lỗi:** cờ `resolved_by_check` **không có** `evidence_tool_call` vẫn qua, và code không kiểm lời gọi công cụ có lỗi hay không.

**Sửa:**
- Mỗi cờ phải trỏ tới một lời gọi công cụ có thật, và đầu ra không có `error`.
- Cờ do cán bộ xác nhận (`resolved_by: officer`) được tính là kiểm bằng người.

**Test:** `test_gate_needs_evidence_for_every_closed_flag`.

### B3. LAW-IP-02 bị ép chuyển cán bộ, gắn ghi chú và trích dẫn của LAW-IP-01 *(§3.5: "không đổi sàn; Agent 3 đánh giá")*

**Lỗi:**
- Code luôn `escalate`, kèm câu "nhà cung cấp không có trong danh sách phân phối được ủy quyền", là điều chưa hề kiểm.
- Trích dẫn dùng của LAW-IP-01.

**Sửa:**
- LAW-IP-01 (khai "không có ủy quyền"): giữ `escalate`, ghi chú đúng sự thật.
- LAW-IP-02 (ủy quyền "chưa rõ"): băn khoăn mức `warn` kèm trích dẫn của chính nó (`PQL-2018#39`).
- Có mô hình: chỉ khi mô hình nêu băn khoăn hợp lệ (qua kiểm của code) thì mới nghiêm hơn.
- Không có mô hình: không ai đánh giá được, nên chuyển cán bộ.

**Test:**
- `test_law_ip02_without_a_model_goes_to_an_officer_with_its_own_citation`
- `test_law_ip02_judged_fine_by_the_model_does_not_block`

### B4. AML-CDD-01 đòi xác minh chủ sở hữu hưởng lợi với cả hộ kinh doanh

**Đặc tả:** "hoặc **là công ty** mà chưa xác minh chủ sở hữu hưởng lợi".

**Sửa:** chỉ đòi khi chủ thể không phải `individual_business`.

**Test:** `test_aml_cdd_beneficial_owner_only_for_companies`.

### B5. LAW-01 không đối chiếu ủy quyền với nguồn đã dùng thật

**Sửa:**
- Ngoài việc ủy quyền còn hạn và chưa bị rút, LAW-01 kiểm mọi nguồn Agent 1 đã tra thật (dòng tiền, thuế, tín dụng, FATE, suy từ `tool_calls`) đều có trong phạm vi ủy quyền.
- Kết quả ghi rõ phạm vi còn thiếu.

### B6. RISK-06 chưa quét lập luận của Agent 2 *(§3.1: "`llm_notes` hoặc `rationale`")*

**Sửa:**
- Pha 2 quét từng luận điểm của Agent 2 tìm lệnh ẩn hoặc lời hứa (cùng bộ mẫu với ghi chú).
- Có thì giữ băn khoăn RISK-06 và chuyển cán bộ.

**Test:** `test_risk06_catches_a_steering_rationale`.

### B7. "Câu trả lời của Agent 2" ở pha 2 do Agent 3 tự dựng từ cờ dữ liệu mẫu

**Lỗi:** `answer_refs` đọc thẳng cờ kịch bản `rationale_evidence` trong dữ liệu demo.

**Sửa:**
- Câu trả lời lấy từ chính bộ dựng lập luận của Agent 2 (`advise._rationale`) cho phương án đó; chỉ tham chiếu có thật trên phiếu mới được tính.
- Kịch bản `noevid` vẫn ra "phương án nhỏ hơn 97.900" như đặc tả §7.2.

**Test:** `test_noevid_case_still_offers_the_smaller_option`.

### B8. Cổng điều kiện 4 chỉ so số thứ tự cục bộ *(§3.4: "Hash pha 1 có trên chuỗi và có trước hash kết luận cuối")*

**Sửa:** hàm `_seal_on_chain` kiểm:
- bản ghi niêm phong có trong chuỗi của đúng hồ sơ;
- đúng loại, đúng mã băm đã lưu;
- đứng trước kết luận cuối;
- ở chế độ `remote`, neo của nó đã gửi lên dịch vụ chuỗi (`sent`).

### B9. Ghi chuỗi khi niêm phong thất bại không thử lại *(§6: "Thử lại; không có hash thì không mở pha 2")*

**Sửa:**
- Neo quan trọng (niêm phong pha 1, kết luận, quyết định cổng) được gửi lại thêm **một lần** trước khi trả 503.
- Hỏng cả hai lần thì vẫn chặn như cũ, không mở pha 2.

**Test:** `test_remote_seal_is_retried_once`. Test cũ `test_remote_seal_failure_blocks_phase2` vẫn đạt.

### B10. RISK-05 khẳng định điều chưa kiểm khi chạy không có mô hình

**Lỗi:** dòng `checked_ok` ghi "… là sự kiện có thật" dù không có gì được kiểm.

**Sửa:** ghi "chưa đánh giá bằng mô hình (chạy đường code)".

### B11. Lý do gửi người bán luôn ghi Luật Nhãn hiệu 2019

**Sửa:** từ 2027-01-01 ghi Luật Nhãn hiệu 2026, Điều 72.

**Test:** `test_trademark_reason_follows_the_review_date`.

### B12. Cán bộ duyệt vượt quy tắc "từ chối" mà không để lại vết

**Sửa:**
- Duyệt được, vì đó là quyền của cán bộ.
- Nhưng hệ thống ghi sự kiện `officer_override_hard_rule` và trường `decision.overrode_rules`, để Agent 5 và kiểm toán thấy.

**Test:** `test_officer_override_of_a_reject_rule_is_recorded`.

---

## Chưa sửa (cần quyết định của nhóm)

| Vấn đề | Lý do |
|---|---|
| **RISK-02 (sàn "phương án nhỏ hơn") luôn thành chuyển cán bộ** | Hai đặc tả mâu thuẫn. Agent 1 §6.4/§6.6 nói cờ `explained_unverified` và `DATA_*` thì "không duyệt tự động"; Agent 3 §3.1 đặt sàn "phương án nhỏ hơn", còn §3.4 điều kiện 2 đòi sàn là "Đồng ý". Code hiện chọn chuyển cán bộ, đúng với Agent 1. Muốn mời người bán nhận phương án nhỏ hơn thì nhóm phải quyết việc đó có được duyệt tự động không |
| **LLM tự kết luận "chuyển cán bộ" mà không có băn khoăn hợp lệ** | Đặc tả §5: "chuyển cán bộ bất cứ lúc nào". Code (và test có sẵn của nhóm) cố ý bỏ qua kết luận trần của mô hình: chỉ băn khoăn mà code kiểm được tham chiếu mới làm nghiêm hơn. Đã thử áp đặc tả nhưng làm hỏng 2 test có chủ đích, nên **giữ nguyên** và để nhóm quyết |
| **Pha 2 chưa có LLM thật** | Pha 2 vẫn là code: gỡ RISK-04 khi có tham chiếu B3 và B8, quét RISK-06 trên lập luận. Chưa có các công cụ `get_agent2_rationale`, `ask_agent2`, `conclude` cho mô hình. Thêm thì phải có cả bộ ca đối kháng (§8) để kiểm việc "bị thuyết phục sai" |
| Bộ quy tắc là tuple Python, không phải YAML có `level: hard/warn` | Đổi định dạng không đổi hành vi; "hard" hiện là `min_verdict == "reject"`. Có thể chuyển khi có bước pháp chế duyệt |
| LAW-03 chỉ kiểm có `reason_codes`, chưa kiểm đủ ba yếu tố (luật, yếu tố chính, cách cải thiện) | Lý do gửi người bán do code dựng sẵn ba trường; cần định nghĩa rõ cách kiểm trên phiếu |
| POL-06 chưa kiểm "mặt hàng khớp mục đích" | Cần danh mục đối chiếu mặt hàng với sự kiện, hoặc giao cho RISK-05 của mô hình |
| Danh sách tiêu cực lẫn hai cột | Chỉ dùng toàn văn để kiểm câu trích; ba mục đang dùng (thực phẩm, dược, thiết bị y tế loại III) cần người đối chiếu bản PDF gốc |
| `GOODS-2026` chưa có quy tắc nào dùng | Mới trích thành bảng để tra; quy tắc hàng cấm hiện dựa trên nhóm hàng trong biểu mẫu |
| Đặc tả §3.5 ghi câu trích `AML-2024#19` sai | Nên sửa đặc tả thành `"本法所称法人、非法人组织的受益所有人"` |

## Khôi phục bản trước khi sửa Agent 3

```bash
cd /Users/trantiendung/Desktop/fintech_final
B=fintech_new_backup_20261014_160358_before_agent3
cp $B/BackEnd/src/app/agents/{agent3_control,llm_tools}.py fintech_new/BackEnd/src/app/agents/
cp $B/BackEnd/src/app/core/legal.py fintech_new/BackEnd/src/app/core/
cp $B/BackEnd/src/app/platform/seed.py fintech_new/BackEnd/src/app/platform/
cp $B/BackEnd/src/app/blockchain/chain.py fintech_new/BackEnd/src/app/blockchain/
cp $B/BackEnd/src/tests/{test_chain_remote,test_llm_agents,test_ruleset_postaudit}.py fintech_new/BackEnd/src/tests/
cp $B/BackEnd/API_config/API_CONTRACT_V4.md fintech_new/BackEnd/API_config/
cp $B/docs/agents/TQ/README.md fintech_new/docs/agents/TQ/
rm -r fintech_new/BackEnd/src/app/core/laws fintech_new/BackEnd/src/scripts/extract_laws.py fintech_new/BackEnd/src/tests/test_agent3_fixes.py
```
