from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.schemas import ORMModel


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return str(value).lower()

    @field_validator("password")
    @classmethod
    def bcrypt_byte_limit(cls, value):
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must not exceed 72 UTF-8 bytes")
        return value


class RegisterIn(LoginIn):
    full_name: str = Field(min_length=1, max_length=150)
    role: Literal["teacher", "student"] = "student"
    teacher_registration_key: str | None = Field(default=None, max_length=256, exclude=True)

    @field_validator("full_name")
    @classmethod
    def nonempty_name(cls, value):
        if not value.strip():
            raise ValueError("Full name cannot be blank")
        return value.strip()


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=4096)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class UserOut(ORMModel):
    id: str
    email: EmailStr
    full_name: str
    role: Literal["teacher", "student"]
    created_at: datetime
