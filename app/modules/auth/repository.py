from pymongo.errors import DuplicateKeyError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.core.db import new_id, now
from app.core.mongo import model_from_doc
from app.modules.auth.model import RefreshSession, User


class AuthRepository:
    def __init__(self, db):
        self.db = db

    def by_email(self, email):
        if getattr(self.db, "is_mongo", False):
            return model_from_doc(User, self.db.collection("users").find_one({"email": email}))
        return self.db.scalar(select(User).where(User.email == email))

    def add_user(self, **values):
        values.setdefault("id", new_id())
        values.setdefault("created_at", now())
        user = User(**values)
        try:
            self.db.add(user)
            self.db.flush()
        except (IntegrityError, DuplicateKeyError) as exc:
            raise ValueError("duplicate_user") from exc
        return user

    def add_refresh(self, jti, user_id, expires_at):
        self.db.add(RefreshSession(jti=jti, user_id=user_id, expires_at=expires_at))

    def consume_refresh(self, jti, user_id):
        if getattr(self.db, "is_mongo", False):
            result = self.db.collection("refresh_sessions").update_one(
                {"jti": jti, "user_id": user_id, "revoked_at": None, "expires_at": {"$gt": now()}},
                {"$set": {"revoked_at": now()}},
            )
            return result.modified_count == 1
        result = self.db.execute(
            update(RefreshSession)
            .where(
                RefreshSession.jti == jti,
                RefreshSession.user_id == user_id,
                RefreshSession.revoked_at.is_(None),
                RefreshSession.expires_at > now(),
            )
            .values(revoked_at=now())
            .returning(RefreshSession.jti)
            .execution_options(synchronize_session=False)
        )
        return result.scalar_one_or_none() is not None
