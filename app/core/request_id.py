"""Request ID for tracing one call across FE, BE logs and the AI service (contract v1 §1)."""

import re
from contextvars import ContextVar
from uuid import uuid4

HEADER = "x-request-id"
VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def current_request_id():
    """The active request id; outside a request (worker) a fresh id is returned."""
    return _request_id.get() or uuid4().hex


def bind_request_id(value=None):
    """Set the id for the current context; invalid or missing values get a new one."""
    request_id = value if value and VALID_ID.match(value) else uuid4().hex
    return request_id, _request_id.set(request_id)


def reset_request_id(token):
    _request_id.reset(token)


class RequestIdMiddleware:
    """Accept or create X-Request-ID, expose it to handlers and echo it on the response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        incoming = dict(scope.get("headers", [])).get(HEADER.encode(), b"").decode("latin-1")
        request_id, token = bind_request_id(incoming)

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                headers = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() != HEADER.encode()
                ]
                headers.append((HEADER.encode(), request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            reset_request_id(token)
