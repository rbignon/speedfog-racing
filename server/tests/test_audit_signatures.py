"""tools/audit_signatures.py: the known signatures of cheating, on synthetic runs."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "audit_signatures.py"
_spec = importlib.util.spec_from_file_location("audit_signatures", _SCRIPT)
assert _spec is not None and _spec.loader is not None
sig = importlib.util.module_from_spec(_spec)
sys.modules["audit_signatures"] = sig  # dataclasses look their module up
_spec.loader.exec_module(sig)

T0 = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def chain(
    *names: str,
    kinds: dict[str, str] | None = None,
    bosses: dict[str, str] | None = None,
) -> Any:
    """A linear seed graph: names[0] is the start (layer 0), the last is the final boss."""
    kinds, bosses = kinds or {}, bosses or {}
    nodes: dict[str, Any] = {}
    for i, name in enumerate(names):
        default = "start" if i == 0 else "final_boss" if i == len(names) - 1 else "boss_arena"
        nodes[name] = {
            "type": kinds.get(name, default),
            "layer": i,
            "boss_name": bosses.get(name),
            "entrances": [{"text": f"into {name}", "from": names[i - 1]}] if i else [],
            "exits": (
                [{"fog_id": "f", "text": f"out of {name}", "to": names[i + 1]}]
                if i + 1 < len(names)
                else []
            ),
        }
    edges = [{"from": a, "to": b} for a, b in zip(names, names[1:])]
    return sig.Graph.from_json({"nodes": nodes, "edges": edges})


def e(
    node: str, seconds: float, kind: str = "fog", mid: int | None = None, deaths: int = 0
) -> dict[str, Any]:
    entry: dict[str, Any] = {"node_id": node, "igt_ms": int(seconds * 1000), "type": kind}
    if mid is not None:
        entry["message_id"] = mid
    if deaths:
        entry["deaths"] = deaths
    return entry


def make_run(
    history: list[dict[str, Any]],
    *,
    rid: str = "p1",
    user: str = "u1",
    race: str | None = "r1",
    seed: str = "s1",
    kind: str = "race",
    status: str = "finished",
    igt_s: float | None = None,
    created: datetime | None = None,
    finished: datetime | None = None,
    last_change: datetime | None = None,
    target: bool = True,
    flags: dict[str, Any] | None = None,
) -> Any:
    igt = igt_s if igt_s is not None else (history[-1]["igt_ms"] / 1000 if history else 0)
    return sig.Run(
        kind=kind,
        id=rid,
        user_id=user,
        race_id=race if kind == "race" else None,
        seed_id=seed,
        status=status,
        created_at=created,
        finished_at=finished,
        last_igt_change_at=last_change,
        igt_ms=int(igt * 1000),
        death_count=sum(x.get("deaths", 0) for x in history),
        history=history,
        is_target=target,
        debug_flags=flags,
    )


def make_bundle(
    runs: list[Any],
    graphs: dict[str, Any],
    *,
    races: dict[str, Any] | None = None,
    users: dict[str, Any] | None = None,
    events: dict[str, Any] | None = None,
    seeds: dict[str, Any] | None = None,
) -> Any:
    return sig.Bundle(
        path=Path("."),
        manifest={},
        users=users or {},
        races=races or {},
        seeds=seeds or {},
        events=events or {},
        runs=runs,
        graphs=graphs,
    )


def write_bundle(root: Path, **files: list[dict[str, Any]]) -> Path:
    """A bundle directory: manifest plus one JSON Lines file per keyword (``users=[...]``)."""
    data = root / "data"
    data.mkdir(parents=True)
    manifest = {"latest_activity": {"participant_joined": "2026-09-30T17:00:00+00:00"}}
    (root / "manifest.json").write_text(json.dumps(manifest))
    for name in ("users", "races", "participants", "training_sessions", "seeds", "events"):
        rows = files.get(name, [])
        (data / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return root


# --- common definitions ------------------------------------------------------


def test_split_processes_groups_by_message_id():
    history = [
        e("a", 0, "spawn"),
        e("b", 10, mid=1000),
        e("c", 20, mid=1003),
        e("b", 15, "backtrack", mid=900_000),
        e("c", 30, mid=900_002),
        e("d", 40, mid=500),  # a decrease starts a process too
    ]
    processes = sig.split_processes(history)
    assert [(p.launch_ms, p.entries) for p in processes] == [
        (1000, [0, 1, 2]),
        (900_000, [3, 4]),
        (500, [5]),
    ]


def test_split_processes_without_message_ids_is_empty():
    assert sig.split_processes([e("a", 0, "spawn"), e("b", 10)]) == []


def test_clean_traversals_rules():
    graph = chain("start", "a", "b", "c")
    history = [
        e("start", 0, "spawn"),
        e("a", 10, mid=1),
        e("b", 30, mid=2, deaths=1),  # died there: not clean
        e("a", 40, "backtrack", mid=3),  # respawned in a
        e("b", 50, mid=4),  # re-entry, counted from where the runner respawned
        e("c", 70, mid=5),
    ]
    run = make_run(history, igt_s=100)
    got = [(t.index, t.node, t.exit_to, t.ms, t.gate_key) for t in sig.clean_traversals(run, graph)]
    assert got == [
        (0, "start", "a", 10_000, None),  # no gate into the start
        (1, "a", "b", 20_000, ("a", None, "into a", "out of a")),
        (4, "b", "c", 20_000, ("b", None, "into b", "out of b")),
        (5, "c", "finish", 30_000, ("c", None, "into c", "finish")),
    ]


def test_clean_traversals_skip_non_successors_and_unfinished_finals():
    graph = chain("start", "a", "b")
    run = make_run([e("start", 0, "spawn"), e("b", 5), e("a", 9)], status="abandoned")
    # start -> b is not an edge, b -> a goes backwards, and an abandoned run has no finish.
    assert sig.clean_traversals(run, graph) == []


def test_entries_without_type_count_as_fog():
    graph = chain("start", "a", "b")
    run = make_run([{"node_id": "a", "igt_ms": 0}, {"node_id": "b", "igt_ms": 5000}], igt_s=9)
    assert [t.node for t in sig.clean_traversals(run, graph)] == ["a", "b"]


def test_check_out_prefix_refuses_bundle_and_repository(tmp_path):
    bundle, repo = tmp_path / "bundle", tmp_path / "repo"
    for path in (bundle, repo):
        path.mkdir()
    with pytest.raises(SystemExit, match="inside the bundle"):
        sig.check_out_prefix(bundle / "sig", bundle, repo_root=repo)
    with pytest.raises(SystemExit, match="inside the repository"):
        sig.check_out_prefix(repo / "sig", bundle, repo_root=repo)
    assert (
        sig.check_out_prefix(tmp_path / "out" / "sig", bundle, repo_root=repo)
        == (tmp_path / "out" / "sig").resolve()
    )


def test_load_bundle_reads_runs_and_reduces_graphs(tmp_path):
    graph = {
        "nodes": {"a": {"type": "start", "layer": 0, "zones": ["z"], "exits": []}},
        "edges": [],
        "event_map": {},
    }
    root = write_bundle(
        tmp_path / "bundle",
        users=[{"id": "u1", "name": "player_0001"}],
        races=[{"id": "r1", "seed_id": "s1", "is_target": True}],
        participants=[
            {
                "id": "p1",
                "race_id": "r1",
                "user_id": "u1",
                "status": "finished",
                "created_at": "2026-09-26T12:00:00+00:00",
                "igt_ms": 5000,
                "zone_history": [{"node_id": "a", "igt_ms": 0, "type": "spawn"}],
                "is_target": True,
            }
        ],
        training_sessions=[
            {"id": "t1", "user_id": "u1", "seed_id": "s1", "status": "active", "is_target": False}
        ],
        seeds=[{"id": "s1", "pool_name": "standard", "graph": graph}],
    )
    bundle = sig.load_bundle(root)
    race_run, solo = bundle.runs
    assert (race_run.kind, race_run.seed_id, race_run.created_at) == ("race", "s1", T0)
    assert (solo.kind, solo.race_id, solo.seed_id) == ("training", None, "s1")
    assert bundle.race_runs("r1") == [race_run]
    assert bundle.pool(race_run) == "standard"
    # Only what the signatures read is kept in memory.
    assert bundle.graphs["s1"].nodes == {"a": {"type": "start", "layer": 0, "exits": []}}


def test_a_disqualified_run_is_audited_on_what_it_did(tmp_path):
    root = write_bundle(
        tmp_path / "bundle",
        races=[{"id": "r1", "seed_id": "s1", "is_target": True}],
        participants=[
            {
                "id": "p1",
                "race_id": "r1",
                "user_id": "u1",
                "status": "disqualified",
                "status_before_disqualification": "finished",
                "zone_history": [],
            }
        ],
    )
    (run,) = sig.load_bundle(root).runs
    assert (run.status, run.disqualified) == ("finished", True)
    # The reviewer sees the case is already handled.
    finding = sig.Finding(signature="x", strength="info", title="t", run=run)
    assert finding.evidence["disqualified"] is True
