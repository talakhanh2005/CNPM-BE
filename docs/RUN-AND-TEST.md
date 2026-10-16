# Hướng dẫn chạy và test từng task — Windows + MongoDB

## 1. Chuẩn bị và chạy ứng dụng

1. Cài MongoDB (Community 7/8) hoặc tạo cluster Atlas miễn phí. Cách nhanh nhất là `docker compose up -d mongo`. File và video lưu trên Cloudinary, cần `CLOUDINARY_*` trong `.env`.
2. Mở PowerShell trong thư mục project:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Nếu Python 3.12 chưa có, dùng Python 3.11+ đã cài để tạo venv.

Sửa `.env`:

```dotenv
JWT_SECRET=<chuoi-ngau-nhien-vua-sinh>
MONGO_URI=mongodb://localhost:27017/face_emotion
ALLOW_TEACHER_REGISTRATION=true
AI_BASE_URL=http://localhost:9000
AI_API_KEY=<cung-gia-tri-voi-dich-vu-AI>
CORS_ORIGINS=["http://localhost:3000","http://localhost:8000"]
CLOUDINARY_CLOUD_NAME=<cloud>
CLOUDINARY_API_KEY=<key>
CLOUDINARY_API_SECRET=<secret>
```

`ALLOW_TEACHER_REGISTRATION=true` là thiết lập demo local để thử role teacher. Tên database lấy từ path của `MONGO_URI`; collection và index được app tự tạo khi khởi động, không có bước migration. Với Atlas dùng `mongodb+srv://<user>:<password>@<cluster>/face_emotion`.

```powershell
.\.venv\Scripts\uvicorn.exe app.main:create_app --factory --host 0.0.0.0 --port 8000 --workers 1 --ws-max-size 1048576
```

Giữ terminal API mở. Mở terminal thứ hai ở cùng thư mục để chạy worker:

```powershell
.\.venv\Scripts\python.exe -m app.worker
```

