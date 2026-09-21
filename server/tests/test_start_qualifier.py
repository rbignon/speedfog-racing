"""tools/start_qualifier.py: the start plan, and runs against the API it drives."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Event,
    Participant,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)

_SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "start_qualifier.py"
_spec = importlib.util.spec_from_file_location("start_qualifier", _SCRIPT)
assert _spec is not None and _spec.loader is not None
sq = importlib.util.module_from_spec(_spec)
sys.modules["start_qualifier"] = sq  # dataclasses look their module up
_spec.loader.exec_module(sq)

WEEK = 7 * 24 * 60
MODES = [{"key": "standard", "label": "Standard"}, {"key": "boss_rush", "label": "Boss Rush"}]
DETAIL = {
    "starts_at": "2026-09-23T18:00:00Z",
    "qualifier_ends_at": "2026-09-30T18:00:00Z",
    "modes": MODES,
    "seeds_per_mode": 2,
}


def _planned(race_id: str, status: str = "setup", **overrides: Any) -> dict[str, Any]:
    race = {
        "id": race_id,
        "name": race_id,
        "status": status,
        "is_public": False,
        "open_registration": False,
        "max_participants": None,
        "seeds_released_at": None,
        "participant_count": 0,
        "participant_previews": [],
        "late_join_window_minutes": WEEK,
        "race_duration_minutes": WEEK,
    }
    return {**race, **overrides}


def test_only_attached_races_in_setup_are_started():
    attached = {
        "qualifier:standard:1": "a",
        "qualifier:standard:2": "b",
        "qualifier:boss_rush:1": "gone",
    }
    races = {"a": _planned("a"), "b": _planned("b", "running")}

    plans = {p.slot: p for p in sq.plan_slots(DETAIL, attached, races)}

    assert list(plans) == [
        "qualifier:standard:1",
        "qualifier:standard:2",
        "qualifier:boss_rush:1",
        "qualifier:boss_rush:2",
    ]
    assert [slot for slot, p in plans.items() if p.start] == ["qualifier:standard:1"]
    assert plans["qualifier:standard:2"].notes == ["already running, left alone"]
    # Attached but out of the in-flight list: finished, or an id gone wrong.
    assert plans["qualifier:boss_rush:1"].race is None
    assert plans["qualifier:boss_rush:2"].notes == ["no race attached"]


def test_a_race_to_start_is_flagged_when_it_would_not_open_clean():
    attached = {
        "qualifier:standard:1": "clean",
        "qualifier:standard:2": "busy",
        "qualifier:boss_rush:1": "short",
        "qualifier:boss_rush:2": "exposed",
    }
    races = {
        "clean": _planned("clean"),
        "busy": _planned(
            "busy", participant_count=1, participant_previews=[{"twitch_username": "check"}]
        ),
        "short": _planned("short", race_duration_minutes=WEEK - 10),
        "exposed": _planned("exposed", is_public=True, open_registration=True),
    }

    plans = {p.slot: p for p in sq.plan_slots(DETAIL, attached, races)}

    def flagged(slot: str, *words: str) -> bool:
        notes = plans[slot].notes
        return len(notes) == len(words) and all(
            word in note for word, note in zip(words, notes, strict=True)
        )

    # Flagged, not skipped: the organizer decides whether to fix it first.
    assert all(plans[slot].start for slot in attached)
    assert plans["qualifier:standard:1"].notes == []
    assert flagged("qualifier:standard:2", "check")
    assert flagged("qualifier:boss_rush:1", "window", "late join")
    assert flagged("qualifier:boss_rush:2", "public", "registration")


@pytest.fixture
async def async_session(tmp_path):
    # A file, not :memory:, whose single shared connection would interleave
    # the transactions of the calls the script sends concurrently.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/db.sqlite", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield maker
    app.dependency_overrides.clear()
    await engine.dispose()


async def _event(db: AsyncSession, opening: datetime) -> tuple[User, Event]:
    root = User(twitch_id="id-root", twitch_username="root", api_token="tok-root")
    root.role = UserRole.ADMIN
    db.add(root)
    await db.flush()
    event = Event(
        slug="cup",
        name="Cup",
        starts_at=opening,
        qualifier_ends_at=opening + timedelta(minutes=WEEK),
        ends_at=opening + timedelta(days=30),
        newcomer_threshold=5,
        config={"modes": MODES, "seeds_per_mode": 2},
    )
    db.add(event)
    await db.flush()
    return root, event


async def _race(
    db: AsyncSession,
    organizer: User,
    event: Event,
    slot: str,
    status: RaceStatus = RaceStatus.SETUP,
    released_at: datetime | None = None,
    started_at: datetime | None = None,
) -> Race:
    """A qualifier race the way the organizer leaves it: registration closed."""
    seed = Seed(
        seed_number=slot,
        pool_name=slot.split(":")[1],
        graph_json={"total_layers": 5, "nodes": []},
        total_layers=5,
        folder_path=f"/seeds/{slot}.zip",
        status=SeedStatus.CONSUMED,
    )
    db.add(seed)
    await db.flush()
    race = Race(
        name=slot,
        organizer_id=organizer.id,
        seed_id=seed.id,
        status=status,
        is_public=False,
        open_registration=False,
        seeds_released_at=released_at,
        started_at=started_at,
        late_join_window_minutes=WEEK,
        race_duration_minutes=WEEK,
        event_id=event.id,
        event_slot=slot,
        exclude_from_stats=True,
    )
    db.add(race)
    await db.flush()
    return race


def _aware(moment: datetime | None) -> datetime | None:
    return moment.replace(tzinfo=UTC) if moment and moment.tzinfo is None else moment


async def _run(
    now: bool,
    before_opening: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    return int(
        await sq.run(
            "http://test",
            "cup",
            "tok-root",
            False,
            now,
            10,
            before_opening=before_opening,
            transport=transport or ASGITransport(app=app),
        )
    )


@pytest.mark.asyncio
async def test_run_opens_registration_releases_and_starts(async_session, capsys):
    now = datetime.now(UTC)
    async with async_session() as db:
        root, event = await _event(db, now + timedelta(hours=1))
        withheld = await _race(db, root, event, "qualifier:standard:1")
        checked = await _race(db, root, event, "qualifier:standard:2", released_at=now)
        running = await _race(
            db, root, event, "qualifier:boss_rush:1", RaceStatus.RUNNING, now, now
        )
        await db.commit()

    assert await _run(now=True, before_opening=True) == 0

    out = capsys.readouterr().out
    assert "Left alone, already running: qualifier:boss_rush:1" in out
    assert "No race to start: qualifier:boss_rush:2" in out
    async with async_session() as db:
        for race_id in (withheld.id, checked.id):
            race = await db.get(Race, race_id)
            assert race is not None
            assert race.status == RaceStatus.RUNNING
            assert race.seeds_released_at is not None
            assert race.open_registration is True and race.max_participants == 100
        left_alone = await db.get(Race, running.id)
    assert left_alone is not None and _aware(left_alone.started_at) == now


@pytest.mark.asyncio
async def test_run_waits_for_the_opening_minus_the_countdown(async_session, monkeypatch):
    opening = (datetime.now(UTC) + timedelta(hours=1)).replace(microsecond=0)
    async with async_session() as db:
        root, event = await _event(db, opening)
        await _race(db, root, event, "qualifier:standard:1")
        await db.commit()
    waits: list[datetime] = []

    async def record(moment: datetime) -> None:
        waits.append(moment)

    monkeypatch.setattr(sq, "sleep_until", record)

    assert await _run(now=False) == 0
    # Read again, open and release first; start calls one countdown early.
    fire_at = opening - timedelta(seconds=10)
    assert waits == [fire_at - sq.REFRESH_LEAD, fire_at]


@pytest.mark.asyncio
async def test_run_refuses_an_opening_already_past(async_session):
    async with async_session() as db:
        root, event = await _event(db, datetime.now(UTC) - timedelta(minutes=1))
        race = await _race(db, root, event, "qualifier:standard:1")
        await db.commit()

    assert await _run(now=False) == 1
    async with async_session() as db:
        untouched = await db.get(Race, race.id)
    assert untouched is not None and untouched.status == RaceStatus.SETUP


class _LoseFirstStartAnswer(httpx.AsyncBaseTransport):
    """Lets the first start call through, then loses its answer, as a timeout
    after the server committed would."""

    def __init__(self) -> None:
        self.inner = ASGITransport(app=app)
        self.lost = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.inner.handle_async_request(request)
        if not self.lost and request.method == "POST" and request.url.path.endswith("/start"):
            self.lost = True
            await response.aclose()
            raise httpx.ReadTimeout("answer lost", request=request)
        return response


@pytest.mark.asyncio
async def test_a_start_whose_answer_was_lost_still_counts(async_session, capsys):
    async with async_session() as db:
        root, event = await _event(db, datetime.now(UTC) + timedelta(hours=1))
        race = await _race(db, root, event, "qualifier:standard:1")
        await db.commit()

    # The retry reads "already started"; the race's state says it did.
    assert await _run(now=True, before_opening=True, transport=_LoseFirstStartAnswer()) == 0
    assert "FAILED" not in capsys.readouterr().out
    async with async_session() as db:
        started = await db.get(Race, race.id)
    assert started is not None and started.status == RaceStatus.RUNNING


@pytest.mark.asyncio
async def test_now_is_refused_before_the_opening(async_session):
    """On the real event, --now would open every seed hours early."""
    async with async_session() as db:
        root, event = await _event(db, datetime.now(UTC) + timedelta(hours=1))
        race = await _race(db, root, event, "qualifier:standard:1")
        await db.commit()

    assert await _run(now=True) == 1
    async with async_session() as db:
        untouched = await db.get(Race, race.id)
    assert untouched is not None and untouched.status == RaceStatus.SETUP
    assert untouched.open_registration is False


class _RefuseRegistration(httpx.AsyncBaseTransport):
    """Answers every PATCH with a server error."""

    def __init__(self) -> None:
        self.inner = ASGITransport(app=app)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            return httpx.Response(500, json={"detail": "down"})
        return await self.inner.handle_async_request(request)


@pytest.mark.asyncio
async def test_a_race_whose_registration_stays_closed_is_not_started(async_session, capsys):
    """Started, its registration could never open: nobody could join the seed."""
    async with async_session() as db:
        root, event = await _event(db, datetime.now(UTC) + timedelta(hours=1))
        race = await _race(db, root, event, "qualifier:standard:1")
        await db.commit()

    assert await _run(now=True, before_opening=True, transport=_RefuseRegistration()) == 1
    assert "left in setup" in capsys.readouterr().out
    async with async_session() as db:
        kept = await db.get(Race, race.id)
    assert kept is not None and kept.status == RaceStatus.SETUP


@pytest.mark.asyncio
async def test_the_last_reading_decides_what_starts(async_session, monkeypatch):
    """A seed detached after the launch (voided) is not started."""
    async with async_session() as db:
        root, event = await _event(db, datetime.now(UTC) + timedelta(hours=1))
        race = await _race(db, root, event, "qualifier:standard:1")
        await db.commit()
    waits: list[datetime] = []

    async def detach_on_first_wait(moment: datetime) -> None:
        if not waits:
            async with async_session() as db:
                voided = await db.get(Race, race.id)
                assert voided is not None
                voided.event_id = None
                voided.event_slot = None
                await db.commit()
        waits.append(moment)

    monkeypatch.setattr(sq, "sleep_until", detach_on_first_wait)

    assert await _run(now=False) == 0
    async with async_session() as db:
        kept = await db.get(Race, race.id)
    assert kept is not None and kept.status == RaceStatus.SETUP


@pytest.mark.asyncio
async def test_a_participant_left_registered_fails_the_run(async_session, capsys):
    """Past the start the check account can no longer be removed: the race
    starts, and the run says so."""
    async with async_session() as db:
        root, event = await _event(db, datetime.now(UTC) + timedelta(hours=1))
        race = await _race(db, root, event, "qualifier:standard:1")
        check = User(twitch_id="id-check", twitch_username="check", api_token="tok-check")
        db.add(check)
        await db.flush()
        db.add(Participant(race_id=race.id, user_id=check.id))
        await db.commit()

    assert await _run(now=True, before_opening=True) == 1
    assert "participant still registered: qualifier:standard:1" in capsys.readouterr().out
    async with async_session() as db:
        started = await db.get(Race, race.id)
    assert started is not None and started.status == RaceStatus.RUNNING
