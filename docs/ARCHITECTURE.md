# Kiến trúc và Data Model

## Cấu trúc

```text
face-emotion-backend/
  app/
    main.py                  # App factory, DI adapters, handlers, routes
    worker.py                # Worker bền vững, chạy process riêng
    models.py                # Registry các document model
    core/
      config.py db.py document.py mongo.py dependencies.py errors.py limits.py schemas.py security.py
    integrations/
      storage.py             # VideoStorage protocol + CloudinaryStorage
      ai.py                  # AIClient protocol + HttpAIClient
      ai_schema.py           # Contract AI chung
    modules/
      auth/
      meetings/
      signaling/             # Có ConnectionManager, không có media relay
      recordings/
      analysis/
      emotions/
      reports/               # Read model trên kết quả batch/realtime
  tests/                     # HTTP, WebSocket, repository race, adapter contract
  docs/
  scripts/entrypoint.sh
  pyproject.toml requirements.lock .env.example
```

Trong mỗi module: router nhận/validate request; service kiểm tra nghiệp vụ và transaction; repository truy vấn MongoDB hoặc connection index; model là dataclass mô tả document. Schema Pydantic nằm cạnh model. Service giữa các module dùng contract của module phụ thuộc để áp dụng cùng chính sách quyền.

## Dependency đã dùng để triển khai

1. BE-01 hoàn thiện `CurrentUser`, `Teacher`, `Student`, `require_role`, User và session factory.
2. BE-02 dùng BE-01, cung cấp `MeetingService.require(..., owner, active, lock)`.
3. BE-03 và BE-04 dùng interface meeting đã hoàn thiện.
4. BE-05 dùng RecordingService, VideoStorage và AIClient contract.
5. BE-06 dùng MeetingService, ConnectionManager và AIClient. FE-04/AI-06 được thay bằng test client giả trong kiểm thử.
6. BE-07 đọc AnalysisResult/EmotionSample theo contract chung; AI-07 thực cần xác nhận `sample_counts` và semantics timeline.

## Các collection MongoDB

Mỗi thực thể là một collection; `id` là UUID do ứng dụng sinh (field `id`, không dùng `_id`). Thời gian luôn UTC (client `tz_aware`). Email chuẩn hóa chữ thường và có unique index. Index do `MongoDatabase.ensure_indexes` tạo khi khởi động; không có migration. Cột "Collection" bên dưới là tên collection; CHECK/FK cũ được thay bằng validate ở tầng service.

| Collection | Trường | Constraint / index |
|---|---|---|
| users | id, email, password_hash, full_name, role, created_at | PK id; UNIQUE email; CHECK role teacher/student |
| refresh_sessions | jti, user_id, expires_at, revoked_at | PK jti; FK user; index user_id; không lưu raw token |
| meetings | id, code, teacher_id, status, created_at, ended_at | PK id; UNIQUE code; FK teacher; CHECK status |
| participants | meeting_id, user_id, status, joined_at, left_at | PK kép meeting/user; FK meeting/user; CHECK joined/left |
| recordings | id, meeting_id, cloudinary_url, public_id, format, duration, size_bytes, status, created_at | PK id; UNIQUE public_id; FK meeting; CHECK duration>0, status |
| analysis_jobs | id, recording_id, state, attempts, lease_token, lease_until, error_message, created_at, updated_at | PK id; UNIQUE recording_id; FK recording; index state/lease_until |
| analysis_results | recording_id, result, completed_at | PK/FK recording_id; result JSON theo BatchResult |
| emotion_samples | id, meeting_id, student_id, timestamp, emotion, confidence, mock | PK id; FK meeting/user; index meeting+timestamp, student |

Participant giữ lần join/leave gần nhất, không phải nhật ký toàn bộ các lần reconnect. Số participant ở API bao gồm cả người đã rời. Lịch sử điểm cảm xúc vẫn tham chiếu user/meeting.

## Quan hệ

