# Face Emotion Backend — MongoDB

Backend FastAPI BE-01 -> BE-07, chạy trực tiếp bằng Python và **MongoDB**, phiên bản 1.1.0.

REST API, 1 WebSocket endpoint và các collection MongoDB cho auth, meeting, recording, analysis, emotion samples và tài liệu học tập. ConnectionManager cần một API process. Phòng học gồm một giáo viên và một học viên.

## Chạy trên Windows

Cần Python 3.11+ (ưu tiên 3.12) và MongoDB đang chạy. Backend đọc connection string Mongo từ biến môi trường `MONGO_URI`.

Mở PowerShell tại thư mục project đã giải nén:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Dán chuỗi vừa sinh vào `JWT_SECRET` của `.env`. Không cần activate virtualenv với cách gọi trực tiếp ở trên.

Sửa `.env` để trỏ tới MongoDB:

```dotenv
MONGO_URI=mongodb://localhost:27017/face_emotion
```

Nếu dùng MongoDB Atlas hoặc cluster có auth, đặt nguyên connection string Atlas vào `MONGO_URI`. Tên database được lấy từ path của URI; nếu URI không có path, backend dùng database mặc định `face_emotion`.

Chạy API:

```powershell
.\.venv\Scripts\uvicorn.exe app.main:create_app --factory --host 0.0.0.0 --port 8000 --workers 1 --ws-max-size 1048576
```

Mở [http://localhost:8000/docs](http://localhost:8000/docs) để thử REST API.

Terminal thứ hai, cùng thư mục project:

```powershell
.\.venv\Scripts\python.exe -m app.worker
```

Worker cần chạy để job phân tích chuyển từ pending sang processing/completed. Auth, meeting, signaling và report rỗng có thể test trước khi cấu hình Cloudinary. Test tự động dùng mock AI/storage nên không cần credential bên ngoài.

## Test từng task

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

| Task | Lệnh (sau `.\.venv\Scripts\python.exe -m`) |
|---|---|
| Ràng buộc phòng | `pytest tests/test_classroom_features.py -k "room or join" -v` |
| Signaling/refresh | `pytest tests/test_classroom_features.py -k "websocket or signaling" -v` |
| Realtime/AI/log | `pytest tests/test_classroom_features.py -k "frame or log or face or probability" -v` |
| Video/lịch sử/worker | `pytest tests/test_classroom_features.py -k "after_session or worker" -v` |
| Tài liệu | `pytest tests/test_classroom_features.py -k "material or pptx" -v` |
| SQL migration | `pytest tests/test_migration.py -v` |

Ứng dụng runtime dùng MongoDB qua `MONGO_URI`. Một số test và tài liệu legacy cho SQL Server vẫn còn trong repo để tham chiếu lịch sử, nhưng không còn là đường chạy mặc định của API/worker.

**Hướng dẫn chi tiết chạy và test thủ công từng task: `docs/RUN-AND-TEST.md`.**

## Nội dung bàn giao

| Module | Package | Model/schema chính |
|---|---|---|
| BE-01 | `app/modules/auth` | User, RefreshSession, RegisterIn, TokenOut |
| BE-02 | `app/modules/meetings` | Meeting, Participant, MeetingIn/Out |
| BE-03 | `app/modules/signaling` | Connection, AUTH, SDP/ICE/status messages, ConnectionManager |
| BE-04 | `app/modules/recordings` | Recording, RecordingOut, PlaybackOut |
| BE-05 | `app/modules/analysis` | AnalysisJob, AnalysisResult, StatusOut |
| BE-06 | `app/modules/emotions` | EmotionSample, FrameIn/Out |
| BE-07 | `app/modules/reports` | ReportSelection, ReportOut |

Mỗi package tách router/service/repository/model/schema. Signaling lưu socket trong bộ nhớ; report là read model trên dữ liệu phân tích.

- `docs/API.md`: endpoint, quyền, request/response mẫu và WebSocket protocol.
- `docs/ARCHITECTURE.md`: dependency và luồng nghiệp vụ.
- `docs/AI-CONTRACT.md`: hợp đồng batch/frame và mock AI.
- `docs/openapi.json`: REST schema import được vào công cụ API.
- `docs/schema.sqlserver.sql`: tài liệu DDL legacy của bản SQL Server trước đây.
- `docs/VERIFICATION.md`: kết quả kiểm chứng và những kết nối chưa được chạy thật.

## Những điểm cần cấu hình khi tích hợp

Teacher đăng ký cần `TEACHER_REGISTRATION_KEY`; có thể bật `ALLOW_TEACHER_REGISTRATION=true` chỉ để demo/test local. Video và tài liệu upload yêu cầu credential Cloudinary. Mặc định `AI_MODE=http`, cấu hình `AI_BASE_URL`/`AI_API_KEY` theo [AI contract](docs/AI-CONTRACT.md). Chỉ đặt rõ `AI_MODE=mock` khi cần dữ liệu giả để test.

Upload là raw body với buffer RAM có giới hạn, mặc định 64 MiB và 2 upload đồng thời; không ghi file video local. File dài hơn cần chia thành video/segment hoàn chỉnh trước khi upload. Worker dùng collection `analysis_jobs` và lease token để khôi phục job sau restart. Báo cáo chọn batch hoặc realtime để tránh đếm đôi cùng dữ liệu.

Chưa có credential Cloudinary/AI thật trong repo; local có thể chạy với mock AI/storage trong test.

## Tính năng bổ sung

- WebSocket nhận `FRAME` 3 FPS; REST `/meetings/{id}/frames` là fallback, dùng cùng rate limit. Chỉ student đang joined trong phòng ongoing, mode realtime được gửi.
- Mọi kết quả có `frame_id`, `timestamp`, 7 probabilities, `face_id`, `face_detected`; AI lỗi/không thấy mặt có `fail_detection` và lý do. Chat log phát khi thay đổi trạng thái hoặc sau 90 giây; xem lại tại `/meetings/{id}/emotion-logs`.
- `GET /meetings` trả lịch sử của teacher với `mode=realtime/after_session`. Upload video cho after_session tự gửi vào worker AI; FE vẫn cần ghi/upload video.
- Upload tài liệu qua `/meetings/{id}/materials?filename=...`; xem danh sách và tải qua URL ký 5 phút.
- Socket mới thay socket cũ cùng user. Refresh không tự leave. `ICE_SERVERS` được FE lấy qua `/meetings/{id}/ice-config`; cần FE và hạ tầng xác nhận TURN hoạt động.

MongoDB tự bổ sung collection/index khi khởi động; meeting cũ mặc định realtime. Nếu dùng SQL Server, chạy `python -m alembic upgrade head` trước khi chạy API/worker. Frame request cũ cần bổ sung `frame_id` và `timestamp`; AI response cũ cần nâng cấp theo contract mới. Đổi cấu hình `FRAME_INTERVAL_SECONDS=1` cũ thành `0.3333333333333333` và `MAX_ROOM_CONNECTIONS=100` thành `2` nếu có override.

Cài dependency kiểm thử bằng `python -m pip install -e ".[test]"`. Các test mới trong `tests/test_classroom_features.py` chạy cả SQLite và MongoDB giả lập; `tests/test_migration.py` kiểm tra migration. Xem [API](docs/API.md) để tích hợp FE.
