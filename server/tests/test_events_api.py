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
from speedfog_racing.services.event_service import load_featured_events

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
            "advance": 2,
        },
        {
            "key": "semi_b",
            "label": "Semi B",
            "kind": "semi",
            "date": "2026-10-11T19:00:00Z",
            "races": 3,
            "seeds": [2, 3],
            "advance": 2,
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
        },
    ],
    "rules": ["One sitting per run."],
    "announced_at": "2026-09-16T18:00:00Z",
    "phase_override": "qualifier",
}

QUARTERS_CONFIG = {
    **CONFIG,
    "stages": [
        *(
            {
                "key": key,
                "label": label,
                "kind": "quarter",
                "date": f"2026-10-0{2 + i}T19:00:00Z",
                "races": 3,
                "seeds": seeds,
                "advance": 2,
            }
            for i, (key, label, seeds) in enumerate(
                [
                    ("quarter_a", "Quarter A", [1, 8, 9, 16]),
                    ("quarter_b", "Quarter B", [4, 5, 12, 13]),
                    ("quarter_c", "Quarter C", [2, 7, 10, 15]),
                    ("quarter_d", "Quarter D", [3, 6, 11, 14]),
                ]
            )
        ),
        {
            "key": "semi_a",
            "label": "Semi A",
            "kind": "semi",
            "date": "2026-10-10T19:00:00Z",
            "races": 3,
            "from": ["quarter_a", "quarter_b"],
            "advance": 2,
        },
        {
            "key": "semi_b",
            "label": "Semi B",
            "kind": "semi",
            "date": "2026-10-11T19:00:00Z",
            "races": 3,
            "from": ["quarter_c", "quarter_d"],
            "advance": 2,
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
        },
    ],
    "phase_override": "cut",
}


def _season(base: datetime) -> tuple[datetime, datetime, datetime, dict[str, object]]:
    """A season opening at ``base``: announced a week before, one qualifier week,
    four Sunday-like stages from day 11 to day 32, over on day 34. No phase
    override, so the phase follows the wall clock."""

    def iso(moment: datetime) -> str:
        return moment.isoformat().replace("+00:00", "Z")

    stages = [
        {**stage, "date": iso(base + timedelta(days=11 + 7 * i))}
        for i, stage in enumerate(CONFIG["stages"])
    ]
    config = {
        **CONFIG,
        "stages": stages,
        "announced_at": iso(base - timedelta(days=7)),
        "phase_override": None,
    }
    return base, base + timedelta(days=7), base + timedelta(days=34), config


async def _season_event(db: AsyncSession, slug: str, base: datetime) -> Event:
    starts_at, qualifier_ends_at, ends_at, config = _season(base)
    return await _event(
        db,
        slug,
        starts_at=starts_at,
        qualifier_ends_at=qualifier_ends_at,
        ends_at=ends_at,
        config=config,
    )


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


