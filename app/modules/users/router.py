from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import OAuth2PasswordRequestForm

from app.core.dependencies import DB, Admin, CurrentUser
from app.core.schemas import ok
from app.modules.auth.schema import RegisterIn
from app.modules.auth.service import AuthService
from app.modules.users.schema import AdminUserUpdate, UserCreate, UserUpdate, V1Token
from app.modules.users.service import UserService, serialize_user

# BE A /api/v1/*: same /api prefix as the rest of the API (FE proxy strips it).
auth_router = APIRouter(prefix="/v1/auth", tags=["v1 Authentication (BE A)"])
router = APIRouter(prefix="/v1/users", tags=["v1 Users (BE A)"])


@auth_router.post("/register", status_code=201)
def register(data: UserCreate, request: Request, db: DB):
    """Register a student by email; display_name becomes full_name."""
    full_name = (data.display_name or "").strip() or str(data.email).split("@")[0]
    payload = RegisterIn(email=data.email, password=data.password, full_name=full_name)
    user = AuthService(db, request.app.state.settings).register(payload)
    return ok(serialize_user(user), "Registered")


@auth_router.post("/login", response_model=V1Token)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], request: Request, db: DB):
    """OAuth2 password form (username = email). Raw token body so Swagger "Authorize" works."""
    service = AuthService(db, request.app.state.settings)
    user = service.authenticate(form.username, form.password)
    tokens = service.tokens(user.id)
    db.commit()
    return {"access_token": tokens["access_token"], "token_type": "bearer"}


@router.get("/me")
def read_profile(user: CurrentUser):
    return ok(serialize_user(user))


@router.put("/me")
def update_profile(data: UserUpdate, request: Request, user: CurrentUser, db: DB):
    service = UserService(db, request.app.state.settings)
    return ok(serialize_user(service.update(user, data)), "Profile updated")


@router.get("")
def list_users(
    request: Request,
    admin: Admin,
    db: DB,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    users = UserService(db, request.app.state.settings).list(offset, limit)
    return ok([serialize_user(user) for user in users])


@router.get("/{user_id}")
def read_user(user_id: str, request: Request, admin: Admin, db: DB):
    return ok(serialize_user(UserService(db, request.app.state.settings).require(user_id)))


@router.put("/{user_id}")
def admin_update_user(user_id: str, data: AdminUserUpdate, request: Request, admin: Admin, db: DB):
    service = UserService(db, request.app.state.settings)
    return ok(serialize_user(service.update(service.require(user_id), data, actor=admin)))


@router.delete("/{user_id}")
def delete_user(user_id: str, request: Request, admin: Admin, db: DB):
    UserService(db, request.app.state.settings).delete(user_id, admin)
    return ok({"id": user_id, "deleted": True}, "User deleted")
