# Pre-review — phần việc của Tú (BE-TU-01 … 07)

> **Ngày:** 16/10/2026 · **Người làm:** Tú · **Người review:** Tiền, Khánh, Tùng
> **Nhánh:** BE `feat/merge-a-b` · FE `feat/merge-a-b` · AI `stage-2-video-analyst` — **chưa commit**, toàn bộ thay đổi đang ở working tree.
> **Đọc nhanh:** mục 1 (làm được gì) → mục 4 (chạy thế nào) → mục 6 (thay đổi ảnh hưởng người khác) → mục 7 (cần ai làm gì).

## 1. Tóm tắt

| Task | Nội dung | Trạng thái |
|---|---|---|
| TU-01 | API contract v1 (`docs/CONTRACT-v1.md`) | Đã chốt 16/10 (ghi vào changelog). Cần 3 người xác nhận lại bằng mắt. |
| TU-02 | `POST /meetings/{id}/emotions/infer` (AI wrapper realtime) | Xong, đã nối FE |
| TU-03 | Đưa kết quả AI video thành `emotion_segments` `[start,end)` | Xong |
| TU-04 | `GET /meetings/{id}/emotions/timeline` | Xong, đã nối FE |
| TU-05 | Chatbot, 2 intent (`GET_EMOTION_BY_TIME`, `FIND_EMOTION`) | Xong, dùng Gemini làm phương án dự phòng |
| TU-06 | `POST /meetings/{id}/chat`: validate, không bịa, kiểm quyền | Xong, đã nối FE |
| TU-07 | Request ID, OpenAPI, E2E | Request ID + OpenAPI xong; E2E đã có script, **chưa chạy trên khuôn mặt thật** |

Ngoài task gốc, cũng đã làm theo yêu cầu: **chuyển toàn bộ DB sang MongoDB**, **bỏ mock AI**, **sửa T02** (realtime không được lưu video), **chuyển chatbot sang Gemini**, **nối FE** (overlay realtime + trang Report).

## 2. Đã dùng gì

| Thành phần | Dùng | Ghi chú |
|---|---|---|
| Backend | Python 3.11, FastAPI, pymongo, httpx, Pydantic | Bỏ SQLAlchemy / Alembic / pyodbc |
| Database | **MongoDB** (local hoặc Atlas), chọn bằng `MONGO_URI` | Collection + index tự tạo lúc khởi động |
| File / video | **Cloudinary** (authenticated) | Chỉ metadata nằm trong Mongo; frame realtime chỉ ở RAM |
| AI nhận diện | Dịch vụ `CNPM-NC` (FastAPI + PyTorch, EfficientNet-B0) | BE gọi `AI_BASE_URL`, xác thực `AI_API_KEY` dùng chung |
| Chatbot | Bộ luật tiếng Việt + **Gemini `gemini-3.5-flash`** (chỉ khi luật không hiểu) | Thiếu key / lỗi → tự dùng bộ luật |
| Frontend | React + Vite + axios | Không dùng MSW khi chạy thật |
| Test | pytest, mongomock, ruff, script E2E chạy trên stack thật | |

## 3. Thay đổi chi tiết

### 3.1 BE (`CNPM-BE2`) — 67 file: 53 sửa, 14 xoá, 15 mới (+941 / −2342 dòng)