async def _event(
    db: AsyncSession,
    slug: str = "season-one",
    *,
    starts_at: datetime = T0,
    qualifier_ends_at: datetime | None = None,
    ends_at: datetime = datetime(2026, 10, 26, tzinfo=UTC),
    config: dict[str, object] = CONFIG,
) -> Event:
    event = Event(
        slug=slug,
        name="Season One",
        partner_name="Ignite",
        starts_at=starts_at,
        qualifier_ends_at=qualifier_ends_at or starts_at + timedelta(days=7),
        ends_at=ends_at,
        newcomer_threshold=5,
        config=config,
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
async def test_detail_dates_a_stage_by_its_races_until_the_config_fixes_one(
    test_client, async_session
):
    stages = [dict(s) for s in QUARTERS_CONFIG["stages"]]
    for stage in stages:
        if stage["kind"] in ("quarter", "semi"):
            stage.pop("date")
    config = {**QUARTERS_CONFIG, "stages": stages}
    evening = datetime(2026, 10, 3, 19, tzinfo=UTC)
    async with async_session() as db:
        orga = await _user(db, "orga", UserRole.ORGANIZER)
        event = await _event(db, config=config)
        await _race(
            db,
            orga,
            await _seed(db, "standard", "q1"),
            event,
            "quarter_b:1",
            status=RaceStatus.SETUP,
            is_public=True,
            scheduled_at=evening,
        )
        await db.commit()
    async with test_client as client:
        data = (await client.get("/api/events/season-one")).json()
    stages_out = {s["key"]: s for s in data["stages"]}
    assert stages_out["quarter_a"]["date"] is None
    assert stages_out["quarter_a"]["date_fixed"] is False
    assert datetime.fromisoformat(stages_out["quarter_b"]["date"]) == evening
    assert stages_out["final"]["date_fixed"] is True
    assert stages_out["semi_a"]["from"] == ["quarter_a", "quarter_b"]
    assert stages_out["quarter_a"]["from"] == []
    assert [s["kind"] for s in data["timeline"]] == [
        "announce",
        "open",
        "cut",
        "playoffs",
        "newcomers",
        "final",
    ]


@pytest.mark.asyncio
async def test_detail_seeds_the_quarters_and_names_what_the_later_rounds_wait_on(
    test_client, async_session
):
    async with async_session() as db:
        await _event(db, config=QUARTERS_CONFIG)
        await db.commit()
    async with test_client as client:
        data = (await client.get("/api/events/season-one")).json()
    stages = {s["key"]: s for s in data["stages"]}
    assert [f["label"] for f in stages["quarter_a"]["field"]] == [
        "Seed 1",
        "Seed 8",
        "Seed 9",
        "Seed 16",
    ]
    assert [f["label"] for f in stages["semi_a"]["field"]] == (
        ["Top 2 of Quarter A"] * 2 + ["Top 2 of Quarter B"] * 2
    )
    assert [f["label"] for f in stages["final"]["field"]] == (
        ["Top 2 of Semi A"] * 2 + ["Top 2 of Semi B"] * 2
    )
    assert [g["stage_key"] for g in data["qualified"]["groups"]] == [
        "quarter_a",
        "quarter_b",
        "quarter_c",
        "quarter_d",
        "newcomers",
    ]


async def _ranked_runners(db: AsyncSession, event: Event, count: int, status: RaceStatus):
    """``count`` runners who finished one seed per mode, runner1 fastest."""
    orga = await _user(db, "orga", UserRole.ORGANIZER)
    std = await _race(
        db, orga, await _seed(db, "standard", "s1"), event, "qualifier:standard:1", status
    )
    boss = await _race(
        db, orga, await _seed(db, "boss_rush", "b1"), event, "qualifier:boss_rush:1", status
    )
    for i in range(count):
        runner = await _user(db, f"runner{i + 1}")
        await _entry(db, std, runner, ParticipantStatus.FINISHED, 1_000_000 + i * 100_000)
        await _entry(db, boss, runner, ParticipantStatus.FINISHED, 1_000_000 + i * 100_000)


@pytest.mark.asyncio
async def test_detail_calls_up_the_next_runner_for_a_withdrawn_seed(test_client, async_session):
    async with async_session() as db:
        event = await _event(db, config={**CONFIG, "withdrawn": ["RUNNER2"]})
        await _ranked_runners(db, event, 5, RaceStatus.RUNNING)
        await db.commit()
    async with test_client as client:
        data = (await client.get("/api/events/season-one")).json()
    stages = {s["key"]: s for s in data["stages"]}
    # Semi B seats seeds 2 and 3; runner2 withdrew, so the first runner after
    # the largest seed (4) takes the seat.
    assert [(f["label"], f["user"]["twitch_username"]) for f in stages["semi_b"]["field"]] == [
        ("Seed 5", "runner5"),
        ("Seed 3", "runner3"),
    ]


@pytest.mark.asyncio
async def test_detail_a_withdrawal_from_a_started_stage_calls_nobody_up(test_client, async_session):
    async with async_session() as db:
        event = await _event(db, config={**CONFIG, "withdrawn": ["RUNNER2"]})
        await _ranked_runners(db, event, 5, RaceStatus.RUNNING)
        orga = await _user(db, "orga2", UserRole.ORGANIZER)
        semi_seed = await _seed(db, "standard", "s-semi-b")
        await _race(db, orga, semi_seed, event, "semi_b:1", status=RaceStatus.RUNNING)
        await db.commit()
    async with test_client as client:
        data = (await client.get("/api/events/season-one")).json()
    stages = {s["key"]: s for s in data["stages"]}
    # Semi B (seeds 2 and 3) already has a race under way: runner2 keeps
    # seed 2 instead of being replaced by the withdrawal.
    assert [(f["label"], f["user"]["twitch_username"]) for f in stages["semi_b"]["field"]] == [
        ("Seed 2", "runner2"),
        ("Seed 3", "runner3"),
    ]


@pytest.mark.asyncio
async def test_detail_reads_no_runner_once_the_ladder_is_final(test_client, async_session):
    async with async_session() as db:
        event = await _event(db, config={**CONFIG, "phase_override": "cut"})
        await _ranked_runners(db, event, 3, RaceStatus.FINISHED)
        await db.commit()
    async with test_client as client:
        data = (await client.get("/api/events/season-one")).json()
    stages = {s["key"]: s for s in data["stages"]}
    assert [f["label"] for f in stages["semi_a"]["field"]] == ["Seed 1", "No runner"]


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
    # bob: his boss1 run is still in progress, so it does not score yet and he is unranked
    assert entries["bob"]["mode_points"] == {"standard": 100, "boss_rush": None}
    assert entries["bob"]["modes_scored"] == 1 and entries["bob"]["rank"] is None
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
async def test_my_result_leaves_a_run_in_progress_out_of_the_field(
    test_client, world, async_session
):
    """The viewer's points are computed over the settled runs only, as on the
    ladder: a runner still playing the seed neither ranks nor dilutes them."""
    async with async_session() as db:
        cleo = await _user(db, "cleo")
        await _entry(db, world["std1"], cleo, ParticipantStatus.PLAYING, 500_000, layer=5)
        await db.commit()
    async with test_client as client:
        response = await client.get(
            "/api/events/season-one", headers={"Authorization": "Bearer tok-ana"}
        )
    mine = {r["slot"]: r["my_result"] for r in response.json()["qualifier_races"]}[
        "qualifier:standard:1"
    ]
    # bob finished first, ana second: 2nd of 2 settled runs, not 2nd of 3 (67).
    assert mine["rank"] == 2
    assert mine["points"] == 50


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
        # ana is through while bob still runs: the semi race stays live and scores her.
        await _entry(db, semi_race, ana, ParticipantStatus.FINISHED, 500_000)
        await _entry(db, semi_race, bob, ParticipantStatus.PLAYING, 400_000)
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


SHOWCASE = {"key": "showcase", "label": "Ignite Showcase", "races": 3, "modes": ["Standard"]}


@pytest.mark.asyncio
async def test_a_showcase_scores_like_a_stage_off_the_bracket(test_client, async_session):
    """One showcase race done, one live: points summed, none of the bracket's state."""
    async with async_session() as db:
        orga = await _user(db, "orga", UserRole.ORGANIZER)
        aaron = await _user(db, "aaron")
        ana = await _user(db, "ana")
        bob = await _user(db, "bob")
        cleo = await _user(db, "cleo")
        duel = {"key": "duel", "label": "Duel", "races": 1}
        event = await _event(
            db, config={**CONFIG, "phase_override": "playoffs", "showcases": [SHOWCASE, duel]}
        )
        semi = await _race(
            db,
            orga,
            await _seed(db, "standard", "semi1"),
            event,
            "semi_a:1",
            status=RaceStatus.FINISHED,
            is_public=True,
        )
        await _entry(
            db,
            semi,
            ana,
            ParticipantStatus.FINISHED,
            1_000_000,
            weapons=[{"ids": [9000010], "ticks": 3}],
        )
        first_at = T0 + timedelta(days=9)
        first = await _race(
            db,
            orga,
            await _seed(db, "standard", "show1"),
            event,
            "showcase:1",
            status=RaceStatus.FINISHED,
            is_public=True,
            scheduled_at=first_at,
        )
        # A heavier weapon than the semi's: a showcase run must not become ana's signature.
        await _entry(
            db,
            first,
            ana,
            ParticipantStatus.FINISHED,
            1_000_000,
            weapons=[{"ids": [8030025], "ticks": 99}],
        )
        await _entry(db, first, bob, ParticipantStatus.FINISHED, 1_500_000)
        second = await _race(
            db,
            orga,
            await _seed(db, "standard", "show2"),
            event,
            "showcase:2",
            status=RaceStatus.RUNNING,
            is_public=True,
            scheduled_at=first_at + timedelta(hours=1),
        )
        await _entry(db, second, cleo, ParticipantStatus.PLAYING, 500_000, layer=2)
        await _entry(db, second, bob, ParticipantStatus.PLAYING, 400_000, layer=4)
        # Joins last yet sorts first in the field.
        await _entry(db, second, aaron, ParticipantStatus.PLAYING, 300_000, layer=1)
        # A complete showcase still sends nobody on.
        duel_race = await _race(
            db,
            orga,
            await _seed(db, "standard", "duel1"),
            event,
            "duel:1",
            status=RaceStatus.FINISHED,
            is_public=True,
        )
        await _entry(db, duel_race, ana, ParticipantStatus.FINISHED, 1_000_000)
        await _entry(db, duel_race, bob, ParticipantStatus.FINISHED, 1_500_000)
        await db.commit()

    async with test_client as client:
        data = (await client.get("/api/events/season-one")).json()

    assert [s["key"] for s in data["stages"]] == [s["key"] for s in CONFIG["stages"]]
    assert not any("showcase" in stop["key"] for stop in data["timeline"])
    assert data["live_race"] is None
    assert data["current_stage_key"] is None
    semi_a = next(s for s in data["stages"] if s["key"] == "semi_a")
    assert semi_a["results"][0]["signature_weapon"]["id"] == 9000000

    showcase, duel_result = data["showcases"]
    assert showcase["kind"] == "showcase"
    assert datetime.fromisoformat(showcase["date"]) == first_at
    assert showcase["races_expected"] == 3 and len(showcase["races"]) == 2
    assert showcase["complete"] is False
    # ana won the first race, bob came second; nobody has finished the live race yet,
    # so it lists nobody (cleo and aaron wait in the field) and moves no one.
    assert [(r["user"]["twitch_username"], r["points"]) for r in showcase["results"]] == [
        ("ana", 100),
        ("bob", 70),
    ]
    assert [f["user"]["twitch_username"] for f in showcase["field"]] == [
        "aaron",
        "ana",
        "bob",
        "cleo",
    ]
    assert duel_result["complete"] is True
    assert not any(r["advances"] for r in duel_result["results"])


@pytest.mark.asyncio
async def test_a_showcase_holds_neither_the_season_nor_its_player_count(test_client, async_session):
    now = datetime.now(UTC)
    async with async_session() as db:
        orga = await _user(db, "orga", UserRole.ORGANIZER)
        ana = await _user(db, "ana")
        bob = await _user(db, "bob")
        cleo = await _user(db, "cleo")
        # The final was dated a day ago; the season ends tomorrow.
        starts_at, qualifier_ends_at, ends_at, config = _season(now - timedelta(days=33))
        event = await _event(
            db,
            starts_at=starts_at,
            qualifier_ends_at=qualifier_ends_at,
            ends_at=ends_at,
            config={**config, "showcases": [SHOWCASE]},
        )
        for i in (1, 2, 3):
            seed = await _seed(db, "standard", f"final{i}")
            race = await _race(
                db, orga, seed, event, f"final:{i}", status=RaceStatus.FINISHED, is_public=True
            )
            await _entry(db, race, ana, ParticipantStatus.FINISHED, 1_000_000)
            await _entry(db, race, bob, ParticipantStatus.FINISHED, 1_500_000)
        # Still running, and a runner nothing else in the season knows.
        seed = await _seed(db, "standard", "show1")
        race = await _race(
            db, orga, seed, event, "showcase:1", status=RaceStatus.RUNNING, is_public=True
        )
        await _entry(db, race, cleo, ParticipantStatus.PLAYING, 500_000)
        await db.commit()

    async with test_client as client:
        (summary,) = (await client.get("/api/events")).json()
    assert summary["phase"] == "finished"
    assert summary["champion"]["twitch_username"] == "ana"
    assert summary["live"] is None
    assert summary["players"] == 2
    assert "cleo" not in [u["twitch_username"] for u in summary["player_previews"]]


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
async def test_qualifier_races_stay_off_the_page_until_the_opening(test_client, async_session):
    """An organizer may release a seed before the opening to check it: until
    then the detail names no qualifier race, so nothing leads to that pack."""
    now = datetime.now(UTC)
    async with async_session() as db:
        orga = await _user(db, "orga", UserRole.ORGANIZER)
        soon = await _season_event(db, "soon", now + timedelta(days=1))
        opened = await _season_event(db, "opened", now - timedelta(days=1))
        early = await _race(
            db,
            orga,
            await _seed(db, "standard", "e1"),
            soon,
            "qualifier:standard:1",
            status=RaceStatus.SETUP,
        )
        early.seeds_released_at = now
        live = await _race(
            db,
            orga,
            await _seed(db, "standard", "l1"),
            opened,
            "qualifier:standard:1",
            started_at=now - timedelta(days=1),
        )
        await db.commit()
    async with test_client as client:
        upcoming = await client.get("/api/events/soon")
        running = await client.get("/api/events/opened")
    assert upcoming.json()["phase"] == "upcoming"
    assert upcoming.json()["qualifier_races"] == []
    assert str(early.id) not in upcoming.text
    assert [r["race"]["id"] for r in running.json()["qualifier_races"]] == [str(live.id)]


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


# --- listing ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_listing_runs_from_the_announcement_to_a_week_after_the_end(
    test_client, async_session
):
    now = datetime.now(UTC)
    async with async_session() as db:
        # Announced yesterday, opens in six days: on the bill.
        await _season_event(db, "soon", now + timedelta(days=6))
        # Announced tomorrow: not yet.
        await _season_event(db, "later", now + timedelta(days=8))
        # Over four days ago: still on the bill for a week.
        await _season_event(db, "just-over", now - timedelta(days=38))
        # Over eleven days ago: gone.
        await _season_event(db, "long-over", now - timedelta(days=45))
        await db.commit()

    async with test_client as client:
        response = await client.get("/api/events")
    assert response.status_code == 200
    data = response.json()
    # A finished season yields the bill to one still to come.
    assert [e["slug"] for e in data] == ["soon", "just-over"]
    by_slug = {e["slug"]: e for e in data}
    assert by_slug["soon"]["phase"] == "upcoming"
    assert by_slug["just-over"]["phase"] == "finished"


