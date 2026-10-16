# Reid · Xác thực khuôn mặt

InsightFace **buffalo_l**: SCRFD-10G dò mặt + 5 điểm mốc, ArcFace `w600k_r50` lấy vector 512 chiều.
Góc đầu (yaw/pitch) tính từ 5 điểm mốc (`src/pose.py`), không chạy mô hình 1k3d68.

| Tệp | Việc |
|---|---|
| `src/engine.py` | Nạp buffalo_l (GPU CUDA nếu có, không thì CPU), giải mã khung hình, dò mặt, ArcFace |
| `src/pose.py` | Yaw/pitch từ 5 điểm mốc, chia 8 hướng của vòng xoay |
| `src/flows.py` | Luồng đăng ký (3 khung nhìn thẳng + 8 hướng) và đăng nhập (nhận diện + thử thách quay trái/phải) |
| `src/store.py` | Mẫu khuôn mặt theo người dùng: `data/<user_id>/templates.npy`, `meta.json`, `crops/*.jpg` |
| `../app/api/face.py` | API `/v4/face/*`; `/v4/auth/register` nhận `face_enroll_id` |
| `Frontend/src/xac-thuc-khuon-mat/` | Hộp thoại camera, vòng 8 hướng, gửi từng khung hình |

**Luồng.** Đăng ký: điền form → camera mở → nhìn thẳng (3 khung) → xoay đầu một vòng cho tới khi 8 cung sáng
→ tạo tài khoản, lưu 11 mẫu ArcFace. Đăng nhập: bấm *Đăng nhập bằng khuôn mặt* (email bỏ trống = tìm trên mọi
tài khoản) → nhận diện ở khung nhìn thẳng → quay mặt theo hướng ngẫu nhiên → vào phiên như đăng nhập mật khẩu.
Một khuôn mặt chỉ đăng ký được một tài khoản.

**Cài đặt.** `pip install -r Reid/requirements.txt` (đã gộp vào `requirements.txt`; cần trình biên dịch C/C++).
Máy có CUDA: thay `onnxruntime` bằng `onnxruntime-gpu`. Mô hình tự tải về `models/buffalo_l` lần đầu chạy.
Camera trên trình duyệt chỉ chạy qua HTTPS hoặc `http://localhost`.

**Cấu hình** (`.env`): `FACE_AUTH_ENABLED`, `FACE_MATCH_THRESHOLD` (0.45), `FACE_MODEL_ROOT`, `FACE_DATA_DIR`,
`FACE_SAVE_CROPS`, `FACE_DET_SIZE`, `FACE_WARMUP`, `FACE_REQUIRED_AT_SIGNUP`.

**Giới hạn.** Thử thách quay đầu (phải qua góc trung gian, mặt không nhảy chỗ, bỏ khung trùng) chặn một ảnh tĩnh hay
ảnh thẳng + ảnh nghiêng ghép lại, nhưng không phải chống giả mạo được chứng nhận: video quay sẵn cảnh người đó quay đầu,
hoặc một chuỗi ảnh ở các góc liên tiếp, vẫn có thể qua. Khung hình do trình duyệt gửi nên máy chủ không chứng minh được
chúng đến từ camera thật. Với khoản vay thật, nên dùng khuôn mặt làm yếu tố thứ hai hoặc thêm mô hình chống giả mạo. Phiên quét giữ trong bộ nhớ tiến trình (một worker, như Dockerfile).
`data/` chứa dữ liệu sinh trắc học: không commit, sao lưu cùng cơ sở dữ liệu.
