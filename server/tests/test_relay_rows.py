"""A relay race's leaderboard messages carry one row per team."""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from speedfog_racing import database as db_module
from speedfog_racing.database import Base
from speedfog_racing.models import Participant, ParticipantStatus, Race, RelayTeam, User
from speedfog_racing.services.relay import leaderboard_entries, load_relay_row
from speedfog_racing.websocket.race import spectator as race_spectator
from speedfog_racing.websocket.race.manager import (
    ConnectionManager,
    build_leaderboard_payload,
    participant_to_info,
    sort_leaderboard,
)
from tests.relay_fixtures import make_relay_race

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def rr_session(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_module, "async_session_maker", maker)
    yield maker
    await engine.dispose()


async def _users(db, n: int) -> list[User]:
    users = [
        User(
            twitch_id=f"rr{i}",
            twitch_username=f"rr{i}",
            twitch_display_name=f"Runner {i}",
            api_token=f"rrt{i}",
        )
        for i in range(n)
    ]
    db.add_all(users)
    await db.flush()
    return users


async def _load(db, race_id) -> Race:
    result = await db.execute(
        select(Race)
        .where(Race.id == race_id)
        .options(
            selectinload(Race.seed),
            selectinload(Race.participants).selectinload(Participant.user),
        )
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


@pytest.fixture
async def relay_race(rr_session):
    """Two teams of two, the first team's first runner holding the baton."""
    async with rr_session() as db:
        users = await _users(db, 5)
        race = await make_relay_race(
            db, users[0], team_size=2, teams=[[users[1], users[2]], [users[3], users[4]]]
        )
        race_id = race.id
    async with rr_session() as db:
        race = await _load(db, race_id)
        for team in race.relay_teams:
            members = [p for p in race.participants if p.relay_team_id == team.id]
            team.holder_id = members[0].id
            team.status = ParticipantStatus.PLAYING
        for p in race.participants:
            p.status = ParticipantStatus.PLAYING
        await db.commit()
    async with rr_session() as db:
        return await _load(db, race_id)


def _team(race: Race, name: str) -> RelayTeam:
    return next(t for t in race.relay_teams if t.name == name)


async def test_team_row_is_participant_shaped(relay_race):
    graph = relay_race.seed.graph_json
    team = _team(relay_race, "Team 1")
    holder = next(p for p in relay_race.participants if p.id == team.holder_id)
    other = next(
        p for p in relay_race.participants if p.relay_team_id == team.id and p.id != holder.id
    )
    row = next(r for r in leaderboard_entries(relay_race, graph) if r.id == team.id)

    info = participant_to_info(row, connected_ids={holder.id}, graph_json=graph)

    assert (info.id, info.twitch_display_name, info.twitch_username) == (
        str(team.id),
        "Team 1",
        f"team-{str(team.id)[:8]}",
    )
    assert (info.mod_connected, info.relay_holder_id, info.relay_holder) == (
        True,
        str(holder.id),
        holder.user.twitch_display_name,
    )
    assert info.relay_cap == row.cap
    assert info.relay_members is not None
    assert [(m.participant_id, m.online) for m in info.relay_members] == [
        (str(holder.id), True),
        (str(other.id), False),
    ]
    assert all(m.status == "playing" and not m.ready for m in info.relay_members)


async def test_team_row_follows_the_holder_connection(relay_race):
    graph = relay_race.seed.graph_json
    team = _team(relay_race, "Team 1")
    waiting = next(
        p for p in relay_race.participants if p.relay_team_id == team.id and p.id != team.holder_id
    )
    row = next(r for r in leaderboard_entries(relay_race, graph) if r.id == team.id)
    # Only a waiting member is online: the team's mod is not connected.
    info = participant_to_info(row, connected_ids={waiting.id}, graph_json=graph)
    assert info.mod_connected is False
    assert [m.online for m in info.relay_members or []] == [False, True]


async def test_teams_rank_like_runners(rr_session):
    async with rr_session() as db:
        users = await _users(db, 7)
        race = await make_relay_race(
            db,
            users[0],
            team_size=2,
            teams=[[users[1], users[2]], [users[3], users[4]], [users[5], users[6]]],
        )
        race_id = race.id
    async with rr_session() as db:
        race = await _load(db, race_id)
        a, b, c = sorted(race.relay_teams, key=lambda t: t.name)
        a.status, a.igt_ms, a.current_layer = ParticipantStatus.FINISHED, 90_000, 12
        b.status, b.current_layer, b.igt_ms = ParticipantStatus.PLAYING, 8, 50_000
        c.status, c.current_layer, c.igt_ms = ParticipantStatus.PLAYING, 3, 20_000
        await db.commit()
    async with rr_session() as db:
        race = await _load(db, race_id)
    graph = race.seed.graph_json
    # Entries are not in rank order to start with.
    entries = list(reversed(leaderboard_entries(race, graph)))

    ordered, _ = sort_leaderboard(entries, graph_json=graph)

    assert [e.team.name for e in ordered] == ["Team 1", "Team 2", "Team 3"]
    payload = json.loads(build_leaderboard_payload(entries, connected_ids=set(), graph_json=graph))
    assert [p["twitch_display_name"] for p in payload["participants"]] == [
        "Team 1",
        "Team 2",
        "Team 3",
    ]


async def test_solo_rows_carry_no_relay_field(rr_session, sample_graph_json):
    async with rr_session() as db:
        (user,) = await _users(db, 1)
        from speedfog_racing.models import Seed

        seed = Seed(
            seed_number="rrsolo",
            pool_name="standard",
            graph_json=sample_graph_json,
            total_layers=5,
            folder_path="/t/rrsolo",
        )
        db.add(seed)
        await db.flush()
        race = Race(name="Solo", organizer_id=user.id, seed_id=seed.id)
        db.add(race)
        await db.flush()
        db.add(Participant(race_id=race.id, user_id=user.id))
        await db.commit()
        race_id = race.id
    async with rr_session() as db:
        race = await _load(db, race_id)
    assert leaderboard_entries(race, race.seed.graph_json) is race.participants
    dumped = participant_to_info(race.participants[0]).model_dump()
    assert dumped["relay_holder"] is None and dumped["relay_holder_id"] is None
    assert dumped["relay_cap"] is None and dumped["relay_members"] is None


async def test_race_state_of_a_relay_race_lists_teams(relay_race):
    payload = json.loads(
        race_spectator.build_race_state_payload(relay_race, locale="en", pending_invites=[])
    )
    assert payload["type"] == "race_state"
    assert len(payload["participants"]) == 2
    assert all(len(p["relay_members"]) == 2 for p in payload["participants"])


async def test_team_zone_history_reaches_race_state(rr_session, relay_race):
    history = [{"node_id": "n1", "igt_ms": 1000, "deaths": 0, "runner_id": "abc"}]
    async with rr_session() as db:
        race = await _load(db, relay_race.id)
        _team(race, "Team 1").zone_history = history
        await db.commit()
    async with rr_session() as db:
        race = await _load(db, relay_race.id)
    payload = json.loads(
        race_spectator.build_race_state_payload(race, locale="en", pending_invites=[])
    )
    by_name = {p["twitch_display_name"]: p for p in payload["participants"]}
    assert by_name["Team 1"]["zone_history"] == history


async def test_broadcast_sends_team_rows_to_the_room(rr_session, relay_race):
    class _WS:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send_text(self, message: str) -> None:
            self.sent.append(message)

    mgr = ConnectionManager()
    room = mgr.get_or_create_room(relay_race.id)
    ws = _WS()
    conn = race_spectator.SpectatorConnection(websocket=ws, locale="en")  # type: ignore[arg-type]
    room.spectators[conn.connection_id] = conn
    graph = relay_race.seed.graph_json

    await mgr.broadcast_leaderboard(
        relay_race.id, leaderboard_entries(relay_race, graph), graph_json=graph
    )
    team = _team(relay_race, "Team 2")
    async with rr_session() as db:
        row = await load_relay_row(db, team.id, graph)
    assert row is not None
    await mgr.broadcast_player_update(relay_race.id, row, graph_json=graph)

    update = json.loads(ws.sent[0])
    assert {p["id"] for p in update["participants"]} == {str(t.id) for t in relay_race.relay_teams}
    player = json.loads(ws.sent[1])
    assert player["type"] == "player_update"
    assert player["player"]["id"] == str(team.id)
    assert len(player["player"]["relay_members"]) == 2


class _WS:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, message: str) -> None:
        self.sent.append(message)


