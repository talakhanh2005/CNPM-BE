import asyncio
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401
from app.core.config import get_settings
from app.core.errors import AppError, install_handlers
from app.core.limits import RateLimiter, RequestLimitsMiddleware
from app.core.mongo import make_mongo_database
from app.core.request_id import RequestIdMiddleware
from app.core.schemas import Envelope, ErrorEnvelope, ok
from app.integrations.ai import build_ai
from app.integrations.storage import CloudinaryStorage
from app.modules.analysis.router import router as analysis_router
from app.modules.auth.router import router as auth_router
from app.modules.auth.service import AuthService
from app.modules.chat.llm import build_intent_parser
from app.modules.chat.router import router as chat_router
from app.modules.emotion_labels.router import router as emotion_labels_router
from app.modules.emotions.router import router as emotions_router
from app.modules.materials.router import router as materials_router
from app.modules.materials.router import share_router
from app.modules.media.router import router as media_router
from app.modules.meetings.router import router as meetings_router
from app.modules.recordings.router import router as recordings_router
from app.modules.reports.router import router as reports_router
from app.modules.signaling.manager import ConnectionManager
from app.modules.signaling.router import router as signaling_router
from app.modules.timeline.router import router as timeline_router
from app.modules.users.router import auth_router as v1_auth_router
from app.modules.users.router import router as users_router

APP_VERSION = "2.0.0"
# Uvicorn's logger so lines appear with the default uvicorn log configuration.
logger = logging.getLogger("uvicorn.error")
SHARE_TOKEN_PATH = re.compile(r"(/share/documents/)[^/?\s]+")


class RedactShareTokenFilter(logging.Filter):
    """BE A: a share token grants document access, so hide it in access logs."""

    def filter(self, record):
        if isinstance(record.args, tuple):
            record.args = tuple(
                SHARE_TOKEN_PATH.sub(r"\1***", arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True


def install_log_redaction():
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, RedactShareTokenFilter) for item in access_logger.filters):
        access_logger.addFilter(RedactShareTokenFilter())


def log_startup(settings, driver):
    """Important configuration without secrets, to debug deployments."""
    logger.info(
        "Startup: env=%s db=%s cors=%s cloudinary_configured=%s ai=%s",
        settings.environment,
        driver,
        settings.cors_origins,
        all(
            (
                settings.cloudinary_cloud_name,
                settings.cloudinary_api_key,
                settings.cloudinary_api_secret,
            )
        ),
        settings.ai_base_url,
    )
    if settings.environment == "production" and not (
        settings.teacher_email_whitelist_list or settings.teacher_registration_key
    ):
        logger.warning("No teacher whitelist or invite key: nobody can register as teacher.")


def create_app(settings=None, session_factory=None, ai=None, storage=None):
    """Application factory; inject a MongoDB session factory and adapters for integration tests."""
    settings = settings or get_settings()
    database = None
    driver = "injected"
    if session_factory is None:
        database, session_factory = make_mongo_database(settings.mongo_uri)
        driver = "mongodb"

    @asynccontextmanager
    async def lifespan(app):
        log_startup(settings, driver)
        install_log_redaction()
        if settings.admin_email:
            try:
                with session_factory() as db:
                    if AuthService(db, settings).ensure_admin():
                        logger.info("Admin account created for %s", settings.admin_email)
            except Exception:
                # An unreachable database must not stop the API from starting.
                logger.exception("Could not seed the admin account")
        yield
        for room in list(app.state.manager.repo.rooms):
            await app.state.manager.close_room(room)
        if database is not None:
            database.close()

    app = FastAPI(
        title="Face Emotion Backend",
        version=APP_VERSION,
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
    # Chatbot question parser (Gemini); None = rules only. Tests replace it.
    app.state.chat_llm = build_intent_parser(settings)
    install_handlers(app)
    app.add_middleware(RequestLimitsMiddleware, max_json_bytes=settings.max_http_json_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        # PUT/PATCH/DELETE are used by the merged BE A routes (meetings, documents, users).
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    # Outermost, so every response (errors and CORS preflight included) carries the id.
    app.add_middleware(RequestIdMiddleware)
    errors = {
        code: {"model": ErrorEnvelope}
        for code in [400, 401, 403, 404, 409, 413, 415, 422, 429, 500, 502, 503]
    }
    for router in [
        auth_router,
        meetings_router,
        materials_router,
        share_router,
        signaling_router,
        recordings_router,
        analysis_router,
        emotions_router,
        reports_router,
        media_router,
        timeline_router,
        chat_router,
        v1_auth_router,
        users_router,
        emotion_labels_router,
    ]:
        app.include_router(router, responses=errors)

    @app.get("/", tags=["Health"])
    def root():
        return ok({"message": "Hello FastAPI"})

    @app.get("/health", response_model=Envelope[dict[str, str]], tags=["Health"])
    def health():
        """Liveness only; no external service requests."""
        return ok(
            {
                "status": "ok",
                "env": settings.environment,
                "version": APP_VERSION,
                "time": datetime.now(timezone.utc).isoformat(),
            }
        )

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
        return ok({"database": "ok", "driver": driver})

    return app
