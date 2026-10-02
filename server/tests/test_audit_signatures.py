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


# --- S2 impossible_traversal ------------------------------------------------

TUNNEL = chain("start", "a", "tunnel", "c")


def _tunnel_run(rid: str, tunnel_s: float, came: str = "a") -> Any:
    history = [e("start", 0, "spawn"), e(came, 10), e("tunnel", 20), e("c", 20 + tunnel_s)]
    return make_run(history, rid=rid, user=rid, status="abandoned")


def _s2(subject: Any, others: list[Any], graph: Any = TUNNEL) -> list[Any]:
    bundle = make_bundle([subject, *others], {"s1": graph})
    refs = sig.build_references(bundle)
    return [
        f
        for f in sig.s2_impossible_traversal(subject, graph, refs)
        if f.evidence["node"] == "tunnel"
    ]


def test_s2_flags_a_traversal_far_under_the_gate_floor():
    others = [_tunnel_run(f"o{i}", 70 + i) for i in range(25)]
    (finding,) = _s2(_tunnel_run("cheat", 44), others)
    assert finding.strength == "medium"  # under 0.75 x floor, but fewer than 50 references
    assert finding.evidence["floor_s"] == 70.0 and finding.evidence["ratio"] == 0.63
    assert finding.evidence["references"] == 25 and finding.evidence["faster_runs"] == 0


def test_s2_strong_with_enough_references():
    others = [_tunnel_run(f"o{i}", 70 + i % 10) for i in range(60)]
    (finding,) = _s2(_tunnel_run("cheat", 44), others)
    assert finding.strength == "strong"


def test_s2_needs_twenty_references_and_ignores_other_gates():
    few = [_tunnel_run(f"o{i}", 70) for i in range(19)]
    assert _s2(_tunnel_run("cheat", 44), few) == []
    # Fast runs through another entrance are not compared (different gate key).
    graph = chain("start", "a", "tunnel", "c")
    graph.nodes["tunnel"]["entrances"].append({"text": "side door", "from": "start"})
    graph.succ["start"].add("tunnel")
    side = [
        make_run(
            [e("start", 0, "spawn"), e("tunnel", 10), e("c", 10 + 30)],
            rid=f"s{i}",
            user=f"s{i}",
            status="abandoned",
        )
        for i in range(30)
    ]
    normal = [_tunnel_run(f"o{i}", 70) for i in range(25)]
    (finding,) = _s2(_tunnel_run("cheat", 44), side + normal, graph)
    assert finding.evidence["floor_s"] == 70.0


def test_s2_never_compares_a_run_with_itself():
    # The subject's own time is in the tables; the floor must come from the others.
    others = [_tunnel_run(f"o{i}", 50) for i in range(25)]
    assert _s2(_tunnel_run("same", 50), others) == []


def test_s2_boss_falls_back_to_a_loose_reference():
    graph = chain("start", "a", "boss", "c", bosses={"boss": "Radahn"})
    runs = [
        make_run(
            [e("start", 0, "spawn"), e("a", 5), e("boss", 10), e("c", 10 + 90)],
            rid=f"o{i}",
            user=f"o{i}",
            status="abandoned",
        )
        for i in range(30)
    ]
    # Each reference came in through a different gate: no gate key has 20 samples.
    for i, run in enumerate(runs):
        graph.nodes["boss"]["entrances"].append({"text": f"door {i}", "from": f"x{i}"})
        run.history[1]["node_id"] = f"x{i}"
        graph.succ.setdefault(f"x{i}", set()).add("boss")
        graph.nodes[f"x{i}"] = {"type": "boss_arena", "layer": 1}
    subject = make_run(
        [e("start", 0, "spawn"), e("a", 5), e("boss", 10), e("c", 40)], rid="fast", user="fast"
    )
    bundle = make_bundle([subject, *runs], {"s1": graph})
    refs = sig.build_references(bundle)
    (finding,) = [
        f for f in sig.s2_impossible_traversal(subject, graph, refs) if f.evidence["node"] == "boss"
    ]
    assert finding.evidence["reference"].startswith("same boss, any gates")


def test_s2_without_a_graph_finds_nothing():
    run = _tunnel_run("cheat", 44)
    bundle = make_bundle([run], {})
    assert sig.s2_impossible_traversal(run, bundle.graph(run), sig.build_references(bundle)) == []


# --- S1 deaths_stop ----------------------------------------------------------

S1_NAMES = ["start", "first", *[f"n{i}" for i in range(1, 15)], "final"]
S1_GRAPH = chain(*S1_NAMES, kinds={f"n{i}": "major_boss" for i in (2, 4, 6, 8, 10)})


def _s1_history(struggle_deaths: int, tail_deaths: int = 0) -> list[dict[str, Any]]:
    history = [e("start", 0, "spawn"), e("first", 10, deaths=struggle_deaths)]
    for i, node in enumerate(S1_NAMES[2:], start=1):
        history.append(e(node, 10 + 30 * i, deaths=tail_deaths if node == "n3" else 0))
    return history


def _field(n: int = 20) -> list[Any]:
    """Other runs dying once in every node: about 15 expected deaths over the tail."""
    runs = []
    for i in range(n):
        history = [e("start", 0, "spawn")]
        history += [e(node, 10 * k, deaths=1) for k, node in enumerate(S1_NAMES[1:], start=1)]
        runs.append(make_run(history, rid=f"o{i}", user=f"o{i}"))
    return runs