async def _handler_with_spectator(rr_session, race, monkeypatch):
    from unittest.mock import MagicMock

    from speedfog_racing.websocket.race import mod as race_mod

    mgr = ConnectionManager()
    monkeypatch.setattr(race_mod, "manager", mgr)
    ws = _WS()
    conn = race_spectator.SpectatorConnection(websocket=ws, locale="en")  # type: ignore[arg-type]
    mgr.get_or_create_room(race.id).spectators[conn.connection_id] = conn
    handler = race_mod.RaceModHandler(MagicMock(), race.id, rr_session)
    handler._cached_graph_json = race.seed.graph_json
    return handler, ws


@pytest.mark.parametrize("loader", ["_load_participant_no_seed", "_load_participant_light"])
async def test_runner_update_goes_out_as_the_team_row_from_a_light_loader(
    rr_session, relay_race, monkeypatch, loader
):
    # The status_update fast path loads the runner without race.participants:
    # the team row is loaded on its own instead of read off the race.
    from speedfog_racing.websocket.race import mod as race_mod

    team = _team(relay_race, "Team 1")
    handler, ws = await _handler_with_spectator(rr_session, relay_race, monkeypatch)
    async with rr_session() as db:
        entity = await getattr(race_mod, loader)(db, team.holder_id)
    handler._participant_id = entity.id

    await handler._broadcast_after_status_update(
        entity, became_active=False, death_delta=0, history_changed=False, weapons=None
    )

    player = json.loads(ws.sent[0])["player"]
    assert player["id"] == str(team.id)
    assert player["relay_holder_id"] == str(team.holder_id)
    assert len(player["relay_members"]) == 2


