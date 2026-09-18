import asyncio
import logging

from app import models  # noqa: F401
from app.core.config import get_settings
from app.core.db import make_database
from app.core.mongo import make_mongo_database
from app.integrations.ai import build_ai
from app.integrations.storage import CloudinaryStorage
from app.modules.analysis.service import process_one


async def main():
    settings = get_settings()
    database = None
    engine = None
    if settings.mongo_uri:
        database, factory = make_mongo_database(settings.mongo_uri)
    else:
        engine, factory = make_database(settings.sqlalchemy_url)
    ai, storage = build_ai(settings), CloudinaryStorage(settings)
    try:
        while True:
            try:
                processed = await process_one(factory, ai, storage, settings)
                if not processed:
                    await asyncio.sleep(settings.worker_poll_seconds)
            except Exception:
                logging.exception("Worker polling failed")
                await asyncio.sleep(settings.worker_poll_seconds)
    finally:
        if database is not None:
            database.close()
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
