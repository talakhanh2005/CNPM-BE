from typing import Literal
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=80)


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=80)


class AdminUserUpdate(UserUpdate):
    role: Literal["user", "admin"] | None = None


class UserRead(BaseModel):
    id: str
    email: EmailStr
    display_name: str | None = None
    role: Literal["user", "admin"]


class TokenRead(BaseModel):
    access_token: str
    token_type: str = "bearer"


class EmotionRead(BaseModel):
    id: str
    user_id: str
    label: str
    created_at: datetime
    media_url: str | None = None