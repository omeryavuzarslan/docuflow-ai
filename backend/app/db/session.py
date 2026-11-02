import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(url: str | None = None) -> Engine:
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Set DATABASE_URL (e.g. run with `uv run --env-file .env ...`)")
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False: objects stay readable after commit, which the worker relies on.
    return sessionmaker(bind=engine, expire_on_commit=False)
