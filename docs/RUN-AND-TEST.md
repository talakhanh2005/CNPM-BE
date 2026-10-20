# Chạy và kiểm thử — Windows + MongoDB

## Cài đặt

Cần Python 3.11+ và MongoDB local hoặc Atlas. Chạy PowerShell trong thư mục backend:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Đặt chuỗi ngẫu nhiên vào JWT_SECRET. Cấu hình tối thiểu:

```dotenv
MONGO_URI=mongodb://localhost:27017/face_emotion
JWT_SECRET=<chuỗi-ngẫu-nhiên-ít-nhất-32-ký-tự>
AI_MODE=http
AI_BASE_URL=http://localhost:9000
```

Atlas dùng connection string mongodb+srv://. Nếu URI không có tên database, backend dùng face_emotion. Không cấu hình DATABASE_URL hoặc SQLSERVER_*. Không cần ODBC hoặc Alembic. Với demo local có thể đặt AI_MODE=mock và ALLOW_TEACHER_REGISTRATION=true; production không cho phép hai tùy chọn này.

Kiểm tra kết nối và tạo index:

```powershell
.\.venv\Scripts\python.exe -m scripts.check_mongo
```

Công cụ chỉ in trạng thái, không in URI/mật khẩu. Index cũng được tạo khi API/worker kết nối MongoDB lần đầu.

## API và worker

Terminal thứ nhất:

```powershell
.\.venv\Scripts\uvicorn.exe app.main:create_app --factory --host 0.0.0.0 --port 8000 --workers 1 --ws-max-size 1048576
```

Terminal thứ hai:

```powershell
.\.venv\Scripts\python.exe -m app.worker
```

Mở http://localhost:8000/docs. GET /health kiểm tra API; GET /ready kiểm tra MongoDB. Dùng MongoDB Compass hoặc mongosh để xem các collection. Cloudinary cần credential thật để upload; worker cần AI HTTP hợp lệ hoặc mock rõ ràng trong môi trường demo.

Tạo admin, mật khẩu được nhập qua prompt:

```powershell
.\.venv\Scripts\python.exe -m scripts.create_admin --email admin@example.com --name "Admin"
```

## Kiểm thử tự động

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app scripts
```

Pytest dùng mongomock với timezone UTC và index như ứng dụng. AI/storage được giả lập. Không cần bật API, worker hoặc MongoDB thật để chạy test. Các test này không thay thế kiểm thử kết nối, cạnh tranh ghi và crash recovery trên MongoDB thật.

| Nhóm | File test |
|---|---|
| Phòng học, signaling, frame, tài liệu, worker | tests/test_classroom_features.py |
| Callback, dashboard, admin, refresh token | tests/test_backend_tasks.py |
| Upload theo học sinh và báo cáo | tests/test_recording_student.py |
| Xóa phòng và dữ liệu con | tests/test_meeting_delete.py |
| Tên người tham gia | tests/test_participant_names.py |
| MongoDB index, insert, merge và model | tests/test_mongo_persistence.py |
| Cấu hình MongoDB và lỗi trùng dữ liệu | tests/test_mongo_compatibility.py |

## Kiểm thử thủ công

1. Đăng ký teacher/student ở POST /auth/register, đăng nhập ở POST /auth/login. Dùng Authorize trong Swagger với access token. Teacher registration cần key hoặc cấu hình demo local.
2. Teacher tạo phòng POST /meetings; student join bằng ID hoặc code. GET /meetings/{id} phải hiển thị membership và tên học sinh. Thử leave/rejoin, start/end và truy cập bằng giáo viên khác.
3. Với phòng realtime, student gửi POST /meetings/{id}/frames với frame_id, timestamp có timezone và JPEG/PNG base64 theo schema. Teacher kiểm tra emotion-logs và dashboard. PATCH logged chỉ đổi hiển thị; DELETE loại sample khỏi thống kê.
4. Teacher upload tài liệu qua endpoint trong Swagger với Content-Type và raw body đúng định dạng. Student thuộc phòng có thể xem danh sách và lấy URL tải. Người ngoài phòng phải bị từ chối.
5. Teacher upload video camera của từng học sinh qua POST /meetings/{id}/recordings?student_id={id}, raw video body. Thiếu student_id trả 422. Với after_session, worker tự xử lý job; realtime dùng endpoint yêu cầu phân tích theo API.
6. Kiểm tra trạng thái bản ghi và report sau khi worker hoàn tất. Đối chiếu phân quyền giữa các phòng và giữa các học sinh.
7. Admin gọi GET /admin/users và /admin/meetings. Response user không được lộ password_hash.
8. Teacher xóa phòng, kiểm tra các document liên quan đã bị xóa và phòng khác còn nguyên.

Hợp đồng request/response và signaling chi tiết nằm trong API.md; tích hợp AI trong AI-CONTRACT.md.

Ví dụ truy vấn mongosh:

```javascript
use face_emotion
db.users.find({}, {password_hash: 0})
db.meetings.find({teacher_id: "<teacher-id>"})
db.participants.find({meeting_id: "<meeting-id>"})
db.analysis_jobs.find({state: "pending"})
db.emotion_samples.find({meeting_id: "<meeting-id>"}).sort({timestamp: 1})
db.materials.getIndexes()
```

## Sự cố thường gặp

- ServerSelectionTimeoutError: kiểm tra MongoDB service, host/port, Atlas network access và firewall.
- AuthenticationFailure: kiểm tra user/password, authSource và quyền tạo index/đọc/ghi.
- DuplicateKeyError khi tạo index: database đã có dữ liệu trùng; sao lưu và xử lý trùng trước khi chạy lại.
- Job pending: kiểm tra worker chạy cùng MONGO_URI và log AI/storage.
- API trả 503 ở /ready: MongoDB chưa sẵn sàng; /health vẫn có thể trả 200.
- Meeting cũ thiếu mode vẫn được coi là realtime. Dữ liệu SQL cũ không tự chuyển sang MongoDB; cần quy trình xuất/nhập và đối chiếu riêng.
