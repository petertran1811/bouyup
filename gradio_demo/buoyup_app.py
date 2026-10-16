"""BuoyUp loan-circle demo as a Gradio app (public link with --share, or a Hugging Face Space).

Tabs:
- Demo vòng vay, Luồng mới so với bản trước, BuoyUp nói dễ hiểu: self-contained HTML pages in ./pages,
  each in an iframe so its own scripts run unchanged; re-read on every visit.
- Hỏi đáp BuoyUp: chatbot over the team's documents (chatbot.py, knowledge/kb.json from build_kb.py).
- Góp ý: feedback saved on this machine in feedback/feedback.jsonl (feedback.py), re-read on every visit.
- Tra cứu luật (RAG): live search over the Chinese and Vietnamese law corpora with the backend's own
  retrieval module (BackEnd/src/app/core/rag.py): BM25 + local multilingual embeddings, fused.

    python buoyup_app.py     # http://127.0.0.1:7860
    python buoyup_app.py --share  # also prints a public https://….gradio.live link (valid 72 hours)
"""

from __future__ import annotations

import argparse
import html
import os
import sys
import threading
from pathlib import Path

import gradio as gr
import gradio_client.utils as _gcu

# Gradio 5.9 crashes building its API description when a JSON schema is a bare true/false
# ("argument of type 'bool' is not iterable"), which also blocks the --share link. Treat those as "Any".
_schema_to_type = _gcu._json_schema_to_python_type
_gcu._json_schema_to_python_type = lambda schema, defs=None: (
    "Any" if isinstance(schema, bool) else _schema_to_type(schema, defs))

HERE = Path(__file__).resolve().parent
PAGES = HERE / "pages"
BACKEND = HERE.parent / "BackEnd" / "src"
# The retrieval module reads these from the environment; the model and vectors are shared with the backend.
os.environ.setdefault("BUOYUP_RAG_CACHE", str(HERE.parent / "data" / "rag-cache"))
os.environ.setdefault("BUOYUP_RAG_MODEL", "intfloat/multilingual-e5-large")
sys.path.insert(0, str(BACKEND))
try:
    from app.core import rag  # noqa: E402
except Exception as exc:  # noqa: BLE001 - the pages still work without the law search
    rag = None
    RAG_ERROR = f"{type(exc).__name__}: {exc}"
else:
    RAG_ERROR = ""
import chatbot  # noqa: E402 - after sys.path, so it shares the backend's retrieval module
import feedback  # noqa: E402

SKELETON = ('<!doctype html><html lang="vi"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1"></head><body style="margin:0">{}</body></html>')

NOTE = """**BuoyUp · vòng vay (bản demo dự thi FinTechathon 2026)**
Mọi số liệu cửa hàng, thuế, tín dụng và quyết định của ngân hàng trong trang là **mô phỏng**. Tên các ngân hàng
(WeBank, China Merchants Bank, ICBC…) chỉ dùng làm đối tác giả định trong kịch bản, **chưa có hợp tác thật**."""

RAG_HELP = """### Tra cứu luật bằng RAG
Gõ câu hỏi bằng **tiếng Việt** (có dấu hoặc không dấu), **tiếng Anh** hoặc **tiếng Trung**, chọn kho luật rồi bấm **Tìm**.
Hệ thống thêm thuật ngữ pháp lý tương ứng (ví dụ "thuốc lá điện tử" → 电子烟), tìm theo chữ (BM25) và theo nghĩa
(mô hình đa ngôn ngữ *multilingual-e5-large* chạy ngay trên máy), trộn hai kết quả rồi trả về các điều gần nhất,
kèm nguyên văn và trạng thái hiệu lực.

- **Kho Trung Quốc:** 794 điều, 14 văn bản (chống rửa tiền, thương mại điện tử, thông tin cá nhân, cho vay qua internet,
  vốn lưu động, nhãn hiệu, thuốc lá điện tử, danh mục hàng cấm…), giữ nguyên tiếng Trung.
- **Kho Việt Nam:** 1.147 mục, 5 văn bản (Luật PCRT 2022, Luật Đầu tư 2025 kèm phụ lục, NĐ 98/2020 bản hợp nhất,
  NĐ 59/2006, NĐ 173/2024); phần đã bị bãi bỏ được đánh dấu.

Trong hệ thống thật, Agent 3 tự đặt các câu hỏi như thế này cho từng hồ sơ và đối chiếu với quy tắc. **RAG chỉ tìm
căn cứ, không quyết định**; trích dẫn vẫn phải khớp nguyên văn."""

EXAMPLES = [
    ["thuốc lá điện tử vị hoa quả có được bán không", "Trung Quốc"],
    ["customer due diligence beneficial owner", "Trung Quốc"],
    ["禁止通过信息网络销售电子烟", "Trung Quốc"],
    ["người dùng có quyền rút lại sự đồng ý", "Trung Quốc"],
    ["báo cáo giao dịch đáng ngờ", "Việt Nam"],
    ["kinh doanh dịch vụ cầm đồ có điều kiện không", "Việt Nam"],
    ["buôn bán hàng giả mạo nhãn hàng hóa bị phạt thế nào", "Việt Nam"],
    ["nhan biet khach hang", "Việt Nam"],
]
_J = {"Trung Quốc": "CN", "Việt Nam": "VN"}
_STATUS = {"repealed": "đã bãi bỏ", "partly_repealed": "bãi bỏ một phần"}


