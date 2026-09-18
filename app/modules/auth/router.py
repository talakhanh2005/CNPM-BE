from fastapi import APIRouter, Request

from app.core.dependencies import DB, CurrentUser
from app.core.schemas import Envelope, ok
from app.modules.auth.schema import LoginIn, RefreshIn, RegisterIn, TokenOut, UserOut
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["BE-01 Authentication"])


@router.post("/register", status_code=201, response_model=Envelope[UserOut])
def register(data: RegisterIn, request: Request, db: DB):
    """Register a student or an invited teacher; emails are case-insensitive."""
    return ok(AuthService(db, request.app.state.settings).register(data), "Registered")


@router.post("/login", response_model=Envelope[TokenOut])
def login(data: LoginIn, request: Request, db: DB):
    """Return short-lived access JWT and a rotating, single-use refresh JWT."""
    return ok(AuthService(db, request.app.state.settings).login(data))


@router.get("/me", response_model=Envelope[UserOut])
def me(user: CurrentUser):
    """Return the user identified by the Bearer access token."""
    return ok(user)


@router.post("/refresh", response_model=Envelope[TokenOut])
def refresh(data: RefreshIn, request: Request, db: DB):
    """Atomically consume the refresh token and rotate both tokens."""
    return ok(AuthService(db, request.app.state.settings).refresh(data.refresh_token))


@router.post("/logout", response_model=Envelope[None])
def logout(data: RefreshIn, request: Request, db: DB):
    """Revoke this refresh session; access JWT remains valid until expiration."""
    AuthService(db, request.app.state.settings).logout(data.refresh_token)
    return ok(message="Logged out")
