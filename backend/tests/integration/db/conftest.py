"""Database tests run against a real Postgres (`docker compose up -d db`), in a separate
`docuflow_test` database. They are skipped, not failed, when it is not running.

Once per test session the schema is rebuilt through the Alembic migrations (down to empty,
then up to head), so the migrations themselves are tested. Each test then runs inside a
transaction that is rolled back, so tests never see each other's data.
"""

import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://docuflow:docuflow@localhost:5433/docuflow_test"
)


def alembic_config(url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    except OperationalError:
        pytest.skip("test database not reachable; run `docker compose up -d db`")
    config = alembic_config(TEST_DATABASE_URL)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    connection = engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


@pytest.fixture
def session_factory(connection: Connection) -> sessionmaker[Session]:
    # Commits inside the code under test become savepoints, so the rollback in
    # `connection` still undoes everything.
    return sessionmaker(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
