"""speedrun.fog service: which runs count, ranking, record history, weapons."""

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.config import settings
from speedfog_racing.database import Base
from speedfog_racing.models import (
    Event,
    Participant,
    ParticipantStatus,
    Pool,
    Race,
    RaceStatus,
    RunMode,
    Seed,
    SeedStatus,
    TrainingSession,
    TrainingSessionStatus,
    User,
    UserRole,
)
from speedfog_racing.schemas import UserResponse
from speedfog_racing.services.speedrun_service import (
    RUN_TYPES,
    CountedRun,
    build_board,
    build_overview,
    filter_board,
    load_categories,
    load_counted_runs,
    load_main_weapons,
    load_unranked_runs,
    main_weapon,
    place_of,
    race_counts_on_boards,
    rank_board,
    record_history,
    record_seed,
)

BASE = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
# An existing file: a seed whose ``folder_path`` points here keeps its files
# (not purged), so its runs stay on the Set Seed boards.
SEED_ZIP = str(Path(__file__).parent / "fixtures" / "seed_zip_stub")


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
async def pools(async_session):
    async with async_session() as db:
        db.add_all(
            [
                Pool(
                    name="sprint",
                    config={"name": "Sprint", "type": "race", "sort_order": 20, "layers_count": 15},
                ),
                Pool(name="training_sprint", config={"name": "Sprint", "type": "training"}),
                Pool(
                    name="retired",
                    enabled=False,
                    config={"name": "Retired", "type": "race", "sort_order": 5},
                ),
            ]
        )
        await db.commit()


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None)


async def _user(db: AsyncSession, name: str, *, banned: bool = False) -> User:
    user = User(
        twitch_id=f"id-{name}",
        twitch_username=name,
        api_token=f"tok-{name}",
        role=UserRole.USER,
        banned_at=BASE if banned else None,
    )
    db.add(user)
    await db.flush()
    return user


async def _event(db: AsyncSession) -> Event:
    event = Event(
        slug=f"ev-{uuid.uuid4().hex[:8]}",
        name="Event",
        starts_at=BASE,
        qualifier_ends_at=BASE + timedelta(days=7),
        ends_at=BASE + timedelta(days=30),
    )
    db.add(event)
    await db.flush()
    return event


async def _add_run(
    db: AsyncSession,
    *,
    user: User,
    igt_ms: int,
    minute: int,
    pool: str = "sprint",
    deathless: bool = False,
    kind: str = "race",
    race_status: RaceStatus = RaceStatus.FINISHED,
    status: ParticipantStatus = ParticipantStatus.FINISHED,
    zone_history: list[dict[str, Any]] | None = None,
    finished: bool = True,
    layers: int = 15,
    mode: RunMode = RunMode.SPEEDRUN,
    seed: Seed | None = None,
    seed_was_seen: bool = False,
    seed_played: bool = False,
    rerolled_without_report: bool = False,
) -> Participant:
    """One race with a single participant, on ``seed`` or on its own seed."""
    tag = uuid.uuid4().hex[:10]
    if seed is None:
        seed = Seed(
            seed_number=f"seed{tag}",
            pool_name=pool,
            graph_json={"nodes": {}},
            total_layers=layers,
            folder_path=SEED_ZIP,
            status=SeedStatus.CONSUMED,
            created_at=BASE + timedelta(minutes=minute - 60),
        )
        db.add(seed)
        await db.flush()
    race = Race(
        name=f"Race {tag}",
        organizer_id=user.id,
        seed_id=seed.id,
        status=race_status,
        started_at=BASE + timedelta(minutes=minute - 30),
        deathless=deathless,
        mode=mode,
        seed_was_seen=seed_was_seen,
        seed_played=seed_played,
        rerolled_without_report=rerolled_without_report,
        exclude_from_stats=kind in ("daily", "event"),
        # daily_date is unique: one Daily Seed per day.
        daily_date=date(2026, 10, 1) + timedelta(days=minute) if kind == "daily" else None,
        event_id=(await _event(db)).id if kind == "event" else None,
    )
    db.add(race)
    await db.flush()
    participant = Participant(
        race_id=race.id,
        user_id=user.id,
        mod_token=f"mt-{tag}",
        status=status,
        igt_ms=igt_ms,
        death_count=1,
        finished_at=BASE + timedelta(minutes=minute) if finished else None,
        zone_history=zone_history,
    )
    db.add(participant)
    await db.flush()
    return participant


async def _add_session(
    db: AsyncSession,
    user: User,
    seed_pool: str,
    mode: RunMode,
    igt_ms: int,
    *,
    status: TrainingSessionStatus = TrainingSessionStatus.FINISHED,
    finished_at: datetime | None = BASE,
    layers: int = 15,
    zone_history: list[dict[str, Any]] | None = None,
    seed: Seed | None = None,
) -> TrainingSession:
    """One solo session, on ``seed`` or on its own seed."""
    tag = uuid.uuid4().hex[:10]
    if seed is None:
        seed = Seed(
            seed_number=f"seed{tag}",
            pool_name=seed_pool,
            graph_json={"nodes": {}},
            total_layers=layers,
            folder_path=SEED_ZIP,
            status=SeedStatus.CONSUMED,
            created_at=BASE - timedelta(hours=1),
        )
        db.add(seed)
        await db.flush()
    session = TrainingSession(
        user_id=user.id,
        seed_id=seed.id,
        mode=mode,
        status=status,
        igt_ms=igt_ms,
        death_count=2,
        finished_at=finished_at,
        zone_history=zone_history,
    )
    db.add(session)
    await db.flush()
    return session


