def upload(env, room, student_id=None):
    return env.client.post(
        f"/meetings/{room}/recordings",
        params={} if student_id is None else {"student_id": student_id},
        content=b"\x00\x00\x00\x18ftypmp42",
        headers={**env.headers["teacher"], "Content-Type": "video/mp4"},
    )


def test_recording_student_persisted(env, room):
    response = upload(env, room, "student")
    assert response.status_code == 201, response.text
    recording = response.json()["data"]
    assert recording["student_id"] == "student"
    env.client.post(f"/meetings/{room}/join", headers=env.headers["other"])
    assert (
        env.client.get(f"/recordings/{recording['id']}", headers=env.headers["teacher"]).json()[
            "data"
        ]["student_id"]
        == "student"
    )
    assert (
        env.client.get(
            f"/recordings/{recording['id']}", headers=env.headers["outsider"]
        ).status_code
        == 403
    )


def test_multiple_students_validation(env, room):
    env.client.post(f"/meetings/{room}/join", headers=env.headers["other"])
    response = upload(env, room)
    assert response.status_code == 422
    for student_id in ("teacher", "outsider", "missing"):
        response = upload(env, room, student_id)
        assert response.status_code == 422
        assert response.json()["data"]["code"] == "INVALID_STUDENT"
    for student_id in ("student", "other"):
        response = upload(env, room, student_id)
        assert response.status_code == 201, response.text
        assert response.json()["data"]["student_id"] == student_id


def test_student_required_for_empty_meeting(env):
    room = env.client.post("/meetings", json={}, headers=env.headers["teacher"]).json()["data"][
        "id"
    ]
    assert upload(env, room, "student").status_code == 422
    response = upload(env, room)
    assert response.status_code == 422, response.text
    env.client.post(f"/meetings/{room}/join", headers=env.headers["student"])
    assert upload(env, room).status_code == 422


def test_reports_aggregate_student_recordings(env, room):
    from app.modules.analysis.model import AnalysisResult
    from app.modules.recordings.model import Recording

    env.client.post(f"/meetings/{room}/join", headers=env.headers["other"])
    ids = []
    for student_id, emotion, count in [("student", "happy", 1), ("other", "sad", 9)]:
        recording_id = upload(env, room, student_id).json()["data"]["id"]
        ids.append(recording_id)
        with env.factory() as db:
            recording = db.get(Recording, recording_id)
            recording.status = "completed"
            db.add(recording)
            db.add(
                AnalysisResult(
                    recording_id=recording_id,
                    result={
                        "sample_counts": {emotion: count},
                        "timeline": [
                            {
                                "timestamp": 0,
                                "emotion": emotion,
                                "confidence": 0.9,
                                "student_id": "untrusted-ai-id",
                            }
                        ],
                    },
                )
            )
            db.commit()
        path = f"/recordings/{recording_id}/report"
        report = env.client.get(path, headers=env.headers["teacher"]).json()["data"]
        assert report["student_id"] == student_id
        assert report["recording_id"] == recording_id
        assert report["meeting_id"] == room
        assert report["timeline"][0]["student_id"] == student_id
        assert report["sample_count"] == count
        assert env.client.get(path, headers=env.headers["outsider"]).status_code == 403
        assert (
            env.client.get(
                f"/recordings/{recording_id}/analysis", headers=env.headers["teacher"]
            ).json()["data"]
            == report
        )
    report = env.client.get(
        f"/meetings/{room}/report?limit=1", headers=env.headers["teacher"]
    ).json()["data"]
    assert report["meeting_id"] == room
    assert report["distribution"] == {"happy": 10, "sad": 90}
    assert report["sample_count"] == 10
    assert report["timeline_total"] == 2 and len(report["timeline"]) == 1
    assert report["timeline"][0]["recording_id"] in ids
    upload(env, room, "student")
    report = env.client.get(f"/meetings/{room}/report", headers=env.headers["teacher"]).json()[
        "data"
    ]
    assert report["status"] == "partial"
    assert report["sample_count"] == 10


def test_empty_reports_keep_recording_identity(env, room):
    recording_id = upload(env, room, "student").json()["data"]["id"]
    report = env.client.get(
        f"/recordings/{recording_id}/report", headers=env.headers["teacher"]
    ).json()["data"]
    assert report["student_id"] == "student" and report["sample_count"] == 0
    assert report["status"] == "uploaded"
    meeting = env.client.get(f"/meetings/{room}/report", headers=env.headers["teacher"]).json()[
        "data"
    ]
    assert meeting["source"] == "none" and meeting["sample_count"] == 0
