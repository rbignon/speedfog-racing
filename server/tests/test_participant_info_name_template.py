"""Tests that ParticipantInfo carries the rewards equip + name_template fields."""

import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["SECRET_KEY"] = "test-secret-key"

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
)
from speedfog_racing.rewards.catalog import NAME_TEMPLATES
from speedfog_racing.websocket.race.manager import participant_to_info


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


async def _setup_participant(async_session, user: User) -> Participant:
    """Create a Race + Seed + Participant for the given user, return the Participant."""
    async with async_session() as db:
        seed = Seed(
            seed_number="test_seed",
            pool_name="standard",
            graph_json={"nodes": {}, "edges": [], "total_nodes": 0},
            total_layers=1,
            folder_path="/fake",
            status=SeedStatus.AVAILABLE,
        )
        db.add(seed)
        await db.flush()

        organizer = User(twitch_id="org", twitch_username="org")
        db.add(organizer)
        await db.flush()

        race = Race(
            name="Test Race",
            organizer_id=organizer.id,
            status=RaceStatus.SETUP,
            is_public=True,
            seed_id=seed.id,
        )
        db.add(race)
        await db.flush()

        # Re-attach user (it was created in another session)
        merged_user = await db.merge(user)

        participant = Participant(
            user_id=merged_user.id,
            race_id=race.id,
            status=ParticipantStatus.REGISTERED,
            current_layer=0,
            igt_ms=0,
            death_count=0,
        )
        db.add(participant)
        await db.commit()
        await db.refresh(participant, attribute_names=["user"])
        return participant


async def test_participant_info_no_template_when_unset(async_session):
    """A user without an equipped template gets name_template=None so the mod
    and web fall back to the status color (preserves functional readability)."""
    async with async_session() as db:
        u = User(twitch_id="t1", twitch_username="alice")
        db.add(u)
        await db.commit()
        await db.refresh(u)
    participant = await _setup_participant(async_session, u)

    info = participant_to_info(participant)
    assert info.name_template is None
    assert info.equipped_badge_id is None
    assert info.equipped_name_template_id is None


async def test_participant_info_no_template_when_default(async_session):
    """The 'default' template id is a sentinel for 'no override'."""
    async with async_session() as db:
        u = User(
            twitch_id="t1b",
            twitch_username="dave",
            equipped_name_template_id="default",
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
    participant = await _setup_participant(async_session, u)

    info = participant_to_info(participant)
    assert info.name_template is None
    assert info.equipped_name_template_id == "default"


async def test_participant_info_carries_gradient_when_equipped(async_session):
    async with async_session() as db:
        u = User(
            twitch_id="t2",
            twitch_username="bob",
            equipped_name_template_id="elo_crown",
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
    participant = await _setup_participant(async_session, u)

    info = participant_to_info(participant)
    assert info.equipped_name_template_id == "elo_crown"
    assert info.name_template is not None
    expected_gradient = NAME_TEMPLATES["elo_crown"].gradient
    assert expected_gradient is not None
    assert info.name_template.gradient == list(expected_gradient)
    assert info.name_template.color is None


async def test_participant_info_carries_equipped_badge_id(async_session):
    async with async_session() as db:
        u = User(
            twitch_id="t3",
            twitch_username="carol",
            equipped_badge_id="contributor",
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
    participant = await _setup_participant(async_session, u)

    info = participant_to_info(participant)
    assert info.equipped_badge_id == "contributor"
