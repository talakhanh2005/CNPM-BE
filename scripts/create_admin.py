"""Provision an admin locally; password is prompted and never put in command arguments."""

import argparse
from getpass import getpass

from app.core.config import get_settings
from app.core.db import make_database
from app.core.mongo import make_mongo_database
from app.core.security import hash_password
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schema import LoginIn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    credentials = LoginIn(email=args.email, password=getpass("Admin password: "))
    if credentials.password != getpass("Confirm password: "):
        raise SystemExit("Passwords do not match")
    settings = get_settings()
    if settings.mongo_uri:
        database, factory = make_mongo_database(settings.mongo_uri)
    else:
        database, factory = make_database(settings.sqlalchemy_url)
    try:
        with factory() as db:
            repo = AuthRepository(db)
            if repo.by_email(credentials.email):
                raise SystemExit("Email already exists; no user was modified")
            repo.add_user(
                email=credentials.email,
                full_name=args.name,
                role="admin",
                password_hash=hash_password(credentials.password, settings.bcrypt_rounds),
            )
            db.commit()
        print("Admin created")
    finally:
        if settings.mongo_uri:
            database.close()
        else:
            database.dispose()


if __name__ == "__main__":
    main()
