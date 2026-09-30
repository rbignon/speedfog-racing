"""tools/audit_extract.py: what the audit bundle holds, and what it must never hold."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    ChatChannel,
    ChatMessage,
    Event,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    TrainingSession,
    User,
    UserRole,
)

_SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "audit_extract.py"
_spec = importlib.util.spec_from_file_location("audit_extract", _SCRIPT)
assert _spec is not None and _spec.loader is not None
ae = importlib.util.module_from_spec(_spec)
sys.modules["audit_extract"] = ae
_spec.loader.exec_module(ae)

SINCE = datetime(2026, 9, 20, tzinfo=UTC)
BEFORE = datetime(2026, 9, 1, 12, tzinfo=UTC)
AFTER = datetime(2026, 9, 25, 12, tzinfo=UTC)

SECRETS = ["api-token-alice", "api-token-bob", "mod-token-1", "mod-token-2", "mod-token-3"]
SECRETS += ["training-token-1", "training-token-2"]


def _graph(tag: str) -> dict[str, Any]:
    return {
        "total_layers": 2,
        "nodes": {
            f"start_{tag}": {"type": "start", "layer": 0, "tier": 1, "exits": [{"to": f"b_{tag}"}]},
            f"b_{tag}": {
                "type": "final_boss",
                "layer": 1,
                "tier": 2,
                "display_name": "Vanilla boss",
                "boss_name": f"Boss {tag}",
                "exits": [],
            },
        },
        "edges": [{"from": f"start_{tag}", "to": f"b_{tag}"}],
        "event_map": {"1": f"b_{tag}"},
        "care_package": [],
        "weapon_upgrade": 25,
    }


@pytest.fixture
async def maker(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/db.sqlite", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _populate(maker: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    async with maker() as db:
        alice = User(
            twitch_id="100",
            twitch_username="alice",
            twitch_display_name="Alice",
            api_token="api-token-alice",
            created_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
        bob = User(
            twitch_id="200",
            twitch_username="bobby",
            twitch_display_name="Bobby",
            api_token="api-token-bob",
            created_at=datetime(2026, 9, 24, tzinfo=UTC),
        )
        daily = User(
            twitch_id="1",
            twitch_username="speedfog_daily",
            twitch_display_name="Daily Seed",
            role=UserRole.SYSTEM,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        seeds = {
            tag: Seed(
                seed_number=tag,
                pool_name="standard",
                graph_json=_graph(tag),
                total_layers=2,
                folder_path=f"/seeds/{tag}.zip",
            )
            for tag in ("old", "qual", "new", "solo")
        }
        event = Event(
            slug="ev",
            name="Event",
            starts_at=datetime(2026, 8, 30, tzinfo=UTC),
            qualifier_ends_at=datetime(2026, 10, 8, tzinfo=UTC),
            ends_at=datetime(2026, 11, 1, tzinfo=UTC),
            config={
                "withdrawn": ["bobby"],
                "rules": ["Ask Alice"],
                "modes": [{"key": "standard", "label": "Standard"}],
            },
        )
        db.add_all([daily, alice, bob, event, *seeds.values()])
        await db.flush()
        races = {
            # Before the window, not attached: history.
            "old": Race(
                name="Old", organizer_id=alice.id, seed_id=seeds["old"].id, started_at=BEFORE
            ),
            # Before the window, but attached to the event: under review.
            "qual": Race(
                name="Qualifier",
                organizer_id=alice.id,
                seed_id=seeds["qual"].id,
                started_at=BEFORE,
                event_id=event.id,
                event_slot="qualifier:standard:1",
            ),
            # Inside the window: under review.
            "new": Race(
                name="Bobby's Tuesday race",
                organizer_id=bob.id,
                seed_id=seeds["new"].id,
                started_at=AFTER,
            ),
        }
        for race in races.values():
            race.status = RaceStatus.RUNNING
        db.add_all(races.values())
        await db.flush()
        history = [{"node_id": "start_x", "igt_ms": 0, "type": "spawn"}]
        db.add_all(
            [
                Participant(
                    race_id=races["old"].id,
                    user_id=alice.id,
                    mod_token="mod-token-1",
                    status=ParticipantStatus.FINISHED,
                    zone_history=history,
                ),
                Participant(race_id=races["qual"].id, user_id=alice.id, mod_token="mod-token-2"),
                Participant(race_id=races["new"].id, user_id=bob.id, mod_token="mod-token-3"),
                TrainingSession(
                    user_id=alice.id,
                    seed_id=seeds["solo"].id,
                    mod_token="training-token-1",
                    created_at=BEFORE,
                ),
                TrainingSession(
                    user_id=bob.id,
                    seed_id=seeds["solo"].id,
                    mod_token="training-token-2",
                    created_at=AFTER,
                ),
                ChatMessage(
                    race_id=races["old"].id,
                    channel=ChatChannel.PUBLIC,
                    user_id=alice.id,
                    message="history chat",
                    created_at=datetime(2026, 9, 25, 13, 0, tzinfo=UTC),
                ),
                ChatMessage(
                    race_id=races["new"].id,
                    channel=ChatChannel.PARTICIPANTS,
                    user_id=None,
                    message="Alice has joined the race",
                    created_at=datetime(2026, 9, 25, 13, 1, tzinfo=UTC),
                ),
                ChatMessage(
                    race_id=races["new"].id,
                    channel=ChatChannel.PUBLIC,
                    user_id=alice.id,
                    message="Daily Seed tomorrow?",
                    created_at=datetime(2026, 9, 25, 13, 2, tzinfo=UTC),
                ),
                ChatMessage(
                    race_id=races["new"].id,
                    channel=ChatChannel.PUBLIC,
                    user_id=bob.id,
                    message="gg ALICE, what malice",
                    created_at=datetime(2026, 9, 25, 13, 3, tzinfo=UTC),
                ),
            ]
        )
        await db.commit()
        return {"races": {k: str(r.id) for k, r in races.items()}, "seeds": seeds}


def _rows(bundle: Path, name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (bundle / "data" / name).read_text().splitlines()]


async def _export(maker, tmp_path: Path, **kwargs: Any) -> tuple[Path, Path, dict[str, Any]]:
    bundle, identities = tmp_path / "bundle", tmp_path / "bundle.identities.json"
    manifest = await ae.export(
        maker, bundle, identities, since=SINCE, event_slug="ev", **{"real_names": False} | kwargs
    )
    return bundle, identities, manifest


async def test_bundle_holds_no_secret_and_no_real_name(maker, tmp_path):
    await _populate(maker)
    bundle, identities, _ = await _export(maker, tmp_path)

    exported = "".join(
        p.read_text() for p in bundle.rglob("*") if p.is_file() and p.name != "weapons.json"
    )
    for secret in SECRETS:
        assert secret not in exported
    assert re.search(r"(?<!\w)(alice|bobby)(?!\w)", exported, re.IGNORECASE) is None

    # The oldest account is player_0001; the way back to the names stays outside.
    # System accounts are not people: they keep their name. Twitch ids become
    # their rank, which keeps the accounts' order without naming them.
    users = _rows(bundle, "users.jsonl")
    assert all("twitch_id" not in u for u in users)
    names = {u["twitch_id_rank"]: u["name"] for u in users}
    assert names == {1: "speedfog_daily", 2: "player_0001", 3: "player_0002"}
    mapping = json.loads(identities.read_text())
    assert mapping["player_0001"]["twitch_username"] == "alice"


async def test_real_names_keep_twitch_logins(maker, tmp_path):
    await _populate(maker)
    bundle, identities, manifest = await _export(maker, tmp_path, real_names=True)

    users = _rows(bundle, "users.jsonl")
    assert {u["name"] for u in users} == {"speedfog_daily", "alice", "bobby"}
    assert {u["twitch_id"] for u in users} == {"1", "100", "200"}
    assert manifest["pseudonymized"] is False
    assert not identities.exists()


async def test_targets_are_the_window_plus_the_event(maker, tmp_path):
    ids = await _populate(maker)
    bundle, _, manifest = await _export(maker, tmp_path)

    races = {r["id"]: r["is_target"] for r in _rows(bundle, "races.jsonl")}
    assert races == {
        ids["races"]["old"]: False,
        ids["races"]["qual"]: True,
        ids["races"]["new"]: True,
    }
    participants = {p["race_id"]: p["is_target"] for p in _rows(bundle, "participants.jsonl")}
    assert participants == races
    training = sorted(t["is_target"] for t in _rows(bundle, "training_sessions.jsonl"))
    assert training == [False, True]
    assert manifest["targets"] == {"races": 2, "training_sessions": 1}

    # Only the races under review bring their chat.
    assert {m["race_id"] for m in _rows(bundle, "chat_messages.jsonl")} == {ids["races"]["new"]}


async def test_free_text_names_are_replaced_whole_words_only(maker, tmp_path):
    await _populate(maker)
    bundle, _, _ = await _export(maker, tmp_path)

    # System messages carry display names, users write logins in any case.
    assert [m["message"] for m in _rows(bundle, "chat_messages.jsonl")] == [
        "player_0001 has joined the race",
        "Daily Seed tomorrow?",
        "gg player_0001, what malice",
    ]
    names = {r["name"] for r in _rows(bundle, "races.jsonl")}
    assert "player_0002's Tuesday race" in names
    config = _rows(bundle, "events.jsonl")[0]["config"]
    assert config["withdrawn"] == ["player_0002"]
    assert config["rules"] == ["Ask player_0001"]
    # Structure is not free text: left as it is.
    assert config["modes"] == [{"key": "standard", "label": "Standard"}]


async def test_target_seeds_keep_their_whole_graph(maker, tmp_path):
    await _populate(maker)
    bundle, _, _ = await _export(maker, tmp_path)

    seeds = {s["seed_number"]: s for s in _rows(bundle, "seeds.jsonl")}
    # The solo session's seed comes along too, as history.
    assert set(seeds) == {"old", "qual", "new", "solo"}
    for tag in ("qual", "new"):
        assert seeds[tag]["graph_is_full"] is True
        assert seeds[tag]["graph"]["event_map"] == {"1": f"b_{tag}"}
    for tag in ("old", "solo"):
        graph = seeds[tag]["graph"]
        assert seeds[tag]["graph_is_full"] is False
        assert "event_map" not in graph
        assert graph["nodes"][f"start_{tag}"] == {"type": "start", "layer": 0, "tier": 1}
        # Bosses are randomized per seed: the compact graph keeps the real one.
        assert graph["nodes"][f"b_{tag}"]["boss_name"] == f"Boss {tag}"
        assert graph["edges"] == [{"from": f"start_{tag}", "to": f"b_{tag}"}]


async def test_unknown_event_is_refused(maker, tmp_path):
    await _populate(maker)
    with pytest.raises(SystemExit, match="no event"):
        await ae.export(
            maker,
            tmp_path / "bundle",
            tmp_path / "ids.json",
            since=SINCE,
            event_slug="nope",
            real_names=False,
        )


def test_check_paths_refuses_what_could_leak(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    audits, keys = tmp_path / "audits", tmp_path / "keys"

    with pytest.raises(SystemExit, match="inside the repository"):
        ae.check_paths(repo / "bundle", keys / "ids.json", repo_root=repo)
    with pytest.raises(SystemExit, match="inside the repository"):
        ae.check_paths(audits / "bundle", repo / "ids.json", repo_root=repo)
    # An analyst started in the bundle could read it there, or list it next door.
    for ids in (audits / "bundle" / "ids.json", audits / "bundle.ids.json"):
        with pytest.raises(SystemExit, match="folder around it"):
            ae.check_paths(audits / "bundle", ids, repo_root=repo)

    (audits / "bundle").mkdir(parents=True)
    (audits / "bundle" / "leftover").write_text("x")
    with pytest.raises(SystemExit, match="new or empty"):
        ae.check_paths(audits / "bundle", keys / "ids.json", repo_root=repo)

    out, ids = ae.check_paths(audits / "fresh", keys / "ids.json", repo_root=repo)
    assert out == (audits / "fresh").resolve() and ids == (keys / "ids.json").resolve()
