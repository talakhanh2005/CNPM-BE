# Kiến trúc và dữ liệu MongoDB

Backend sử dụng FastAPI và PyMongo. API, worker và script quản trị đều đọc `MONGO_URI`; không có nhánh kết nối SQL dự phòng.

## Cấu trúc

- `app/main.py`: app factory, middleware, router, health/readiness.
- `app/worker.py`: process xử lý job phân tích.
- `app/core/config.py`: cấu hình môi trường.
- `app/core/db.py`: UUID và thời gian UTC.
- `app/core/mongo.py`: kết nối, index, chuyển document/model và theo dõi thay đổi.
- `app/modules/*/model.py`: dataclass Python, tên collection qua `__collection__`.
- `app/modules/*/repository.py`: truy vấn PyMongo và cập nhật có điều kiện.
- `app/modules/*/service.py`: nghiệp vụ, phân quyền và điều phối storage/AI.
- `scripts/check_mongo.py`, `scripts/create_admin.py`: công cụ vận hành.

Schema Pydantic xác thực request và tạo response. Model lưu trữ không phụ thuộc ORM. UUID dạng chuỗi được giữ nguyên để FE, JWT và các document tham chiếu tiếp tục dùng cùng ID. MongoDB tạo thêm trường `_id` nội bộ; API không dùng trường này làm ID nghiệp vụ.

## Collection

| Collection | Khóa duy nhất | Index tra cứu |
|---|---|---|
| users | id, email | email |
| refresh_sessions | jti | user_id |
| meetings | id, code | teacher_id |
| participants | meeting_id + user_id | membership theo phòng/người dùng |
| recordings | id, public_id | meeting_id, student_id, status |
| analysis_jobs | id, recording_id | state + lease_until |
| analysis_results | recording_id | kết quả theo bản ghi |
| emotion_samples | id | meeting_id + timestamp; student_id; frame/log/received_at |
| materials | id, public_id | meeting_id + created_at |

Index được tạo idempotent khi kết nối lần đầu. Dữ liệu trùng đã tồn tại có thể khiến tạo unique index thất bại; phải xử lý dữ liệu trùng trước khi đưa hệ thống vào sử dụng.

Thời gian lưu BSON UTC và đọc với timezone. Unicode và payload JSON được lưu trực tiếp thành chuỗi/document BSON. Meeting cũ thiếu `mode` được hiểu là `realtime`; emotion sample cũ thiếu `logged` hoặc `face_detected` có mặc định true.

Participants lưu trong collection riêng. Khi đọc meeting, backend tải participants và thông tin user để trả tên học sinh. Các thuộc tính quan hệ `participants` và `user` không được ghi lồng vào document cha.

## Ghi dữ liệu và tính nhất quán

`MongoSession` giữ giao diện add/get/flush/commit/refresh để service quản lý model Python. Tạo mới dùng insert để ID trùng không ghi đè dữ liệu cũ; merge dùng upsert cho kết quả phân tích. Model đã đọc được theo dõi snapshot, cập nhật chỉ ghi các field thay đổi.

Đây không phải transaction nhiều document. flush/commit thực hiện ghi ngay; rollback chỉ bỏ các thay đổi chưa ghi và trạng thái theo dõi trong bộ nhớ, không hoàn tác các ghi đã hoàn tất. MongoDB standalone được hỗ trợ. Nếu cần tính nguyên tử giữa nhiều collection, phải bổ sung transaction với replica set và cơ chế bù lỗi cho Cloudinary.

Refresh token được tiêu thụ bằng update có điều kiện để chỉ một request thắng. Worker claim job bằng find_one_and_update, gán lease token và tăng attempts. finish chỉ chấp nhận token đang sở hữu job; job hết lease có thể được claim lại. Worker phục hồi trường hợp recording after_session đã ghi nhưng chưa có job. Nhiều thao tác ghi trong finish vẫn có thể bị gián đoạn khi process dừng.

Xóa meeting xóa analysis_jobs/results theo recording_id và các collection con theo meeting_id. Quyền tham gia, role và trạng thái được kiểm tra tại service; MongoDB không tự cung cấp foreign key/cascade như database quan hệ.

## Luồng và triển khai

Auth dùng JWT, refresh token hash-independent JTI và quyền đọc từ users. Phòng học hỗ trợ một giáo viên, nhiều học sinh. Video/tài liệu lưu Cloudinary; MongoDB lưu metadata. AI HTTP thực hiện phân tích; test dùng adapter giả lập. Report tách kết quả video và cảm xúc realtime để tránh đếm đôi.

Signaling WebSocket, presence, limiter và khóa theo phòng nằm trong bộ nhớ API process. Chạy một API worker; process phân tích chạy riêng và dùng chung MongoDB. Không có relay media trong backend.

`/health` chỉ kiểm tra API. `/ready` ping MongoDB và trả driver mongodb; lỗi kết nối trả 503 và không trả connection string.

Việc chuyển mã nguồn không tự sao chép dữ liệu từ database cũ. Nếu còn dữ liệu SQL, cần xuất và nhập riêng, giữ nguyên UUID và quan hệ tham chiếu; sao lưu và đối chiếu số lượng trước khi chuyển môi trường.
