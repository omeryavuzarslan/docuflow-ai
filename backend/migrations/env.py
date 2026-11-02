"""Alembic entry point: connects to the database and runs migrations against our models."""

import os

from alembic import context
from sqlalchemy import create_engine

from backend.app.db.models import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = config.get_main_option("sqlalchemy.url") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Set DATABASE_URL (e.g. run with `uv run --env-file .env alembic ...`)")
    return url


def run_migrations_offline() -> None:
    """Write SQL to stdout instead of running it (`alembic upgrade head --sql`)."""
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
