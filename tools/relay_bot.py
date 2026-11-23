#!/usr/bin/env python3
"""Bot runners for testing relay races without the game (docs/RELAY.md).

A relay race plays one run per team, with one runner holding the baton at a
time, so even a lone tester needs a whole field. Each bot is a local user placed
in a named team of a relay race, whose "mod" is this script: it connects over
/ws/mod/<race> with the participant's own token and behaves as a well-behaved
mod does (the contract is the "Baton", "Gate" and "Lifecycle" sections of
docs/RELAY.md): it reports ready, passes the fresh-save gate with its first
report once the race runs, tells the server it waits at the Chapel
(`relay_ready`, again after every reconnection), answers a `relay_release` with
a character state (a plausible default, or the file --state names, checked
against the server's model at startup), answers a `relay_take` with
`relay_taken` and only then reports the team's progress, starting from the team
IGT it was given. Its role and its end (a member out, a finished team) come from
the server.

A console drives the bots:

    status                the teams: status, holder, zone, IGT, and each member's
                          zones over the cap
    walk BOT              the holder takes the next gate of the forward path
                          (a zone counts for the runner who kills its boss, or
                          exits it when it has none)
    boss BOT              the holder kills the boss of its zone (sends its defeat
                          flag)
    pass BOT TO           the holder hands the baton to the teammate named TO
    take BOT              a waiting bot asks for the baton (free only after the
                          holder was offline 60 s, or when it left the team)
    offline BOT           close BOT's socket and stay away
    online BOT            connect BOT again
    mute BOT on|off       on: BOT ignores a `relay_take`, which exercises the
                          30 s acknowledgement timeout
    finish BOT            the holder sends the seed's finish event from wherever
                          it is (the server credits the final boss): its team
                          finishes even before the final layer, so it proves
                          nothing about the walk
    quit

Typical run: two teams of two bots (or one team and yourself), start the race
from the web once every bot reports ready, `walk`, `boss` and `pass` on the
holders, `offline` the holder of a team, wait 60 s and `take` with its mate,
then `finish` each team.

Local databases only: the bots join by a direct insert while the race is in
setup (a team named by --team is created when the race has none of that name),
one at a time in the order given, so the teams created and the bots placed are
listed in that order. A refused placement stops the tool, the bots placed
before it staying in the race: a second start places the rest.
Never name your own user as a bot: its mod connection would replace yours. Run
from server/ while the dev server runs. A bot whose socket closes (a race reset,
a server reload) connects again.

Usage:
    cd server && uv run python ../tools/relay_bot.py <race_id> \\
        --team Alpha=bot1,bot2 --team Beta=bot3,bot4 [--state state.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Must run from server/ (cd server && uv run python ../tools/relay_bot.py)
sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from race_items_bot import deepest_nodes, forward_path, node_flags  # noqa: E402

# A waiting runner's first report must carry an IGT of at most 60 s (the
# fresh-save gate, MAX_FRESH_IGT_MS): its own save's, not the team's.
FRESH_IGT_MS = 5_000

OUT_TEAM_STATUSES = ("finished", "abandoned", "disqualified")
OUT_MEMBER_STATUSES = ("abandoned", "disqualified")

# What a handoff carries of the character when --state names no file:
# attributes in the game's order, a Vagabond at its starting level (the level
# is the attribute sum minus 79, or the receiver's mod does not write it).
FAKE_STATE: dict[str, Any] = {
    "attributes": [15, 10, 11, 14, 13, 9, 9, 7],
    "level": 9,
    "runes": 0,
    "items": [],
    "grace_flags": [],
}


def stats_plausible(state: dict[str, Any]) -> bool:
    """The receiver's mod rule for writing a state's stats: every attribute in
    1 to 99, the level in 1 to 713 and equal to the attribute sum minus 79,
    the runes at most 999999999 (mod/src/core/relay_items.rs)."""
    attributes = state["attributes"]
    level = state["level"]
    return (
        all(1 <= a <= 99 for a in attributes)
        and 1 <= level <= 713
        and sum(attributes) == level + 79
        and state["runes"] <= 999_999_999
    )


def load_state(path: Path) -> dict[str, Any]:
    """The character state in the JSON file ``path`` (attributes, level, runes,
    items, grace_flags), checked against the server's own model
    (``CharacterState``) and as that model gives it (absent lists empty).
    ValueError naming the file and the problem when it cannot be read or is
    not a state the server would accept."""
    from pydantic import ValidationError

    from speedfog_racing.websocket.schemas import CharacterState

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"--state {path}: cannot read it ({e.strerror or e})") from e
    try:
        state = CharacterState.model_validate_json(raw)
    except ValidationError as e:
        raise ValueError(f"--state {path}: not a valid CharacterState: {e}") from e
    return state.model_dump()


def log(*parts: object) -> None:
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


# --- bots --------------------------------------------------------------------


@dataclass
class Bot:
    name: str
    participant_id: str
    mod_token: str
    team_name: str
    ws: Any = None
    clock: Callable[[], float] = time.monotonic
    # The character it hands over at a release.
    state: dict[str, Any] = field(default_factory=lambda: FAKE_STATE)
    last_error: str = ""
    # What the server last told this mod (RelayInfo).
    team_id: str = ""
    running: bool = False
    holder: bool = False
    validated: bool = False
    gates_locked: bool = False
    # The wait as received at `info_at` (a reading of `clock`): each RelayInfo
    # carries it, but no update comes when it runs out, so it is counted down.
    baton_free_in_s: int | None = None
    info_at: float = 0.0
    members: list[dict[str, Any]] = field(default_factory=list)
    out: bool = False
    # The team's IGT at `igt_at` (a reading of `clock`): it runs from there.
    igt_ms: int = 0
    igt_at: float = 0.0
    # The next report is the first since a take or an authentication: it
    # carries the IGT as given, not advanced by the clock.
    first_report: bool = True
    ready_sent: bool = False
    muted: bool = False
    # A relay_take that was not acknowledged because the bot is muted.
    unacked_take: str | None = None
    offline: bool = False

    def igt_now(self) -> int:
        return self.igt_ms + int((self.clock() - self.igt_at) * 1000)

    def set_igt(self, igt_ms: int) -> None:
        self.igt_ms = igt_ms
        self.igt_at = self.clock()


def apply_info(bot: Bot, relay: dict[str, Any]) -> None:
    """Take in a RelayInfo: the role, the gate, and whether this bot is out."""
    bot.team_id = relay["team_id"]
    bot.members = relay["members"]
    bot.gates_locked = relay["gates_locked"]
    bot.baton_free_in_s = relay["baton_free_in_s"]
    bot.info_at = bot.clock()
    bot.holder = relay["role"] == "holder"
    own = next(
        (m for m in bot.members if m["participant_id"] == bot.participant_id), None
    )
    bot.validated = own is not None and own["validated"]
    bot.out = relay["team_status"] in OUT_TEAM_STATUSES or (
        own is not None and own["status"] in OUT_MEMBER_STATUSES
    )
    if not bot.holder:
        bot.unacked_take = None


def next_action(bot: Bot, message: dict[str, Any]) -> dict[str, Any] | None:
    """What the bot answers to one server message (None: nothing). Updates the
    bot's picture of the race as a side effect."""
    kind = message.get("type")
    if kind == "ping":
        return {"type": "pong"}
    if kind == "auth_ok":
        bot.running = message["race"]["status"] == "running"
        # The team's IGT, from its row among the participants.
        relay = message.get("relay")
        if relay is not None:
            apply_info(bot, relay)
            row = next(
                (p for p in message["participants"] if p["id"] == bot.team_id), None
            )
            bot.set_igt(row["igt_ms"] if row is not None else 0)
        bot.first_report = True
        bot.ready_sent = False
        if relay is not None and not bot.holder and bot.validated and not bot.out:
            bot.ready_sent = True
            return {"type": "relay_ready", "ready": True}
        return None
    if kind in ("race_start", "race_status_change"):
        running = kind == "race_start" or message.get("status") == "running"
        if running and not bot.running:
            bot.set_igt(0)
            bot.first_report = True
        bot.running = running
        return None
    if kind == "relay_update":
        was_holder = bot.holder
        apply_info(bot, message["relay"])
        if bot.holder and not was_holder:
            bot.first_report = True
        return None
    if bot.out:
        return None
    if kind == "relay_release":
        return {
            "type": "relay_state",
            "handoff_id": message["handoff_id"],
            "state": bot.state,
            "igt_ms": bot.igt_now(),
        }
    if kind == "relay_take":
        if bot.muted:
            bot.unacked_take = message["handoff_id"]
            return None
        bot.holder = True
        bot.ready_sent = False
        bot.first_report = True
        bot.set_igt(message["igt_ms"])
        return {"type": "relay_taken", "handoff_id": message["handoff_id"]}
    return None


