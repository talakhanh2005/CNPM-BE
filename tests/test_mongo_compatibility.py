import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError

from app.core.config import Settings
from app.core.errors import install_handlers
from app.core.mongo import MongoDatabase


def test_mongo_ignores_unused_sql_configuration():
    settings = Settings(
        _env_file=None,
        jwt_secret="test-secret-" * 4,
        mongo_uri="mongodb://localhost/face_emotion",
        database_url="unused SQL configuration",
        sqlserver_trusted_connection=False,
    )
    assert settings.mongo_uri == "mongodb://localhost/face_emotion"


@pytest.mark.parametrize("uri", ["", "sqlite://", "https://localhost"])
def test_requires_mongo_uri(uri):
    with pytest.raises(ValidationError, match="MONGO_URI must use"):
        Settings(
            _env_file=None,
            jwt_secret="test-secret-" * 4,
            mongo_uri=uri,
        )


def test_mongo_duplicate_returns_conflict():
    app = FastAPI()
    install_handlers(app)

    @app.post("/duplicate")
    def duplicate():
        raise DuplicateKeyError("private database details")

    with TestClient(app) as client:
        response = client.post("/duplicate")
    assert response.status_code == 409
    assert response.json()["data"]["code"] == "CONFLICT"
    assert "private database details" not in response.text


def test_backend_imports_without_sql_dependencies():
    code = """
import importlib.abc
import sys
class BlockSQL(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'sqlalchemy', 'alembic', 'pyodbc'}:
            raise ImportError('SQL dependency used: ' + fullname)
sys.meta_path.insert(0, BlockSQL())
from app.main import create_app
from app.core.config import Settings
import app.worker
import scripts.create_admin
import scripts.check_mongo
app = create_app(Settings(_env_file=None, jwt_secret='test-secret-' * 4))
assert '/ready' in app.openapi()['paths']
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_readiness_uses_mongo_and_hides_connection_details(monkeypatch):
    from app.main import create_app

    settings = Settings(_env_file=None, jwt_secret="test-secret-" * 4)
    monkeypatch.setattr(MongoDatabase, "ping", lambda self: None)
    with TestClient(create_app(settings)) as client:
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json()["data"]["driver"] == "mongodb"

        def fail(self):
            raise ServerSelectionTimeoutError("private connection details")

        monkeypatch.setattr(MongoDatabase, "ping", fail)
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json()["data"]["code"] == "DATABASE_UNAVAILABLE"
        assert "private connection details" not in response.text
        assert client.get("/health").status_code == 200
