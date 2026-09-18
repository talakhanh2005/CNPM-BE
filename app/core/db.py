from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import DateTime, TypeDecorator


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """UTC timestamps: SQL Server DATETIMEOFFSET, normalized SQLite in unit tests."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("Naive datetime is not accepted")
            return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is not None:
            return (
                value.replace(tzinfo=timezone.utc)
                if value.tzinfo is None
                else value.astimezone(timezone.utc)
            )


def now():
    return datetime.now(timezone.utc)


def new_id():
    return str(uuid4())


def make_engine(url, **kwargs):
    """Shared SQL Server engine configuration for API, worker, tools and Alembic."""
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        options = {"check_same_thread": False, "timeout": 30}
    elif parsed.drivername == "mssql+pyodbc":
        import pyodbc

        # Let SQLAlchemy own pooling so disposal really closes test connections.
        pyodbc.pooling = False
        options = {"timeout": 15}
    else:
        raise ValueError("Unsupported database driver; use SQL Server mssql+pyodbc")
    engine = create_engine(parsed, connect_args=options, pool_pre_ping=True, **kwargs)
    if parsed.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def pragmas(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")

    return engine


def make_database(url):
    engine = make_engine(url)
    return engine, sessionmaker(engine, expire_on_commit=False)


def lock_row(statement, model, db):
    """SQL Server ignores FOR UPDATE: use update locks held until transaction end."""
    if db.get_bind().dialect.name == "mssql":
        return statement.with_hint(model, "WITH (UPDLOCK, ROWLOCK)", dialect_name="mssql")
    return statement.with_for_update()


def compare_and_swap(db, statement, primary_key):
    """Use OUTPUT INSERTED/RETURNING, never pyodbc rowcount, to detect a CAS winner."""
    result = db.execute(
        statement.returning(primary_key).execution_options(synchronize_session=False)
    )
    return result.scalar_one_or_none() is not None
