"""UUID columns must survive SQLite, the tests' stand-in for Postgres.

SQLite picks a column's affinity from its declared type name: a type named
``UUID`` gets NUMERIC affinity, which turns a stored hex string made only of
digits (or digits and one ``e``) into a number that no longer reads back as
a UUID. Roughly one uuid4 in 700,000 is such a string, enough to fail a
random test in one full run out of several.
"""

import uuid

import pytest
from sqlalchemy import Uuid, select
from sqlalchemy.dialects import sqlite
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import User


@pytest.fixture
async def session_maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.parametrize(
    "user_id",
    [
        uuid.UUID("12345678-1234-4234-8234-123456789012"),  # digits only
        uuid.UUID("12345678-1234-4234-8234-1234567890e1"),  # digits and one e
    ],
)
async def test_a_uuid_that_reads_as_a_number_round_trips(session_maker, user_id):
    async with session_maker() as db:
        db.add(User(id=user_id, twitch_id="t", twitch_username="u", api_token="k"))
        await db.commit()
    async with session_maker() as db:
        assert (await db.execute(select(User.id))).scalar_one() == user_id


def test_every_uuid_column_has_text_affinity_on_sqlite():
    # postgresql.UUID and sqlalchemy.UUID both subclass Uuid, so a column
    # declared with either is caught here.
    dialect = sqlite.dialect()
    ddl = {
        f"{table.name}.{column.name}": column.type.compile(dialect=dialect).upper()
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, Uuid)
    }
    assert ddl, "no UUID column found: the filter no longer matches the models"
    numeric = {
        name: sql
        for name, sql in ddl.items()
        if not any(word in sql for word in ("CHAR", "TEXT", "CLOB"))
    }
    assert numeric == {}
