# Tổng kết chức năng Backend đã bổ sung và chỉnh sửa

Ngày cập nhật: 12/10/2026. Backend: `face-emotion-backend`, phiên bản hiện tại `1.2.0`.

Tài liệu tổng hợp các thay đổi đang có trong workspace và phần chỉnh sửa recording/report vừa thực hiện. Các mục meeting nhiều học sinh, emotion log, dashboard, callback và admin đã có trong đợt cập nhật trước; phần mới nhất siết quy định upload theo học sinh và hoàn thiện API report. Đây là kết quả code và kiểm thử local, chưa phải bản đã triển khai trên server thật.

## 1. Meeting có một giáo viên và nhiều học sinh

Backend sử dụng membership của từng người tham gia để quản lý phòng học. `student_ids` chứa danh sách học sinh đã có membership, kể cả người đã rời phòng; `participants[].status` cho biết ai đang tham gia. Trường `meeting.student_id` cũ giữ cho dữ liệu legacy, không dùng để xác định quyền hoặc giới hạn một học sinh.

Học sinh có thể join, leave và rejoin. Join lặp lại không tạo membership trùng. Giáo viên khác không được tham gia với tư cách chủ phòng. Meeting hỗ trợ hai chế độ `realtime` và `after_session`, độc lập với trạng thái vòng đời phòng.

**Ý nghĩa:** quản lý đúng lớp nhiều học sinh và xác định quyền theo từng membership.

**Code liên quan:** `app/modules/meetings/model.py`, `repository.py`, `schema.py`, `service.py`, `router.py`.

## 2. Signaling và kết nối WebSocket

Signaling hỗ trợ chuyển OFFER/ANSWER/ICE theo `target_id` để Frontend quản lý nhiều peer. Kết nối mới của cùng một người thay kết nối cũ; việc dọn kết nối cũ không xóa nhầm kết nối mới. Mất kết nối mạng giữ membership để người dùng reconnect. Xử lý AI không chặn luồng signaling.

Giới hạn mặc định là 100 socket/phòng. Cấu hình `MAX_ROOM_CONNECTIONS` phải từ 4 trở lên. Backend hiện cần chạy một API process vì presence, locks và limiter còn nằm trong bộ nhớ của process.

**Ý nghĩa:** hỗ trợ nhiều người trong cùng phòng và giảm lỗi khi refresh/reconnect. Frontend vẫn cần quản lý peer connection theo `user_id`.

**Code liên quan:** `app/modules/signaling/manager.py`, các module meetings/signaling và `app/core/config.py`.

## 3. Ghi nhận cảm xúc và quản lý emotion log

Học sinh gửi frame qua REST `POST /meetings/{id}/frames` hoặc WebSocket FRAME. Backend xác định học sinh từ JWT, kiểm tra frame, gọi AI và lưu kết quả. Dữ liệu có emotion, confidence, probabilities của 7 lớp, frame ID, timestamp và trạng thái phát hiện khuôn mặt.

Trường hợp không có khuôn mặt hoặc AI lỗi được biểu diễn bằng `fail_detection` cùng lý do. Backend kiểm tra frame trùng theo `(meeting_id, student_id, frame_id)`; hai học sinh được dùng cùng frame ID. Kết quả không được lưu nếu học sinh đã leave hoặc meeting đã kết thúc trong lúc AI xử lý.

| API | Chức năng |
|---|---|
| `GET /meetings/{id}/emotion-logs` | Lọc theo học sinh/thời gian, phân trang và trả tổng số log |
| `PATCH /meetings/{id}/emotion-logs/{sample_id}` | Sửa `logged` để thay đổi khả năng hiển thị log |
| `DELETE /meetings/{id}/emotion-logs/{sample_id}` | Xóa sample khỏi database và thống kê |

Chỉ giáo viên chủ phòng được đọc/sửa/xóa log. PATCH không sửa kết quả suy luận của AI. Sample có `logged=false` vẫn được tính trong analytics; DELETE mới loại sample khỏi analytics. Sau sửa/xóa, Frontend cần tải lại dashboard vì chưa có event thông báo xóa.

**Ý nghĩa:** tra cứu cảm xúc theo học sinh và thời gian, đồng thời quản lý log mà vẫn phân biệt rõ dữ liệu suy luận với trạng thái hiển thị.

**Code liên quan:** `app/modules/emotions/model.py`, `schema.py`, `repository.py`, `service.py`, `router.py`.

## 4. Callback AI và tổng hợp realtime

