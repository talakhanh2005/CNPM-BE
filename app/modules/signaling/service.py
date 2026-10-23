from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError
from app.core.security import decode_token
from app.modules.auth.model import User
from app.modules.materials.service import MaterialService
from app.modules.meetings.service import MeetingService


class SignalingService:
    def __init__(self, session_factory, settings, manager):
        self.factory, self.settings, self.manager = session_factory, settings, manager

    def authenticate(self, room, token):
        payload = decode_token(token, "access", self.settings)
        with self.factory() as db:
            user = db.get(User, payload["sub"])
            if not user:
                raise AppError(401, "INVALID_TOKEN", "User not found")
            MeetingService(db).require(room, user, active=True)
            return user, payload["exp"]

    def active(self, room, user):
        with self.factory() as db:
            MeetingService(db).require(room, user, active=True)

    def leave(self, room, user):
        with self.factory() as db:
            MeetingService(db).leave(room, user)

    def require_presentable_document(self, room, material_id, user):
        with self.factory() as db:
            MeetingService(db, self.settings).require(room, user, owner=True, active=True)
            MaterialService(db).owned(room, material_id, user)

    def require_presentation_owner(self, room, user):
        with self.factory() as db:
            MeetingService(db, self.settings).require(room, user, owner=True, active=True)

    async def relay(self, room, user, message):
        data = message.model_dump()
        data["sender_id"] = user.id
        data["full_name"] = user.full_name
        data["role"] = user.role
        if message.type in {"OFFER", "ANSWER"} and message.payload.type != message.type.lower():
            raise AppError(422, "INVALID_SDP", "SDP type does not match message type")
        if message.type in {"OFFER", "ANSWER", "ICE_CANDIDATE"}:
            if message.target_id == user.id:
                raise AppError(422, "INVALID_TARGET", "Cannot relay signaling to yourself")
            await self.manager.relay(room, message.target_id, data)
        elif message.type in {"CAMERA_STATUS", "MIC_STATUS"}:
            await self.manager.broadcast(room, data, exclude=user.id)
        elif message.type in {"DOCUMENT_PRESENT", "DOCUMENT_PAGE", "DOCUMENT_STOP"}:
            # Presentation control is a host capability. Never accept a
            # material id from a student or trust it without checking that it
            # belongs to this meeting.
            if message.type == "DOCUMENT_STOP":
                await run_in_threadpool(self.require_presentation_owner, room, user)
            else:
                await run_in_threadpool(
                    self.require_presentable_document, room, message.payload.material_id, user
                )

            if message.type == "DOCUMENT_PRESENT":
                state = self.manager.present_document(
                    room, message.payload.material_id, message.payload.page
                )
                data["payload"] = state
            elif message.type == "DOCUMENT_PAGE":
                state = self.manager.change_document_page(
                    room, message.payload.material_id, message.payload.page
                )
                data["payload"] = state
            else:
                self.manager.stop_presentation(room)
            await self.manager.broadcast(room, data, exclude=user.id)
