# REST API và WebSocket contract

Base URL ví dụ: `http://localhost:8000`. Tất cả business REST responses và server WS messages có envelope:

```json
{"success": true, "data": {}, "message": "OK"}
```

```json
{"success": false, "data": {"code": "FORBIDDEN", "details": null}, "message": "Only the owning teacher can access this resource"}
```

HTTP status giữ đúng ý nghĩa: 201 tạo mới; 202 enqueue; 401 auth; 403 quyền; 404 không tồn tại; 409 lifecycle/duplicate; 413 size/duration; 415 media type; 422 validation; 429 throttle; 502 upstream; 503 cấu hình/capacity. `details` của validation chỉ gồm loc/msg/type, không echo password/token. `/docs`, `/redoc`, `/openapi.json` là tài liệu giao thức, không bọc envelope. WebSocket upgrade/close là protocol frames, không phải JSON response.

Trong ví dụ: `M` = UUID meeting, `R` = UUID recording, `T`/`S` = UUID teacher/student. Thay các placeholder bằng ID thật. Endpoint path trong OpenAPI dùng `{meeting_id}`/`{recording_id}`, tương đương `{id}` trong yêu cầu.

## 1. BE-01 Authentication

| Method/path | Quyền | Request | Response data |
|---|---|---|---|
| POST /auth/register | Public; teacher cần invite theo config | RegisterIn | UserOut, 201 |
| POST /auth/login | Public | LoginIn | TokenOut, 200 |
| GET /auth/me | Access JWT | Không body | UserOut |
| POST /auth/refresh | Refresh JWT trong body | RefreshIn | TokenOut |
| POST /auth/logout | Refresh JWT trong body | RefreshIn | null |

Register:

```json
{"email":"teacher@example.com","password":"SecurePass123!","full_name":"Nguyễn An","role":"teacher","teacher_registration_key":"<invite-key>"}
```

Student dùng `role:"student"` và bỏ teacher_registration_key. Response:

```json
{"success":true,"data":{"id":"T","email":"teacher@example.com","full_name":"Nguyễn An","role":"teacher","created_at":"2026-09-15T14:00:00Z"},"message":"Registered"}
```

Login request và response:

```json
{"email":"teacher@example.com","password":"SecurePass123!"}
```

```json
{"success":true,"data":{"access_token":"<access-jwt>","refresh_token":"<refresh-jwt>","token_type":"bearer","expires_in":900},"message":"OK"}
```

`GET /auth/me` gửi `Authorization: Bearer <access-jwt>`, trả cùng data UserOut, message `OK`.

Refresh/logout request:

```json
{"refresh_token":"<refresh-jwt>"}
```

Refresh trả TokenOut mới. FE phải thay **cả hai** token sau refresh, chỉ chạy một request refresh tại một thời điểm. Logout trả `{"success":true,"data":null,"message":"Logged out"}`; access JWT cũ còn hiệu lực đến exp. Password từ 8 ký tự, tối đa 72 **UTF-8 bytes** do bcrypt. Email không phân biệt chữ hoa/thường.

Contract/mô hình: `auth/model.py`, `auth/schema.py`; nghiệp vụ ở `auth/service.py`, SQL ở `auth/repository.py`. Test: login/register/me bằng httpx AsyncClient; duplicate email, sai mật khẩu, JWT hết hạn/sai type, refresh reuse, concurrent refresh, invite thiếu.

Vai trò giáo viên (gộp từ BE A): email nằm trong `TEACHER_EMAIL_WHITELIST` luôn được đăng ký là teacher, kể cả khi client gửi `role:"student"`. Email khác muốn làm teacher vẫn cần `teacher_registration_key` (hoặc `ALLOW_TEACHER_REGISTRATION=true` khi demo). Role `admin` chỉ tạo qua `ADMIN_EMAIL`/`ADMIN_PASSWORD` lúc khởi động; admin đăng nhập bằng `/auth/login` như user thường.

### API v1 gộp từ BE A

