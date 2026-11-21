"""Relay race fixtures: a relay seed, and a relay race with its teams inserted directly.

Shared by the relay tests, on the model of ``event_fixtures.py``. Rows are
inserted without going through the routes, so a test of the rules does not
depend on the routes that build teams.

The socket tests use ``setup_relay_race`` (a race ready to start, on the
integration database of ``test_integration.py``), ``start_relay`` (every member
connected, the race started, each holder's first report sent) or
``started_mods`` (the same as a fixture body), ``RelayModClient``, a mod kept
connected across a test, ``barrier``, ``connect_spectator``, and the member
steps ``validate``, ``set_ready`` and ``make_receiver``. Tests without a socket
put a race of ``make_relay_race`` in play with ``run_relay_race``. A test that
creates a relay race through the API uses the ``relay_races_on`` fixture.
"""

from __future__ import annotations

import asyncio
import itertools
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from starlette.testclient import TestClient

from speedfog_racing.config import settings
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    RelayTeam,
    Seed,
    User,
    UserRole,
)
from speedfog_racing.websocket.race.manager import manager

from .test_integration import ModTestClient

RELAY_BLOCK = {
    "lock_flag": 1050290500,
    "chapel_warp_flag": 1050290501,
    "warp_flag_base": 1050290510,
    "zone_flag_base": 1050294000,
    "warp_flag_count": 490,
}

# The run of ``progress_graph``: the start (no boss), a boss arena on layer 1, a
# zone without boss on layer 2 and the final boss on layer 3. The start node's
# zone is the Chapel's, so grace 10012952 resolves to it on a zone_query.
START_NODE = "chapel_start_4f96"
BOSS_NODE = "stormveil_godrick_48fd"
PLAIN_NODE = "raya_lucaria_1a2b"
FINAL_NODE = "elden_beast_9f00"
START_GRACE = 10012952
FOG_FLAG = 1050294001  # START_NODE -> BOSS_NODE
SECOND_FOG_FLAG = 1050294002  # BOSS_NODE -> PLAIN_NODE
THIRD_FOG_FLAG = 1050294003  # PLAIN_NODE -> FINAL_NODE
BOSS_FLAG = 10000800
FINAL_BOSS_FLAG = 19000800
FINISH_FLAG = 1050299000
PROGRESS_TOTAL_LAYERS = 4


@pytest.fixture
def relay_races_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Relay races are off by default (``settings.relay_races_enabled``): a
    test that creates one through the API, or counts relay seeds in the pools,
    turns them on. Rows inserted directly need nothing."""
    monkeypatch.setattr(settings, "relay_races_enabled", True)


def relay_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """A copy of ``graph`` with the relay block added."""
    out = deepcopy(graph)
    out["relay"] = dict(RELAY_BLOCK)
    return out


def progress_graph() -> dict[str, Any]:
    """A relay seed's graph with a run to play (see ``START_NODE`` and the flags)."""
    return relay_graph(
        {
            "version": "4.15",
            "total_layers": PROGRESS_TOTAL_LAYERS,
            "nodes": {
                START_NODE: {
                    "type": "start",
                    "display_name": "Chapel of Anticipation",
                    "zones": ["chapel_start"],
                    "layer": 0,
                    "tier": 1,
                    "exits": [{"text": "Fog", "fog_id": 1, "to": BOSS_NODE}],
                },
                BOSS_NODE: {
                    "type": "boss_arena",
                    "display_name": "Godrick the Grafted",
                    "zones": ["stormveil_godrick"],
                    "layer": 1,
                    "tier": 2,
                    "defeat_flag": BOSS_FLAG,
                    "exits": [{"text": "Fog", "fog_id": 2, "to": PLAIN_NODE}],
                },
                PLAIN_NODE: {
                    "display_name": "Raya Lucaria",
                    "zones": ["academy"],
                    "layer": 2,
                    "tier": 3,
                    "exits": [{"text": "Fog", "fog_id": 3, "to": FINAL_NODE}],
                },
                FINAL_NODE: {
                    "type": "final_boss",
                    "display_name": "Elden Beast",
                    "zones": ["zone_end"],
                    "layer": 3,
                    "tier": 4,
                    "defeat_flag": FINAL_BOSS_FLAG,
                },
            },
            "edges": [
                {"from": START_NODE, "to": BOSS_NODE},
                {"from": BOSS_NODE, "to": PLAIN_NODE},
                {"from": PLAIN_NODE, "to": FINAL_NODE},
            ],
            "event_map": {
                str(FOG_FLAG): BOSS_NODE,
                str(SECOND_FOG_FLAG): PLAIN_NODE,
                str(THIRD_FOG_FLAG): FINAL_NODE,
            },
            "finish_event": FINISH_FLAG,
            "finish_boss_defeat_flag": FINAL_BOSS_FLAG,
        }
    )


