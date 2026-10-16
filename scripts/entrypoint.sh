#!/bin/sh
# Chờ MongoDB nhận kết nối TCP rồi chạy uvicorn. Index Mongo do app tự tạo lúc khởi động.
set -eu

python - <<'PY'
import os
import socket
import sys
import time
from urllib.parse import urlsplit

uri = os.environ.get("MONGO_URI", "")
if not uri:
    # Không có Mongo thì bỏ qua bước chờ.
    sys.exit(0)
parts = urlsplit(uri)
if parts.scheme == "mongodb+srv":
    # Host SRV (Atlas) không mở được bằng socket thường; để driver tự xử lý.
    sys.exit(0)

# Lấy host đầu tiên trong URI (bỏ user:pass@ và danh sách replica set).
host_port = parts.netloc.rsplit("@", 1)[-1].split(",")[0]
host, _, port = host_port.partition(":")
port = int(port or 27017)
timeout = int(os.environ.get("MONGO_WAIT_SECONDS", "60"))

deadline = time.monotonic() + timeout
while True:
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"MongoDB ready at {host}:{port}", flush=True)
            break
    except OSError:
        if time.monotonic() >= deadline:
            print(f"MongoDB not reachable at {host}:{port} after {timeout}s", file=sys.stderr)
            sys.exit(1)
        time.sleep(1)
PY

# exec để uvicorn thay thế shell, nhận trực tiếp SIGTERM khi container dừng.
exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}" \
    --workers 1 --ws-max-size "${WS_MAX_MESSAGE_BYTES:-1048576}" --proxy-headers