Mở [Swagger UI](http://localhost:8000/docs). `/health` kiểm tra API; `/ready` ping MongoDB. Dùng MongoDB Compass hoặc `docker compose --profile tools up -d mongo-express` để xem các collection users, refresh_sessions, meetings, participants, recordings, analysis_jobs, analysis_results, emotion_samples, emotion_segments, materials, emotion_labels.

## 2. Test tự động theo từng task

Chạy lệnh trong terminal thứ ba. Không cần bật API/worker cho pytest: test tự khởi tạo app và gọi worker function khi cần.

| Task | Lệnh PowerShell | Kết quả chính |
|---|---|---|
| Tính năng phòng học | `.\.venv\Scripts\python.exe -m pytest tests/test_classroom_features.py -v` | Slot học viên; socket refresh; frame/log; lịch sử/video; tài liệu; ICE config |

Các test chạy trên MongoDB giả lập (mongomock), không chạm database thật. Cài dependency và chạy:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest -q
```

AI và Cloudinary được giả lập trong test. Kiểm chứng MongoDB thật cần một instance riêng. Ứng dụng luôn gọi dịch vụ AI thật; xem [REAL-DATA.md](REAL-DATA.md).

## 3. Test thủ công BE-01: tài khoản và phân quyền

Trong Swagger, chọn POST /auth/register → Try it out. Tạo teacher:

```json
{"email":"teacher@example.com","password":"SecurePass123!","full_name":"Nguyễn An","role":"teacher"}
```

Tạo student:

```json
{"email":"student@example.com","password":"SecurePass123!","full_name":"Trần Bình","role":"student"}
```

Nếu không bật đăng ký teacher tự do, thêm teacher_registration_key đúng cấu hình. Gọi POST /auth/login với email/password từng người. Lưu access_token, refresh_token và id riêng cho teacher/student.

Bấm Authorize ở Swagger, dán **access token teacher** vào ô Bearer. Gọi GET /auth/me: phải trả role teacher và đúng tên tiếng Việt. Login password sai phải trả 401; đăng ký email trùng phải trả 409. Dán token student rồi gọi POST /meetings phải bị 403.

Kiểm tra trong `mongosh`:

```javascript
db.users.find({}, {_id: 0, id: 1, email: 1, full_name: 1, role: 1, created_at: 1})
```

## 4. Test thủ công BE-02: meeting

Authorize teacher, gọi POST /meetings với `{"status":"ongoing"}`. Lưu id (meeting_id), code và teacher_id.

Authorize student, gọi POST /meetings/{meeting_id}/join. GET meeting phải có cả teacher và student, status joined. Gọi leave: student thành left nhưng record vẫn còn. Gọi join lại để chuẩn bị test WebSocket/frame. Có thể thử POST /meetings/join bằng `{"code":"<room-code>"}`.

Chưa end meeting ở bước này vì BE-03/BE-06 cần ongoing. Muốn test scheduled riêng: tạo room khác status scheduled, student join bị 409; teacher gọi start rồi student join thành công.

```javascript
db.meetings.find({}, {_id: 0, id: 1, code: 1, status: 1, teacher_id: 1})
db.participants.find({}, {_id: 0, meeting_id: 1, user_id: 1, status: 1, joined_at: 1, left_at: 1})
```

## 5. Test thủ công BE-03: WebSocket signaling

Swagger không gửi WebSocket trực tiếp. Cách dễ nhất là dùng pytest cho module này. Nếu muốn quan sát thủ công, mở Developer Tools → Console trên trang `http://localhost:8000/docs`, rồi chạy:

```javascript
const meetingId = prompt("meeting_id");
const teacherId = prompt("teacher_id");
const teacherToken = prompt("teacher access_token");
const studentToken = prompt("student access_token");
function connect(token) {
  const ws = new WebSocket(`ws://localhost:8000/ws/meetings/${meetingId}`);
  ws.onopen = () => ws.send(JSON.stringify({type: "AUTH", token}));
  ws.onmessage = e => console.log(JSON.parse(e.data));
  return ws;
}
const teacherWS = connect(teacherToken);
const studentWS = connect(studentToken);
```

Chờ thấy JOIN rồi chạy tiếp:

```javascript
studentWS.send(JSON.stringify({
  type: "OFFER", target_id: teacherId,
  payload: {type: "offer", sdp: "v=0\r\n"}
}));
studentWS.send(JSON.stringify({type:"CAMERA_STATUS",payload:{enabled:false}}));
studentWS.send(JSON.stringify({type:"MIC_STATUS",payload:{enabled:true}}));
```

Console phải thấy teacher nhận OFFER có sender_id student. SDP ở đây chỉ là dữ liệu thử relay, không dựng cuộc gọi video thực. Giữ cả hai socket mở để test BE-06. Cuối cùng đóng studentWS sẽ phát LEAVE và cập nhật participant thành left; muốn gửi frame sau đó phải REST join lại.

## 6. Test thủ công BE-04: upload recording thật

Điền credential Cloudinary trong `.env`, khởi động lại API và worker để đọc cấu hình mới. Lấy một file MP4/WebM hợp lệ và dưới giới hạn dung lượng.

PowerShell:

```powershell
$meetingId = "<meeting-id>"
$teacherToken = "<teacher-access-token>"
$upload = Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8000/meetings/$meetingId/recordings" `
  -Headers @{Authorization="Bearer $teacherToken"} `
  -ContentType "video/mp4" -InFile "C:\Videos\lesson.mp4"
$upload | ConvertTo-Json -Depth 8
$recordingId = $upload.data.id
```

Response phải status uploaded, có duration và cloudinary_url. POST nhận raw body, không dùng multipart/FormData. File byte giả sẽ không upload thành công trên Cloudinary thật. GET /recordings/{id}/playback bằng teacher để lấy URL tải có chữ ký. Credential chưa có sẽ nhận 503; hãy điền khoá Cloudinary thật (xem REAL-DATA.md).

```javascript
db.recordings.find({}, {_id: 0, id: 1, meeting_id: 1, duration: 1, size_bytes: 1, status: 1, cloudinary_url: 1})
```

## 7. Test thủ công BE-05: job phân tích

Với recording vừa upload, Authorize teacher, POST /recordings/{recording_id}/analyze, không cần body. Response 202, status pending hoặc trạng thái hiện có nếu bấm lại.

