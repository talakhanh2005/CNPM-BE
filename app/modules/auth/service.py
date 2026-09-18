from datetime import timedelta
from hmac import compare_digest

from app.core.db import new_id, now
from app.core.errors import AppError
from app.core.security import decode_token, hash_password, issue_token, verify_password
from app.modules.auth.repository import AuthRepository


class AuthService:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings
        self.repo = AuthRepository(db)

    def register(self, data):
        if data.role == "teacher" and not self.settings.allow_teacher_registration:
            expected = self.settings.teacher_registration_key
            if not expected or not compare_digest(data.teacher_registration_key or "", expected):
                raise AppError(
                    403,
                    "TEACHER_INVITE_REQUIRED",
                    "Teacher registration requires an invitation key",
                )
        if self.repo.by_email(data.email):
            raise AppError(409, "EMAIL_EXISTS", "Email already registered")
        try:
            user = self.repo.add_user(
                email=data.email,
                full_name=data.full_name,
                role=data.role,
                password_hash=hash_password(data.password, self.settings.bcrypt_rounds),
            )
            self.db.commit()
            return user
        except ValueError as exc:
            self.db.rollback()
            raise AppError(409, "EMAIL_EXISTS", "Email already registered") from exc

    def tokens(self, user_id):
        jti = new_id()
        self.repo.add_refresh(jti, user_id, now() + timedelta(days=self.settings.refresh_days))
        return {
            "access_token": issue_token(user_id, "access", self.settings),
            "refresh_token": issue_token(user_id, "refresh", self.settings, jti),
            "token_type": "bearer",
            "expires_in": self.settings.access_minutes * 60,
        }

    def login(self, data):
        user = self.repo.by_email(data.email)
        if not user:
            # Match the bcrypt cost on unknown emails to reduce timing leakage.
            hash_password(data.password, self.settings.bcrypt_rounds)
            raise AppError(401, "INVALID_CREDENTIALS", "Invalid email or password")
        if not verify_password(data.password, user.password_hash):
            raise AppError(401, "INVALID_CREDENTIALS", "Invalid email or password")
        result = self.tokens(user.id)
        self.db.commit()
        return result

    def refresh(self, token):
        payload = decode_token(token, "refresh", self.settings)
        if not self.repo.consume_refresh(payload["jti"], payload["sub"]):
            raise AppError(401, "REFRESH_REUSED", "Refresh token revoked or already used")
        result = self.tokens(payload["sub"])
        self.db.commit()
        return result

    def logout(self, token):
        payload = decode_token(token, "refresh", self.settings)
        self.repo.consume_refresh(payload["jti"], payload["sub"])
        self.db.commit()