| Method/path | Quyền | Ghi chú |
|---|---|---|
| POST /v1/auth/register | Public | `{email, password, display_name?}`; luôn tạo student |
| POST /v1/auth/login | Public | Form OAuth2 (`username`=email, `password`); trả **trực tiếp** `{access_token, token_type}` (không envelope) để nút Authorize của Swagger dùng được |
| GET/PUT /v1/users/me | Access JWT | Xem/sửa email, password, `display_name`/`full_name` |
| GET /v1/users, GET/PUT/DELETE /v1/users/U | Admin | Admin không tự hạ quyền/xoá mình (400); xoá user còn sở hữu phòng/dữ liệu trên SQL → 409 `USER_IN_USE` |
| POST/GET /v1/emotions, GET/DELETE /v1/emotions/E | Access JWT | Nhãn cảm xúc tự ghi của chính người dùng, multipart `label` + `media_file` tuỳ chọn |

### Media gộp từ BE A

| Method/path | Quyền | Ghi chú |
|---|---|---|
| POST /media/signed-upload | Access JWT | Tham số đã ký để trình duyệt upload thẳng lên Cloudinary vào `openemotion/uploads/{user_id}/{folder}` |
| GET /media/PUBLIC_ID | Owner/participant | Thông tin file ghi gắn với phòng qua `/recording-file` |
| DELETE /media/PUBLIC_ID | Owner | Xoá file ghi, đưa `recording_status` về `none` |

Lỗi media giữ mã của BE A: `FILE_TOO_LARGE` (413), `UNSUPPORTED_MEDIA_TYPE` (415), `UPLOAD_FAILED` (502), `MEDIA_NOT_FOUND` (404), `MEDIA_NOT_CONFIGURED` (503).

## 2. BE-02 Meeting

| Method/path | Quyền | Body | Kết quả |
|---|---|---|---|
| POST /meetings | Teacher | `{"status":"ongoing"}` hoặc `{"status":"scheduled"}` | MeetingOut, 201 |
| GET /meetings/M | Member/owner | Không | MeetingOut |
| POST /meetings/join | Authenticated | `{"code":"A12B34C56D"}` | MeetingOut |
| POST /meetings/M/join | Student/owner | Không | MeetingOut |
| POST /meetings/M/leave | Member/owner | Không | MeetingOut |
| POST /meetings/M/start | Owner | Không | MeetingOut |
| POST /meetings/M/end | Owner | Không | MeetingOut |
| GET /meetings | Teacher | Query offset, limit, mode | Lịch sử của chính giáo viên, gồm mode, name, participant_count và analysis_status |
| GET /meetings/M/ice-config | Active member | Không | iceServers, turn_configured |
| GET /meetings/history | Authenticated | Query page, size, q, status, recording_status, from_date, to_date | Teacher: phòng mình tạo; student: phòng đã tham gia. Không có `page` → mảng; có `page` → `{items, pagination}` |
| PUT /meetings/M | Owner (người khác 404) | `{"name"?, "description"?, "tags"?}` | MeetingOut |
| DELETE /meetings/M | Owner (người khác 404) | Không | `{meeting_id, deleted_at}`; xoá mềm, phòng biến mất khỏi mọi tra cứu |
| POST /meetings/M/disconnect | Member | Không | Đánh dấu `disconnected` khi thoát trang; GET /meetings/M sau đó tự join lại |
| POST /meetings/M/recording | Owner hoặc member đang joined | `{"durationSeconds"?}` | Lưu thời lượng, `recording_status=processing`; quá 5 phút không có kết quả → `failed` (`timeout_waiting_ai`) |
| POST /meetings/M/recording-file | Owner hoặc member đang joined | multipart `file` (ảnh/video/audio) | Upload Cloudinary có kiểm tra magic bytes, gắn vào phòng |

POST /meetings nhận thêm `mode="realtime"` (mặc định) hoặc `mode="after_session"`, cùng các trường phòng: `name`, `description`, `tags`, `participant_mode` (`free`/`approval`), `duration_minutes`. Tên cũ dạng camelCase (`participantMode`, `analysisMode="batch"`, `emotionRecognition`) vẫn được chấp nhận; `mode` được ưu tiên. `participant_mode=approval` hiện chỉ được lưu lại, chưa có luồng duyệt (giống bản BE A).

