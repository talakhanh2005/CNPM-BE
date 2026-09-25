# Kiểm chứng tính năng phòng học

Ngày: 25/09/2026, Windows, Python trong `.venv` của dự án.

- `python -m pytest -q`: **39 passed**, 2 cảnh báo deprecation từ Starlette/httpx/anyio.
- Test nghiệp vụ chạy trên SQLite và MongoDB giả lập (mongomock), không cần database thật.
- Bao gồm: join đồng thời chỉ một student thắng; slot được giữ sau leave; phân quyền frame; log đổi trạng thái/90 giây; kết quả đến muộn; AI lỗi/không thấy mặt; report loại fail_detection khỏi phân bố; REST/WS chung limiter; nhận 3 FPS; frame lớn hơn 64 KiB; socket mới thay socket cũ cả khác phòng; signaling trong khi AI chậm; end trong khi AI xử lý; video tự enqueue; worker phục hồi video thiếu job; lịch sử theo owner; PDF/PPTX và quyền tải; ICE config theo membership.
- Migration được kiểm tra từ revision cũ sang head trên SQLite có sẵn user/meeting/participant; dữ liệu được giữ nguyên.
- OpenAPI, JSON schema WebSocket và DDL SQL Server đã xuất lại từ code.

AI HTTP được kiểm tra contract qua httpx MockTransport. Cloudinary upload/download dùng adapter giả lập trong test; chưa upload thật. SQL Server DDL đã biên dịch offline, chưa chạy trên SQL Server thật. MongoDB giả lập không thay thế kiểm thử production MongoDB.

Người dùng xác nhận FE chưa có hoặc chưa kiểm tra STUN/TURN. Backend có endpoint `/meetings/{id}/ice-config`; FE cần dùng iceServers khi tạo RTCPeerConnection và kiểm chứng TURN trên hai mạng khác nhau. Chưa kiểm thử browser media/TURN end-to-end. FE cũng cần ghi và upload video cho mode after_session; backend không nhận luồng media qua signaling.

Chạy lại:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests scripts alembic
.\.venv\Scripts\python.exe -m ruff format --check app tests scripts alembic
```
