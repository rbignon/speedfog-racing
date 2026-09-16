"""Public event endpoint."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Event,
    EventSignup,
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
    "announced_at": "2026-09-16T18:00:00Z",
    "phase_override": "qualifier",
}


def _expected_next_stage_key() -> str | None:
    """The key of the first configured stage dated after the real wall clock.

    Mirrors the endpoint's own selection so the assertion stays correct
    whenever this suite runs, rather than pinning it to today's date.
    """
    now = datetime.now(UTC)
    for stage in CONFIG["stages"]:
        if datetime.fromisoformat(stage["date"]) > now:
            return stage["key"]
    return None


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
    weapons: list[dict[str, object]] | None = None,
):
    # A run scores once it has two zone entries; a registered runner has none yet.
    history: list[dict[str, object]] = [{"node_id": "a"}, {"node_id": "b"}] if started else []
    if weapons and history:
        history[0]["weapons"] = weapons
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
    assert data["phase"] == "qualifier"
    assert data["current_stage_key"] is None
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
        "finished": True,
        "rank": 1,
        "igt_ms": 1_500_000,
        "points": 100,
        "provisional": True,
    }
    assert by_slot["qualifier:standard:2"]["status"] == "not_played"
    assert by_slot["qualifier:boss_rush:1"]["status"] == "playing"
    assert by_slot["qualifier:boss_rush:2"]["status"] == "joined"


@pytest.mark.asyncio
async def test_my_result_marks_an_abandoned_run_as_unfinished_but_scored(
    test_client, world, async_session
):
    """An abandon is ``done`` with ``finished`` false: it keeps a rank and points
    below the finishers (the page labels it DNF) rather than reading as a finish."""
    async with async_session() as db:
        std2 = (
            await db.execute(select(Race).where(Race.event_slot == "qualifier:standard:2"))
        ).scalar_one()
        await _entry(db, std2, world["bob"], ParticipantStatus.ABANDONED, 900_000, layer=3)
        await db.commit()
    async with test_client as client:
        response = await client.get(
            "/api/events/season-one", headers={"Authorization": "Bearer tok-bob"}
        )
    mine = {r["slot"]: r["my_result"] for r in response.json()["qualifier_races"]}[
        "qualifier:standard:2"
    ]
    assert mine["status"] == "done"
    assert mine["finished"] is False
    # ana finished this seed; bob's abandon ranks after her, still scoring.
    assert mine["rank"] == 2
    assert mine["points"] == 50  # two scored runs: 100 to ana, half to the abandon


@pytest.mark.asyncio
async def test_detail_final_ladder_excludes_bogus_slot_and_shows_live_stage_race(
    test_client, async_session
):
    """All qualifiers finished (final ladder), a bogus slot, and a live semi race."""
    async with async_session() as db:
        orga = await _user(db, "orga", UserRole.ORGANIZER)
        ana = await _user(db, "ana")
        bob = await _user(db, "bob")
        event = await _event(db)
        s1 = await _seed(db, "standard", "s1")
        s2 = await _seed(db, "standard", "s2")
        b1 = await _seed(db, "boss_rush", "b1")
        b2 = await _seed(db, "boss_rush", "b2")
        stray_seed = await _seed(db, "standard", "stray")
        semi_seed = await _seed(db, "standard", "semi1")

        std1 = await _race(db, orga, s1, event, "qualifier:standard:1", status=RaceStatus.FINISHED)
        std2 = await _race(db, orga, s2, event, "qualifier:standard:2", status=RaceStatus.FINISHED)
        boss1 = await _race(
            db, orga, b1, event, "qualifier:boss_rush:1", status=RaceStatus.FINISHED
        )
        await _race(db, orga, b2, event, "qualifier:boss_rush:2", status=RaceStatus.FINISHED)
        await _entry(
            db,
            std1,
            ana,
            ParticipantStatus.FINISHED,
            2_000_000,
            weapons=[{"ids": [9000010], "ticks": 3}],
        )
        await _entry(db, std1, bob, ParticipantStatus.FINISHED, 1_500_000)
        await _entry(db, std2, ana, ParticipantStatus.FINISHED, 1_000_000)
        await _entry(db, boss1, ana, ParticipantStatus.FINISHED, 3_000_000)
        await _entry(db, boss1, bob, ParticipantStatus.FINISHED, 2_500_000)

        # A race attached under a slot key the config no longer recognizes: must be
        # dropped entirely, not surfaced as a live race or counted anywhere.
        bogus = await _race(db, orga, stray_seed, event, "nonsense", status=RaceStatus.RUNNING)
        semi_race = await _race(
            db, orga, semi_seed, event, "semi_a:1", status=RaceStatus.RUNNING, is_public=True
        )
        # The bogus race's heavier weapon must not reach ana's signature weapon.
        await _entry(
            db,
            bogus,
            ana,
            ParticipantStatus.FINISHED,
            1_000,
            weapons=[{"ids": [8030025], "ticks": 99}],
        )
        await _entry(db, semi_race, ana, ParticipantStatus.PLAYING, 500_000)
        await db.commit()
        bogus_id, semi_race_id = str(bogus.id), str(semi_race.id)

    async with test_client as client:
        response = await client.get("/api/events/season-one")
    assert response.status_code == 200
    data = response.json()

    assert data["ladder_final"] is True
    assert data["ladder"]["provisional"] is False
    assert data["qualified"]["provisional"] is False
    assert bogus_id not in json.dumps(data)
    assert data["live_race"] is not None
    assert data["live_race"]["id"] == semi_race_id
    semi = next(s for s in data["stages"] if s["key"] == "semi_a")
    assert semi["results"][0]["user"]["twitch_username"] == "ana"
    # The base id of the Uchigatana carried on std1, normalised from its runtime id.
    assert semi["results"][0]["signature_weapon"]["id"] == 9000000

    expected_next = _expected_next_stage_key()
    if expected_next is None:
        assert data["next_stage"] is None
    else:
        assert data["next_stage"]["key"] == expected_next


@pytest.mark.asyncio
async def test_qualifier_races_are_hidden_from_listings(test_client, world, async_session):
    """Even a public qualifier seed stays off the feeds; a public stage race is listed."""
    recent = datetime.now(UTC) - timedelta(hours=1)
    async with async_session() as db:
        await _user(db, "cara")
        orga = await _user(db, "orga2", UserRole.ORGANIZER)
        other = await _event(db, "cup")
        stage = await _race(
            db,
            orga,
            await _seed(db, "standard", "pub1"),
            world["event"],
            "semi_a:1",
            is_public=True,
            started_at=recent,
            scheduled_at=recent,
        )
        qualifier = await _race(
            db,
            orga,
            await _seed(db, "standard", "pub2"),
            other,
            "qualifier:standard:1",
            is_public=True,
            started_at=recent,
            scheduled_at=recent,
        )
        await db.commit()
    headers = {"Authorization": "Bearer tok-cara"}
    async with test_client as client:
        listed = (await client.get("/api/races?status=running", headers=headers)).json()
        joinable = (await client.get("/api/races/joinable", headers=headers)).json()
    listed_ids = {r["id"] for r in listed["races"]}
    joinable_ids = {r["id"] for r in joinable["races"]}
    assert str(stage.id) in listed_ids and str(stage.id) in joinable_ids
    assert str(qualifier.id) not in listed_ids and str(qualifier.id) not in joinable_ids
    assert str(world["std1"].id) not in listed_ids


@pytest.mark.asyncio
async def test_qualifier_races_stay_in_admin_inflight(test_client, world, async_session):
    """The admin list is the only surface with the slot control: an attached
    seed must remain reachable there so a broken one can be detached."""
    async with async_session() as db:
        await _user(db, "root", UserRole.ADMIN)
        await db.commit()
    headers = {"Authorization": "Bearer tok-root"}
    async with test_client as client:
        response = await client.get("/api/admin/races", headers=headers)
    assert response.status_code == 200
    assert str(world["std1"].id) in {r["id"] for r in response.json()["races"]}


@pytest.mark.asyncio
async def test_signing_up_lists_the_runner_last_without_a_score(test_client, world, async_session):
    async with async_session() as db:
        await _user(db, "cleo")
        await db.commit()
    headers = {"Authorization": "Bearer tok-cleo"}
    async with test_client as client:
        first = await client.post("/api/events/season-one/signup", headers=headers)
        assert first.status_code == 204
        # Twice is still once.
        second = await client.post("/api/events/season-one/signup", headers=headers)
        assert second.status_code == 204
        detail = (await client.get("/api/events/season-one", headers=headers)).json()
    assert detail["my_signup"] is True
    ladder = detail["ladder"]
    assert ladder["entered"] == 2
    assert ladder["signed_up"] == 1
    names = [e["user"]["twitch_username"] for e in ladder["entries"]]
    assert len(names) == 3 and names[-1] == "cleo"
    last = ladder["entries"][-1]
    assert last["rank"] is None
    assert last["total"] is None
    assert last["modes_scored"] == 0
    assert last["mode_points"] == {"standard": None, "boss_rush": None}
    assert last["newcomer"] is True


@pytest.mark.asyncio
async def test_withdrawing_removes_the_row_and_nothing_else(test_client, world, async_session):
    async with async_session() as db:
        cleo = await _user(db, "cleo")
        db.add(EventSignup(event_id=world["event"].id, user_id=cleo.id))
        db.add(EventSignup(event_id=world["event"].id, user_id=world["ana"].id))
        await db.commit()
    cleo_h = {"Authorization": "Bearer tok-cleo"}
    ana_h = {"Authorization": "Bearer tok-ana"}
    async with test_client as client:
        first = await client.delete("/api/events/season-one/signup", headers=cleo_h)
        assert first.status_code == 204
        # Nothing left to remove is not an error.
        second = await client.delete("/api/events/season-one/signup", headers=cleo_h)
        assert second.status_code == 204
        third = await client.delete("/api/events/season-one/signup", headers=ana_h)
        assert third.status_code == 204
        detail = (await client.get("/api/events/season-one", headers=ana_h)).json()
    names = [e["user"]["twitch_username"] for e in detail["ladder"]["entries"]]
    assert "cleo" not in names
    assert "ana" in names  # her runs keep her on the ladder
    assert detail["my_signup"] is False
    assert detail["ladder"]["signed_up"] == 0


@pytest.mark.asyncio
async def test_signing_up_needs_a_signed_in_runner(test_client, world):
    async with test_client as client:
        assert (await client.post("/api/events/season-one/signup")).status_code == 401
        assert (await client.delete("/api/events/season-one/signup")).status_code == 401
        response = await client.post(
            "/api/events/no-such-event/signup", headers={"Authorization": "Bearer tok-ana"}
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_signups_close_with_the_qualifier(test_client, world, async_session):
    async with async_session() as db:
        cleo = await _user(db, "cleo")
        event = await db.get(Event, world["event"].id)
        assert event is not None
        db.add(EventSignup(event_id=event.id, user_id=cleo.id))
        event.config = {**CONFIG, "phase_override": "cut"}
        await db.commit()
    cleo_h = {"Authorization": "Bearer tok-cleo"}
    async with test_client as client:
        post = await client.post(
            "/api/events/season-one/signup", headers={"Authorization": "Bearer tok-bob"}
        )
        assert post.status_code == 400
        withdraw = await client.delete("/api/events/season-one/signup", headers=cleo_h)
        assert withdraw.status_code == 400
        detail = (await client.get("/api/events/season-one", headers=cleo_h)).json()
    assert detail["phase"] == "cut"
    assert "cleo" not in [e["user"]["twitch_username"] for e in detail["ladder"]["entries"]]
    assert detail["ladder"]["signed_up"] == 0
    # The row itself stays; it just no longer lists anyone.
    assert detail["my_signup"] is True


@pytest.mark.asyncio
async def test_newcomer_cut_is_the_announcement(test_client, world, async_session):
    """Runs between the announcement and the opening do not cost newcomer status:
    what a player had finished when they learnt of the event is what counts."""
    announced = datetime.fromisoformat(CONFIG["announced_at"])
    async with async_session() as db:
        orga = await _user(db, "orga3", UserRole.ORGANIZER)
        dan = await _user(db, "dan")
        eve = await _user(db, "eve")
        for user, first_start in (
            (dan, announced + timedelta(days=1)),
            (eve, announced - timedelta(days=6)),
        ):
            for i in range(5):
                race = await _race(
                    db,
                    orga,
                    await _seed(db, "standard", f"{user.twitch_username}{i}"),
                    None,
                    None,
                    status=RaceStatus.FINISHED,
                    started_at=first_start + timedelta(hours=i),
                )
                await _entry(db, race, user, ParticipantStatus.FINISHED, 1_000_000)
        await _entry(db, world["std1"], dan, ParticipantStatus.FINISHED, 2_500_000)
        await _entry(db, world["std1"], eve, ParticipantStatus.FINISHED, 2_600_000)
        await db.commit()
    async with test_client as client:
        data = (await client.get("/api/events/season-one")).json()
    entries = {e["user"]["twitch_username"]: e for e in data["ladder"]["entries"]}
    assert entries["dan"]["newcomer"] is True
    assert entries["eve"]["newcomer"] is False