def tick(bot: Bot) -> list[dict[str, Any]]:
    """What the bot sends on its own, once a second: its report and its
    readiness."""
    if bot.out or not bot.running:
        return []
    sent: list[dict[str, Any]] = []
    if bot.holder:
        if bot.ready_sent:
            bot.ready_sent = False
            sent.append({"type": "relay_ready", "ready": False})
        if bot.unacked_take is None:
            igt = bot.igt_ms if bot.first_report else bot.igt_now()
            if bot.first_report:
                bot.set_igt(bot.igt_ms)
            bot.first_report = False
            sent.append({"type": "status_update", "igt_ms": igt, "death_count": 0})
    elif not bot.validated:
        sent.append({"type": "status_update", "igt_ms": FRESH_IGT_MS, "death_count": 0})
    elif not bot.ready_sent:
        bot.ready_sent = True
        sent.append({"type": "relay_ready", "ready": True})
    return sent


def request_pass(bot: Bot, to_name: str) -> dict[str, Any] | str:
    """The handoff request, or why the bot cannot make it."""
    if not bot.holder:
        return f"{bot.name} does not hold the baton"
    target = next((m for m in bot.members if m["name"] == to_name), None)
    if target is None:
        return f"no teammate {to_name!r} ({', '.join(m['name'] for m in bot.members)})"
    if target["participant_id"] == bot.participant_id:
        return "the baton cannot be passed to oneself"
    return {
        "type": "relay_handoff_request",
        "to_participant_id": target["participant_id"],
    }


