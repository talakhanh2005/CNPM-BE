# Hướng dẫn chạy và test từng task — Windows + SQL Server

## 1. Chuẩn bị và chạy ứng dụng

1. Giải nén project vào một thư mục mới, ví dụ `C:\Projects\face-emotion-backend`.
2. Mở SQL Server Management Studio, kết nối instance. Ghi lại Server name và cách đăng nhập. SSMS không thay thế SQL Server Database Engine.
3. Trong SSMS, mở `scripts/create_database.sql` rồi Execute để tạo database face_emotion. Nếu dùng database khác, tự tạo database và sửa SQLSERVER_DATABASE tương ứng.
4. Cài Microsoft ODBC Driver 18 bản phù hợp với Python/Windows 64-bit. Có thể kiểm tra driver sau khi cài dependency bằng lệnh bên dưới.
5. Mở PowerShell trong thư mục project:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Nếu Python 3.12 chưa có, cài Python 3.12 hoặc dùng Python 3.11+ đã cài để tạo venv. Dependency lock có điều kiện nền tảng cho Windows; uvloop chỉ được cài trên hệ điều hành hỗ trợ.

Sửa `.env`:

```dotenv
JWT_SECRET=<chuoi-ngau-nhien-vua-sinh>
SQLSERVER_SERVER='localhost\SQLEXPRESS'
SQLSERVER_DATABASE=face_emotion
SQLSERVER_TRUSTED_CONNECTION=true
SQLSERVER_ENCRYPT=true
SQLSERVER_TRUST_SERVER_CERTIFICATE=true
ALLOW_TEACHER_REGISTRATION=true
AI_MODE=mock
CORS_ORIGINS=["http://localhost:3000","http://localhost:8000"]
```

`ALLOW_TEACHER_REGISTRATION=true` là thiết lập demo local để thử role teacher. Windows Authentication dùng tài khoản Windows đang chạy Python; nên là cùng tài khoản đăng nhập SSMS. Nếu dùng SQL login:

```dotenv
SQLSERVER_TRUSTED_CONNECTION=false
SQLSERVER_USERNAME=<sql-login>
SQLSERVER_PASSWORD='<password>'
```

Tên instance ví dụ:

| Server name trong SSMS | Giá trị SQLSERVER_SERVER |
|---|---|
| `localhost` | `'localhost'` |
| `.\SQLEXPRESS` | '.\SQLEXPRESS' |
| `DESKTOP-ABC\SQLEXPRESS` | 'DESKTOP-ABC\SQLEXPRESS' |
| TCP host có cổng cố định | `'localhost,1433'` |

Giữ dấu nháy đơn trong `.env` để dấu `\` của named instance không bị hiểu thành escape. `TrustServerCertificate=true` chỉ dùng dev với chứng chỉ tự ký; production cần xác minh chứng chỉ. Các thuộc tính kết nối này theo [Microsoft ODBC connection keywords](https://learn.microsoft.com/en-us/sql/connect/odbc/dsn-connection-string-attribute).

```powershell
.\.venv\Scripts\python.exe -c "import pyodbc; print(pyodbc.drivers())"
.\.venv\Scripts\python.exe scripts/check_sqlserver.py
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe check
.\.venv\Scripts\uvicorn.exe app.main:create_app --factory --host 0.0.0.0 --port 8000 --workers 1 --ws-max-size 65536
```

Giữ terminal API mở. Mở terminal thứ hai ở cùng thư mục để chạy worker:

```powershell
.\.venv\Scripts\python.exe -m app.worker
```

Mở [Swagger UI](http://localhost:8000/docs). `/health` kiểm tra API; `/ready` kiểm tra kết nối SQL. Trong SSMS refresh Tables để thấy users, refresh_sessions, meetings, participants, recordings, analysis_jobs, analysis_results, emotion_samples và bảng nội bộ alembic_version.

## 2. Test tự động theo từng task

Chạy lệnh trong terminal thứ ba. Không cần bật API/worker cho pytest: test tự khởi tạo app và gọi worker function khi cần.

| Task | Lệnh PowerShell | Kết quả chính |
|---|---|---|
| BE-01 | `.\.venv\Scripts\python.exe -m pytest tests/test_auth.py -v` | Register/login/me; token hết hạn; password sai; refresh rotation |
| BE-02 | `.\.venv\Scripts\python.exe -m pytest tests/test_meetings.py -v` | Create/start/join/leave/end; kiểm tra role/owner |
| BE-03 | `.\.venv\Scripts\python.exe -m pytest tests/test_signaling.py -v` | OFFER/ANSWER/ICE; presence; camera/mic; disconnect |
| BE-04 | `.\.venv\Scripts\python.exe -m pytest tests/test_recordings.py -v` | Upload metadata; size/type/duration; owner; lỗi storage |
| BE-05 | `.\.venv\Scripts\python.exe -m pytest tests/test_analysis.py -v` | Enqueue→completed; failure/retry; lease recovery |
| BE-06 | `.\.venv\Scripts\python.exe -m pytest tests/test_emotions.py -v` | Frame→AI→teacher; throttle; ảnh sai; AI lỗi |
| BE-07 | `.\.venv\Scripts\python.exe -m pytest tests/test_reports.py -v` | Report rỗng; phân trang; tính tỷ lệ theo số mẫu |

Mặc định những lệnh trên dùng SQLite tạm để kiểm tra nghiệp vụ nhanh. Chúng không kiểm tra kết nối SQL Server của bạn. Để chạy trên SQL Server đã cấu hình, thêm `--sqlserver` vào đúng lệnh cần test, ví dụ:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_auth.py --sqlserver -v
.\.venv\Scripts\python.exe -m pytest tests/test_concurrency.py --sqlserver -v
.\.venv\Scripts\python.exe -m pytest --sqlserver -q
```

