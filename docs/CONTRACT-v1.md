# API & Schema Contract v1 — SIA / OpenEmotion

> **Trạng thái:** **ĐÃ CHỐT v1 (16/10/2026)** — soạn bởi Tú (BE-TU-01). Mọi thay đổi sau đây phải ghi vào Changelog (mục 11) và báo cả 4 người.
> **Người duyệt:** Tiền (BE), Khánh (AI, Team Lead), Tùng (FE) — đã chốt.
> **Phạm vi:** FE ↔ BE ↔ AI cho giai đoạn 12/10–23/10, căn cứ `README_SIA_CHOT_NHIEM_VU_12-23_10_2026.md`.
> **Nguồn sự thật kỹ thuật:** code backend nhánh `feat/merge-a-b`, `docs/openapi.json` (sinh từ code), `docs/API.md` (chi tiết toàn bộ endpoint), `docs/AI-CONTRACT.md` (BE ↔ AI).

Mọi thay đổi sau khi duyệt phải ghi vào [Changelog](#11-changelog) và báo cả 4 người.

---

## 0. Các quyết định đã chốt

| ID | Quyết định đề xuất | Lý do | Người duyệt chính |
|---|---|---|---|
| D1 | Giá trị enum trên wire **giữ dạng chữ thường hiện có** (`realtime`/`after_session`, `ongoing`…) và ánh xạ 1-1 với tên trong README (§2). Riêng `data_status` của API mới (timeline/chat) dùng chữ hoa đúng như ví dụ README. | FE và AI đã tích hợp theo giá trị hiện tại; README cho phép "giữ tương thích hoặc thống nhất mapping". Đổi tên đồng loạt tốn công của 3 repo mà không thêm chức năng. | Tiền, Tùng |
| D2 | Không tạo route trùng nghĩa: `POST /meetings/{id}/emotions/infer` là route chuẩn; `POST /meetings/{id}/frames` giữ làm **alias deprecated** (cùng handler) tới hết 23/10. | Đúng tên README, không phá FE đang chạy. | Tùng |
| D3 | AI video trả thêm `segments` + `model_version` (tuỳ chọn). Khi AI chưa trả `segments`, BE **tự dựng segment** từ `timeline` điểm theo thuật toán §6.3 và đánh dấu `segments_source="derived"`. | Không block BE/FE chờ AI-KHANH-05; khi AI trả segment thật thì BE dùng luôn, không đổi API. | Khánh |
| D4 | Thời gian trong timeline/chat tính bằng **giây từ đầu video** (float), khoảng **`[start, end)`**. Thời gian hệ thống: ISO-8601 UTC. | Theo README §6. | Cả nhóm |
| D5 | Chatbot: LLM (Gemini, `gemini-3.5-flash`) **chỉ dùng để hiểu câu hỏi** khi bộ luật không nhận ra intent; câu trả lời luôn dựng theo mẫu từ dữ liệu DB. Key ở biến môi trường `GEMINI_API_KEY` của BE; thiếu key thì chatbot vẫn chạy bằng luật. | "Không trả lời bịa", "không hardcode key", "không gửi video/frame lên LLM". | Khánh |
| D6 | Timeline/chat/report sau buổi học chỉ mở cho **Teacher chủ phòng**, meeting `after_session`, recording đã `COMPLETED`. Student và người ngoài nhận 403. | README T06, T10. | Tiền |
| D7 | Một meeting có thể có nhiều recording; timeline/chat mặc định lấy **recording hoàn thành mới nhất**, chọn khác bằng `recording_id`. | Hệ thống hiện cho upload nhiều video. | Tiền, Tùng |

---

## 1. Quy ước chung

- **Base URL:** BE chạy `http://localhost:8000`. FE gọi qua `/api` (Vite proxy bỏ tiền tố `/api`), WebSocket qua `/ws`.
- **Auth:** `Authorization: Bearer <access_token>` (JWT 15 phút) + refresh token xoay vòng (`POST /auth/refresh`). Đăng nhập bằng **email**.
- **Envelope thành công:** `{"success": true, "data": {...}, "message": "OK"}`
- **Envelope lỗi:** `{"success": false, "data": {"code": "MEETING_NOT_FOUND", "details": null, "request_id": "..."}, "message": "..."}`
- **Request ID:** client có thể gửi `X-Request-ID` (1–64 ký tự `[A-Za-z0-9._-]`); BE sinh mới nếu thiếu/sai, trả lại ở header `X-Request-ID` của mọi response, ghi vào log và chuyển tiếp sang AI. Báo lỗi luôn kèm request id.
- **Mã HTTP:** 401 chưa đăng nhập/token sai; 403 sai vai trò hoặc không thuộc meeting; 404 không tồn tại (hoặc ẩn để chống dò ID); 409 sai trạng thái/mode; 413 quá dung lượng; 415 sai định dạng; 422 dữ liệu không hợp lệ; 429 vượt tần suất; 502/503 lỗi dịch vụ ngoài/cấu hình.
- **Dữ liệu cảm xúc** là kết quả mô hình ước tính từ biểu cảm khuôn mặt, không phải chẩn đoán tâm lý. `no_face`/`unknown` không bao giờ được tính là `neutral`; tỷ lệ chỉ tính trên thời gian phân tích hợp lệ và luôn kèm `coverage`.

## 2. Enum (D1)

| Khái niệm | Tên trong README | Giá trị trên API (wire) |
|---|---|---|
| Meeting mode | `REALTIME` / `POST_SESSION` | `realtime` / `after_session` |
| Meeting status | `CREATED` / `IN_PROGRESS` / `ENDED` / `CANCELLED` | `scheduled` / `ongoing` / `ended` / xoá mềm (`DELETE`, không trả về nữa) |
| Recording status | `PENDING` / `UPLOADING` / `READY` / `FAILED` | Upload là 1 request đồng bộ nên không có `UPLOADING`; `uploaded` = READY chưa phân tích; sau đó `pending` → `processing` → `completed` / `failed` theo job phân tích |
| Analysis status | `QUEUED` / `PROCESSING` / `COMPLETED` / `FAILED` | Job: `pending` / `processing` / `completed` / `failed`. Trường `data_status` của API timeline/chat: `QUEUED` / `PROCESSING` / `COMPLETED` / `FAILED` / `NO_RECORDING` |
| Participant status | — | `joined` / `left` / `disconnected` |
| Role | Teacher / Student | `teacher` / `student` / `admin` |

**Nhãn cảm xúc (7 lớp, cố định):** `happy`, `neutral`, `sad`, `angry`, `surprised`, `fearful`, `disgusted`.
Nhãn model FER-2013 được AI ánh xạ trước khi trả: `disgust→disgusted`, `fear→fearful`, `surprise→surprised`.

| Ngữ cảnh | Nhãn đặc biệt |
|---|---|
| Realtime (từng frame) | `emotion="fail_detection"` + `failure_reason` ∈ `no_face` / `ai_error` |
| Segment video | `emotion` ∈ 7 lớp + `no_face` (không thấy mặt) + `unknown` (có mặt nhưng không đủ tin cậy) |

## 3. Ma trận endpoint & owner

Trạng thái: **Có** = chạy trong code hiện tại; **Mới (Tú)** = thêm trong đợt này; **Tiền** = thuộc BE-TIEN, ghi chú phần còn thiếu so với README.

| Method | Endpoint | Owner | Trạng thái | Ghi chú |
|---|---|---|---|---|
| POST | `/meetings` | Tiền | Có | `mode` mặc định `realtime`; README muốn **bắt buộc** — Tiền chốt |
| GET | `/meetings`, `/meetings/history` | Tiền | Có | |
| GET | `/meetings/lookup?code=` | Tú | **Mới (16/10)** | Kiểm tra mã phòng không join: 200 / 404 `MEETING_NOT_FOUND` / 409 `MEETING_NOT_ACTIVE` / 403. FE gọi trước khi mở phòng chờ (U09) |
| GET | `/meetings/{id}` | Tiền | Có | Trả `mode`, `status` |
| PUT (README: PATCH) | `/meetings/{id}` | Tiền | Có | Sửa name/description/tags. Tiền chốt PUT hay PATCH; chặn đổi mode sau khi bắt đầu (hiện mode không sửa được) |
| DELETE | `/meetings/{id}` | Tiền | Có | Xoá mềm; đóng socket của phòng (gộp BE Tiền 20/10) |
| GET | `/meetings/{id}/dashboard`, `/summary` | Tiền | **Có (20/10)** | Thống kê realtime: phân bố, độ tin cậy TB, xu hướng theo `bucket_seconds`, lọc `student_id`/`start`/`end` |
| PATCH / DELETE | `/meetings/{id}/emotion-logs/{sample_id}` | Tiền | **Có (20/10)** | PATCH chỉ đổi `logged`; DELETE xoá sample khỏi thống kê. `GET /emotion-logs` thêm `start`, `end`, `total` |
| GET | `/recordings/{id}/report` | Tiền | **Có (20/10)** | Report riêng một recording (= `/analysis`), có `student_id` lấy từ recording |
| GET | `/admin/users`, `/admin/meetings` | Tiền | **Có (20/10)** | Chỉ admin, phân trang `offset`/`limit` |
| Internal | `POST /internal/emotions` | Tiền | **Có (20/10)** | Callback AI tuỳ chọn, header `X-AI-Key` = `INTERNAL_AI_KEY` (rỗng = tắt) |
| POST | `/meetings/{id}/end` | Tiền | Có | Idempotent; WS phát `MEETING_ENDED` |
| POST | `/meetings/{id}/recordings` (upload raw), `/recording`, `/recording-file`, `/media/signed-upload` (kèm `meeting_id`) | Tiền | Có | Realtime → 409 `INVALID_MEETING_MODE` (T02, đã chặn ở BE từ 16/10) |
| POST | `/meetings/{id}/recordings/upload-signature`, `/confirm` | Tiền | Chưa có | BE-TIEN-05; hiện có `/media/signed-upload` dùng chung |
| GET | `/meetings/{id}/report`, `/meetings/{id}/analytics` | Tiền | `/report` Có | **`/report` đang trả cả dữ liệu realtime** — cần chặn theo D6; nên dùng lại `summary` của §5.4 |
| POST | `/meetings/{id}/emotions/infer` | **Tú** | **Mới (Tú)** | Alias cũ `/meetings/{id}/frames` (D2) |
| WS | `/ws/meetings/{id}` message `FRAME` | **Tú** | Có, thêm `model_version` | FE dùng REST `/emotions/infer`; WS vẫn nhận `EMOTION` cho Teacher |
| GET | `/meetings/{id}/emotion-logs` | **Tú** | Có, thêm `model_version` | Log realtime đã lọc (đổi trạng thái hoặc mỗi 90 giây) |
| GET | `/meetings/{id}/emotions/timeline` | **Tú** | **Mới (Tú)** | §5.3 |
| POST | `/meetings/{id}/chat` | **Tú** | **Mới (Tú)** | §5.5 |
| Internal | AI `POST /v1/analyze/frame` | Khánh | Có | ≙ README `/infer/image`; thêm `model_version` (§6) |
| Internal | AI `POST /v1/analyze/video` | Khánh | Có | Thêm `segments`, `model_version` (§6) |

## 4. Quy tắc mode & quyền (bắt buộc kiểm tra ở BE)

| Hành động | `realtime` | `after_session` | Ai được gọi | Owner |
|---|---|---|---|---|
| Gửi frame suy luận | Cho phép khi meeting `ongoing` và student đang `joined` | 409 `INVALID_MEETING_MODE` | Student | Tú |
| Upload/ghi hình/confirm | **409 `INVALID_MEETING_MODE`** | Cho phép | Teacher chủ phòng | Tiền |
| Timeline / Chat | 409 `INVALID_MEETING_MODE` | Chỉ khi recording `completed`, nếu không 409 `ANALYSIS_NOT_READY` | Teacher chủ phòng | Tú |
| Report / Analytics | 409 `INVALID_MEETING_MODE` | Chỉ khi `completed` | Teacher chủ phòng | Tiền |
| Xem log realtime | Cho phép | Cho phép (trống) | Teacher chủ phòng | Tú |

Student/người ngoài gọi API của Teacher → 403 (`FORBIDDEN` / `NOT_A_PARTICIPANT`).

## 5. Endpoint của Tú — chi tiết

### 5.1. `POST /meetings/{id}/emotions/infer` (realtime)

Quyền: Student đang `joined`, meeting `ongoing`, mode `realtime`. Frame chỉ nằm trong RAM; **không lưu ảnh**, chỉ lưu metadata dự đoán.

Request:
```json
{
  "frame_id": "f-0001",
  "timestamp": "2026-10-12T09:10:11.000Z",
  "frame_base64": "<JPEG/PNG base64, không có tiền tố data:>",
  "content_type": "image/jpeg"
}
```

Response 200 (`data`):
```json
{
  "type": "EMOTION",
  "sample_id": "uuid",
  "meeting_id": "m_001",
  "student_id": "student_01",
  "frame_id": "f-0001",
  "timestamp": "2026-10-12T09:10:11Z",
  "received_at": "2026-10-12T09:10:11.050Z",
  "face_detected": true,
  "face_id": "0",
  "emotion": "neutral",
  "confidence": 0.86,
  "probabilities": {"happy": 0.02, "neutral": 0.86, "sad": 0.04, "angry": 0.02, "surprised": 0.02, "fearful": 0.02, "disgusted": 0.02},
  "failure_reason": null,
  "model_version": "emotion-v1",
  "logged": true,
  "mock": false,
  "delivered_to_teacher": true
}
```

- Tần suất: tối đa 3 frame/giây/học sinh (`FRAME_INTERVAL_SECONDS`), chung giới hạn với WebSocket. Vượt → 429 `RATE_LIMITED`; AI quá tải → 429 `AI_BUSY`. FE bỏ frame, không xếp hàng.
- AI lỗi/timeout (10 giây) → vẫn 200 với `emotion="fail_detection"`, `failure_reason="ai_error"`. **Không retry** frame cũ: frame kế tiếp chính là lần thử lại.
- Không thấy mặt → `failure_reason="no_face"`, đủ 7 xác suất = 0.
- Lỗi: 403 `FORBIDDEN` (không phải student), 403 `NOT_A_PARTICIPANT`, 409 `MEETING_NOT_ACTIVE`, 409 `INVALID_MEETING_MODE`, 413 `FRAME_TOO_LARGE`, 422 `INVALID_FRAME`.
- Overlay: Student nhận kết quả của chính mình (response REST hoặc WS `FRAME_RESULT`); Teacher nhận WS `EMOTION` khi `logged=true`.

### 5.2. WebSocket `FRAME`

Giữ nguyên giao thức trong `docs/API.md` (AUTH → JOIN/OFFER/ANSWER/ICE_CANDIDATE/CAMERA_STATUS/MIC_STATUS/FRAME/LEAVE). Sự kiện `FRAME_RESULT` (cho student) và `EMOTION` (cho teacher) có cùng trường như §5.1, kèm `model_version`.

### 5.3. `GET /meetings/{id}/emotions/timeline`

Quyền và điều kiện: D6. Query (đều tuỳ chọn):

| Tham số | Kiểu | Ý nghĩa |
|---|---|---|
| `recording_id` | string | Mặc định recording hoàn thành mới nhất (D7) |
| `from_seconds`, `to_seconds` | number ≥ 0 | Lọc khoảng `[from, to)`; segment được **cắt** theo khoảng; cần `from < to` |
| `student_id` | string | Chỉ segment có `student_id` này (AI chỉ trả khi có ánh xạ rõ ràng) |

Response 200 (`data`):
```json
{
  "meeting_id": "m_001",
  "recording_id": "r_001",
  "analysis_id": "job_001",
  "model_version": "emotion-v1",
  "duration_seconds": 300.0,
  "data_status": "COMPLETED",
  "segments_source": "ai",
  "range": {"from_seconds": 0.0, "to_seconds": 300.0},
  "segments": [
    {"start_seconds": 0.0, "end_seconds": 10.0, "emotion": "neutral", "avg_confidence": 0.87, "student_id": null},
    {"start_seconds": 10.0, "end_seconds": 18.0, "emotion": "happy", "avg_confidence": 0.91, "student_id": null},
    {"start_seconds": 18.0, "end_seconds": 22.0, "emotion": "no_face", "avg_confidence": null, "student_id": null}
  ],
  "summary": {
    "total_seconds": 22.0,
    "analyzed_seconds": 18.0,
    "no_face_seconds": 4.0,
    "unknown_seconds": 0.0,
    "coverage": 0.8182,
    "emotions": {"neutral": {"seconds": 10.0, "percent": 55.56}, "happy": {"seconds": 8.0, "percent": 44.44}},
    "dominant_emotion": "neutral"
  }
}
```

Lỗi: 403 `FORBIDDEN`; 404 `MEETING_NOT_FOUND` / `RECORDING_NOT_FOUND`; 409 `INVALID_MEETING_MODE`; 409 `ANALYSIS_NOT_READY` với `details=[{"data_status": "NO_RECORDING" | "QUEUED" | "PROCESSING" | "FAILED"}]`; 422 `VALIDATION_ERROR`.

### 5.4. Thống kê dùng chung (cho Tiền tái sử dụng)

Hàm `summarize(segments, start, end)` trong `app/modules/timeline/stats.py`:
- `total_seconds` = độ dài khoảng; `analyzed_seconds` = tổng độ dài segment thuộc 7 lớp cảm xúc.
- `percent` = `seconds / analyzed_seconds × 100` (không tính `no_face`/`unknown`).
- `coverage` = `analyzed_seconds / total_seconds`.
- `dominant_emotion` = lớp có nhiều giây nhất (`null` nếu không có dữ liệu hợp lệ).

API report/analytics của Tiền gọi lại hàm này, **không** tạo route timeline thứ hai.

### 5.5. `POST /meetings/{id}/chat`

Quyền và điều kiện: D6. Request:
```json
{"question": "Từ 02:00 đến 03:00 học sinh có cảm xúc gì?", "recording_id": null}
```

Response 200 (`data`):
```json
{
  "answer": "Từ 02:00 đến 03:00 (đã phân tích 55/60 giây): neutral 40 giây (72.7%), happy 15 giây (27.3%). Không thấy khuôn mặt 5 giây.",
  "intent": "GET_EMOTION_BY_TIME",
  "parameters": {"start_seconds": 120.0, "end_seconds": 180.0, "emotion": null},
  "references": [
    {"start_seconds": 120.0, "end_seconds": 160.0, "emotion": "neutral"},
    {"start_seconds": 160.0, "end_seconds": 165.0, "emotion": "no_face"},
    {"start_seconds": 165.0, "end_seconds": 180.0, "emotion": "happy"}
  ],
  "data_status": "COMPLETED",
  "recording_id": "r_001",
  "parser": "rules"
}
```

| Intent | Câu mẫu | Xử lý |
|---|---|---|
| `GET_EMOTION_BY_TIME` | "Từ 02:00 đến 03:00 có cảm xúc gì?", "2 phút đầu thế nào?", "lúc 01:30?" | Lấy segment giao với khoảng (cắt theo khoảng), trả thời lượng và % trên thời gian hợp lệ |
| `FIND_EMOTION` | "Cảm xúc buồn xuất hiện khi nào?", "Từ 1:00 đến 3:00 có lúc nào giận không?" | Chuẩn hoá tiếng Việt → nhãn (`buồn→sad`, `giận→angry`…), trả mọi khoảng `[start,end)` của nhãn đó (có thể giới hạn trong khoảng hỏi) |
| `UNKNOWN` | Câu ngoài phạm vi | 200, `references=[]`, câu trả lời hướng dẫn cách hỏi |

- Định dạng giờ nhận được: `mm:ss`, `hh:mm:ss`, "X phút Y giây", "X giây", "phút X".
- `parser`: `rules` (bộ luật) hoặc `llm` (Gemini hiểu câu hỏi khi luật không nhận ra). Kết quả của LLM được kiểm tra schema; sai/không có key → `UNKNOWN`.
- Không gửi video, frame hay khuôn mặt cho LLM; chỉ gửi câu hỏi và danh sách nhãn.
- `references` click được để FE seek video tới `start_seconds`.
- Lỗi: như §5.3; câu hỏi rỗng hoặc > 500 ký tự → 422.

## 6. Hợp đồng BE ↔ AI (bổ sung cho `docs/AI-CONTRACT.md`)

### 6.1. Realtime `POST /v1/analyze/frame`
Giữ nguyên request/response hiện tại, **thêm trường tuỳ chọn** `"model_version": "emotion-v1"` (≤ 64 ký tự). BE chấp nhận cả khi thiếu (lưu `null`).

### 6.2. Video `POST /v1/analyze/video`
Request giữ nguyên (`recording_id`, `video_url` đã ký, `duration`, header `Idempotency-Key`, thêm `X-Request-ID`). Response giữ các trường cũ và **thêm tuỳ chọn**:
```json
{
  "sample_counts": {"neutral": 10, "happy": 8},
  "timeline": [{"timestamp": 0.0, "emotion": "neutral", "confidence": 0.9, "student_id": null, "mock": false}],
  "summary": "18 classified samples.",
  "mock": false,
  "model_version": "emotion-v1",
  "segments": [
    {"start_seconds": 0, "end_seconds": 10, "emotion": "neutral", "avg_confidence": 0.87, "student_id": null},
    {"start_seconds": 10, "end_seconds": 18, "emotion": "happy", "avg_confidence": 0.91, "student_id": null},
    {"start_seconds": 18, "end_seconds": 22, "emotion": "no_face", "avg_confidence": null, "student_id": null}
  ]
}
```
Ràng buộc `segments` (BE kiểm tra, sai → job `failed`): sắp xếp theo `start_seconds`; `0 ≤ start < end ≤ duration`; không chồng lấn; `emotion` ∈ 7 lớp + `no_face` + `unknown`; `avg_confidence` ∈ [0,1] hoặc `null` (bắt buộc `null` với `no_face`); tối đa 20.000 segment.

### 6.3. Khi AI chưa trả `segments` (D3)
BE dựng segment từ `timeline`:
1. Gom điểm cùng `timestamp`; chọn nhãn xuất hiện nhiều nhất, hoà thì lấy confidence cao hơn.
2. `step` = trung vị khoảng cách giữa các timestamp (mặc định 1 giây).
3. Mỗi điểm phủ `[t, t+step)`, nối liền tới điểm kế nếu cách ≤ 1,5·step.
4. Khoảng trống ≥ 0,5·step (gồm đầu/cuối video) → segment `no_face`.
5. Gộp segment liền kề cùng nhãn; `avg_confidence` = trung bình có trọng số theo độ dài.
6. Video không có điểm nào → một segment `no_face` phủ cả video.

Ví dụ T04: 10 điểm `neutral` tại 0..9 giây → một segment `[0,10)`.

## 7. Schema dữ liệu

| Entity README | Bảng/collection hiện có | Ghi chú |
|---|---|---|
| `meetings` | `meetings` | `title`≙`name`; có `deleted_at`; `started_at`≙`created_at` khi tạo `ongoing` (Tiền chốt có cần cột riêng) |
| `meeting_participants` | `participants` | Khoá `(meeting_id, user_id)`; role lấy từ `users` |
| `recordings` | `recordings` | `cloudinary_public_id`≙`public_id`, `duration_seconds`≙`duration` |
| `emotion_analyses` | `analysis_jobs` + `analysis_results` | Kết quả AI thô lưu trong `analysis_results.result` (JSON, có `model_version`) |
| `emotion_segments` | **`emotion_segments` (mới, Tú)** | Xem dưới |
| `realtime_emotion_logs` | `emotion_samples` | Thêm cột `model_version`; không có ảnh |

`emotion_segments`: `id`, `analysis_job_id` → `analysis_jobs.id`, `recording_id` → `recordings.id`, `meeting_id` → `meetings.id`, `start_seconds`, `end_seconds`, `emotion`, `avg_confidence` (null được), `student_id` (null được), `sample_count`, `model_version`, `source` (`ai`/`derived`), `created_at`. Index `(recording_id, start_seconds)`.
Ghi lại segment của một recording luôn **xoá rồi ghi lại toàn bộ** → chạy lặp không tạo bản trùng (T11).

## 8. Mã lỗi dùng chung (bổ sung)

| Code | HTTP | Khi nào |
|---|---|---|
| `INVALID_MEETING_MODE` | 409 | Gọi chức năng không đúng mode |
| `ANALYSIS_NOT_READY` | 409 | Recording chưa có/đang chờ/đang xử lý/thất bại; `details[0].data_status` |
| `RECORDING_NOT_FOUND` | 404 | `recording_id` không thuộc meeting |
| `RATE_LIMITED`, `AI_BUSY` | 429 | Frame quá nhanh / AI quá tải |
| `VALIDATION_ERROR` | 422 | Tham số sai |

## 9. Việc của từng người để khớp contract

- **Tú:** §5 toàn bộ; migration `emotion_segments` + `model_version`; request ID; cập nhật OpenAPI.
- **Tiền:** ✅ chặn mode cho upload/ghi hình (§4, làm bởi Tú ngày 16/10); còn lại: chặn mode cho report; quyết định PUT/PATCH, `mode` bắt buộc, `started_at`; upload-signature/confirm (BE-TIEN-05); report/analytics dùng `summarize` (§5.4).
- **Khánh:** thêm `model_version` cho frame + video; trả `segments` (§6.2) khi xong AI-KHANH-05; giữ nhãn và ràng buộc §2/§6.
- **Tùng:** ✅ FE gọi `POST /emotions/infer` (chỉ khi meeting `realtime`), overlay hiển thị `no_face`/`ai_error`/mất kết nối; ẩn nút ghi hình với `realtime`; trang Report (`SessionReport`) gọi `/emotions/timeline` + `/chat` + `/recordings/{id}/playback`, tua video theo `references`.

## 10. Test fixture

- Test dùng `tests/fakes.py::FakeAIClient`; ứng dụng chỉ gọi AI thật. Khi AI chưa trả `segments`, BE tự dựng segment (D3).
- Fixture timeline/chat dùng trong test: `tests/test_timeline_chat.py`.

## 11. Changelog

| Ngày | Phiên bản | Nội dung | Người |
|---|---|---|---|
| 12/10/2026 | v1-draft | Bản nháp đầu tiên cho M0 | Tú |
| 12/10/2026 | v1-draft | BE hiện thực §5 (infer, timeline, chat), §6 (nhận `model_version`/`segments`, tự dựng segment), §7 (`emotion_segments`, `model_version`), request ID. Phần của Tiền/Khánh/Tùng ở §9 chưa làm | Tú |
| 16/10/2026 | **v1 (chốt)** | Chốt contract v1 cho cả nhóm. Thêm: chặn mode `realtime` ở mọi đường lưu video (`/recordings`, `/recording`, `/recording-file`, `/media/signed-upload` với `meeting_id`) → 409 `INVALID_MEETING_MODE`; FE nối `/emotions/infer`, `/emotions/timeline`, `/chat`; bỏ `AI_MODE=mock`, dữ liệu nằm hoàn toàn trên MongoDB + Cloudinary | Tú |
| 16/10/2026 | v1.1 | `GET /meetings/{id}/report` trả 409 `INVALID_MEETING_MODE` cho `realtime`; `POST /meetings/{id}/recording` trả 409 `RECORDING_NOT_UPLOADED` khi chưa có video; frame base64 vượt giới hạn trả 413 `FRAME_TOO_LARGE`; AI luôn trả `model_version` (mặc định = tên file checkpoint, đặt bằng `AI_MODEL_VERSION`). Không đổi wire enum (D1) | Tú |
| 16/10/2026 | v1.2 | Thêm `GET /meetings/lookup?code=` (U09: mã sai không được vào màn hình phòng học). Frame quá lớn luôn trả 413 `FRAME_TOO_LARGE` (A41): body vượt giới hạn được đọc bỏ rồi mới trả lời, nên proxy dev không còn báo 502 | Tú |
| 20/10/2026 | v1.3 | **Gộp BE của Tiền (nhánh `page-4`) vào BE2.** Thêm: dashboard/summary realtime, PATCH/DELETE emotion log, lọc `start`/`end` + `total` cho log, `/recordings/{id}/report`, admin, callback `/internal/emotions` + WS `EMOTION_AGGREGATE` (chỉ gửi khi giáo viên đang online), `student_ids` trong meeting, chặn giáo viên thứ hai mở socket, chống frame trùng (409 `DUPLICATE_FRAME`). **Breaking:** `POST /meetings/{id}/recordings` bắt buộc `?student_id=` (học sinh có membership; thiếu → 422 `STUDENT_REQUIRED`, sai → 422 `INVALID_STUDENT`), kiểm tra **sau** chặn mode nên realtime vẫn 409; `/meetings/{id}/report` mặc định `source=batch`, `student_id` lọc theo recording của học sinh. Giữ xoá mềm thay cho xoá cứng của BE Tiền (README yêu cầu soft-delete). `/ready` không còn trả thông điệp lỗi của driver | Tú |
