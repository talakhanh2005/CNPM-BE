# Quản lý secret

Secret chỉ nằm trong `.env` (local, đã gitignore) hoặc trong secret store của nền tảng deploy (biến môi trường của dashboard, hoặc file `.env` quyền `600` trên VPS). Không commit, không dán vào issue/chat, không đặt giá trị mặc định trong `docker-compose.yml`. `.env.example` chỉ chứa tên biến và giá trị mẫu.

| Biến | Mô tả | Nguồn lấy | Rotate |
| --- | --- | --- | --- |
| `JWT_SECRET` | Ký và xác thực token. Tối thiểu 32 ký tự. | `python -c "import secrets; print(secrets.token_urlsafe(48))"` | Khi nghi lộ hoặc mỗi 6 tháng. Rotate làm mọi token hiện tại hết hiệu lực, người dùng phải đăng nhập lại. |
| `MONGO_URI` | Connection string MongoDB (database chính), có thể chứa user/password. | MongoDB Atlas hoặc Mongo tự host | Khi đổi người trong nhóm hoặc nghi lộ: tạo DB user mới, cập nhật env, xoá user cũ. |
| `CLOUDINARY_API_KEY` / `CLOUDINARY_API_SECRET` | Upload, xoá, ký URL cho video ghi hình và tài liệu. | Cloudinary Console → Settings → API Keys | Đi theo cặp. Khi nghi lộ: tạo key mới, deploy, rồi vô hiệu hoá key cũ. |
| `AI_API_KEY` | Khoá gọi dịch vụ AI nhận diện cảm xúc. | Người vận hành dịch vụ AI | Cùng lúc ở BE và AI service. |
| `GEMINI_API_KEY` | Khoá Gemini cho chatbot (chỉ gửi **văn bản câu hỏi**, không gửi video hay frame; gửi qua header `x-goog-api-key`, không nằm trong URL). Để trống thì chatbot chạy bằng luật. | Google AI Studio → API keys | Khi nghi lộ: tạo khoá mới, xoá khoá cũ. |
| `ADMIN_PASSWORD` | Mật khẩu tài khoản admin được tạo lúc khởi động (đi cùng `ADMIN_EMAIL`). Chỉ dùng khi tài khoản chưa tồn tại. | Tự đặt, lưu trong trình quản lý mật khẩu | Sau lần khởi động đầu, đổi qua API người dùng; đổi giá trị env không cập nhật tài khoản đã có. |
| `TEACHER_REGISTRATION_KEY` | Khoá cho phép đăng ký tài khoản giáo viên. | Tự sinh | Khi nghi lộ hoặc đổi người quản lý. |
| `TURN_CREDENTIAL` | Mật khẩu TURN server trả cho FE qua `GET /meetings/{id}/ice-config`. | Nhà cung cấp TURN hoặc coturn tự host | Theo chính sách nhà cung cấp; khi nghi lộ. |

## Khi secret bị lộ

1. Rotate ngay theo cột "Rotate".
2. Cập nhật env trên mọi môi trường và redeploy.
3. Nếu đã commit lên git: rotate là bắt buộc. Xoá khỏi lịch sử git không đủ vì bản clone/fork cũ vẫn còn.

## Phòng ngừa

- `.env` và `.env.*` nằm trong `.gitignore` và `.dockerignore` (trừ `.env.example`), nên không vào git và không bị đóng gói vào image.
- Không đưa API key hay URL có token vào source; token chia sẻ tài liệu đã được che trong log truy cập.
- Nên bật `detect-secrets` hoặc `gitleaks` trong pre-commit/CI; repo hiện chưa cấu hình.
