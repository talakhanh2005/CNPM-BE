# Bàn giao Backend 1.2.0 — 12/10/2026

Các mã BE-01…BE-10 bên dưới theo thứ tự 10 task trong ảnh công việc; khác với mã module BE-01…BE-07 lịch sử của repository.

| Task | Kết quả trong repository | Nghiệm thu |
|---|---|---|
| BE-01 API contract meeting/emotion/auth | OpenAPI, schema WebSocket, bảng mapping và ví dụ trong tài liệu này | Đã xuất; cần FE/AI xác nhận contract |
| BE-02 Meeting 1-N | Membership nhiều học viên, join idempotent, leave/rejoin, signaling target, socket replacement | Test 1 teacher + 3 students; còn kiểm thử media/TURN thật |
| BE-03 Emotion log/persistence/authorization | Lưu prediction; query student/time; pagination + total; PATCH visibility; DELETE theo ownership | Regression SQLite/Mongo giả lập |
| BE-04 Realtime aggregation | Callback nội bộ và EMOTION_AGGREGATE, cửa sổ 30 giây, chỉ teacher của phòng nhận | Regression callback, duplicate, teacher WS |
| BE-05 Dashboard/summary | Distribution, averages, trend, ratios theo meeting/student/time | Regression số liệu, empty-state, filter |
| BE-06 RBAC/Admin | Admin list users/meetings; dependency role; script provision admin; SQL migration | Regression 401/403/200 và chặn self-registration |
| BE-07 Integration FE-AI-BE | AI request/response giữ schema hiện có; bảng mapping FE cụ thể dưới đây | Chưa đạt E2E FE thật: FE hiện vẫn chạy MSW/mock |
| BE-08 Postman/API regression | Collection 43 requests + environment; pytest cho WS/AI/log/worker | pytest đã chạy; Postman/Newman chưa chạy trên server thật |
| BE-09 Security regression | Cross-owner, invalid/expired/wrong-type JWT, role claim giả, admin/self-registration, student direct URL | Đạt các case tự động; không thay thế audit triển khai |
| BE-10 Final regression & core candidate | Phiên bản 1.2.0; manifest SHA-256 để review/freeze contract | Candidate local; chưa release/deploy và chưa freeze bởi FE/AI |

## Contract chính thức và mapping FE

Base REST `http://localhost:8000`; WS `ws://localhost:8000/ws/meetings/{meeting_id}`. Envelope `{success,data,message}`; lỗi `{success:false,data:{code,details},message}`. JWT xác định identity; role đọc lại từ database, không nhận role từ request/client để cấp quyền.

| FE mock hiện có | Backend thật | Cách tích hợp |
|---|---|---|
| `/api/auth/login` với `username,password,role` | `/auth/login` với `email,password` | Form dùng email thật; không dùng role để xác thực |
| Register `username,password,role` | `email,password,full_name,role` | Mật khẩu >=8 ký tự, <=72 UTF-8 bytes; teacher cần invite |
| Login trả `token,user` | `access_token,refresh_token,token_type,expires_in` | Lưu access/refresh; gọi `/auth/me` lấy user; UI dùng `full_name` |
| `/api/rooms`, `hostId`, `participantMode` | `/meetings`, `teacher_id`, `student_ids`, `participants` | Chuyển API adapter sang meeting contract; room code không phải meeting ID |
| `/api` mặc định và MSW bật vô điều kiện | Backend root path | FE cần disable MSW khi tích hợp và cấu hình proxy `/api` -> backend bỏ prefix, hoặc baseURL thật |
| Mock report | `/meetings/{id}/dashboard`, `/summary`, `/report` | Chart distribution là % 0–100; ratios là 0–1; report batch/realtime có `time_basis` |
| Một remote peer | WS JOIN có danh sách `peers` | FE quản lý peer connection theo user_id; OFFER/ANSWER/ICE có target_id |

Backend không tự sửa payload mock sang user thật. FE mock có username tùy ý, mật khẩu 4 ký tự và token giả; các giá trị này không phải credential Backend. Việc FE chấp nhận contract và chạy thật là điều kiện nghiệm thu còn lại của BE-01/BE-07.

