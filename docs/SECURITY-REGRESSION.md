# Backend regression — 12/10/2026

Kết quả local: **58 passed**, 2 deprecation warnings từ FastAPI/Starlette test client. Các test parametrized chạy SQLite và MongoDB giả lập (`mongomock`); migration nâng DB cũ chạy SQLite. Code được kiểm tra bằng Ruff.

| Nhóm | Case đã kiểm chứng |
|---|---|
| Meeting 1-N | 1 teacher + 3 students, đồng thời join, join idempotent, leave/rejoin, teacher khác bị từ chối, signaling OFFER đúng target |
| Socket | Reconnect thay socket cũ, cleanup không xóa socket mới, slow AI không chặn signaling, cross-room peer offline |
| Authentication | Register normalize email, duplicate, sai password, login/me, rotate refresh, reuse/logout bị từ chối |
| JWT/RBAC | Token sai/hết hạn/sai type, role claim không nâng quyền DB, student direct URL, teacher khác không xem log/dashboard |
| Admin | Admin đọc users/meetings, teacher/student 403, không token 401, không lộ password hash, không self-register admin |
| Emotion | Frame permissions, validation/rate limits, AI failure/no-face, không lưu sau end/leave, log thay đổi/90 giây |
| AI contract | HTTP adapter roundtrip với schema trong repository AI hiện tại, seven-class probabilities và frame metadata |
| Callback | X-AI-Key bắt buộc, persistence, duplicate 409, aggregate đúng room/student qua teacher socket |
| Analytics | Sample-weighted distribution, average, positive/negative/neutral đủ 7 lớp, student/time filters, empty-state và start>end |
| Log CRUD | Pagination DB + total, inclusive time filter, update visibility, delete sample, cross-owner/cross-meeting IDs |
| Regression cũ | Recording after-session, worker/lease, tài liệu và migration dữ liệu cũ |

Không có lỗi còn thất bại trong các case đã chạy. Chưa chạy pentest, dependency vulnerability scan, load test hay kiểm thử credential/dịch vụ thật; không thể kết luận toàn hệ thống không còn Critical/High chỉ dựa vào bộ test này.

Postman collection 43 request đã được tạo; chưa chạy Postman/Newman trên server thật. Cần credential sáu account theo environment. AI/storage trong pytest được inject mock/transport giả lập; không phải inference/video/media thật. Frontend vẫn bật MSW và dùng mock contract, nên E2E FE-AI-BE còn pending như [bảng bàn giao](BACKEND-TASKS.md).

Release candidate local 1.2.0 có [manifest](contract-manifest.json) để so sánh contract. Chưa deploy, chưa chạy migration/provision admin trên database thật, chưa có phê duyệt freeze schema từ FE/AI. Khi nghiệm thu thực tế cần ghi kết quả vào báo cáo này và khóa contract đã thống nhất.
