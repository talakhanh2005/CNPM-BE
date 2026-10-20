import mongomock
import pytest
from pymongo.errors import DuplicateKeyError

from app.core.mongo import MongoDatabase, MongoSession, doc_from_model, model_from_doc
from app.modules.analysis.model import AnalysisResult
from app.modules.auth.model import User
from app.modules.meetings.model import Meeting, Participant


@pytest.fixture
def database():
    db = mongomock.MongoClient(tz_aware=True).test
    indexes = MongoDatabase("mongodb://unused/test")
    indexes.database = db
    indexes.ensure_indexes()
    indexes.ensure_indexes()
    return db


def test_indexes_protect_ids_and_email(database):
    database.users.insert_one({"id": "one", "email": "one@example.com"})
    for doc in (
        {"id": "one", "email": "two@example.com"},
        {"id": "two", "email": "one@example.com"},
    ):
        with pytest.raises(DuplicateKeyError):
            database.users.insert_one(doc)


def test_insert_cannot_overwrite_existing_user(database):
    user = User(
        id="one",
        email="one@example.com",
        password_hash="hash",
        full_name="Original",
        role="student",
    )
    with MongoSession(database) as db:
        db.add(user)
        db.commit()
    with MongoSession(database) as db:
        db.add(
            User(
                id="one",
                email="two@example.com",
                password_hash="hash",
                full_name="Replacement",
                role="teacher",
            )
        )
        with pytest.raises(DuplicateKeyError):
            db.commit()
        db.rollback()
    assert database.users.find_one({"id": "one"})["full_name"] == "Original"


def test_merge_updates_result_and_rollback_discards_unflushed_edits(database):
    with MongoSession(database) as db:
        db.merge(AnalysisResult(recording_id="recording", result={"version": 1}))
    with MongoSession(database) as db:
        db.merge(AnalysisResult(recording_id="recording", result={"version": 2}))
    assert database.analysis_results.count_documents({}) == 1
    assert database.analysis_results.find_one({})["result"] == {"version": 2}
    with MongoSession(database) as db:
        result = db.get(AnalysisResult, "recording")
        result.result = {"version": 3}
        db.rollback()
        db.commit()
    assert database.analysis_results.find_one({})["result"] == {"version": 2}


def test_legacy_meeting_defaults_and_transient_relations():
    meeting = model_from_doc(
        Meeting,
        {
            "_id": "mongo-id",
            "id": "meeting",
            "code": "CODE",
            "teacher_id": "teacher",
            "legacy_field": True,
        },
    )
    assert meeting.mode == "realtime"
    meeting.participants = [Participant(meeting_id="meeting", user_id="student")]
    assert meeting.student_ids == ["student"]
    assert "participants" not in doc_from_model(meeting)
    assert "user" not in doc_from_model(meeting.participants[0])
