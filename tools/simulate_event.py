#!/usr/bin/env python3
"""Put a local database into one life stage of a tournament event.

Generates a whole season once from a fixed RNG seed (roster, run times,
outcomes, weapons carried), then projects it at a virtual "now" chosen by the
stage argument. Every event and race date is shifted so that the virtual now
lands on the real now, which keeps the backend's phase derivation and the
browser's clocks honest; weekdays shift accordingly, so a Sunday final may
fall on a Wednesday.

Meant for looking at /events/<slug> in each of its states while working on the
page. Local databases only, and it refuses a database that is not on this
machine unless --force is given: it writes fabricated participations onto real
user rows and deletes the participants and casters of the races it manages.

It manages eighteen races, named the way docs/EVENTS.md has an organizer name
real ones so the page renders them identically, and found again by their event
slot on later runs. Creating them consumes one available seed each: three
standard, three boss rush, two UWYG major rush, and one each of sprint,
hardcore, UWYG rush and hardcore boss rush, plus the six qualifier seeds.

The event itself must already exist (create it from the admin Events tab), and
its modes and stages must match the ones below; its dates are rewritten. One
event at a time: --slug names which one, it does not isolate two.

Usage:
    cd server && uv run python ../tools/simulate_event.py qualifier
    cd server && uv run python ../tools/simulate_event.py semi_a_live --viewer alice
    cd server && uv run python ../tools/simulate_event.py final_done --slug season-one

With --viewer, that runner gets a seed of every card state (done, DNF,
playing, joined, and two never entered), so the page can be checked from a
participant's seat.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import secrets
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from sqlalchemy import delete, func, select, true, update
from sqlalchemy.orm import selectinload

# Must run from server/ (cd server && uv run python ../tools/simulate_event.py)
sys.path.insert(0, str(Path.cwd()))

import speedfog_racing.api  # noqa: E402, F401  (settles the api <-> services import cycle)
from speedfog_racing.config import settings  # noqa: E402
from speedfog_racing.database import async_session_maker  # noqa: E402
from speedfog_racing.models import (  # noqa: E402
    Caster,
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
from speedfog_racing.schemas import EventConfig  # noqa: E402
from speedfog_racing.services.event_service import (  # noqa: E402
    Slot,
    compute_ladder,
    compute_qualified,
    compute_stage_results,
)

RNG_SEED = 7
# Hosts this tool accepts without --force. Everything it does is destructive and
# only makes sense against a development database.
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "")


def check_local_database() -> None:
    dsn = settings.database_url
    host = urlparse(dsn).hostname or ""
    if not dsn.startswith("sqlite") and host not in LOCAL_HOSTS:
        raise SystemExit(
            f"refusing to write to a database on {host!r}; pass --force if that is "
            "really a development database"
        )


def D(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


# The season's shape. Only the intervals matter: every date is shifted so the
# scenario's virtual now becomes the real now.
ANNOUNCE = D("2026-09-16T18:00")
STARTS = D("2026-09-23T17:00")
CUT = D("2026-09-30T17:00")
ENDS = D("2026-10-25T23:00")
STAGES: dict[str, tuple[datetime, list[str]]] = {
    "semi_a": (D("2026-10-04T19:00"), ["standard", "boss_rush", "uwyg_major"]),
    "semi_b": (D("2026-10-11T19:00"), ["standard", "boss_rush", "uwyg_major"]),
    "newcomers": (D("2026-10-18T19:00"), ["standard", "sprint", "boss_rush"]),
    "final": (D("2026-10-25T19:00"), ["hardcore", "uwyg_rush", "hardcore_boss_rush"]),
}
STAGE_LABELS = {
    "semi_a": "Semi A",
    "semi_b": "Semi B",
    "newcomers": "Newcomers' final",
    "final": "Open final",
}
POOL_LABELS = {
    "standard": "Standard",
    "boss_rush": "Boss Rush",
    "uwyg_major": "UWYG Major Rush",
    "sprint": "Sprint",
    "hardcore": "Hardcore",
    "uwyg_rush": "UWYG Rush",
    "hardcore_boss_rush": "Hardcore Boss Rush",
}
MODES = ["standard", "uwyg_major", "boss_rush"]
SEEDS_PER_MODE = 2
BASE_MINUTES = {
    "standard": 62,
    "uwyg_major": 55,
    "boss_rush": 38,
    "sprint": 28,
    "hardcore": 70,
    "uwyg_rush": 45,
    "hardcore_boss_rush": 42,
}
STAGE_RACE_GAP = timedelta(minutes=60)
# A stage's races are created and attached this long before its date.
STAGE_ATTACH_LEAD = timedelta(days=2)
# Catalogue base ids (server/data/weapons.json), one favourite per runner so the
# event's signature weapon means something.
WEAPON_IDS = [
    8030000,  # Bloodhound's Fang
    9000000,  # Uchigatana
    9060000,  # Moonveil
    9040000,  # Nagakiba
    9080000,  # Serpentbone Blade
    12080000,  # Curved Great Club
    4030000,  # Troll's Golden Sword
    3040000,  # Knight's Greatsword
    3020000,  # Iron Greatsword
    18160000,  # Gargoyle's Black Halberd
]

# A scenario is either a fixed virtual now, or ("live", stage key) to sit 15
# minutes into that evening's second race, whenever the generated season put it.
SCENARIOS: dict[str, datetime | tuple[str, str]] = {
    "announce": D("2026-09-18T15:00"),
    "announce_attached": D("2026-09-18T15:00"),
    "qualifier": D("2026-09-27T15:00"),
    "cut": D("2026-10-01T15:00"),
    "semi_a_live": ("live", "semi_a"),
    "semi_a_done": D("2026-10-06T15:00"),
    "newcomers_live": ("live", "newcomers"),
    "newcomers_done": D("2026-10-20T15:00"),
    "final_live": ("live", "final"),
    "final_done": D("2026-10-25T22:30"),
}


# --- plan -------------------------------------------------------------------


@dataclass(eq=False)
class Runner:
    user: User
    skill: float
    newcomer: bool


@dataclass
class Run:
    user: User
    join_at: datetime
    start: datetime
    end: datetime  # finish or abandon instant
    finished: bool
    depth: float  # fraction of the seed's layers reached when abandoned (1.0 finished)
    color_index: int


@dataclass
class State:
    status: ParticipantStatus
    igt_ms: int
    current_layer: int
    current_zone: str | None
    zone_history: list[dict] | None
    layer_entry_igts: dict[str, int]
    finished_at: datetime | None
    death_count: int


def walk(graph: dict, rng: random.Random) -> list[tuple[str, int]]:
    """A start-to-final path through the seed graph as (node_id, layer)."""
    nodes = graph["nodes"]
    start = next(k for k, v in nodes.items() if v.get("type") == "start")
    path = [(start, nodes[start]["layer"])]
    seen = {start}
    cur = start
    while True:
        layer = nodes[cur]["layer"]
        exits = [
            e["to"]
            for e in nodes[cur].get("exits", [])
            if e["to"] in nodes
            and e["to"] not in seen
            and nodes[e["to"]]["layer"] > layer
        ]
        if not exits:
            break
        nxt = rng.choice(exits)
        seen.add(nxt)
        path.append((nxt, nodes[nxt]["layer"]))
        cur = nxt
    return path


def project(run: Run, vnow: datetime, graph: dict, slot: str) -> State | None:
    """The participant row for ``run`` as seen at ``vnow``, or None if not joined yet.

    The path and the per-node times come from an RNG seeded per (slot, user) so a
    run projects identically whatever the scenario.
    """
    if run.join_at > vnow:
        return None
    if run.start > vnow:
        return State(ParticipantStatus.REGISTERED, 0, 0, None, None, {}, None, 0)
    rng = random.Random(f"{slot}:{run.user.id}")
    path = walk(graph, rng)
    total_ms = int((run.end - run.start).total_seconds() * 1000)
    # cumulative igt at each node of the path, front-loaded a little
    weights = [rng.uniform(0.6, 1.4) for _ in path[1:]]
    acc, cum = 0.0, [0]
    for w in weights:
        acc += w
        cum.append(acc)
    scale = total_ms / (cum[-1] or 1)
    igts = [int(c * scale) for c in cum]
    playing = run.end > vnow
    if playing:
        frac = (vnow - run.start) / (run.end - run.start)
        reached = max(1, int(frac * run.depth * (len(path) - 1)) + 1)
        igt_ms = int(frac * total_ms)
    elif run.finished:
        reached = len(path)
        igt_ms = total_ms
    else:
        reached = max(2, int(run.depth * (len(path) - 1)) + 1)
        igt_ms = total_ms
    reached = min(reached, len(path))
    # Each runner favours one weapon (picked from their id) and dabbles in another.
    key = int(str(run.user.id)[-4:], 16)
    favourite = WEAPON_IDS[key % len(WEAPON_IDS)]
    other = WEAPON_IDS[(key + 3) % len(WEAPON_IDS)]
    history = [
        {
            "node_id": node,
            "igt_ms": igts[i],
            "type": "spawn" if i == 0 else "fog",
            "weapons": [
                {"ids": [favourite + 25], "ticks": rng.randint(20, 60)},
                {"ids": [other + 10], "ticks": rng.randint(0, 15)},
            ],
        }
        for i, (node, _layer) in enumerate(path[:reached])
    ]
    entry_igts = {str(path[i][1]): igts[i] for i in range(reached)}
    node, layer = path[reached - 1]
    if playing:
        status = ParticipantStatus.PLAYING
    elif run.finished:
        status = ParticipantStatus.FINISHED
    else:
        status = ParticipantStatus.ABANDONED
    return State(
        status=status,
        igt_ms=igt_ms,
        current_layer=layer,
        current_zone=node,
        zone_history=history,
        layer_entry_igts=entry_igts,
        finished_at=None if playing else run.end,
        death_count=rng.randint(0, 3) + int(igt_ms / 180_000 * rng.uniform(0.3, 1.2)),
    )


def duration(pool: str, skill: float, rng: random.Random) -> timedelta:
    minutes = BASE_MINUTES[pool] * skill * rng.lognormvariate(0, 0.12)
    return timedelta(minutes=minutes)


def plan_qualifier(
    runners: list[Runner], viewer: User | None, rng: random.Random
) -> dict[str, list[Run]]:
    """Runs per qualifier slot, ``qualifier:<mode>:<n>``."""
    runs: dict[str, list[Run]] = {
        f"qualifier:{m}:{i}": [] for m in MODES for i in (1, 2)
    }
    window_start = STARTS + timedelta(hours=1)
    window_end = CUT - timedelta(hours=5)
    span = (window_end - window_start).total_seconds()
    others = [r for r in runners if viewer is None or r.user.id != viewer.id]
    partial = set(rng.sample(others, 8))
    colors: dict[str, int] = {slot: 0 for slot in runs}

    def add(
        slot: str,
        user: User,
        join_at: datetime,
        start: datetime,
        end: datetime,
        finished: bool,
        depth: float,
    ) -> None:
        runs[slot].append(Run(user, join_at, start, end, finished, depth, colors[slot]))
        colors[slot] += 1

    for runner in others:
        skipped_mode = rng.choice(MODES) if runner in partial else None
        for mode in MODES:
            if mode == skipped_mode:
                continue
            all_seeds = list(range(1, SEEDS_PER_MODE + 1))
            seeds = all_seeds[:1] if rng.random() < 0.45 else all_seeds
            if rng.random() < 0.12:
                seeds = all_seeds[-1:]
            for n in seeds:
                start = window_start + timedelta(seconds=rng.uniform(0, span))
                dur = duration(mode, runner.skill, rng)
                finished = rng.random() < 0.86
                depth = 1.0 if finished else rng.uniform(0.15, 0.85)
                end = start + (dur if finished else dur * depth * rng.uniform(0.8, 1.1))
                join_at = start - timedelta(minutes=rng.uniform(2, 180))
                add(
                    f"qualifier:{mode}:{n}",
                    runner.user,
                    join_at,
                    start,
                    end,
                    finished,
                    depth,
                )

    if viewer is None:
        return runs
    # The viewer plays one seed of every card state, all visible at once in the
    # qualifier scenario: done, DNF, still playing, joined but not started, and
    # one seed never entered.
    skill = next(r.skill for r in runners if r.user.id == viewer.id)
    s = D("2026-09-24T20:00")
    add(
        "qualifier:standard:1",
        viewer,
        s - timedelta(minutes=20),
        s,
        s + duration("standard", skill, rng),
        True,
        1.0,
    )
    s = D("2026-09-25T20:00")
    add(
        "qualifier:uwyg_major:1",
        viewer,
        s - timedelta(minutes=10),
        s,
        s + timedelta(minutes=24),
        False,
        0.4,
    )
    s = D("2026-09-27T14:30")
    add(
        "qualifier:uwyg_major:2",
        viewer,
        s - timedelta(minutes=5),
        s,
        s + duration("uwyg_major", skill, rng),
        True,
        1.0,
    )
    s = D("2026-09-29T19:00")
    add(
        "qualifier:boss_rush:1",
        viewer,
        D("2026-09-27T13:00"),
        s,
        s + duration("boss_rush", skill, rng),
        True,
        1.0,
    )
    return runs


def plan_stage(
    key: str, field: list[User], skills: dict[uuid.UUID, float], rng: random.Random
) -> dict[str, list[Run]]:
    date, pools = STAGES[key]
    runs: dict[str, list[Run]] = {}
    prev_end = date
    for i, pool in enumerate(pools, start=1):
        # The evening's races follow one another: the next one starts once the
        # previous one is over (and at least an hour after the previous start).
        start = max(date + STAGE_RACE_GAP * (i - 1), prev_end + timedelta(minutes=10))
        slot_runs: list[Run] = []
        for color, user in enumerate(field):
            dur = duration(pool, skills[user.id], rng)
            finished = rng.random() < 0.92
            depth = 1.0 if finished else rng.uniform(0.3, 0.9)
            end = start + (dur if finished else dur * depth)
            slot_runs.append(
                Run(user, date - timedelta(days=1), start, end, finished, depth, color)
            )
        runs[f"{key}:{i}"] = slot_runs
        prev_end = max(r.end for r in slot_runs)
    return runs


def stage_bounds(runs: list[Run]) -> tuple[datetime, datetime]:
    return runs[0].start, max(r.end for r in runs) + timedelta(minutes=2)


# --- transient projection for the service functions -------------------------


def fake_race(
    runs: list[Run], vnow: datetime, graph: dict, slot: str, race_end: datetime
) -> SimpleNamespace:
    """A stand-in Race the pure scoring functions accept, without touching the DB."""
    status = RaceStatus.FINISHED if vnow >= race_end else RaceStatus.RUNNING
    parts = []
    for run in runs:
        st = project(run, vnow, graph, slot)
        if st is None:
            continue
        parts.append(
            SimpleNamespace(
                id=uuid.uuid4(),
                user_id=run.user.id,
                status=st.status,
                igt_ms=st.igt_ms,
                current_layer=st.current_layer,
                zone_history=st.zone_history,
            )
        )
    return SimpleNamespace(status=status, participants=parts)


# --- database ---------------------------------------------------------------


async def pick_seed(db, pool: str) -> Seed:
    seed = (
        await db.execute(
            select(Seed)
            .where(Seed.pool_name == pool, Seed.status == SeedStatus.AVAILABLE)
            .order_by(Seed.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if seed is None:
        raise SystemExit(f"no available seed in pool {pool}")
    seed.status = SeedStatus.CONSUMED
    return seed


async def ensure_race(
    db, event: Event, slot: str, name: str, pool: str, organizer: User, **fields
) -> Race:
    """The race this run manages in ``slot``, created on first use.

    Found by its slot when a previous run left it attached, by its name when
    that run detached it (the announce scenario does), created otherwise. Names
    match the ones docs/EVENTS.md has an organizer give real races, so the page
    shortens them the same way it will in production; adopting a race that
    happens to carry one is why this tool refuses a non-local database.
    """
    by_slot = select(Race).where(Race.event_id == event.id, Race.event_slot == slot)
    by_name = select(Race).where(Race.name == name, Race.event_id.is_(None))
    for stmt in (by_slot, by_name):
        race = (
            (await db.execute(stmt.options(selectinload(Race.seed)))).scalars().first()
        )
        if race is not None:
            race.name = name
            break
    else:
        seed = await pick_seed(db, pool)
        race = Race(
            name=name, organizer_id=organizer.id, seed_id=seed.id, seed=seed, config={}
        )
        db.add(race)
        await db.flush()
    for k, v in fields.items():
        setattr(race, k, v)
    return race


async def pick_roster(
    db, viewer: User | None, real_now: datetime, rng: random.Random
) -> tuple[list[Runner], list[User]]:
    """Runners and casters drawn from the local users, by their finished races."""
    # Only races outside any event count, so a previous run's fabricated
    # participations do not push its own newcomers out of the pool.
    finished_count = (
        select(Participant.user_id, func.count().label("n"))
        .join(Race, Race.id == Participant.race_id)
        .where(
            Participant.status == ParticipantStatus.FINISHED, Race.event_id.is_(None)
        )
        .group_by(Participant.user_id)
        .subquery()
    )
    not_the_viewer = User.id != viewer.id if viewer else true()
    veterans = list(
        (
            await db.execute(
                select(User)
                .join(finished_count, finished_count.c.user_id == User.id)
                .where(
                    User.twitch_avatar_url.isnot(None),
                    finished_count.c.n >= 15,
                    not_the_viewer,
                )
                .order_by(finished_count.c.n.desc())
                .limit(40)
            )
        )
        .scalars()
        .all()
    )
    newcomers = list(
        (
            await db.execute(
                select(User)
                .outerjoin(finished_count, finished_count.c.user_id == User.id)
                .where(
                    User.twitch_avatar_url.isnot(None),
                    func.coalesce(finished_count.c.n, 0) <= 2,
                    User.last_seen > real_now - timedelta(days=120),
                    not_the_viewer,
                )
                .order_by(User.last_seen.desc())
                .limit(30)
            )
        )
        .scalars()
        .all()
    )
    if len(veterans) < 26 or len(newcomers) < 9:
        raise SystemExit(
            f"not enough users to build a roster: {len(veterans)} veterans, "
            f"{len(newcomers)} newcomers (need 26 and 9)"
        )
    vets = rng.sample(veterans[:34], 26)
    casters = [u for u in veterans if u not in vets][:2]
    news = rng.sample(newcomers, 9)
    runners = [Runner(viewer, 0.93, False)] if viewer else []
    runners += [Runner(u, rng.uniform(0.78, 1.32), False) for u in vets[:24]]
    runners += [Runner(u, rng.uniform(1.04, 1.4), True) for u in news]
    runners[-1].skill = 0.9  # one newcomer strong enough to be seeded into a semi
    return runners, casters


async def simulate(stage: str, slug: str, viewer_name: str | None, force: bool) -> None:
    if not force:
        check_local_database()
    scenario = SCENARIOS[stage]
    real_now = datetime.now(UTC).replace(microsecond=0)
    vnow = scenario if isinstance(scenario, datetime) else None

    def T(dt: datetime) -> datetime:
        # delta is bound once the virtual now is known; calling T before that
        # raises rather than writing unshifted dates.
        return dt + delta

    rng = random.Random(RNG_SEED)
    async with async_session_maker() as db:
        event = (
            await db.execute(select(Event).where(Event.slug == slug))
        ).scalar_one_or_none()
        if event is None:
            raise SystemExit(
                f"no event with slug {slug!r}: create it from the admin Events tab"
            )
        viewer = None
        if viewer_name:
            viewer = (
                await db.execute(
                    select(User).where(User.twitch_username == viewer_name)
                )
            ).scalar_one_or_none()
            if viewer is None:
                raise SystemExit(f"no user named {viewer_name!r}")
        organizer = (
            viewer
            or (
                await db.execute(
                    select(User).where(User.role == UserRole.ADMIN).limit(1)
                )
            ).scalar_one_or_none()
        )
        if organizer is None:
            raise SystemExit(
                "no admin user to organize the races, and no --viewer given"
            )

        config = EventConfig.model_validate(event.config)
        mismatch = []
        if config.mode_keys() != MODES:
            mismatch.append(f"modes {config.mode_keys()} != {MODES}")
        if config.seeds_per_mode != SEEDS_PER_MODE:
            mismatch.append(
                f"seeds_per_mode {config.seeds_per_mode} != {SEEDS_PER_MODE}"
            )
        if [st.key for st in config.stages] != list(STAGES):
            mismatch.append(
                f"stages {[st.key for st in config.stages]} != {list(STAGES)}"
            )
        if mismatch:
            raise SystemExit(
                f"event {slug!r} does not match this tool's season: "
                + "; ".join(mismatch)
            )

        runners, casters = await pick_roster(db, viewer, real_now, rng)
        skills = {r.user.id: r.skill for r in runners}
        newcomer_flags = {r.user.id: r.newcomer for r in runners}
        users_by_id = {r.user.id: r.user for r in runners}

        # --- season plan ---
        qual_runs = plan_qualifier(runners, viewer, rng)
        qual_races: dict[str, Race] = {}
        for mode in MODES:
            for n in range(1, SEEDS_PER_MODE + 1):
                slot = f"qualifier:{mode}:{n}"
                qual_races[slot] = await ensure_race(
                    db,
                    event,
                    slot,
                    f"{event.name} qualifier - {POOL_LABELS[mode]} - Seed {n}",
                    mode,
                    organizer,
                    is_public=False,
                    open_registration=True,
                    max_participants=None,
                    late_join_window_minutes=10080,
                    race_duration_minutes=10080,
                    exclude_from_stats=True,
                    daily_date=None,
                    custom_rules="Same seed for everyone; one sitting per run.",
                )

        def graph_of(race: Race) -> dict:
            return race.seed.graph_json

        # The ladder as it stands at the cut decides the playoff fields.
        final_qual = [
            (
                Slot("qualifier", mode, n),
                fake_race(
                    qual_runs[f"qualifier:{mode}:{n}"],
                    CUT,
                    graph_of(qual_races[f"qualifier:{mode}:{n}"]),
                    f"qualifier:{mode}:{n}",
                    CUT,
                ),
            )
            for mode in MODES
            for n in range(1, SEEDS_PER_MODE + 1)
        ]
        ladder = compute_ladder(MODES, final_qual)
        groups = compute_qualified(ladder, config, newcomer_flags)
        fields: dict[str, list[User]] = {}
        for key in ("semi_a", "semi_b", "newcomers"):
            slots = groups[key]
            if any(s.user_id is None for s in slots):
                raise SystemExit(
                    f"group {key} has an open slot: too few ranked runners"
                )
            fields[key] = [users_by_id[s.user_id] for s in slots]

        stage_runs: dict[str, dict[str, list[Run]]] = {
            key: plan_stage(key, fields[key], skills, rng)
            for key in ("semi_a", "semi_b", "newcomers")
        }
        stage_races: dict[str, Race] = {}
        for key, (_date, pools) in STAGES.items():
            for i, pool in enumerate(pools, start=1):
                slot = f"{key}:{i}"
                stage_races[slot] = await ensure_race(
                    db,
                    event,
                    slot,
                    f"{STAGE_LABELS[key]} - Race {i} - {POOL_LABELS[pool]}",
                    pool,
                    organizer,
                    open_registration=False,
                    max_participants=4,
                    late_join_window_minutes=None,
                    race_duration_minutes=120,
                    exclude_from_stats=False,
                    daily_date=None,
                    custom_rules=None,
                )

        # The semis' advancing runners make the final's field.
        semi_results = {}
        for key in ("semi_a", "semi_b"):
            races = []
            for slot, runs in stage_runs[key].items():
                _s, end = stage_bounds(runs)
                races.append(
                    fake_race(runs, end, graph_of(stage_races[slot]), slot, end)
                )
            semi_results[key] = compute_stage_results(config.stage(key), races, 2)
        fields["final"] = [
            users_by_id[e.user_id]
            for key in ("semi_a", "semi_b")
            for e in semi_results[key].entries
            if e.advances
        ]
        stage_runs["final"] = plan_stage("final", fields["final"], skills, rng)

        # A live scenario sits 15 minutes into the evening's second race, so
        # race 1 is over, race 2 runs and race 3 is still to come.
        if isinstance(scenario, tuple):
            _kind, live_key = scenario
            vnow = stage_runs[live_key][f"{live_key}:2"][0].start + timedelta(
                minutes=15
            )
        delta = real_now - vnow

        # --- write ---
        managed = list(qual_races.values()) + list(stage_races.values())
        ids = [r.id for r in managed]
        await db.execute(delete(Participant).where(Participant.race_id.in_(ids)))
        await db.execute(delete(Caster).where(Caster.race_id.in_(ids)))
        # Any other race holding one of the event's slots would collide with the
        # unique constraint on (event_id, event_slot) once we claim it.
        await db.execute(
            update(Race)
            .where(Race.event_id == event.id, Race.id.notin_(ids))
            .values(event_id=None, event_slot=None)
        )

        def add_participants(race: Race, runs: list[Run], slot: str) -> None:
            for run in runs:
                st = project(run, vnow, graph_of(race), slot)
                if st is None:
                    continue
                db.add(
                    Participant(
                        race_id=race.id,
                        user_id=run.user.id,
                        mod_token=secrets.token_urlsafe(24),
                        status=st.status,
                        igt_ms=st.igt_ms,
                        current_layer=st.current_layer,
                        current_zone=st.current_zone,
                        zone_history=st.zone_history,
                        layer_entry_igts=st.layer_entry_igts,
                        finished_at=T(st.finished_at) if st.finished_at else None,
                        # The inactivity monitor only abandons a PLAYING runner
                        # whose last IGT change is known and stale, so leaving
                        # this None keeps the fake live runners alive.
                        last_igt_change_at=None,
                        death_count=st.death_count,
                        color_index=run.color_index,
                    )
                )

        # Qualifier races: attached from the announcement on, except in the
        # bare "announce" scenario where the event page has nothing yet.
        attach_qual = stage != "announce"
        for slot, race in qual_races.items():
            race.event_id = event.id if attach_qual else None
            race.event_slot = slot if attach_qual else None
            race.scheduled_at = T(STARTS)
            if vnow < STARTS:
                race.status = RaceStatus.SETUP
                race.started_at = None
                race.seeds_released_at = None
                race.finished_at = None
            else:
                race.status = RaceStatus.RUNNING if vnow < CUT else RaceStatus.FINISHED
                race.started_at = T(STARTS)
                race.seeds_released_at = T(STARTS)
                race.finished_at = T(CUT) if vnow >= CUT else None
                add_participants(race, qual_runs[slot], slot)

        # Stage races: created (and public) a couple of days before the evening.
        for key, (date, _pools) in STAGES.items():
            created = vnow >= date - STAGE_ATTACH_LEAD
            for slot, runs in stage_runs[key].items():
                race = stage_races[slot]
                start, end = stage_bounds(runs)
                race.event_id = event.id if created else None
                race.event_slot = slot if created else None
                race.is_public = created
                race.scheduled_at = T(start)
                if not created or vnow < start:
                    race.status = RaceStatus.SETUP
                    race.started_at = None
                    race.seeds_released_at = None
                    race.finished_at = None
                else:
                    race.status = (
                        RaceStatus.RUNNING if vnow < end else RaceStatus.FINISHED
                    )
                    race.started_at = T(start)
                    race.seeds_released_at = T(start - timedelta(minutes=10))
                    race.finished_at = T(end) if vnow >= end else None
                if created:
                    add_participants(race, runs, slot)
                    for caster in casters:
                        db.add(Caster(race_id=race.id, user_id=caster.id))

        # Event dates and stage dates, shifted onto the real clock.
        event.starts_at = T(STARTS)
        event.qualifier_ends_at = T(CUT)
        event.ends_at = T(ENDS)
        cfg = dict(event.config)
        cfg["announced_at"] = T(ANNOUNCE).isoformat().replace("+00:00", "Z")
        cfg["stages"] = [
            {**s, "date": T(STAGES[s["key"]][0]).isoformat().replace("+00:00", "Z")}
            for s in cfg["stages"]
        ]
        cfg["phase_override"] = None
        event.config = cfg
        EventConfig.model_validate(cfg)

        await db.commit()

    print(f"{stage}: virtual now {vnow:%a %d %b %H:%M}Z, shifted by {delta}")
    print(
        f"qualifier {T(STARTS):%a %d %b %H:%M} to {T(CUT):%a %d %b %H:%M}, ends {T(ENDS):%a %d %b}"
    )
    for key, (date, _pools) in STAGES.items():
        print(
            f"  {key:10s} {T(date):%a %d %b %H:%M}Z  {[u.twitch_username for u in fields[key]]}"
        )
    print("ladder after the cut:")
    for e in ladder[:10]:
        tag = " new" if newcomer_flags[e.user_id] else ""
        name = users_by_id[e.user_id].twitch_username
        print(f"  {e.rank!s:>4} {name:18s} {e.total!s:>5}{tag}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Put a local database into one life stage of a tournament event."
    )
    parser.add_argument("stage", choices=sorted(SCENARIOS), help="the state to project")
    parser.add_argument(
        "--slug", default="season-one", help="event slug (default: season-one)"
    )
    parser.add_argument(
        "--viewer",
        help="twitch username to give every seed-card state",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="write even though the database is not on this machine",
    )
    args = parser.parse_args()
    asyncio.run(simulate(args.stage, args.slug, args.viewer, args.force))


if __name__ == "__main__":
    main()