def frame(name: str, height: int) -> str:
    page = SKELETON.format((PAGES / name).read_text(encoding="utf-8"))
    return (f'<iframe srcdoc="{html.escape(page, quote=True)}" title="{name}" '
            f'style="width:100%;height:{height}px;border:0;border-radius:12px" loading="eager"></iframe>')


def law_search(query: str, corpus: str, k: float) -> str:
    if rag is None:
        return f"<p>Không nạp được mô-đun tra cứu: {html.escape(RAG_ERROR)}</p>"
    q = (query or "").strip()
    if not q:
        return "<p>Gõ một câu hỏi rồi bấm Tìm.</p>"
    j = _J.get(corpus, "VN")
    hits = rag.search(q, k=int(k), jurisdiction=j)
    mode = "theo chữ + theo nghĩa (embedding)" if rag.mode(j) == "hybrid" else "chỉ theo chữ (BM25)"
    terms = hits[0]["terms"] if hits else []
    out = [f"<p style='color:#56675f'>Kho {html.escape(corpus)} · tìm {mode}"
           + (f" · thuật ngữ thêm: {html.escape(', '.join(terms))}" if terms else "") + "</p>"]
    if not hits:
        out.append("<p>Không tìm thấy điều nào.</p>")
    for i, h in enumerate(hits, 1):
        art = rag.article(h["article_id"]) or {}
        flag = _STATUS.get(h.get("status", ""), "") or ("" if h["in_force"] else "chưa có hiệu lực")
        badge = f" <span style='background:#fae4e7;color:#b3283a;border-radius:99px;padding:1px 8px;font-size:.8em'>{flag}</span>" if flag else ""
        out.append(
            f"<details style='border:1px solid #d6e0db;border-radius:10px;padding:8px 12px;margin:6px 0'>"
            f"<summary><b>{i}. {html.escape(h['law'])}</b>{badge}<br><span style='color:#56675f'>"
            f"{html.escape(h['snippet'][:220])}</span></summary>"
            f"<pre style='white-space:pre-wrap;font-family:inherit;margin:8px 0 0'>{html.escape(art.get('text', ''))}</pre>"
            f"<p style='color:#56675f;font-size:.85em;margin:6px 0 0'>Mã: <code>{html.escape(h['article_id'])}</code>"
            f" · hiệu lực từ {html.escape(str(art.get('eff') or '—'))}"
            + (f" · bãi bỏ từ {html.escape(art['repealed_on'])}" if art.get("repealed_on") else "") + "</p></details>")
    return "".join(out)


CHAT_HELP = """### Hỏi đáp về BuoyUp
Hỏi bất cứ điều gì về BuoyUp: quy trình vay, hạn mức, lãi, trả nợ, năm agent, ngân hàng, FATE, blockchain, RAG, cách dùng demo.
Trợ lý tìm trong tài liệu của đội (bằng cùng bộ tìm kiếm với tab RAG) và **trích nguyên văn đoạn gần nhất kèm nguồn**,
không tự bịa câu trả lời. Câu hỏi về luật có thêm các điều luật gần nhất. Bấm 👍 / 👎 dưới câu trả lời để chấm; lượt chấm
được lưu cùng các góp ý."""

CHAT_EXAMPLES = ["BuoyUp là gì?", "Hạn mức được tính thế nào?", "Nhiều ngân hàng cùng cho vay ra sao?",
                 "Trả chậm thì bị xử lý thế nào?", "Agent 3 làm gì?", "Tiền vay được giải ngân vào đâu?",
                 "AI có tự quyết định cho vay không?", "How is the credit limit calculated?"]

FEEDBACK_HELP = """### Góp ý cho BuoyUp
Góp ý được **lưu ngay trên máy chạy demo** (file `gradio_demo/feedback/feedback.jsonl`) và hiện trong bảng bên dưới cho mọi người.
Bảng tự tải lại mỗi khi mở trang; bấm **Tải lại** để xem góp ý mới của người khác. Đừng ghi thông tin cá nhân nhạy cảm."""


def chat_reply(message: str, history: list) -> str:
    return chatbot.answer(message, history)


def chat_rated(history: list, data: gr.LikeData) -> None:
    i = data.index[0] if isinstance(data.index, (list, tuple)) else data.index
    reply = history[i]["content"] if 0 <= i < len(history) else ""
    asked = next((m["content"] for m in reversed(history[:i]) if m.get("role") == "user"), "")
    feedback.save("Ẩn danh", "Khác", "Hỏi đáp (chatbot)", feedback.STARS[0] if data.liked else feedback.STARS[-1],
                  f"{'👍' if data.liked else '👎'} Hỏi: {asked}\nĐáp: {str(reply)[:500]}", kind="chat_rating")


