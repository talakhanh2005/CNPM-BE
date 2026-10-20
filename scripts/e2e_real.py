"""End-to-end checks against the RUNNING stack (API + worker + AI + MongoDB + Cloudinary).

    set TEACHER_REGISTRATION_KEY=<value from .env>
    python scripts/e2e_real.py

Covers the acceptance tests owned by Tu (README section 10): T01, T02, T05, T06, T08-T11 and
the mode/permission rules of contract v1. Creates uniquely named accounts, meetings and one
small Cloudinary video; nothing is deleted. Exit code 1 if any check fails.
"""

import base64
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import cv2
import httpx
import numpy as np
from PIL import Image

BACKEND = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
KEY = os.getenv("TEACHER_REGISTRATION_KEY", "")
WAIT_SECONDS = int(os.getenv("ANALYSIS_WAIT_SECONDS", "180"))
results = []
sys.stdout.reconfigure(encoding="utf-8")


def check(test_id, name, ok, detail=""):
    results.append((test_id, name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {test_id} {name}" + (f" -- {detail}" if detail else ""))


def code(response):
    try:
        return response.json()["data"].get("code")
    except Exception:
        return None


def jpeg_frame(frame_id):
    buffer = BytesIO()
    Image.new("RGB", (320, 240), (120, 120, 120)).save(buffer, format="JPEG")
    return {
        "frame_id": frame_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "frame_base64": base64.b64encode(buffer.getvalue()).decode(),
        "content_type": "image/jpeg",
    }


def make_video(seconds=30, fps=10):
    path = Path(tempfile.mkdtemp()) / "e2e.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (320, 240))
    rng = np.random.default_rng(1)
    for _ in range(seconds * fps):
        writer.write(rng.integers(90, 160, (240, 320, 3), dtype=np.uint8))
    writer.release()
    return path.read_bytes()


def main():
    run = uuid4().hex[:8]
    c = httpx.Client(base_url=BACKEND, timeout=60)

    def register(role, label):
        body = {"email": f"e2e-{label}-{run}@gmail.com", "password": "E2eTestPassword123!",
                "full_name": f"E2E {label}", "role": role}
        if role == "teacher":
            body["teacher_registration_key"] = KEY
        r = c.post("/auth/register", json=body)
        assert r.status_code == 201, r.text
        login = c.post("/auth/login", json={"email": body["email"], "password": body["password"]})
        return {"Authorization": "Bearer " + login.json()["data"]["access_token"]}

    teacher, student, outsider = (
        register("teacher", "teacher"), register("student", "student"), register("student", "other"),
    )
    # Uploads name the student whose camera the video is (merged from BE Tiền).
    student_id = c.get("/auth/me", headers=student).json()["data"]["id"]

    # ---- REALTIME meeting ------------------------------------------------------------------
    rt = c.post("/meetings", json={"mode": "realtime"}, headers=teacher).json()["data"]["id"]
    c.post(f"/meetings/{rt}/join", headers=student)
    r = c.post(f"/meetings/{rt}/emotions/infer", json=jpeg_frame("rt-1"), headers=student)
    d = r.json().get("data", {})
    check("T01", "realtime infer reaches real AI, returns EMOTION", r.status_code == 200
          and d.get("type") == "EMOTION" and d.get("mock") is False, f"emotion={d.get('emotion')} reason={d.get('failure_reason')}")
    check("T01", "result carries model_version (also for no_face)", bool(d.get("model_version")),
          f"model_version={d.get('model_version')}")
    r = c.get(f"/meetings/{rt}/report", headers=teacher)
    check("T02", "realtime meeting has no Report (409)", r.status_code == 409, str(r.status_code))
    time.sleep(0.4)
    big = jpeg_frame("rt-big")
    big["frame_base64"] = base64.b64encode(os.urandom(600_000)).decode()
    r = c.post(f"/meetings/{rt}/emotions/infer", json=big, headers=student)
    check("TU-02", "oversized frame -> 413 FRAME_TOO_LARGE, not 5xx", r.status_code == 413 and code(r) == "FRAME_TOO_LARGE",
          f"{r.status_code} {code(r)}")
    time.sleep(0.4)
    logs = c.get(f"/meetings/{rt}/emotion-logs", headers=teacher).json()["data"]["items"]
    check("T01", "prediction metadata logged, no image field", len(logs) >= 1
          and not any(("base64" in k or "image" in k or "blob" in k) for k in logs[0]))
    code_of_rt = c.get(f"/meetings/{rt}", headers=teacher).json()["data"]["code"]
    r = c.get("/meetings/lookup", params={"code": code_of_rt}, headers=student)
    check("U09", "lookup of a valid room code succeeds without joining", r.status_code == 200, str(r.status_code))
    r = c.get("/meetings/lookup", params={"code": "ZZZZZZZZZZ"}, headers=student)
    check("U09", "lookup of a wrong code -> 404 MEETING_NOT_FOUND", r.status_code == 404 and code(r) == "MEETING_NOT_FOUND",
          f"{r.status_code} {code(r)}")
    r = c.post(f"/meetings/{rt}/emotions/infer", json=jpeg_frame("rt-2"), headers=teacher)
    check("TU-02", "teacher cannot submit frames (403)", r.status_code == 403, str(r.status_code))
    time.sleep(0.5)  # frame rate limit is ~3/s per student
    r = c.post(f"/meetings/{rt}/emotions/infer", json={**jpeg_frame("rt-3"), "frame_base64": "!!"}, headers=student)
    check("TU-02", "invalid frame rejected (422)", r.status_code == 422, str(r.status_code))
    r = c.post(f"/meetings/{rt}/emotions/infer", json=jpeg_frame("rt-4"), headers=outsider)
    check("T10", "non-participant cannot infer (403)", r.status_code == 403, str(r.status_code))
    r = c.get(f"/meetings/{rt}/emotions/timeline", headers=teacher)
    check("TU-04", "realtime meeting has no timeline (409 INVALID_MEETING_MODE)",
          r.status_code == 409 and code(r) == "INVALID_MEETING_MODE", f"{r.status_code} {code(r)}")
    r = c.post(f"/meetings/{rt}/chat", json={"question": "Khi nao buon?"}, headers=teacher)
    check("TU-05", "realtime meeting has no chat (409)", r.status_code == 409, str(r.status_code))
    video = make_video()
    r = c.post(f"/meetings/{rt}/recordings", params={"student_id": student_id}, content=video,
               headers={**teacher, "Content-Type": "video/mp4"})
    check("T02", "realtime meeting rejects video upload (409)", r.status_code == 409 and code(r) == "INVALID_MEETING_MODE",
          f"got {r.status_code}" + (" -> asset created in Cloudinary!" if r.status_code == 201 else ""))
    r = c.post(f"/meetings/{rt}/recording", json={"durationSeconds": 60}, headers=teacher)
    check("T02", "realtime meeting rejects /recording metadata (409)", r.status_code == 409, str(r.status_code))
    r = c.post(f"/meetings/{rt}/recording-file", files={"file": ("a.webm", b"x", "video/webm")}, headers=teacher)
    check("T02", "realtime meeting rejects /recording-file (409)", r.status_code == 409, str(r.status_code))
    r = c.post("/media/signed-upload", json={"meeting_id": rt}, headers=teacher)
    check("T02", "realtime meeting gets no signed upload (409)", r.status_code == 409, str(r.status_code))

    # ---- AFTER_SESSION meeting -------------------------------------------------------------
    ps = c.post("/meetings", json={"mode": "after_session"}, headers=teacher).json()["data"]["id"]
    c.post(f"/meetings/{ps}/join", headers=student)
    r = c.post(f"/meetings/{ps}/emotions/infer", json=jpeg_frame("ps-1"), headers=student)
    check("TU-02", "after_session meeting rejects realtime frames (409)", r.status_code == 409, str(r.status_code))
    r = c.get(f"/meetings/{ps}/emotions/timeline", headers=teacher)
    check("T06", "timeline before any recording -> 409 ANALYSIS_NOT_READY/NO_RECORDING",
          r.status_code == 409 and code(r) == "ANALYSIS_NOT_READY", f"{r.status_code} {code(r)}")
    r = c.post(f"/meetings/{ps}/recordings", params={"student_id": student_id}, content=video,
               headers={**teacher, "Content-Type": "video/mp4"})
    ok = r.status_code == 201
    check("T03", "teacher uploads 30s video to real Cloudinary", ok, f"{r.status_code} {r.text[:150] if not ok else ''}")
    if not ok:
        return
    rec = r.json()["data"]
    rid = rec["id"]
    check("T03", "recording has Cloudinary URL and duration", bool(rec.get("cloudinary_url")) and rec["duration"] > 0,
          f"duration={rec['duration']}")
    r = c.get(f"/meetings/{ps}/emotions/timeline", headers=teacher)
    check("T06", "timeline while queued/processing is not served (409)",
          r.status_code == 409 or (r.status_code == 200), f"{r.status_code} {r.json().get('data', {}).get('details') if r.status_code == 409 else 'already done'}")
    for who, headers, expected in (("student", student, 403), ("outsider", outsider, 403)):
        r = c.get(f"/meetings/{ps}/emotions/timeline", headers=headers)
        check("T10", f"{who} cannot read timeline", r.status_code == expected, str(r.status_code))
        r = c.post(f"/meetings/{ps}/chat", json={"question": "x"}, headers=headers)
        check("T10", f"{who} cannot use chat", r.status_code == expected, str(r.status_code))

    status, deadline = None, time.time() + WAIT_SECONDS
    while time.time() < deadline:
        status = c.get(f"/recordings/{rid}/status", headers=teacher).json()["data"]
        if status["status"] in {"completed", "failed"}:
            break
        time.sleep(3)
    check("T03/T04", "real AI job completes via worker", status and status["status"] == "completed",
          f"status={status and status['status']} error={status and status.get('error_message')}")
    if not (status and status["status"] == "completed"):
        return
    r = c.get(f"/meetings/{ps}/emotions/timeline", headers=teacher)
    tl = r.json()["data"]
    segs = tl["segments"]
    check("T04", "timeline segments cover [0,duration) without overlap",
          r.status_code == 200 and segs and segs[0]["start_seconds"] == 0
          and all(a["end_seconds"] == b["start_seconds"] for a, b in zip(segs, segs[1:]))
          and abs(segs[-1]["end_seconds"] - tl["duration_seconds"]) < 0.6,
          f"{len(segs)} segments, source={tl['segments_source']}")
    check("T05", "no-face video is never reported as neutral",
          all(s["emotion"] != "neutral" for s in segs) and tl["summary"]["coverage"] <= 1,
          f"emotions={sorted({s['emotion'] for s in segs})} coverage={tl['summary']['coverage']}")
    r = c.get(f"/recordings/{rid}/playback", headers=teacher)
    check("FE", "playback returns a signed Cloudinary URL for the report video",
          r.status_code == 200 and r.json()["data"]["url"].startswith("https://"), str(r.status_code))
    keys = {"meeting_id", "recording_id", "duration_seconds", "model_version", "segments", "summary"}
    check("FE", "timeline has every field SessionReport reads",
          keys <= set(tl) and {"coverage", "analyzed_seconds", "no_face_seconds", "unknown_seconds",
                               "emotions", "dominant_emotion"} <= set(tl["summary"]))
    r = c.get(f"/meetings/{ps}/emotions/timeline", params={"from_seconds": 5, "to_seconds": 10}, headers=teacher)
    w = r.json()["data"]
    check("TU-04", "time-range filter clips segments to [5,10)",
          w["segments"][0]["start_seconds"] == 5 and w["segments"][-1]["end_seconds"] == 10)
    r = c.post(f"/meetings/{ps}/chat", json={"question": "Từ 00:05 đến 00:15 học sinh có cảm xúc gì?"}, headers=teacher)
    ch = r.json()["data"]
    check("T08", "chat GET_EMOTION_BY_TIME answers from DB", r.status_code == 200
          and ch["intent"] == "GET_EMOTION_BY_TIME" and ch["references"], ch["answer"][:90])
    r = c.post(f"/meetings/{ps}/chat", json={"question": "Khi nào học sinh buồn?"}, headers=teacher)
    ch = r.json()["data"]
    check("T09", "chat FIND_EMOTION(sad) does not invent data", r.status_code == 200
          and ch["intent"] == "FIND_EMOTION" and ch["references"] == [], ch["answer"][:90])
    r = c.post(f"/meetings/{ps}/chat", json={"question": "Hôm nay trời đẹp không?"}, headers=teacher)
    check("TU-06", "out-of-scope question -> UNKNOWN, no references", r.json()["data"]["intent"] == "UNKNOWN"
          and r.json()["data"]["references"] == [])
    r = c.post(f"/meetings/{ps}/chat", json={"question": ""}, headers=teacher)
    check("TU-06", "empty question rejected (422)", r.status_code == 422, str(r.status_code))

    before = c.get(f"/meetings/{ps}/emotions/timeline", headers=teacher).json()["data"]["segments"]
    for _ in range(2):
        c.post(f"/recordings/{rid}/analyze", headers=teacher)
    time.sleep(8)
    after = c.get(f"/meetings/{ps}/emotions/timeline", headers=teacher).json()["data"]["segments"]
    st = c.get(f"/recordings/{rid}/status", headers=teacher).json()["data"]
    check("T11", "repeated analyze keeps one job and identical segments", before == after
          and st["status"] == "completed", f"job={st['job_id']}")
    e1 = c.post(f"/meetings/{ps}/end", headers=teacher)
    e2 = c.post(f"/meetings/{ps}/end", headers=teacher)
    check("T11", "end meeting twice is idempotent", e1.status_code == 200 and e2.status_code == 200,
          f"{e1.status_code}/{e2.status_code}")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print("SETUP FAILED:", exc)
        sys.exit(2)
    failed = [r for r in results if not r[2]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)
