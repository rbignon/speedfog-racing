"""Public event endpoint."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Event,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)

T0 = datetime(2026, 9, 23, 8, tzinfo=UTC)
CONFIG = {
    "modes": [{"key": "standard", "label": "Standard"}, {"key": "boss_rush", "label": "Boss Rush"}],
    "seeds_per_mode": 2,
    "stages": [
        {
            "key": "semi_a",
            "label": "Semi A",
            "kind": "semi",
            "date": "2026-10-04T19:00:00Z",
            "races": 3,
            "seeds": [1, 4],
            "modes": ["Standard", "Boss Rush", "UWYG Major Rush"],
        },
        {
            "key": "semi_b",
            "label": "Semi B",
            "kind": "semi",
            "date": "2026-10-11T19:00:00Z",
            "races": 3,
            "seeds": [2, 3],
        },
        {
            "key": "newcomers",
            "label": "Newcomers",
            "kind": "newcomers",
            "date": "2026-10-18T19:00:00Z",
            "races": 2,
            "size": 2,
        },
        {
            "key": "final",
            "label": "Final",
            "kind": "final",
            "date": "2026-10-25T19:00:00Z",
            "races": 3,
            "from": ["semi_a", "semi_b"],
            "advance": 2,
        },
    ],
    "rules": ["One sitting per run."],
}


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


@pytest.fixture
def test_client(async_session):
    from httpx import ASGITransport, AsyncClient

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


async def _user(db: AsyncSession, name: str, role: UserRole = UserRole.USER) -> User:
    user = User(twitch_id=f"id-{name}", twitch_username=name, api_token=f"tok-{name}", role=role)
    db.add(user)
    await db.flush()
    return user


async def _seed(db: AsyncSession, pool: str, number: str) -> Seed:
    seed = Seed(
        seed_number=number,
        pool_name=pool,
        graph_json={"total_layers": 5, "nodes": []},
        total_layers=5,
        folder_path=f"/seeds/{number}.zip",
        status=SeedStatus.CONSUMED,
    )
    db.add(seed)
    await db.flush()
    return seed


async def _event(db: AsyncSession, slug: str = "season-one") -> Event:
    event = Event(
        slug=slug,
        name="Season One",
        partner_name="Ignite",
        starts_at=T0,
        qualifier_ends_at=T0 + timedelta(days=7),
        ends_at=datetime(2026, 10, 26, tzinfo=UTC),
        newcomer_threshold=5,
        config=CONFIG,
    )
    db.add(event)
    await db.flush()
    return event


async def _race(
    db,
    organizer: User,
    seed: Seed,
    event: Event | None,
    slot: str | None,
    status: RaceStatus = RaceStatus.RUNNING,
    is_public: bool = False,
    started_at: datetime = T0,
    scheduled_at: datetime | None = None,
) -> Race:
    race = Race(
        name=slot or "race",
        organizer_id=organizer.id,
        seed_id=seed.id,
        status=status,
        is_public=is_public,
        open_registration=True,
        started_at=started_at,
        scheduled_at=scheduled_at,
        late_join_window_minutes=10080,
        race_duration_minutes=10080,
        event_id=event.id if event else None,
        event_slot=slot,
        exclude_from_stats=slot is not None and slot.startswith("qualifier:"),
    )
    db.add(race)
    await db.flush()
    return race


async def _entry(
    db,
    race: Race,
    user: User,
    status: ParticipantStatus,
    igt_ms: int,
    layer: int = 4,
    started: bool = True,
):
    # A run scores once it has two zone entries; a registered runner has none yet.
    history = [{"node_id": "a"}, {"node_id": "b"}] if started else []
    db.add(
        Participant(
            race_id=race.id,
            user_id=user.id,
            status=status,
            igt_ms=igt_ms,
            current_layer=layer,
            zone_history=history,
        )
    )


@pytest.fixture
async def world(async_session):
    """An event in its qualifier week with two standard seeds and two boss rush seeds."""
    async with async_session() as db:
        orga = await _user(db, "orga", UserRole.ORGANIZER)
        ana = await _user(db, "ana")
        bob = await _user(db, "bob")
        event = await _event(db)
        s1 = await _seed(db, "standard", "s1")
        s2 = await _seed(db, "standard", "s2")
        b1 = await _seed(db, "boss_rush", "b1")
        b2 = await _seed(db, "boss_rush", "b2")
        std1 = await _race(db, orga, s1, event, "qualifier:standard:1")
        std2 = await _race(db, orga, s2, event, "qualifier:standard:2")
        boss1 = await _race(db, orga, b1, event, "qualifier:boss_rush:1")
        boss2 = await _race(db, orga, b2, event, "qualifier:boss_rush:2")
        await _entry(db, std1, ana, ParticipantStatus.FINISHED, 2_000_000)
        await _entry(db, std1, bob, ParticipantStatus.FINISHED, 1_500_000)
        await _entry(db, std2, ana, ParticipantStatus.FINISHED, 1_000_000)
        await _entry(db, boss1, ana, ParticipantStatus.FINISHED, 3_000_000)
        await _entry(db, boss1, bob, ParticipantStatus.PLAYING, 400_000, layer=2)
        await _entry(db, boss2, bob, ParticipantStatus.REGISTERED, 0, layer=0, started=False)
        await db.commit()
        return {"ana": ana, "bob": bob, "event": event, "std1": std1}


@pytest.mark.asyncio
async def test_unknown_slug_is_404(test_client):
    async with test_client as client:
        assert (await client.get("/api/events/nope")).status_code == 404


@pytest.mark.asyncio
async def test_detail_ladder_is_provisional_during_qualifier(test_client, world):
    async with test_client as client:
        response = await client.get("/api/events/season-one")
    assert response.status_code == 200
    data = response.json()
    assert data["phase"] in ("upcoming", "qualifier", "cut", "playoffs", "finished")  # wall clock
    assert data["ladder_final"] is False
    assert data["ladder"]["provisional"] is True
    entries = {e["user"]["twitch_username"]: e for e in data["ladder"]["entries"]}
    # ana: std1 2nd of 2 (50), std2 1st (100) -> 100; boss1 1st -> 100; total 200, ranked
    assert entries["ana"]["mode_points"] == {"standard": 100, "boss_rush": 100}
    assert entries["ana"]["total"] == 200 and entries["ana"]["rank"] == 1
    # bob: playing on boss1 counts as a DNF score, so he is ranked with a low boss_rush score
    assert entries["bob"]["mode_points"]["standard"] == 100
    assert entries["bob"]["modes_scored"] == 2 and entries["bob"]["rank"] == 2
    assert all(e["newcomer"] is True for e in entries.values())
    assert [r["slot"] for r in data["qualifier_races"]] == [
        "qualifier:standard:1",
        "qualifier:standard:2",
        "qualifier:boss_rush:1",
        "qualifier:boss_rush:2",
    ]
    assert data["qualifier_races"][0]["my_result"] is None
    assert data["qualified"]["provisional"] is True
    groups = {g["stage_key"]: g for g in data["qualified"]["groups"]}
    assert groups["semi_a"]["entries"][0]["user"]["twitch_username"] == "ana"
    assert groups["semi_a"]["entries"][1]["user"] is None
    assert [s["kind"] for s in data["timeline"]] == [
        "announce",
        "open",
        "cut",
        "semi",
        "semi",
        "newcomers",
        "final",
    ]
    assert data["stages"][0]["modes"] == ["Standard", "Boss Rush", "UWYG Major Rush"]


@pytest.mark.asyncio
async def test_my_result_for_signed_in_viewer(test_client, world):
    async with test_client as client:
        response = await client.get(
            "/api/events/season-one", headers={"Authorization": "Bearer tok-bob"}
        )
    data = response.json()
    by_slot = {r["slot"]: r["my_result"] for r in data["qualifier_races"]}
    assert by_slot["qualifier:standard:1"] == {
        "status": "done",
        "rank": 1,
        "igt_ms": 1_500_000,
        "points": 100,
        "provisional": True,
    }
    assert by_slot["qualifier:standard:2"]["status"] == "not_played"
    assert by_slot["qualifier:boss_rush:1"]["status"] == "playing"
    assert by_slot["qualifier:boss_rush:2"]["status"] == "joined"
