# Chạy với dữ liệu thật: MongoDB, Cloudinary, AI

Ứng dụng không còn chế độ giả. API và worker luôn dùng: **MongoDB** (dữ liệu), **Cloudinary** (video, tài liệu, media), **dịch vụ AI CNPM-NC** (nhận diện cảm xúc) và tuỳ chọn **Gemini** (chatbot). Test tự động vẫn dùng bản giả trong `tests/`, không ảnh hưởng khi chạy thật.

Sơ đồ: `FE (5173) → BE API (8000) ⇄ MongoDB` · `BE worker → AI (9000) → tải video từ Cloudinary`.

## 1. Lấy từng khoá / kết nối

| Biến trong `.env` | Lấy ở đâu |
| --- | --- |
| `MONGO_URI` | **Local:** `mongodb://localhost:27017/face_emotion` (cài MongoDB Community hoặc `docker compose up -d mongo`). **Atlas:** cloud.mongodb.com → Create cluster (M0 miễn phí) → *Database Access* tạo user/password → *Network Access* thêm IP của bạn → *Connect → Drivers* copy chuỗi `mongodb+srv://...` rồi thêm `/face_emotion` trước dấu `?`. Mật khẩu có ký tự đặc biệt phải URL-encode. |
| `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | console.cloudinary.com → *Settings → API Keys* (cloud name nằm ở *Dashboard*). Cần tài khoản Cloudinary; gói free đủ để thử. |
| `AI_API_KEY` | **Không lấy từ nhà cung cấp nào**: đây là khoá dùng chung do bạn tự đặt giữa BE và AI. Sinh bằng `python -c "import secrets; print(secrets.token_urlsafe(32))"` và dán **cùng một giá trị** vào `.env` của BE (`AI_API_KEY`) và `.env` của AI (`AI_API_KEY`). |
| `AI_BASE_URL` | Địa chỉ dịch vụ AI mà BE truy cập được, ví dụ `http://localhost:9000`. Production phải là HTTPS. |
| `GEMINI_API_KEY` (tuỳ chọn) | aistudio.google.com/apikey → *Create API key*. Chỉ gửi văn bản câu hỏi của chatbot (không gửi video hay khuôn mặt); để trống thì chatbot chạy bằng bộ luật. Model mặc định `gemini-3.5-flash` (đổi bằng `CHAT_LLM_MODEL`; model cũ như `gemini-2.0-flash` đã ngừng). |
| `JWT_SECRET` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `TEACHER_EMAIL_WHITELIST` hoặc `ADMIN_EMAIL`+`ADMIN_PASSWORD` | Tự đặt. Email trong whitelist đăng ký sẽ thành teacher; admin được tạo khi API khởi động. |
| `TURN_*` (khi học qua mạng khác nhau) | Nhà cung cấp TURN hoặc coturn tự host; mạng LAN/cùng máy chỉ cần STUN mặc định. |

`.env` đã nằm trong `.gitignore`. Không commit, không dán khoá vào chat.

## 2. Chuẩn bị mô hình AI

Trong thư mục AI (`CNPM-NC`):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
Copy-Item .env.example .env
```

Sửa `.env` của AI:

```dotenv
AI_API_KEY=<cùng giá trị với BE>
AI_MODEL_PATH=models/openemotion_efficientnet_b0.pth
AI_DEVICE=cpu
```

File trọng số mặc định trong repo là `models/openemotion_efficientnet_b0.pth` (không phải `emotion_model_best.pth` như `.env.example` ghi), nên **phải sửa `AI_MODEL_PATH`**. Thiếu hoặc sai trọng số thì AI không khởi động. Lưu ý chất lượng: số liệu hiện có trong `evaluation/` chỉ khoảng accuracy 0.29 / macro-F1 0.20, nên kết quả nhận diện còn yếu cho tới khi Khánh train và chốt checkpoint mới (đổi `AI_MODEL_PATH` là đủ, không phải đổi BE).

```powershell
.\.venv\Scripts\python.exe -m uvicorn openemotion.api.app:create_app --factory --app-dir src --host 127.0.0.1 --port 9000
```

Kiểm tra: `curl http://127.0.0.1:9000/health` trả OK sau khi model đã load. AI chỉ tải video từ `res.cloudinary.com` và `api.cloudinary.com` (`AI_DOWNLOAD_HOSTS`).

