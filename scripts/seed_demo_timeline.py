"""Create ONE finished after_session meeting with a known emotion timeline, for testing
BE-TU-04 (timeline), BE-TU-05/06 (chatbot) and the Report page without recording a real face.

    python scripts/make_demo_video.py demo.mp4
    python scripts/seed_demo_timeline.py --teacher-email you@example.com --video demo.mp4

What is real and what is not:
  * real: MongoDB documents, the Cloudinary upload of the video, the segments ingestion,
    the timeline/chat code paths, permissions;
  * synthetic: the emotion segments below were typed in (marked model_version "demo-seed" and
    a SEEDED summary), because a faceless video cannot produce them. Do not use them as results.

The meeting is named "[DEMO] ..." so it is easy to find and delete; the script prints its id.
"""

import argparse
import secrets
import sys
from pathlib import Path

from app import models  # noqa: F401
from app.core.config import get_settings
from app.core.db import new_id, now
from app.core.mongo import make_mongo_database
from app.integrations.ai_schema import BatchResult
from app.integrations.storage import CloudinaryStorage
from app.modules.analysis.model import AnalysisJob, AnalysisResult
from app.modules.meetings.model import Meeting, Participant
from app.modules.recordings.model import Recording

MODEL_VERSION = "demo-seed"
# [start, end) in seconds from the start of the 60 s video. These are the expected answers
# used by docs/TEST-TU-04-05-06.md and scripts/check_tu_04_05_06.py.
SEGMENTS = [
    {"start_seconds": 0, "end_seconds": 10, "emotion": "neutral", "avg_confidence": 0.87},
    {"start_seconds": 10, "end_seconds": 25, "emotion": "happy", "avg_confidence": 0.91},
    {"start_seconds": 25, "end_seconds": 30, "emotion": "no_face", "avg_confidence": None},
    {"start_seconds": 30, "end_seconds": 45, "emotion": "sad", "avg_confidence": 0.70},
    {"start_seconds": 45, "end_seconds": 52, "emotion": "angry", "avg_confidence": 0.66},
    {"start_seconds": 52, "end_seconds": 60, "emotion": "neutral", "avg_confidence": 0.80},
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--teacher-email", required=True)
    parser.add_argument("--student-email", help="optional student to add as a participant")
    parser.add_argument("--video", required=True, help="MP4 of at least 60 seconds")
    args = parser.parse_args()

    data = Path(args.video).read_bytes()
    settings = get_settings()
    database, factory = make_mongo_database(settings.mongo_uri)
    try:
        with factory() as db:
            teacher = db.collection("users").find_one({"email": args.teacher_email.lower()})
            if teacher is None or teacher.get("role") != "teacher":
                sys.exit(f"{args.teacher_email} is not an existing teacher account")
            student = None
            if args.student_email:
                student = db.collection("users").find_one({"email": args.student_email.lower()})
                if student is None:
                    sys.exit(f"{args.student_email} does not exist")

            meeting_id, recording_id, job_id = new_id(), new_id(), new_id()
            public_id = f"face-emotion/{meeting_id}/{recording_id}"
            asset = CloudinaryStorage(settings).upload(data, public_id)
            if asset.duration < 59:
                CloudinaryStorage(settings).delete(asset.public_id)
                sys.exit(f"video is {asset.duration:.0f}s; the demo timeline needs 60s")

            result = BatchResult(
                sample_counts={"neutral": 18, "happy": 15, "sad": 15, "angry": 7},
                timeline=[],
                summary="SEEDED DEMO DATA, not an AI result.",
                segments=SEGMENTS,
                model_version=MODEL_VERSION,
            )
            created = now()
            db.add(
                Meeting(
                    id=meeting_id,
                    code=secrets.token_hex(5).upper(),
                    teacher_id=teacher["id"],
                    student_id=student["id"] if student else None,
                    mode="after_session",
                    status="ended",
                    created_at=created,
                    ended_at=created,
                    name="[DEMO] Timeline mẫu 60 giây",
                    description="Dữ liệu cảm xúc mẫu để test timeline/chatbot (scripts/seed_demo_timeline.py).",
                    tags=["demo"],
                    participant_mode="free",
                    duration_minutes=1,
                    recording_status="none",
                )
            )
            db.add(Participant(meeting_id=meeting_id, user_id=teacher["id"], status="left",
                               joined_at=created, left_at=created))
            if student:
                db.add(Participant(meeting_id=meeting_id, user_id=student["id"], status="left",
                                   joined_at=created, left_at=created))
            db.add(
                Recording(
                    id=recording_id,
                    meeting_id=meeting_id,
                    cloudinary_url=asset.url,
                    public_id=asset.public_id,
                    format=asset.format,
                    duration=asset.duration,
                    size_bytes=asset.size_bytes,
                    status="completed",
                    created_at=created,
                )
            )
            db.add(
                AnalysisJob(id=job_id, recording_id=recording_id, state="completed", attempts=1,
                            created_at=created, updated_at=created)
            )
            db.add(
                AnalysisResult(recording_id=recording_id, result=result.model_dump(mode="json"),
                               completed_at=created)
            )
            db.commit()
        print(f"meeting_id={meeting_id}\ncode={_code(factory, meeting_id)}\nrecording_id={recording_id}")
    finally:
        database.close()


def _code(factory, meeting_id):
    with factory() as db:
        return db.collection("meetings").find_one({"id": meeting_id})["code"]


if __name__ == "__main__":
    main()
