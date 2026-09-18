# Kết quả kiểm chứng — SQL Server edition 1.1.0

Ngày: 15/09/2026. Python 3.12.14, Linux; requirements.lock giữ các phiên bản đã kiểm thử và thêm điều kiện nền tảng Windows.

| Hạng mục | Kết quả |
|---|---|
| Pytest | 42 passed, 2 deprecation warnings từ TestClient/httpx/anyio |
| Nghiệp vụ 7 module | 33 test của bản trước tiếp tục pass sau thay database adapter/CAS |
| SQL Server config/dialect | 9 test mới: Windows/SQL auth, escape credential, driver validation, Unicode/JSON/time DDL, lock hint, OUTPUT INSERTED, UTC, BIT filter và tên tiếng Việt round-trip |
| SQL Server DDL | Alembic upgrade head --sql biên dịch thành docs/schema.sqlserver.sql |
| SQLite migration | Upgrade head và alembic check không có drift |
| Unicode migration | Initial migration giữ nguyên; revision tiếp theo đổi Unicode fields trên SQL Server |
| Optional live tests | Có pytest --sqlserver, mỗi test dùng schema riêng; chưa chạy live trong môi trường bàn giao |

Unit test vẫn dùng SQLite tạm để kiểm tra nghiệp vụ và concurrency; đây không phải bằng chứng chạy thành công trên SQL Server thật. Test SQL Server dialect kiểm tra SQL được biên dịch, không mô phỏng ODBC engine.

Môi trường bàn giao không có SQL Server service và không có ODBC runtime (libodbc.so.2) để nạp pyodbc; không thể kiểm tra Windows Authentication, SQL login, named-instance discovery, database permission, runtime DATETIMEOFFSET/JSON round-trip hoặc khóa đồng thời trên SQL Server thật. Chạy scripts/check_sqlserver.py, alembic upgrade head và pytest --sqlserver theo RUN-AND-TEST.md trên máy đã cài SQL Server để kiểm tra các phần này.

Cloudinary và AI dùng mock trong bộ test. Chưa upload hoặc phân tích video thật bằng credential của dự án. Chưa load-test lớp đông hoặc chạy browser media/TURN end-to-end.

Bản trước đã có Uvicorn HTTP smoke với SQLite; kết quả đó không được coi là SQL Server smoke. API vẫn cần một process do ConnectionManager ở bộ nhớ.

## Chạy lại

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check app tests scripts alembic
.\.venv\Scripts\ruff.exe format --check app tests scripts alembic
```

Sau khi cấu hình SQL Server thật:

```powershell
.\.venv\Scripts\python.exe scripts/check_sqlserver.py
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe check
.\.venv\Scripts\python.exe -m pytest --sqlserver -q
```

Test live tạo schema fe_test_<uuid> riêng, không xóa bảng hiện có của ứng dụng. Nếu process bị ngắt cưỡng bức, có thể còn schema test; xác minh đúng tên trước khi dọn thủ công. Không dùng downgrade base trên database có dữ liệu cần giữ.
