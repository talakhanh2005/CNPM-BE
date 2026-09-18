import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import models  # noqa: F401
from app.core.config import get_settings
from app.core.db import make_database
from app.core.errors import AppError, install_handlers
from app.core.limits import RateLimiter, RequestLimitsMiddleware
from app.core.mongo import make_mongo_database
from app.core.schemas import Envelope, ErrorEnvelope, ok
from app.integrations.ai import build_ai
from app.integrations.storage import CloudinaryStorage
from app.modules.analysis.router import router as analysis_router
from app.modules.auth.router import router as auth_router
from app.modules.emotions.router import router as emotions_router
from app.modules.meetings.router import router as meetings_router
from app.modules.recordings.router import router as recordings_router
from app.modules.reports.router import router as reports_router
from app.modules.signaling.manager import ConnectionManager
from app.modules.signaling.router import router as signaling_router


def create_app(settings=None, session_factory=None, ai=None, storage=None):
    """Application factory; inject SQLAlchemy sessions and adapters for integration tests."""
    settings = settings or get_settings()
    database = None
    engine = None
    if session_factory is None:
        if settings.mongo_uri:
            database, session_factory = make_mongo_database(settings.mongo_uri)
        else:
            engine, session_factory = make_database(settings.sqlalchemy_url)

    @asynccontextmanager
    async def lifespan(app):
        yield
        for room in list(app.state.manager.repo.rooms):
            await app.state.manager.close_room(room)
        if database is not None:
            database.close()
        if engine is not None:
            engine.dispose()

    app = FastAPI(
        title="Face Emotion Backend",
        version="1.1.0",
        lifespan=lifespan,
        description="Classroom auth, meeting management, WebRTC signaling, Cloudinary and AI orchestration. WebSocket protocol: docs/API.md.",
    )
    app.state.settings, app.state.session_factory = settings, session_factory
    app.state.ai = ai or build_ai(settings)
    app.state.storage = storage or CloudinaryStorage(settings)
    app.state.manager = ConnectionManager(settings.max_room_connections)
    app.state.frame_limiter = RateLimiter()
    app.state.frame_semaphore = asyncio.Semaphore(settings.frame_slots)
    app.state.upload_semaphore = asyncio.Semaphore(settings.upload_slots)
    install_handlers(app)
    app.add_middleware(RequestLimitsMiddleware, max_json_bytes=settings.max_http_json_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    errors = {
        code: {"model": ErrorEnvelope}
        for code in [400, 401, 403, 404, 409, 413, 415, 422, 429, 500, 502, 503]
    }
    for router in [
        auth_router,
        meetings_router,
        signaling_router,
        recordings_router,
        analysis_router,
        emotions_router,
        reports_router,
    ]:
        app.include_router(router, responses=errors)

    @app.get("/health", response_model=Envelope[dict[str, str]], tags=["Health"])
    def health():
        """Liveness only; no external service requests."""
        return ok({"status": "ok"})

    @app.get("/ready", response_model=Envelope[dict[str, str]], tags=["Health"])
    def ready():
        """Database connectivity readiness."""
        if database is not None:
            try:
                database.ping()
            except Exception as exc:
                raise AppError(
                    503,
                    "DATABASE_UNAVAILABLE",
                    "Database is not ready",
                    [{"type": exc.__class__.__name__, "msg": str(exc), "database": "mongodb"}],
                ) from exc
            return ok({"database": "ok", "driver": "mongodb"})
        try:
            with session_factory() as db:
                db.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise AppError(
                503,
                "DATABASE_UNAVAILABLE",
                "Database is not ready",
                [
                    {
                        "type": exc.__class__.__name__,
                        "msg": str(exc),
                        "config": {
                            "database_url_set": bool(settings.database_url),
                            "driver": settings.sqlserver_driver,
                            "server": settings.sqlserver_server,
                            "database": settings.sqlserver_database,
                            "trusted_connection": settings.sqlserver_trusted_connection,
                            "encrypt": settings.sqlserver_encrypt,
                            "trust_server_certificate": settings.sqlserver_trust_server_certificate,
                        },
                    }
                ],
            ) from exc
        return ok({"database": "ok"})

    return app
