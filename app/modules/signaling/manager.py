import asyncio

from app.core.errors import AppError
from app.core.schemas import ok
from app.modules.signaling.model import Connection
from app.modules.signaling.repository import ConnectionRepository


class ConnectionManager:
    """One API process. Serialize sends and bound slow-client delivery time."""

    def __init__(self, max_room_connections=2):
        self.repo = ConnectionRepository()
        self.max_room_connections = min(max_room_connections, 2)
        self.users = {}

    async def connect(self, room, socket, user):
        members = [c for c in self.repo.members(room) if c.user_id != user.id]
        if len(members) >= self.max_room_connections or any(c.role == user.role for c in members):
            raise AppError(429, "ROOM_FULL", "Room connection limit reached")
        previous = self.users.get(user.id)
        connection = Connection(socket, user.id, user.role, room)
        if previous:
            self.repo.remove(previous.room, previous.user_id, previous)
        self.repo.add(room, connection)
        self.users[user.id] = connection
        if previous:
            if previous.room != room:
                await self.broadcast(previous.room, {"type": "LEAVE", "sender_id": user.id})
            try:
                await asyncio.wait_for(previous.socket.close(code=4001), 1)
            except (TimeoutError, RuntimeError, OSError):
                pass
        return connection

    def current(self, connection):
        return self.users.get(connection.user_id) is connection

    async def send(self, connection, payload):
        if not self.current(connection):
            return False
        try:
            async with asyncio.timeout(5):
                async with connection.send_lock:
                    if not self.current(connection):
                        return False
                    await connection.socket.send_json(payload)
            return True
        except (TimeoutError, RuntimeError, OSError):
            self.repo.remove(connection.room, connection.user_id, connection)
            if self.current(connection):
                del self.users[connection.user_id]
            try:
                await asyncio.wait_for(connection.socket.close(code=1013), timeout=1)
            except (TimeoutError, RuntimeError, OSError):
                pass
            return False

    async def broadcast(self, room, data, exclude=None, role=None):
        await asyncio.gather(
            *(
                self.send(c, ok(data))
                for c in self.repo.members(room)
                if c.user_id != exclude and (role is None or c.role == role)
            )
        )

    async def relay(self, room, target, data):
        connection = self.repo.get(room, target)
        if connection is None or not await self.send(connection, ok(data)):
            raise AppError(404, "PEER_OFFLINE", "Target peer is not connected to this room")

    async def disconnect(self, room, connection):
        if self.current(connection):
            del self.users[connection.user_id]
        if self.repo.remove(room, connection.user_id, connection):
            await self.broadcast(room, {"type": "LEAVE", "sender_id": connection.user_id})

    async def close_user(self, room, user_id):
        connection = self.repo.get(room, user_id)
        if connection:
            await self.disconnect(room, connection)
            try:
                await asyncio.wait_for(connection.socket.close(code=1000), 2)
            except (TimeoutError, RuntimeError, OSError):
                pass

    async def close_room(self, room):
        await self.broadcast(room, {"type": "MEETING_ENDED"})
        await asyncio.gather(*(self.close_user(room, c.user_id) for c in self.repo.members(room)))