Test SQL Server tạo schema riêng cho mỗi test và xóa nó khi xong; tài khoản cần quyền tạo schema/bảng. AI và Cloudinary vẫn là mock. Không dùng `--sqlserver` nếu chỉ muốn test nhanh mà chưa cài database/ODBC driver.

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

Kiểm tra SQL trong SSMS:

```sql
SELECT id, email, full_name, role, created_at FROM dbo.users;
```

## 4. Test thủ công BE-02: meeting

Authorize teacher, gọi POST /meetings với `{"status":"ongoing"}`. Lưu id (meeting_id), code và teacher_id.

Authorize student, gọi POST /meetings/{meeting_id}/join. GET meeting phải có cả teacher và student, status joined. Gọi leave: student thành left nhưng record vẫn còn. Gọi join lại để chuẩn bị test WebSocket/frame. Có thể thử POST /meetings/join bằng `{"code":"<room-code>"}`.

Chưa end meeting ở bước này vì BE-03/BE-06 cần ongoing. Muốn test scheduled riêng: tạo room khác status scheduled, student join bị 409; teacher gọi start rồi student join thành công.

```sql
SELECT id, code, status, teacher_id FROM dbo.meetings;
SELECT meeting_id, user_id, status, joined_at, left_at FROM dbo.participants;
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

Điền credential Cloudinary trong `.env`, khởi động lại API và worker để đọc cấu hình mới. AI_MODE vẫn có thể là mock. Lấy một file MP4/WebM hợp lệ và dưới giới hạn dung lượng.

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

Response phải status uploaded, có duration và cloudinary_url. POST nhận raw body, không dùng multipart/FormData. File byte giả sẽ không upload thành công trên Cloudinary thật. GET /recordings/{id}/playback bằng teacher để lấy URL tải có chữ ký. Credential chưa có sẽ nhận 503; lúc đó dùng pytest để test flow với mock storage.

```sql
SELECT id, meeting_id, duration, size_bytes, status, cloudinary_url FROM dbo.recordings;
```

## 7. Test thủ công BE-05: job phân tích

Với recording vừa upload, Authorize teacher, POST /recordings/{recording_id}/analyze, không cần body. Response 202, status pending hoặc trạng thái hiện có nếu bấm lại.

Worker đang chạy sẽ đổi processing rồi completed. Gọi GET /recordings/{recording_id}/status để kiểm tra. Mock chạy nhanh nên có thể không quan sát được processing qua poll; test tự động kiểm tra transaction/lease. Tắt worker trước Analyze sẽ thấy pending giữ nguyên; bật worker lại để thấy job được xử lý.

```sql
SELECT id, recording_id, state, attempts, lease_until, error_message FROM dbo.analysis_jobs;
SELECT recording_id, completed_at, result FROM dbo.analysis_results;
```

Nếu status failed, đọc error_message và kiểm tra endpoint/credential AI; POST Analyze lại để retry. Bản mock không phân tích nội dung thật của video.

## 8. Test thủ công BE-06: frame realtime

Student phải joined và meeting ongoing. Teacher nên có WebSocket đang mở như bước BE-03. Dùng ảnh JPEG nhỏ, ví dụ 640x360 và dưới 512 KiB:

```powershell
$meetingId = "<meeting-id>"
$studentToken = "<student-access-token>"
$frameBase64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("C:\Images\frame.jpg"))
$body = @{frame_base64=$frameBase64;content_type="image/jpeg"} | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8000/meetings/$meetingId/frames" `
  -Headers @{Authorization="Bearer $studentToken"} `
  -ContentType "application/json" -Body $body
```

Response có emotion/confidence, student_id, timestamp và mock=true. Teacher socket nhận EMOTION. Nếu teacher offline, delivered_to_teacher=false nhưng SQL vẫn có mẫu. Gửi liên tiếp trong dưới một giây sẽ nhận 429. Sau một giây có thể thử lại.

```sql
SELECT TOP (20) student_id, [timestamp], emotion, confidence, mock
FROM dbo.emotion_samples ORDER BY [timestamp] DESC;
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
| Missing ODBC Driver / IM002 | Cài đúng ODBC Driver 18; kiểm tra pyodbc.drivers() |
| Server not found / 08001 | SQL Server service đang chạy; server/instance trùng SSMS; TCP/IP và cổng nếu dùng TCP |
| Login failed / 28000 | Windows account hoặc SQL username/password; mixed authentication nếu dùng SQL login |
| Cannot open database | Đã tạo face_emotion; login có user/quyền tương ứng trong database |
| Certificate chain error | Local: TrustServerCertificate=true; production: certificate hợp lệ và false |
| Teacher registration 403 | Đặt invite key hoặc cho phép đăng ký teacher trong demo local |
| Job giữ pending | Terminal worker chưa chạy hoặc API/worker đọc khác database/env |
| Test --sqlserver lỗi CREATE SCHEMA | Login test thiếu quyền; dùng tài khoản/database test được cấp quyền |
| Command script không import được app | Cài package bằng `pip install --no-deps -e .` trong cùng venv |

Đổi `.env` xong cần restart API/worker. JWT_SECRET phải giống nhau giữa các lần chạy nếu muốn token đang dùng tiếp tục hợp lệ.
