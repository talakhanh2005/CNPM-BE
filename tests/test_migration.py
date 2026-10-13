from alembic.config import Config
from sqlalchemy import inspect, text

from alembic import command
from app.core.config import get_settings
from app.core.db import make_engine


def test_upgrade_existing_database(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrations.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    # Settings require a JWT secret; do not depend on a developer's local .env.
    monkeypatch.setenv("JWT_SECRET", "migration-test-secret-" * 2)
    get_settings.cache_clear()
    try:
        config = Config("alembic.ini")
        command.upgrade(config, "20260915_unicode")
        engine = make_engine(url)
        with engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO users (id,email,password_hash,full_name,role,created_at) "
                    "VALUES ('teacher','t@example.test','hash','Teacher','teacher',CURRENT_TIMESTAMP)"
                )
            )
            db.execute(
                text(
                    "INSERT INTO meetings (id,code,teacher_id,status,created_at) "
                    "VALUES ('meeting','ABC12345','teacher','ongoing',CURRENT_TIMESTAMP)"
                )
            )
            db.execute(
                text(
                    "INSERT INTO participants (meeting_id,user_id,status,joined_at) "
                    "VALUES ('meeting','teacher','joined',CURRENT_TIMESTAMP)"
                )
            )
        engine.dispose()
        command.upgrade(config, "head")
        engine = make_engine(url)
        inspector = inspect(engine)
        assert "materials" in inspector.get_table_names()
        assert {"mode", "student_id"} <= {c["name"] for c in inspector.get_columns("meetings")}
        assert {"frame_id", "probabilities", "face_detected", "logged"} <= {
            c["name"] for c in inspector.get_columns("emotion_samples")
        }
        assert {"name", "participant_mode", "deleted_at", "recording_status"} <= {
            c["name"] for c in inspector.get_columns("meetings")
        }
        assert {"shared_with_all", "share_token", "revoked_at"} <= {
            c["name"] for c in inspector.get_columns("materials")
        }
        assert "emotion_labels" in inspector.get_table_names()
        assert "emotion_segments" in inspector.get_table_names()
        assert "model_version" in {c["name"] for c in inspector.get_columns("emotion_samples")}
        with engine.connect() as db:
            assert db.scalar(text("SELECT mode FROM meetings WHERE id='meeting'")) == "realtime"
            assert db.scalar(text("SELECT COUNT(*) FROM participants")) == 1
            assert (
                db.scalar(text("SELECT participant_mode FROM meetings WHERE id='meeting'"))
                == "free"
            )
        with engine.begin() as db:
            # New CHECK values: admin role and disconnected participants.
            db.execute(
                text(
                    "INSERT INTO users (id,email,password_hash,full_name,role,created_at) "
                    "VALUES ('admin','a@example.test','hash','Admin','admin',CURRENT_TIMESTAMP)"
                )
            )
            db.execute(text("UPDATE participants SET status='disconnected'"))
            # Downgrade restores the old CHECKs, so remove values they do not allow.
            db.execute(text("DELETE FROM users WHERE id='admin'"))
            db.execute(text("UPDATE participants SET status='joined'"))
        engine.dispose()
        command.downgrade(config, "20260925_classroom")
    finally:
        get_settings.cache_clear()
