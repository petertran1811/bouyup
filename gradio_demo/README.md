---
title: BuoyUp vong vay
sdk: gradio
sdk_version: 5.9.1
app_file: buoyup_app.py
pinned: false
---

# BuoyUp · vòng vay (Gradio)

Bản demo vòng vay BuoyUp gói trong Gradio, có sáu tab:

- **Demo vòng vay:** 11 kịch bản ghi từ backend thật, và phần tự điền trên điện thoại giả lập.
- **Hỏi đáp BuoyUp:** chatbot trả lời về toàn bộ ứng dụng. Tìm trong `knowledge/kb.json` (60 mục: hỏi đáp viết sẵn ở `knowledge/faq.md`, phần 1 trang "nói dễ hiểu", `LOAN_CIRCLE_CHANGES.md`, một phần `HANDOVER.md`, tóm tắt năm agent) bằng cùng bộ tìm kiếm của RAG, rồi trích nguyên văn đoạn gần nhất kèm nguồn. Câu hỏi về luật có thêm điều luật gần nhất. Câu ngoài chủ đề thì trả lời "chưa tìm thấy". Nút 👍/👎 được lưu vào file góp ý.
- **Luồng mới so với bản trước.**
- **BuoyUp nói dễ hiểu:** giải thích bằng lời thường, có phần RAG và đối chiếu yêu cầu cuộc thi.
- **Tra cứu luật (RAG):** gõ câu hỏi, chọn Việt Nam hoặc Trung Quốc, xem các điều luật gần nhất. Tab này gọi thẳng `BackEnd/src/app/core/rag.py`, nên cần thư mục `BackEnd/` nằm cạnh `gradio_demo/` và gói `fastembed` (lần đầu tải mô hình e5 khoảng 2,2 GB). Không có `fastembed` thì tự chuyển sang chỉ dùng từ khóa.

- **Góp ý:** tên, vai trò, phần góp ý, số sao, nội dung. Lưu ngay vào `feedback/feedback.jsonl` trên máy (mỗi dòng một JSON; đổi chỗ lưu bằng `BUOYUP_FEEDBACK_FILE`). Bảng đọc lại file mỗi khi mở trang hoặc bấm **Tải lại**; có nút tải file về.

Ba trang HTML nằm trong `pages/`. Mỗi trang là một file HTML tự chứa, nhúng qua iframe. Toàn bộ số liệu là mô phỏng.

## Chạy trên máy

```bash
cd gradio_demo
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python buoyup_app.py            # http://127.0.0.1:7860
.venv/bin/python buoyup_app.py --share    # thêm link công khai https://….gradio.live
```

Link `--share` chỉ sống 72 giờ và chỉ chạy khi máy này còn bật tiến trình.

## Link cố định trên Hugging Face Spaces

1. Tạo tài khoản tại https://huggingface.co, rồi tạo Space mới với SDK **Gradio** và chế độ Public.
2. Đưa cả thư mục này (`buoyup_app.py`, `chatbot.py`, `feedback.py`, `requirements.txt`, `README.md`, `pages/`, `knowledge/`) lên Space, theo một trong hai cách:
   - kéo thả file trên trang Space (Files → Add file → Upload files);
   - hoặc `git push` vào kho git của Space.
3. Space tự cài và chạy. Link có dạng `https://huggingface.co/spaces/<tên>/<space>`, không hết hạn.

Cách khác: chạy `gradio deploy` trong thư mục này, rồi đăng nhập Hugging Face khi được hỏi.

## Chatbot

- Sửa câu trả lời: sửa `knowledge/faq.md` (mỗi `##` là một câu hỏi), rồi chạy `.venv/bin/python build_kb.py` và khởi động lại app. Lần đầu sau khi đổi, app tính lại vector khoảng 30 giây.
- Mặc định chatbot không gọi dịch vụ ngoài. Muốn mô hình ngôn ngữ viết câu trả lời từ 5 đoạn tìm được, đặt `BUOYUP_CHAT_LLM=anthropic` và `ANTHROPIC_API_KEY`, hoặc đặt `BUOYUP_CHAT_LLM=openai` cùng `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `BUOYUP_CHAT_MODEL`. Khi đó các đoạn tài liệu được gửi tới nhà cung cấp đó. Gặp lỗi thì quay về câu trả lời trích nguyên văn.

## Góp ý trên Hugging Face Spaces

Ổ đĩa của Space bị xóa mỗi lần Space khởi động lại, nên góp ý sẽ mất. Muốn giữ thì bật Persistent storage và đặt `BUOYUP_FEEDBACK_FILE=/data/feedback.jsonl`.

## Cập nhật trang

Khi trang demo đổi, chép file HTML mới đè vào `pages/demo.html`, `pages/flow.html` hoặc `pages/de-hieu.html`, rồi chạy lại app hoặc đưa lại lên Space.
