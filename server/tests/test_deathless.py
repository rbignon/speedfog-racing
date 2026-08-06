"""Deathless race option: plumbing (Task 1) and enforcement (Task 2)."""

from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    ChatMessage,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def dl_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def dl_async_session(dl_async_engine):
    return async_sessionmaker(dl_async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def dl_test_client(dl_async_session):
    async def override_get_db():
        async with dl_async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def dl_organizer(dl_async_session):
    async with dl_async_session() as db:
        user = User(
            twitch_id="org_dl",
            twitch_username="organizer_dl",
            twitch_display_name="Organizer DL",
            api_token="org_dl_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def dl_player(dl_async_session):
    async with dl_async_session() as db:
        user = User(
            twitch_id="player_dl",
            twitch_username="player_dl",
            twitch_display_name="Player DL",
            api_token="player_dl_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _make_seed(db, *, suffix: str, status: SeedStatus = SeedStatus.CONSUMED) -> Seed:
    seed = Seed(
        seed_number=f"dl_{suffix}",
        pool_name="standard",
        graph_json={"total_layers": 5, "nodes": []},
        total_layers=5,
        folder_path=f"/test/dl_{suffix}",
        status=status,
    )
    db.add(seed)
    await db.flush()
    return seed


# ---------------------------------------------------------------------------
# Task 1: option plumbing
# ---------------------------------------------------------------------------


async def test_create_race_deathless_default_false(dl_test_client, dl_async_session, dl_organizer):
    async with dl_async_session() as db:
        await _make_seed(db, suffix="create_def", status=SeedStatus.AVAILABLE)
        await db.commit()

    async with dl_test_client as client:
        resp = await client.post(
            "/api/races",
            json={"name": "Plain race"},
            headers={"Authorization": f"Bearer {dl_organizer.api_token}"},
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["deathless"] is False


async def test_create_race_deathless_true(dl_test_client, dl_async_session, dl_organizer):
    async with dl_async_session() as db:
        await _make_seed(db, suffix="create_on", status=SeedStatus.AVAILABLE)
        await db.commit()

    async with dl_test_client as client:
        resp = await client.post(
            "/api/races",
            json={"name": "Deathless race", "deathless": True},
            headers={"Authorization": f"Bearer {dl_organizer.api_token}"},
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["deathless"] is True


async def test_patch_deathless_setup_toggles_and_broadcasts(
    dl_test_client, dl_async_session, dl_organizer, monkeypatch
):
    from unittest.mock import AsyncMock

    from speedfog_racing.api import races as races_api

    broadcast = AsyncMock()
    monkeypatch.setattr(races_api, "broadcast_race_info_update", broadcast)

    async with dl_async_session() as db:
        seed = await _make_seed(db, suffix="patch_setup")
        race = Race(
            name="Patch deathless",
            organizer_id=dl_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    async with dl_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={"deathless": True},
            headers={"Authorization": f"Bearer {dl_organizer.api_token}"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deathless"] is True
    broadcast.assert_awaited_once()


async def test_patch_deathless_rejected_when_running(
    dl_test_client, dl_async_session, dl_organizer
):
    async with dl_async_session() as db:
        seed = await _make_seed(db, suffix="patch_run")
        race = Race(
            name="Running race",
            organizer_id=dl_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    async with dl_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={"deathless": True},
            headers={"Authorization": f"Bearer {dl_organizer.api_token}"},
        )
    assert resp.status_code == 400
    assert "deathless" in resp.json()["detail"]


async def test_race_info_includes_deathless(dl_async_session, dl_organizer):
    from speedfog_racing.websocket.schemas import build_race_info

    async with dl_async_session() as db:
        seed = await _make_seed(db, suffix="raceinfo")
        race = Race(
            name="Info race",
            organizer_id=dl_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            deathless=True,
        )
        db.add(race)
        await db.commit()
        info = build_race_info(race)

    assert info.deathless is True
    assert '"deathless":true' in info.model_dump_json()


# ---------------------------------------------------------------------------
# Task 2: enforcement
# ---------------------------------------------------------------------------


async def _make_user(db, *, suffix: str) -> User:
    user = User(
        twitch_id=f"u_{suffix}",
        twitch_username=f"user_{suffix}",
        api_token=f"token_{suffix}",
    )
    db.add(user)
    await db.flush()
    return user


async def _make_running_race(
    session_factory,
    *,
    organizer_id,
    players,
    suffix: str,
    deathless: bool = True,
):
    """players: list of (user_id, ParticipantStatus). Returns (race_id, [participant_ids])."""
    async with session_factory() as db:
        seed = await _make_seed(db, suffix=suffix)
        race = Race(
            name=f"Deathless {suffix}",
            organizer_id=organizer_id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC),
            deathless=deathless,
        )
        db.add(race)
        await db.flush()
        participant_ids = []
        for user_id, p_status in players:
            p = Participant(
                race_id=race.id,
                user_id=user_id,
                status=p_status,
                current_zone="node_a",
                zone_history=[{"node_id": "node_a", "igt_ms": 0, "type": "spawn"}],
                igt_ms=60000,
                death_count=1,
            )
            db.add(p)
            await db.flush()
            participant_ids.append(p.id)
        await db.commit()
        return race.id, participant_ids


async def test_deathless_death_eliminates_and_keeps_race_running(
    dl_async_session, dl_organizer, dl_player
):
    from speedfog_racing.websocket.race.mod import handle_deathless_death

    async with dl_async_session() as db:
        other = await _make_user(db, suffix="alive1")
        await db.commit()
        other_id = other.id

    race_id, (p1_id, p2_id) = await _make_running_race(
        dl_async_session,
        organizer_id=dl_organizer.id,
        players=[
            (dl_player.id, ParticipantStatus.PLAYING),
            (other_id, ParticipantStatus.PLAYING),
        ],
        suffix="elim",
    )

    await handle_deathless_death(dl_async_session, p1_id)

    async with dl_async_session() as db:
        p1 = (await db.execute(select(Participant).where(Participant.id == p1_id))).scalar_one()
        p2 = (await db.execute(select(Participant).where(Participant.id == p2_id))).scalar_one()
        race = (await db.execute(select(Race).where(Race.id == race_id))).scalar_one()
        messages = (
            (await db.execute(select(ChatMessage).where(ChatMessage.race_id == race_id)))
            .scalars()
            .all()
        )

    assert p1.status == ParticipantStatus.ABANDONED
    assert p2.status == ParticipantStatus.PLAYING
    assert race.status == RaceStatus.RUNNING
    assert any(m.message == "Player DL died." for m in messages)


async def test_deathless_death_last_alive_finishes_race(dl_async_session, dl_organizer, dl_player):
    from speedfog_racing.websocket.race.mod import handle_deathless_death

    async with dl_async_session() as db:
        other = await _make_user(db, suffix="done1")
        await db.commit()
        other_id = other.id

    race_id, (p1_id, _p2_id) = await _make_running_race(
        dl_async_session,
        organizer_id=dl_organizer.id,
        players=[
            (dl_player.id, ParticipantStatus.PLAYING),
            (other_id, ParticipantStatus.FINISHED),
        ],
        suffix="finish",
    )

    await handle_deathless_death(dl_async_session, p1_id)

    async with dl_async_session() as db:
        race = (await db.execute(select(Race).where(Race.id == race_id))).scalar_one()
        messages = (
            (
                await db.execute(
                    select(ChatMessage)
                    .where(ChatMessage.race_id == race_id)
                    .order_by(ChatMessage.created_at, ChatMessage.id)
                )
            )
            .scalars()
            .all()
        )

    assert race.status == RaceStatus.FINISHED
    died = [m for m in messages if m.message == "Player DL died."]
    finished = [m for m in messages if m.message == "The race has finished."]
    assert len(died) == 1
    assert len(finished) == 1
    assert messages.index(died[0]) < messages.index(finished[0])


async def test_deathless_noop_when_race_not_deathless(dl_async_session, dl_organizer, dl_player):
    from speedfog_racing.websocket.race.mod import handle_deathless_death

    race_id, (p1_id,) = await _make_running_race(
        dl_async_session,
        organizer_id=dl_organizer.id,
        players=[(dl_player.id, ParticipantStatus.PLAYING)],
        suffix="plain",
        deathless=False,
    )

    await handle_deathless_death(dl_async_session, p1_id)

    async with dl_async_session() as db:
        p1 = (await db.execute(select(Participant).where(Participant.id == p1_id))).scalar_one()
        messages = (
            (await db.execute(select(ChatMessage).where(ChatMessage.race_id == race_id)))
            .scalars()
            .all()
        )
    assert p1.status == ParticipantStatus.PLAYING
    assert messages == []


async def test_deathless_noop_when_participant_not_playing(
    dl_async_session, dl_organizer, dl_player
):
    from speedfog_racing.websocket.race.mod import handle_deathless_death

    _race_id, (p1_id,) = await _make_running_race(
        dl_async_session,
        organizer_id=dl_organizer.id,
        players=[(dl_player.id, ParticipantStatus.FINISHED)],
        suffix="notplay",
    )

    await handle_deathless_death(dl_async_session, p1_id)

    async with dl_async_session() as db:
        p1 = (await db.execute(select(Participant).where(Participant.id == p1_id))).scalar_one()
    assert p1.status == ParticipantStatus.FINISHED


async def test_death_delta_triggers_deathless_elimination(
    dl_async_session, dl_organizer, dl_player, monkeypatch
):
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy.orm import selectinload

    from speedfog_racing.websocket.race import mod as race_mod

    elim = AsyncMock()
    monkeypatch.setattr(race_mod, "handle_deathless_death", elim)

    race_id, (p_id,) = await _make_running_race(
        dl_async_session,
        organizer_id=dl_organizer.id,
        players=[(dl_player.id, ParticipantStatus.PLAYING)],
        suffix="wire",
    )
    async with dl_async_session() as db:
        participant = (
            await db.execute(
                select(Participant)
                .where(Participant.id == p_id)
                .options(
                    selectinload(Participant.race).selectinload(Race.seed),
                    selectinload(Participant.race).selectinload(Race.participants),
                )
            )
        ).scalar_one()

    handler = race_mod.RaceModHandler(MagicMock(), race_id, dl_async_session)
    handler._participant_id = p_id

    await handler._broadcast_after_status_update(
        participant, became_active=False, death_delta=1, history_changed=False
    )
    elim.assert_awaited_once_with(dl_async_session, p_id)

    elim.reset_mock()
    await handler._broadcast_after_status_update(
        participant, became_active=False, death_delta=0, history_changed=False
    )
    elim.assert_not_awaited()


async def test_death_delta_no_elimination_on_plain_race(
    dl_async_session, dl_organizer, dl_player, monkeypatch
):
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy.orm import selectinload

    from speedfog_racing.websocket.race import mod as race_mod

    elim = AsyncMock()
    monkeypatch.setattr(race_mod, "handle_deathless_death", elim)

    race_id, (p_id,) = await _make_running_race(
        dl_async_session,
        organizer_id=dl_organizer.id,
        players=[(dl_player.id, ParticipantStatus.PLAYING)],
        suffix="wireplain",
        deathless=False,
    )
    async with dl_async_session() as db:
        participant = (
            await db.execute(
                select(Participant)
                .where(Participant.id == p_id)
                .options(
                    selectinload(Participant.race).selectinload(Race.seed),
                    selectinload(Participant.race).selectinload(Race.participants),
                )
            )
        ).scalar_one()

    handler = race_mod.RaceModHandler(MagicMock(), race_id, dl_async_session)
    handler._participant_id = p_id

    await handler._broadcast_after_status_update(
        participant, became_active=False, death_delta=1, history_changed=False
    )
    elim.assert_not_awaited()


# ---------------------------------------------------------------------------
# Task 4 (daily deathless): elimination parity on Daily Seeds
# ---------------------------------------------------------------------------

DAILY_DATE = date(2026, 8, 5)


async def _make_daily_running_race(
    session_factory,
    *,
    organizer_id,
    players,
    suffix: str,
    started_at=None,
    qualified: bool = False,
):
    """Daily variant of ``_make_running_race``: sets ``daily_date`` plus the
    24h windows the creation loop uses. ``qualified`` controls whether the
    participants' zone_history has crossed the first fog gate (the streak
    qualification predicate needs >= 2 entries)."""
    history = [{"node_id": "node_a", "igt_ms": 0, "type": "spawn"}]
    if qualified:
        history.append({"node_id": "node_b", "igt_ms": 30000, "type": "zone"})
    async with session_factory() as db:
        seed = await _make_seed(db, suffix=suffix)
        race = Race(
            name=f"Daily deathless {suffix}",
            organizer_id=organizer_id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=started_at or datetime.now(UTC),
            deathless=True,
            daily_date=DAILY_DATE,
            late_join_window_minutes=1440,
            race_duration_minutes=1440,
            exclude_from_stats=True,
        )
        db.add(race)
        await db.flush()
        participant_ids = []
        for user_id, p_status in players:
            p = Participant(
                race_id=race.id,
                user_id=user_id,
                status=p_status,
                current_zone="node_a",
                zone_history=list(history),
                igt_ms=60000,
                death_count=1,
            )
            db.add(p)
            await db.flush()
            participant_ids.append(p.id)
        await db.commit()
        return race.id, participant_ids


async def _give_streak(session_factory, user_id, *, current: int = 3, best: int = 5) -> None:
    async with session_factory() as db:
        user = await db.get(User, user_id)
        user.daily_current_streak = current
        user.daily_best_streak = best
        user.daily_freeze_count = 0
        user.daily_last_qualifying_date = DAILY_DATE - timedelta(days=1)
        await db.commit()


async def test_deathless_daily_elimination_breaks_unqualified_streak(
    dl_async_session, dl_organizer, dl_player, monkeypatch
):
    from speedfog_racing.websocket.race.manager import manager
    from speedfog_racing.websocket.race.mod import handle_deathless_death

    unicasts = []

    async def _record_unicast(race_id, user_id, **kwargs):
        unicasts.append((race_id, user_id, kwargs))

    monkeypatch.setattr(manager, "send_daily_streak_update_to_user", _record_unicast)

    await _give_streak(dl_async_session, dl_player.id)
    race_id, (p1_id,) = await _make_daily_running_race(
        dl_async_session,
        organizer_id=dl_organizer.id,
        players=[(dl_player.id, ParticipantStatus.PLAYING)],
        suffix="daily_streak",
    )

    await handle_deathless_death(dl_async_session, p1_id)

    async with dl_async_session() as db:
        p1 = (await db.execute(select(Participant).where(Participant.id == p1_id))).scalar_one()
        user = await db.get(User, dl_player.id)

    assert p1.status == ParticipantStatus.ABANDONED
    assert user.daily_current_streak == 0
    assert user.daily_best_streak == 5
    assert unicasts == [
        (
            race_id,
            dl_player.id,
            {"current": 0, "best": 5, "freeze_count": 0, "freeze_consumed_for": None},
        )
    ]


async def test_deathless_daily_elimination_after_qualification_keeps_streak(
    dl_async_session, dl_organizer, dl_player
):
    from speedfog_racing.websocket.race.mod import handle_deathless_death

    await _give_streak(dl_async_session, dl_player.id)
    _race_id, (p1_id,) = await _make_daily_running_race(
        dl_async_session,
        organizer_id=dl_organizer.id,
        players=[(dl_player.id, ParticipantStatus.PLAYING)],
        suffix="daily_qual",
        qualified=True,
    )

    await handle_deathless_death(dl_async_session, p1_id)

    async with dl_async_session() as db:
        p1 = (await db.execute(select(Participant).where(Participant.id == p1_id))).scalar_one()
        user = await db.get(User, dl_player.id)

    assert p1.status == ParticipantStatus.ABANDONED
    assert user.daily_current_streak == 3


async def test_deathless_daily_elimination_does_not_autofinish_during_window(
    dl_async_session, dl_organizer, dl_player
):
    from speedfog_racing.websocket.race.mod import handle_deathless_death

    race_id, (p1_id,) = await _make_daily_running_race(
        dl_async_session,
        organizer_id=dl_organizer.id,
        players=[(dl_player.id, ParticipantStatus.PLAYING)],
        suffix="daily_window",
    )

    await handle_deathless_death(dl_async_session, p1_id)

    async with dl_async_session() as db:
        race = (await db.execute(select(Race).where(Race.id == race_id))).scalar_one()
        messages = (
            (await db.execute(select(ChatMessage).where(ChatMessage.race_id == race_id)))
            .scalars()
            .all()
        )

    assert race.status == RaceStatus.RUNNING
    assert not any(m.message == "The daily seed is over." for m in messages)
    assert not any(m.message == "The race has finished." for m in messages)


async def test_deathless_daily_elimination_autofinish_uses_daily_wording(
    dl_async_session, dl_organizer, dl_player
):
    from speedfog_racing.websocket.race.mod import handle_deathless_death

    race_id, (p1_id,) = await _make_daily_running_race(
        dl_async_session,
        organizer_id=dl_organizer.id,
        players=[(dl_player.id, ParticipantStatus.PLAYING)],
        suffix="daily_over",
        started_at=datetime.now(UTC) - timedelta(hours=25),
    )

    await handle_deathless_death(dl_async_session, p1_id)

    async with dl_async_session() as db:
        race = (await db.execute(select(Race).where(Race.id == race_id))).scalar_one()
        messages = (
            (await db.execute(select(ChatMessage).where(ChatMessage.race_id == race_id)))
            .scalars()
            .all()
        )

    assert race.status == RaceStatus.FINISHED
    assert any(m.message == "The daily seed is over." for m in messages)
    assert not any(m.message == "The race has finished." for m in messages)
