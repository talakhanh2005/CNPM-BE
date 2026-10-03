"""Exercise the running backend -> OpenEmotion integration.

Run from the backend project directory:
    python scripts/test_live_ai_connection.py

The script creates uniquely named test accounts and a meeting. It does not
delete them so the result can be inspected through the normal API/database.
"""

import base64
import os
import sys
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

import httpx
from PIL import Image


BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = float(os.getenv("TEST_TIMEOUT_SECONDS", "30"))


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def expect(response: httpx.Response, statuses: set[int], action: str) -> dict:
    if response.status_code not in statuses:
        fail(f"{action}: HTTP {response.status_code}: {response.text}")
    try:
        return response.json()
    except ValueError:
        fail(f"{action}: response was not JSON: {response.text}")


def data(response_json: dict, action: str) -> dict:
    value = response_json.get("data")
    if not isinstance(value, dict):
        fail(f"{action}: missing data envelope: {response_json}")
    return value


def main() -> None:
    run_id = uuid4().hex[:10]
    teacher = {
        "email": f"live-teacher-{run_id}@gmail.com",
        "password": "LiveTestPassword123!",
        "full_name": "Live Integration Teacher",
        "role": "teacher",
    }
    student = {
        "email": f"live-student-{run_id}@gmail.com",
        "password": "LiveTestPassword123!",
        "full_name": "Live Integration Student",
        "role": "student",
    }

    image = BytesIO()
    Image.new("RGB", (320, 240), color=(128, 128, 128)).save(image, format="JPEG")
    frame = {
        "frame_id": f"live-frame-{run_id}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "frame_base64": base64.b64encode(image.getvalue()).decode("ascii"),
        "content_type": "image/jpeg",
    }

    with httpx.Client(base_url=BACKEND_URL, timeout=TIMEOUT) as client:
        health = expect(client.get("/health"), {200}, "backend health")
        print(f"Backend health: {health}")

        for account, label in ((teacher, "teacher"), (student, "student")):
            expect(client.post("/auth/register", json=account), {201}, f"register {label}")

        tokens = {}
        for account, label in ((teacher, "teacher"), (student, "student")):
            login = data(
                expect(
                    client.post(
                        "/auth/login",
                        json={"email": account["email"], "password": account["password"]},
                    ),
                    {200},
                    f"login {label}",
                ),
                f"login {label}",
            )
            tokens[label] = login["access_token"]

        teacher_headers = {"Authorization": f"Bearer {tokens['teacher']}"}
        student_headers = {"Authorization": f"Bearer {tokens['student']}"}

        meeting = data(
            expect(
                client.post(
                    "/meetings",
                    json={"status": "ongoing", "mode": "realtime"},
                    headers=teacher_headers,
                ),
                {201},
                "create realtime meeting",
            ),
            "create realtime meeting",
        )
        meeting_id = meeting["id"]
        print(f"Created meeting: {meeting_id}")

        expect(
            client.post(f"/meetings/{meeting_id}/join", headers=student_headers),
            {200},
            "student join meeting",
        )

        result = data(
            expect(
                client.post(
                    f"/meetings/{meeting_id}/frames",
                    json=frame,
                    headers=student_headers,
                ),
                {200},
                "send frame through backend",
            ),
            "send frame through backend",
        )

    if result.get("frame_id") != frame["frame_id"]:
        fail(f"AI response frame_id mismatch: {result}")
    if result.get("mock") is True:
        fail("Backend used MockAIClient; check AI_MODE=http")
    if result.get("emotion") not in {
        "happy",
        "neutral",
        "sad",
        "angry",
        "surprised",
        "fearful",
        "disgusted",
        "fail_detection",
    }:
        fail(f"Unexpected AI emotion: {result}")

    print("Frame response from live OpenEmotion:")
    print(result)
    print("PASS: teacher creation, student creation, room flow, and live AI frame request")


if __name__ == "__main__":
    main()
