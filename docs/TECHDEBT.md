# Technical Debt

Chuyển từ BE A sang bản gộp. Mỗi mục là điều chưa làm hoặc chưa kiểm chứng, đã đối chiếu lại với code hiện tại ở mức mô tả; kiểm lại trước khi coi là còn hiệu lực.

## Media và tài liệu

- [ ] Chưa thử upload/tải thật trên Cloudinary (test dùng stub): kiểm tra `type=authenticated`, `raw` và `private_download_url` với một file PDF thật.
- [ ] Giới hạn kích thước chỉ chặn sau khi nhận dữ liệu: cần `client_max_body_size` (Nginx) hoặc tương đương khi deploy.
- [ ] Signed upload (`POST /media/signed-upload`) không gắn với phòng: file mồ côi nếu FE upload mà không lưu lại.
- [ ] `doc/ppt/xls` chỉ kiểm được chữ ký OLE, không phân biệt được ba loại với nhau.
- [ ] `unshare` theo danh sách id khi đang chia sẻ cả lớp không chặn được các id đó: phải unshare toàn bộ rồi share lại từng id.
- [ ] Giới hạn 10 MiB cho media chung theo gói Cloudinary miễn phí; tệp lớn phải nén trước.

## Frontend

- [ ] FE chưa có màn hình tài liệu: upload, chia sẻ, thu hồi, mở link công khai.
- [ ] FE chưa gọi `GET /meetings/{id}/emotions/timeline` và `POST /meetings/{id}/chat`.
- [ ] WebSocket chưa tự kết nối lại khi token hết hạn.
- [ ] Mock MSW của FE đã cũ so với API hiện tại.

## Việc còn mở theo README chốt nhiệm vụ (xem `CONTRACT-v1.md` §9)

- [ ] Upload ghi hình chưa chặn meeting `realtime` (test T02).
- [ ] `/report` vẫn mở cho meeting `realtime`.
- [ ] Dịch vụ AI chưa trả `model_version` và `segments`; cần trỏ `AI_MODEL_PATH` tới file trọng số đã train (xem REAL-DATA.md).

## Chưa thử trên hạ tầng thật

- [ ] Kiểm chatbot với Gemini trên nhiều câu hỏi thật (rate limit, model đổi tên).
- [ ] MongoDB thật (mới chỉ chạy test với mongomock).
- [ ] Build và chạy `Dockerfile` / `docker-compose.yml`.
