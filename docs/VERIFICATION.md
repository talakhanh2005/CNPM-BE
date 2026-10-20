# Kiểm chứng bản chuyển MongoDB

Ngày kiểm tra: 20/10/2026.

Kết quả: 49 test đạt; Ruff check và format cho app/scripts đạt. Số test giảm so với bộ cũ vì bỏ lượt chạy SQLite và test migration SQL; các test nghiệp vụ tiếp tục chạy trên MongoDB giả lập.

- API, worker và create_admin chỉ sử dụng MongoDB.
- Model lưu trữ dùng dataclass; bỏ phụ thuộc SQLAlchemy, Alembic và pyodbc.
- Kiểm thử nghiệp vụ dùng mongomock, mock AI và storage; giữ timezone và unique index.
- Kiểm tra các luồng auth, refresh, phòng nhiều học sinh, signaling, tài liệu, video, worker, dashboard, callback, báo cáo và admin.
- Kiểm tra ID/email trùng không ghi đè, merge kết quả phân tích, rollback thay đổi chưa flush, model legacy và thuộc tính quan hệ không lưu lồng.
- Không tự chuyển dữ liệu từ SQL sang MongoDB.

Lệnh kiểm tra:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app scripts
.\.venv\Scripts\python.exe -m ruff format --check app scripts
```

Chưa xác minh kết nối MongoDB/Atlas thật, upload Cloudinary thật hoặc AI production trong lần chuyển đổi này. mongomock không mô phỏng đầy đủ concurrency, transaction và lỗi mạng.

MongoSession không cung cấp transaction nhiều document. rollback không hoàn tác ghi đã flush; xem ARCHITECTURE.md. Các báo cáo kiểm chứng cũ trong repo ghi nhận trạng thái tại thời điểm viết và có thể còn nhắc tới bản SQL trước đây.
