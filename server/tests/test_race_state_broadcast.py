"""race_state broadcasts build the state once, not once per spectator.

The broadcast used to open a DB session (pending invites) and re-serialize the
full state (~170 KB with the seed graph) for every spectator, all concurrently:
S spectators meant S simultaneous DB connections on every race end or abandon.
"""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from speedfog_racing import database as db_module
from speedfog_racing.database import Base
from speedfog_racing.models import (
    Caster,
    Invite,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.websocket.race import spectator as race_spectator
from speedfog_racing.websocket.race.manager import ConnectionManager, SpectatorConnection


class _RecordingWS:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, message: str) -> None:
        self.sent.append(message)


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def race(async_engine, sample_graph_json, monkeypatch):
    maker = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_module, "async_session_maker", maker)
    async with maker() as db:
        org = User(twitch_id="rso", twitch_username="rso", api_token="rsot", role=UserRole.USER)
        players = [
            User(twitch_id=f"rsp{i}", twitch_username=f"rsp{i}", api_token=f"rspt{i}")
            for i in range(2)
        ]
        db.add_all([org, *players])
        await db.flush()
        seed = Seed(
            seed_number="rss",
            pool_name="standard",
            graph_json=sample_graph_json,
            total_layers=5,
            folder_path="/t/rss",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()
        race = Race(name="State", organizer_id=org.id, seed_id=seed.id, status=RaceStatus.SETUP)
        db.add(race)
        await db.flush()
        for i, player in enumerate(players):
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=player.id,
                    mod_token=f"rsm{i}",
                    status=ParticipantStatus.REGISTERED,
                )
            )
        db.add_all(
            [
                Invite(race_id=race.id, twitch_username="alice"),
                Invite(race_id=race.id, twitch_username="bob"),
                Invite(race_id=race.id, twitch_username="carol", accepted=True),
            ]
        )
        await db.commit()
        race_id = race.id
    async with maker() as db:
        return (
            await db.execute(
                select(Race)
                .where(Race.id == race_id)
                .options(
                    selectinload(Race.seed),
                    selectinload(Race.participants).selectinload(Participant.user),
                    selectinload(Race.casters).selectinload(Caster.user),
                )
            )
        ).scalar_one()


async def test_broadcast_builds_once_per_locale_and_queries_invites_once(
    async_engine, race, monkeypatch
):
    mgr = ConnectionManager()
    monkeypatch.setattr(race_spectator, "manager", mgr)
    # Stamp the locale into the translated graph so a payload served to the
    # wrong locale is visible (translations are not loaded in tests).
    monkeypatch.setattr(
        race_spectator, "translate_graph_json", lambda graph, locale: {**graph, "_locale": locale}
    )
    real_build = race_spectator.build_race_state_payload
    built_locales: list[str] = []

    def counting_build(race, *, locale, pending_invites):  # type: ignore[no-untyped-def]
        built_locales.append(locale)
        return real_build(race, locale=locale, pending_invites=pending_invites)

    monkeypatch.setattr(race_spectator, "build_race_state_payload", counting_build)
    room = mgr.get_or_create_room(race.id)
    sockets = {locale: [_RecordingWS(), _RecordingWS()] for locale in ("en", "fr")}
    for locale, wss in sockets.items():
        for ws in wss:
            conn = SpectatorConnection(websocket=ws, locale=locale)  # type: ignore[arg-type]
            room.spectators[conn.connection_id] = conn
    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        statements.append(statement)

    event.listen(async_engine.sync_engine, "before_cursor_execute", capture)
    try:
        await race_spectator.broadcast_race_state_update(race.id, race)
    finally:
        event.remove(async_engine.sync_engine, "before_cursor_execute", capture)

    assert len([s for s in statements if "FROM invites" in s]) == 1
    assert sorted(built_locales) == ["en", "fr"]
    for locale, wss in sockets.items():
        for ws in wss:
            assert len(ws.sent) == 1
            payload = json.loads(ws.sent[0])
            assert payload["type"] == "race_state"
            assert payload["seed"]["graph_json"].get("_locale") == (
                locale if locale != "en" else None
            )
            assert len(payload["participants"]) == 2
            assert sorted(p["twitch_username"] for p in payload["pending_invites"]) == [
                "alice",
                "bob",
            ]


async def test_broadcast_without_spectators_skips_the_query(async_engine, race, monkeypatch):
    mgr = ConnectionManager()
    monkeypatch.setattr(race_spectator, "manager", mgr)
    mgr.get_or_create_room(race.id)  # a room with nobody watching
    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        statements.append(statement)

    event.listen(async_engine.sync_engine, "before_cursor_execute", capture)
    try:
        await race_spectator.broadcast_race_state_update(race.id, SimpleNamespace())  # type: ignore[arg-type]
    finally:
        event.remove(async_engine.sync_engine, "before_cursor_execute", capture)

    assert statements == []