Một phòng có một teacher chủ phòng và nhiều student. Số kết nối tối đa của phòng (kể cả giáo viên) là `MAX_ROOM_CONNECTIONS` (mặc định 30); khi đầy, student mới bị `409 ROOM_FULL`. `student_id` giữ học viên đầu tiên tham gia, chỉ để tham khảo. MeetingOut có thêm `name`, `description`, `tags`, `participant_mode`, `duration_minutes`, `recording_status` (`none`/`uploaded`/`processing`/`completed`/`failed`), `recording_url`, `failed_reason`; mỗi participant có thêm `full_name`, `role`, `disconnected_at`.

Response mẫu sau student join:

```json
{
  "success": true,
  "data": {
    "id": "M", "code": "A12B34C56D", "teacher_id": "T", "status": "ongoing",
    "created_at": "2026-09-15T14:00:00Z", "ended_at": null,
    "participants": [
      {"user_id":"T","status":"joined","joined_at":"2026-09-15T14:00:00Z","left_at":null},
      {"user_id":"S","status":"joined","joined_at":"2026-09-15T14:01:00Z","left_at":null}
    ]
  },
  "message": "OK"
}
```

Create có message `Meeting created`; các action khác `OK`. Leave đổi participant thành `left`, set left_at; không xóa record. Join lại giữ record, cập nhật joined_at/left_at. Chỉ ongoing cho join; scheduled cần owner gọi start. End set `status=ended`, ended_at, đánh dấu toàn bộ left và đóng WS. Mất kết nối hoặc refresh giữ membership; mở WS mới bằng token còn hiệu lực. Chỉ cần REST join lại sau khi đã chủ động LEAVE.

Contract/mô hình: `meetings/model.py`, `meetings/schema.py`. Test: role student không tạo được; scheduled chưa join được; teacher khác không start; ended không join; leave/rejoin giữ đúng số record.

## 3. BE-03 WebRTC signaling

Endpoint `ws://localhost:8000/ws/meetings/M` (deployment HTTPS dùng `wss://`). FE phải REST join trước, sau đó gửi AUTH trong 5 giây; không đặt token vào query string:

```json
{"type":"AUTH","token":"<access-jwt>"}
```

Server xác thực và trả presence:

```json
{"success":true,"data":{"type":"JOIN","sender_id":"S","peers":[{"user_id":"T","role":"teacher"}]},"message":"OK"}
```

Các peer còn lại nhận `data={"type":"JOIN","sender_id":"S","role":"student"}`. Một user tối đa một socket trong API process. Socket mới thay socket cũ; socket cũ đóng code `4001`. FE không tự reconnect socket đã bị thay thế, tránh hai tab giành kết nối liên tục. Cleanup socket cũ không xóa socket mới hoặc thay đổi membership.

### Client message mẫu

| Type | JSON gửi lên | Relay |
|---|---|---|
| JOIN | `{"type":"JOIN"}` | ACK cho sender; handshake đã broadcast presence |
| LEAVE | `{"type":"LEAVE"}` | Đóng socket, cập nhật membership, broadcast LEAVE |
| OFFER | `{"type":"OFFER","target_id":"T","payload":{"type":"offer","sdp":"v=0..."}}` | Chỉ target |
| ANSWER | `{"type":"ANSWER","target_id":"S","payload":{"type":"answer","sdp":"v=0..."}}` | Chỉ target |
| ICE_CANDIDATE | `{"type":"ICE_CANDIDATE","target_id":"T","payload":{"candidate":"candidate:...","sdpMid":"0","sdpMLineIndex":0}}` | Chỉ target |
| CAMERA_STATUS | `{"type":"CAMERA_STATUS","payload":{"enabled":false}}` | Broadcast tới các peer khác |
| MIC_STATUS | `{"type":"MIC_STATUS","payload":{"enabled":true}}` | Broadcast tới các peer khác |

