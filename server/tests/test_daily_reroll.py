"""HTTP tests for the seed reroll behavior on running Daily Seeds.

Regular races still only allow reroll while in SETUP. Dailies, by
contrast, may be rerolled while RUNNING by an admin to recover from a
bad seed; that path resets every participant's progress and broadcasts
an explicit invalidation message in the public chat.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    ChatChannel,
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


@pytest.fixture
async def dr_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def dr_async_session_maker(dr_async_engine):
    return async_sessionmaker(dr_async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def dr_test_client(dr_async_session_maker):
    from httpx import ASGITransport, AsyncClient

    from speedfog_racing.database import get_db
    from speedfog_racing.main import app

    async def override_get_db():
        async with dr_async_session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


async def _make_admin(session_maker) -> str:
    async with session_maker() as db:
        admin = User(
            twitch_id=f"admin-{uuid4().hex[:6]}",
            twitch_username=f"admin_{uuid4().hex[:6]}",
            twitch_display_name="Admin",
            api_token=f"tok-admin-{uuid4().hex[:8]}",
            role=UserRole.ADMIN,
        )
        db.add(admin)
        await db.commit()
        return admin.api_token


async def _make_seed(db: AsyncSession, *, suffix: str) -> Seed:
    seed = Seed(
        seed_number=f"seed-{suffix}",
        pool_name="standard",
        graph_json={"nodes": {}, "total_layers": 5},
        total_layers=5,
        folder_path=f"/test/seed-{suffix}",
        status=SeedStatus.CONSUMED,
    )
    db.add(seed)
    await db.flush()
    return seed


async def _running_regular_race(session_maker) -> Race:
    async with session_maker() as db:
        organizer = User(
            twitch_id=f"org-{uuid4().hex[:6]}",
            twitch_username=f"org_{uuid4().hex[:6]}",
            api_token=f"tok-org-{uuid4().hex[:8]}",
            role=UserRole.ORGANIZER,
        )
        db.add(organizer)
        await db.flush()
        seed = await _make_seed(db, suffix="reg")
        # An extra available seed so reroll has something to swap to.
        await _make_seed(db, suffix="reg-spare")
        spare = (
            await db.execute(select(Seed).where(Seed.seed_number == "seed-reg-spare"))
        ).scalar_one()
        spare.status = SeedStatus.AVAILABLE

        race = Race(
            name="Regular Running",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            is_public=True,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.commit()
        await db.refresh(race)
        return race


async def _running_daily_with_progress(session_maker) -> Race:
    started = datetime.now(UTC) - timedelta(hours=1)
    async with session_maker() as db:
        sys_user = User(
            twitch_id="sys-dr",
            twitch_username="sys_dr",
            twitch_display_name="System",
            api_token=None,
            role=UserRole.SYSTEM,
        )
        player = User(
            twitch_id=f"player-{uuid4().hex[:6]}",
            twitch_username=f"player_{uuid4().hex[:6]}",
            api_token=f"tok-player-{uuid4().hex[:8]}",
            role=UserRole.USER,
        )
        db.add_all([sys_user, player])
        await db.flush()
        seed = await _make_seed(db, suffix="daily")
        # Spare available seed so reroll has somewhere to land.
        await _make_seed(db, suffix="daily-spare")
        spare = (
            await db.execute(select(Seed).where(Seed.seed_number == "seed-daily-spare"))
        ).scalar_one()
        spare.status = SeedStatus.AVAILABLE

        race = Race(
            name=f"Daily Seed - {started.date().isoformat()}",
            organizer_id=sys_user.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            is_public=True,
            open_registration=True,
            daily_date=started.date(),
            exclude_from_stats=True,
            started_at=started,
            seeds_released_at=started,
            late_join_window_minutes=1440,
            race_duration_minutes=1440,
        )
        db.add(race)
        await db.flush()

        db.add(
            Participant(
                race_id=race.id,
                user_id=player.id,
                mod_token=f"mt-{uuid4().hex[:6]}",
                status=ParticipantStatus.PLAYING,
                igt_ms=720_000,
                death_count=2,
                current_layer=2,
                current_zone="zone_a",
                zone_history=[{"zone": "zone_a", "at_ms": 0}],
            )
        )
        await db.commit()
        await db.refresh(race)
        return race


@pytest.mark.asyncio
async def test_running_regular_race_reroll_still_forbidden(
    dr_test_client, dr_async_session_maker
) -> None:
    race = await _running_regular_race(dr_async_session_maker)
    admin_token = await _make_admin(dr_async_session_maker)
    response = await dr_test_client.post(
        f"/api/races/{race.id}/reroll-seed",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_running_daily_reroll_resets_participants_and_releases_seed(
    dr_test_client, dr_async_session_maker
) -> None:
    race = await _running_daily_with_progress(dr_async_session_maker)
    admin_token = await _make_admin(dr_async_session_maker)

    response = await dr_test_client.post(
        f"/api/races/{race.id}/reroll-seed",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"report_buggy": True, "report_reason": "Crash on launch"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["seeds_released_at"] is not None
    assert all(p["status"] == "registered" for p in body["participants"])

    async with dr_async_session_maker() as db:
        participant = (
            await db.execute(select(Participant).where(Participant.race_id == race.id))
        ).scalar_one()
        assert participant.status == ParticipantStatus.REGISTERED
        assert participant.current_zone is None
        assert participant.current_layer == 0
        assert participant.igt_ms == 0
        assert participant.death_count == 0
        assert participant.finished_at is None
        assert participant.zone_history is None

        # The reroll message lives on the participants channel, which the
        # daily page surfaces to every participant row (including those just
        # reset by the reroll). The public channel stays empty.
        participants_messages = (
            (
                await db.execute(
                    select(ChatMessage).where(
                        ChatMessage.race_id == race.id,
                        ChatMessage.channel == ChatChannel.PARTICIPANTS,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert any("rerolled" in m.message.lower() for m in participants_messages)
        public_messages = (
            (
                await db.execute(
                    select(ChatMessage).where(
                        ChatMessage.race_id == race.id,
                        ChatMessage.channel == ChatChannel.PUBLIC,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert public_messages == []


@pytest.mark.asyncio
async def test_running_daily_reroll_notifies_mod_of_new_seed_id(
    dr_test_client, dr_async_session_maker
) -> None:
    """A connected mod must receive a race_info_update carrying the new seed_id
    so its overlay can flag the now-stale loaded seed pack."""
    import json
    from unittest.mock import AsyncMock

    from speedfog_racing.websocket.race.manager import ModConnection, manager

    race = await _running_daily_with_progress(dr_async_session_maker)
    admin_token = await _make_admin(dr_async_session_maker)
    old_seed_id = race.seed_id

    async with dr_async_session_maker() as db:
        participant = (
            await db.execute(select(Participant).where(Participant.race_id == race.id))
        ).scalar_one()

    mod_ws = AsyncMock()
    room = manager.get_or_create_room(race.id)
    room.mods[participant.id] = ModConnection(
        websocket=mod_ws,
        participant_id=participant.id,
        user_id=participant.user_id,
    )
    try:
        response = await dr_test_client.post(
            f"/api/races/{race.id}/reroll-seed",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200, response.text

        async with dr_async_session_maker() as db:
            new_seed_id = (
                await db.execute(select(Race.seed_id).where(Race.id == race.id))
            ).scalar_one()
        assert new_seed_id != old_seed_id  # sanity: the reroll changed the seed

        sent = [json.loads(c.args[0]) for c in mod_ws.send_text.call_args_list]
        race_info_updates = [m for m in sent if m.get("type") == "race_info_update"]
        assert race_info_updates, (
            f"mod received no race_info_update; got types {[m.get('type') for m in sent]}"
        )
        assert race_info_updates[-1]["race"]["seed_id"] == str(new_seed_id)
    finally:
        manager.rooms.pop(race.id, None)
