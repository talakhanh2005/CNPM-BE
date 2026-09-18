class ConnectionRepository:
    """Process-local room index; only access on the API event loop."""

    def __init__(self):
        self.rooms = {}

    def get(self, room, user):
        return self.rooms.get(room, {}).get(user)

    def members(self, room):
        return list(self.rooms.get(room, {}).values())

    def add(self, room, connection):
        self.rooms.setdefault(room, {})[connection.user_id] = connection

    def remove(self, room, user, connection):
        if self.get(room, user) is not connection:
            return False
        del self.rooms[room][user]
        if not self.rooms[room]:
            del self.rooms[room]
        return True