@pytest.mark.asyncio
async def test_listing_summary_during_the_qualifier(test_client, async_session):
    now = datetime.now(UTC)
    async with async_session() as db:
        orga = await _user(db, "orga", UserRole.ORGANIZER)
        ana = await _user(db, "ana")
        bob = await _user(db, "bob")
        # Sorts first and signed up first, yet previewed last: no run.
        aaa = await _user(db, "aaa")
        event = await _season_event(db, "season-one", now - timedelta(days=1))
        s1 = await _seed(db, "standard", "s1")
        std1 = await _race(db, orga, s1, event, "qualifier:standard:1")
        db.add(EventSignup(event_id=event.id, user_id=aaa.id))
        await _entry(db, std1, ana, ParticipantStatus.PLAYING, 400_000, layer=2)
        await _entry(db, std1, bob, ParticipantStatus.FINISHED, 2_000_000)
        await db.commit()

    async with test_client as client:
        anonymous = (await client.get("/api/events")).json()
        as_aaa = (
            await client.get("/api/events", headers={"Authorization": "Bearer tok-aaa"})
        ).json()

    (summary,) = anonymous
    assert summary["slug"] == "season-one"
    assert summary["name"] == "Season One"
    assert summary["partner_name"] == "Ignite"
    assert summary["phase"] == "qualifier"
    # Two runners on the seed plus one signup, previewed in the share card's
    # order: the ladder first (bob finished, then the signup), then the
    # runners without a settled run (ana is still playing), whatever the join
    # order or the alphabet say.
    assert summary["players"] == 3
    assert [u["twitch_username"] for u in summary["player_previews"]] == ["bob", "aaa", "ana"]
    assert summary["my_signup"] is False
    assert summary["next_stage"]["key"] == "semi_a"
    assert summary["live"] is None
    assert summary["champion"] is None
    assert as_aaa[0]["my_signup"] is True


