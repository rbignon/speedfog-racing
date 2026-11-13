#!/usr/bin/env python3
"""Bot runners for testing race items with one real game (docs/RACE_ITEMS.md).

Most race items aim at another runner, so a lone tester needs company. Each
bot is a local user joined to a race with items, whose "mod" is this script:
it connects over /ws/mod/<race> with the participant's own token, reports
ready and, once the race runs, an in-game time that follows the wall clock.
Its items arrive and leave through the real messages (item_grant answered by
item_received, item_inventory, the use flag), so everything a bot does to the
real runner goes through the server's own rules.

A console drives the bots while you play:

    status                show the field: rank, tier, layer, held item
    ahead BOT             walk BOT forward to the deepest layer before the final
                          boss
    boss BOT              walk BOT to the nearest boss it has not killed, kill it
                          (the server draws an item by BOT's tier, unless BOT
                          already holds one)
    give WHO ITEM         hand ITEM to a bot or to a runner (by username), as an
                          unconfirmed grant the server sends again; a real
                          runner gets it at its next load (fog gate, quit-out)
    use BOT               BOT uses its item (its use flag)
    inventory BOT         BOT reports its inventory (what it holds)
    quit

Typical layout: one bot walks ahead, one stays at the start, so every target
rule can reach you (the runner just behind or just ahead, the leader, everyone
else). With three runners the leader draws front items, the second middle
items, the last back items.

Local databases only: the bots join by a direct insert while the race is in
setup, and `give` writes the held item (outside the server's item lock: do not
give while a grant or a use is on its way to the same runner). Never name your
own user as a bot: its mod connection would replace yours. Run from server/
while the dev server runs; start the race from the web once your mod and the
bots are ready. A bot whose socket closes (a race reset, a server reload)
connects again; after a reset it reports ready again and walks from the start.

Usage:
    cd server && uv run python ../tools/race_items_bot.py <race_id> --bots NAME,NAME
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Must run from server/ (cd server && uv run python ../tools/race_items_bot.py)
sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def log(*parts: object) -> None:
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


# --- graph -------------------------------------------------------------------


def node_flags(graph: dict[str, Any]) -> dict[str, int]:
    """One event flag per node: the flag that reports entering it."""
    flags: dict[str, int] = {}
    for flag, node in sorted(
        graph.get("event_map", {}).items(), key=lambda kv: int(kv[0])
    ):
        flags.setdefault(node, int(flag))
    return flags


def forward_path(
    graph: dict[str, Any], start: str, goals: set[str]
) -> list[str] | None:
    """The shortest walk from ``start`` to a node of ``goals``, through exits
    that go to a deeper layer, as the nodes entered (``start`` left out);
    None when no goal is reachable."""
    nodes = graph["nodes"]
    previous: dict[str, str | None] = {start: None}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        if current in goals and current != start:
            path = []
            node: str | None = current
            while node is not None and node != start:
                path.append(node)
                node = previous[node]
            return path[::-1]
        layer = nodes[current]["layer"]
        for exit_ in nodes[current].get("exits", []):
            nxt = exit_.get("to")
            if nxt in nodes and nxt not in previous and nodes[nxt]["layer"] > layer:
                previous[nxt] = current
                queue.append(nxt)
    return None


def deepest_nodes(graph: dict[str, Any]) -> set[str]:
    """The nodes of the deepest layer below the final boss."""
    nodes = graph["nodes"]
    playable = {k: v for k, v in nodes.items() if v.get("type") != "final_boss"}
    if not playable:
        return set()
    top = max(v["layer"] for v in playable.values())
    return {k for k, v in playable.items() if v["layer"] == top}


# --- bots --------------------------------------------------------------------


@dataclass
class Bot:
    name: str
    participant_id: str
    mod_token: str
    node: str
    ws: Any = None
    message_id: int = 0
    held: str | None = None  # the race item in its "inventory"
    killed: set[str] = field(default_factory=set)
    last_error: str = ""


class Console:
    def __init__(self, race_id: str, ws_url: str) -> None:
        self.race_id = race_id
        self.ws_url = ws_url
        self.bots: dict[str, Bot] = {}
        self.graph: dict[str, Any] = {}
        self.catalog: dict[str, Any] = {}
        self.boss_nodes: dict[str, int] = {}
        self.started_at: datetime | None = None
        self.tasks: list[asyncio.Task[None]] = []

    # --- setup ---

    async def load(self, wanted: list[str]) -> None:
        from sqlalchemy import func, select
        from sqlalchemy.orm import selectinload

        from speedfog_racing.database import async_session_maker
        from speedfog_racing.models import Participant, Race, RaceStatus, User
        from speedfog_racing.services.layer_service import get_start_node
        from speedfog_racing.services.race_items import extract_race_item_catalog
        from speedfog_racing.websocket.handler import extract_boss_flags

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
            if not race.race_items:
                raise SystemExit(
                    "this race has race items off (Race options, community race)"
                )
            if race.seed is None or not race.seed.graph_json:
                raise SystemExit("this race has no seed yet")
            self.graph = race.seed.graph_json
            self.catalog = extract_race_item_catalog(self.graph)
            if not self.catalog:
                raise SystemExit("the race's seed has no race item catalog")
            self.boss_nodes = {
                node: flag for flag, node in extract_boss_flags(self.graph).items()
            }
            self.started_at = race.started_at

            joined = {p.user.twitch_username: p for p in race.participants}
            names = wanted
            organizer = (
                await db.execute(
                    select(User.twitch_username).where(User.id == race.organizer_id)
                )
            ).scalar_one_or_none()
            if organizer in names:
                raise SystemExit(
                    f"{organizer} organizes this race: never play yourself as a bot"
                )
            missing = [n for n in names if n not in joined]
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
                top = (
                    await db.execute(
                        select(func.max(Participant.color_index)).where(
                            Participant.race_id == race.id
                        )
                    )
                ).scalar()
                for i, name in enumerate(missing):
                    p = Participant(
                        race_id=race.id,
                        user_id=found[name].id,
                        color_index=(top if top is not None else -1) + 1 + i,
                    )
                    db.add(p)
                    joined[name] = p
                await db.commit()
                log(f"joined {missing} to the race")
            start = get_start_node(self.graph)
            if start is None:
                raise SystemExit("the seed graph has no start node")
            for name in names:
                p = joined[name]
                await db.refresh(p)
                node = p.current_zone or start
                held = p.held_item or {}
                history = p.zone_history or []
                self.bots[name] = Bot(
                    name=name,
                    participant_id=str(p.id),
                    mod_token=p.mod_token,
                    node=node,
                    # The server ignores a fog flag whose message id it already
                    # recorded: carry on from the last one.
                    message_id=max(
                        (e.get("message_id") or 0 for e in history), default=0
                    ),
                    held=held.get("item") if held.get("confirmed") else None,
                    killed={e["node_id"] for e in history if "boss_kill_igt_ms" in e},
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
        log(f"bots connected and ready: {', '.join(up) or 'none'}")
        if down:
            log(f"still connecting: {', '.join(down)}")

    async def supervise(self, bot: Bot) -> None:
        """Connect, authenticate, report ready, read; connect again once the
        socket closes (a race reset or a server reload closes the mods)."""
        import websockets

        from speedfog_racing.websocket.schemas import PROTOCOL_VERSION

        while True:
            try:
                ws = await websockets.connect(f"{self.ws_url}/ws/mod/{self.race_id}")
                await ws.send(
                    json.dumps(
                        {
                            "type": "auth",
                            "mod_token": bot.mod_token,
                            "protocol_version": PROTOCOL_VERSION,
                            "mod_version": "race_items_bot",
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
                    # As the mod does at every (re)connection: the server
                    # reconciles the held item with it.
                    await self.inventory(bot)
                    await self.read(bot)
                    # A clean close ends the read loop without an exception.
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

    async def read(self, bot: Bot) -> None:
        import websockets

        try:
            async for raw in bot.ws:
                msg = json.loads(raw)
                kind = msg.get("type")
                if kind == "ping":
                    await self.send(bot, {"type": "pong"})
                elif kind == "item_grant":
                    bot.held = msg["item"]
                    await self.send(
                        bot, {"type": "item_received", "grant_id": msg["grant_id"]}
                    )
                    log(f"[{bot.name}] got {msg['item']} (grant {msg['grant_id']})")
                elif kind == "item_effect":
                    log(f"[{bot.name}] hit by {msg['item']}: {msg['effect']}")
                elif kind == "item_result":
                    banner = msg.get("banner", {})
                    line, detail = banner.get("line"), banner.get("detail")
                    log(f"[{bot.name}] {msg['item']} result: {line} {detail}")
                elif kind == "item_remove":
                    if bot.held == msg.get("item"):
                        bot.held = None
                    log(
                        f"[{bot.name}] {msg.get('item')} removed (shield used or taken back)"
                    )
                elif kind in ("error", "auth_error"):
                    self.note(
                        bot, f"{kind}: {msg.get('message')} {msg.get('code', '')}"
                    )
        except websockets.ConnectionClosed:
            pass  # reported by supervise

    # --- in-game time ---

    def igt(self) -> int:
        if self.started_at is None:
            return 0
        started = self.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        return max(1, int((datetime.now(UTC) - started).total_seconds() * 1000))

    async def refresh_start(self) -> None:
        """Follow the race's start: a reset clears it and a new start moves it,
        so the bots then walk again from the start node."""
        from speedfog_racing.database import async_session_maker
        from speedfog_racing.models import Race
        from speedfog_racing.services.layer_service import get_start_node

        async with async_session_maker() as db:
            race = await db.get(Race, uuid.UUID(self.race_id))
            started = race.started_at if race is not None else None
        if started != self.started_at:
            if self.started_at is not None:
                start = get_start_node(self.graph)
                for bot in self.bots.values():
                    bot.node = start or bot.node
                    bot.killed.clear()
                    bot.held = None  # a reset clears every held item
                log(
                    "race start changed (reset or new start): bots back at the start node"
                )
            self.started_at = started

    async def heartbeat(self) -> None:
        """Each bot reports its in-game time, as a mod does every second."""
        beat = 0
        while True:
            if beat % 5 == 0:
                await self.refresh_start()
            beat += 1
            if self.started_at is not None:
                for bot in self.bots.values():
                    if bot.ws is not None:
                        await self.send(
                            bot,
                            {
                                "type": "status_update",
                                "igt_ms": self.igt(),
                                "death_count": 0,
                            },
                        )
            await asyncio.sleep(1.0)

    async def flag(self, bot: Bot, flag_id: int) -> bool:
        bot.message_id += 1
        sent = await self.send(
            bot,
            {
                "type": "event_flag",
                "flag_id": flag_id,
                "igt_ms": self.igt(),
                "message_id": bot.message_id,
            },
        )
        await asyncio.sleep(0.1)
        return sent

    async def walk(self, bot: Bot, goals: set[str]) -> bool:
        """Walk forward to the nearest node of ``goals``, one fog flag per node."""
        if bot.node in goals:
            log(f"[{bot.name}] already at {bot.node}")
            return True
        path = forward_path(self.graph, bot.node, goals)
        if path is None:
            log(f"[{bot.name}] no way forward from {bot.node} to that")
            return False
        flags = node_flags(self.graph)
        for node in path:
            if node not in flags:
                log(
                    f"[{bot.name}] node {node} has no entry flag, stopped at {bot.node}"
                )
                return False
            if not await self.flag(bot, flags[node]):
                log(f"[{bot.name}] disconnected, stopped at {bot.node}")
                return False
            bot.node = node
        layer = self.graph["nodes"][bot.node]["layer"]
        log(f"[{bot.name}] now at {bot.node} (layer {layer})")
        return True

    # --- commands ---

    def bot(self, name: str) -> Bot | None:
        found = self.bots.get(name)
        if found is None:
            log(f"no bot {name!r} ({', '.join(self.bots)})")
        return found

    async def status(self) -> None:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from speedfog_racing.database import async_session_maker
        from speedfog_racing.models import Participant, ParticipantStatus, Race
        from speedfog_racing.services.race_items import tier_of
        from speedfog_racing.websocket.race.manager import sort_leaderboard

        async with async_session_maker() as db:
            race = (
                await db.execute(
                    select(Race)
                    .where(Race.id == uuid.UUID(self.race_id))
                    .options(
                        selectinload(Race.participants).selectinload(Participant.user)
                    )
                )
            ).scalar_one()
            ordered, _ = sort_leaderboard(race.participants, graph_json=self.graph)
            playing = [p for p in ordered if p.status == ParticipantStatus.PLAYING]
            log(f"race {race.status.value}, igt {self.igt() // 1000} s")
            for p in ordered:
                tier = (
                    tier_of(playing.index(p), len(playing))
                    if p in playing
                    else p.status.value
                )
                held = p.held_item or {}
                item = f"{held.get('item')}{'' if held.get('confirmed') else ' (unconfirmed)'}"
                print(
                    f"  {p.user.twitch_username:<20} {tier:<8} layer {p.current_layer:<3} "
                    f"igt {p.igt_ms // 1000:>5} s  {item if held else '-'}"
                )

    async def give(self, who: str, item: str) -> None:
        from sqlalchemy import select

        from speedfog_racing.database import async_session_maker
        from speedfog_racing.models import Participant, User

        if item not in self.catalog:
            log(f"no item {item!r}: {', '.join(sorted(self.catalog))}")
            return
        async with async_session_maker() as db:
            p = (
                await db.execute(
                    select(Participant)
                    .join(User, User.id == Participant.user_id)
                    .where(
                        Participant.race_id == uuid.UUID(self.race_id),
                        User.twitch_username == who,
                    )
                )
            ).scalar_one_or_none()
            if p is None:
                log(f"no runner {who!r} in this race")
                return
            p.item_grant_count += 1
            p.held_item = {
                "grant_id": p.item_grant_count,
                "item": item,
                "confirmed": False,
            }
            await db.commit()
        bot = self.bots.get(who)
        if bot is None:
            log(
                f"{who} holds {item}: it spawns at their next load (fog gate, quit-out)"
            )
            return
        await self.inventory(bot)

    async def use(self, bot: Bot) -> None:
        if bot.held is None:
            log(f"[{bot.name}] holds nothing")
            return
        use_flag = self.catalog[bot.held].use_flag
        if use_flag is None:
            log(f"[{bot.name}] {bot.held} cannot be used")
            return
        log(f"[{bot.name}] uses {bot.held}")
        if await self.flag(bot, use_flag):
            bot.held = None

    async def inventory(self, bot: Bot) -> None:
        items = [bot.held] if bot.held else []
        await self.send(bot, {"type": "item_inventory", "items": items})

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
                elif cmd == "give" and len(args) == 2:
                    await self.give(args[0], args[1])
                elif cmd in ("ahead", "boss", "use", "inventory") and len(args) == 1:
                    bot = self.bot(args[0])
                    if bot is None:
                        continue
                    if cmd != "inventory" and self.igt() < 3000:
                        # Before its first status of the running race, a bot is
                        # not playing yet and the server drops its flags.
                        log("wait until the race has run for a few seconds")
                    elif cmd == "ahead":
                        await self.walk(bot, deepest_nodes(self.graph))
                    elif cmd == "boss":
                        goals = set(self.boss_nodes) - bot.killed
                        if bot.held:
                            log(
                                f"[{bot.name}] holds {bot.held}: a kill grants nothing until used"
                            )
                        if await self.walk(bot, goals):
                            await self.flag(bot, self.boss_nodes[bot.node])
                            bot.killed.add(bot.node)
                            log(f"[{bot.name}] killed the boss of {bot.node}")
                    elif cmd == "use":
                        await self.use(bot)
                    else:
                        await self.inventory(bot)
                else:
                    log(f"unknown command: {line.strip()} (help)")
            except Exception as e:  # keep the console alive on a bad command
                log(f"error: {e!r}")


async def main_async(args: argparse.Namespace) -> None:
    from simulate_event import check_local_database

    if not args.force:
        check_local_database()
    console = Console(args.race_id, args.ws)
    await console.load([n for n in args.bots.split(",") if n])
    await console.connect()
    await console.run()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("race_id")
    parser.add_argument(
        "--bots", required=True, help="local usernames to play as bots, comma separated"
    )
    parser.add_argument(
        "--ws", default="ws://localhost:8000", help="the server's WebSocket"
    )
    parser.add_argument(
        "--force", action="store_true", help="allow a non-local database"
    )
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
