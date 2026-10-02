from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pymongo.errors import DuplicateKeyError

from cnpm_be.database import get_database, password_hash
from cnpm_be.schemas import TokenRead, UserCreate, UserRead

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def serialize_user(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(document["_id"]),
        "email": document["email"],
        "display_name": document.get("display_name"),
        "role": document.get("role", "user"),
    }


def create_access_token(user_id: str, request: Request) -> str:
    config = request.app.state.settings
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=config.access_token_expire_minutes
    )
    return jwt.encode(
        {"sub": user_id, "exp": expires_at},
        config.jwt_secret_key.get_secret_value(),
        algorithm=config.jwt_algorithm,
    )


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    database: Any = Depends(get_database),
) -> dict[str, Any]:
    config = request.app.state.settings
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            config.jwt_secret_key.get_secret_value(),
            algorithms=[config.jwt_algorithm],
        )
        user_id = ObjectId(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized from None

    user = await database.users.find_one({"_id": user_id})
    if user is None:
        raise unauthorized
    return user


async def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register_user(user: UserCreate, database: Any = Depends(get_database)) -> dict[str, Any]:
    email = str(user.email).lower()
    if await database.users.find_one({"email": email}):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    document = {
        "email": email,
        "password_hash": password_hash.hash(user.password),
        "display_name": user.display_name,
        "role": "user",
    }
    try:
        result = await database.users.insert_one(document)
    except DuplicateKeyError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered") from None
    document["_id"] = result.inserted_id
    return serialize_user(document)


@router.post("/login", response_model=TokenRead)
async def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    database: Any = Depends(get_database),
) -> dict[str, str]:
    user = await database.users.find_one({"email": form.username.lower()})
    if user is None or not password_hash.verify(form.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"access_token": create_access_token(str(user["_id"]), request), "token_type": "bearer"}