def request_take(bot: Bot) -> dict[str, Any] | str:
    """The take request, or why the bot cannot make it yet."""
    if bot.holder:
        return f"{bot.name} holds the baton"
    if bot.baton_free_in_s is None:
        return "the holder is online: the baton is not free"
    left = bot.baton_free_in_s - int(bot.clock() - bot.info_at)
    if left > 0:
        return f"the baton is free in {left} s"
    return {"type": "relay_take_request"}


def next_gate(graph: dict[str, Any], node: str) -> tuple[str, int] | str:
    """The next zone of the forward path from ``node`` and the fog flag that
    enters it, or why there is none. Toward the deepest layer below the final
    boss, then the final boss itself."""
    nodes = graph["nodes"]
    finals = {k for k, v in nodes.items() if v.get("type") == "final_boss"}
    path = forward_path(graph, node, deepest_nodes(graph)) or forward_path(
        graph, node, finals
    )
    if not path:
        return f"no way forward from {node}"
    flags = node_flags(graph)
    if path[0] not in flags:
        return f"node {path[0]} has no entry flag"
    return path[0], flags[path[0]]


def finish_warning(graph: dict[str, Any], node: str) -> str | None:
    """A line to print when ``node`` is not the final boss's zone: the finish
    event is accepted from anywhere, so the finish it brings proves no walk."""
    if graph["nodes"].get(node, {}).get("type") == "final_boss":
        return None
    return (
        f"the team is at {node}, not at the final boss: the server accepts the "
        "finish event from anywhere, this finish does not prove the walk"
    )


def parse_team(spec: str) -> tuple[str, list[str]]:
    """``NAME=BOT,BOT`` into the team name and its bots (2 or more, distinct)."""
    name, sep, rest = spec.partition("=")
    bots = [b for b in rest.split(",")] if sep else []
    if not name.strip() or len(bots) < 2 or "" in bots or len(set(bots)) != len(bots):
        raise ValueError(
            f"--team wants NAME=BOT,BOT (two or more distinct bots): {spec!r}"
        )
    return name.strip(), bots