| Chủ đề | Thay đổi | File chính |
|---|---|---|
| **MongoDB hoàn toàn** | Model chuyển từ ORM sang dataclass (`Document`); `MongoSession` làm unit-of-work; bỏ nhánh SQL trong mọi repository; `DuplicateKeyError` → 409; `MONGO_URI` là bắt buộc | `app/core/document.py`, `app/core/mongo.py`, `app/core/db.py`, `app/modules/*/model.py`, `*/repository.py` |
| **Xoá** | `alembic/`, `alembic.ini`, `scripts/check_sqlserver.py`, `scripts/create_database.sql`, `docs/schema.sqlserver.sql`, `tests/test_migration.py`, `test_log.md` (chứa token), `.DS_Store` | |
| **Bỏ mock** | `MockAIClient` chuyển sang `tests/fakes.py` (`FakeAIClient`); bỏ `AI_MODE`; thiếu `AI_API_KEY` thì API/worker không khởi động | `app/integrations/ai.py`, `app/core/config.py` |
| **T02** | Meeting `realtime` → 409 `INVALID_MEETING_MODE` ở `/recordings`, `/recording`, `/recording-file`, `/media/signed-upload` (kèm `meeting_id`); chặn trước khi đọc body nên không có gì lên Cloudinary | `meetings/service.py`, `recordings/{router,service}.py`, `media/router.py` |
| **Report** | `GET /meetings/{id}/report` → 409 cho `realtime` | `reports/service.py` |
| **Recording kẹt `processing`** | `/recording` → 409 `RECORDING_NOT_UPLOADED` khi chưa có video | `meetings/service.py` |
| **Frame lớn** | Frame base64 > giới hạn → 413 `FRAME_TOO_LARGE`; body quá lớn được đọc bỏ (tối đa 32 MB) rồi mới trả 413 để proxy không báo 502 | `emotions/schema.py`, `core/limits.py` |
| **U09** `GET /meetings/lookup?code=` kiểm tra mã phòng không có tác dụng phụ | `meetings/{router,service}.py` |
| **Chatbot → Gemini** | `ClaudeIntentParser` → `GeminiIntentParser` (httpx, header `x-goog-api-key`, thử lại 1 lần khi 429/500/503); bỏ phụ thuộc `anthropic` | `app/modules/chat/llm.py`, `config.py` |
| **Contract & docs** | CONTRACT-v1 chốt + changelog; OpenAPI xuất lại; viết mới `REAL-DATA.md`, `TEST-TU-04-05-06.md`; sửa README, RUN-AND-TEST, ARCHITECTURE, DEPLOY, SECRETS, API | `docs/` |
| **Script mới** | `e2e_real.py`, `check_tu_04_05_06.py`, `seed_demo_timeline.py`, `make_demo_video.py` | `scripts/` |

### 3.2 FE (`CNPM-FE`) — 9 file sửa, 1 mới

| Thay đổi | File |
|---|---|
| Realtime: gọi **REST `POST /emotions/infer`** thay vì WebSocket `FRAME`; **chỉ khi meeting `realtime`** (trước đây gửi cả ở `after_session` → bị 409); xử lý 429 (bỏ frame), 403/409 (tự dừng) | `hooks/useEmotionFrames.js`, `api/meetingApi.js` |
| Overlay camera hiện "Không thấy khuôn mặt / AI gặp lỗi / Mất kết nối AI" thay vì luôn "Đang chờ AI" | `components/CameraGrid.jsx`, `hooks/useWebRTC.js`, `pages/Meeting.jsx` |
| Nút Ghi hình chỉ hiện cho giáo viên trong meeting `after_session` | `components/MeetingControls.jsx`, `pages/Meeting.jsx` |
| **U09**: `JoinRoom` kiểm tra mã bằng `/meetings/lookup` trước khi mở phòng chờ; mã sai/phòng đã đóng hiện thông báo và nút Quay lại | `components/JoinRoom.jsx`, `api/meetingApi.js` |
| Bỏ số cứng "Tập trung TB 91%" / "Cần hỗ trợ 0 em"; thay bằng "Đã nhận diện X/Y" và "Cảm xúc nhiều nhất" tính từ dự đoán thật | `pages/Meeting.jsx` |
| **Trang Report làm lại bằng dữ liệu thật** (bỏ toàn bộ học sinh/số bịa): thẻ tóm tắt, phân bổ cảm xúc, thanh timeline bấm để tua, video (URL ký 5 phút, tự làm mới), chatbot có mốc thời gian bấm được; trạng thái chờ tự làm mới 5 giây; realtime hiện thông báo không có Report | `pages/EmotionReport.jsx`, `components/SessionReport.jsx` (mới), `api/reportApi.js` |

### 3.3 AI (`CNPM-NC`) — 3 file sửa

`api/schema.py`, `api/settings.py`, `api/app.py`: kết quả frame và video **luôn có `model_version`** (mặc định = tên file checkpoint, đổi bằng `AI_MODEL_VERSION`). Trước đó field này luôn `null`, trái contract.

## 4. Hướng dẫn chạy (chi tiết ở `docs/REAL-DATA.md`)

Cần: MongoDB đang chạy, tài khoản Cloudinary, dịch vụ AI, (tuỳ chọn) khoá Gemini.