Server bọc envelope và gắn sender_id từ JWT:

```json
{"success":true,"data":{"type":"OFFER","target_id":"T","sender_id":"S","payload":{"type":"offer","sdp":"v=0..."}},"message":"OK"}
```

Không gửi trường sender_id từ FE: schema cấm extra fields. Target phải online trong cùng room. ICE candidate chuỗi rỗng dùng cho end-of-candidates; không gửi payload null. Backend không inspect/đổi SDP; FE chịu trách nhiệm RTCPeerConnection, perfect negotiation khi glare, pending ICE trước remoteDescription và STUN/TURN.

Disconnect/LEAVE broadcast:

```json
{"success":true,"data":{"type":"LEAVE","sender_id":"S"},"message":"OK"}
```

Owner kết thúc phòng: `data={"type":"MEETING_ENDED"}` rồi close. JWT hết hạn trong socket sẽ bị đóng; FE refresh token rồi reconnect. Origin trình duyệt phải thuộc CORS_ORIGINS. Giới hạn 30 message/giây/socket, 1 MiB/message và 2 connection/phòng. Frame có giới hạn riêng 3 FPS mặc định. Binary message bị từ chối. Client JSON không bọc envelope; server JSON luôn bọc. Uvicorn cần `--ws-max-size 1048576`.

Contract: `signaling/schema.py`, schema export `websocket-client.schema.json` (AUTH riêng trong mô tả trên). Storage của module là ConnectionRepository trong bộ nhớ, ConnectionManager tái sử dụng ở BE-06. Test cover OFFER/ANSWER/ICE, trạng thái camera/mic, disconnect, spoof sender, target ngoài phòng và duplicate connection.

### FE skeleton

```javascript
await fetch(`${api}/meetings/${meetingId}/join`, {
  method: "POST", headers: { Authorization: `Bearer ${accessToken}` }
});
const socket = new WebSocket(`${wsBase}/ws/meetings/${meetingId}`);
socket.onopen = () => socket.send(JSON.stringify({ type: "AUTH", token: accessToken }));
socket.onmessage = ({ data }) => {
  const envelope = JSON.parse(data);
  if (!envelope.success) return handleError(envelope);
  const event = envelope.data;
  // JOIN/LEAVE: update presence; OFFER/ANSWER/ICE: apply to peer connection.
  // EMOTION: update owning teacher's chart, deduplicate by sample_id.
  // MEETING_ENDED: close peer connections and stop sending frames.
  handleEvent(event);
};
```

`handleError`/`handleEvent` là callback FE tự triển khai; đây là snippet hợp đồng, không phải media client hoàn chỉnh.

## 4. BE-04 Recording

| Method/path | Quyền | Request | Kết quả |
|---|---|---|---|
| POST /meetings/M/recordings | Teacher owner; ongoing/ended | Raw video body | RecordingOut, 201 |
| GET /recordings/R | Teacher owner | Không body | RecordingOut |
| GET /recordings/R/playback | Teacher owner | Không body | Signed URL |

```bash
curl -X POST http://localhost:8000/meetings/M/recordings   -H 'Authorization: Bearer <access-jwt>'   -H 'Content-Type: video/webm'   --data-binary @recording.webm
```

Không dùng FormData/multipart. MIME: video/mp4, video/webm, video/quicktime. Giới hạn default 64 MiB, 7.200 giây. Length được kiểm tra cả header lẫn tổng byte thực nhận. Cloudinary trả duration để server kiểm tra, không tin duration do FE tự khai. Request video stream có deadline 120 giây. Upload SDK lỗi/timeout trả 502, lỗi kéo dài nhận body trả 408, chưa cấu hình credential trả 503.

```json
{"success":true,"data":{"id":"R","meeting_id":"M","cloudinary_url":"https://res.cloudinary.com/demo/video/authenticated/example.mp4","duration":120.0,"size_bytes":4000000,"status":"uploaded","created_at":"2026-09-15T14:05:00Z"},"message":"Recording uploaded"}
```

