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
            if scope["path"] in {"/auth/login", "/auth/register", "/auth/refresh"}:
                peer = (scope.get("client") or ("unknown",))[0]
                self.limiter.take((peer, scope["path"]), 60, limit=30)
            if json_body:
                # Bound incoming memory before Pydantic/Starlette parse the payload.
                chunks, total = [], 0
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    total += len(message.get("body", b""))
                    if total > self.max_json_bytes:
                        raise AppError(413, "BODY_TOO_LARGE", "JSON request exceeds size limit")
                    chunks.append(message)
                    if not message.get("more_body", False):
                        break
                iterator = iter(chunks)

                async def replay():
                    return next(iterator, {"type": "http.request", "body": b"", "more_body": False})

                return await self.app(scope, replay, send)
            return await self.app(scope, receive, send)
        except AppError as exc:
            await error_response(exc.status, exc.code, exc.message)(scope, receive, send)
