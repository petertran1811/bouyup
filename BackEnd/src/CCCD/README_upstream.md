# OCR 身份证 Trung Quốc

## Chạy demo local có model

OCR là phần phụ thuộc tùy chọn, tách khỏi requirements chính. PaddlePaddle 2.6.2
có wheel matrix hẹp hơn backend; Dockerfile OCR dùng Python 3.10 riêng:

```bash
cd sellergraph-core
docker compose -f docker-compose.ocr.yml up --build
```

Mở <http://localhost:8000/app/china-id-ocr.html>. Model tiếng Trung được tải/cache
bởi PaddleOCR ở lần quét đầu tiên. Chạy trạng thái engine qua
`GET /v1/credit/ocr/china-id/status`; upload một mặt qua
`POST /v1/credit/ocr/china-id?side=front|back|auto` với multipart field `file`.

Ảnh JPEG kiểu chụp thử có sẵn tại
`sellergraph-core/data/ocr_demo/china_id_front_photo_demo.jpg`. Đây là ảnh tổng
hợp từ thẻ demo, có phối cảnh, nền và nhiễu nhẹ để kiểm tra đường upload ảnh;
dữ liệu đều giả và có watermark. Có thể gửi trực tiếp bằng curl:

```bash
curl -F 'file=@sellergraph-core/data/ocr_demo/china_id_front_photo_demo.jpg' \
  'http://127.0.0.1:8000/v1/credit/ocr/china-id?side=front'
```

Không dùng ảnh mẫu upstream có thể chứa danh tính thật. Hai ảnh trong
`sellergraph-core/data/ocr_demo/` là dữ liệu hư cấu có watermark; số demo cố ý
không qua kiểm tra mã vùng/checksum.

## Pipeline

1. Giới hạn upload 8 MB, chỉ JPEG/PNG; kiểm tra định dạng thực và số pixel.
2. PaddleOCR `lang=ch` đọc một mặt ảnh trong bộ nhớ; ảnh và raw OCR text không
   được ghi ra đĩa hoặc log.
3. Parser tất định nhận các trường mặt trước: 姓名, 性别, 民族, 出生, 住址,
   公民身份号码; mặt sau: 签发机关, 有效期限.
4. Định dạng 身份证号码 được kiểm tra theo cấu trúc 18 ký tự, ngày sinh và
   checksum GB 11643. Kết quả không hợp lệ được trả kèm cảnh báo, không tự sửa.
5. `review_required` luôn là `true`; OCR không xác minh tính xác thực hay chip.

Endpoint chỉ nhận request từ loopback vì ứng dụng demo chưa có xác thực tài
khoản. Docker Compose bind host port vào `127.0.0.1`; container chỉ tin subnet
nội bộ Docker được cấu hình trong `CHINA_ID_OCR_ALLOWED_NETWORKS`.

## Nguồn model

`shaojun427/idcard-ocr` là repo tham khảo có API ảnh hai mặt và parser trường
tiếng Trung/confidence. Checkout hiện không có file license; vì vậy code của repo
đó không được copy/vendor. Adapter trong SellerGraph gọi PaddleOCR trực tiếp.
Trước khi xử lý giấy tờ thật, cần cài OCR trên môi trường Linux/Python 3.10 và
đánh giá bằng ảnh có sự đồng ý, nhãn chuẩn và quy trình lưu/xóa phù hợp.
