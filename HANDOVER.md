# BuoyUp v4 · Tài liệu bàn giao và hướng dẫn triển khai

Tài liệu này dành cho người nhận thư mục `FINTACHATHONS/` để dựng BuoyUp trên một máy khác (VPS, máy chủ công ty, máy demo). Làm lần lượt từ mục 3 đến mục 8 là có hệ thống chạy được qua HTTPS. Các mục còn lại phục vụ vận hành, xử lý sự cố và phát triển tiếp.

Ngày lập: 14/10/2026. Mã nguồn tách từ repo `sellergraph-core` (nhánh `feat/webank-v3`, mốc commit `9bf7cfe` cộng các thay đổi chưa commit tới ngày này).

---

## Mục lục
1. [Hệ thống là gì](#1-hệ-thống-là-gì)
2. [Cấu trúc thư mục theo từng khối](#2-cấu-trúc-thư-mục-theo-từng-khối)
3. [Yêu cầu máy chủ](#3-yêu-cầu-máy-chủ)
4. [Chép mã nguồn sang máy mới](#4-chép-mã-nguồn-sang-máy-mới)
5. [Cài Docker](#5-cài-docker)
6. [Cấu hình `.env`](#6-cấu-hình-env)
7. [Build và chạy](#7-build-và-chạy)
8. [Tên miền và HTTPS](#8-tên-miền-và-https)
9. [Kiểm tra sau khi dựng (smoke test)](#9-kiểm-tra-sau-khi-dựng-smoke-test)
10. [Vận hành hằng ngày](#10-vận-hành-hằng-ngày)
11. [Sao lưu và khôi phục](#11-sao-lưu-và-khôi-phục)
12. [Cập nhật phiên bản mới](#12-cập-nhật-phiên-bản-mới)
13. [Chạy không cần Docker](#13-chạy-không-cần-docker)
14. [Kiểm thử tự động](#14-kiểm-thử-tự-động)
15. [Dịch vụ bên ngoài](#15-dịch-vụ-bên-ngoài)
16. [Xử lý sự cố](#16-xử-lý-sự-cố)
17. [Bảo mật và giới hạn hiện tại](#17-bảo-mật-và-giới-hạn-hiện-tại)
18. [Đối chiếu với repo cũ](#18-đối-chiếu-với-repo-cũ)
19. [Checklist bàn giao](#19-checklist-bàn-giao)

---

## 1. Hệ thống là gì

BuoyUp cho người bán trên sàn thương mại điện tử vay vốn theo quy trình **loan circle** (`docs/BuoyUp loan circle .docx`, chi tiết thay đổi ở `LOAN_CIRCLE_CHANGES.md`). Người vay chọn loại (hộ kinh doanh / doanh nghiệp), dán link cửa hàng, quét CCCD, đánh dấu ba ô đồng ý và ký bằng khuôn mặt hoặc OTP. Lõi quyết định tính hạn mức; WeBank dẫn đầu, các ngân hàng hợp tác **tự duyệt song song trong 30 giây** (hai đối tác: 40/30/30; một đối tác: 30/70; không ai: thử 70%, 50% rồi từ chối). Người vay chọn số tiền, kỳ hạn, hình thức trả và ngày trả trong hạn mức (hiệu lực 7 ngày), đọc bảng chi phí ít nhất 20 giây rồi ký; vốn đi qua tài khoản trung gian tại WeBank, phần vượt 100.000 tệ trả thẳng nhà cung cấp. Năm AI agent xử lý phần còn lại:

| Agent | Việc | Mã nguồn |
|---|---|---|
| 1 · Xác minh | Cửa hàng có thật, doanh thu theo thuế, ảnh doanh thu tự nộp (tùy chọn), báo cáo tín dụng, FATE, lịch sử với BuoyUp; bật và đóng cờ (B10) | `app/agents/agent1_verify.py` |
| 2 · Tư vấn | Nhận phiếu hạn mức, gợi ý vay vừa đủ, báo giá từng lựa chọn, chat với người bán | `app/agents/agent2_advise.py` |
| 3 · Kiểm soát | Pha 0–2 trên gói hồ sơ ở mức hạn mức; cổng duyệt; gửi bộ điều phối các ngân hàng | `app/agents/agent3_control.py`, `app/banks/syndicate.py` |
| Hợp đồng | Chọn khoản vay, bảng chi phí, ký, giữ chỗ hạn mức ngân hàng | `app/agents/contract.py` |
| 4 · Giải ngân & quản lý | Tài khoản trung gian, giải ngân, trích vào ngày trả, trả tối thiểu, lãi phạt, quá hạn 30 ngày, trả trước, giám sát tài khoản kinh doanh; tự chạy mỗi 5 phút | `app/agents/agent4_*.py`, `app/autopilot/loop.py` |
| 5 · Hậu kiểm | Thống kê sau cho vay, LLM tóm tắt và đề xuất chỉnh tham số (người duyệt) | `app/agents/agent5_*.py` |

Mọi con số (hạn mức, lãi, hạng, lịch trả) do giải thuật cố định B1–B9 tính (`app/core/algorithm.py`); agent không tạo số. Thiết kế đầy đủ: `docs/thiet-ke-loi-ky-thuat-v4.html` (mở bằng trình duyệt).

**Một tiến trình** (FastAPI/uvicorn) phục vụ cả API (`/v4/...`, 70 đường dẫn) và giao diện web tĩnh (`/app/...`). Dữ liệu nằm trong **một file SQLite**. Không cần Node, Redis hay Postgres để chạy.

Người dùng và trang:

| Vai trò | Trang | Tài khoản demo (khi `APP_ENV=dev/demo`) |
|---|---|---|
| Người bán | `/app/giaodien/workspace.html` | `lan@buoyup.vn` (hồ sơ mẫu chị Lan) |
| Cán bộ tín dụng | `/app/giaodien/admin.html` | `officer@buoyup.vn` |
| Quản trị | `/app/giaodien/admin.html` | `admin@buoyup.vn` |
| Ngân hàng đối tác | `/app/giaodien/bank.html` | `webank@buoyup.vn`, `cmb@`, `icbc@`, `vcb@` |

Mật khẩu demo: giá trị `BUOYUP_DEMO_PASSWORD` (mặc định `BuoyUp@2026`). Trang chủ: `/` (tự chuyển tới `/app/giaodien/index.html`). Tài liệu API tương tác: `/docs`.

---

## 2. Cấu trúc thư mục theo từng khối

```
FINTACHATHONS/
├── HANDOVER.md                  ← tài liệu này
├── README.md
├── Dockerfile                   ← image = API + giao diện
├── docker-compose.yml           ← chạy 1 service "buoyup", volume dữ liệu "buoyup-data"
├── run-local.sh                 ← chạy không Docker / chạy test / reset demo
├── deploy/
│   ├── backup.sh                ← sao lưu DB từ container
│   └── nginx-buoyup.conf        ← mẫu Nginx reverse proxy + HTTPS
├── docs/
│   └── thiet-ke-loi-ky-thuat-v4.html   ← thiết kế lõi (5 agent, B1–B12, FISCO)
├── BackEnd/
│   ├── API_config/
│   │   ├── .env.example         ← mẫu cấu hình, có chú thích từng biến
│   │   ├── .env                 ← cấu hình THẬT (bí mật, không commit) – xem mục 6
│   │   ├── API_CONTRACT_V4.md   ← hợp đồng API v4 (mọi route, request, response, lỗi)
│   │   └── fisco-chain-service.openapi.json  ← OpenAPI dịch vụ chuỗi FISCO của team
│   └── src/                     ← gói Python "app" (chạy: uvicorn app.main:app)
│       ├── requirements.txt / requirements-dev.txt / pytest.ini
│       ├── app/
│       │   ├── main.py          ← khởi động: tạo bảng, seed, đồng bộ chuỗi, autopilot, mount UI
│       │   ├── core/            ← KHỐI GIẢI THUẬT: algorithm (B1–B9, FATE mỏng, khoản vay mồi), params (Bảng
│       │   │                       tham số v4.0), legal (quy tắc pháp lý + trích dẫn), stress (kịch bản sự kiện),
│       │   │                       challenger + models/challenger_v1.json (mô hình thách thức của Agent 3),
│       │   │                       flow (dựng lại luồng tính toán từng khối cho admin)
│       │   ├── agents/          ← KHỐI 5 AGENT: agent1_verify, agent2_advise, agent3_control,
│       │   │                       agent4a_payout (giải ngân, quyền một lần) / agent4b_monitor (giám sát,
│       │   │                       chỉ đọc; lệnh trích nợ định kỳ) / agent4_llm, agent5_postaudit / agent5_llm,
│       │   │                       complaints (bàn khiếu nại), llm_tools (vòng gọi công cụ)
│       │   ├── banks/           ← KHỐI NGÂN HÀNG: split (điều kiện + chia B12, trần từng ngân hàng)
│       │   ├── blockchain/      ← KHỐI FISCO BCOS: chain (sổ hash theo hồ sơ), chain_remote (client
│       │   │                       dịch vụ chuỗi thật), chain_sync (kéo danh mục ngân hàng + khóa),
│       │   │                       withdrawals (lệnh giải ngân mã hóa từng ngân hàng)
│       │   ├── data_sources/    ← KHỐI DỮ LIỆU: sources (6 nguồn, dữ liệu mẫu), profiles (+ profiles/lan.json),
│       │   │                       consent (ủy quyền)
│       │   ├── autopilot/       ← KHỐI TỰ CHẠY: loop (Agent 4 mỗi 5 phút, Agent 5 mỗi 6 giờ)
│       │   ├── api/             ← KHỐI API /v4: auth, applications, loans, officer, admin, banks,
│       │   │                       chain_api, payouts, postaudit, public; views (định dạng trả về)
│       │   ├── platform/        ← HẠ TẦNG: config, db/ (engine, Base), tables (bảng bu_*), security
│       │   │                       (đăng nhập, phân quyền), seed, events, audit (log JSON), errors,
│       │   │                       ledger_key (khóa HMAC), guards (câu cấm), llm/ (OpenAI-compat, Gemini)
│       │   └── static/          ← decrypt_withdrawal.py (script giải mã độc lập cho ngân hàng)
│       ├── tests/               ← 177 test (pytest), chạy offline, không chạm chuỗi thật
│       └── scripts/             ← reset_demo_seller.py, gen_lan_profile.py
└── Frontend/
    ├── index.html               ← chuyển hướng sang giaodien/
    ├── giaodien/                ← 6 TRANG: index (trang chủ), login, register,
    │                               workspace (người bán), admin (cán bộ/quản trị), bank (ngân hàng)
    ├── src/                     ← JS/CSS theo khối, trang tham chiếu bằng ../src/...
    │   ├── chung/               ← dùng chung: bu/ (api.js, session.js, motion.js, shell.js,
    │   │                           tokens.css…), assets/, fonts/, vendor/ (gsap, lenis, font chữ)
    │   ├── trang-chu/           ← main.js
    │   ├── nguoi-ban/           ← workspace-v4.js/.css (wizard 8 bước + chat với Agent 2)
    │   ├── quan-tri/            ← admin-v4.js/.css (hồ sơ, tab "Toàn bộ luồng", chuỗi, hậu kiểm)
    │   └── ngan-hang/           ← bank.js (cổng ngân hàng đối tác)
    └── tests/                   ← kiểm tra giao diện (Node) + kiểm tra hợp đồng API (Python)
```

Quy ước:
- Mã Python luôn import theo khối, ví dụ `from app.core import algorithm`, `from app.blockchain import chain`.
- Bảng cơ sở dữ liệu nằm ở `app/platform/tables.py` (tiền tố `bu_`). Bảng được tạo tự động khi khởi động; không có migration. Hãy thêm cột mới với giá trị mặc định, hoặc thêm bảng mới.
- Các trang trong `giaodien/` nằm cùng cấp nên link giữa các trang luôn là `login.html`, `admin.html`…

---

## 3. Yêu cầu máy chủ

| Mục | Tối thiểu | Khuyên dùng |
|---|---|---|
| Hệ điều hành | Linux 64-bit bất kỳ có Docker | Ubuntu Server 22.04 / 24.04 LTS |
| CPU / RAM | 1 vCPU / 1 GB | 2 vCPU / 2 GB |
| Ổ đĩa | 5 GB trống | 20 GB (log, backup) |
| Phần mềm | Docker Engine 24+ và Docker Compose v2 | như trên + Nginx + Certbot (HTTPS) |
| Mạng ra | HTTPS tới `fs.buoyup.app:443` (chuỗi FISCO); tới máy LLM (`LLM_HOST:LLM_PORT`, hiện là `45.78.203.38:8003`) | |
| Mạng vào | cổng 8000 (thử) hoặc 80/443 (qua Nginx) | chỉ mở 22, 80, 443 |

Không cần GPU: mô hình ngôn ngữ chạy ở máy LLM riêng (vLLM), BuoyUp chỉ gọi API của nó.

---

## 4. Chép mã nguồn sang máy mới

Chép **cả thư mục `FINTACHATHONS/`** (khoảng 3 MB). Có ba cách:

**a) rsync qua SSH (khuyên dùng):**
```bash
# chạy trên máy hiện tại
rsync -avz --exclude '.omc' --exclude '__pycache__' --exclude 'data/' --exclude 'BackEnd/.venv' \
  FINTACHATHONS/ user@may-moi:/opt/buoyup/
```

**b) Nén rồi scp:**
```bash
tar --exclude='.omc' --exclude='__pycache__' --exclude='./data' -czf buoyup-v4.tgz -C FINTACHATHONS .
scp buoyup-v4.tgz user@may-moi:/tmp/
ssh user@may-moi 'sudo mkdir -p /opt/buoyup && sudo chown $USER /opt/buoyup && tar -xzf /tmp/buoyup-v4.tgz -C /opt/buoyup'
```

**c) Qua git:** commit thư mục này lên một repo riêng tư rồi `git clone` trên máy mới. File `BackEnd/API_config/.env` bị `.gitignore` chặn nên phải chép riêng (bước dưới).

**Về file bí mật `BackEnd/API_config/.env`:** file này chứa khóa API LLM và khóa HMAC của sổ cái. Chép bằng rsync/scp như trên là được (nó nằm trong thư mục). Không gửi qua chat, email hay commit lên git. Trên máy mới, giới hạn quyền đọc:
```bash
chmod 600 /opt/buoyup/BackEnd/API_config/.env
```
Nếu không mang theo `.env`, tạo lại từ mẫu (mục 6).

Từ đây trở đi tài liệu giả định mã nằm ở `/opt/buoyup` (thay bằng đường dẫn của bạn).

---

## 5. Cài Docker

Ubuntu 22.04/24.04 (theo hướng dẫn chính thức của Docker):
```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER      # đăng xuất rồi đăng nhập lại để dùng docker không cần sudo
docker --version && docker compose version
```
Các hệ điều hành khác: xem https://docs.docker.com/engine/install/.

---

## 6. Cấu hình `.env`

Nếu đã chép `.env` thật từ máy cũ thì chỉ cần kiểm lại. Nếu không:
```bash
cd /opt/buoyup
cp BackEnd/API_config/.env.example BackEnd/API_config/.env
nano BackEnd/API_config/.env
```

Biến **phải điền**:

| Biến | Ý nghĩa | Giá trị |
|---|---|---|
| `APP_ENV` | Môi trường | `demo` (có tài khoản mẫu, dùng để trình diễn) hoặc `production` (không có tài khoản mẫu; tạo người dùng qua trang Quản trị hoặc đăng ký) |
| `CREDIT_LEDGER_KEY` | Khóa HMAC ký các khối của sổ cục bộ. Bắt buộc khi `APP_ENV` không phải `dev`/`test`, thiếu thì server **từ chối khởi động** | Sinh: `python3 -c 'import secrets;print(secrets.token_hex(32))'`. Giữ cố định cho một cơ sở dữ liệu |
| `LLM_HOST`, `LLM_PORT`, `LLM_MODEL_NAME`, `LLM_API_KEY` | Máy mô hình ngôn ngữ kiểu OpenAI (vLLM) | Hiện tại: `http://45.78.203.38`, `8003`, `Apero-LLM`, khóa trong `.env` cũ |
| `BUOYUP_CHAIN_BACKEND`, `BUOYUP_CHAIN_URL` | Chuỗi khối | `remote` + `https://fs.buoyup.app` (chuỗi thật của team), hoặc `local` (sổ mô phỏng, không cần mạng) |

Biến tùy chọn (có giá trị mặc định hợp lý):

| Biến | Mặc định | Ghi chú |
|---|---|---|
| `LLM_ENABLED` | `true` | `false`: mọi agent chạy đường template cố định; hệ thống vẫn đủ chức năng, chỉ bớt "tự nhiên" |
| `LLM_TIMEOUT_SECONDS` | `30` | |
| `LLM_AGENT3_MODEL_NAME` | trống | mô hình riêng cho Agent 3 trên cùng endpoint |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | trống | chỉ dùng khi không đặt `LLM_HOST` |
| `BUOYUP_CHAIN_TOKEN` | trống | dịch vụ chuỗi hiện chưa đòi token |
| `BUOYUP_CHAIN_TIMEOUT_SECONDS` | `15` | |
| `BUOYUP_AUTOPILOT` | `true` | Agent 4/5 tự chạy nền |
| `BUOYUP_AGENT4_INTERVAL_SECONDS` | `300` | Agent 4 giám sát mỗi 5 phút (và ngay khi có tiền về) |
| `BUOYUP_AGENT5_INTERVAL_SECONDS` | `21600` | Agent 5 hậu kiểm mỗi 6 giờ (sớm hơn khi có khoản tất toán/cảnh báo đỏ) |
| `BUOYUP_DEMO_PASSWORD` | `BuoyUp@2026` | mật khẩu tài khoản mẫu |
| `BUOYUP_SESSION_HOURS` | `12` | thời hạn phiên đăng nhập |
| `CORS_ALLOW_ORIGINS` | `["*"]` | chỉ cần khi giao diện chạy ở tên miền khác API |
| `FATE_URL` | trống | trống = điểm liên ngân hàng từ dữ liệu mẫu |
| `LOG_LEVEL` | `INFO` | |
| `DATABASE_URL` | Docker: `sqlite:////data/buoyup.db` (compose đặt sẵn) | chỉ đổi khi chạy không Docker |
| `BUOYUP_PORT` | `8000` | cổng trên máy chủ, đặt trong shell hoặc file `.env` cạnh `docker-compose.yml` |

Lưu ý định dạng: mỗi dòng `TEN=giatri`, không thêm dấu nháy, không có khoảng trắng quanh `=`.

---

## 7. Build và chạy

```bash
cd /opt/buoyup
docker compose up -d --build        # lần đầu ~2–3 phút (tải image Python, cài thư viện)
docker compose ps                   # STATUS phải là "Up ... (healthy)" sau ~30 giây
docker compose logs -f buoyup       # Ctrl+C để thoát xem log
```

Log khởi động bình thường có các dòng JSON:
- `"event": "startup"`, kèm `app_env`, `llm_model` và `llm_available: true`;
- `"event": "chain_catalog_synced"` khi `BUOYUP_CHAIN_BACKEND=remote`: 10 ngân hàng, 10 khóa, kéo từ chuỗi;
- `"event": "autopilot_started"`;
- `"event": "frontend_mounted"`.

Mở `http://IP-MAY-CHU:8000/` để thấy trang chủ BuoyUp. Nếu máy có tường lửa:
```bash
sudo ufw allow 8000/tcp     # chỉ để thử; khi đã có Nginx (mục 8) thì đóng lại: sudo ufw delete allow 8000/tcp
```

Image chạy với người dùng không phải root (uid 10001). Dữ liệu nằm trong volume Docker `buoyup-data` (thư mục `/data` trong container), nên **xóa hay build lại container không mất dữ liệu**. Chỉ `docker compose down -v` mới xóa volume.

Cổng khác 8000: `BUOYUP_PORT=8080 docker compose up -d`.

---

## 8. Tên miền và HTTPS

1. Trỏ bản ghi DNS `A` của tên miền (ví dụ `buoyup.example.com`) về IP máy chủ.
2. Cài Nginx và Certbot:
   ```bash
   sudo apt-get install -y nginx certbot python3-certbot-nginx
   sudo cp /opt/buoyup/deploy/nginx-buoyup.conf /etc/nginx/sites-available/buoyup
   sudo sed -i 's/buoyup.example.com/TEN-MIEN-CUA-BAN/' /etc/nginx/sites-available/buoyup
   sudo ln -s /etc/nginx/sites-available/buoyup /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   sudo certbot --nginx -d TEN-MIEN-CUA-BAN     # tự thêm HTTPS và chuyển hướng 80 → 443
   sudo ufw allow 'Nginx Full'
   ```
3. Chỉ cho BuoyUp nghe trên máy (không lộ cổng 8000 ra ngoài): sửa `docker-compose.yml`, mục `ports`, thành `"127.0.0.1:${BUOYUP_PORT:-8000}:8000"`, rồi chạy `docker compose up -d`.

Trình duyệt chỉ cho phép camera/clipboard và một số API trên HTTPS, nên khi demo cho người ngoài hãy dùng HTTPS.

---

## 9. Kiểm tra sau khi dựng (smoke test)

Ở đây `URL=https://TEN-MIEN-CUA-BAN`, hoặc `http://IP:8000`.

```bash
curl -s $URL/healthz                                   # {"ok":true,"version":"0.1.0"}
curl -s -o /dev/null -w '%{http_code}\n' $URL/app/giaodien/login.html    # 200
curl -s -X POST $URL/v4/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@buoyup.vn","password":"BuoyUp@2026"}' | head -c 120   # có "token"
```

Kiểm tra trên trình duyệt (khoảng 10 phút):
1. Đăng nhập `lan@buoyup.vn` và đi hết wizard: chọn hộ kinh doanh, dán link (đã điền sẵn), định danh, ba ô đồng ý và ký, kế hoạch (ảnh doanh thu bỏ trống được), xác minh. Kết quả phải là **"Ngân hàng đã duyệt hạn mức · Tối đa 200.000 tệ"** với WeBank 40% · China Merchants Bank 30% · ICBC 30%. Chọn số tiền, kỳ hạn (3/6/12), hình thức và ngày trả, mở bảng chi phí, đợi 20 giây, nhập tài khoản WeBank (và tài khoản nhà cung cấp khi vay trên 100.000), ký → **"Đã giải ngân!"**.
2. Trên trang khoản vay: lịch trả, nút trả tối thiểu và trả trước; mục "Mô phỏng (demo)" cho tiền hàng về, chi tiền và cho thời gian trôi (xem trích nợ, nhắc hạn, lãi phạt, báo quá hạn 30 ngày).
3. Thẻ khoản vay hiện dòng "Giải ngân đã ghi trên chuỗi FISCO BCOS · khối N · 4/4 nút xác nhận" (chế độ `remote`).
4. Đăng nhập `admin@buoyup.vn`, mở hồ sơ vừa tạo, tab **"Toàn bộ luồng"**: B1–B9 có công thức và số thật, nhãn "✓ Khớp phiếu đã lưu" và "✓ Phiếu đã lưu đúng bản niêm phong trên chuỗi". Mục "Chuỗi & sổ cái" có nhãn "FISCO BCOS · chuỗi thật" và 4 nút đang hoạt động.
5. Đăng nhập `webank@buoyup.vn`: mục "Duyệt song song" có hồ sơ vừa duyệt; danh sách lệnh giải ngân có phần của WeBank và giải mã được; panel "Điều khoản trên chuỗi" có dữ liệu.

Muốn làm lại từ đầu với chị Lan:
```bash
docker compose exec buoyup python /srv/BackEnd/src/scripts/reset_demo_seller.py
```
Lệnh này chuyển hồ sơ cũ của Lan sang tài khoản lưu trữ. Hồ sơ không bị xóa: dữ liệu đã ghi lên chuỗi phải giữ nguyên.

---

## 10. Vận hành hằng ngày

| Việc | Lệnh |
|---|---|
| Xem trạng thái | `docker compose ps` |
| Xem log | `docker compose logs -f --tail 200 buoyup` (log JSON, mỗi dòng một sự kiện) |
| Khởi động lại | `docker compose restart buoyup` |
| Dừng / chạy | `docker compose stop` / `docker compose up -d` |
| Vào shell container | `docker compose exec buoyup sh` |
| Reset demo chị Lan | `docker compose exec buoyup python /srv/BackEnd/src/scripts/reset_demo_seller.py` |
| Xem Agent 4/5 tự chạy | Trang Quản trị, mục "Khoản vay · Agent 4 giám sát" và "Agent 5 · Hậu kiểm" (giờ chạy gần nhất / lần tới); hoặc API `GET /v4/autopilot/status` (staff) |
| Đồng bộ lại danh mục ngân hàng từ chuỗi | Trang Quản trị, mục "Chuỗi & sổ cái", nút "Đồng bộ ngân hàng từ chuỗi" (cũng tự chạy khi khởi động) |
| Chạy giám sát với ngày giả định (demo cảnh báo vàng/đỏ) | Trang Quản trị, mục "Khoản vay", chọn "Ngày mô phỏng" rồi bấm "Chạy ngay" |
| Đổi tham số tín dụng | Không sửa tay. Agent 5 đề xuất, một admin khác người đề xuất duyệt trong trang Quản trị; mỗi phiên bản tham số được băm lên chuỗi |

Container tự khởi động lại khi máy reboot (`restart: unless-stopped`) và log được xoay vòng (5 × 20 MB).

**Chỉ chạy 1 bản sao (1 worker).** Vòng tự chạy của Agent 4/5 chạy trong tiến trình, còn SQLite chỉ cho một tiến trình ghi tại một thời điểm. Muốn nhiều bản sao thì phải chuyển sang Postgres và tách autopilot ra một tiến trình riêng (xem mục 17).

---

## 11. Sao lưu và khôi phục

Sao lưu (an toàn cả khi đang chạy):
```bash
cd /opt/buoyup && ./deploy/backup.sh        # tạo backups/buoyup-YYYYmmdd-HHMMSS.db
```
Sao lưu tự động mỗi đêm (crontab của người dùng có quyền docker):
```bash
crontab -e
# thêm dòng:
15 2 * * * cd /opt/buoyup && ./deploy/backup.sh >> backups/backup.log 2>&1 && find backups -name 'buoyup-*.db' -mtime +14 -delete
```
Sao lưu cả `BackEnd/API_config/.env` (nơi an toàn, tách khỏi máy chủ). **Mất `CREDIT_LEDGER_KEY` thì sổ cục bộ cũ không kiểm được nữa.** Dữ liệu trên chuỗi FISCO thật không bị ảnh hưởng.

Khôi phục (ví dụ từ file `backups/buoyup-20261014-021500.db`):
```bash
cd /opt/buoyup
docker compose stop buoyup
docker compose run --rm --no-deps -u root -v "$PWD/backups:/backups" buoyup sh -c \
  'cp /backups/buoyup-20261014-021500.db /data/buoyup.db && rm -f /data/buoyup.db-wal /data/buoyup.db-shm && chown 10001:10001 /data/buoyup.db'
docker compose start buoyup
docker compose logs --tail 20 buoyup     # kiểm tra startup
```

---

## 12. Cập nhật phiên bản mới

```bash
cd /opt/buoyup
./deploy/backup.sh                      # luôn sao lưu trước
# chép mã mới đè lên (rsync như mục 4, KHÔNG ghi đè BackEnd/API_config/.env)
docker compose up -d --build            # build lại image, giữ nguyên volume dữ liệu
docker compose logs --tail 50 buoyup    # kiểm tra startup
```
Bảng mới tự được tạo khi khởi động. Nếu bản mới **đổi cột** của một bảng có sẵn, cần viết script chuyển dữ liệu: hệ thống không có migration tự động.

---

## 13. Chạy không cần Docker

Dùng cho máy dev hoặc VPS không cài được Docker. Cần Python 3.12+ (đã thử với 3.12 và 3.14); muốn chạy test giao diện thì cần thêm Node 18+.
```bash
cd /opt/buoyup
./run-local.sh              # lần đầu tạo BackEnd/.venv và cài thư viện; chạy ở http://localhost:8000/
PORT=8080 ./run-local.sh    # cổng khác
./run-local.sh test         # 177 test backend + kiểm tra API + kiểm tra giao diện
./run-local.sh reset-lan    # làm mới tài khoản chị Lan
```
Dữ liệu nằm ở `./data/buoyup.db`. Cấu hình đọc từ `BackEnd/API_config/.env`; dùng biến `ENV_FILE` để trỏ chỗ khác. Muốn chạy như dịch vụ hệ thống, tạo unit systemd chạy `run-local.sh` với `WorkingDirectory=/opt/buoyup`.

Lệnh chạy tay tương đương:
```bash
cd /opt/buoyup/data && FRONTEND_DIR=/opt/buoyup/Frontend \
  /opt/buoyup/BackEnd/.venv/bin/uvicorn app.main:app --app-dir /opt/buoyup/BackEnd/src --host 0.0.0.0 --port 8000
```

---

## 14. Kiểm thử tự động

| Bộ | Lệnh (từ thư mục gốc) | Kết quả lúc bàn giao |
|---|---|---|
| Backend (pytest) | `cd BackEnd/src && ../.venv/bin/python -m pytest -q` | **177 passed** |
| Hợp đồng API, 9 kịch bản demo | `BackEnd/.venv/bin/python -B Frontend/tests/v4-api-check.py` | PASS (ghi `/tmp/v4-qa-api-evidence.json`) |
| Giao diện v4 (Node) | `cd Frontend/tests && node v4-ui-check.mjs` | **32 nhóm passed** (cần bằng chứng ở dòng trên) |
| Giao diện đăng nhập/ngân hàng | `BackEnd/.venv/bin/python -B Frontend/tests/c1-api-check.py && cd Frontend/tests && C1_API_EVIDENCE=/tmp/c1-api-evidence.json node c1-check.mjs` | **14 nhóm passed** |

Hoặc chạy gộp: `./run-local.sh test`.

Test luôn chạy với cơ sở dữ liệu tạm, tắt LLM, ép chuỗi `local`, nên **không bao giờ ghi lên chuỗi FISCO của team**. Kiểm thử chuỗi thật dùng một server giả (`httpx.MockTransport`).

---

## 15. Dịch vụ bên ngoài

### 15.1 Mô hình ngôn ngữ (LLM)
- API kiểu OpenAI (`POST {LLM_HOST}:{LLM_PORT}/v1/chat/completions`). Hiện là vLLM `Apero-LLM` tại `45.78.203.38:8003`.
- Dùng cho:
  - Agent 1: thứ tự gọi công cụ và ghi chú;
  - Agent 2: giải thích hạn mức và chat;
  - Agent 3: pha 1;
  - Agent 4: chọn tỷ lệ chia ngân hàng và viết thông báo cho người bán;
  - Agent 5: tóm tắt và đề xuất.
- Mọi đầu ra của mô hình đều đi qua bộ lọc của code: bộ lọc số, câu cấm, kiểm tra tỷ lệ chia. Lỗi hay vượt giới hạn thì hệ thống dùng đường template. **Máy LLM ngừng thì hệ thống vẫn chạy**, chỉ là câu chữ theo mẫu.

### 15.2 Chuỗi FISCO BCOS (dịch vụ của team)
- URL `https://fs.buoyup.app`. Tài liệu: `/docs/`; explorer công khai: `/explorer/`; OpenAPI lưu tại `BackEnd/API_config/fisco-chain-service.openapi.json`.
- BuoyUp dùng các endpoint:

| Endpoint | Dùng cho |
|---|---|
| `POST /v1/audit/anchors` | Neo dấu vân tay của từng bước hồ sơ (ủy quyền, biên bản xác minh, phiếu, niêm phong Agent 3, quyết định, giải ngân, trích nợ…) |
| `GET /v1/audit/anchors/{hồ sơ}/verify` | Kiểm tra chuỗi hash của một hồ sơ |
| `POST /v1/withdrawals` | Agent 4 giải ngân: số tiền tính bằng fen/đồng, `bankSplit` theo %, `requestId = disburse:<mã hồ sơ>` (gửi lại không chi hai lần) |
| `GET /v1/withdrawals/{id}` và `/verify` | Đọc và kiểm tra một lệnh giải ngân |
| `POST /explorer/api/decrypt` | Ngân hàng giải mã phần của mình |
| `GET /v1/banks`, `/v1/banks/{code}`, `/v1/overview` | Đồng bộ danh mục: hạn mức, chính sách, hợp đồng, khóa của 10 ngân hàng |
| `GET /v1/chain`, `/v1/regions` | Trạng thái nút, tỉnh/thành |

- Chuỗi không truy cập được:
  - **Anchor không quan trọng** được xếp hàng (outbox), Agent 4 tự gửi lại mỗi 5 phút.
  - **Anchor quan trọng** (niêm phong Agent 3, quyết định cổng) bị từ chối với lỗi 503 `CHAIN_UNAVAILABLE`, để không có hồ sơ nào được duyệt mà thiếu niêm phong.
  - **Giải ngân** xếp hàng chờ rồi gửi lại với cùng `requestId`, nên không chi hai lần.
- Quy tắc chia vốn B12 lấy hạn mức thật từ danh mục trên chuỗi:
  - tỷ lệ tối đa mỗi ngân hàng;
  - số tiền tối đa mỗi ngân hàng cho một khoản (đọc từ `maxLoanAmount`, xem mục 17);
  - phần tối thiểu mỗi lệnh;
  - khung lãi;
  - kỳ hạn tối đa;
  - điểm và tuổi cửa hàng tối thiểu.

  Trong vòng duyệt song song mỗi ngân hàng hợp tác áp các quy tắc này cùng chính sách riêng (`app/banks/syndicate.py`, `bank_decides`); kỳ hạn tối đa của các ngân hàng tham gia giới hạn khung kỳ hạn chào người vay. Ví dụ với danh mục trên chuỗi: chị Lan (điểm 4,6, 26 tháng) bị CMB (cần 4,7) và ICBC (cần 36 tháng) từ chối, BOC quá 30 giây, CCB đồng ý → WeBank 30% / CCB 70%, kỳ hạn chỉ còn 3 tháng (CCB cho vay tối đa 120 ngày).
- Muốn chạy không cần chuỗi thật thì đặt `BUOYUP_CHAIN_BACKEND=local`: sổ mô phỏng trong DB, giao diện ghi nhãn "Mô phỏng".

### 15.3 FATE
Chưa nối. Điểm liên ngân hàng lấy từ dữ liệu mẫu, và giao diện ghi rõ "Dữ liệu mẫu".

### 15.4 Nguồn dữ liệu người bán
Sáu nguồn (trang cửa hàng, đăng ký kinh doanh, dòng tiền, thuế 银税互动, tín dụng, FATE) hiện là **dữ liệu mẫu** (`app/data_sources/`). Hồ sơ chị Lan sinh tất định bằng `scripts/gen_lan_profile.py` và nằm trong `profiles/lan.json`. Nối nguồn thật thì thay các hàm trong `app/data_sources/sources.py`; agent và giải thuật không phải đổi.

---

### 15.5 Truy xuất điều luật (RAG)

- Kho: 794 điều tiếng Trung từ 14 văn bản trong `docs/agents/TQ` (`app/core/laws/corpus.json`). Kho được trích bằng `scripts/extract_laws.py`, hash ghi lên chuỗi.
- Tìm kiếm lai (`app/core/rag.py`):
  - BM25 theo cặp ký tự Trung, cộng bảng thuật ngữ Việt/Anh → Trung.
  - Embedding đa ngôn ngữ chạy trên máy (`fastembed`, mặc định `intfloat/multilingual-e5-large`, 2,2 GB).
  - Hai kết quả trộn bằng RRF. Không có mô hình thì tự lùi về BM25.
- Agent 3 tự đặt câu hỏi theo từng hồ sơ (mặt hàng, giấy phép, nhãn hiệu, chủ sở hữu hưởng lợi, đồng ý dữ liệu, mục đích vay, thanh toán ủy thác) và lưu kết quả ở `control.retrieval`.
  - Mỗi quy tắc đã bật được kiểm xem truy xuất có tìm thấy điều luật nó trích không.
  - Quyết định vẫn do quy tắc; trích dẫn vẫn phải khớp nguyên văn.
- API cho cán bộ: `GET /v4/legal/search?q=…`, `GET /v4/legal/articles/{id}`.
- Cấu hình trong `.env`:
  - `BUOYUP_RAG_CACHE`: thư mục chứa mô hình và vector, ví dụ `data/rag-cache`. Với Docker, đặt trong volume `data` để không tải lại.
  - `BUOYUP_RAG_MODEL`: tên mô hình embedding.
  - `BUOYUP_RAG_DENSE=0`: chỉ dùng BM25.
- Dựng sẵn bộ đệm: `cd BackEnd/src && ../.venv/bin/python scripts/build_rag_index.py`. Lần đầu tải mô hình và lập chỉ mục mất khoảng 6 phút; sau đó nạp trong vài giây.
- Đo chất lượng: `scripts/eval_rag.py`.
  - Bộ 42 câu `tests/rag_eval.json` dùng để viết bảng thuật ngữ.
  - Bộ kiểm tra riêng 22 câu `tests/rag_eval_holdout.json` có recall@5: BM25 0,59 → lai 0,82.
  - Test chất lượng có mô hình chỉ chạy khi đặt `BUOYUP_RAG_EVAL_DENSE=1`.

## 16. Xử lý sự cố

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| Container khởi động rồi thoát; log có `LedgerKeyMissing` | `APP_ENV` không phải dev/test mà thiếu `CREDIT_LEDGER_KEY` | Điền khóa (mục 6) rồi `docker compose up -d` |
| Log có `error parsing value for field ...` | Sai định dạng một biến trong `.env` (ví dụ danh sách JSON) | Sửa đúng `TEN=giatri`; danh sách viết JSON, ví dụ `["https://a.com"]` |
| `chain_catalog_sync_failed` trong log; trang Quản trị báo lỗi chuỗi | Máy chủ không ra được `fs.buoyup.app:443` hoặc dịch vụ chuỗi đang tắt | `docker compose exec buoyup python -c "import urllib.request;print(urllib.request.urlopen('https://fs.buoyup.app/healthz').read())"`. Tạm thời đặt `BUOYUP_CHAIN_BACKEND=local` |
| Hồ sơ dừng ở "Chờ cán bộ" với lý do "Chưa có ngân hàng đối tác nào nhận được hồ sơ ở mức này" | Không ngân hàng nào đủ điều kiện, hoặc trần của các ngân hàng không gánh đủ số tiền | Đúng thiết kế. Cán bộ xem tab "Agent 3", mục "Chính sách ngân hàng" để biết lý do từng ngân hàng |
| Câu trả lời của trợ lý luôn giống mẫu; log có `llm` lỗi hoặc timeout | Máy LLM không truy cập được | Kiểm tra `curl http://LLM_HOST:LLM_PORT/v1/models`. Hệ thống vẫn chạy bằng template |
| `database is locked` | Hai thao tác ghi dài chạy cùng lúc. Đã đặt chờ khóa 30 giây; vẫn gặp thì do có hơn 1 tiến trình cùng ghi | Chỉ chạy 1 container, không tăng `--workers` |
| Trang trắng, F12 báo 404 file `.js`/`.css` | Thiếu thư mục `Frontend/src` khi chép | Chép lại đủ `Frontend/`; kiểm tra `curl $URL/app/src/chung/bu/api.js` |
| Đăng nhập tài khoản demo báo sai mật khẩu | `APP_ENV=production` (không tạo tài khoản mẫu) hoặc đã đổi `BUOYUP_DEMO_PASSWORD` | Đặt `APP_ENV=demo` rồi khởi động lại, hoặc tạo người dùng ở trang Quản trị |
| `permission denied` khi ghi `/data` | Volume tạo bởi người dùng khác | `docker compose exec -u root buoyup chown -R buoyup /data` |
| Ngân hàng không giải mã được lệnh cũ | Lệnh tạo ở chế độ `local` mở bằng khóa cục bộ; lệnh trên chuỗi thật mở bằng khóa của dịch vụ chuỗi | Đúng thiết kế. Cổng ngân hàng tự chọn khóa theo từng lệnh |

Log chi tiết của một request: mỗi response có header `x-request-id`; tìm id đó trong `docker compose logs`.

---

### 16.1 Rà soát ngày 16/10/2026 (sáu điểm phản biện)

Thiết kế và quyết định: `docs/SellerGraph_core_tech_v5.html`. Tham số mới trong `core/params.py`, đổi qua quy trình duyệt của Agent 5:

| Điểm | Ở đâu trong code | Tham số |
|---|---|---|
| 1 Phân xử Agent 2 ↔ 3 | `agent3_control.phase2` (vòng hỏi đáp, bản ghi chuỗi `debate_round`), `gate` ghi `gate_decision` mọi kết cục | `arbitration.max_rounds` 2, `arbitration.on_no_acceptable` reject |
| 2 Agent 3 độc lập | `core/challenger.py` (đặc trưng không giao với Agent 2), pha 1 không thấy phương án đề xuất, `llm_tools.check_independence_at_startup` | `challenger.smaller_at` 0,30 · `escalate_at` 0,60; `AGENT3_REQUIRE_DISTINCT_MODEL` |
| 3 Tách Agent 4 | `agent4a_payout` (quyền giải ngân một lần `bu_payout_grants`), `agent4b_monitor`, `platform/capabilities.py`; vòng autopilot không giải ngân lại; cán bộ cấp lại: `POST /v4/officer/applications/{id}/reauthorize-payout` | `payout.token_ttl_min` 15 |
| 4 Khiếu nại | `agents/complaints.py`, `api/complaints.py`, bảng `bu_complaints`, mục Khiếu nại ở trang quản trị và trang người bán | `complaint.ack_days` 1 · `answer_days` 5 · `max_days` 15 · `review_days` 2 |
| 5 FATE mỏng | `sources.parse_coverage`, `agent1_verify.fate_state`, `algorithm.fate_alt_points`, trần `thin_fate_cap`; kịch bản demo `thin` | `fate.thin_min_banks` 2 · `thin_cap_mult` 0,5 · `thin_cap_abs` 50.000 |
| 6 Doanh thu khoản đầu | `algorithm.seed_ratio` (trần `seed_cap`), `agent1_verify.borrower_history` (dòng tiền TK WeBank), cờ `RISK_INFLOW_GAP`, `RISK_PASS_THROUGH` | `seed.ratio` 0,5 / 0,75 / 1,0 · `min_webank_months` 3 · `min_inflow_share` 0,8 |

Lưu ý vận hành: mô hình thách thức hiện huấn luyện trên dữ liệu **tổng hợp** (`simulated: true`); huấn luyện lại bằng `python scripts/train_challenger.py` khi có nhãn trả nợ thật. Dịch vụ FATE cần trả thêm `coverage` (`{"banks", "months"}`); dịch vụ cũ không trả thì hành vi như trước. Ở môi trường `production`, nếu bật LLM thì `LLM_AGENT3_MODEL_NAME` phải khác `LLM_MODEL_NAME`, nếu không server từ chối khởi động.

## 17. Bảo mật và giới hạn hiện tại

Đây là bản **demo / thí điểm**, chưa phải sản phẩm cho vay thật. Trước khi dùng với tiền và dữ liệu thật, cần xử lý các điểm sau:

1. **Dịch vụ chuỗi của team đang công khai khóa demo.** `GET /v1/overview` trả khóa riêng của mọi ngân hàng và khóa chủ. `/v1/*` không đòi token, nên ai cũng tạo được lệnh giải ngân (kho quỹ giả). Khi chạy thật: tắt `showDemoKeys`, đặt `apiToken` (BuoyUp gửi qua `BUOYUP_CHAIN_TOKEN`), và để ngân hàng tự giữ khóa riêng.
2. **Bốn nút FISCO chạy trên một máy do một bên vận hành**, nên câu "không ai sửa được một mình" chưa đứng vững (lỗ hổng 17 trong tài liệu thiết kế).
3. **Dữ liệu người bán và FATE là dữ liệu mẫu**; chưa nối nguồn thật (mục 15.4).
4. **`APP_ENV=demo`** tạo tài khoản mẫu có mật khẩu công khai và cho phép "mô phỏng tiền về". Khi chạy thật phải dùng `production`.
5. **CORS mặc định `["*"]`.** Giao diện đi kèm chạy cùng origin nên an toàn; nếu tách giao diện ra tên miền khác thì đặt danh sách cụ thể.
6. **SQLite, 1 tiến trình.** Đủ cho demo và thí điểm nhỏ. Muốn mở rộng: chuyển `DATABASE_URL` sang Postgres (SQLAlchemy hỗ trợ; cần kiểm lại các truy vấn JSON), và tách `autopilot.loop` ra tiến trình riêng.
7. **Diễn giải `maxLoanAmount`** của danh mục ngân hàng: BuoyUp hiểu là số tiền tối đa *mỗi ngân hàng góp* cho một khoản, không phải tổng khoản vay. Cần xác nhận với người làm dịch vụ chuỗi (xem `app/blockchain/chain_sync.py`).
8. **Lệch làm tròn:** chuỗi chia số tiền theo fen, BuoyUp tính phần mỗi ngân hàng bằng tệ chẵn. Khi hai bên lệch nhau, hệ thống ghi sự kiện `chain_legs_mismatch` để cán bộ đối soát.
9. **Không có migration cơ sở dữ liệu** (mục 12).
10. **Pháp lý:** các lỗ hổng 11, 13, 14, 15 trong tài liệu thiết kế (FATE và giấy phép, nền tảng ứng tiền rồi thu lại, ngân hàng có phải tự duyệt, tỷ lệ tối thiểu 30%) còn chờ nhóm quyết.

---

## 18. Đối chiếu với repo cũ

Bản này tách từ repo `sellergraph-core`. Thư mục cũ vẫn để nguyên ở máy phát triển.

| Cũ | Mới |
|---|---|
| `sellergraph-core/app/buoyup/algorithm.py`, `params.py`, `legal.py`, `stress.py`, `flow.py` | `BackEnd/src/app/core/` |
| `app/buoyup/agents/verify.py`, `advise.py`, `control.py` | `app/agents/agent1_verify.py`, `agent2_advise.py`, `agent3_control.py` |
| `app/buoyup/agents/disburse.py`, `signoff.py`, `llm_agent4.py` | `app/agents/agent4a_payout.py` + `agent4b_monitor.py` (tách ngày 16/10/2026; `agent4_signoff.py` đã bỏ khi làm loan circle), `agent4_llm.py` |
| `app/buoyup/agents/postaudit.py`, `llm_agent5.py` | `app/agents/agent5_postaudit.py`, `agent5_llm.py` |
| `app/buoyup/banks.py` | `app/banks/split.py` |
| `app/buoyup/chain*.py`, `withdrawals.py` | `app/blockchain/` |
| `app/buoyup/sources.py`, `profiles.py`, `consent.py` | `app/data_sources/` |
| `app/buoyup/autopilot.py` | `app/autopilot/loop.py` |
| `app/buoyup/api/*`, `views.py` | `app/api/` |
| `app/buoyup/tables.py`, `security.py`, `seed.py`, `events.py`; `app/config.py`, `app/db/*`, `app/llm/*` | `app/platform/` |
| `app/credit/ledger.py` (chỉ phần khóa), `app/credit/agents/guards.py` (chỉ câu cấm), `app/services/audit.py` (chỉ logger), `app/api/errors.py` | `app/platform/ledger_key.py`, `guards.py`, `audit.py`, `errors.py` |
| `docs/buoyup/API_CONTRACT_V4.md`, `sellergraph-core/.env.example` | `BackEnd/API_config/` |
| `frontend/*.html` (6 trang v4) | `Frontend/giaodien/` |
| `frontend/bu/*`, `styles.css`, `chat.css`, `console.css`, `assets/`, `fonts/`, `vendor/{fonts,gsap,lenis}` | `Frontend/src/chung/` |
| `frontend/workspace-v4.*`, `workspace.css` | `Frontend/src/nguoi-ban/` |
| `frontend/admin-v4.*`, `admin.css`, `officer-labels.js` | `Frontend/src/quan-tri/` |
| `frontend/bu/bank.js` | `Frontend/src/ngan-hang/bank.js` |
| `frontend/main.js` | `Frontend/src/trang-chu/main.js` |

**Không mang sang** (code SellerGraph v3, BuoyUp v4 không dùng):
- backend: `app/credit/`, `app/finance_core/`, `app/agents/` cũ, `app/connectors/`, `app/tools/`, `app/services/` (trừ logger), các route `/sellers`, `/credit`, `/onboarding`…;
- frontend: `officer.html`, `seller.html`, `app.html`, `ban_moi_v3_1/`, `ds/`, `demo-*.js`;
- test v3: `tests/credit`, `tests/unit`, `tests/integration`.

Tất cả vẫn còn trong git của repo cũ.

**Dữ liệu cũ:** bản mới bắt đầu với cơ sở dữ liệu trống: khi khởi động, hệ thống tự tạo ngân hàng, Bảng tham số v4.0 và tài khoản demo. Không nên chép `sellergraph.db` cũ sang, vì các khối của sổ cục bộ cũ được ký bằng khóa dev công khai, nên với `CREDIT_LEDGER_KEY` mới thì phần kiểm toàn chuỗi cục bộ sẽ báo hỏng.

---

## 19. Checklist bàn giao

Trước khi chép (máy cũ):
- [ ] Chép đủ `FINTACHATHONS/` (gồm `BackEnd/API_config/.env`) theo mục 4.
- [ ] Ghi lại nơi lưu bản sao `.env` và `CREDIT_LEDGER_KEY`.

Trên máy mới:
- [ ] Cài Docker và Compose (mục 5); `docker compose version` chạy được.
- [ ] `BackEnd/API_config/.env` có `APP_ENV`, `CREDIT_LEDGER_KEY`, `LLM_*`, `BUOYUP_CHAIN_*` (mục 6); đã `chmod 600`.
- [ ] `docker compose up -d --build` lên `healthy` (mục 7).
- [ ] Máy chủ ra được `fs.buoyup.app:443` và máy LLM; log có `chain_catalog_synced` và `llm_available: true`.
- [ ] Tên miền và HTTPS (mục 8); cổng 8000 không lộ ra ngoài.
- [ ] Smoke test 5 bước trên trình duyệt đạt (mục 9).
- [ ] Sao lưu tự động hằng đêm (mục 11); đã thử khôi phục một lần.
- [ ] Đọc mục 17 và quyết định những gì phải xử lý trước khi chạy thật.

Lưu ý về Docker: image **chưa được build trên máy phát triển** (máy đó không cài Docker). Thay vào đó đã kiểm tra tương đương: dựng môi trường Python sạch chỉ từ `requirements.txt`, rồi chạy đúng lệnh khởi động của container (`uvicorn … --app-dir`, `/data` làm thư mục làm việc, biến môi trường nạp từ `.env` như compose). Kết quả: 177 test pass, toàn bộ luồng chị Lan chạy trên Chrome không lỗi. Lần `docker compose up --build` đầu tiên trên máy mới là lần build image thật đầu tiên. Nếu lỗi ở bước build, xem log `docker compose build` và mục 16.