## 3. Chạy backend

Trong thư mục BE2 (đã có `.env` mẫu; điền các giá trị còn thiếu theo bảng trên):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
# Terminal 1: API
.\.venv\Scripts\uvicorn.exe app.main:create_app --factory --port 8000 --workers 1 --ws-max-size 1048576
# Terminal 2: worker (bắt buộc để job phân tích video chạy)
.\.venv\Scripts\python.exe -m app.worker
```

Thiếu `AI_API_KEY` thì API và worker dừng ngay với lỗi rõ ràng. Collection và index trong MongoDB do app tự tạo. Kiểm tra `GET http://localhost:8000/ready` trả `database: ok`.

> **Lưu ý dữ liệu cũ:** BE cũ (`CNPM-BE`) lưu `accounts`/`rooms`, còn BE2 dùng `users`/`meetings`/... nên **không dùng chung database**. `.env` đã trỏ sang database mới `face_emotion`; tài khoản cũ phải đăng ký lại.

## 4. Chạy frontend thật (không MSW)

Trong `CNPM-FE`: không đặt `VITE_USE_MOCKS` (mock chỉ bật khi giá trị đúng bằng `true`). Tạo `.env.local`:

```dotenv
VITE_API_URL=/api
```

`npm run dev` (Vite proxy `/api` và `/ws` sang `localhost:8000`). Nếu trình duyệt từng bật MSW, xoá service worker trong DevTools → Application.

## 5. Kiểm tra end-to-end bằng dữ liệu thật

1. Smoke test tự động (API đang chạy, AI đang chạy): `python scripts/test_live_ai_connection.py`. Script tạo tài khoản, meeting, gửi một frame qua BE sang AI thật và báo FAIL nếu kết quả bị đánh dấu mock. Nó không xoá dữ liệu đã tạo.
2. **Realtime:** Teacher đăng ký bằng email trong whitelist, tạo meeting `realtime`; Student vào bằng mã phòng, bật camera. Student thấy overlay, Teacher nhận log; trong MongoDB `emotion_samples` có bản ghi (`db.emotion_samples.find().sort({timestamp:-1}).limit(5)`), không có ảnh.
3. **Sau buổi học:** tạo meeting `after_session`, ghi hình, Teacher End, upload. Kiểm tra file xuất hiện trong Cloudinary Media Library (thư mục `face-emotion/<meeting_id>/`), `recordings.status` đi `uploaded → pending → processing → completed`, rồi `emotion_segments` có dữ liệu và `GET /meetings/{id}/emotions/timeline` trả segment.
4. **Chatbot:** `POST /meetings/{id}/chat` với "Từ 00:00 đến 00:30 có cảm xúc gì?" phải trả đoạn lấy từ DB.

## 6. Lỗi thường gặp

| Hiện tượng | Nguyên nhân / cách xử lý |
| --- | --- |
| API/worker thoát với "AI_API_KEY is required" | Chưa điền `AI_API_KEY` trong `.env` của BE. |
| Frame trả `fail_detection` + `ai_error` | AI chưa chạy, sai `AI_BASE_URL`, hoặc hai `AI_API_KEY` không khớp (AI trả 401). |
| Job kẹt `pending` | Worker chưa chạy hoặc worker và API trỏ khác `MONGO_URI`. |
| Job `failed`, "AI processing failed or timed out" | Xem log AI: model sai, video không tải được từ Cloudinary, hoặc quá `AI_PROCESSING_TIMEOUT_SECONDS`. |
| Upload video trả 503 | Thiếu hoặc sai khoá Cloudinary. |
| `ServerSelectionTimeoutError` | MongoDB chưa chạy hoặc Atlas chưa whitelist IP. |