async def test_event_flag_and_zone_query_updates_go_out_as_the_team_row(
    rr_session, relay_race, monkeypatch
):
    from speedfog_racing.websocket.race import mod as race_mod

    team = _team(relay_race, "Team 1")
    handler, ws = await _handler_with_spectator(rr_session, relay_race, monkeypatch)
    graph = relay_race.seed.graph_json
    async with rr_session() as db:
        entity = await race_mod._load_participant_no_seed(db, team.holder_id)
    await handler._broadcast_after_event_flag(
        entity, "n1", graph, is_first_visit=False, prev_zone_history_len=None
    )
    async with rr_session() as db:
        entity = await race_mod._load_participant(db, team.holder_id)
    await handler._broadcast_after_zone_query(
        entity, is_first_visit=False, prev_zone_history_len=None
    )

    players = [json.loads(m) for m in ws.sent if '"player_update"' in m]
    assert [p["player"]["id"] for p in players] == [str(team.id)] * 2


async def test_death_counts_aggregate_over_team_rows(relay_race):
    from speedfog_racing.websocket.race.mod import aggregate_death_counts

    a, b = sorted(relay_race.relay_teams, key=lambda t: t.name)
    a.zone_history = [{"node_id": "n1", "deaths": 2}, {"node_id": "n2"}]
    b.zone_history = [{"node_id": "n1", "deaths": 1}, {"node_id": "n3", "deaths": 0}]

    rows = leaderboard_entries(relay_race, relay_race.seed.graph_json)

    assert aggregate_death_counts(rows) == {"n1": 3}
