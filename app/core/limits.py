import time

from app.core.errors import AppError, error_response


class RateLimiter:
    """Event-loop-local limiter; deployments must use one API process."""

    def __init__(self):
        self.entries = {}

    def take(self, key, interval, limit=1):
        current = time.monotonic()
        start, count = self.entries.get(key, (current, 0))
        if current - start >= interval:
            start, count = current, 0
        if count >= limit:
            raise AppError(429, "RATE_LIMITED", "Sampling or request rate exceeded; retry later")
        if len(self.entries) >= 10000:
            self.entries = {k: v for k, v in self.entries.items() if current - v[0] < 60}
            if key not in self.entries and len(self.entries) >= 10000:
                raise AppError(503, "LIMITER_BUSY", "Service is busy; retry later")
        self.entries[key] = (start, count + 1)


# Oversize bodies are read and discarded up to this many bytes before answering 413.
DRAIN_LIMIT_BYTES = 32 * 1024 * 1024
FRAME_PATHS = ("/emotions/infer", "/frames")


class RequestLimitsMiddleware:
    """Bound JSON body accumulation before parsing; throttle credential endpoints."""

    def __init__(self, app, max_json_bytes):
        self.app, self.max_json_bytes, self.limiter = app, max_json_bytes, RateLimiter()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        json_body = b"json" in headers.get(b"content-type", b"").lower()
        try:
            if scope["path"] in {
                "/auth/login",
                "/auth/register",
                "/auth/refresh",
                "/v1/auth/login",
                "/v1/auth/register",
            }:
                peer = (scope.get("client") or ("unknown",))[0]
                self.limiter.take((peer, scope["path"]), 60, limit=30)
            if json_body:
                # Bound incoming memory before Pydantic/Starlette parse the payload.
                chunks, total, oversize = [], 0, False
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    total += len(message.get("body", b""))
                    if total > self.max_json_bytes:
                        # Keep reading (and dropping) the rest of the body, up to a cap, so the
                        # client, or a dev proxy in front of us, gets a clean 413 instead of a
                        # connection reset it reports as 502.
                        oversize, chunks = True, []
                    elif not oversize:
                        chunks.append(message)
                    if not message.get("more_body", False) or total > DRAIN_LIMIT_BYTES:
                        break
                if oversize:
                    if scope["path"].endswith(FRAME_PATHS):
                        raise AppError(413, "FRAME_TOO_LARGE", "Frame exceeds size limit")
                    raise AppError(413, "BODY_TOO_LARGE", "JSON request exceeds size limit")
                iterator = iter(chunks)

                async def replay():
                    return next(iterator, {"type": "http.request", "body": b"", "more_body": False})

                return await self.app(scope, replay, send)
            return await self.app(scope, receive, send)
        except AppError as exc:
            await error_response(exc.status, exc.code, exc.message)(scope, receive, send)
