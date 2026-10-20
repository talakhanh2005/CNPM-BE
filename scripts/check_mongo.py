"""Check MongoDB connectivity and create the application's required indexes."""

from pymongo.errors import PyMongoError

from app.core.config import get_settings
from app.core.mongo import MongoDatabase


def main():
    database = MongoDatabase(get_settings().mongo_uri)
    try:
        database.ping()
        print("MongoDB connection and indexes: OK")
    except PyMongoError as exc:
        raise SystemExit(f"MongoDB check failed ({type(exc).__name__})") from None
    finally:
        database.close()


if __name__ == "__main__":
    main()