async def make_relay_seed(
    db: AsyncSession,
    *,
    suffix: str,
    total_layers: int = 12,
    graph: dict[str, Any] | None = None,
) -> Seed:
    """A relay seed; ``graph`` (given whole, relay block included) replaces the
    empty default graph and sets ``total_layers``."""
    if graph is None:
        graph = relay_graph({"total_layers": total_layers, "nodes": []})
    else:
        total_layers = int(graph["total_layers"])
    seed = Seed(
        seed_number=f"relay_{suffix}",
        pool_name="standard",
        graph_json=graph,
        relay=True,
        total_layers=total_layers,
        folder_path=f"/test/relay_{suffix}",
    )
    db.add(seed)
    await db.flush()
    return seed


async def make_relay_race(
    db: AsyncSession,
    organizer: User,
    *,
    team_size: int = 3,
    teams: Sequence[Sequence[User]],
    graph: dict[str, Any] | None = None,
) -> Race:
    """A relay race with one team per inner list, members in order (the first is
    the team's first runner). An empty list makes an empty placeholder team."""
    seed = await make_relay_seed(db, suffix=f"race_{organizer.twitch_id}_{len(teams)}", graph=graph)
    race = Race(
        name="Relay",
        organizer_id=organizer.id,
        seed_id=seed.id,
        relay_team_size=team_size,
    )
    db.add(race)
    await db.flush()
    for index, users in enumerate(teams):
        team = RelayTeam(
            race_id=race.id,
            name=f"Team {index + 1}",
            color_index=index,
            placeholder=not users,
        )
        db.add(team)
        await db.flush()
        for user in users:
            member = Participant(
                race_id=race.id, user_id=user.id, relay_team_id=team.id, color_index=index
            )
            db.add(member)
            await db.flush()
            if team.first_runner_id is None:
                team.first_runner_id = member.id
    await db.commit()
    loaded = await db.execute(
        select(Race)
        .where(Race.id == race.id)
        .options(selectinload(Race.participants))
        .execution_options(populate_existing=True)
    )
    return loaded.scalar_one()


async def run_relay_race(db: AsyncSession, race: Race, *, started_at: datetime) -> None:
    """Put ``race`` (from ``make_relay_race``) in play since ``started_at``, as if
    every team had made its first report: the race RUNNING, each team PLAYING
    with its first runner holding the baton, every member PLAYING and validated.
    Rows only: no mod is connected, so nobody's offline stamp is set."""
    race.status = RaceStatus.RUNNING
    race.started_at = started_at
    race.seeds_released_at = started_at
    for team in race.relay_teams:
        team.status = ParticipantStatus.PLAYING
        team.holder_id = team.first_runner_id
        team.igt_ms = 60_000
        team.last_igt_change_at = datetime.now(UTC)
    for member in race.participants:
        member.status = ParticipantStatus.PLAYING
        member.relay_validated = True
    await db.commit()


# --- Socket tests (integration database of test_integration.py) ---