```powershell
# 0. MongoDB (nếu chưa có):  docker compose up -d mongo
# 1. AI — trong CNPM-NC, .env có AI_API_KEY (cùng giá trị với BE) và AI_MODEL_PATH=models/openemotion_efficientnet_b0.pth
.\.venv\Scripts\python.exe -m uvicorn openemotion.api.app:create_app --factory --app-dir src --host 127.0.0.1 --port 9000
# 2. BE API — trong CNPM-BE2
.\.venv\Scripts\uvicorn.exe app.main:create_app --factory --port 8000 --workers 1 --ws-max-size 1048576
# 3. BE worker (bắt buộc, nếu không job phân tích kẹt pending)
.\.venv\Scripts\python.exe -m app.worker
# 4. FE — trong CNPM-FE, .env.local: VITE_API_URL=/api ; KHÔNG đặt VITE_USE_MOCKS
npm run dev
```

Biến môi trường BE (`.env`, không commit): `MONGO_URI`, `JWT_SECRET`, `CLOUDINARY_*`, `AI_BASE_URL`, `AI_API_KEY`, `GEMINI_API_KEY`, `CHAT_LLM_MODEL`, `TEACHER_EMAIL_WHITELIST` / `TEACHER_REGISTRATION_KEY`, `ADMIN_EMAIL` / `ADMIN_PASSWORD`. Kiểm tra sống: `GET :8000/ready` (ping Mongo), `GET :9000/health`.

**Đăng ký giáo viên:** email phải nằm trong `TEACHER_EMAIL_WHITELIST` **lúc đăng ký** (role được lưu cố định, đổi `.env` sau đó không đổi tài khoản cũ), hoặc bật `ALLOW_TEACHER_REGISTRATION=true` khi demo local. Form FE không có ô khoá mời. Restart API sau mỗi lần sửa `.env`.

## 5. Test và kết quả

| Bộ test | Lệnh | Kết quả 16/10 |
|---|---|---|
| Unit / integration (mongomock) | `pytest -q` | **67 pass** |
| Lint | `ruff check app tests` | sạch |
| E2E trên stack thật (Mongo + Cloudinary + AI thật + worker) | `python scripts/e2e_real.py` | **37/37** |
| TU-04/05/06 trên buổi học mẫu | `python scripts/check_tu_04_05_06.py` | **30/30** (28 nếu không cung cấp tài khoản học sinh) |
| Kết nối BE → AI | `python scripts/test_live_ai_connection.py` | PASS |
| FE | `npm run build` | thành công (còn 2 cảnh báo lint `set-state-in-effect`, cùng loại cảnh báo sẵn có) |

`e2e_real.py` phủ: T01 (infer + log, không lưu ảnh), T02 (4 đường lưu video bị 409), T03 (upload Cloudinary), T04/T05 (timeline phủ kín, `no_face` không bị tính `neutral`), T06 (chưa xong thì 409), T08/T09 (chat), T10 (phân quyền), T11 (idempotent), frame lớn → 413, `model_version` luôn có, `/report` realtime → 409.

Muốn tự test TU-04/05/06: xem `docs/TEST-TU-04-05-06.md` — tạo **buổi học mẫu** có timeline biết trước (`seed_demo_timeline.py`), kèm bảng câu hỏi/đáp án mong đợi cho Swagger và các bước trên FE.

> **Lưu ý trung thực:** buổi học mẫu dùng **đoạn cảm xúc gõ tay** (`model_version = demo-seed`), vì video không có mặt thì AI không thể sinh ra chúng. Code timeline/chat, phân quyền, Cloudinary, Mongo đều là thật; **kết quả nhận diện không phải thật**.

## 6. Thay đổi ảnh hưởng người khác (cần đọc)

| Thay đổi | Ai bị ảnh hưởng |
|---|---|
| `GET /meetings/{id}/report` → **409 cho `realtime`** (trước đó 200 rỗng) | Tiền (endpoint của bạn); FE đã không còn gọi `/report` |
| 4 endpoint lưu video → **409 `INVALID_MEETING_MODE`** cho `realtime`; `/media/signed-upload` nhận thêm `meeting_id` tuỳ chọn | Tiền, Tùng |
| `POST /meetings/{id}/recording` → 409 `RECORDING_NOT_UPLOADED` khi chưa có video | Tùng (FE hiện không gọi) |
| Frame quá lớn → luôn 413 `FRAME_TOO_LARGE` (kể cả body > 1 MB; không còn 422/502 qua proxy Vite) | Tùng |
| Thêm `GET /meetings/lookup?code=` (không join); `JoinRoom` gọi trước khi mở phòng chờ, mã sai hiện thông báo, không bật camera | Tùng, Tiền |
| AI luôn trả `model_version` | Khánh |
| `AI_MODE` bị xoá; `AI_API_KEY` bắt buộc | Mọi người chạy local: cập nhật `.env` |
| `ANTHROPIC_API_KEY` → `GEMINI_API_KEY`; `CHAT_LLM_MODEL` mặc định `gemini-3.5-flash` | Mọi người chạy local |
| DB: **chỉ MongoDB**; BE cũ (`CNPM-BE`, collection `accounts`/`rooms`) đã xoá, **không dùng chung database** với BE2 (`users`/`meetings`/…) | Mọi người: tài khoản cũ phải đăng ký lại |
| `scripts/test_live_ai_connection.py` nhận `TEACHER_REGISTRATION_KEY` | Ai chạy script |
| Giá trị enum giữ **chữ thường** (`realtime`/`after_session`, `ongoing`/`ended`) theo quyết định D1, không đổi thành `REALTIME`/`POST_SESSION` | Cả nhóm |