@pytest.mark.asyncio
async def test_listing_hides_a_young_upcoming_count(test_client, async_session):
    now = datetime.now(UTC)
    async with async_session() as db:
        event = await _season_event(db, "season-one", now + timedelta(days=3))
        for i in range(9):
            runner = await _user(db, f"r{i}")
            db.add(EventSignup(event_id=event.id, user_id=runner.id))
        await db.commit()

    async with test_client as client:
        (summary,) = (await client.get("/api/events")).json()
        assert summary["phase"] == "upcoming"
        # Nine players in: the opening day is the whole message, not the count.
        assert summary["players"] == 0
        assert summary["player_previews"] == []

        async with async_session() as db:
            tenth = await _user(db, "r9")
            db.add(EventSignup(event_id=event.id, user_id=tenth.id))
            await db.commit()

        (summary,) = (await client.get("/api/events")).json()
        assert summary["players"] == 10
        # The stack is capped; the count carries the rest as a "+N" chip.
        assert [u["twitch_username"] for u in summary["player_previews"]] == [
            f"r{i}" for i in range(8)
        ]


@pytest.mark.asyncio
async def test_listing_carries_the_live_playoff_race_and_its_stage(test_client, async_session):
    now = datetime.now(UTC)
    async with async_session() as db:
        orga = await _user(db, "orga", UserRole.ORGANIZER)
        ana = await _user(db, "ana")
        # Semi A was dated yesterday: playoffs, its second race running now.
        event = await _season_event(db, "season-one", now - timedelta(days=12))
        seed = await _seed(db, "standard", "semi2")
        race = await _race(
            db, orga, seed, event, "semi_a:2", status=RaceStatus.RUNNING, is_public=True
        )
        await _entry(db, race, ana, ParticipantStatus.PLAYING, 500_000)
        await db.commit()
        race_id = str(race.id)

    async with test_client as client:
        (summary,) = (await client.get("/api/events")).json()
    assert summary["phase"] == "playoffs"
    assert summary["live"]["race"]["id"] == race_id
    assert summary["live"]["stage_label"] == "Semi A"
    assert summary["live"]["index"] == 2
    assert summary["live"]["races_expected"] == 3
    assert summary["next_stage"]["key"] == "semi_b"