def feedback_view():
    entries = feedback.load()
    return feedback.summary(entries), feedback.rows(entries), (str(feedback.FILE) if feedback.FILE.exists() else None)


def feedback_submit(name, role, section, stars, text):
    try:
        feedback.save(name, role, section, stars, text)
    except ValueError as exc:
        gr.Warning(str(exc))
        return (gr.update(),) + feedback_view()
    gr.Info("Đã lưu góp ý. Cảm ơn bạn!")
    return ("",) + feedback_view()


def _warm() -> None:  # load the indexes and the model before the first question
    try:
        chatbot.kb().warm()
    except Exception:  # noqa: BLE001
        pass
    if rag is None:
        return
    for j in rag.available():
        try:
            rag.index(j).dense_ready()
        except Exception:  # noqa: BLE001
            pass


with gr.Blocks(title="BuoyUp vòng vay", fill_width=True, css=".gradio-container{max-width:1400px!important}") as app:
    gr.Markdown(NOTE)
    with gr.Tabs():
        with gr.Tab("Demo vòng vay"):
            demo_html = gr.HTML(frame("demo.html", 1500))
        with gr.Tab("Hỏi đáp BuoyUp"):
            gr.Markdown(CHAT_HELP)
            chat = gr.ChatInterface(
                chat_reply, type="messages", examples=CHAT_EXAMPLES, cache_examples=False,
                chatbot=gr.Chatbot(type="messages", height=560, label="Trợ lý BuoyUp", show_copy_button=True),
                textbox=gr.Textbox(placeholder="Gõ câu hỏi về BuoyUp…", submit_btn=True, show_label=False))
            chat.chatbot.like(chat_rated, [chat.chatbot], None)
        with gr.Tab("Luồng mới so với bản trước"):
            flow_html = gr.HTML(frame("flow.html", 2400))
        with gr.Tab("BuoyUp nói dễ hiểu"):
            easy_html = gr.HTML(frame("de-hieu.html", 4200))
        with gr.Tab("Tra cứu luật (RAG)"):
            gr.Markdown(RAG_HELP)
            with gr.Row():
                q_in = gr.Textbox(label="Câu hỏi", placeholder="Ví dụ: báo cáo giao dịch đáng ngờ", scale=4)
                corpus_in = gr.Radio(["Việt Nam", "Trung Quốc"], value="Việt Nam", label="Kho luật", scale=2)
                k_in = gr.Slider(3, 10, value=5, step=1, label="Số điều trả về", scale=1)
            go = gr.Button("Tìm", variant="primary")
            result = gr.HTML()
            gr.Examples(EXAMPLES, inputs=[q_in, corpus_in], label="Câu hỏi mẫu")
            go.click(law_search, [q_in, corpus_in, k_in], result)
            q_in.submit(law_search, [q_in, corpus_in, k_in], result)
        with gr.Tab("Góp ý"):
            gr.Markdown(FEEDBACK_HELP)
            with gr.Row():
                fb_name = gr.Textbox(label="Tên (không bắt buộc)", placeholder="Ẩn danh", max_length=80)
                fb_role = gr.Dropdown(feedback.ROLES, value=feedback.ROLES[0], label="Bạn là")
                fb_section = gr.Dropdown(feedback.SECTIONS, value="Chung", label="Góp ý cho phần")
            fb_stars = gr.Radio(feedback.STARS, label="Đánh giá chung (không bắt buộc)")
            fb_text = gr.Textbox(label="Nội dung góp ý", lines=5, max_length=feedback.MAX_TEXT,
                                 placeholder="Điều bạn thích, điều chưa rõ, lỗi gặp phải, câu hỏi cho đội…")
            with gr.Row():
                fb_send = gr.Button("Gửi góp ý", variant="primary")
                fb_reload = gr.Button("Tải lại")
                fb_file = gr.DownloadButton("Tải file góp ý (.jsonl)", value=None)
            fb_summary = gr.Markdown()
            fb_table = gr.Dataframe(headers=feedback.COLUMNS, datatype=["str"] * 6, interactive=False, wrap=True,
                                    column_widths=["11%", "10%", "12%", "13%", "8%", "46%"], label="Các góp ý (mới nhất trước)")
            fb_send.click(feedback_submit, [fb_name, fb_role, fb_section, fb_stars, fb_text],
                          [fb_text, fb_summary, fb_table, fb_file])
            fb_reload.click(feedback_view, None, [fb_summary, fb_table, fb_file])
    # Re-read the pages on every visit: replacing a file in ./pages updates the site without a restart.
    app.load(lambda: (frame("demo.html", 1500), frame("flow.html", 2400), frame("de-hieu.html", 4200)),
             outputs=[demo_html, flow_html, easy_html])
    app.load(feedback_view, None, [fb_summary, fb_table, fb_file])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--share", action="store_true", help="create a public gradio.live link")
    ap.add_argument("--port", type=int, default=7860)
    a = ap.parse_args()
    threading.Thread(target=_warm, daemon=True).start()
    app.launch(server_name="127.0.0.1", server_port=a.port, share=a.share)
