from pymongo.errors import DuplicateKeyError

from app.core.errors import AppError
from app.core.mongo import model_from_doc
from app.core.security import hash_password
from app.modules.auth.model import User
from app.modules.auth.repository import AuthRepository


def serialize_user(user):
    """BE B UserOut plus BE A's display_name alias."""
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "display_name": user.full_name,
        "role": user.role,
        "created_at": user.created_at,
    }


class UserService:
    """Profile and admin user management merged from BE A /api/v1/users."""

    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    def require(self, user_id):
        user = self.db.get(User, user_id)
        if user is None:
            raise AppError(404, "USER_NOT_FOUND", "User not found")
        return user

    def list(self, offset, limit):
        return [
            model_from_doc(User, doc)
            for doc in self.db.collection("users")
            .find()
            .sort([("email", 1)])
            .skip(offset)
            .limit(limit)
        ]

    def update(self, user, data, actor=None):
        values = data.model_dump(exclude_unset=True)
        name = values.pop("full_name", None) or values.pop("display_name", None)
        values.pop("display_name", None)
        role = values.pop("role", None)
        if actor is not None and role and actor.id == user.id and role != "admin":
            raise AppError(400, "SELF_DEMOTION", "Admins cannot remove their own role")
        email = values.get("email")
        if email is not None:
            email = str(email).lower()
            existing = AuthRepository(self.db).by_email(email)
            if existing is not None and existing.id != user.id:
                raise AppError(409, "EMAIL_EXISTS", "Email already registered")
            user.email = email
        if values.get("password") is not None:
            user.password_hash = hash_password(values["password"], self.settings.bcrypt_rounds)
        if name is not None:
            if not name.strip():
                raise AppError(422, "VALIDATION_ERROR", "Name cannot be blank")
            user.full_name = name.strip()
        if role:
            user.role = role
        try:
            self.db.commit()
        except DuplicateKeyError as exc:
            self.db.rollback()
            raise AppError(409, "EMAIL_EXISTS", "Email already registered") from exc
        return user

    def delete(self, user_id, actor):
        if user_id == actor.id:
            raise AppError(400, "SELF_DELETE", "Admins cannot delete themselves")
        user = self.require(user_id)
        self.db.collection("refresh_sessions").delete_many({"user_id": user.id})
        self.db.collection("users").delete_one({"id": user.id})
