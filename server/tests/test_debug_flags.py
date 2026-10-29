"""Cheat detection: game debug flags reported by the mod."""

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.discord import notify_debug_flags_detected
from speedfog_racing.main import app
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Pool,
    Race,
    RaceStatus,
    RunMode,
    Seed,
    SeedStatus,
    TrainingSession,
    User,
    UserRole,
)
from speedfog_racing.services.debug_flags import debug_flag_label, merge_debug_flags
from speedfog_racing.websocket.race.manager import RaceRoom, SpectatorConnection
from speedfog_racing.websocket.schemas import ParticipantInfo
from speedfog_racing.websocket.training.mod import TrainingModHandler, _load_session_no_graph

NOW = datetime(2026, 10, 1, 20, 0, tzinfo=UTC)


def test_merge_records_first_observation() -> None:
    merged, added = merge_debug_flags(None, ["one_shot"], igt_ms=83000, node_id="node_a", now=NOW)
    assert added == ["one_shot"]
    assert merged == {
        "one_shot": {"igt_ms": 83000, "node_id": "node_a", "detected_at": NOW.isoformat()}
    }


def test_merge_keeps_first_observation_and_adds_only_new_flags() -> None:
    existing = {"one_shot": {"igt_ms": 1000, "node_id": "start_node", "detected_at": "x"}}
    merged, added = merge_debug_flags(
        existing, ["one_shot", "infinite_stamina"], igt_ms=5000, node_id="node_b", now=NOW
    )
    assert added == ["infinite_stamina"]
    assert merged is not None
    assert merged["one_shot"] == existing["one_shot"]
    assert merged["infinite_stamina"]["igt_ms"] == 5000


def test_merge_with_nothing_new_returns_existing() -> None:
    existing = {"one_shot": {"igt_ms": 1000, "node_id": None, "detected_at": "x"}}
    merged, added = merge_debug_flags(existing, ["one_shot"], igt_ms=9000, node_id=None, now=NOW)
    assert added == []
    assert merged is existing


@pytest.mark.parametrize(
    "reported",
    [None, "one_shot", {"one_shot": True}, [1, 2], ["god_mode"], ["one_shot"] * 65],
)
def test_merge_ignores_malformed_reports(reported: object) -> None:
    assert merge_debug_flags(None, reported, igt_ms=1000, node_id=None, now=NOW) == (None, [])


def test_merge_keeps_known_names_next_to_unknown_ones() -> None:
    # A newer mod may know flags this server does not: keep the known ones.
    merged, added = merge_debug_flags(
        None, ["future_flag", "one_shot"], igt_ms=1000, node_id=None, now=NOW
    )
    assert added == ["one_shot"]
    assert merged is not None and set(merged) == {"one_shot"}


def _handler(maker: Any = None) -> TrainingModHandler:
    return TrainingModHandler(MagicMock(), uuid.uuid4(), maker or MagicMock())


def _session(mode: RunMode, **fields: Any) -> TrainingSession:
    return TrainingSession(mode=mode, igt_ms=fields.pop("igt_ms", 0), **fields)


def test_normal_session_ignores_debug_flags() -> None:
    entity = _session(RunMode.NORMAL)
    assert _handler()._record_debug_flags(entity, ["one_shot"], 1000) == []
    assert entity.debug_flags is None


@pytest.mark.parametrize("mode", [RunMode.SPEEDRUN, RunMode.SET_SEED])
def test_ranked_session_records_debug_flags_once(mode: RunMode) -> None:
    entity = _session(mode, current_zone="node_a")
    handler = _handler()

    assert handler._record_debug_flags(entity, ["one_shot"], 83000) == ["one_shot"]
    assert handler._record_debug_flags(entity, ["one_shot"], 90000) == []
    assert entity.debug_flags is not None
    assert entity.debug_flags["one_shot"]["igt_ms"] == 83000
    assert entity.debug_flags["one_shot"]["node_id"] == "node_a"