class RelayModClient(ModTestClient):
    """A mod kept connected across a test; ``close()`` ends its connection.

    ``receive_until`` keeps the messages it skipped in ``skipped``, so a test
    can tell that something was not sent before what it waited for.
    """

    def __init__(self, session: Any, mod_token: str, participant_id: str) -> None:
        """Enter ``session`` (a websocket session not opened yet)."""
        # Set once the server's handler has returned, its disconnect hooks done.
        self._ended = threading.Event()
        app = session.app

        async def run(scope: Any, receive: Any, send: Any) -> None:
            try:
                await app(scope, receive, send)
            finally:
                self._ended.set()

        session.app = run
        session.__enter__()
        super().__init__(session, mod_token)
        self.participant_id = participant_id
        self.skipped: list[dict[str, Any]] = []
        self._closed = False

    @classmethod
    def connect(
        cls, client: TestClient, race_id: str, mod_token: str, participant_id: str
    ) -> RelayModClient:
        return cls(client.websocket_connect(f"/ws/mod/{race_id}"), mod_token, participant_id)

    def send(self, payload: dict[str, Any]) -> None:
        self.ws.send_json(payload)

    def receive_until(
        self,
        msg_type: str,
        where: Callable[[dict[str, Any]], bool] | None = None,
        max_messages: int = 50,
    ) -> dict[str, Any]:
        """The next message of ``msg_type`` that ``where`` accepts."""
        self.skipped = []
        for _ in range(max_messages):
            msg = self.receive()
            if msg.get("type") == msg_type and (where is None or where(msg)):
                return msg
            self.skipped.append(msg)
        raise TimeoutError(f"Did not receive a matching {msg_type}")

    def close(self) -> None:
        """End the session, once the server's handler has returned: leaving a
        test session cancels the server's task at once, and a disconnect hook
        cut in its database work leaks an SQLite connection, sometimes with
        its lock (a later commit then fails with ``database is locked``)."""
        if not self._closed:
            self._closed = True
            if not self._ended.is_set():
                self.ws.close(1000)
                self._ended.wait(timeout=5)
            self.ws.__exit__(None, None, None)

    def disconnect(self) -> None:
        """Close the socket the way a mod does and wait until the server's
        handler has returned, its disconnect hooks done. ``close()`` still
        ends the session."""
        self.ws.close(1000)
        if not self._ended.wait(timeout=5):
            raise TimeoutError("The server did not end the connection within 5s")


_barrier_ids = itertools.count(90_000)


def barrier(mod: RelayModClient) -> None:
    """Wait until the server handled everything ``mod`` sent so far: an unknown
    flag is acknowledged after the messages before it (one loop per socket)."""
    message_id = next(_barrier_ids)
    mod.send_event_flag(1, igt_ms=0, message_id=message_id)
    mod.receive_until("event_flag_ack", lambda m: m["message_id"] == message_id)


def connect_spectator(client: TestClient, race_id: str) -> RelayModClient:
    """An anonymous spectator of the race, past its ``race_state`` (the mod
    client's receive helpers serve it too); ``close()`` ends it."""
    spectator = RelayModClient(
        client.websocket_connect(f"/ws/race/{race_id}"), mod_token="", participant_id=""
    )
    try:
        spectator.send({"type": "no_auth"})
        spectator.receive_until("race_state")
    except BaseException:
        spectator.close()
        raise
    return spectator


