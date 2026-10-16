# BuoyUp v4

Cho vay người bán thương mại điện tử: năm AI agent, giải thuật tín dụng cố định B1–B12, nhiều ngân hàng cùng cấp vốn, nhật ký và lệnh giải ngân trên FISCO BCOS.

- **Triển khai và bàn giao:** đọc [HANDOVER.md](HANDOVER.md) (cài đặt, cấu hình, Docker, HTTPS, vận hành, sự cố).
- **Chạy nhanh bằng Docker:** `cp BackEnd/API_config/.env.example BackEnd/API_config/.env` (điền), rồi `docker compose up -d --build`, mở http://localhost:8000/
- **Chạy không Docker:** `./run-local.sh` · test: `./run-local.sh test`
- **API:** [BackEnd/API_config/API_CONTRACT_V4.md](BackEnd/API_config/API_CONTRACT_V4.md) · tài liệu tương tác ở `/docs`
- **Thiết kế:** [docs/thiet-ke-loi-ky-thuat-v4.html](docs/thiet-ke-loi-ky-thuat-v4.html)

| Thư mục | Khối |
|---|---|
| `BackEnd/src/app/core` | Giải thuật B1–B9, Bảng tham số, luật, luồng tính toán |
| `BackEnd/src/app/agents` | Agent 1 → 5 |
| `BackEnd/src/app/banks` | Ngân hàng đối tác, chia vốn B12 |
| `BackEnd/src/app/blockchain` | FISCO BCOS: sổ hash, dịch vụ chuỗi, lệnh giải ngân mã hóa |
| `BackEnd/src/app/data_sources` | 6 nguồn dữ liệu, hồ sơ mẫu, ủy quyền |
| `BackEnd/src/app/autopilot` | Agent 4/5 tự chạy |
| `BackEnd/src/app/api` | REST API `/v4` |
| `BackEnd/src/app/platform` | Cấu hình, DB, bảo mật, LLM, log |
| `BackEnd/src/Reid` | Xác thực khuôn mặt (InsightFace buffalo_l: SCRFD + ArcFace), API ở `app/api/face.py` |
| `BackEnd/API_config` | `.env`, hợp đồng API, OpenAPI chuỗi |
| `Frontend/giaodien` | 6 trang: trang chủ, đăng nhập, đăng ký, người bán, quản trị, ngân hàng |
| `Frontend/src` | JS/CSS theo khối: chung, trang-chu, nguoi-ban, quan-tri, ngan-hang, xac-thuc-khuon-mat |
