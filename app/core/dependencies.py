from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AppError
from app.core.security import decode_token
from app.modules.auth.model import User

bearer = HTTPBearer(auto_error=False)


def get_db(request: Request):
    with request.app.state.session_factory() as db:
        yield db


DB = Annotated[object, Depends(get_db)]


def get_current_user(
    request: Request,
    db: DB,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
):
    if not credentials:
        raise AppError(401, "UNAUTHENTICATED", "Bearer access token required")
    payload = decode_token(credentials.credentials, "access", request.app.state.settings)
    user = db.get(User, payload["sub"])
    if user is None:
        raise AppError(401, "INVALID_TOKEN", "User no longer exists")
    request.state.current_user = user
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(role: str):
    def check(user: CurrentUser):
        if user.role != role:
            raise AppError(403, "FORBIDDEN", f"Role {role} required")
        return user

    return check


Teacher = Annotated[User, Depends(require_role("teacher"))]
Student = Annotated[User, Depends(require_role("student"))]
