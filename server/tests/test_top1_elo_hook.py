"""The top1_elo badge holders are refreshed after every race ELO recalc."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from speedfog_racing.database import Base
from speedfog_racing.models import (
    BadgeGrant,
    NameTemplateUnlock,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.services.race_lifecycle import check_race_auto_finish
from speedfog_racing.services.stats_service import PROVISIONAL_THRESHOLD


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


async def test_check_race_auto_finish_refreshes_top1_elo(async_session):
    """A race finishing rebalances top1_elo holders against the new ELO state."""
    async with async_session() as db:
        # Two established players: A starts higher.
        user_a = User(
            twitch_id="ua",
            twitch_username="alice",
            api_token="ta",
            role=UserRole.USER,
            elo_rating=1700.0,
            elo_races=PROVISIONAL_THRESHOLD,
        )
        user_b = User(
            twitch_id="ub",
            twitch_username="bob",
            api_token="tb",
            role=UserRole.USER,
            elo_rating=1500.0,
            elo_races=PROVISIONAL_THRESHOLD,
        )
        organizer = User(
            twitch_id="org",
            twitch_username="org",
            api_token="torg",
            role=UserRole.ORGANIZER,
        )
        db.add_all([user_a, user_b, organizer])
        await db.flush()

        seed = Seed(
            seed_number="s1",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
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
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        # B finishes faster (lower igt_ms) and should gain ELO.
        p_a = Participant(
            race_id=race.id,
            user_id=user_a.id,
            status=ParticipantStatus.FINISHED,
            igt_ms=600000,
            finished_at=datetime.now(UTC),
        )
        p_b = Participant(
            race_id=race.id,
            user_id=user_b.id,
            status=ParticipantStatus.FINISHED,
            igt_ms=300000,
            finished_at=datetime.now(UTC),
        )
        db.add_all([p_a, p_b])
        await db.commit()

        # Re-fetch with eager-loaded participants for the lifecycle helper.
        result = await db.execute(
            select(Race).where(Race.id == race.id).options(selectinload(Race.participants))
        )
        loaded_race = result.scalar_one()
        ok = await check_race_auto_finish(db, loaded_race)
        assert ok is True

    # In a fresh session, verify the badge state.
    async with async_session() as db:
        # Whoever has the highest ELO now should be the top1 holder.
        users = (
            (await db.execute(select(User).where(User.elo_races >= PROVISIONAL_THRESHOLD)))
            .scalars()
            .all()
        )
        max_elo = max(u.elo_rating for u in users)
        expected_holders = {u.id for u in users if u.elo_rating == max_elo}

        active_grants = (
            (
                await db.execute(
                    select(BadgeGrant.user_id).where(
                        BadgeGrant.badge_id == "top1_elo",
                        BadgeGrant.revoked_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert set(active_grants) == expected_holders

        # And the holder(s) also got the elo_crown name template (permanent).
        unlocks = (
            (
                await db.execute(
                    select(NameTemplateUnlock.user_id).where(
                        NameTemplateUnlock.template_id == "elo_crown"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert set(unlocks) == expected_holders
