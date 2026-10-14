#!/usr/bin/env python3
"""Play one event stage's races live on a local server, the way the runners' mods would.

Meant for checking the cast scenes (docs/CAST_OVERLAYS.md) over a whole
evening before a broadcast: unlike tools/simulate_event.py, which writes each
state straight into the database, every update here travels the real path
(mod WebSocket, REST, the spectator broadcasts), so the scenes go through the
transitions a real evening puts them through. Run tools/simulate_event.py
first to put the stage's races in setup with their field registered
(`newcomers_done` leaves Group B for tonight).

Each race in turn: every runner's mod connects over /ws/mod/<race> with the
participant's own mod token and reports ready; the organizer releases the
seeds and starts the race over the REST API; the in-game time then runs
--speed times faster than the wall clock (the wrong-save guard lets a report
outrun it by 60 seconds, so the default 30x leaves room), each runner crossing
fog gates along a path through the seed's graph, dying now and then and
swapping weapons once. Finishes are spread over the cutoff and reported one
per tick, so the run never depends on how the server orders two finishes
landing in the same few milliseconds. The race ends on its own
once every runner is out. What happens to whom depends on the race's number,
cycling past the third: in race 1 the slowest runner is eliminated by the
playoff IGT cutoff, in race 2 everyone finishes, in race 3 the organizer
disqualifies one runner on the way.

With --shots DIR (Playwright needed: `uv run --with playwright`), every cast
scene stays open in a headless Chrome at 1920x1080 for the whole evening, as
OBS browser sources would, and is captured into DIR at each checkpoint (setup,
countdown, early, mid, after the disqualification, first finish, late, end,
and once more after the talk scene has re-read the event), with the pages'
errors in DIR/errors.jsonl. The talk scene stays up all evening; each race's
scenes open when its setup starts.

Local databases only: the tokens are read from it and kept in memory, and the
races it drives get real runs. Since simulate_event.py takes a run with mod
activity for a real one, the participants' last IGT change is cleared once
each race is over. Do not write files under server/ while it runs: the dev
server's --reload restarts on any change there and drops every WebSocket.

Usage:
    cd server && uv run python ../tools/simulate_event.py newcomers_done --slug sim-season
    cd server && uv run --with playwright python ../tools/simulate_match.py group_b \\
        --slug sim-season --shots /tmp/group_b
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Must run from server/ (cd server && uv run python ../tools/simulate_match.py)
sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402
import websockets  # noqa: E402
from simulate_event import (  # noqa: E402
    BASE_MINUTES,
    LOCAL_HOSTS,
    WEAPON_IDS,
    check_local_database,
    walk,
)
from sqlalchemy import func, select, update  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from speedfog_racing.database import async_session_maker  # noqa: E402
from speedfog_racing.models import (  # noqa: E402
    Caster,
    Event,
    Participant,
    Race,
    RaceStatus,
    User,
)
from speedfog_racing.schemas import EventConfig  # noqa: E402
from speedfog_racing.websocket.schemas import PROTOCOL_VERSION  # noqa: E402

MIN = 60_000
TICK = 1.0  # seconds between two reports of a runner, as the mod sends them
DAGGER = 1000000  # held in the left hand now and then
TERMINAL = ("finished", "abandoned", "disqualified")


def log(*parts: object) -> None:
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


# --- plan -------------------------------------------------------------------


@dataclass
class Runner:
    name: str
    participant_id: str
    mod_token: str
    total_ms: int  # finish time, or how far a run that does not finish goes
    outcome: str  # "finish", "slow" (the IGT cutoff eliminates it), "dq"
    dq_at_ms: int
    offset_ms: int  # loading a little later than the others
    entries: list[tuple[int, int]]  # (igt_ms, event flag) per fog gate
    deaths_at: list[int]
    swap_at_ms: int
    weapons: tuple[int, int]  # favourite, then the one swapped to
    finish_flag: int
    ws: Any = None
    message_id: int = 0
    sent: int = 0
    done: bool = False
    last_error: str = ""
    reader: asyncio.Task[None] | None = None


def plan_race(
    race: Race, number: int, cutoff_min: int, rng: random.Random
) -> list[Runner]:
    """Each runner's run in race ``number`` of the stage (see the module docstring)."""
    graph = race.seed.graph_json
    flags: dict[str, list[int]] = {}
    for flag, node in graph["event_map"].items():
        flags.setdefault(node, []).append(int(flag))
    base = BASE_MINUTES.get(race.seed.pool_name, 50) * MIN
    field_ = sorted(race.participants, key=lambda p: p.color_index)
    order = rng.sample(field_, len(field_))
    best = int(base * rng.uniform(0.85, 1.0))
    totals, t = [], best
    for i in range(len(order)):
        totals.append(t)
        # Every finisher inside the cutoff, spread evenly enough over it.
        step = (cutoff_min - 1) / max(1, len(order) - 1)
        t += int(rng.uniform(step / 2, step) * MIN)
    script = (number - 1) % 3
    runners = []
    for i, p in enumerate(order):
        outcome = "finish"
        total = totals[i]
        if script == 0 and i == len(order) - 1:
            outcome, total = "slow", best + (cutoff_min + 5) * MIN
        if script == 2 and i == len(order) // 2:
            outcome = "dq"
        path = [node for node, _layer in walk(graph, rng)]
        run_ms = int(total * 0.94)  # the final boss takes the rest
        weights = [rng.uniform(0.6, 1.4) for _ in path[1:]]
        acc, entries = 0.0, []
        for node, w in zip(path[1:], weights):
            acc += w
            if flags.get(node):
                entries.append((acc, rng.choice(flags[node])))
        entries = [(int(a / acc * run_ms), f) for a, f in entries]
        key = int(str(p.user_id)[-4:], 16)
        runners.append(
            Runner(
                name=p.user.twitch_username,
                participant_id=str(p.id),
                mod_token=p.mod_token,
                total_ms=total,
                outcome=outcome,
                dq_at_ms=int(best * 0.4),
                offset_ms=rng.randint(0, 3000),
                entries=entries,
                deaths_at=sorted(
                    rng.randint(2 * MIN, int(total * 0.97))
                    for _ in range(rng.randint(1, 6))
                ),
                swap_at_ms=int(total * rng.uniform(0.35, 0.55)),
                weapons=(
                    WEAPON_IDS[key % len(WEAPON_IDS)],
                    WEAPON_IDS[(key + 3) % len(WEAPON_IDS)],
                ),
                finish_flag=int(graph["finish_event"]),
            )
        )
    return runners