@pytest.mark.asyncio
async def test_listing_crowns_the_champion_once_the_final_is_complete(test_client, async_session):
    now = datetime.now(UTC)
    async with async_session() as db:
        orga = await _user(db, "orga", UserRole.ORGANIZER)
        ana = await _user(db, "ana")
        bob = await _user(db, "bob")
        # The final was dated a day ago; the season ends tomorrow.
        event = await _season_event(db, "season-one", now - timedelta(days=33))
        for i in (1, 2):
            seed = await _seed(db, "standard", f"final{i}")
            race = await _race(
                db, orga, seed, event, f"final:{i}", status=RaceStatus.FINISHED, is_public=True
            )
            await _entry(db, race, ana, ParticipantStatus.FINISHED, 1_000_000)
            await _entry(db, race, bob, ParticipantStatus.FINISHED, 1_500_000)
        await db.commit()

    async with test_client as client:
        (summary,) = (await client.get("/api/events")).json()
        # Two of three final races: the stage is not complete, nobody is crowned.
        assert summary["phase"] == "playoffs"
        assert summary["champion"] is None

        async with async_session() as db:
            seed = await _seed(db, "standard", "final3")
            race = await _race(
                db, orga, seed, event, "final:3", status=RaceStatus.FINISHED, is_public=True
            )
            await _entry(db, race, bob, ParticipantStatus.FINISHED, 1_000_000)
            await _entry(db, race, ana, ParticipantStatus.FINISHED, 1_500_000)
            await db.commit()

        (summary,) = (await client.get("/api/events")).json()
        # The complete final ends the season early; ana took two races out of three.
        assert summary["phase"] == "finished"
        assert summary["champion"]["twitch_username"] == "ana"


