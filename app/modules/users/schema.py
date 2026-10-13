from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


def _bcrypt_limit(value):
    if value is not None and len(value.encode("utf-8")) > 72:
        raise ValueError("Password must not exceed 72 UTF-8 bytes")
    return value


class UserCreate(BaseModel):
    """BE A /v1/auth/register: email + password, optional display name; role is student."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    display_name: str | None = Field(default=None, max_length=150)

    _password = field_validator("password")(_bcrypt_limit)


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=72)
    # BE A called the name display_name; BE B calls it full_name. Both are accepted.
    display_name: str | None = Field(default=None, min_length=1, max_length=150)
    full_name: str | None = Field(default=None, min_length=1, max_length=150)

    _password = field_validator("password")(_bcrypt_limit)


class AdminUserUpdate(UserUpdate):
    role: Literal["teacher", "student", "admin"] | None = None


class V1Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