Worker đang chạy sẽ đổi processing rồi completed. Gọi GET /recordings/{recording_id}/status để kiểm tra. Test tự động kiểm tra lease. Tắt worker trước Analyze sẽ thấy pending giữ nguyên; bật worker lại để thấy job được xử lý.

```javascript
db.analysis_jobs.find({}, {_id: 0, id: 1, recording_id: 1, state: 1, attempts: 1, lease_until: 1, error_message: 1})
db.analysis_results.find({}, {_id: 0, recording_id: 1, completed_at: 1, result: 1})
```

Nếu status failed, đọc error_message và kiểm tra endpoint/credential AI; POST Analyze lại để retry.

## 8. Test thủ công BE-06: frame realtime

Student phải joined và meeting ongoing. Teacher nên có WebSocket đang mở như bước BE-03. Dùng ảnh JPEG nhỏ, ví dụ 640x360 và dưới 512 KiB:

```powershell
$meetingId = "<meeting-id>"
$studentToken = "<student-access-token>"
$frameBase64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("C:\Images\frame.jpg"))
$body = @{frame_id=[guid]::NewGuid().ToString();timestamp=[DateTimeOffset]::UtcNow.ToString("o");frame_base64=$frameBase64;content_type="image/jpeg"} | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8000/meetings/$meetingId/frames" `
  -Headers @{Authorization="Bearer $studentToken"} `
  -ContentType "application/json" -Body $body
```

Response có emotion/confidence, 7 probabilities, face_id, face_detected, frame_id, timestamp và received_at. Teacher nhận EMOTION khi trạng thái đổi hoặc sau 90 giây. Nếu teacher offline, delivered_to_teacher=false nhưng database vẫn có mẫu. Mặc định gửi cách nhau ít nhất 334 ms (~3 FPS); nhanh hơn bị 429. WebSocket FRAME là kênh chính, xem API.md. AI thật không thấy mặt hoặc lỗi có fail_detection và failure_reason.

```javascript
db.emotion_samples.find({}, {_id: 0, student_id: 1, timestamp: 1, emotion: 1, confidence: 1, mock: 1}).sort({timestamp: -1}).limit(20)
```

## 9. Test thủ công BE-07: báo cáo

Authorize teacher, lần lượt gọi:

```text
GET /recordings/{recording_id}/analysis
GET /meetings/{meeting_id}/report
GET /meetings/{meeting_id}/report?source=realtime
```

Recording completed có distribution/timeline/summary. Source=auto ưu tiên batch đã completed, vì vậy dùng source=realtime nếu muốn thấy mẫu vừa gửi ở BE-06. Room chưa có phân tích trả mảng/object rỗng có thông báo, không phải lỗi 500. Token student hoặc teacher không sở hữu phòng phải bị 403.

Cuối cùng teacher gọi POST /meetings/{meeting_id}/end. GET meeting phải ended, ended_at có giá trị; WS nhận MEETING_ENDED rồi đóng. Student không thể join/gửi frame vào phòng ended.

## Lỗi kết nối thường gặp

| Hiện tượng | Kiểm tra |
|---|---|
| ServerSelectionTimeoutError | MongoDB chưa chạy hoặc `MONGO_URI` sai host/cổng; Atlas cần whitelist IP |
| Authentication failed | User/password trong `MONGO_URI`; có thể cần `?authSource=admin` |
| Duplicate key khi khởi động | Dữ liệu cũ vi phạm unique index (email, code, public_id) |
| Teacher registration 403 | Đặt invite key hoặc cho phép đăng ký teacher trong demo local |
| Job giữ pending | Terminal worker chưa chạy hoặc API/worker đọc khác database/env |
| WebSocket frame đóng vì quá kích thước | Chạy Uvicorn với --ws-max-size 1048576 |
| Command script không import được app | Cài package bằng `pip install --no-deps -e .` trong cùng venv |

Đổi `.env` xong cần restart API/worker. JWT_SECRET phải giống nhau giữa các lần chạy nếu muốn token đang dùng tiếp tục hợp lệ.