GET metadata trả cùng data, message OK. `cloudinary_url` là định danh authenticated asset, không mặc định dùng trực tiếp cho video tag. GET playback trả:

```json
{"success":true,"data":{"url":"https://api.cloudinary.com/...signed-download...","expires_in":300},"message":"OK"}
```

URL ký có quyền truy cập cho người giữ URL tới khi hết hạn. FE cần tải/phát lại theo response của provider; endpoint là signed download, chưa triển khai adaptive HLS. POST upload không idempotent: mỗi request thành công tạo recording mới; tránh tự retry mù khi mất response.

Contract: `recordings/model.py`, `recordings/schema.py`, `integrations/storage.py`. Tests cover happy path bằng FakeStorage, SDK RAM buffer contract, student/stranger denied, empty/body lớn, type sai, duration quá dài và cleanup khi timeout.

Với `mode=after_session`, upload tự enqueue và trả recording `status=pending`; giáo viên chỉ cần xem kết quả qua report. FE vẫn phải ghi video bằng MediaRecorder hoặc nhận video từ hệ thống ghi hình rồi upload endpoint trên: signaling không chứa media nên BE không thể tự quay lại buổi học. Cần chạy `python -m app.worker`. Worker tự phục hồi video đã lưu nhưng chưa có job nếu API dừng giữa hai bước. Lịch sử `GET /meetings` có `analysis_status=awaiting_recording/pending/processing/completed/failed`, `recording_statuses` và `report_url`; không yêu cầu FE phát video.

## Tài liệu buổi học

| Method/path | Quyền | Dữ liệu |
|---|---|---|
| POST /meetings/M/materials?filename=lesson.pdf | Teacher owner | Raw file body, Content-Type đúng định dạng; trả metadata 201 |
| GET /meetings/M/materials?offset=0&limit=50 | Owner/participant | Danh sách tài liệu, không trả public_id |
| GET /materials/ID/download | Owner/participant | URL tải có chữ ký, expires_in=300 |

Hỗ trợ PDF, PPT/PPTX, DOC/DOCX, XLS/XLSX, TXT UTF-8 và ảnh PNG/JPG. Giới hạn mặc định 20 MiB qua `MAX_DOCUMENT_BYTES`, tối đa `MAX_DOCUMENTS_PER_MEETING` (100) tài liệu mỗi phòng; kiểm tra extension, MIME và chữ ký/container; không nhận đường dẫn trong filename. Upload là raw body, không phải multipart. Asset Cloudinary dùng `type=authenticated`; URL ký chỉ cấp sau khi kiểm tra quyền. Tài liệu upload theo cách này mặc định **cả lớp xem được**.

### Chia sẻ tài liệu (gộp từ BE A)

Cùng bảng `materials`, thêm upload multipart và quyền chia sẻ. Tài liệu upload qua `/documents` mặc định **riêng tư** cho tới khi giáo viên chia sẻ. Học viên chỉ thấy tài liệu chưa bị thu hồi và được chia sẻ cho cả lớp hoặc cho chính mình; quy tắc này áp dụng cho cả `/materials` ở trên. Người không có quyền nhận `404 DOCUMENT_NOT_FOUND` để không dò được ID.

| Method/path | Quyền | Dữ liệu |
|---|---|---|
| POST /meetings/M/documents | Owner | multipart `file`, `tags` ("toan, slide"); trả metadata + `download_url` 5 phút |
| GET /meetings/M/documents | Owner/participant | Query page, size (≤50), q, tag, from_date, to_date, include_revoked; `{items, pagination}` |
| GET /meetings/M/documents/D | Owner/participant có quyền | Metadata + `download_url`; header `Cache-Control: no-store` |
| DELETE /meetings/M/documents/D | Owner | Xoá file Cloudinary rồi xoá bản ghi; Cloudinary lỗi → 502 và giữ bản ghi |
| PATCH /meetings/M/documents/D/share | Owner | `{"account_ids": []}` = cả lớp; danh sách ID = thêm từng học viên |
| PATCH /meetings/M/documents/D/unshare | Owner | `[]` = ẩn với tất cả; danh sách ID = bỏ từng học viên |
| POST /meetings/M/documents/D/revoke, /restore | Owner | Thu hồi/khôi phục, file vẫn giữ để audit |
| POST /meetings/M/documents/D/generate-share-link | Owner | `{"expires_in_hours": 1-168}` (mặc định 24); trả `share_path`, `share_token`, `expires_at` |
| GET /share/documents/TOKEN | Không cần đăng nhập | 404 token sai; 410 `SHARE_LINK_GONE` khi đã thu hồi/hết hạn |