## 7. Việc cần từng người

- **Tiền:** (1) chặn mode cho `/report`, `/analytics`, kiểm tra lại các thay đổi mục 6; (2) `upload-signature` / `confirm` (BE-TIEN-05) **chưa có** — cần quyết định làm hay giữ `/recordings` + `/recording-file`; (3) `mode` còn mặc định `realtime` thay vì bắt buộc, sửa meeting còn là `PUT` không phải `PATCH`.
- **Khánh:** (1) AI chưa trả `segments` (BE đang tự dựng, `segments_source="derived"`), chưa có smoothing — AI-KHANH-05; (2) model hiện accuracy ~0.29, macro-F1 ~0.20, chưa có bảng so với baseline; (3) xem lại 3 file đã sửa ở `CNPM-NC`.
- **Tùng:** review các file FE ở mục 3.2; còn dữ liệu cứng ở `TeacherHome` / `StudentHome` (lớp mẫu, lịch học mẫu); `.env.example` của FE ghi `VITE_ENABLE_MOCKS` nhưng code đọc `VITE_USE_MOCKS`.
- **Cả nhóm:** xác nhận contract v1 (đã ghi "đã chốt"); chạy thử E2E trên **video thật có mặt**.

## 8. Chưa kiểm / rủi ro

- **Chưa chạy FE trong trình duyệt:** overlay với camera thật, bấm timeline/mốc chat để tua video chỉ mới build, chưa kiểm bằng mắt.
- **Chưa có kết quả trên khuôn mặt thật:** E2E dùng video/ảnh không mặt (ra `no_face`). T04 "10 frame neutral → 1 segment", T08/T09 với cảm xúc thật cần một video quay thật.
- **Chất lượng model thấp** (xem mục 7) → overlay và timeline thật sẽ sai nhiều cho tới khi có checkpoint mới.
- **Mongo không có transaction nhiều document**; khoá theo meeting nằm trong bộ nhớ process → API phải chạy **1 process**.
- **Xoá user** không còn trả 409 `USER_IN_USE`.
- **Proxy Vite** trả 502 (thay vì 413) khi gửi body lớn bị server từ chối sớm — chỉ ở môi trường dev, BE trả 413 đúng.
- **Dữ liệu demo / test** đang nằm trong DB và Cloudinary (buổi "[DEMO] Timeline mẫu 60 giây", các meeting `e2e-*`/`verify-*`, một số video 30–60 giây); xoá bằng `DELETE /meetings/{id}` và Cloudinary Media Library.
- **Bí mật:** khoá Gemini đã từng xuất hiện trong chat — nên tạo khoá mới. `.env` đã gitignore, không có khoá trong code hay docs.

## 9. Checklist review

- [ ] Đọc `docs/CONTRACT-v1.md` (mục 4 quy tắc mode/quyền, mục 11 changelog)
- [ ] Chạy `pytest -q` và `scripts/e2e_real.py` (cần stack đang chạy)
- [ ] Làm theo `docs/TEST-TU-04-05-06.md` (buổi mẫu + FE)
- [ ] Xem diff `app/core/mongo.py`, `app/core/document.py` (thay đổi nền tảng lớn nhất)
- [ ] Xem diff `app/modules/chat/llm.py` và `docs/SECRETS.md`
- [ ] Quay một video thật có mặt, chạy luồng `after_session` đầu-cuối
- [ ] Quyết định `upload-signature` / `confirm` (Tiền) và nhận `segments` từ AI (Khánh)
