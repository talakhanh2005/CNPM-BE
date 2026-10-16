# Triển khai

Healthcheck cho mọi môi trường: `GET /health` → `{"status": "ok", "version": "2.0.0", ...}`. `GET /ready` kiểm tra thêm kết nối database.

Chạy local không dùng Docker: xem [RUN-AND-TEST.md](RUN-AND-TEST.md). Tài liệu này chỉ nói về Docker và deploy.

## Thành phần cần có

| Thành phần | Vai trò | Có trong `docker-compose.yml`? |
| --- | --- | --- |
| API (`Dockerfile`) | FastAPI + WebSocket signaling | Có (`api`) |
| MongoDB | Database chính, chọn bằng `MONGO_URI` | Có (`mongo`) |
| AI service | `AI_BASE_URL` + `AI_API_KEY` (dịch vụ CNPM-NC, bắt buộc) | Không |

MongoDB là database duy nhất (`MONGO_URI`); video, tài liệu và media nằm trên Cloudinary. App tự tạo collection và index khi khởi động nên không có bước migration.

## Docker

```powershell
Copy-Item .env.example .env      # rồi sửa các biến bên dưới
docker compose up --build -d
docker compose ps                # api phải "healthy"
curl http://localhost:8000/health
```

Các biến `.env` cần khi chạy trong container:

- `JWT_SECRET`: chuỗi ngẫu nhiên từ 32 ký tự.
- `AI_BASE_URL` và `AI_API_KEY` của dịch vụ AI thật; thiếu `AI_API_KEY` thì API và worker không khởi động.
- `MONGO_URI` trong `.env` bị compose ghi đè.

Ghi chú:

- Compose ghi đè `MONGO_URI` thành `mongodb://mongo:27017/face_emotion` và `PORT` trong container luôn là 8000.
- App tự tạo index khi khởi động.
- Xem Mongo bằng mongo-express: `docker compose --profile tools up -d` → <http://localhost:8081>.
- Xoá dữ liệu Mongo: `docker compose down -v`.
- Chỉ chạy **1 worker** (WebSocket signaling giữ trạng thái phòng trong bộ nhớ).

## Staging / production

Dùng chung `Dockerfile`; `scripts/entrypoint.sh` chờ Mongo (nếu có `MONGO_URI`) rồi chạy uvicorn trên `$PORT`.

- Khai báo biến trong dashboard của nền tảng hoặc file `.env` quyền `600`; xem danh sách secret ở [SECRETS.md](SECRETS.md).
- `ENVIRONMENT=production`: app từ chối khởi động nếu `BCRYPT_ROUNDS` < 12, `AI_BASE_URL` không phải HTTPS, hoặc `ALLOW_TEACHER_REGISTRATION=true`. Production bắt buộc có `AI_API_KEY`.
- `CORS_ORIGINS` phải là domain FE thật, không dùng `*`.
- Đặt reverse proxy HTTPS (Caddy/Nginx) phía trước và bật upgrade WebSocket cho `/ws/meetings/{id}`.
- Dùng MongoDB có xác thực (Atlas hoặc user riêng) và đặt đủ vào `MONGO_URI`; không mở cổng 27017 ra ngoài.
- Giới hạn kích thước body ở proxy (`client_max_body_size` ≥ `MAX_UPLOAD_BYTES`), vì kiểm tra kích thước trong app chỉ chặn sau khi nhận dữ liệu.
- TURN server thật (`TURN_URLS`, `TURN_USERNAME`, `TURN_CREDENTIAL`) nếu học sinh ở sau NAT chặt.

## Checklist release

- [ ] Biến môi trường đầy đủ, không có giá trị mẫu (`JWT_SECRET`, `MONGO_URI`, `CORS_ORIGINS`, Cloudinary nếu bật upload, `AI_*`).
- [ ] `GET /health` và `GET /ready` trả 200 sau deploy.
- [ ] Backup MongoDB trước khi deploy: `mongodump --uri "$MONGO_URI" --out backup-<ngày>` (Atlas: snapshot).
- [ ] Rollback: ghi lại image tag/commit đang chạy; lỗi thì deploy lại tag cũ và restore backup nếu dữ liệu bị hỏng.
- [ ] `pytest` pass trên commit được release.

## Chưa được kiểm chứng

`Dockerfile` và `docker-compose.yml` mới được viết lại cho backend đã gộp. Chưa build được vì Docker daemon không chạy trên máy lúc viết. Cần chạy `docker compose up --build` một lần trước khi dựa vào.