Giáo viên thấy thêm `shared_with`, `shared_with_all`, `revoked`, `revoked_at`, `share_path`, `share_expires_at`. Share token được che thành `***` trong access log.

### Trình chiếu tài liệu trực tiếp

Giáo viên có thể gửi `DOCUMENT_PRESENT`, `DOCUMENT_PAGE` và `DOCUMENT_STOP` qua WebSocket của phòng. Event chỉ chứa `material_id` và số trang; mỗi client tự gọi endpoint chi tiết tài liệu để lấy signed URL theo quyền của mình. Trạng thái đang trình chiếu nằm trong response `JOIN` để client reconnect hoặc vào muộn đồng bộ ngay. Xem [LIVE-DOCUMENT-PRESENTATION.md](LIVE-DOCUMENT-PRESENTATION.md) để biết đầy đủ luồng, giới hạn định dạng và kiểm thử.

## STUN/TURN cho FE

Đặt `ICE_SERVERS` trong môi trường backend (ví dụ trong `.env.example`). Nếu `ICE_SERVERS` rỗng, backend dựng danh sách từ `STUN_URLS` (mặc định `stun:stun.l.google.com:19302`) và `TURN_URLS`/`TURN_USERNAME`/`TURN_CREDENTIAL`. Sau khi join, FE lấy `GET /meetings/M/ice-config` và tạo `new RTCPeerConnection({iceServers: response.data.iceServers})`. `turn_configured` chỉ xác nhận có URL TURN trong cấu hình, không phải đã kiểm tra được kết nối TURN. Không có cấu hình hạ tầng mặc định. Chỉ STUN có thể không đủ khi NAT khắt khe; cần TURN hợp lệ và kiểm thử thực tế hai mạng khác nhau. Có thể ép `iceTransportPolicy: "relay"` trong bài test FE để kiểm chứng TURN. Repo này không chứa FE nên việc truyền iceServers vào peer connection cần phía FE xác nhận.

## 5. BE-05 Recorded AI analysis

| Method/path | Quyền | Body | Response |
|---|---|---|---|
| POST /recordings/R/analyze | Teacher owner | Không | StatusOut, 202 |
| GET /recordings/R/status | Teacher owner | Không | StatusOut, 200 |

```json
{"success":true,"data":{"recording_id":"R","status":"pending","job_id":"J","attempts":0,"error_message":null,"updated_at":"2026-09-15T14:06:00Z"},"message":"Analysis requested"}
```

GET status trả message OK. Status lần lượt `uploaded → pending → processing → completed/failed`. Failed có error_message; POST Analyze lại để retry. Analyze lặp khi pending/processing/completed trả trạng thái hiện tại. Job persist trước response; BE không chạy AI trong request POST. FE poll mỗi 2 giây, dừng khi completed hoặc failed.

```json
{"success":true,"data":{"recording_id":"R","status":"failed","job_id":"J","attempts":1,"error_message":"AI processing failed or timed out; retry analysis","updated_at":"2026-09-15T14:08:00Z"},"message":"OK"}
```

Contract: `analysis/model.py`, `analysis/schema.py`, `integrations/ai_schema.py`; chi tiết AI ở `AI-CONTRACT.md`. Test: durable enqueue, completed, failure/retry, recovery hết lease, stale result và concurrent enqueue/claim.

## 6. BE-06 Real-time emotion

