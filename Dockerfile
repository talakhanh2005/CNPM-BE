FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY app ./app

RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uv", "run", "--frozen", "--no-dev", "uvicorn", "cnpm_be.main:app", "--host", "0.0.0.0", "--port", "8000"]