```mermaid
erDiagram
    USERS ||--o{ MEETINGS : owns
    USERS ||--o{ PARTICIPANTS : joins
    MEETINGS ||--o{ PARTICIPANTS : contains
    MEETINGS ||--o{ RECORDINGS : has
    RECORDINGS ||--o| ANALYSIS_JOBS : schedules
    RECORDINGS ||--o| ANALYSIS_RESULTS : produces
    MEETINGS ||--o{ EMOTION_SAMPLES : samples
    USERS ||--o{ EMOTION_SAMPLES : submits
    USERS ||--o{ REFRESH_SESSIONS : authenticates
```

## Quyền

| Hành vi | Điều kiện |
|---|---|
| Tạo meeting | Teacher |
| Đọc meeting | Owner hoặc đã có participant record |
| Join | Meeting ongoing; student hoặc teacher sở hữu |
| Start/end | Teacher sở hữu |
| Signaling | Access JWT còn hạn + participant joined + ongoing |
| Upload/read recording, analyze/status/report/playback | Teacher sở hữu meeting |
| Gửi frame | Student đã join, meeting ongoing |
| Nhận cảm xúc qua WS | Chỉ socket teacher sở hữu meeting |

`require_role` chỉ là tầng đầu; mọi resource riêng tư đều kiểm tra ownership/membership để tránh truy cập chéo phòng. Client không được truyền `sender_id` hay `student_id` cho frame; server lấy từ JWT.

## Transaction và concurrent requests

- Register dựa trên UNIQUE email và rollback khi trùng, kể cả concurrent registration.
- Refresh token được consume bằng `update_one` có điều kiện: `revoked_at IS NULL` và chưa hết hạn. Chỉ một request thắng; tạo refresh mới trong cùng transaction.
- Meeting lifecycle được đồng bộ bằng lock theo meeting trong API process (nên chạy một process); student join lại cập nhật record cũ. Adapter MongoDB không có transaction nhiều document.
- Analyze dùng conditional UPDATE trên recording để chỉ enqueue từ `uploaded/failed`. Một recording có một job. Request lặp trong pending/processing/completed trả trạng thái hiện có.
- Worker claim bằng `find_one_and_update` nguyên tử trên job (pending hoặc lease hết hạn), cấp lease_token mới và đặt recording processing trước khi gọi AI.
- Job chuyển completed bằng cập nhật có điều kiện lease_token rồi ghi kết quả. Worker hết lease không thể overwrite do token không còn khớp.
- Worker crash khi processing: job đủ điều kiện nhận lại sau lease. AI có thể nhận request nhiều lần; AI thật cần hỗ trợ `Idempotency-Key`.
- Upload Cloudinary và MongoDB không có distributed transaction. Nếu lưu DB thất bại hoặc quá duration, backend gọi delete Cloudinary. Crash giữa upload và lưu DB hoặc cleanup lỗi có thể để lại orphan asset; cần đối soát theo public_id khi vận hành.
- API sync dùng threadpool FastAPI; đường WS/frame tạo session ngắn trong worker thread. Không chia sẻ MongoSession giữa request hay giữa các job.

## Report semantics

`distribution[e] = sample_counts[e] / tổng sample_counts * 100`, làm tròn 4 số lẻ. Có thể lệch rất nhỏ khỏi 100 do làm tròn. Không trung bình cộng phần trăm giữa các recording khác số mẫu.

`source=auto`: nếu có ít nhất một batch hoàn thành thì chọn batch; nếu chưa có thì chọn realtime. Không cộng batch với realtime vì có thể là cùng sự kiện. `source=realtime` luôn trả mẫu live. Batch chưa hoàn thành được phản ánh bằng `recording_statuses`; `status=partial` khi một số recording chưa completed.

Batch timeline dùng giây tính từ đầu **từng recording**, kèm recording_id. Không suy ra một trục thời gian chung của meeting vì metadata hiện không có thời điểm bắt đầu quay. Realtime timeline dùng timestamp chụp do FE gửi và được chuẩn hóa UTC khi lưu; received_at do BE gắn. Pagination chỉ tác động timeline; distribution và sample_count vẫn tính trên toàn bộ nguồn đã chọn. `fail_detection` có trong timeline nhưng không được tính như một trong 7 lớp cảm xúc.

