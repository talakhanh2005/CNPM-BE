from pymongo.errors import DuplicateKeyError

from app.core.db import new_id, now
from app.core.mongo import model_from_doc
from app.modules.auth.model import RefreshSession, User


class AuthRepository:
    def __init__(self, db):
        self.db = db

    def by_email(self, email):
        return model_from_doc(User, self.db.collection("users").find_one({"email": email}))

    def add_user(self, **values):
        values.setdefault("id", new_id())
        values.setdefault("created_at", now())
        user = User(**values)
        try:
            self.db.add(user)
            self.db.flush()
        except DuplicateKeyError as exc:
            raise ValueError("duplicate_user") from exc
        return user

    def add_refresh(self, jti, user_id, expires_at):
        self.db.add(RefreshSession(jti=jti, user_id=user_id, expires_at=expires_at))

    def consume_refresh(self, jti, user_id):
        result = self.db.collection("refresh_sessions").update_one(
            {"jti": jti, "user_id": user_id, "revoked_at": None, "expires_at": {"$gt": now()}},
            {"$set": {"revoked_at": now()}},
        )
        return result.modified_count == 1