# --- scenes -----------------------------------------------------------------


class Shooter:
    """The cast scenes, open in a headless Chrome for the whole evening."""

    def __init__(self, out: Path, web: str) -> None:
        self.out = out
        self.web = web
        self.pages: dict[str, Any] = {}
        self.errors: list[dict[str, str]] = []

    async def start(self, caster_token: str | None) -> None:
        from playwright.async_api import async_playwright  # noqa: PLC0415

        self.pw = await async_playwright().start()
        try:
            self.browser = await self.pw.chromium.launch(headless=True)
        except Exception:  # noqa: BLE001
            # Playwright's own Chromium not downloaded: the installed Chrome.
            self.browser = await self.pw.chromium.launch(
                headless=True, channel="chrome"
            )
        size = {"width": 1920, "height": 1080}
        self.anon = await self.browser.new_context(viewport=size)
        # Cast Setup shows to the race's casters only.
        self.auth = await self.browser.new_context(viewport=size)
        if caster_token:
            await self.auth.add_init_script(
                "try { localStorage.setItem('speedfog_token', "
                f"{json.dumps(caster_token)}); }} catch (e) {{}}"
            )

    async def stop(self) -> None:
        # Safe on a start that failed halfway.
        if getattr(self, "browser", None) is not None:
            await self.browser.close()
        if getattr(self, "pw", None) is not None:
            await self.pw.stop()

    def _watch(self, name: str, page: Any) -> None:
        def note(kind: str, text: str) -> None:
            self.errors.append({"page": name, "type": kind, "text": text[:500]})

        page.on(
            "console",
            lambda m: note(m.type, m.text) if m.type in ("error", "warning") else None,
        )
        page.on("pageerror", lambda e: note("pageerror", str(e)))
        page.on(
            "requestfailed", lambda r: note("requestfailed", f"{r.url} {r.failure}")
        )
        page.on(
            "response",
            lambda r: note(f"http{r.status}", r.url) if r.status >= 400 else None,
        )

    async def open(self, name: str, path: str, auth: bool = False) -> None:
        page = await (self.auth if auth else self.anon).new_page()
        self._watch(name, page)
        await page.goto(self.web + path, wait_until="domcontentloaded")
        self.pages[name] = page

    async def close(self, prefix: str) -> None:
        for name in [n for n in self.pages if n.startswith(prefix)]:
            await self.pages.pop(name).close()

    async def shoot(self, label: str, only: list[str] | None = None) -> None:
        folder = self.out / label
        folder.mkdir(parents=True, exist_ok=True)
        for name, page in self.pages.items():
            if only and not any(name.startswith(o) for o in only):
                continue
            try:
                await page.screenshot(path=str(folder / f"{name}.png"))
            except Exception as e:  # noqa: BLE001
                # A page the dev server is hot-reloading can time out: the
                # evening goes on without that capture.
                log("capture failed", label, name, str(e).splitlines()[0])
        if self.errors:
            with (self.out / "errors.jsonl").open("a") as f:
                for e in self.errors:
                    f.write(json.dumps({"at": label, **e}) + "\n")
            self.errors.clear()
        log("captured", label)


