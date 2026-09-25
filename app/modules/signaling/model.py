import asyncio
from dataclasses import dataclass, field

from fastapi import WebSocket


@dataclass
class Connection:
    """Ephemeral presence; media is never routed through this connection."""

    socket: WebSocket
    user_id: str
    role: str
    room: str = ""
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
