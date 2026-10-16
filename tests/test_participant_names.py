from app.modules.auth.model import User


def test_participant_names_in_meeting_responses(env):
    with env.factory() as db:
        db.get(User, "teacher").full_name = "Nguyễn Giáo Viên"
        db.get(User, "student").full_name = "Trần Học Sinh"
        db.commit()
    response = env.client.post("/meetings", json={}, headers=env.headers["teacher"])
    meeting = response.json()["data"]
    assert meeting["participants"][0]["full_name"] == "Nguyễn Giáo Viên"
    meeting_id = meeting["id"]
    response = env.client.post(
        "/meetings/join", json={"code": meeting["code"]}, headers=env.headers["student"]
    )
    expected = {"teacher": "Nguyễn Giáo Viên", "student": "Trần Học Sinh"}

    def check(response):
        assert response.status_code == 200, response.text
        participants = response.json()["data"]["participants"]
        assert {p["user_id"]: p["full_name"] for p in participants} == expected
        assert all("email" not in p and "password_hash" not in p for p in participants)

    check(response)
    for role in ("teacher", "student"):
        check(env.client.get(f"/meetings/{meeting_id}", headers=env.headers[role]))
    with env.factory() as db:
        db.get(User, "student").full_name = "Tên Mới"
        db.commit()
    expected["student"] = "Tên Mới"
    for action, role in (("leave", "student"), ("join", "student"),
                         ("start", "teacher"), ("end", "teacher")):
        check(env.client.post(f"/meetings/{meeting_id}/{action}", headers=env.headers[role]))
    assert env.client.get(
        f"/meetings/{meeting_id}", headers=env.headers["outsider"]
    ).status_code == 403
