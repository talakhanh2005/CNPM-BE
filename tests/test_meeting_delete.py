"""DELETE /meetings/{id}: BE Tiền's owner check and socket close, kept as a soft delete.

README asks for a soft delete, so the document stays (``deleted_at`` set) and recordings,
analysis and samples are kept for audit; the room disappears from every lookup.
"""

from unittest.mock import AsyncMock

from app.modules.meetings.model import Meeting


def test_delete_requires_owner(env, room):
    url = f"/meetings/{room}"
    assert env.client.delete(url).status_code == 401
    # Non-owners get 404 so meeting ids cannot be probed.
    for role in ("student", "outsider"):
        assert env.client.delete(url, headers=env.headers[role]).status_code == 404
    assert env.client.get(url, headers=env.headers["teacher"]).status_code == 200


def test_delete_hides_meeting_and_closes_room(env, room):
    other = env.client.post("/meetings", json={}, headers=env.headers["teacher"]).json()["data"]
    close_room = AsyncMock()
    env.app.state.manager.close_room = close_room
    response = env.client.delete(f"/meetings/{room}", headers=env.headers["teacher"])
    assert response.status_code == 200, response.text
    assert response.json()["data"]["meeting_id"] == room
    close_room.assert_awaited_once_with(room)
    with env.factory() as db:
        stored = db.collection(Meeting.__collection__).find_one({"id": room})
        assert stored["deleted_at"] is not None
        assert db.collection(Meeting.__collection__).find_one({"id": other["id"]}) is not None
    assert env.client.get(f"/meetings/{room}", headers=env.headers["teacher"]).status_code == 404
    assert env.client.delete(f"/meetings/{room}", headers=env.headers["teacher"]).status_code == 404
    history = env.client.get("/meetings", headers=env.headers["teacher"]).json()["data"]["items"]
    assert room not in {item["id"] for item in history}
    assert other["id"] in {item["id"] for item in history}
