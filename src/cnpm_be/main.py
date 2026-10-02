from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cnpm_be.config import Settings, settings
from cnpm_be.database import create_lifespan
from cnpm_be.auth import router as auth_router
from cnpm_be.emotions import router as emotions_router
from cnpm_be.fe_auth import router as classroom_auth_router
from cnpm_be.meetings import router as classroom_meetings_router
from cnpm_be.rooms import router as classroom_rooms_router
from cnpm_be.users import router as users_router


def create_app(config: Settings = settings, database: Any = None) -> FastAPI:
    app = FastAPI(
        title="CNPM Backend API",
        version="0.1.0",
        lifespan=create_lifespan(config, database),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.settings = config
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(emotions_router)
    app.include_router(classroom_auth_router)
    app.include_router(classroom_rooms_router)
    app.include_router(classroom_meetings_router)

    @app.get("/", tags=["health"])
    async def root() -> dict[str, str]:
        return {"message": "Hello FastAPI"}

    return app


app = create_app()