async def test_ranked_session_records_debug_flags_and_alerts(df_session) -> None:
    async with df_session() as db:
        user = User(twitch_id="t1", twitch_username="runner", twitch_display_name="Runner")
        db.add(user)
        db.add(Pool(name="sprint", config={"name": "Sprint", "type": "race"}))
        await db.flush()
        seed = Seed(
            seed_number="s1",
            pool_name="sprint",
            graph_json={"nodes": {"node_a": {"display_name": "Gate"}}},
            total_layers=15,
            folder_path="/t/s1",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()
        entity = TrainingSession(user_id=user.id, seed_id=seed.id, mode=RunMode.SPEEDRUN)
        db.add(entity)
        await db.flush()
        entity.current_zone = "node_a"
        await db.commit()
        # The cached-graph path of a status_update: the seed brings no graph.
        db.expunge_all()  # else the identity map hands back the full seed
        entity = await _load_session_no_graph(db, entity.id)
        assert entity is not None
        handler = _handler(df_session)
        handler._cached_graph_json = {"nodes": {"node_a": {"display_name": "Gate"}}}
        added = handler._record_debug_flags(entity, ["one_shot"], 83000)

        with patch("speedfog_racing.websocket.training.mod.fire_debug_flags_notification") as fire:
            await handler._on_debug_flags_recorded(entity, added)

    fire.assert_called_once()
    kwargs = fire.call_args.kwargs
    assert kwargs["session_id"] == str(entity.id)
    assert kwargs["race_id"] is None
    assert kwargs["race_name"] == "Solo \u00b7 Sprint \u00b7 Speedrun"
    assert (kwargs["flags"], kwargs["igt_ms"]) == (["one_shot"], 83000)


async def test_session_alert_links_the_training_page() -> None:
    mock_send = AsyncMock()
    with patch("speedfog_racing.discord._send_admin_webhook", mock_send):
        await notify_debug_flags_detected(
            race_name="Solo \u00b7 Sprint \u00b7 Set Seed",
            race_id=None,
            session_id="abc",
            player_name="Runner",
            flags=["one_shot"],
            igt_ms=1000,
            zone_name="Gate",
        )
    embed = mock_send.call_args.args[0]
    assert embed["url"].endswith("/training/abc")
    assert embed["fields"][0]["name"] == "Run"


@pytest.mark.parametrize(
    ("mode", "accepted"),
    [(RunMode.SPEEDRUN, False), (RunMode.SET_SEED, False), (RunMode.NORMAL, True)],
)
def test_ranked_session_rejects_implausible_igt(mode: RunMode, accepted: bool) -> None:
    """A forward jump past wall-clock time is a wrong save on a ranked
    session only; a normal session has no wall reference."""
    entity = _session(mode, igt_ms=600_000)
    handler = _handler()
    handler._on_igt_change(entity, 601_000)  # a changed report starts the reference
    assert (entity.last_igt_change_at is not None) == (mode != RunMode.NORMAL)

    assert handler._igt_plausible(entity, 601_000 + 7_200_000) is accepted
    assert handler._igt_plausible(entity, 100_000)  # restores stay plausible


def test_equal_igt_report_does_not_move_the_reference() -> None:
    entity = _session(RunMode.SPEEDRUN, igt_ms=500_000)
    _handler()._on_igt_change(entity, 500_000)
    assert entity.last_igt_change_at is None


async def test_staff_broadcast_reaches_organizer_and_admins_only() -> None:
    room = RaceRoom(race_id=uuid.uuid4())
    sockets = {role: AsyncMock() for role in ("organizer", "admin", "caster", "participant", None)}
    conns = [SpectatorConnection(websocket=ws, role=role) for role, ws in sockets.items()]
    room.spectators = {c.connection_id: c for c in conns}

    await room.broadcast_to_race_staff('{"type": "debug_flags_detected"}')

    for role, ws in sockets.items():
        assert ws.send_text.called == (role in ("organizer", "admin")), role


async def test_admin_discord_embed_names_runner_flags_and_place() -> None:
    mock_send = AsyncMock()
    with patch("speedfog_racing.discord._send_admin_webhook", mock_send):
        await notify_debug_flags_detected(
            race_name="Friday race",
            race_id="r1",
            player_name="Some_Runner",
            flags=["one_shot", "infinite_stamina"],
            igt_ms=83000,
            zone_name="Stormveil Castle",
        )
    embed = mock_send.call_args[0][0]
    assert "Some\\_Runner" in embed["title"]  # markdown-escaped
    values = {f["name"]: f["value"] for f in embed["fields"]}
    for name in ("one_shot", "infinite_stamina"):
        assert debug_flag_label(name) in values["Flags"]
    assert "one_shot" not in values["Flags"], "labels, not wire names"
    assert values["IGT"] == "1:23"  # _format_igt drops the hour under one hour
    assert values["Zone"] == "Stormveil Castle"


async def test_admin_webhook_is_a_noop_without_url() -> None:
    from speedfog_racing.discord import _send_admin_webhook

    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.httpx.AsyncClient") as mock_client,
    ):
        mock_settings.discord_admin_webhook_url = None
        await _send_admin_webhook({"title": "x"})
    mock_client.assert_not_called()


FLAGS = {
    "one_shot": {"igt_ms": 83000, "node_id": "node_a", "detected_at": "2026-10-01T20:00:00+00:00"}
}


@pytest.fixture
async def df_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def df_client(df_session):
    async def override_get_db():
        async with df_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


@pytest.fixture
async def df_users(df_session) -> dict[str, User]:
    roles = {
        "organizer": UserRole.ORGANIZER,
        "admin": UserRole.ADMIN,
        "flagged": UserRole.USER,
        "other": UserRole.USER,
    }
    async with df_session() as db:
        users = {
            key: User(
                twitch_id=f"df_{key}",
                twitch_username=f"{key}_df",
                api_token=f"df_{key}_token",
                role=role,
            )
            for key, role in roles.items()
        }
        db.add_all(users.values())
        await db.commit()
        for user in users.values():
            await db.refresh(user)
        return users