Thêm `POST /internal/emotions` cho AI gửi kết quả về Backend. Endpoint yêu cầu header `X-AI-Key` khớp `INTERNAL_AI_KEY`; key rỗng vô hiệu hóa callback. Callback kiểm tra học sinh, membership và meeting đang hoạt động ở chế độ realtime trước khi lưu.

Sau khi lưu cảm xúc, giáo viên đang online nhận event `EMOTION_AGGREGATE`, mặc định tổng hợp cửa sổ 30 giây, có breakdown theo học sinh. Event chỉ gửi đến giáo viên của đúng phòng. Event `EMOTION` gốc vẫn được giữ.

**Ý nghĩa:** giáo viên theo dõi thống kê trực tiếp trong buổi học. Callback là đường tích hợp tùy chọn; luồng Backend gọi AI HTTP vẫn được hỗ trợ. `AI_API_KEY` và `INTERNAL_AI_KEY` phục vụ hai chiều giao tiếp khác nhau.

**Code liên quan:** `app/modules/emotions/internal.py`, `analytics.py`, `analytics_schema.py`, `app/main.py`, `app/core/config.py`.

## 5. Dashboard và summary cảm xúc

`GET /meetings/{id}/dashboard` và `/summary` trả cùng cấu trúc thống kê realtime. Có thể lọc `student_id`, `start`, `end` và chọn `bucket_seconds` cho biểu đồ xu hướng. Timestamp phải có timezone; khoảng thời gian không hợp lệ trả 422.

| Trường | Giải thích |
|---|---|
| `sample_count` | Số mẫu phân loại hợp lệ, có khuôn mặt |
| `total_samples`, `failed_samples` | Tổng mẫu và số mẫu không phân loại được |
| `sample_counts`, `distribution` | Số mẫu và tỷ lệ phần trăm của 7 cảm xúc |
| `average_confidence`, `average_probabilities` | Trung bình trên mẫu hợp lệ |
| `students` | Thống kê riêng từng học sinh |
| `trend` | Thống kê theo từng khoảng thời gian |
| Các trường ratio | Tỷ lệ nhóm cảm xúc, chủ yếu trong khoảng 0–1 |

Quy ước nhóm: positive = happy; negative = sad/angry/fearful/disgusted; neutral group = neutral/surprised. `positive_negative_ratio` là tỷ số số mẫu positive/negative, trả null khi mẫu negative bằng 0. Tỷ lệ cảm xúc được tính theo số mẫu, không lấy trung bình tỷ lệ của các học sinh.

**Ý nghĩa:** cung cấp số liệu cho biểu đồ, theo dõi lớp và từng học sinh. Dashboard chỉ dùng dữ liệu realtime; report video dùng dữ liệu recording để tránh đếm hai lần.

**Code liên quan:** `app/modules/emotions/analytics.py`, `analytics_schema.py`, `app/modules/reports/router.py`.

## 6. Phân quyền và Admin

Thêm role `admin`, dependency kiểm tra quyền và hai API `GET /admin/users`, `GET /admin/meetings`, có phân trang. Response danh sách người dùng không trả `password_hash`. Người dùng không được tự đăng ký role admin.

JWT xác định danh tính, còn quyền được đọc từ database. Role tự gắn trong request hoặc token không được dùng để nâng quyền. Admin có API tổng quan riêng; không tự động có quyền xem dashboard thuộc giáo viên khác hoặc join lớp như giáo viên chủ phòng.

Thêm script tạo admin:

```powershell
.\.venv\Scripts\python.exe -m scripts.create_admin --email admin@example.com --name "Admin"
```

Script nhập mật khẩu qua prompt, từ chối email đã tồn tại và không tự nâng quyền tài khoản cũ.

**Ý nghĩa:** tách quyền quản trị khỏi quyền giáo viên/học sinh và bảo vệ dữ liệu giữa các phòng.

**Code liên quan:** `app/modules/admin/`, `app/core/dependencies.py`, `app/modules/auth/model.py`, `schema.py`, `scripts/create_admin.py`.

## 7. Recording là camera của từng học sinh — chỉnh sửa mới nhất

Quy định mới: mỗi recording là video camera của một học sinh trong meeting. Frontend phải upload riêng video của từng học sinh, không gửi video tổng thể phòng làm recording của một học sinh.

```http
POST /meetings/{meeting_id}/recordings?student_id={student_id}
Authorization: Bearer <teacher_access_token>
Content-Type: video/webm

<raw video bytes của học sinh được chọn>
```

