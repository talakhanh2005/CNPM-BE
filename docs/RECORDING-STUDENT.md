# Recording thuộc học viên nào

Upload video raw body như trước, thêm query parameter:

`POST /meetings/{meeting_id}/recordings?student_id={student_id}`

Response upload và `GET /recordings/{recording_id}` trả thêm `student_id: string | null`.

- BE kiểm tra tài khoản có role student và có membership trong meeting, kể cả đã rời phòng.
- `student_id` bắt buộc với mọi upload; thiếu trường trả 422. Mỗi video là camera của một học sinh, không phải video tổng thể của phòng.
- Student không hợp lệ trả 422 `INVALID_STUDENT`. Chỉ giáo viên chủ phòng được upload và đọc recording.
- Liên kết được lưu trên recording và không đổi khi có học viên khác vào phòng.
- Recording cũ không có liên kết trả null; không suy đoán danh tính từ thành viên hiện tại.
- Đây là metadata do luồng upload xác định, không phải nhận dạng khuôn mặt. FE phải gửi video của đúng học viên được chọn; video toàn phòng không bảo đảm kết quả AI chỉ thuộc học viên đó.

## Report cảm xúc

- `GET /recordings/{recording_id}/report` trả report riêng của recording; `/analysis` vẫn dùng được. Report có `meeting_id`, `recording_id`, `student_id`, phân bố cảm xúc và timeline.
- `GET /meetings/{meeting_id}/report` mặc định `source=batch`: tổng hợp số mẫu của các recording đã completed. Ví dụ recording có 1 mẫu happy và recording có 9 mẫu sad cho phân bố meeting 10% happy, 90% sad.
- Timeline batch luôn lấy `student_id` từ recording đã lưu, không tin danh tính do AI trả về. Timestamp là số giây từ đầu từng recording; dùng `recording_id` để phân biệt.
- Recording chưa có kết quả trả report rỗng cùng trạng thái hiện tại. Meeting có cả recording hoàn tất và chưa hoàn tất trả `partial`.
- Có thể yêu cầu `source=realtime` hoặc `source=auto` để dùng hành vi realtime trước đây. Không cộng mẫu realtime vào report batch.

SQL: chạy `alembic upgrade head` trước khi sử dụng phiên bản này. Migration mới thêm cột nullable, foreign key và index; giữ nguyên video cũ. MongoDB không cần migration cột, index được tạo theo cơ chế ensure_indexes hiện có.
