from sqlalchemy import pool

from alembic import context
from app import models  # noqa: F401
from app.core.config import get_settings
from app.core.db import Base, make_engine

config = context.config
target_metadata = Base.metadata
url = get_settings().sqlalchemy_url
if context.is_offline_mode():
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