def setup_relay_race(
    integration_db: async_sessionmaker[AsyncSession],
    *,
    team_count: int = 2,
    team_size: int = 2,
    graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A relay race ready to start: ``team_count`` teams of ``team_size`` READY
    members (the first of each team is its first runner), seeds released, on
    ``progress_graph`` unless ``graph`` is given.

    Returns ``{"db", "race_id", "organizer", "teams": [{"id", "name",
    "members": [{"participant_id", "mod_token", "user"}]}]}``; ids are strings.
    """

    async def setup() -> dict[str, Any]:
        async with integration_db() as db:
            organizer = User(
                twitch_id="relay_org",
                twitch_username="relay_org",
                twitch_display_name="Relay Org",
                api_token="relay_org_token",
                role=UserRole.ORGANIZER,
            )
            users = [
                User(
                    twitch_id=f"relay_runner_{i}",
                    twitch_username=f"relay_runner_{i}",
                    twitch_display_name=f"Relay Runner {i}",
                    api_token=f"relay_runner_token_{i}",
                    role=UserRole.USER,
                )
                for i in range(team_count * team_size)
            ]
            db.add_all([organizer, *users])
            await db.flush()
            groups = [users[i * team_size : (i + 1) * team_size] for i in range(team_count)]
            race = await make_relay_race(
                db,
                organizer,
                team_size=team_size,
                teams=groups,
                graph=graph if graph is not None else progress_graph(),
            )
            race.seeds_released_at = datetime.now(UTC)
            by_user = {p.user_id: p for p in race.participants}
            start = datetime(2026, 1, 1, tzinfo=UTC)
            for i, user in enumerate(users):
                by_user[user.id].status = ParticipantStatus.READY
                # Distinct join times: member order is by created_at.
                by_user[user.id].created_at = start + timedelta(minutes=i)
            await db.commit()
            teams = sorted(race.relay_teams, key=lambda t: t.name)
            return {
                "db": integration_db,
                "race_id": str(race.id),
                "organizer": organizer,
                "teams": [
                    {
                        "id": str(team.id),
                        "name": team.name,
                        "members": [
                            {
                                "participant_id": str(by_user[u.id].id),
                                "mod_token": by_user[u.id].mod_token,
                                "user": u,
                            }
                            for u in group
                        ],
                    }
                    for team, group in zip(teams, groups, strict=True)
                ],
            }

    return asyncio.run(setup())


def start_relay(client: TestClient, relay_race: Mapping[str, Any]) -> dict[str, RelayModClient]:
    """Connect every member on protocol 1.19, start the race, skip the countdown
    and send each team holder's first ``status_update`` (IGT 1 s), so every team
    is PLAYING on its start node. Returns the mods by participant id; the
    caller closes them."""
    race_id = relay_race["race_id"]
    mods: dict[str, RelayModClient] = {}
    try:
        for team in relay_race["teams"]:
            for member in team["members"]:
                mod = RelayModClient.connect(
                    client, race_id, member["mod_token"], member["participant_id"]
                )
                mods[member["participant_id"]] = mod
                assert mod.auth(protocol_version="1.19")["type"] == "auth_ok"
        response = client.post(
            f"/api/races/{race_id}/start",
            headers={"Authorization": f"Bearer {relay_race['organizer'].api_token}"},
        )
        assert response.status_code == 200, response.json()
        patch_race(relay_race, started_at=datetime.now(UTC) - timedelta(seconds=1))
        for team in relay_race["teams"]:
            holder = mods[team["members"][0]["participant_id"]]
            holder.send_status_update(igt_ms=1_000, death_count=0)
            holder.receive_until("relay_update", lambda m: m["relay"]["team_status"] == "playing")
    except BaseException:
        # An open socket would hold the test client's shutdown forever.
        for mod in mods.values():
            mod.close()
        raise
    return mods


def live_take_timers() -> list[Any]:
    """The relay_take timers still running in the server's rooms."""
    return [
        pending
        # Copies: the server's thread drops a room when its timer ends.
        for room in list(manager.rooms.values())
        for pending in list(room.relay_pending.values())
        if pending.timer is not None and not pending.timer.done()
    ]


def wait_for_timers(seconds: float = 2.0) -> None:
    """Wait until no take timer is running (each fired or was stopped)."""
    deadline = time.monotonic() + seconds
    while live_take_timers() and time.monotonic() < deadline:
        time.sleep(0.01)


def started_mods(
    client: TestClient, relay_race: Mapping[str, Any]
) -> Iterator[dict[str, RelayModClient]]:
    """A fixture body: ``start_relay``'s mods, closed after the test, which must
    not leave a relay_take timer running (it acknowledges the take or waits
    for the timer to fire)."""
    mods = start_relay(client, relay_race)
    yield mods
    left = live_take_timers()
    for mod in mods.values():
        mod.close()
    assert not left, "a relay_take timer outlived its test"


def member_view(update: Mapping[str, Any], participant_id: str) -> dict[str, Any]:
    """One member's entry in a ``relay_update``."""
    member: dict[str, Any] = next(
        m for m in update["relay"]["members"] if m["participant_id"] == participant_id
    )
    return member


def validate(mod: RelayModClient) -> None:
    """The member's first report under 60 s passes its fresh-save gate."""
    mod.send_status_update(igt_ms=2_000, death_count=0)
    mod.receive_until("relay_update", lambda m: member_view(m, mod.participant_id)["validated"])


def set_ready(mod: RelayModClient) -> None:
    """The member is loaded at the Chapel with its lock raised."""
    mod.send({"type": "relay_ready", "ready": True})
    mod.receive_until("relay_update", lambda m: member_view(m, mod.participant_id)["ready"])


def pass_gate(mod: RelayModClient, flag: int, igt_ms: int, message_id: int) -> None:
    """The holder takes a fog gate of ``progress_graph`` (its zone_update back)."""
    node = progress_graph()["event_map"][str(flag)]
    mod.send_event_flag(flag, igt_ms=igt_ms, message_id=message_id)
    mod.receive_until("zone_update", lambda m: m["node_id"] == node)


def make_receiver(mod: RelayModClient) -> None:
    """The member may receive the baton: validated, then ready at the Chapel."""
    validate(mod)
    set_ready(mod)


def _run(relay_race: Mapping[str, Any], work: Callable[[AsyncSession], Any]) -> Any:
    async def run() -> Any:
        async with relay_race["db"]() as db:
            result = await work(db)
            await db.commit()
            return result

    return asyncio.run(run())


def load_team(relay_race: Mapping[str, Any], index: int = 0) -> RelayTeam:
    team_id = UUID(relay_race["teams"][index]["id"])

    async def work(db: AsyncSession) -> RelayTeam:
        team = await db.get(RelayTeam, team_id)
        assert team is not None
        return team

    team: RelayTeam = _run(relay_race, work)
    return team


def load_members(relay_race: Mapping[str, Any], index: int = 0) -> list[Participant]:
    team_id = UUID(relay_race["teams"][index]["id"])

    async def work(db: AsyncSession) -> list[Participant]:
        result = await db.execute(
            select(Participant)
            .where(Participant.relay_team_id == team_id)
            .order_by(Participant.created_at)
        )
        return list(result.scalars())

    members: list[Participant] = _run(relay_race, work)
    return members


def load_member(relay_race: Mapping[str, Any], participant_id: str) -> Participant:
    async def work(db: AsyncSession) -> Participant:
        member = await db.get(Participant, UUID(participant_id))
        assert member is not None
        return member

    member: Participant = _run(relay_race, work)
    return member


def load_race(relay_race: Mapping[str, Any]) -> Race:
    async def work(db: AsyncSession) -> Race:
        race = await db.get(Race, UUID(relay_race["race_id"]))
        assert race is not None
        return race

    race: Race = _run(relay_race, work)
    return race


def patch_team(relay_race: Mapping[str, Any], index: int = 0, **fields: Any) -> None:
    async def work(db: AsyncSession) -> None:
        team = await db.get(RelayTeam, UUID(relay_race["teams"][index]["id"]))
        for key, value in fields.items():
            setattr(team, key, value)

    _run(relay_race, work)


def patch_member(relay_race: Mapping[str, Any], participant_id: str, **fields: Any) -> None:
    async def work(db: AsyncSession) -> None:
        member = await db.get(Participant, UUID(participant_id))
        for key, value in fields.items():
            setattr(member, key, value)

    _run(relay_race, work)


def patch_race(relay_race: Mapping[str, Any], **fields: Any) -> None:
    async def work(db: AsyncSession) -> None:
        race = await db.get(Race, UUID(relay_race["race_id"]))
        for key, value in fields.items():
            setattr(race, key, value)

    _run(relay_race, work)