## Luồng phòng học một giáo viên, nhiều học viên

`Meeting.mode` là realtime/after_session, độc lập với lifecycle scheduled/ongoing/ended. Bản gộp với BE A bỏ slot một học viên: student join tự do cho tới khi phòng đủ `MAX_ROOM_CONNECTIONS` kết nối (tính cả giáo viên); `student_id` chỉ ghi học viên đầu tiên để tham khảo. WebRTC giữa các peer là mesh (mỗi cặp một kết nối) nên giới hạn này cần nhỏ; lớp đông cần SFU. Lock theo meeting trong API process đồng bộ thao tác join/end/leave với việc lưu frame.

Từ BE A: phòng có tên/mô tả/tag/participant_mode/thời lượng; xoá mềm bằng `deleted_at` (repository coi phòng đã xoá là không tồn tại); participant có thêm trạng thái `disconnected` khi FE thoát trang, mở lại phòng thì tự join lại; tài liệu dùng chung bảng `materials` với quyền chia sẻ theo học viên, thu hồi và link công khai; bảng `emotion_labels` cho API v1 tự gắn nhãn; role `admin` để quản lý user. MongoSession chỉ ghi các trường đã thay đổi để không ghi đè trạng thái do conditional update cập nhật. MongoDB adapter không cung cấp transaction nhiều document; worker có bước phục hồi recording after_session đã lưu nhưng chưa có job.

Socket index vừa theo phòng vừa theo user. Khi thay socket, index được đổi trước khi đóng socket cũ; mọi send kiểm tra connection hiện tại, cleanup cũ không xóa connection mới. Transport disconnect chỉ cập nhật presence; LEAVE chủ động mới đổi membership. API vẫn phải chạy một process.

WebSocket FRAME và REST frame dùng chung service, limiter và semaphore AI. Frame xử lý bằng task có giới hạn để không chặn signaling. Lưu tất cả kết quả; cờ logged chỉ bật khi trạng thái/lý do lỗi đổi hoặc đã qua 90 giây từ log gần nhất, theo đồng hồ BE. Kết quả đến trễ vẫn được lưu nhưng không đẩy lùi trạng thái trực tiếp. Log là dữ liệu bền vững; WS push là best effort.

Tài liệu lưu metadata trong collection/table materials; file nằm trên Cloudinary raw authenticated. Owner upload, participant đọc metadata và lấy signed download URL. Video after_session dùng worker phân tích hiện có, tự enqueue sau upload. Lịch sử teacher chỉ đọc dữ liệu và không kích hoạt lại tác vụ AI.

## Mở rộng

Với lớp đông, bổ sung SFU ở tầng media; signaling hiện chỉ chuyển metadata. Để nhiều API process cần distributed presence/pub-sub và shared limiter. Với báo cáo rất lớn, chuyển timeline JSON sang bảng point riêng để phân trang ngay ở MongoDB; hiện batch load payload kết quả để tính tổng hợp, tối đa 20.000 điểm mỗi response AI.

Tham khảo API nền tảng: [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/). Cấu hình session và connection manager trong project thể hiện các lựa chọn cụ thể của bản triển khai này.

## MongoDB adapter

API và worker dùng chung `Settings.mongo_uri`. `app/core/document.py` định nghĩa dataclass `Document`; `app/core/mongo.py` có `MongoSession` (unit of work): `get` nạp document và theo dõi thay đổi, `commit/flush` ghi lại bằng `$set` các trường đổi (upsert cho document mới). Các thao tác cần nguyên tử (claim job, consume refresh token, enqueue) dùng `update_one`/`find_one_and_update` có điều kiện. Lỗi trùng unique index (`DuplicateKeyError`) được map sang 409.

Mọi file lớn (video ghi hình, tài liệu, media) lưu trên Cloudinary; MongoDB chỉ giữ metadata (`public_id`, URL, kích thước, trạng thái). Frame realtime chỉ nằm trong RAM, không ghi đĩa hay DB.
