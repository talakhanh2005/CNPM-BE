import asyncio
import json
import time

from anyio import CancelScope
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError
from app.core.schemas import ok
from app.modules.emotions.service import process_frame
from app.modules.signaling.schema import AuthMessage, message_adapter
from app.modules.signaling.service import SignalingService

router = APIRouter(tags=["BE-03 Signaling"])


@router.websocket("/ws/meetings/{meeting_id}")
async def signaling(socket: WebSocket, meeting_id: str):
    """First message AUTH within five seconds. See docs/API.md for protocol."""
    state = socket.app.state
    origin = socket.headers.get("origin")
    if origin is not None and origin not in state.settings.cors_origins:
        await socket.close(code=1008)
        return
    await socket.accept()
    connection = None
    frame_tasks = set()
    explicit_leave = False
    service = SignalingService(state.session_factory, state.settings, state.manager)

    async def receive(timeout):
        message = await asyncio.wait_for(socket.receive(), timeout)
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))
        raw = message.get("text")
        if raw is None:
            raise AppError(422, "INVALID_MESSAGE", "Signaling requires a JSON text message")
        if len(raw.encode()) > state.settings.ws_max_message_bytes:
            raise AppError(413, "MESSAGE_TOO_LARGE", "WebSocket message exceeds limit")
        return json.loads(raw)

    try:
        auth = AuthMessage.model_validate(await receive(5))
        user, expiry = await run_in_threadpool(service.authenticate, meeting_id, auth.token)
        connection = await state.manager.connect(meeting_id, socket, user)
        if not state.manager.current(connection):
            return

        async def handle_frame(data):
            try:
                result = await process_frame(
                    state, meeting_id, user, data, lambda: state.manager.current(connection)
                )
                await state.manager.send(connection, ok({**result, "type": "FRAME_RESULT"}))
            except AppError as exc:
                await state.manager.send(
                    connection,
                    {
                        "success": False,
                        "data": {"code": exc.code, "frame_id": data.frame_id},
                        "message": exc.message,
                    },
                )

        def frame_finished(task):
            frame_tasks.discard(task)
            if not task.cancelled() and task.exception():
                import logging

                logging.getLogger(__name__).error(
                    "WebSocket frame processing failed", exc_info=task.exception()
                )

        await state.manager.send(
            connection,
            ok(
                {
                    "type": "JOIN",
                    "sender_id": user.id,
                    "peers": [
                        {"user_id": c.user_id, "role": c.role}
                        for c in state.manager.repo.members(meeting_id)
                        if c.user_id != user.id
                    ],
                }
            ),
        )
        await state.manager.broadcast(
            meeting_id, {"type": "JOIN", "sender_id": user.id, "role": user.role}, exclude=user.id
        )
        window_start, count = time.monotonic(), 0
        while True:
            remaining = expiry - time.time()
            if remaining <= 0:
                raise AppError(401, "TOKEN_EXPIRED", "Reconnect using a new access token")
            try:
                value = await receive(min(30, remaining))
            except TimeoutError:
                await run_in_threadpool(service.active, meeting_id, user)
                continue
            await run_in_threadpool(service.active, meeting_id, user)
            if not state.manager.current(connection):
                break
            if time.monotonic() - window_start >= 1:
                window_start, count = time.monotonic(), 0
            count += 1
            if count > 30:
                raise AppError(429, "SIGNAL_RATE_LIMIT", "At most 30 messages per second")
            try:
                message = message_adapter.validate_python(value)
                if message.type == "LEAVE":
                    explicit_leave = True
                    break
                if message.type == "FRAME":
                    if user.role != "student":
                        raise AppError(403, "FORBIDDEN", "Only students may submit frames")
                    if len(frame_tasks) >= state.settings.frame_slots:
                        raise AppError(429, "AI_BUSY", "Too many in-flight frames")
                    task = asyncio.create_task(handle_frame(message.payload))
                    frame_tasks.add(task)
                    task.add_done_callback(frame_finished)
                elif message.type == "JOIN":
                    await state.manager.send(connection, ok({"type": "JOIN", "sender_id": user.id}))
                else:
                    await service.relay(meeting_id, user, message)
            except (ValidationError, AppError) as exc:
                await state.manager.send(
                    connection,
                    {
                        "success": False,
                        "data": {"code": getattr(exc, "code", "INVALID_MESSAGE")},
                        "message": getattr(exc, "message", "Invalid signaling message"),
                    },
                )
    except (WebSocketDisconnect, RuntimeError, OSError):
        pass
    except (AppError, ValidationError, ValueError, TimeoutError) as exc:
        try:
            await socket.send_json(
                {
                    "success": False,
                    "data": {"code": getattr(exc, "code", "INVALID_MESSAGE")},
                    "message": getattr(exc, "message", "Invalid message or authentication timeout"),
                }
            )
            await socket.close(code=1008)
        except (RuntimeError, OSError):
            pass
    finally:
        if connection:
            # ASGI servers may cancel the handler during transport disconnect.
            # Complete membership cleanup and LEAVE delivery even under cancellation.
            with CancelScope(shield=True):
                for task in list(frame_tasks):
                    task.cancel()
                await asyncio.gather(*list(frame_tasks), return_exceptions=True)
                try:
                    # Transport loss/refresh is not an explicit departure from the meeting.
                    if explicit_leave and state.manager.current(connection):
                        await run_in_threadpool(service.leave, meeting_id, user)
                finally:
                    await state.manager.disconnect(meeting_id, connection)
                try:
                    await socket.close(code=1000)
                except (RuntimeError, OSError):
                    pass