Meeting có một teacher chủ phòng và nhiều student. `student_ids` chứa toàn bộ membership student (kể cả đã leave); `participants[].status` xác định ai đang joined. `student_id` chỉ giữ để đọc dữ liệu legacy, không còn dùng làm quyền hay khóa slot. Teacher khác/admin không được join như teacher. Socket mới cùng user thay socket cũ; disconnect mạng giữ membership để reconnect. Default tối đa 100 socket/phòng, config `MAX_ROOM_CONNECTIONS>=4`; giới hạn này áp dụng presence, không giới hạn lịch sử membership. Chạy **một API process**; multiworker cần distributed presence/locks/limiter.

Ví dụ tạo và join:

```http
POST /meetings
Authorization: Bearer <teacher_access_token>
Content-Type: application/json

{"mode":"realtime","status":"ongoing"}
```

```http
POST /meetings/join
Authorization: Bearer <student_access_token>
Content-Type: application/json

{"code":"<code_from_create_response>"}
```

## Emotion log và callback AI

Student gửi REST `/meetings/{id}/frames` hoặc WS FRAME, cùng FrameIn như [API.md](API.md). Backend gắn student_id từ JWT, validate frame và gọi AI. Khóa idempotency `(meeting_id,student_id,frame_id)` kiểm tra dưới meeting lock trước persistence; duplicate trả `409 DUPLICATE_FRAME` khi đã qua rate limit (retry quá sớm vẫn trả 429). Hai học viên được dùng cùng frame_id. Index lookup không unique để giữ được dữ liệu legacy; bảo đảm serialize phụ thuộc một API process. Không gửi lại frame ID đã lưu sau reconnect.

Callback trusted: `POST /internal/emotions`, header `X-AI-Key` khớp `INTERNAL_AI_KEY`. Key rỗng vô hiệu endpoint (401). Đây là callback tùy chọn; đường Backend gọi AI HTTP vẫn là mặc định. `AI_API_KEY` và `INTERNAL_AI_KEY` phục vụ hai chiều khác nhau.

```json
{
  "meeting_id":"<meeting_uuid>",
  "student_id":"<student_uuid>",
  "result":{
    "frame_id":"callback-0001","timestamp":"2026-10-12T03:00:00Z",
    "face_detected":true,"face_id":"face-1","emotion":"happy","confidence":0.8,
    "probabilities":{"happy":0.8,"neutral":0.1,"sad":0.02,"angry":0.02,"surprised":0.02,"fearful":0.02,"disgusted":0.02},
    "failure_reason":null,"mock":false
  }
}
```

Success: `{"success":true,"data":{"sample_id":"<uuid>","logged":true},"message":"OK"}`. Student phải tồn tại, có role student, joined trong phòng ongoing/realtime. No-face/AI-error dùng cùng FrameResult. Không nhận raw arbitrary emotion thiếu probabilities/frame metadata.

`GET /meetings/{id}/emotion-logs?student_id=S&start=2026-10-12T03:00:00Z&end=2026-10-12T04:00:00Z&offset=0&limit=100`: teacher owner, timestamp filter inclusive; sort timestamp/id ổn định; pagination tại DB; response `{items,total,offset,limit}`. Chỉ trả `logged=true`; mọi sample vẫn nằm trong analytics.

`PATCH /meetings/{id}/emotion-logs/{sample_id}` body `{"logged":false}` chỉ sửa visibility, không sửa inference. `DELETE` xóa sample khỏi DB và analytics. Cả hai yêu cầu teacher owner, xác nhận sample thuộc đúng meeting; student/cross-owner 403. Các thao tác này không phát event xóa; FE refetch dashboard sau thao tác. Frame ingestion là đường create chính thức.

## Dashboard và WS aggregate

`GET /meetings/{id}/dashboard` và `/summary` có cùng schema. Query `student_id,start,end,bucket_seconds` (1–3600, mặc định 60). Date phải có timezone; start>end trả 422. Chỉ dữ liệu realtime; báo cáo video tiếp tục dùng `/report?source=batch`. Dashboard không merge video với realtime để tránh đếm đôi.