async def _flagged_race(
    df_session,
    df_users,
    *,
    detected: dict[str, str | None],
    nodes: dict[str, dict[str, str]] | None = None,
    node_ids: dict[str, str | None] | None = None,
) -> uuid.UUID:
    """A running race organized by "organizer" where each user key in
    ``detected`` participates; a non-None value is that participant's
    detection time."""
    async with df_session() as db:
        seed = Seed(
            seed_number=f"df_{uuid.uuid4().hex[:8]}",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": nodes or {}},
            total_layers=5,
            folder_path="/test/df",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()
        race = Race(
            name="Flag race",
            organizer_id=df_users["organizer"].id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()
        for key, detected_at in detected.items():
            flags = (
                None
                if detected_at is None
                else {
                    "one_shot": {
                        **FLAGS["one_shot"],
                        "detected_at": detected_at,
                        "node_id": (node_ids or {}).get(key, FLAGS["one_shot"]["node_id"]),
                    }
                }
            )
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=df_users[key].id,
                    status=ParticipantStatus.PLAYING,
                    debug_flags=flags,
                )
            )
        await db.commit()
        return race.id


async def test_race_detail_exposes_debug_flags_to_staff_only(df_client, df_session, df_users):
    race_id = await _flagged_race(
        df_session, df_users, detected={"flagged": FLAGS["one_shot"]["detected_at"], "other": None}
    )
    visible = {"organizer": True, "admin": True, "flagged": False, "other": False, None: False}
    async with df_client as client:
        for who, can_see in visible.items():
            headers = {"Authorization": f"Bearer {df_users[who].api_token}"} if who else {}
            resp = await client.get(f"/api/races/{race_id}", headers=headers)
            assert resp.status_code == 200, resp.text
            row = next(
                p
                for p in resp.json()["participants"]
                if p["user"]["twitch_username"] == "flagged_df"
            )
            assert (row["debug_flags"] is not None) == can_see, who


def test_public_participant_info_never_carries_debug_flags() -> None:
    # leaderboard_update, player_update and race_state are public.
    assert "debug_flags" not in ParticipantInfo.model_fields


async def test_cheat_detections_most_recent_first(df_client, df_session, df_users):
    await _flagged_race(
        df_session,
        df_users,
        detected={
            "flagged": "2026-09-01T10:00:00+00:00",
            "other": "2026-09-02T10:00:00+00:00",
            "admin": None,
        },
    )
    async with df_client as client:
        resp = await client.get(
            "/api/admin/cheat-detections",
            headers={"Authorization": f"Bearer {df_users['admin'].api_token}"},
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert [d["user"]["twitch_username"] for d in data] == ["other_df", "flagged_df"]
    assert data[0]["race_name"] == "Flag race"
    assert data[0]["last_detected_at"] == "2026-09-02T10:00:00+00:00"


async def test_cheat_detections_capped(df_client, df_session, df_users, monkeypatch):
    from speedfog_racing.api import admin as admin_api

    monkeypatch.setattr(admin_api, "CHEAT_DETECTIONS_LIMIT", 1, raising=False)
    await _flagged_race(
        df_session,
        df_users,
        detected={"flagged": "2026-09-01T10:00:00+00:00", "other": "2026-09-02T10:00:00+00:00"},
    )
    async with df_client as client:
        resp = await client.get(
            "/api/admin/cheat-detections",
            headers={"Authorization": f"Bearer {df_users['admin'].api_token}"},
        )
    assert [d["user"]["twitch_username"] for d in resp.json()] == ["other_df"]


async def test_cheat_detections_name_the_zones(df_client, df_session, df_users):
    await _flagged_race(
        df_session,
        df_users,
        detected={"flagged": "2026-09-01T10:00:00+00:00"},
        nodes={"node_a": {"display_name": "Stormveil Castle"}},
    )
    async with df_client as client:
        resp = await client.get(
            "/api/admin/cheat-detections",
            headers={"Authorization": f"Bearer {df_users['admin'].api_token}"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["zone_names"] == {"node_a": "Stormveil Castle"}


async def test_cheat_detections_zone_names_skip_missing_nodes_and_fall_back(
    df_client, df_session, df_users
):
    # A race reset clears current_zone, so a detection recorded right after it
    # has no node; a node absent from the seed graph keeps its id.
    await _flagged_race(
        df_session,
        df_users,
        detected={"flagged": "2026-09-01T10:00:00+00:00", "other": "2026-09-02T10:00:00+00:00"},
        nodes={"node_a": {"display_name": "Stormveil Castle"}},
        node_ids={"flagged": None, "other": "node_x"},
    )
    async with df_client as client:
        resp = await client.get(
            "/api/admin/cheat-detections",
            headers={"Authorization": f"Bearer {df_users['admin'].api_token}"},
        )
    assert resp.status_code == 200, resp.text
    by_user = {d["user"]["twitch_username"]: d["zone_names"] for d in resp.json()}
    assert by_user == {"flagged_df": {}, "other_df": {"node_x": "node_x"}}


async def test_cheat_detections_requires_admin(df_client, df_users):
    async with df_client as client:
        resp = await client.get(
            "/api/admin/cheat-detections",
            headers={"Authorization": f"Bearer {df_users['organizer'].api_token}"},
        )
    assert resp.status_code == 403
