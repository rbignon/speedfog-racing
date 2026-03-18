"""Integration tests for stats service and API."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    EloHistory,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.services.stats_service import update_elo_ratings


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def finished_race(async_session):
    """Create a finished race with 3 participants (2 finished, 1 abandoned with igt>0)."""
    async with async_session() as db:
        users = []
        for i in range(3):
            u = User(
                twitch_id=f"u{i}",
                twitch_username=f"player{i}",
                api_token=f"tok{i}",
                role=UserRole.USER,
            )
            users.append(u)
        organizer = User(
            twitch_id="org",
            twitch_username="organizer",
            api_token="tok_org",
            role=UserRole.ORGANIZER,
        )
        db.add_all([*users, organizer])
        await db.flush()

        seed = Seed(
            seed_number="s1",
            pool_name="standard",
            graph_json={"nodes": {}, "total_layers": 5},
            total_layers=5,
            folder_path="/test/s1",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Test Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        participants = [
            Participant(
                race_id=race.id,
                user_id=users[0].id,
                mod_token="mt0",
                status=ParticipantStatus.FINISHED,
                igt_ms=2_000_000,
                death_count=10,
            ),
            Participant(
                race_id=race.id,
                user_id=users[1].id,
                mod_token="mt1",
                status=ParticipantStatus.FINISHED,
                igt_ms=2_800_000,
                death_count=15,
            ),
            Participant(
                race_id=race.id,
                user_id=users[2].id,
                mod_token="mt2",
                status=ParticipantStatus.ABANDONED,
                igt_ms=500_000,
                death_count=5,
            ),
        ]
        db.add_all(participants)
        await db.commit()

        return race.id, [u.id for u in users]


class TestUpdateEloRatings:
    async def test_updates_user_elo_after_race(self, async_session, finished_race):
        race_id, user_ids = finished_race
        async with async_session() as db:
            await update_elo_ratings(race_id, db)

        async with async_session() as db:
            for uid in user_ids:
                user = await db.get(User, uid)
                assert user.elo_races == 1
            winner = await db.get(User, user_ids[0])
            assert winner.elo_rating > 1500.0
            abandoner = await db.get(User, user_ids[2])
            assert abandoner.elo_rating < 1500.0

    async def test_creates_elo_history_entries(self, async_session, finished_race):
        race_id, user_ids = finished_race
        async with async_session() as db:
            await update_elo_ratings(race_id, db)

        async with async_session() as db:
            entries = (await db.execute(select(EloHistory))).scalars().all()
            assert len(entries) == 3

    async def test_idempotent(self, async_session, finished_race):
        race_id, user_ids = finished_race
        async with async_session() as db:
            await update_elo_ratings(race_id, db)
        async with async_session() as db:
            await update_elo_ratings(race_id, db)

        async with async_session() as db:
            entries = (await db.execute(select(EloHistory))).scalars().all()
            assert len(entries) == 3  # Still 3, not 6

    async def test_skips_non_playing_abandoned(self, async_session):
        """Abandoned with igt_ms=0 should be excluded entirely."""
        async with async_session() as db:
            users = [
                User(
                    twitch_id=f"t{i}",
                    twitch_username=f"p{i}",
                    api_token=f"t{i}",
                    role=UserRole.USER,
                )
                for i in range(2)
            ]
            org = User(
                twitch_id="org2", twitch_username="org2", api_token="to2", role=UserRole.ORGANIZER
            )
            db.add_all([*users, org])
            await db.flush()
            seed = Seed(
                seed_number="s2",
                pool_name="standard",
                graph_json={"nodes": {}},
                total_layers=3,
                folder_path="/t/s2",
                status=SeedStatus.CONSUMED,
            )
            db.add(seed)
            await db.flush()
            race = Race(
                name="R2",
                organizer_id=org.id,
                seed_id=seed.id,
                status=RaceStatus.FINISHED,
                started_at=datetime.now(UTC),
            )
            db.add(race)
            await db.flush()
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=users[0].id,
                    mod_token="m0",
                    status=ParticipantStatus.FINISHED,
                    igt_ms=2_000_000,
                    death_count=5,
                )
            )
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=users[1].id,
                    mod_token="m1",
                    status=ParticipantStatus.ABANDONED,
                    igt_ms=0,
                    death_count=0,
                )
            )
            await db.commit()
            rid = race.id
            uid_finished = users[0].id
            uid_abandoned = users[1].id

        async with async_session() as db:
            await update_elo_ratings(rid, db)

        async with async_session() as db:
            finished_user = await db.get(User, uid_finished)
            abandoned_user = await db.get(User, uid_abandoned)
            # Only 1 eligible player, no pairs possible
            assert finished_user.elo_races == 0
            assert abandoned_user.elo_races == 0