Kênh chính: WebSocket `/ws/meetings/M`, sau AUTH. Chỉ student có membership joined trong phòng ongoing, mode realtime được gửi:

```json
{"type":"FRAME","payload":{"frame_id":"frame-42","timestamp":"2026-09-25T10:00:00Z","frame_base64":"<base64-JPEG-or-PNG-without-data-prefix>","content_type":"image/jpeg"}}
```

`POST /meetings/M/frames` vẫn có để fallback; body là đối tượng `payload` ở trên. Hai kênh dùng chung rate limit: mặc định 3 FPS (cách nhau ít nhất 333.34 ms), cấu hình 2–5 FPS. Không gửi student_id, server gắn từ JWT. Ảnh <=512 KiB, tối đa 2.073.600 pixel; JSON <=1 MiB. Ảnh sai trả 422, quá size 413, vượt tần suất/capacity 429. Nếu leave/end trong khi AI xử lý thì kết quả không được ghi. AI chạy trong task riêng, không chặn OFFER/ANSWER/ICE.

Teacher chỉ nhận `EMOTION` khi trạng thái thay đổi hoặc đủ 90 giây từ log gần nhất. Ví dụ `data`:

```json
{
  "type":"EMOTION", "sample_id":"E", "meeting_id":"M", "student_id":"S",
  "frame_id":"frame-42", "timestamp":"2026-09-25T10:00:00Z",
  "received_at":"2026-09-25T10:00:00.050Z", "logged":true,
  "face_detected":true, "face_id":"face-1", "emotion":"neutral", "confidence":0.7,
  "probabilities":{"happy":0.05,"neutral":0.7,"sad":0.05,"angry":0.05,"surprised":0.05,"fearful":0.05,"disgusted":0.05},
  "failure_reason":null, "mock":false
}
```

Student nhận ACK `FRAME_RESULT` cho từng frame đã xử lý, gồm các trường trên và `delivered_to_teacher`; REST trả `type=EMOTION`. `timestamp` là thời điểm chụp do FE gửi (bắt buộc timezone), `received_at` là giờ BE nhận để tính log 90 giây. `logged=false` nghĩa là kết quả được lưu nhưng không đẩy thêm chat log. `GET /meetings/M/emotion-logs?offset=0&limit=100` trả log đã lọc, chỉ owner được đọc; report realtime vẫn dùng toàn bộ mẫu. Teacher offline không làm mất log.

Không thấy mặt: `face_detected=false`, `emotion="fail_detection"`, `face_id=null`, confidence và đủ 7 xác suất bằng 0. `failure_reason="no_face"` khi AI không tìm thấy mặt; `"ai_error"` khi AI lỗi/timeout/kết quả không hợp lệ. Các trạng thái này cũng được ghi log; không đưa vào phân bố 7 cảm xúc. FE bỏ frame khi nhận RATE_LIMITED/AI_BUSY, không xếp hàng vô hạn; giữ FPS trong khả năng của AI. Khi không có frame mới, BE không tự bịa thêm kết quả sau 90 giây.

Contract: `emotions/model.py`, `emotions/schema.py`, `AIClient.analyze_frame`, `AI-CONTRACT.md`.

## 6b. Timeline và chatbot (contract v1, owner Tú)

Đặc tả đầy đủ, ví dụ payload và quy tắc ở [CONTRACT-v1.md](CONTRACT-v1.md) §5.

| Method/path | Quyền | Ghi chú |
|---|---|---|
| POST /meetings/M/emotions/infer | Student đang joined, phòng `realtime` đang `ongoing` | Route chuẩn của suy luận realtime; `POST /meetings/M/frames` là alias deprecated. Response có thêm `model_version` |
| GET /meetings/M/emotions/timeline | Teacher owner, phòng `after_session`, recording `completed` | Query `recording_id`, `from_seconds`, `to_seconds`, `student_id`. Trả segment `[start,end)` (giây từ đầu video) và `summary` (giây/% trên thời gian phân tích hợp lệ, `coverage`, `dominant_emotion`) |
| POST /meetings/M/chat | Như timeline | `{"question": "...", "recording_id"?}` → `answer`, `intent` (`GET_EMOTION_BY_TIME`/`FIND_EMOTION`/`UNKNOWN`), `references` để seek video, `parser` (`rules`/`llm`) |