Backend vẫn nhận raw video body, không chuyển sang multipart. `student_id` là query parameter bắt buộc, tối đa 36 ký tự.

| Trước khi siết quy định | Sau cập nhật |
|---|---|
| Phòng một học sinh có thể tự gán khi thiếu ID | Mọi upload đều phải gửi `student_id` |
| Phòng chưa có học sinh có thể lưu recording với ID null | Không tạo recording mới khi thiếu ID hoặc học sinh không thuộc phòng |
| Danh tính trong timeline AI có thể khác metadata recording | Timeline report lấy ID từ recording đã lưu |

Backend kiểm tra tài khoản có role student và có membership trong meeting, kể cả đã leave. Thiếu/chuỗi ID không hợp lệ trả 422; học sinh không thuộc phòng, không tồn tại hoặc sai role trả `422 INVALID_STUDENT`. Service có kiểm tra `STUDENT_REQUIRED` khi được gọi trực tiếp mà thiếu ID; API kiểm tra query bắt buộc trước khi vào handler.

Chỉ giáo viên chủ phòng được upload, đọc metadata và lấy playback. Response upload và `GET /recordings/{id}` có `student_id`. Liên kết đã lưu không thay đổi khi người khác join phòng.

Recording cũ chưa có liên kết vẫn có thể trả `student_id=null`; Backend không đoán danh tính từ danh sách thành viên hiện tại. Trường ID là metadata do luồng upload xác định, không phải cơ chế nhận dạng khuôn mặt hoặc xác minh nội dung video. Frontend chịu trách nhiệm gửi đúng luồng camera.

Chế độ `after_session` tiếp tục tự enqueue phân tích sau upload. Video được lưu trước khi enqueue; lỗi queue không xóa video đã lưu.

**Ý nghĩa:** xác định chính xác recording đang được gán cho học sinh nào để tạo report riêng và tổng hợp meeting.

**Code liên quan:** `app/modules/recordings/model.py`, `schema.py`, `router.py`, `service.py`; migration `alembic/versions/20261012_recording_student.py`.

## 8. Report riêng của recording — chỉnh sửa mới nhất

Thêm `GET /recordings/{recording_id}/report`. API cũ `/recordings/{recording_id}/analysis` vẫn hoạt động và trả cùng dữ liệu. Cả hai chỉ dành cho giáo viên chủ phòng, hỗ trợ `offset` và `limit` để phân trang timeline.

Report có `meeting_id`, `recording_id`, `student_id`, `sample_counts`, `sample_count`, `distribution`, `timeline`, `summary`, `source`, `time_basis`, `status` và `mock`.

`student_id` ở report và từng điểm timeline được lấy từ recording trong database, ghi đè danh tính mà AI có thể trả về. Khi chưa có phân tích, API trả report rỗng, giữ danh tính recording và trạng thái hiện tại như `uploaded` hoặc `pending`.

**Ý nghĩa:** Frontend có thể hiển thị cảm xúc của video từng học sinh và phân biệt rõ đang chờ phân tích với đã có kết quả.

**Code liên quan:** `app/modules/reports/router.py`, `schema.py`, `service.py`.

## 9. Report meeting tổng hợp từ recording — chỉnh sửa mới nhất

`GET /meetings/{meeting_id}/report` đổi mặc định từ `source=auto` sang `source=batch`. Không truyền source thì Backend tổng hợp kết quả các recording đã completed trong meeting.

Cách tính: cộng số mẫu từng cảm xúc từ các report recording, sau đó chia cho tổng số mẫu hợp lệ. Ví dụ recording A có 1 mẫu happy, recording B có 9 mẫu sad thì meeting có 10 mẫu, happy 10%, sad 90%. Không lấy trung bình hai tỷ lệ riêng thành 50%/50%.

Timeline tổng hợp có `recording_id` và `student_id` để biết điểm dữ liệu thuộc video và học sinh nào. Timestamp batch là số giây tính từ đầu từng video; không phải thời gian UTC chung của meeting. Phân trang chỉ giới hạn timeline trả về; tổng mẫu và distribution vẫn tính toàn bộ kết quả đã chọn.

| Trạng thái | Ý nghĩa |
|---|---|
| `completed` | Có kết quả batch và tất cả recording theo trạng thái đã hoàn tất |
| `partial` | Có kết quả batch nhưng còn recording chưa hoàn tất hoặc thất bại |
| `empty` | Không có kết quả batch để tổng hợp |