def _uid(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, name)


def _run(
    name: str,
    igt_ms: int,
    minute: int,
    *,
    pool: str = "sprint",
    deathless: bool = False,
    blind: bool = True,
    seed: str = "abc",
) -> CountedRun:
    return CountedRun(
        run_id=uuid.uuid4(),
        user=UserResponse(
            id=_uid(name),
            twitch_username=name,
            twitch_display_name=None,
            twitch_avatar_url=None,
        ),
        pool=pool,
        category=pool,
        deathless=deathless,
        run_type="race",
        blind=blind,
        igt_ms=igt_ms,
        finished_at=BASE + timedelta(minutes=minute),
        race_id=uuid.uuid4(),
        race_name="R",
        session_id=None,
        daily_date=None,
        seed_number=seed,
        deaths=0,
        seed_excluded=False,
        seed_files_block=None,
    )


async def test_load_counted_runs_inclusion_rules(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        banned = await _user(db, "banned", banned=True)
        race_p = await _add_run(db, user=a, igt_ms=1000, minute=1)
        daily_p = await _add_run(db, user=a, igt_ms=1100, minute=2, kind="daily")
        event_p = await _add_run(db, user=a, igt_ms=1200, minute=3, kind="event")
        await _add_run(db, user=banned, igt_ms=900, minute=4)
        await _add_run(db, user=a, igt_ms=800, minute=5, status=ParticipantStatus.DISQUALIFIED)
        await _add_run(db, user=a, igt_ms=800, minute=6, status=ParticipantStatus.ABANDONED)
        await _add_run(
            db, user=a, igt_ms=800, minute=7, kind="daily", race_status=RaceStatus.RUNNING
        )
        await _add_run(db, user=a, igt_ms=800, minute=9, pool="training_sprint")
        await db.commit()

        runs = await load_counted_runs(db)

    assert sorted(r.run_type for r in runs) == ["daily", "event", "race"]
    assert {r.run_id for r in runs} == {race_p.id, daily_p.id, event_p.id}


async def test_races_count_unless_on_a_seen_seed_or_a_reset_or_rerolled_community_race(
    async_session, pools
):
    """Every mode counts, community races included. A seed SEEN when drawn
    keeps any race off the boards; a reset keeps only a community race off
    (an event race's reset is the admins' call, a Set Seed race is a replay
    anyway), and so does a reroll without a report (the admins reroll Daily
    Seeds and event races). The Python rule, the SQL clause and the seed
    page's unranked list agree: every finished run is either counted or
    unranked."""
    async with async_session() as db:
        a = await _user(db, "a")
        normal = await _add_run(db, user=a, igt_ms=1000, minute=1, mode=RunMode.NORMAL)
        speedrun = await _add_run(db, user=a, igt_ms=1100, minute=2, mode=RunMode.SPEEDRUN)
        set_seed = await _add_run(db, user=a, igt_ms=1200, minute=3, mode=RunMode.SET_SEED)
        daily = await _add_run(db, user=a, igt_ms=1300, minute=4, kind="daily", mode=RunMode.NORMAL)
        event = await _add_run(db, user=a, igt_ms=1400, minute=5, kind="event", mode=RunMode.NORMAL)
        seen = await _add_run(
            db, user=a, igt_ms=1500, minute=6, mode=RunMode.NORMAL, seed_was_seen=True
        )
        seen_event = await _add_run(
            db, user=a, igt_ms=1600, minute=7, kind="event", mode=RunMode.NORMAL, seed_was_seen=True
        )
        reset = await _add_run(
            db, user=a, igt_ms=1700, minute=8, mode=RunMode.NORMAL, seed_played=True
        )
        reset_event = await _add_run(
            db, user=a, igt_ms=1800, minute=9, kind="event", mode=RunMode.NORMAL, seed_played=True
        )
        reset_set_seed = await _add_run(
            db, user=a, igt_ms=1900, minute=10, mode=RunMode.SET_SEED, seed_played=True
        )
        reset_daily = await _add_run(
            db, user=a, igt_ms=2000, minute=11, kind="daily", mode=RunMode.NORMAL, seed_played=True
        )
        rerolled = await _add_run(
            db, user=a, igt_ms=2100, minute=12, mode=RunMode.NORMAL, rerolled_without_report=True
        )
        rerolled_speedrun = await _add_run(
            db, user=a, igt_ms=2200, minute=13, mode=RunMode.SPEEDRUN, rerolled_without_report=True
        )
        rerolled_event = await _add_run(
            db,
            user=a,
            igt_ms=2300,
            minute=14,
            kind="event",
            mode=RunMode.NORMAL,
            rerolled_without_report=True,
        )
        rerolled_daily = await _add_run(
            db,
            user=a,
            igt_ms=2400,
            minute=15,
            kind="daily",
            mode=RunMode.NORMAL,
            rerolled_without_report=True,
        )
        await db.commit()
        everyone = [
            normal,
            speedrun,
            set_seed,
            daily,
            event,
            seen,
            seen_event,
            reset,
            reset_event,
            reset_set_seed,
            reset_daily,
            rerolled,
            rerolled_speedrun,
            rerolled_event,
            rerolled_daily,
        ]
        races: dict[uuid.UUID, Race] = {}
        for p in everyone:
            race = await db.get(Race, p.race_id)
            assert race is not None
            races[p.id] = race

        runs = await load_counted_runs(db)
        unranked = {
            run.run_id
            for race in races.values()
            for run in await load_unranked_runs(db, race.seed_id)
        }

    by_id = {r.run_id: r for r in runs}
    counted = {normal.id, speedrun.id, set_seed.id, daily.id, event.id, reset_event.id}
    counted |= {reset_set_seed.id, reset_daily.id, rerolled_event.id, rerolled_daily.id}
    assert set(by_id) == counted
    assert unranked == {seen.id, seen_event.id, reset.id, rerolled.id, rerolled_speedrun.id}
    assert {run_id for run_id, race in races.items() if race_counts_on_boards(race)} == counted
    assert {r.blind for r in runs if r.run_id in (set_seed.id, reset_set_seed.id)} == {False}
    assert {r.blind for r in runs if r.run_id not in (set_seed.id, reset_set_seed.id)} == {True}


async def test_speedrun_race_excluded_from_stats_still_counts(async_session, pools):
    """A community race created in speedrun mode carries ``exclude_from_stats``
    (it stays out of the site's other stats), yet its runs are on the boards."""
    async with async_session() as db:
        a = await _user(db, "a")
        speedrun = await _add_run(db, user=a, igt_ms=1000, minute=1, mode=RunMode.SPEEDRUN)
        race = await db.get(Race, speedrun.race_id)
        assert race is not None
        race.exclude_from_stats = True
        await db.commit()

        runs = await load_counted_runs(db)

    assert [(r.run_id, r.blind) for r in runs] == [(speedrun.id, True)]


async def test_finished_at_falls_back_to_race_start(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        await _add_run(db, user=a, igt_ms=1000, minute=40, finished=False)
        await db.commit()

        runs = await load_counted_runs(db)

    assert _naive(runs[0].finished_at) == _naive(BASE + timedelta(minutes=10))


def test_rank_board_best_per_player_and_shared_rank():
    runs = [
        _run("A", 1000, 1),
        _run("A", 1200, 2),
        _run("B", 1100, 3),
        _run("C", 1100, 4),
        _run("D", 1300, 5),
    ]

    ranked = rank_board(runs, include_obsolete=False)
    assert [(r.user.twitch_username, r.igt_ms, rank) for r, rank in ranked] == [
        ("A", 1000, 1),
        ("B", 1100, 2),
        ("C", 1100, 2),
        ("D", 1300, 4),
    ]
    assert [rank for _, rank in rank_board(runs, include_obsolete=True)] == [1, 2, 2, None, 4]


def test_rank_board_same_player_equal_igt_keeps_earliest():
    runs = [_run("A", 1000, 9), _run("A", 1000, 2)]

    ranked = rank_board(runs, include_obsolete=True)

    assert [(r.finished_at.minute, rank) for r, rank in ranked] == [(2, 1), (9, None)]
    assert len(rank_board(runs, include_obsolete=False)) == 1


def test_record_history_keeps_strict_improvements_in_date_order():
    runs = [_run("D", 1400, 4), _run("B", 1600, 2), _run("A", 1500, 1), _run("C", 1400, 3)]

    assert [r.user.twitch_username for r in record_history(runs)] == ["A", "C"]


def test_place_of_counts_other_players_strictly_faster():
    board = [_run("A", 1000, 1), _run("B", 1200, 2), _run("C", 1300, 3), _run("A", 1250, 4)]

    assert place_of(board[1], board) == 2
    assert place_of(board[3], board) == 2
    assert place_of(_run("E", 1000, 5), board) == 1


def test_main_weapon_picks_most_ticks_normalized():
    history: list[dict[str, Any]] = [
        {
            "node_id": "a",
            "weapons": [
                {"ids": [2000025], "ticks": 4},
                {"ids": [3000000, 2000100], "ticks": 3},
            ],
        },
        {
            "node_id": "b",
            "weapons": [{"ids": [2000000], "ticks": 2}, {"ids": "bad", "ticks": 9}],
        },
    ]

    assert main_weapon(history) == [2000000]
    assert main_weapon([{"node_id": "a"}]) is None
    assert main_weapon(None) is None


async def test_categories_order(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        await _add_run(db, user=a, igt_ms=1000, minute=1, pool="sprint")
        await _add_run(db, user=a, igt_ms=1000, minute=2, pool="sprint", deathless=True)
        await _add_run(db, user=a, igt_ms=1000, minute=3, pool="standard")
        await _add_run(db, user=a, igt_ms=1000, minute=4, pool="retired", deathless=True)
        await db.commit()

        cats = await load_categories(db, await load_counted_runs(db))

    assert [(c.pool, c.name, c.retired) for c in cats] == [
        ("sprint", "Sprint", False),
        ("standard", "Standard", False),
        ("retired", "Retired", True),
    ]


async def test_build_board_filters_types_and_attaches_weapons(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        b = await _user(db, "b")
        history = [{"node_id": "z", "weapons": [{"ids": [2000025], "ticks": 5}]}]
        await _add_run(db, user=a, igt_ms=1000, minute=1, zone_history=history)
        await _add_run(db, user=b, igt_ms=1100, minute=2, kind="daily")
        await db.commit()
        runs = await load_counted_runs(db)

        daily_only = await build_board(
            db,
            runs,
            category="sprint",
            sub="set",
            deathless_only=False,
            types=frozenset({"daily"}),
            include_obsolete=False,
        )
        full = await build_board(
            db,
            runs,
            category="sprint",
            sub="set",
            deathless_only=False,
            types=frozenset(RUN_TYPES),
            include_obsolete=False,
        )

    assert [(r.user.twitch_username, r.rank) for r in daily_only.runs] == [("b", 1)]
    assert [(r.user.twitch_username, r.weapon) for r in full.runs] == [
        ("a", [2000000]),
        ("b", None),
    ]
    assert [r.user.twitch_username for r in full.history] == ["a"]
    assert all(r.rank is None for r in full.history)


async def test_build_overview_recent_runs_and_places(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        b = await _user(db, "b")
        c = await _user(db, "c")
        await _add_run(db, user=a, igt_ms=1000, minute=1)
        await _add_run(db, user=b, igt_ms=1100, minute=2, kind="daily")
        await _add_run(db, user=c, igt_ms=1050, minute=3, kind="event")
        await _add_run(db, user=a, igt_ms=2000, minute=4, pool="standard")
        await _add_run(db, user=b, igt_ms=1900, minute=5, pool="standard")
        await _add_run(db, user=c, igt_ms=1500, minute=6, kind="daily", deathless=True)
        await db.commit()

        ov = await build_overview(db, await load_counted_runs(db))

    assert (ov.runs, ov.players) == (6, 3)
    assert [r.igt_ms for r in ov.recent_runs] == [1500, 1900, 2000, 1050, 1100]
    assert [r.rank for r in ov.recent_runs] == [3, 1, 2, 2, 3]
    assert (ov.recent_runs[0].category, ov.recent_runs[0].deathless) == ("Sprint", True)


async def test_load_counted_runs_keeps_the_current_layer_count_only(async_session, pools):
    """A seed from an older version of its pool (another layer count than the
    pool's config) does not count; a pool without layers_count keeps all."""
    async with async_session() as db:
        a = await _user(db, "a")
        current = await _add_run(db, user=a, igt_ms=1000, minute=1)
        await _add_run(db, user=a, igt_ms=500, minute=2, layers=12)
        unversioned = await _add_run(db, user=a, igt_ms=900, minute=3, pool="standard", layers=17)
        await db.commit()

        runs = await load_counted_runs(db)

    assert {r.run_id for r in runs} == {current.id, unversioned.id}


async def test_category_release_is_the_first_seed_at_the_current_layer_count(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        await _add_run(db, user=a, igt_ms=500, minute=1, layers=12)
        await _add_run(db, user=a, igt_ms=1000, minute=5)
        await _add_run(db, user=a, igt_ms=1100, minute=9)
        await db.commit()

        cats = await load_categories(db, await load_counted_runs(db))

    assert [(c.pool, _naive(c.released_at)) for c in cats] == [
        ("sprint", _naive(BASE + timedelta(minutes=5 - 60)))
    ]


async def test_counted_runs_include_ranked_solo_sessions(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        banned = await _user(db, "banned", banned=True)
        speedrun = await _add_session(db, a, "sprint", RunMode.SPEEDRUN, 5000)
        set_seed = await _add_session(db, a, "sprint", RunMode.SET_SEED, 6000)
        await _add_session(db, a, "sprint", RunMode.NORMAL, 100)
        await _add_session(
            db,
            a,
            "sprint",
            RunMode.SPEEDRUN,
            100,
            status=TrainingSessionStatus.ACTIVE,
        )
        await _add_session(db, banned, "sprint", RunMode.SPEEDRUN, 100)
        await _add_session(db, a, "training_sprint", RunMode.SPEEDRUN, 100)
        await _add_session(db, a, "sprint", RunMode.SPEEDRUN, 100, layers=12)
        await db.commit()

        runs = await load_counted_runs(db)

    by_id = {r.run_id: r for r in runs}
    assert set(by_id) == {speedrun.id, set_seed.id}
    blind_run = by_id[speedrun.id]
    assert (blind_run.run_type, blind_run.blind, blind_run.category) == ("solo", True, "sprint")
    assert (blind_run.race_id, blind_run.race_name) == (None, None)
    assert blind_run.session_id == speedrun.id
    assert blind_run.igt_ms == 5000
    assert by_id[set_seed.id].blind is False


async def test_session_finish_time_falls_back_to_creation(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        await _add_session(db, a, "sprint", RunMode.SPEEDRUN, 5000, finished_at=None)
        await db.commit()

        runs = await load_counted_runs(db)

    assert len(runs) == 1
    assert runs[0].finished_at is not None


async def test_set_seed_race_runs_are_replays(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        replay = await _add_run(db, user=a, igt_ms=1000, minute=1, mode=RunMode.SET_SEED)
        ordinary = await _add_run(db, user=a, igt_ms=1100, minute=2)
        daily = await _add_run(db, user=a, igt_ms=1200, minute=3, kind="daily")
        event = await _add_run(db, user=a, igt_ms=1300, minute=4, kind="event")
        await db.commit()

        runs = await load_counted_runs(db)

    blind = {r.run_id: r.blind for r in runs}
    assert blind == {replay.id: False, ordinary.id: True, daily.id: True, event.id: True}
    assert all(r.session_id is None for r in runs)


async def test_main_weapons_cover_races_and_sessions(async_session, pools):
    history = [{"weapons": [{"ids": [1000000], "ticks": 5}]}]
    async with async_session() as db:
        a = await _user(db, "a")
        participant = await _add_run(db, user=a, igt_ms=1000, minute=1, zone_history=history)
        session = await _add_session(db, a, "sprint", RunMode.SPEEDRUN, 5000, zone_history=history)
        await db.commit()

        weapons = await load_main_weapons(db, [participant.id], [session.id])

    assert weapons == {participant.id: [1000000], session.id: [1000000]}


async def test_boards_and_overview_hold_a_solo_run_without_a_race(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        session = await _add_session(db, a, "sprint", RunMode.SPEEDRUN, 5000)
        await db.commit()

        runs = await load_counted_runs(db)
        board = await build_board(
            db,
            runs,
            category="sprint",
            sub="set",
            deathless_only=False,
            types=frozenset(RUN_TYPES),
            include_obsolete=False,
        )
        overview = await build_overview(db, runs)

    assert [(r.race_id, r.race_name, r.igt_ms) for r in board.runs] == [(None, None, 5000)]
    # A solo run is named by its session id, the same on the boards and the seed page.
    assert [r.run_id for r in board.runs] == [session.id]
    assert [r.race_id for r in board.history] == [None]
    assert [r.race_id for r in overview.recent_runs] == [None]


async def _four_runs(db: AsyncSession) -> None:
    users = [await _user(db, n) for n in "abcd"]
    await _add_run(db, user=users[0], igt_ms=4000, minute=1)
    await _add_run(db, user=users[1], igt_ms=3000, minute=2, mode=RunMode.SET_SEED)
    await _add_session(db, users[2], "sprint", RunMode.SPEEDRUN, 2000)
    await _add_session(db, users[3], "sprint", RunMode.SET_SEED, 1000)
    await db.commit()


async def test_random_board_keeps_blind_runs_only(async_session, pools):
    async with async_session() as db:
        await _four_runs(db)
        runs = await load_counted_runs(db)

    board = filter_board(
        runs, category="sprint", sub="random", deathless_only=False, types=frozenset(RUN_TYPES)
    )

    assert sorted(r.igt_ms for r in board) == [2000, 4000]


async def test_set_board_keeps_every_run(async_session, pools):
    async with async_session() as db:
        await _four_runs(db)
        runs = await load_counted_runs(db)

    board = filter_board(
        runs, category="sprint", sub="set", deathless_only=False, types=frozenset(RUN_TYPES)
    )
    ranked = rank_board(board, include_obsolete=False)

    assert [(r.user.twitch_username, rank) for r, rank in ranked] == [
        ("d", 1),
        ("c", 2),
        ("b", 3),
        ("a", 4),
    ]


async def test_deathless_only_keeps_deathless_mode_runs(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        b = await _user(db, "b")
        await _add_run(db, user=a, igt_ms=1000, minute=1, deathless=True)
        await _add_run(db, user=b, igt_ms=900, minute=2)
        await _add_session(db, b, "sprint", RunMode.SPEEDRUN, 800)
        await db.commit()
        runs = await load_counted_runs(db)

    every = frozenset(RUN_TYPES)
    default = filter_board(runs, category="sprint", sub="set", deathless_only=False, types=every)
    only = filter_board(runs, category="sprint", sub="set", deathless_only=True, types=every)

    assert len(default) == 3
    assert [(r.user.twitch_username, r.run_type) for r in only] == [("a", "race")]


def test_record_seed_counts_runs_on_the_record_seed():
    board = [
        _run("a", 1000, 1, seed="s1"),
        _run("a", 1500, 2, seed="s1"),
        _run("b", 1200, 3, seed="s1"),
        _run("c", 1100, 4, seed="s2"),
    ]

    seed = record_seed(board, rank_board(board, include_obsolete=False))

    assert seed is not None
    assert (seed.seed_number, seed.runs) == ("s1", 3)
    assert record_seed([], []) is None


def test_record_seed_follows_first_ranked_row():
    board = [_run("a", 1000, 5, seed="late"), _run("b", 1000, 2, seed="early")]

    seed = record_seed(board, rank_board(board, include_obsolete=False))

    assert seed is not None and seed.seed_number == "early"


async def test_recent_run_place_is_on_the_set_board(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        b = await _user(db, "b")
        await _add_run(db, user=a, igt_ms=1000, minute=1, mode=RunMode.SET_SEED)
        await _add_session(db, b, "sprint", RunMode.SPEEDRUN, 1500, finished_at=BASE)
        await _add_run(db, user=b, igt_ms=900, minute=3, deathless=True)
        await db.commit()

        ov = await build_overview(db, await load_counted_runs(db))

    by_igt = {r.igt_ms: r.rank for r in ov.recent_runs}
    # One shared board: b's deathless 900 leads, a's replay is behind it, and
    # b's solo 1500 is behind a (never behind b's own faster run).
    assert by_igt == {900: 1, 1000: 2, 1500: 2}


async def test_recent_run_on_an_excluded_seed_has_no_place(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        b = await _user(db, "b")
        await _add_run(db, user=a, igt_ms=1000, minute=1)
        excluded = await _add_run(db, user=b, igt_ms=900, minute=2)
        race = await db.get(Race, excluded.race_id)
        assert race is not None and race.seed_id is not None
        seed = await db.get(Seed, race.seed_id)
        assert seed is not None
        seed.set_seed_excluded_at = BASE
        await db.commit()

        ov = await build_overview(db, await load_counted_runs(db))

    # The excluded seed's run is on no Set Seed board, so it has no place
    # there, and the other run's place ignores it.
    assert {r.igt_ms: r.rank for r in ov.recent_runs} == {1000: 1, 900: None}


@pytest.fixture
async def archived_pool(async_session):
    async with async_session() as db:
        db.add(
            Pool(
                name="veteran",
                config={
                    "name": "Veteran",
                    "type": "race",
                    "sort_order": 10,
                    "layers_count": 30,
                    "archived_layers": [25],
                },
            )
        )
        await db.commit()


async def test_archived_layer_count_forms_retired_category(async_session, pools, archived_pool):
    async with async_session() as db:
        a = await _user(db, "a")
        current = await _add_run(db, user=a, igt_ms=1000, minute=5, pool="veteran", layers=30)
        old = await _add_run(db, user=a, igt_ms=900, minute=3, pool="veteran", layers=25)
        await _add_run(db, user=a, igt_ms=950, minute=4, pool="veteran", layers=25)
        await _add_run(db, user=a, igt_ms=800, minute=6)
        await db.commit()

        runs = await load_counted_runs(db)
        cats = await load_categories(db, runs)
        board = filter_board(
            runs, category="veteran@25", sub="set", deathless_only=False, types=frozenset(RUN_TYPES)
        )
        overview = await build_overview(db, runs)

    assert {r.run_id: r.category for r in runs}[current.id] == "veteran"
    assert {r.run_id for r in board if r.run_id == old.id} == {old.id}
    assert len(board) == 2
    assert [(c.pool, c.name, c.retired) for c in cats] == [
        ("veteran", "Veteran", False),
        ("sprint", "Sprint", False),
        ("veteran@25", "Veteran (25 layers)", True),
    ]
    archive = cats[2]
    assert _naive(archive.released_at) == _naive(BASE + timedelta(minutes=3 - 60))
    assert {r.category for r in overview.recent_runs} >= {"Veteran (25 layers)"}
    assert "veteran@25" in {r.pool for r in overview.recent_runs}


async def test_unlisted_old_layer_count_stays_out(async_session, pools, archived_pool):
    async with async_session() as db:
        a = await _user(db, "a")
        await _add_run(db, user=a, igt_ms=900, minute=3, pool="veteran", layers=25)
        await _add_run(db, user=a, igt_ms=950, minute=4, pool="veteran", layers=22)
        await db.commit()

        runs = await load_counted_runs(db)

    assert [r.category for r in runs] == ["veteran@25"]


async def test_archived_category_without_runs_is_not_listed(async_session, pools, archived_pool):
    async with async_session() as db:
        a = await _user(db, "a")
        await _add_run(db, user=a, igt_ms=900, minute=3, pool="veteran", layers=30)
        await db.commit()

        cats = await load_categories(db, await load_counted_runs(db))

    assert [c.pool for c in cats] == ["veteran"]


async def _practice(db, seed, user, *, days_ago=1.0, mode=RunMode.SET_SEED, as_race=False):
    """One Set Seed attempt on ``seed`` made ``days_ago`` before PRACTICE_NOW."""
    at = PRACTICE_NOW - timedelta(days=days_ago)
    if as_race:
        part = await _add_run(db, user=user, igt_ms=1000, minute=1, mode=mode, seed=seed)
        part.created_at = at
        return part
    session = await _add_session(db, user, "sprint", mode, 1000, seed=seed)
    session.created_at = at
    return session


PRACTICE_NOW = BASE + timedelta(days=30)


async def _seed(db, number, pool="sprint", layers=15):
    seed = Seed(
        seed_number=number,
        pool_name=pool,
        graph_json={"nodes": {}},
        total_layers=layers,
        folder_path=SEED_ZIP,
        status=SeedStatus.CONSUMED,
        created_at=BASE,
    )
    db.add(seed)
    await db.flush()
    return seed


async def test_practiced_seeds_count_sessions_and_races_in_the_window(async_session, pools):
    async with async_session() as db:
        a, b, banned = await _user(db, "a"), await _user(db, "b"), await _user(db, "z", banned=True)
        s1 = await _seed(db, "aaaaaa111")
        s2 = await _seed(db, "bbbbbb222")
        await _practice(db, s1, a)
        await _practice(db, s1, a, days_ago=2)
        await _practice(db, s1, b, as_race=True)
        await _practice(db, s1, b, days_ago=8)  # too old
        await _practice(db, s1, banned)  # banned
        await _practice(db, s1, b, mode=RunMode.SPEEDRUN)  # blind run, not an attempt
        invalid = await _practice(db, s2, a)
        invalid.invalidated_at = PRACTICE_NOW
        await _practice(db, s2, a, days_ago=9)
        await db.commit()

        ov = await build_overview(db, await load_counted_runs(db), now=PRACTICE_NOW)

    assert [
        (p.seed_number, p.category, p.category_name, p.attempts, p.players)
        for p in ov.practiced_seeds
    ] == [("aaaaaa111", "sprint", "Sprint", 3, 2)]


async def test_practiced_seeds_order_and_cap(async_session, pools):
    async with async_session() as db:
        users = [await _user(db, f"u{i}") for i in range(3)]
        # (attempts, players): ties on attempts break on players, then seed number.
        plan = {"s1": (3, 3), "s2": (3, 1), "s3": (2, 2), "s4": (1, 1), "s5": (1, 1), "s6": (1, 1)}
        for number, (attempts, players) in plan.items():
            seed = await _seed(db, number + "xxxxx")
            for i in range(attempts):
                await _practice(db, seed, users[i % players])
        await db.commit()

        ov = await build_overview(db, await load_counted_runs(db), now=PRACTICE_NOW)

    assert [p.seed_number[:2] for p in ov.practiced_seeds] == ["s1", "s2", "s3", "s4", "s5"]


async def test_practiced_seeds_honor_the_configured_window_and_count(
    async_session, pools, monkeypatch
):
    monkeypatch.setattr(settings, "speedrun_practiced_seeds_days", 10)
    monkeypatch.setattr(settings, "speedrun_practiced_seeds_count", 2)
    async with async_session() as db:
        user = await _user(db, "a")
        # One attempt 9 days ago (inside 10, outside the default 7), then 3, 2 and 1
        # attempts today: only the two busiest seeds are kept.
        old = await _seed(db, "oldold111")
        await _practice(db, old, user, days_ago=9)
        for number, attempts in (("s1xxxxx", 3), ("s2xxxxx", 2), ("s3xxxxx", 1)):
            seed = await _seed(db, number)
            for _ in range(attempts):
                await _practice(db, seed, user)
        await db.commit()

        ov = await build_overview(db, await load_counted_runs(db), now=PRACTICE_NOW)
        monkeypatch.setattr(settings, "speedrun_practiced_seeds_count", 10)
        wide = await build_overview(db, await load_counted_runs(db), now=PRACTICE_NOW)

    assert [p.seed_number for p in ov.practiced_seeds] == ["s1xxxxx", "s2xxxxx"]
    assert ov.practiced_seeds_days == 10
    assert "oldold111" in [p.seed_number for p in wide.practiced_seeds]


async def test_recent_runs_honor_the_configured_count(async_session, pools, monkeypatch):
    monkeypatch.setattr(settings, "speedrun_recent_runs_count", 2)
    async with async_session() as db:
        await _four_runs(db)
        ov = await build_overview(db, await load_counted_runs(db))

    assert len(ov.recent_runs) == 2


async def _seed_of(db: AsyncSession, part: Participant) -> Seed:
    race = await db.get(Race, part.race_id)
    assert race is not None and race.seed_id is not None
    seed = await db.get(Seed, race.seed_id)
    assert seed is not None
    return seed


async def test_boards_count_seeds_added_since_the_board_start(async_session, pools, monkeypatch):
    monkeypatch.setattr(settings, "speedrun_board_start_date", BASE)
    async with async_session() as db:
        a = await _user(db, "a")
        before = await _add_run(db, user=a, igt_ms=500, minute=1)
        (await _seed_of(db, before)).created_at = BASE - timedelta(seconds=1)
        at_start = await _add_run(db, user=a, igt_ms=900, minute=2)
        (await _seed_of(db, at_start)).created_at = BASE
        solo_before = await _add_session(db, a, "sprint", RunMode.SPEEDRUN, 400)
        await db.commit()

        runs = await load_counted_runs(db)
        before_seed = await _seed_of(db, before)
        seed_page = await load_counted_runs(db, seed_id=before_seed.id)

    # The solo session's own seed is added an hour before BASE.
    assert [r.run_id for r in runs] == [at_start.id]
    assert solo_before.id not in {r.run_id for r in runs}
    # A seed page lists its runs whatever the boards do.
    assert [r.run_id for r in seed_page] == [before.id]


async def test_categories_start_at_the_board_start(async_session, pools, monkeypatch):
    monkeypatch.setattr(settings, "speedrun_board_start_date", BASE)
    async with async_session() as db:
        a = await _user(db, "a")
        # Retired pool: played only before the start, so it has no board.
        await _add_run(db, user=a, igt_ms=800, minute=1, pool="retired")
        # Sprint: a seed before the start and two after it.
        await _add_run(db, user=a, igt_ms=700, minute=10)
        await _add_run(db, user=a, igt_ms=1000, minute=70)
        await _add_run(db, user=a, igt_ms=1100, minute=90)
        await db.commit()

        cats = await load_categories(db, await load_counted_runs(db))

    # Seeds are added an hour before their run: 10 -> BASE - 50 min (before),
    # 70 -> BASE + 10 min, the first seed of the board.
    assert [(c.pool, _naive(c.released_at)) for c in cats] == [
        ("sprint", _naive(BASE + timedelta(minutes=10)))
    ]


async def test_set_seed_board_keeps_only_seeds_that_can_be_replayed(
    async_session, pools, monkeypatch
):
    monkeypatch.setattr(settings, "set_seed_min_seed_date", BASE)
    async with async_session() as db:
        a, b, c, d = [await _user(db, n) for n in "abcd"]
        kept = await _add_run(db, user=a, igt_ms=1000, minute=61)
        purged = await _add_run(db, user=b, igt_ms=900, minute=62)
        (await _seed_of(db, purged)).folder_path = "/nonexistent/seed.zip"
        old_version = await _add_run(db, user=c, igt_ms=800, minute=30)
        excluded = await _add_run(db, user=d, igt_ms=700, minute=63)
        (await _seed_of(db, excluded)).set_seed_excluded_at = BASE
        await db.commit()

        runs = await load_counted_runs(db)

    def board(sub):
        return {
            r.run_id
            for r in filter_board(
                runs,
                category="sprint",
                sub=sub,
                deathless_only=False,
                types=frozenset(RUN_TYPES),
            )
        }

    assert board("set") == {kept.id}
    # Random Seed keeps blind runs whatever their seed's files or version.
    assert board("random") == {kept.id, purged.id, old_version.id, excluded.id}


async def test_recent_run_on_a_purged_or_too_old_seed_has_no_place(
    async_session, pools, monkeypatch
):
    monkeypatch.setattr(settings, "set_seed_min_seed_date", BASE)
    async with async_session() as db:
        a, b, c = [await _user(db, n) for n in "abc"]
        await _add_run(db, user=a, igt_ms=1000, minute=61)
        purged = await _add_run(db, user=b, igt_ms=900, minute=62)
        (await _seed_of(db, purged)).folder_path = "/nonexistent/seed.zip"
        await _add_run(db, user=c, igt_ms=800, minute=30)
        await db.commit()

        ov = await build_overview(db, await load_counted_runs(db))

    assert {r.igt_ms: r.rank for r in ov.recent_runs} == {1000: 1, 900: None, 800: None}


async def test_record_seed_says_whether_the_record_can_be_replayed(async_session, pools):
    async with async_session() as db:
        a, b = await _user(db, "a"), await _user(db, "b")
        await _add_run(db, user=a, igt_ms=1000, minute=1)
        purged = await _add_run(db, user=b, igt_ms=900, minute=2)
        (await _seed_of(db, purged)).folder_path = "/nonexistent/seed.zip"
        await db.commit()

        runs = await load_counted_runs(db)
        types = frozenset(RUN_TYPES)
        random_board = await build_board(
            db,
            runs,
            category="sprint",
            sub="random",
            deathless_only=False,
            types=types,
            include_obsolete=False,
        )
        set_board = await build_board(
            db,
            runs,
            category="sprint",
            sub="set",
            deathless_only=False,
            types=types,
            include_obsolete=False,
        )

    assert random_board.record_seed is not None and not random_board.record_seed.replayable
    assert set_board.record_seed is not None and set_board.record_seed.replayable


async def test_an_archive_record_seed_cannot_be_replayed(async_session, pools, archived_pool):
    async with async_session() as db:
        a = await _user(db, "a")
        await _add_run(db, user=a, igt_ms=900, minute=3, pool="veteran", layers=25)
        await db.commit()

        board = await build_board(
            db,
            await load_counted_runs(db),
            category="veteran@25",
            sub="set",
            deathless_only=False,
            types=frozenset(RUN_TYPES),
            include_obsolete=False,
        )

    # Its files are there, but the pool plays 30 layers now.
    assert board.record_seed is not None and not board.record_seed.replayable
