"""Run after installation: python scripts/check_sqlserver.py (does not mutate data)."""

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.db import make_engine


def main():
    settings = get_settings()
    if settings.sqlalchemy_url.get_backend_name() != "mssql":
        raise SystemExit("Expected SQL Server. Remove DATABASE_URL and use SQLSERVER_* in .env.")
    try:
        import pyodbc
    except ImportError:
        raise SystemExit(
            "ODBC runtime is missing. Install Microsoft ODBC Driver 18 (and unixODBC on Linux)."
        ) from None

    drivers = pyodbc.drivers()
    if settings.sqlserver_driver not in drivers:
        raise SystemExit(
            "Missing ODBC driver: "
            + settings.sqlserver_driver
            + ". Installed: "
            + ", ".join(drivers)
        )
    engine = make_engine(settings.sqlalchemy_url)
    try:
        with engine.connect() as connection:
            info = connection.execute(
                text("SELECT DB_NAME(), CAST(SERVERPROPERTY('ProductVersion') AS NVARCHAR(128))")
            ).one()
            print(f"Connected to database {info[0]}; SQL Server version {info[1]}")
            exists = connection.scalar(
                text(
                    "SELECT COUNT(*) FROM sys.tables WHERE name='alembic_version' AND schema_id=SCHEMA_ID('dbo')"
                )
            )
            print(
                "Migration: "
                + str(connection.scalar(text("SELECT version_num FROM dbo.alembic_version")))
                if exists
                else "Migration: not applied; run alembic upgrade head"
            )
    except SQLAlchemyError as exc:
        # Do not print an ODBC URL containing credentials.
        raise SystemExit(
            "SQL Server connection/query failed ("
            + type(exc).__name__
            + "). Check instance, authentication, database permissions and certificate settings in docs/RUN-AND-TEST.md."
        ) from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