Response có `meeting_id` và `recording_statuses` để Frontend theo dõi số recording ở từng trạng thái. Nếu chưa có batch, report mặc định không tự dùng realtime thay thế.

`source=realtime` và `source=auto` vẫn được hỗ trợ khi Frontend yêu cầu rõ: realtime đọc mẫu trực tiếp; auto ưu tiên batch, nếu không có batch thì dùng realtime. Backend không cộng lẫn hai nguồn.

**Ý nghĩa:** cảm xúc meeting mặc định được định nghĩa bằng tổng hợp report recording, đồng thời giữ khả năng truy vấn realtime trước đây.

**Code liên quan:** `app/modules/reports/router.py`, `schema.py`, `service.py`, `repository.py`.

## 10. Database, cấu hình và tài liệu tích hợp

SQL có hai migration mới trong đợt cập nhật:

| Revision | Nội dung |
|---|---|
| `20261012_backend` | Cho phép role admin; thêm index tra cứu frame cảm xúc |
| `20261012_recording_student` | Thêm `recordings.student_id` nullable, foreign key đến users và index |

Cột recording nullable để giữ dữ liệu cũ; yêu cầu bắt buộc ID đối với upload mới được áp dụng ở API/service. MongoDB không cần migration cột SQL, index được tạo qua `ensure_indexes`.

Trước khi dùng bản mới với database SQL:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Cấu hình liên quan được ghi trong `.env.example`: `MAX_ROOM_CONNECTIONS`, `EMOTION_AGGREGATION_WINDOW_SECONDS`, `INTERNAL_AI_KEY`. Nếu cấu hình cũ còn `MAX_ROOM_CONNECTIONS=2` thì cần cập nhật.

Đã cập nhật/xuất tài liệu API, kiến trúc, OpenAPI, schema aggregate, Postman collection 43 request, environment và manifest SHA-256 của contract. Script xuất lại:

```powershell
.\.venv\Scripts\python.exe -m scripts.export_contract
```

Frontend cần chuyển từ mock/MSW sang API thật, dùng email/password và JWT thật, lấy user qua `/auth/me`, quản lý nhiều peer và gửi `student_id` khi upload recording. Đây là phần tích hợp còn phải thực hiện phía Frontend.

## 11. Kết quả kiểm thử và phạm vi đã xác nhận

Lần kiểm tra mới nhất: **68 tests passed**, gồm SQLite và MongoDB giả lập bằng `mongomock`; có 2 cảnh báo deprecation từ thư viện test client. Ruff lint và kiểm tra format các module recording/report cùng test liên quan đều pass.

Các kiểm thử mới xác nhận:

- Upload lưu đúng ID học sinh; từ chối thiếu ID và học sinh không hợp lệ, kể cả phòng rỗng/phòng một học sinh.
- Report riêng giữ đúng danh tính recording khi có hoặc chưa có phân tích.
- Danh tính AI trả về không ghi đè học sinh của recording.
- `/report` của recording và `/analysis` trả cùng dữ liệu; giáo viên khác bị từ chối.
- Report meeting nhiều học sinh có tỷ lệ 10%/90% đúng theo số mẫu.
- Phân trang không làm thay đổi tổng số mẫu hoặc distribution.
- Meeting có recording chưa phân tích trả `partial` khi đã có một phần kết quả.

Bộ test hiện có còn kiểm tra membership, WebSocket, authentication/RBAC, callback AI, log CRUD, dashboard, worker và migration dữ liệu cũ.

Chưa triển khai lên server thật, chưa chạy migration/provision trên database thật. Chưa xác nhận E2E với Frontend thật, SQL Server/MongoDB thật, AI/Cloudinary/TURN thật, tải nhiều người hoặc Postman/Newman trên server thật. Các kết quả local không thay thế những bước nghiệm thu này.

## 12. Tài liệu chi tiết

- [API Backend](docs/API.md)
- [Bàn giao Backend và mapping Frontend](docs/BACKEND-TASKS.md)
- [Recording theo học sinh và report](docs/RECORDING-STUDENT.md)
- [Kiến trúc](docs/ARCHITECTURE.md)
- [Báo cáo regression trước đợt recording/report mới nhất](docs/SECURITY-REGRESSION.md)
- [OpenAPI hiện tại](docs/openapi.json)

Báo cáo regression cũ ghi 58 tests ở thời điểm trước; kết quả mới nhất sau cập nhật recording/report là 68 tests như mục 11.
