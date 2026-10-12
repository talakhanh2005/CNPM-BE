from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.core.dependencies import DB, Admin
from app.core.mongo import model_from_doc
from app.core.schemas import Envelope, ok
from app.modules.auth.model import User
from app.modules.auth.schema import UserOut
from app.modules.meetings.model import Meeting
from app.modules.meetings.schema import MeetingOut

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
    if getattr(db, "is_mongo", False):
        docs = db.collection(model.__tablename__).find().sort("id", 1).skip(offset).limit(limit)
        # Load relationships through the session for meetings.
        return [
            db.get(Meeting, d["id"]) if model is Meeting else model_from_doc(model, d) for d in docs
        ]
    return db.scalars(select(model).order_by(model.id).offset(offset).limit(limit)).all()


@router.get("/users", response_model=Envelope[UsersOut])
def users(user: Admin, db: DB, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    return ok({"items": page(db, User, offset, limit), "offset": offset, "limit": limit})


@router.get("/meetings", response_model=Envelope[MeetingsOut])
def meetings(
    user: Admin, db: DB, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)
):
    return ok({"items": page(db, Meeting, offset, limit), "offset": offset, "limit": limit})