Chưa đủ điều kiện: `409 INVALID_MEETING_MODE` (phòng realtime) hoặc `409 ANALYSIS_NOT_READY` với `details[0].data_status` ∈ `NO_RECORDING`/`QUEUED`/`PROCESSING`/`FAILED`. Student/teacher khác: 403.

Mọi response có header `X-Request-ID` (FE có thể gửi sẵn); envelope lỗi có `data.request_id`.

## 7. BE-07 Analysis và report

| Method/path | Quyền | Query | Kết quả |
|---|---|---|---|
| GET /recordings/R/analysis | Teacher owner | offset>=0, limit=1..2000 | ReportOut |
| GET /meetings/M/report | Teacher owner | source=auto/batch/realtime, offset, limit, student_id | ReportOut |

`student_id` (tuỳ chọn) lọc báo cáo của một học viên trong phòng nhiều học viên. Batch AI đếm theo cả video, không theo học viên, nên khi có `student_id` thì `auto` dùng dữ liệu realtime. `GET /meetings/M/emotion-logs` cũng nhận `student_id`.

Default offset=0, limit=500, source=auto. Ví dụ một kết quả 100 mẫu:

```json
{
  "success":true,
  "data":{
    "distribution":{"happy":45.0,"neutral":40.0,"sad":15.0},
    "sample_counts":{"happy":45,"neutral":40,"sad":15},
    "sample_count":100,
    "timeline":[{"timestamp":0.0,"emotion":"happy","confidence":0.92,"student_id":null,"recording_id":"R","sample_id":null,"mock":false}],
    "timeline_total":1,"offset":0,"limit":500,
    "summary":"100 classified samples.",
    "source":"batch","time_basis":"recording_seconds","status":"completed",
    "recording_statuses":{"completed":1},"mock":false
  },
  "message":"OK"
}
```

Đối với recording analysis, `recording_statuses={}` và `status` là trạng thái recording. Đối với report meeting: `status=completed/partial` cho batch, `available` cho realtime, `empty` khi không có dữ liệu. Khi source=realtime, timestamp là ISO UTC, recording_id=null và sample_id có giá trị.

Ví dụ meeting chưa có dữ liệu:

```json
{"success":true,"data":{"distribution":{},"sample_counts":{},"sample_count":0,"timeline":[],"timeline_total":0,"offset":0,"limit":500,"summary":"No analysis data available.","source":"none","time_basis":"none","status":"empty","recording_statuses":{},"mock":false},"message":"OK"}
```

FE phân biệt chưa có kết quả bằng source/status; không coi empty là lỗi 500. Distribution tính toàn bộ dữ liệu, không chỉ page timeline. Không cộng batch và realtime; xem rationale trong ARCHITECTURE.md. Mock=true khi nguồn đã chọn có dữ liệu mock.

Contract: `reports/schema.py`, `ReportSelection` read model; repository đọc AnalysisResult/EmotionSample. Test weighted aggregation dùng 1 mẫu happy và 9 mẫu sad để xác minh 10%/90%, không sai thành 50%/50%; test pagination, empty và quyền owner.

## Health

`GET /health` trả `data={"status":"ok","env":...,"version":"2.0.0","time":...}`; `GET /` trả lời chào. `GET /ready` kiểm tra SELECT 1, trả `data={"database":"ok"}`. Readiness chưa đo worker lag hoặc trạng thái Cloudinary/AI; cần bổ sung giám sát vận hành khi deploy.

## Cơ sở dữ liệu

Dữ liệu nằm trong MongoDB (cấu hình `MONGO_URI`, xem RUN-AND-TEST.md); file và video nằm trên Cloudinary. API/WS giữ nguyên hợp đồng của bản 1.0.