- `sample_count`: mẫu có face và một trong 7 lớp; `total_samples` bao gồm fail_detection.
- `distribution`: % theo số mẫu, không trung bình % giữa học viên; đủ 7 lớp, empty trả zero.
- `average_confidence`: trung bình confidence mẫu hợp lệ; empty null.
- `average_probabilities`: trung bình probabilities trên mẫu hợp lệ; legacy thiếu probabilities tính 0.
- Positive = happy; negative = sad/angry/fearful/disgusted; neutral group = neutral/surprised. Đây là quy ước dashboard, không suy diễn sức khỏe/tâm lý.
- Các `*_ratio` là fraction 0–1; `positive_negative_ratio` = positive_count/negative_count, null khi denominator=0.
- `students` breakdown theo student_id; `trend` buckets theo UTC epoch, sort tăng dần.

Sau persistence, teacher đang online nhận envelope data `type:"EMOTION_AGGREGATE"` + DashboardOut + `window_seconds:30`. Event có meeting_id và breakdown student; không gửi cho student hoặc phòng khác. Window lọc theo timestamp chụp do client/AI cung cấp; sai giờ client có thể làm mẫu nằm ngoài window. `EMOTION` vẫn là event log gốc; aggregate gửi cả khi trạng thái không đổi. WS là best effort; REST/DB là nguồn kiểm chứng.

Dashboard hiện đọc các sample được chọn để tính thống kê; nên dùng time range cho lịch sử lớn. Aggregate giới hạn cửa sổ 30 giây. Chưa có test tải 100 người hay bảo đảm latency production.

## Admin và triển khai

`GET /admin/users`, `GET /admin/meetings`, offset>=0, limit=1–100; chỉ admin, không lộ password_hash. Admin có view tổng quát riêng, không bypass teacher-owned dashboard hay join lớp. Public register không chấp nhận role admin. Provision từ console:

```powershell
.\.venv\Scripts\python.exe -m scripts.create_admin --email admin@example.com --name "Admin"
```

Password nhập qua prompt; account email đã tồn tại bị từ chối, không tự nâng quyền. SQL Server cần `python -m alembic upgrade head` (revision `20261012_backend`); MongoDB khởi động thêm index. Không chạy migration/provision trên DB thật trong lần triển khai code này. SQL migration đã kiểm thử qua SQLite với dữ liệu legacy; SQL Server thật cần xác nhận riêng.

Nếu `.env` cũ đặt `MAX_ROOM_CONNECTIONS=2`, đổi thành 100; config 2 bị từ chối. Đặt `EMOTION_AGGREGATION_WINDOW_SECONDS=30`; chỉ thêm `INTERNAL_AI_KEY` khi dùng callback. Không cần đổi AI seven-class contract.

## Kiểm thử và release candidate

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check --no-cache app tests scripts/create_admin.py scripts/export_contract.py
.\.venv\Scripts\python.exe -m scripts.export_contract
```

Import [collection](backend.postman_collection.json) và [environment](backend.postman_environment.json) vào Postman. Điền credential của teacher, student/student2/student3, outsider (teacher khác), admin. Chạy theo thứ tự; mỗi lần tạo room mới. Collection kiểm tra status/envelope/permission và schema fields; WS/callback/worker được pytest kiểm tra riêng. Không có credential thật trong artifact. Sau khi cấu hình Newman có thể chạy:

```powershell
newman run docs/backend.postman_collection.json -e docs/backend.postman_environment.json
```

[contract-manifest.json](contract-manifest.json) chứa SHA-256 của OpenAPI và schema client WS. Đây là candidate để review/freeze; không đồng nghĩa đã deploy hay FE/AI phê duyệt. Sinh lại manifest khi đổi contract trước freeze. Trước khi release thật cần FE adapter + multi-peer media, MongoDB/TURN/AI/Cloudinary thật và chạy collection với account thật.
