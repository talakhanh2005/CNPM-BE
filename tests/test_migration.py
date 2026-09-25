from alembic.config import Config
from sqlalchemy import inspect, text

from alembic import command
from app.core.config import get_settings
from app.core.db import make_engine


def test_upgrade_existing_database(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrations.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
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
        with engine.connect() as db:
            assert db.scalar(text("SELECT mode FROM meetings WHERE id='meeting'")) == "realtime"
            assert db.scalar(text("SELECT COUNT(*) FROM participants")) == 1
        engine.dispose()
    finally:
        get_settings.cache_clear()
