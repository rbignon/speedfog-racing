"""Event rewards: who a bracket rewards, when, and the grant of one block."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    BadgeGrant,
    NameTemplateUnlock,
    ParticipantStatus,
    PhantomSkinUnlock,
    RaceStatus,
    RewardNotification,
    User,
    UserRole,
)
from speedfog_racing.rewards.service import RewardsService
from speedfog_racing.services.event_rewards import (
    RewardBlock,
    RewardRef,
    compute_reward_blocks,
    grant_reason,
    grant_reward_block,
    owned_refs,
)
from speedfog_racing.services.event_service import load_event

from .event_fixtures import rewarded
from .test_events_api import CONFIG, _entry, _event, _race, _ranked_runners, _seed, _user

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)


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


async def _blocks(db: AsyncSession, now: datetime = NOW) -> list[RewardBlock]:
    event = await load_event(db, "season-one")
    assert event is not None
    return await compute_reward_blocks(db, event, now)


async def _block(db: AsyncSession, bracket_key: str, role: str, now: datetime = NOW) -> RewardBlock:
    return next(b for b in await _blocks(db, now) if (b.bracket_key, b.role) == (bracket_key, role))


async def _named(db: AsyncSession, name: str) -> User:
    return (await db.execute(select(User).where(User.twitch_username == name))).scalar_one()


def _names(users: Iterable[User]) -> list[str]:
    return [u.twitch_username for u in users]


async def _notifications(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(RewardNotification))).scalar_one()


@pytest.mark.asyncio
async def test_seated_blocks_follow_the_draw_bracket_by_bracket(async_session):
    async with async_session() as db:
        event = await _event(db, config=rewarded(CONFIG))
        await _ranked_runners(db, event, 7, RaceStatus.FINISHED)
        await db.commit()

    async with async_session() as db:
        blocks = await _blocks(db)
    assert [(b.bracket_key, b.role) for b in blocks] == [
        ("main", "seated"),
        ("main", "champion"),
        ("newcomers", "seated"),
        ("newcomers", "champion"),
    ]
    seated = {b.bracket_key: b for b in blocks if b.role == "seated"}
    assert _names(seated["main"].recipients) == ["runner1", "runner2", "runner3", "runner4"]
    # Nobody had finished a race before the announcement: the next two are newcomers.
    assert _names(seated["newcomers"].recipients) == ["runner5", "runner6"]
    assert seated["main"].waiting is None
    assert seated["newcomers"].waiting is None


@pytest.mark.asyncio
async def test_a_forfeit_is_seated_and_a_withdrawal_is_not(async_session):
    config = rewarded({**CONFIG, "forfeits": ["RUNNER2"], "withdrawn": ["RUNNER3"]})
    async with async_session() as db:
        event = await _event(db, config=config)
        await _ranked_runners(db, event, 7, RaceStatus.FINISHED)
        await db.commit()

    async with async_session() as db:
        blocks = await _blocks(db)
    seated = next(b for b in blocks if (b.bracket_key, b.role) == ("main", "seated"))
    assert "runner2" in _names(seated.recipients)
    assert "runner3" not in _names(seated.recipients)
    assert all("runner3" not in _names(b.recipients) for b in blocks)


@pytest.mark.asyncio
async def test_seated_waits_on_a_provisional_ladder(async_session):
    async with async_session() as db:
        event = await _event(db, config=rewarded(CONFIG))
        await _ranked_runners(db, event, 7, RaceStatus.RUNNING)
        await db.commit()

    async with async_session() as db:
        seated = await _block(db, "main", "seated")
    assert seated.waiting == "ladder_provisional"
    assert seated.recipients == []


@pytest.mark.asyncio
async def test_seated_waits_on_the_draw_lock(async_session):
    async with async_session() as db:
        event = await _event(
            db, config=rewarded({**CONFIG, "draw_locks_at": "2026-10-27T00:00:00Z"})
        )
        await _ranked_runners(db, event, 7, RaceStatus.FINISHED)
        await db.commit()

    async with async_session() as db:
        before = await _block(db, "main", "seated")
        after = await _block(db, "main", "seated", now=datetime(2026, 10, 28, tzinfo=UTC))
    assert before.waiting == "draw_not_locked"
    assert before.recipients == []
    assert after.waiting is None
    assert _names(after.recipients) == ["runner1", "runner2", "runner3", "runner4"]


@pytest.mark.asyncio
async def test_champion_waits_for_the_closing_stage_then_names_its_winner(async_session):
    async with async_session() as db:
        orga = await _user(db, "orga", UserRole.ORGANIZER)
        ana = await _user(db, "ana")
        bob = await _user(db, "bob")
        event = await _event(db, config=rewarded(CONFIG))
        for i in (1, 2):
            race = await _race(
                db,
                orga,
                await _seed(db, "standard", f"final{i}"),
                event,
                f"final:{i}",
                RaceStatus.FINISHED,
            )
            await _entry(db, race, ana, ParticipantStatus.FINISHED, 1_000_000)
            await _entry(db, race, bob, ParticipantStatus.FINISHED, 1_500_000)
        await db.commit()

    async with async_session() as db:
        champion = await _block(db, "main", "champion")
    # Two of three final races: nobody is crowned yet.
    assert champion.waiting == "stage_incomplete"
    assert champion.recipients == []

    async with async_session() as db:
        race = await _race(
            db, orga, await _seed(db, "standard", "final3"), event, "final:3", RaceStatus.FINISHED
        )
        await _entry(db, race, bob, ParticipantStatus.FINISHED, 1_000_000)
        await _entry(db, race, ana, ParticipantStatus.FINISHED, 1_500_000)
        await db.commit()

    async with async_session() as db:
        champion = await _block(db, "main", "champion")
    # ana took two races out of three.
    assert champion.waiting is None
    assert _names(champion.recipients) == ["ana"]


@pytest.mark.asyncio
async def test_a_bracket_without_a_final_crowns_its_last_stage(async_session):
    config = {k: v for k, v in CONFIG.items() if k != "stages"}
    config["brackets"] = [
        {
            "key": "main",
            "label": "Playoffs",
            "entry": "all",
            "stages": [
                {"key": "semi", "label": "Semi", "kind": "semi", "races": 1, "seeds": [1, 2]}
            ],
            "rewards": {"champion": {"phantom_skins": ["violet-aura"]}},
        }
    ]
    async with async_session() as db:
        orga = await _user(db, "orga", UserRole.ORGANIZER)
        ana = await _user(db, "ana")
        bob = await _user(db, "bob")
        event = await _event(db, config=config)
        race = await _race(
            db, orga, await _seed(db, "standard", "semi1"), event, "semi:1", RaceStatus.FINISHED
        )
        await _entry(db, race, bob, ParticipantStatus.FINISHED, 1_000_000)
        await _entry(db, race, ana, ParticipantStatus.FINISHED, 1_500_000)
        await db.commit()

    async with async_session() as db:
        champion = await _block(db, "main", "champion")
    assert champion.waiting is None
    assert _names(champion.recipients) == ["bob"]


@pytest.mark.asyncio
async def test_a_banned_runner_is_skipped(async_session):
    async with async_session() as db:
        event = await _event(db, config=rewarded(CONFIG))
        await _ranked_runners(db, event, 7, RaceStatus.FINISHED)
        (await _named(db, "runner1")).banned_at = NOW
        await db.commit()

    async with async_session() as db:
        seated = await _block(db, "main", "seated")
    # A ban does not unseat: nobody moves up into runner1's seat.
    assert _names(seated.banned) == ["runner1"]
    assert _names(seated.recipients) == ["runner2", "runner3", "runner4"]


@pytest.mark.asyncio
async def test_a_block_without_rewards_is_not_listed(async_session):
    config = rewarded(CONFIG)
    config["brackets"][0]["rewards"]["seated"] = {"badges": []}
    config["brackets"][1]["rewards"] = {"champion": {"phantom_skins": ["violet-aura"]}}
    async with async_session() as db:
        event = await _event(db, config=config)
        await _ranked_runners(db, event, 7, RaceStatus.FINISHED)
        await db.commit()

    async with async_session() as db:
        blocks = await _blocks(db)
    assert [(b.bracket_key, b.role) for b in blocks] == [
        ("main", "champion"),
        ("newcomers", "champion"),
    ]


@pytest.mark.asyncio
async def test_an_unknown_id_is_kept_apart(async_session):
    # Stored as is, past the admin save's catalog check: a template retired since.
    config = rewarded(CONFIG)
    config["brackets"][0]["rewards"]["seated"] = {
        "name_templates": ["retired_template", "season_one_qualifier"]
    }
    async with async_session() as db:
        admin = await _user(db, "admin", UserRole.ADMIN)
        event = await _event(db, config=config)
        await _ranked_runners(db, event, 7, RaceStatus.FINISHED)
        await db.commit()

    async with async_session() as db:
        seated = await _block(db, "main", "seated")
        assert [r.ref for r in seated.unknown] == ["name_template:retired_template"]
        assert [r.ref for r in seated.rewards] == ["name_template:season_one_qualifier"]
        # The grant skips the unknown id instead of failing the whole block.
        assert await grant_reward_block(db, "Season One", seated, admin.id) == 4


@pytest.mark.asyncio
async def test_grant_unlocks_once_with_its_reason_and_notifies(async_session):
    async with async_session() as db:
        admin = await _user(db, "admin", UserRole.ADMIN)
        event = await _event(db, config=rewarded(CONFIG))
        await _ranked_runners(db, event, 7, RaceStatus.FINISHED)
        await db.commit()

    async with async_session() as db:
        seated = await _block(db, "main", "seated")
        assert await grant_reward_block(db, "Season One", seated, admin.id) == 4
        await db.commit()

    async with async_session() as db:
        rows = (
            await db.execute(
                select(User.twitch_username, NameTemplateUnlock)
                .join(User, User.id == NameTemplateUnlock.user_id)
                .order_by(User.twitch_username)
            )
        ).all()
        assert [name for name, _ in rows] == ["runner1", "runner2", "runner3", "runner4"]
        for _, unlock in rows:
            assert unlock.template_id == "season_one_qualifier"
            assert unlock.granted_by == admin.id
            assert unlock.reason == "Season One: Playoffs qualifier"
        assert await _notifications(db) == 4

    # A second click finds every recipient already owning it.
    async with async_session() as db:
        seated = await _block(db, "main", "seated")
        assert await grant_reward_block(db, "Season One", seated, admin.id) == 0
        await db.commit()
        assert await _notifications(db) == 4


@pytest.mark.asyncio
async def test_granting_one_block_leaves_the_others_alone(async_session):
    async with async_session() as db:
        admin = await _user(db, "admin", UserRole.ADMIN)
        event = await _event(db, config=rewarded(CONFIG))
        await _ranked_runners(db, event, 7, RaceStatus.FINISHED)
        await db.commit()

    async with async_session() as db:
        seated = await _block(db, "main", "seated")
        await grant_reward_block(db, "Season One", seated, admin.id)
        # The organizer takes runner1's Kindled back.
        await RewardsService(db).revoke_name_template(
            (await _named(db, "runner1")).id, "season_one_qualifier"
        )
        await db.commit()

    async with async_session() as db:
        orga = await _named(db, "orga")
        runner5, runner6 = await _named(db, "runner5"), await _named(db, "runner6")
        for i in (1, 2):
            race = await _race(
                db,
                orga,
                await _seed(db, "standard", f"newcomers{i}"),
                event,
                f"newcomers:{i}",
                RaceStatus.FINISHED,
            )
            await _entry(db, race, runner5, ParticipantStatus.FINISHED, 1_000_000)
            await _entry(db, race, runner6, ParticipantStatus.FINISHED, 1_500_000)
        await db.commit()

    async with async_session() as db:
        champion = await _block(db, "newcomers", "champion")
        assert _names(champion.recipients) == ["runner5"]
        assert await grant_reward_block(db, "Season One", champion, admin.id) == 1
        await db.commit()
        runner1 = await _named(db, "runner1")
        kindled = await db.execute(
            select(NameTemplateUnlock).where(
                NameTemplateUnlock.user_id == runner1.id,
                NameTemplateUnlock.template_id == "season_one_qualifier",
            )
        )
        assert kindled.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_owned_refs_reads_each_reward_kind(async_session):
    async with async_session() as db:
        user = await _user(db, "ana")
        idle = await _user(db, "bob")
        stranger = await _user(db, "cid")
        db.add_all(
            [
                BadgeGrant(user_id=user.id, badge_id="season_one_champion"),
                BadgeGrant(user_id=user.id, badge_id="contributor", revoked_at=NOW),
                NameTemplateUnlock(user_id=user.id, template_id="season_one_qualifier"),
                PhantomSkinUnlock(user_id=user.id, skin_id="violet-aura"),
                PhantomSkinUnlock(user_id=stranger.id, skin_id="violet-aura"),
            ]
        )
        await db.commit()

    refs = [
        RewardRef("badge", "season_one_champion"),
        RewardRef("badge", "contributor"),
        RewardRef("name_template", "season_one_qualifier"),
        RewardRef("name_template", "season_one_champion"),
        RewardRef("phantom_skin", "violet-aura"),
    ]
    async with async_session() as db:
        owned = await owned_refs(db, [user.id, idle.id], refs)
    assert owned[user.id] == {
        "badge:season_one_champion",
        "name_template:season_one_qualifier",
        "phantom_skin:violet-aura",
    }
    assert owned.get(idle.id, set()) == set()
    assert stranger.id not in owned


def test_grant_reason_fits_the_column():
    block = RewardBlock(
        bracket_key="main",
        bracket_label="Playoffs",
        role="champion",
        rewards=[],
        unknown=[],
        waiting=None,
        recipients=[],
        banned=[],
    )
    assert len(grant_reason("x" * 200, block)) == 200
