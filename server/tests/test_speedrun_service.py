"""speedrun.fog service: which runs count, ranking, record history, weapons."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    Event,
    Participant,
    ParticipantStatus,
    Pool,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.schemas import UserResponse
from speedfog_racing.services.speedrun_service import (
    RUN_TYPES,
    CountedRun,
    build_board,
    build_overview,
    load_categories,
    load_counted_runs,
    main_weapon,
    place_of,
    rank_board,
    record_history,
)

BASE = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


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
                Pool(name="sprint", config={"name": "Sprint", "type": "race", "sort_order": 20}),
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
    exclude: bool = False,
    zone_history: list[dict[str, Any]] | None = None,
    finished: bool = True,
) -> Participant:
    """One race on its own seed with a single participant."""
    tag = uuid.uuid4().hex[:10]
    seed = Seed(
        seed_number=f"seed{tag}",
        pool_name=pool,
        graph_json={"nodes": {}},
        total_layers=15,
        folder_path=f"/t/{tag}",
        status=SeedStatus.CONSUMED,
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
        exclude_from_stats=exclude or kind in ("daily", "event"),
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


def _uid(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, name)


def _run(
    name: str,
    igt_ms: int,
    minute: int,
    *,
    pool: str = "sprint",
    deathless: bool = False,
) -> CountedRun:
    return CountedRun(
        participant_id=uuid.uuid4(),
        user=UserResponse(
            id=_uid(name),
            twitch_username=name,
            twitch_display_name=None,
            twitch_avatar_url=None,
        ),
        pool=pool,
        deathless=deathless,
        run_type="race",
        igt_ms=igt_ms,
        finished_at=BASE + timedelta(minutes=minute),
        race_id=uuid.uuid4(),
        race_name="R",
        daily_date=None,
        seed_number="abc",
        layers=15,
        deaths=0,
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
        await _add_run(db, user=a, igt_ms=800, minute=8, exclude=True)
        await _add_run(db, user=a, igt_ms=800, minute=9, pool="training_sprint")
        await db.commit()

        runs = await load_counted_runs(db)

    assert sorted(r.run_type for r in runs) == ["daily", "event", "race"]
    assert {r.participant_id for r in runs} == {race_p.id, daily_p.id, event_p.id}


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


async def test_categories_order_and_subcategories(async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        await _add_run(db, user=a, igt_ms=1000, minute=1, pool="sprint")
        await _add_run(db, user=a, igt_ms=1000, minute=2, pool="sprint", deathless=True)
        await _add_run(db, user=a, igt_ms=1000, minute=3, pool="standard")
        await _add_run(db, user=a, igt_ms=1000, minute=4, pool="retired", deathless=True)
        await db.commit()

        cats = await load_categories(db, await load_counted_runs(db))

    assert [(c.pool, c.name, c.retired, c.subcategories) for c in cats] == [
        ("sprint", "Sprint", False, ["any", "deathless"]),
        ("standard", "Standard", False, ["any"]),
        ("retired", "Retired", True, ["deathless"]),
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
            pool="sprint",
            deathless=False,
            types=frozenset({"daily"}),
            include_obsolete=False,
        )
        full = await build_board(
            db,
            runs,
            pool="sprint",
            deathless=False,
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
    assert [r.rank for r in ov.recent_runs] == [1, 1, 2, 2, 3]
    assert (ov.recent_runs[0].category, ov.recent_runs[0].deathless) == ("Sprint", True)