def _s1(subject: Any, others: list[Any], ratio: float = 1.0) -> list[Any]:
    bundle = make_bundle([subject, *others], {"s1": S1_GRAPH})
    refs = sig.build_references(bundle)
    return sig.s1_deaths_stop(subject, S1_GRAPH, refs, None, ratio)


def test_s1_flags_a_death_loop_followed_by_no_death_at_all():
    (finding,) = _s1(make_run(_s1_history(3), rid="cheat"), _field())
    assert finding.strength == "strong"
    assert finding.evidence["struggle_node"] == "first"
    assert finding.evidence["struggle_deaths"] == 3
    assert finding.evidence["tail_major_bosses"] == 6  # five majors and the final boss
    assert finding.evidence["p_zero"] < 0.001


def test_s1_ignores_runs_without_a_struggle_or_with_tail_deaths():
    assert _s1(make_run(_s1_history(0), rid="clean"), _field()) == []
    assert _s1(make_run(_s1_history(3, tail_deaths=1), rid="human"), _field()) == []


def test_s1_needs_a_long_enough_tail():
    history = _s1_history(0)
    history[-2]["deaths"] = 3  # the struggle is the last node before the final boss
    assert _s1(make_run(history, rid="late"), _field()) == []


def test_s1_player_ratio_lowers_the_expectation():
    assert _s1(make_run(_s1_history(3), rid="careful"), _field(), ratio=0.05) == []


def test_death_ratios_use_the_players_other_runs():
    runs = [make_run(_s1_history(0), rid=f"mine{i}", user="me") for i in range(3)]
    subject = make_run(_s1_history(3), rid="subject", user="me")
    bundle = make_bundle([subject, *runs, *_field()], {"s1": S1_GRAPH})
    ratios = sig.death_ratios(bundle, sig.build_references(bundle))
    # The player's three other runs had no death at all: their ratio is 0.
    assert ratios["subject"] == 0.0
    assert ratios["o0"] == 1.0  # fewer than 3 other runs: neutral


# --- S4 save_restore ---------------------------------------------------------

LAUNCH = 1_790_289_383_715


def _restored(drop_back_to_s: float, igt_s: float = 2297) -> Any:
    """Reached 237 s, the game restarts 638 s later, and resumes at ``drop_back_to_s``."""
    history = [
        e("start", 0, "spawn"),
        e("a", 32, mid=LAUNCH + 1),
        e("b", 141, mid=LAUNCH + 2),
        e("c", 237, mid=LAUNCH + 3),
        e("b", drop_back_to_s, "backtrack", mid=LAUNCH + 638_000),
        e("c", 300, mid=LAUNCH + 638_001),
    ]
    return make_run(history, rid="restorer", user="restorer", igt_s=igt_s)


def _race(subject: Any, other_igts: list[float], slot: str = "") -> Any:
    others = [
        make_run([e("start", 0, "spawn")], rid=f"o{i}", user=f"o{i}", igt_s=s)
        for i, s in enumerate(other_igts)
    ]
    races = {"r1": {"id": "r1", "event_slot": slot or None, "is_target": True}}
    return make_bundle([subject, *others], {}, races=races)


def test_s4_measures_the_erased_time_and_its_effect():
    run = _restored(141.6)
    (finding,) = sig.s4_save_restore(run, _race(run, [2400]))
    assert finding.strength == "info"  # the lower bound alone keeps rank 1
    assert finding.evidence["erased_min_s"] == 95.4
    assert finding.evidence["erased_max_s"] == 502.9  # 32 + 0.96 x 638 - 141.6
    assert finding.evidence["effect"]["rank"] == 1
    assert finding.evidence["effect"]["rank_with_upper"] == 2


def test_s4_is_medium_when_the_lower_bound_changes_the_rank():
    run = _restored(141.6)
    (finding,) = sig.s4_save_restore(run, _race(run, [2350]))
    assert finding.strength == "medium"


def test_s4_qualifier_points():
    run = _restored(141.6)
    (finding,) = sig.s4_save_restore(run, _race(run, [2350, 3000], slot="qualifier:boss_rush:2"))
    effect = finding.evidence["effect"]
    # Three qualified runs: rank 1 scores 100, rank 2 scores 67.
    assert (effect["points"], effect["points_with_lower"]) == (100, 67)


def test_s4_small_drop_is_a_dodged_quit_out_penalty():
    run = _restored(207)  # 30 s under the 237 s reached
    (finding,) = sig.s4_save_restore(run, _race(run, [2400]))
    assert finding.strength == "weak"


def test_s4_ignores_restarts_that_keep_the_time_and_runs_without_ids():
    history = [
        e("start", 0, "spawn"),
        e("a", 30, mid=LAUNCH + 1),
        e("b", 60, mid=LAUNCH + 900_000),
    ]
    run = make_run(history)
    assert sig.s4_save_restore(run, _race(run, [])) == []
    old = make_run([e("start", 0, "spawn"), e("a", 30), e("b", 10, "backtrack")])
    assert sig.s4_save_restore(old, _race(old, [])) == []


def test_s4_rank_leaves_other_disqualified_runs_out():
    run = _restored(141.6)
    bundle = _race(run, [2350])
    bundle.runs[1].disqualified = True  # off the official field
    (finding,) = sig.s4_save_restore(run, bundle)
    effect = finding.evidence["effect"]
    assert (effect["rank_with_lower"], effect["finishers"]) == (1, 1)
