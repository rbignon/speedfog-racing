"""Relay race fixtures: a relay seed, and a relay race with its teams inserted directly.

Shared by the relay tests, on the model of ``event_fixtures.py``. Rows are
inserted without going through the routes, so a test of the rules does not
depend on the routes that build teams.

The socket tests use ``setup_relay_race`` (a race ready to start, on the
integration database of ``test_integration.py``), ``start_relay`` (every member
connected, the race started, each holder's first report sent) and
``RelayModClient``, a mod kept connected across a test.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from starlette.testclient import TestClient

from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RelayTeam,
    Seed,
    User,
    UserRole,
)

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


# --- Socket tests (integration database of test_integration.py) ---


class RelayModClient(ModTestClient):
    """A mod kept connected across a test; ``close()`` ends its connection.

    ``receive_until`` keeps the messages it skipped in ``skipped``, so a test
    can tell that something was not sent before what it waited for.
    """

    def __init__(self, session: Any, mod_token: str, participant_id: str) -> None:
        super().__init__(session, mod_token)
        self.participant_id = participant_id
        self.skipped: list[dict[str, Any]] = []
        self._closed = False

    @classmethod
    def connect(
        cls, client: TestClient, race_id: str, mod_token: str, participant_id: str
    ) -> RelayModClient:
        session = client.websocket_connect(f"/ws/mod/{race_id}")
        session.__enter__()
        return cls(session, mod_token, participant_id)

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
        if not self._closed:
            self._closed = True
            self.ws.__exit__(None, None, None)


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