# --- console -----------------------------------------------------------------


class Console:
    def __init__(
        self,
        race_id: str,
        ws_url: str,
        teams: list[tuple[str, list[str]]],
        state: dict[str, Any],
    ) -> None:
        self.race_id = race_id
        self.ws_url = ws_url
        self.teams = teams
        self.state = state
        self.bots: dict[str, Bot] = {}
        self.graph: dict[str, Any] = {}
        self.finish_flag: int | None = None
        self.start_node = ""
        self.tasks: list[asyncio.Task[None]] = []
        # Numbered as a mod numbers its messages: from the launch time in ms, one
        # more per message. The server drops a fog flag whose id is already in
        # the team's history, which mixes its members' ids: one counter for
        # every bot (a team's bots share its history), and never carried on
        # from the highest recorded id, which would take the next id of the mod
        # that recorded it and drop that mod's next flag.
        self.message_id = time.time_ns() // 1_000_000

    # --- setup ---

    async def load(self) -> None:
        from fastapi import HTTPException
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from speedfog_racing.api.relay_teams import place_in_team
        from speedfog_racing.database import async_session_maker
        from speedfog_racing.models import Participant, Race, RaceStatus, User
        from speedfog_racing.schemas import RelayTeamChoice
        from speedfog_racing.services.layer_service import get_start_node

        async with async_session_maker() as db:
            race = (
                await db.execute(
                    select(Race)
                    .where(Race.id == uuid.UUID(self.race_id))
                    .options(
                        selectinload(Race.participants).selectinload(Participant.user),
                        selectinload(Race.seed),
                    )
                )
            ).scalar_one_or_none()
            if race is None:
                raise SystemExit(f"no race {self.race_id}")
            if not race.is_relay:
                raise SystemExit("this is not a relay race (relay_team_size)")
            if race.seed is None or not race.seed.graph_json:
                raise SystemExit("this race has no seed yet")
            self.graph = race.seed.graph_json
            self.finish_flag = self.graph.get("finish_event")
            start = get_start_node(self.graph)
            if start is None:
                raise SystemExit("the seed graph has no start node")
            self.start_node = start

            wanted = [b for _, bots in self.teams for b in bots]
            if len(set(wanted)) != len(wanted):
                raise SystemExit("a bot is named in two teams")
            organizer = (
                await db.execute(
                    select(User.twitch_username).where(User.id == race.organizer_id)
                )
            ).scalar_one_or_none()
            if organizer in wanted:
                raise SystemExit(
                    f"{organizer} organizes this race: never play yourself as a bot"
                )
            joined = {p.user.twitch_username: p for p in race.participants}
            missing = [n for n in wanted if n not in joined]
            if missing:
                if race.status != RaceStatus.SETUP:
                    raise SystemExit(
                        f"{missing} not in the race, and bots only join in setup"
                    )
                users = (
                    (
                        await db.execute(
                            select(User).where(User.twitch_username.in_(missing))
                        )
                    )
                    .scalars()
                    .all()
                )
                found = {u.twitch_username: u for u in users}
                unknown = [n for n in missing if n not in found]
                if unknown:
                    raise SystemExit(f"no local user named {unknown}")
                added: list[str] = []
                for team_name, bots in self.teams:
                    for name in bots:
                        if name not in found:
                            continue
                        p = Participant(
                            race_id=race.id, user_id=found[name].id, color_index=0
                        )
                        db.add(p)
                        team = next(
                            (t for t in race.relay_teams if t.name == team_name), None
                        )
                        choice = (
                            RelayTeamChoice(relay_team_id=team.id)
                            if team is not None
                            else RelayTeamChoice(create_team=True)
                        )
                        try:
                            placed = await place_in_team(
                                db, race, p, choice, by_organizer=True
                            )
                        except HTTPException as e:
                            await db.rollback()
                            before = f" ({added} joined before it)" if added else ""
                            raise SystemExit(
                                f"cannot place {name} in {team_name!r}: {e.detail}{before}"
                            ) from e
                        if placed is not None and team is None:
                            placed.name = team_name
                            race.relay_teams.append(placed)
                        # One transaction per runner, as one join request each:
                        # teams and members are listed by their creation time,
                        # the transaction's time on PostgreSQL, which a single
                        # transaction would leave tied.
                        await db.commit()
                        joined[name] = p
                        added.append(name)
                log(f"joined {missing} to the race")
            for team_name, bots in self.teams:
                for name in bots:
                    p = joined[name]
                    await db.refresh(p)
                    team = next(
                        (t for t in race.relay_teams if t.id == p.relay_team_id), None
                    )
                    if team is None or team.name != team_name:
                        raise SystemExit(
                            f"{name} is already in the race, in a team other than {team_name!r}"
                        )
                    self.bots[name] = Bot(
                        name=name,
                        participant_id=str(p.id),
                        mod_token=p.mod_token,
                        team_name=team_name,
                        state=self.state,
                    )

    async def connect(self) -> None:
        """Start one connection per bot, kept up by `supervise`, and wait for
        the first authentications."""
        self.tasks = [
            asyncio.create_task(self.supervise(bot)) for bot in self.bots.values()
        ]
        for _ in range(100):
            if all(bot.ws is not None for bot in self.bots.values()):
                break
            await asyncio.sleep(0.1)
        up = [bot.name for bot in self.bots.values() if bot.ws is not None]
        down = [bot.name for bot in self.bots.values() if bot.ws is None]
        log(f"bots connected: {', '.join(up) or 'none'}")
        if down:
            log(f"still connecting: {', '.join(down)}")

    async def supervise(self, bot: Bot) -> None:
        """Connect, authenticate, report ready, read; connect again once the
        socket closes (a race reset or a server reload closes the mods), unless
        the bot was sent offline."""
        import websockets

        from speedfog_racing.websocket.schemas import PROTOCOL_VERSION

        while True:
            if bot.offline:
                await asyncio.sleep(0.5)
                continue
            try:
                ws = await websockets.connect(f"{self.ws_url}/ws/mod/{self.race_id}")
                await ws.send(
                    json.dumps(
                        {
                            "type": "auth",
                            "mod_token": bot.mod_token,
                            "protocol_version": PROTOCOL_VERSION,
                            "mod_version": "relay_bot",
                        }
                    )
                )
                reply = json.loads(await ws.recv())
                if reply.get("type") != "auth_ok":
                    self.note(bot, f"mod auth refused: {reply.get('message')}")
                    await ws.close()
                else:
                    bot.ws = ws
                    bot.last_error = ""
                    # Accepted in setup only (after a reset too), harmless otherwise.
                    await ws.send(json.dumps({"type": "ready"}))
                    await self.handle(bot, reply)
                    await self.read(bot)
                    if not bot.offline:
                        self.note(bot, "connection closed, connecting again")
            except (OSError, websockets.WebSocketException) as e:
                self.note(bot, f"connection failed: {e!r}")
            bot.ws = None
            await asyncio.sleep(2.0)

    def note(self, bot: Bot, line: str) -> None:
        """Log a bot's error line once, not again while it repeats."""
        if line != bot.last_error:
            bot.last_error = line
            log(f"[{bot.name}] {line}")

    async def send(self, bot: Bot, payload: dict[str, Any]) -> bool:
        """Send to a bot's socket; False while it is down."""
        import websockets

        if bot.ws is None:
            self.note(bot, "not connected, nothing sent")
            return False
        try:
            await bot.ws.send(json.dumps(payload))
            return True
        except websockets.ConnectionClosed:
            return False

    # --- messages from the server ---

    async def handle(self, bot: Bot, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        out = next_action(bot, msg)
        if out is not None:
            await self.send(bot, out)
        if kind == "relay_release":
            log(f"[{bot.name}] released the baton (handoff {msg['handoff_id']})")
        elif kind == "relay_take":
            how = "muted: not acknowledged" if bot.muted else "took the baton"
            log(
                f"[{bot.name}] {how} (handoff {msg['handoff_id']}, team igt {msg['igt_ms']})"
            )
        elif kind == "relay_refused":
            self.note(bot, f"refused: {msg['code']}: {msg['message']}")
        elif kind in ("error", "auth_error"):
            self.note(bot, f"{kind}: {msg.get('message')} {msg.get('code') or ''}")

    async def read(self, bot: Bot) -> None:
        import websockets

        try:
            async for raw in bot.ws:
                await self.handle(bot, json.loads(raw))
        except websockets.ConnectionClosed:
            pass  # reported by supervise

    async def heartbeat(self) -> None:
        """What each bot sends on its own, as a mod does every second."""
        while True:
            for bot in self.bots.values():
                if bot.ws is not None:
                    for payload in tick(bot):
                        await self.send(bot, payload)
            await asyncio.sleep(1.0)

    # --- commands ---

    def bot(self, name: str) -> Bot | None:
        found = self.bots.get(name)
        if found is None:
            log(f"no bot {name!r} ({', '.join(self.bots)})")
        return found

    async def team_zone(self, bot: Bot) -> str:
        """The team's current zone (a node id)."""
        from speedfog_racing.database import async_session_maker
        from speedfog_racing.models import RelayTeam

        async with async_session_maker() as db:
            team = await db.get(RelayTeam, uuid.UUID(bot.team_id))
        if team is None:
            return self.start_node
        return team.current_zone or self.start_node

    async def flag(self, bot: Bot, flag_id: int) -> bool:
        self.message_id += 1
        return await self.send(
            bot,
            {
                "type": "event_flag",
                "flag_id": flag_id,
                "igt_ms": bot.igt_now(),
                "message_id": self.message_id,
            },
        )

    def holder_refusal(self, bot: Bot) -> str | None:
        if bot.out:
            return f"{bot.name} is out of the race"
        if not bot.running:
            return "the race is not running"
        if not bot.holder:
            return f"{bot.name} does not hold the baton"
        return None

    async def walk(self, bot: Bot) -> None:
        refusal = self.holder_refusal(bot)
        if refusal is None and bot.gates_locked:
            refusal = f"{bot.name} is at its cap: the gates are locked"
        if refusal is not None:
            log(refusal)
            return
        node = await self.team_zone(bot)
        gate = next_gate(self.graph, node)
        if isinstance(gate, str):
            log(f"[{bot.name}] {gate}")
            return
        target, flag_id = gate
        if await self.flag(bot, flag_id):
            log(f"[{bot.name}] takes the gate {node} -> {target}")

    async def boss(self, bot: Bot) -> None:
        refusal = self.holder_refusal(bot)
        if refusal is not None:
            log(refusal)
            return
        node = await self.team_zone(bot)
        flag_id = self.graph["nodes"].get(node, {}).get("defeat_flag")
        if not isinstance(flag_id, int):
            log(f"[{bot.name}] {node} has no boss: leaving it counts the zone")
            return
        if await self.flag(bot, flag_id):
            log(f"[{bot.name}] killed the boss of {node}")

    async def finish(self, bot: Bot) -> None:
        refusal = self.holder_refusal(bot)
        if refusal is None and self.finish_flag is None:
            refusal = "the seed has no finish event"
        if refusal is not None:
            log(refusal)
            return
        assert self.finish_flag is not None
        node = await self.team_zone(bot)
        warning = finish_warning(self.graph, node)
        if warning is not None:
            log(f"[{bot.name}] warning: {warning}")
        if await self.flag(bot, self.finish_flag):
            log(f"[{bot.name}] sent the finish event")

    async def status(self) -> None:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from speedfog_racing.database import async_session_maker
        from speedfog_racing.models import Participant, Race, RelayTeam
        from speedfog_racing.services.relay import team_cap

        async with async_session_maker() as db:
            race = await db.get(Race, uuid.UUID(self.race_id))
            teams = (
                (
                    await db.execute(
                        select(RelayTeam)
                        .where(RelayTeam.race_id == uuid.UUID(self.race_id))
                        .options(
                            selectinload(RelayTeam.members).selectinload(
                                Participant.user
                            )
                        )
                        .order_by(RelayTeam.created_at)
                    )
                )
                .scalars()
                .all()
            )
            if race is None:
                return
            total = int(self.graph.get("total_layers", 0))
            log(f"race {race.status.value}")
            for t in teams:
                cap = team_cap(total, t.members)
                holder = next((m for m in t.members if m.id == t.holder_id), None)
                holder_name = holder.user.twitch_username if holder is not None else "-"
                zone = (
                    self.graph["nodes"]
                    .get(t.current_zone or "", {})
                    .get("display_name")
                )
                free = " (baton free)" if t.baton_free else ""
                print(
                    f"  {t.name:<16} {t.status.value:<10} holder {holder_name}{free}"
                    f"  zone {zone or t.current_zone or '-'}  layer {t.current_layer}"
                    f"  igt {t.igt_ms // 1000} s"
                )
                for m in t.members:
                    bot = self.bots.get(m.user.twitch_username)
                    link = "" if bot is None else ("online" if bot.ws else "offline")
                    print(
                        f"      {m.user.twitch_username:<18} {m.status.value:<10}"
                        f" {m.relay_zones}/{cap} zones  {link}"
                    )

    async def run(self) -> None:
        self.tasks.append(asyncio.create_task(self.heartbeat()))
        loop = asyncio.get_running_loop()
        log("ready: type help")
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                return
            words = line.split()
            if not words:
                continue
            cmd, args = words[0], words[1:]
            try:
                if cmd in ("quit", "exit"):
                    return
                if cmd == "help":
                    start = __doc__.index("    status")
                    print(__doc__[start : __doc__.index("Typical")].rstrip())
                elif cmd == "status":
                    await self.status()
                elif (
                    cmd in ("walk", "boss", "finish", "take", "offline", "online")
                    and len(args) == 1
                ):
                    await self.one(cmd, args[0])
                elif cmd == "pass" and len(args) == 2:
                    bot = self.bot(args[0])
                    if bot is not None:
                        await self.send_or_say(bot, request_pass(bot, args[1]))
                elif cmd == "mute" and len(args) == 2 and args[1] in ("on", "off"):
                    bot = self.bot(args[0])
                    if bot is not None:
                        bot.muted = args[1] == "on"
                        log(f"[{bot.name}] mute {args[1]}")
                else:
                    log(f"unknown command: {line.strip()} (help)")
            except Exception as e:  # keep the console alive on a bad command
                log(f"error: {e!r}")

    async def send_or_say(self, bot: Bot, request: dict[str, Any] | str) -> None:
        if isinstance(request, str):
            log(request)
        elif await self.send(bot, request):
            log(f"[{bot.name}] sent {request['type']}")

    async def one(self, cmd: str, name: str) -> None:
        bot = self.bot(name)
        if bot is None:
            return
        if cmd == "walk":
            await self.walk(bot)
        elif cmd == "boss":
            await self.boss(bot)
        elif cmd == "finish":
            await self.finish(bot)
        elif cmd == "take":
            await self.send_or_say(bot, request_take(bot))
        elif cmd == "offline":
            bot.offline = True
            if bot.ws is not None:
                await bot.ws.close()
            log(f"[{bot.name}] offline")
        else:
            bot.offline = False
            log(f"[{bot.name}] connecting again")


async def main_async(args: argparse.Namespace) -> None:
    from simulate_event import check_local_database

    if not args.force:
        check_local_database()
    try:
        teams = [parse_team(t) for t in args.team]
        state = FAKE_STATE if args.state is None else load_state(args.state)
    except ValueError as e:
        raise SystemExit(str(e)) from e
    if not stats_plausible(state):
        log(
            "warning: the state's level is not its attribute sum minus 79, or a "
            "value is out of range: the receiver's mod will not write its stats"
        )
    console = Console(args.race_id, args.ws, teams, state)
    await console.load()
    await console.connect()
    await console.run()


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("race_id")
    parser.add_argument(
        "--team",
        action="append",
        required=True,
        help="NAME=BOT,BOT: a team and its bots (local usernames); repeat for more teams",
    )
    parser.add_argument(
        "--ws", default="ws://localhost:8000", help="the server's WebSocket"
    )
    parser.add_argument(
        "--state",
        type=Path,
        help="a CharacterState JSON file (attributes, level, runes, items, "
        "grace_flags) the bots hand over at a release instead of the default",
    )
    parser.add_argument(
        "--force", action="store_true", help="allow a non-local database"
    )
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
