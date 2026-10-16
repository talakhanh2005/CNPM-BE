# ---- Stage 1: cài dependencies vào /opt/venv ----
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# requirements.lock là bản khóa phiên bản đã kiểm thử; không dùng bản "latest".
COPY requirements.lock ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install -r requirements.lock

COPY pyproject.toml README.md ./
COPY app ./app
RUN /opt/venv/bin/pip install --no-deps .

# ---- Stage 2: runtime gọn, chạy bằng user thường ----
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY scripts/entrypoint.sh /app/scripts/entrypoint.sh

RUN useradd -m -u 10001 appuser \
    && sed -i 's/\r$//' /app/scripts/entrypoint.sh \
    && chmod +x /app/scripts/entrypoint.sh \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/health', timeout=3)" || exit 1

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