@pytest.mark.asyncio
async def test_listing_skips_an_event_whose_config_no_longer_validates(test_client, async_session):
    now = datetime.now(UTC)
    async with async_session() as db:
        await _season_event(db, "sound", now + timedelta(days=3))
        starts_at, qualifier_ends_at, ends_at, _config = _season(now + timedelta(days=3))
        await _event(
            db,
            "broken",
            starts_at=starts_at,
            qualifier_ends_at=qualifier_ends_at,
            ends_at=ends_at,
            config={"modes": [], "stages": [{"key": "x"}]},
        )
        await db.commit()

    async with test_client as client:
        response = await client.get("/api/events")
    assert response.status_code == 200
    assert [e["slug"] for e in response.json()] == ["sound"]


@pytest.mark.asyncio
async def test_featured_loader_leaves_the_seed_graphs_behind(async_session):
    """Every visitor loads the listing: the races' seed graphs must stay in the database."""
    now = datetime.now(UTC)
    async with async_session() as db:
        orga = await _user(db, "orga", UserRole.ORGANIZER)
        event = await _season_event(db, "season-one", now - timedelta(days=1))
        seed = await _seed(db, "standard", "s1")
        await _race(db, orga, seed, event, "qualifier:standard:1")
        await db.commit()

    async with async_session() as db:
        (event,) = await load_featured_events(db, now)
        (race,) = event.races
        assert race.seed.pool_name == "standard"
        assert "graph_json" not in race.seed.__dict__
