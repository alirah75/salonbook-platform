"""Migration entry point; credentials come exclusively from the environment."""

import os

from sqlalchemy import create_engine, pool
from sqlalchemy.schema import SchemaItem

from alembic import context
from app.db.models import Base

config = context.config
url = os.environ.get("DATABASE_MIGRATION_URL")
if not url:
    raise RuntimeError("Set DATABASE_MIGRATION_URL to the PostgreSQL migration-owner URL.")
if not url.startswith("postgresql+psycopg://"):
    raise RuntimeError("Only postgresql+psycopg:// migration URLs are supported.")


def include_object(
    obj: SchemaItem, name: str | None, type_: str, reflected: bool, compare_to: SchemaItem | None
) -> bool:
    # The hostname view and Alembic version table are migration-owned objects.
    return name != "alembic_version"


if context.is_offline_mode():
    context.configure(
        url=url,
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(url, poolclass=pool.NullPool).connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            compare_type=True,
            compare_server_default=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
