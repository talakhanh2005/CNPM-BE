from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.dependencies import DB, Admin
from app.core.mongo import model_from_doc
from app.core.schemas import Envelope, ok
from app.modules.auth.model import User
from app.modules.auth.schema import UserOut
from app.modules.meetings.model import Meeting
from app.modules.meetings.schema import MeetingOut
from app.modules.meetings.service import meeting_out

router = APIRouter(prefix="/admin", tags=["Admin"])


class UsersOut(BaseModel):
    items: list[UserOut]
    offset: int
    limit: int


class MeetingsOut(BaseModel):
    items: list[MeetingOut]
    offset: int
    limit: int


def page(db, model, offset, limit):
    docs = db.collection(model.__collection__).find().sort("id", 1).skip(offset).limit(limit)
    if model is Meeting:
        # Admins also see soft-deleted rooms; same payload as GET /meetings/{id}.
        return [meeting_out(db, db.get(Meeting, d["id"])) for d in docs]
    return [model_from_doc(model, d) for d in docs]


@router.get("/users", response_model=Envelope[UsersOut])
def users(user: Admin, db: DB, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    return ok({"items": page(db, User, offset, limit), "offset": offset, "limit": limit})


@router.get("/meetings", response_model=Envelope[MeetingsOut])
def meetings(
    user: Admin, db: DB, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)
):
    return ok({"items": page(db, Meeting, offset, limit), "offset": offset, "limit": limit})
