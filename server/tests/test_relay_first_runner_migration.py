"""The migration that gives every relay team with members a first runner."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import RelayTeam, User, UserRole
from tests.relay_fixtures import make_relay_race

pytestmark = pytest.mark.asyncio

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "a4898d1850a8_backfill_relay_first_runners.py"
)


@pytest.fixture
async def fr_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def test_teams_with_members_get_their_earliest_member(fr_session):
    spec = importlib.util.spec_from_file_location("relay_first_runner_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    async with fr_session() as db:
        users = [
            User(twitch_id=f"fr_{i}", twitch_username=f"fr_{i}", api_token=f"fr_t{i}")
            for i in range(5)
        ]
        users[0].role = UserRole.ORGANIZER
        db.add_all(users)
        await db.flush()
        org, a, b, c, d = users
        race = await make_relay_race(db, org, teams=[[a, b], [c, d], []])
        lost, kept, empty = sorted(race.relay_teams, key=lambda t: t.name)
        by_user = {p.user_id: p for p in race.participants}
        # b joined before a: the earliest member is b, not the row listed first.
        by_user[b.id].created_at = datetime(2026, 1, 1, tzinfo=UTC)
        by_user[a.id].created_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=1)
        lost.first_runner_id = None
        kept.first_runner_id = by_user[d.id].id
        await db.commit()

        await db.execute(text(migration.BACKFILL))
        await db.commit()

        rows = await db.execute(select(RelayTeam.name, RelayTeam.first_runner_id))
        firsts = dict(rows.all())
    assert firsts == {
        lost.name: by_user[b.id].id,
        kept.name: by_user[d.id].id,
        empty.name: None,
    }