# --- driving ----------------------------------------------------------------


class RaceDriver:
    def __init__(
        self,
        number: int,
        race: Race,
        runners: list[Runner],
        org_token: str,
        args: argparse.Namespace,
        http: httpx.AsyncClient,
        shooter: Shooter | None,
    ) -> None:
        self.number = number
        self.race = race
        self.race_id = str(race.id)
        self.runners = runners
        self.headers = {"Authorization": f"Bearer {org_token}"}
        self.args = args
        self.http = http
        self.shooter = shooter
        self.clock_ms = 0  # the race's in-game clock
        self.started = False  # mods report only once the race runs
        self.prefix = f"r{number}_"

    async def open_scenes(self) -> None:
        if self.shooter is None:
            return
        casters = [c.user.twitch_username for c in self.race.casters][:2]
        params = "&".join(
            [f"cams={len(casters)}"]
            + [f"c{i + 1}={name}" for i, name in enumerate(casters)]
            + [f"event={self.args.slug}"]
        )
        joined = [
            p.user.twitch_username
            for p in sorted(self.race.participants, key=lambda p: p.color_index)
        ]
        duel = joined[1::2][:2] if len(joined) >= 4 else joined[:2]
        base = f"/overlay/cast/race/{self.race_id}"
        s, p = self.shooter, self.prefix
        await s.open(p + "quad", f"{base}/quad?{params}")
        await s.open(p + "focus", f"{base}/focus?{params}&focus=2")
        await s.open(p + "duel", f"{base}/duel?{params}&p1={duel[0]}&p2={duel[-1]}")
        await s.open(p + "metro", f"{base}/metro?{params}")
        await s.open(p + "browser", f"{base}/browser?{params}")
        await s.open(p + "castsetup", f"/race/{self.race_id}?cast=1", auth=True)

    async def read(self, r: Runner) -> None:
        try:
            async for raw in r.ws:
                msg = json.loads(raw)
                kind = msg.get("type")
                if kind == "ping":
                    await r.ws.send(json.dumps({"type": "pong"}))
                elif kind in ("auth_error", "error"):
                    line = f"{kind}: {msg.get('message')} {msg.get('code', '')}"
                    if line != r.last_error:
                        r.last_error = line
                        log(f"[{r.name}] {line}")
                elif kind == "leaderboard_update":
                    for info in msg.get("participants", []):
                        ended = info.get("status") in TERMINAL
                        if info.get("id") == r.participant_id and ended and not r.done:
                            r.done = True
                            log(
                                f"[{r.name}] {info['status']} at {info['igt_ms'] / MIN:.2f} min"
                            )
        except websockets.ConnectionClosed as e:
            if e.code != 1000:
                log(f"[{r.name}] connection closed {e.code} {e.reason}")

    async def connect(self) -> None:
        for r in self.runners:
            r.ws = await websockets.connect(f"{self.args.ws}/ws/mod/{self.race_id}")
            await r.ws.send(
                json.dumps(
                    {
                        "type": "auth",
                        "mod_token": r.mod_token,
                        "protocol_version": PROTOCOL_VERSION,
                        "mod_version": "simulate_match",
                    }
                )
            )
            reply = json.loads(await r.ws.recv())
            if reply.get("type") != "auth_ok":
                raise SystemExit(f"{r.name}: mod auth refused: {reply}")
            r.reader = asyncio.create_task(self.read(r))
            await r.ws.send(json.dumps({"type": "ready"}))
        log(f"race {self.number}: {len(self.runners)} mods connected and ready")

    async def disconnect(self) -> None:
        for r in self.runners:
            if r.ws is not None:
                await r.ws.close()

    async def post(self, path: str, **kw: Any) -> dict[str, Any]:
        resp = await self.http.post(
            f"{self.args.api}/api/races/{self.race_id}{path}",
            headers=self.headers,
            **kw,
        )
        if resp.status_code >= 400:
            raise SystemExit(f"POST {path}: {resp.status_code} {resp.text[:300]}")
        return dict(resp.json())

    async def status(self) -> str:
        resp = await self.http.get(
            f"{self.args.api}/api/races/{self.race_id}", headers=self.headers
        )
        return str(resp.json()["status"])

    async def tick(self) -> None:
        """Every runner still out reports up to the race clock."""
        finish_sent = False
        for r in self.runners:
            if r.done:
                continue
            igt = max(0, self.clock_ms - r.offset_ms)
            if r.outcome == "dq" and igt >= r.dq_at_ms:
                r.done = True
                await self.post(
                    f"/participants/{r.participant_id}/disqualify",
                    json={"reason": "Simulated: a debug flag was observed."},
                )
                log(f"race {self.number}: {r.name} disqualified at {igt / MIN:.1f} min")
                continue
            while r.sent < len(r.entries) and r.entries[r.sent][0] <= igt:
                at, flag = r.entries[r.sent]
                r.message_id += 1
                await r.ws.send(
                    json.dumps(
                        {
                            "type": "event_flag",
                            "flag_id": flag,
                            "igt_ms": at,
                            "message_id": r.message_id,
                        }
                    )
                )
                r.sent += 1
            if r.outcome == "finish" and igt >= r.total_ms:
                # One finish per tick: see the module docstring.
                if finish_sent:
                    continue
                finish_sent = True
                r.message_id += 1
                await r.ws.send(
                    json.dumps(
                        {
                            "type": "event_flag",
                            "flag_id": r.finish_flag,
                            "igt_ms": r.total_ms,
                            "message_id": r.message_id,
                        }
                    )
                )
                r.done = True
                log(
                    f"race {self.number}: {r.name} finishes in {r.total_ms / MIN:.2f} min"
                )
                continue
            favourite, other = r.weapons
            right = (favourite if igt < r.swap_at_ms else other) + 25
            left = DAGGER + 10 if igt % (7 * MIN) < 3 * MIN else None
            await r.ws.send(
                json.dumps(
                    {
                        "type": "status_update",
                        "igt_ms": min(igt, r.total_ms),
                        "death_count": sum(1 for d in r.deaths_at if d <= igt),
                        "weapons": [left, right],
                    }
                )
            )

    async def run_until(self, clock_ms: int) -> None:
        while self.clock_ms < clock_ms:
            self.clock_ms = min(
                clock_ms, self.clock_ms + int(self.args.speed * TICK * 1000)
            )
            await self.tick()
            await asyncio.sleep(TICK)

    async def checkpoint(self, name: str, only: list[str] | None = None) -> None:
        """Hold the race clock (the mods keep reporting) while the scenes are captured."""
        if self.shooter is None:
            return
        for _ in range(3):  # let the scenes settle
            if self.started:
                await self.tick()
            await asyncio.sleep(TICK)
        shot = asyncio.create_task(self.shooter.shoot(f"{self.prefix}{name}", only))
        while not shot.done():
            if self.started:
                await self.tick()
            await asyncio.sleep(0.5)
        await shot

    async def run(self) -> None:
        await self.open_scenes()
        try:
            await self.connect()
            await self.play()
        finally:
            # An aborted run too (a dropped connection, Ctrl-C): no mod left
            # connected, and no run simulate_event.py would take for a real one.
            await self.disconnect()
            async with async_session_maker() as db:
                await db.execute(
                    update(Participant)
                    .where(Participant.race_id == self.race.id)
                    .values(last_igt_change_at=None)
                )
                await db.commit()

    async def play(self) -> None:
        await asyncio.sleep(3)
        await self.checkpoint("a_setup")
        if self.race.seeds_released_at is None:
            await self.post("/release-seeds")
        # started_at is the start itself, the server's countdown later.
        started_at = (await self.post("/start"))["started_at"]
        start = datetime.fromisoformat(started_at).timestamp()
        await asyncio.sleep(3)
        p = self.prefix
        await self.checkpoint("b_countdown", only=[p + "quad", p + "metro", "talk"])
        await asyncio.sleep(max(0.0, start - time.time()))
        self.started = True
        finishes = sorted(r.total_ms for r in self.runners if r.outcome == "finish")
        await self.run_until(6 * MIN)
        await self.checkpoint("c_early")
        await self.run_until(finishes[0] // 2)
        await self.checkpoint("d_mid")
        dq = [r.dq_at_ms for r in self.runners if r.outcome == "dq"]
        if dq:
            await self.run_until(dq[0] + 40_000)
            await self.checkpoint("e_after_dq")
        await self.run_until(finishes[0] + 35_000)
        await self.checkpoint("f_first_finish")
        await self.run_until(
            finishes[-2] + 35_000 if len(finishes) > 1 else finishes[0]
        )
        await self.checkpoint("g_late")
        last = max(r.total_ms for r in self.runners)
        while await self.status() != "finished":
            if self.clock_ms > last + 15 * MIN:
                log(f"race {self.number}: still running, finishing it by hand")
                await self.post("/finish")
                break
            self.clock_ms += int(self.args.speed * TICK * 1000)
            await self.tick()
            await asyncio.sleep(TICK)
        log(f"race {self.number}: over at {self.clock_ms / MIN:.1f} min of race clock")
        await asyncio.sleep(3)
        await self.checkpoint("h_end")
        if self.shooter is not None:
            await asyncio.sleep(35)  # the talk scene re-reads the event every 30 s
            await self.shooter.shoot(
                f"{self.prefix}i_after", only=["talk", p + "metro"]
            )


# --- main -------------------------------------------------------------------


async def load_races(
    slug: str, stage_key: str, force: bool
) -> tuple[Event, EventConfig, dict]:
    async with async_session_maker() as db:
        event = (
            await db.execute(select(Event).where(Event.slug == slug))
        ).scalar_one_or_none()
        if event is None:
            raise SystemExit(f"no event with slug {slug!r}")
        config = EventConfig.model_validate(event.config)
        stage = config.stage(stage_key) or next(
            (s for s in config.showcases if s.key == stage_key), None
        )
        if stage is None:
            raise SystemExit(f"event {slug!r} has no stage or showcase {stage_key!r}")
        # The same guard as simulate_event.py: a run with mod activity is a real one.
        real_runs = (
            await db.execute(
                select(func.count())
                .select_from(Participant)
                .join(Race, Race.id == Participant.race_id)
                .where(
                    Race.event_id == event.id,
                    Participant.last_igt_change_at.isnot(None),
                )
            )
        ).scalar_one()
        if real_runs and not force:
            raise SystemExit(
                f"event {slug!r} holds {real_runs} real runs: point the tool at a "
                "simulated copy (--slug), or pass --force"
            )
        races = (
            (
                await db.execute(
                    select(Race)
                    .where(
                        Race.event_id == event.id,
                        Race.event_slot.like(f"{stage_key}:%"),
                    )
                    .options(
                        selectinload(Race.participants).selectinload(Participant.user),
                        selectinload(Race.casters).selectinload(Caster.user),
                        selectinload(Race.seed),
                        selectinload(Race.organizer),
                    )
                )
            )
            .scalars()
            .all()
        )
        by_number = {
            int(r.event_slot.rsplit(":", 1)[1]): r for r in races if r.event_slot
        }
        return event, config, by_number


async def token_of(username: str) -> str | None:
    async with async_session_maker() as db:
        return (
            await db.execute(
                select(User.api_token).where(User.twitch_username == username)
            )
        ).scalar_one_or_none()


async def simulate(args: argparse.Namespace) -> None:
    if not args.force:
        check_local_database()
        # The tokens it sends are the database's: real ones on a production dump.
        for url in (args.api, args.ws):
            if (urlparse(url).hostname or "") not in LOCAL_HOSTS:
                raise SystemExit(
                    f"refusing to drive {url}; pass --force if it is local"
                )
    event, config, races = await load_races(args.slug, args.stage, args.force)
    numbers = args.races or sorted(races)
    if not numbers:
        raise SystemExit(f"{args.stage} has no race attached")
    for n in numbers:
        race = races.get(n)
        if race is None:
            raise SystemExit(f"{args.stage} has no race {n} attached")
        if race.status != RaceStatus.SETUP or len(race.participants) < 2:
            raise SystemExit(
                f"{race.name}: needs to be in setup with a field registered "
                "(run tools/simulate_event.py first)"
            )
    shooter = None
    async with httpx.AsyncClient(timeout=20) as http:
        try:
            if args.shots:
                first = races[numbers[0]]
                caster = (
                    first.casters[0].user.twitch_username if first.casters else None
                )
                shooter = Shooter(Path(args.shots), args.web)
                await shooter.start(await token_of(caster) if caster else None)
                casters = [c.user.twitch_username for c in first.casters][:2]
                talk = "&".join(
                    [f"cams={len(casters)}"]
                    + [f"c{i + 1}={c}" for i, c in enumerate(casters)]
                )
                await shooter.open(
                    "talk", f"/overlay/cast/event/{args.slug}/{args.stage}/talk?{talk}"
                )
            for n in numbers:
                race = races[n]
                rng = random.Random(f"{args.stage}:{n}")
                runners = plan_race(race, n, config.playoff_cutoff_minutes, rng)
                org_token = race.organizer.api_token
                if not org_token:
                    raise SystemExit(f"{race.name}: its organizer has no API token")
                if shooter is not None:
                    for prefix in [f"r{m}_" for m in numbers if m != n]:
                        await shooter.close(prefix)
                await RaceDriver(n, race, runners, org_token, args, http, shooter).run()
        finally:
            if shooter is not None:
                await shooter.stop()
    log("done")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Play one event stage's races live on a local server."
    )
    parser.add_argument(
        "stage", help="the stage or showcase key (group_b, semi_a, ...)"
    )
    parser.add_argument(
        "--slug", default="sim-season", help="event slug (default: sim-season)"
    )
    parser.add_argument(
        "--races",
        type=int,
        nargs="+",
        help="race numbers to play (default: all, in order)",
    )
    parser.add_argument(
        "--speed",
        type=int,
        default=30,
        help="in-game time per wall-clock time (max ~60)",
    )
    parser.add_argument("--shots", help="capture the cast scenes into this directory")
    parser.add_argument("--api", default="http://localhost:8000", help="the server")
    parser.add_argument(
        "--ws", default="ws://localhost:8000", help="the server's WebSocket"
    )
    parser.add_argument("--web", default="http://localhost:5173", help="the web app")
    parser.add_argument(
        "--force",
        action="store_true",
        help="drive an event holding real runs, or a database not on this machine",
    )
    args = parser.parse_args()
    if not 1 <= args.speed <= 60:
        parser.error("--speed must be between 1 and 60 (the wrong-save guard)")
    asyncio.run(simulate(args))


if __name__ == "__main__":
    main()
