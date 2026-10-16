from unittest.mock import AsyncMock

from sqlalchemy import select

from app.core.db import now
from app.modules.analysis.model import AnalysisJob, AnalysisResult
from app.modules.emotions.model import EmotionSample
from app.modules.materials.model import Material
from app.modules.meetings.model import Meeting, Participant
from app.modules.recordings.model import Recording


def test_delete_requires_owner(env, room):
    url = f"/meetings/{room}"
    assert env.client.delete(url).status_code == 401
    for role in ("student", "outsider"):
        assert env.client.delete(url, headers=env.headers[role]).status_code == 403
    assert env.client.get(url, headers=env.headers["teacher"]).status_code == 200


def test_delete_removes_dependents_and_closes_room(env, room):
    other = env.client.post("/meetings", json={}, headers=env.headers["teacher"]).json()["data"]
    with env.factory() as db:
        db.add(Recording(
            id="recording-delete", meeting_id=room, student_id="student",
            cloudinary_url="https://storage.test/video", public_id="delete-video",
            format="mp4", duration=30, size_bytes=10, status="completed", created_at=now(),
        ))
        db.flush()
        db.add(AnalysisJob(
            id="job-delete", recording_id="recording-delete", state="completed", attempts=1,
            created_at=now(), updated_at=now(),
        ))
        db.add(AnalysisResult(recording_id="recording-delete", result={}, completed_at=now()))
        db.add(EmotionSample(
            id="sample-delete", meeting_id=room, student_id="student", timestamp=now(),
            emotion="happy", confidence=0.9, mock=True, face_detected=True, logged=True,
        ))
        db.add(Material(
            id="material-delete", meeting_id=room, uploaded_by="teacher", filename="a.pdf",
            content_type="application/pdf", size_bytes=10, public_id="delete-document",
            created_at=now(),
        ))
        db.commit()
    close_room = AsyncMock()
    env.app.state.manager.close_room = close_room
    response = env.client.delete(f"/meetings/{room}", headers=env.headers["teacher"])
    assert response.status_code == 200, response.text
    assert response.json() == {"success": True, "data": None, "message": "Meeting deleted"}
    close_room.assert_awaited_once_with(room)
    with env.factory() as db:
        assert db.get(Meeting, room) is None
        assert db.get(Meeting, other["id"]) is not None
        for model in (Participant, Recording, Material, EmotionSample):
            if getattr(db, "is_mongo", False):
                assert db.collection(model.__tablename__).count_documents({"meeting_id": room}) == 0
            else:
                assert db.scalar(select(model).where(model.meeting_id == room)) is None
        assert db.get(AnalysisJob, "job-delete") is None
        assert db.get(AnalysisResult, "recording-delete") is None
    assert env.client.get(f"/meetings/{room}", headers=env.headers["teacher"]).status_code == 404
    assert env.client.delete(f"/meetings/{room}", headers=env.headers["teacher"]).status_code == 404
    history = env.client.get("/meetings", headers=env.headers["teacher"]).json()["data"]["items"]
    assert room not in {item["id"] for item in history}
