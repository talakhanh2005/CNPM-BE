from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from pwdlib import PasswordHash
from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.errors import DuplicateKeyError

from cnpm_be.config import Settings

password_hash = PasswordHash.recommended()


async def initialize_database(database: Any, config: Settings) -> None:
    await database.command("ping")
    await database.users.create_index("email", unique=True)
    await database.emotions.create_index(
        [("user_id", ASCENDING), ("created_at", DESCENDING)]
    )
    await database.accounts.create_index("username_lower", unique=True)
    await database.rooms.create_index("code", unique=True)
    await database.rooms.create_index(
        [("host_id", ASCENDING), ("created_at", DESCENDING)]
    )

    if config.admin_email and config.admin_password:
        existing_admin = await database.users.find_one({"email": config.admin_email.lower()})
        if existing_admin is None:
            try:
                await database.users.insert_one(
                    {
                        "email": config.admin_email.lower(),
                        "password_hash": password_hash.hash(
                            config.admin_password.get_secret_value()
                        ),
                        "role": "admin",
                    }
                )
            except DuplicateKeyError:
                pass


def create_lifespan(config: Settings, injected_database: Any = None):
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if injected_database is not None:
            app.state.database = injected_database
            yield
            return

        client = AsyncMongoClient(config.mongo_uri)
        app.state.client = client
        app.state.database = client[config.mongo_db_name]
        try:
            await initialize_database(app.state.database, config)
            yield
        finally:
            await client.close()

    return lifespan


async def get_database(request: Request) -> Any:
    return request.app.state.database