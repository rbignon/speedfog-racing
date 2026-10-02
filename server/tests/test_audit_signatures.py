"""tools/audit_signatures.py: the known signatures of cheating, on synthetic runs."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
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
        e("b", 50, mid=4),  # re-entry: its boss may be dead already, not comparable
        e("c", 70, mid=5),
    ]
    run = make_run(history, igt_s=100)
    got = [(t.index, t.node, t.exit_to, t.ms, t.gate_key) for t in sig.clean_traversals(run, graph)]
    assert got == [
        (0, "start", "a", 10_000, None),  # no gate into the start
        (1, "a", "b", 20_000, ("a", None, "into a", "out of a")),
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


def test_a_join_time_stamped_by_the_migration_is_unknown(tmp_path):
    row = {"race_id": "r1", "user_id": "u1", "status": "finished", "zone_history": []}
    root = write_bundle(
        tmp_path / "bundle",
        races=[{"id": "r1", "seed_id": "s1"}],
        participants=[
            # Older participants got the instant the created_at column was added.
            {**row, "id": "old", "created_at": "2026-04-26T18:30:24.285100+00:00"},
            {**row, "id": "new", "created_at": "2026-04-26T18:40:00+00:00"},
        ],
    )
    old, new = sig.load_bundle(root).runs
    assert (old.created_at, new.created_at) == (None, datetime(2026, 4, 26, 18, 40, tzinfo=UTC))


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


def test_death_ratios_use_the_players_history_runs():
    runs = [make_run(_s1_history(0), rid=f"old{i}", user="me", target=False) for i in range(3)]
    subject = make_run(_s1_history(3), rid="subject", user="me")
    bundle = make_bundle([subject, *runs, *_field()], {"s1": S1_GRAPH})
    ratios = sig.death_ratios(bundle, sig.build_references(bundle))
    # The player's three history runs had no death at all: their ratio is 0.
    assert ratios["subject"] == 0.0
    assert ratios["o0"] == 1.0  # fewer than 3 history runs: neutral


def test_death_ratios_leave_the_players_other_runs_under_review_out():
    # Those may be cheated too: they must not lower the player's expectation.
    runs = [make_run(_s1_history(0), rid=f"new{i}", user="me") for i in range(3)]
    subject = make_run(_s1_history(3), rid="subject", user="me")
    bundle = make_bundle([subject, *runs, *_field()], {"s1": S1_GRAPH})
    assert sig.death_ratios(bundle, sig.build_references(bundle))["subject"] == 1.0


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


# --- S5 layer_jump ------------------------------------------------------------

JUMP = chain("start", "l1", "l2", "l3", "l4", "l5", "l6", "l7", "l8")


def test_s5_real_jump_versus_lost_messages():
    jump = make_run([e("start", 0, "spawn"), e("l1", 10, mid=1), e("l7", 160, mid=2)])
    (finding,) = sig.s5_layer_jump(jump, JUMP)
    assert (finding.strength, finding.evidence["message_gap"]) == ("medium", 1)
    lost = make_run([e("start", 0, "spawn"), e("l1", 10, mid=1), e("l7", 900, mid=29)])
    (finding,) = sig.s5_layer_jump(lost, JUMP)
    assert finding.strength == "weak"


def test_s5_fog_after_a_warp_forward_is_not_a_jump():
    history = [e("start", 0, "spawn")]
    history += [e(f"l{i}", 10 * i, mid=i) for i in range(1, 7)]
    history += [
        e("l1", 70, "backtrack", mid=7),  # respawn at layer 1
        e("l2", 80, mid=8),
        e("l6", 90, "backtrack", mid=9),  # warp to a grace already found at layer 6
        e("l7", 100, mid=10),  # from layer 6 to 7, not from 2 to 7
    ]
    assert sig.s5_layer_jump(make_run(history), JUMP) == []


def test_s5_backtrack_into_a_node_never_visited():
    far = make_run([e("start", 0, "spawn"), e("l1", 10, mid=1), e("l5", 40, "backtrack", mid=2)])
    (finding,) = sig.s5_layer_jump(far, JUMP)
    assert finding.strength == "strong"  # beyond the deepest layer reached plus one
    near = make_run([e("start", 0, "spawn"), e("l1", 10, mid=1), e("l2", 40, "backtrack", mid=2)])
    (finding,) = sig.s5_layer_jump(near, JUMP)
    assert finding.strength == "medium"
    respawn = make_run([e("start", 0, "spawn"), e("l1", 10, mid=1), e("start", 40, "backtrack")])
    assert sig.s5_layer_jump(respawn, JUMP) == []


# --- S6 fresh_account ---------------------------------------------------------


def _s6_bundle(account_created: datetime, runs_of_user: int = 1) -> tuple[Any, Any]:
    subject = make_run(
        [e("start", 0, "spawn")],
        rid="new",
        user="new",
        igt_s=1618,
        created=T0 + timedelta(minutes=3),
    )
    others = [
        make_run([e("start", 0, "spawn")], rid=f"o{i}", user=f"o{i}", igt_s=1600 + 60 * i)
        for i in range(7)
    ]
    extra = [make_run([], rid=f"x{i}", user="new", race="r2") for i in range(runs_of_user - 1)]
    users = {"new": {"id": "new", "created_at": account_created.isoformat()}}
    races = {"r1": {"id": "r1", "started_at": T0.isoformat()}}
    bundle = make_bundle([subject, *others, *extra], {}, users=users, races=races)
    return subject, bundle


def test_s6_new_account_with_a_strong_result():
    subject, bundle = _s6_bundle(T0 + timedelta(minutes=2))
    counts = {"new": 1}
    (finding,) = sig.s6_fresh_account(subject, bundle, counts)
    assert finding.strength == "weak" and finding.evidence["rank"] == 2


def test_s6_old_account_or_many_runs_is_not_fresh():
    subject, bundle = _s6_bundle(T0 - timedelta(days=30))
    assert sig.s6_fresh_account(subject, bundle, {"new": 1}) == []
    subject, bundle = _s6_bundle(T0 + timedelta(minutes=2), runs_of_user=3)
    assert sig.s6_fresh_account(subject, bundle, {"new": 3}) == []


# --- S7 platform and S8 debug_flags -------------------------------------------


def test_s7_cutoff_never_applied():
    start = T0
    runs = [
        make_run(
            [e("start", 0, "spawn")],
            rid="first",
            user="u1",
            race="sc3",
            finished=start + timedelta(minutes=39, seconds=53),
        ),
        make_run(
            [e("start", 0, "spawn")],
            rid="ok",
            user="u2",
            race="sc3",
            finished=start + timedelta(minutes=48),
        ),
        make_run(
            [e("start", 0, "spawn")],
            rid="late",
            user="u3",
            race="sc3",
            finished=start + timedelta(minutes=59, seconds=44),
        ),
    ]
    races = {
        "sc3": {
            "id": "sc3",
            "name": "Showcase 3",
            "event_id": "ev",
            "event_slot": "showcase:3",
            "race_duration_minutes": None,
            "started_at": start.isoformat(),
            "organizer_id": "org",
            "is_target": True,
        }
    }
    events = {"ev": {"id": "ev", "config": {"playoff_cutoff_minutes": 10}}}
    findings = sig.s7_platform(make_bundle(runs, {}, races=races, events=events))
    (cutoff,) = [f for f in findings if f.evidence.get("kind") == "cutoff_missing"]
    assert cutoff.strength == "medium" and cutoff.players == ["u3"]
    assert cutoff.evidence["deadline"] == (start + timedelta(minutes=50)).isoformat()


def test_s7_organizer_racing_their_event():
    runs = [
        make_run([e("start", 0, "spawn")], rid=f"p{i}", user="org", race=f"q{i}") for i in range(2)
    ]
    races = {
        f"q{i}": {
            "id": f"q{i}",
            "name": f"Q{i}",
            "event_id": "ev",
            "organizer_id": "org",
            "event_slot": f"qualifier:standard:{i}",
            "is_target": True,
        }
        for i in range(2)
    }
    findings = sig.s7_platform(make_bundle(runs, {}, races=races, events={"ev": {"id": "ev"}}))
    (finding,) = [f for f in findings if f.evidence.get("kind") == "organizer_racing"]
    assert finding.strength == "info" and sorted(finding.races) == ["q0", "q1"]


def test_s7_in_game_time_faster_than_the_server_clock():
    fast = make_run(
        [e("start", 0, "spawn")], igt_s=1200, created=T0, finished=T0 + timedelta(minutes=15)
    )
    (finding,) = sig.s7_igt_vs_wall(fast)
    assert finding.strength == "strong"
    fine = make_run(
        [e("start", 0, "spawn")], igt_s=1200, created=T0, finished=T0 + timedelta(minutes=25)
    )
    assert sig.s7_igt_vs_wall(fine) == []


def test_s7_skips_a_join_time_after_the_end():
    # Participants older than their created_at column carry the migration's time.
    backfilled = make_run(
        [e("start", 0, "spawn")],
        igt_s=1200,
        created=T0 + timedelta(days=30),
        finished=T0 + timedelta(minutes=25),
    )
    assert sig.s7_igt_vs_wall(backfilled) == []


def test_s8_debug_flags():
    run = make_run([], flags={"one_shot": {"igt_ms": 83000, "node_id": "stormveil"}})
    (finding,) = sig.s8_debug_flags(run)
    assert finding.strength == "strong" and finding.evidence["flag"] == "one_shot"
    assert sig.s8_debug_flags(make_run([])) == []


def test_s6_rank_leaves_other_disqualified_runs_out():
    subject, bundle = _s6_bundle(T0 + timedelta(minutes=2))
    # 1618 s ranks 2nd behind o0 (1600 s): with o0 disqualified it ranks 1st.
    bundle.runs[1].disqualified = True
    (finding,) = sig.s6_fresh_account(subject, bundle, {"new": 1})
    assert (finding.evidence["rank"], finding.evidence["finishers"]) == (1, 7)


# --- logs and S3 grace_warp ---------------------------------------------------

LOGS = """\
2026-10-02T18:01:58+0000 host uvicorn[1]: 2026-10-02 18:01:58,100 - speedfog_racing.websocket.handler - INFO - zone_query: node_id=c strategy=grace candidates=- grace=21012954 map_id=m11 igt_ms=40000 message_id=7 race=r1 participant=p1
2026-10-02T18:02:30+0000 host uvicorn[1]: 2026-10-02 18:02:30,100 - speedfog_racing.websocket.handler - WARNING - zone_query resolved to unvisited node via grace: node=l5 grace_entity_id=35002953 race=r1 participant=p1 message_id=9
2026-09-28 12:27:20,000 - speedfog_racing.websocket.handler - WARNING - zone_query resolved to unvisited node via grace: node=l5 grace_entity_id=35002953 entity=r2 message_id=1790598300003
2026-09-28 12:29:00,000 - speedfog_racing.websocket.handler - INFO - zone_query: node_id=c strategy=grace candidates=- grace=21012954 map_id=m11 entity=r2
2026-09-28 12:40:00,000 - speedfog_racing.websocket.handler - INFO - zone_query: node_id=c strategy=grace candidates=- grace=21012954 map_id=m11 entity=r2
2026-09-28 12:40:01,000 - speedfog_racing.websocket.handler - INFO - zone_query backtrack: b -> c for r2
2026-09-28 12:41:00,000 - speedfog_racing.websocket.handler - INFO - zone_query: node_id=c strategy=grace candidates=- grace=21012954 map_id=m11 training=t1
2026-09-28 12:42:00,000 - speedfog_racing.websocket.handler - INFO - zone_query: node_id=c strategy=map candidates=- grace=None map_id=m11 igt_ms=1 message_id=2 race=r1 participant=p1
garbage line
2026-09-28 12:43:00,000 - speedfog_racing.other - INFO - zone_query: node_id=c strategy=grace
"""  # noqa: E501 (server log lines, verbatim)


def test_parse_logs_reads_both_formats_and_skips_the_rest(tmp_path):
    path = tmp_path / "server.log"
    path.write_text(LOGS)
    lines = sig.parse_logs([path], utc_offset_hours=2)
    kinds = [(line.kind, line.race_id, line.participant_id) for line in lines]
    assert kinds == [
        ("unvisited", "r2", None),
        ("grace_query", "r2", None),
        ("grace_query", "r2", None),
        ("backtrack", "r2", None),
        ("grace_query", "r1", "p1"),
        ("unvisited", "r1", "p1"),
    ]
    # Journal ISO prefix wins; otherwise the Python timestamp with the given offset.
    assert lines[-1].at == datetime(2026, 10, 2, 18, 2, 30, tzinfo=UTC)
    assert lines[0].at == datetime(2026, 9, 28, 10, 27, 20, tzinfo=UTC)
    assert (lines[-2].igt_ms, lines[-2].message_id) == (40000, 7)


OLD_LAUNCH = int(datetime(2026, 9, 28, 12, 25, tzinfo=UTC).timestamp() * 1000)
assert OLD_LAUNCH == 1_790_598_300_000  # the message ids in LOGS derive from it


def _s3_bundle() -> Any:
    graph = chain("start", "l1", "b", "c", "l4", "l5")
    new = make_run(
        [e("start", 0, "spawn"), e("b", 10, mid=5), e("c", 20, mid=6)],
        rid="p1",
        user="u1",
        race="r1",
    )
    # In c from IGT 270 s, which the player's clock puts at 12:29:10 UTC
    # (launch 12:25:00 + (270 - 30) / 0.96 s); the 12:29:00 log line falls inside.
    old = make_run(
        [
            e("start", 0, "spawn"),
            e("b", 30, mid=OLD_LAUNCH + 1),
            e("c", 270, mid=OLD_LAUNCH + 2),
            e("l5", 280, "backtrack", mid=OLD_LAUNCH + 3),
        ],
        rid="p2",
        user="u2",
        race="r2",
    )
    races = {"r1": {"id": "r1"}, "r2": {"id": "r2"}}
    return make_bundle([new, old], {"s1": graph}, races=races)


def test_s3_findings_and_attribution(tmp_path):
    path = tmp_path / "server.log"
    path.write_text(LOGS)
    findings, unattributed = sig.s3_grace_warp(sig.parse_logs([path]), _s3_bundle())
    got = sorted((f.strength, f.run.id, f.evidence.get("attribution")) for f in findings)
    assert got == [
        ("medium", "p1", "participant"),  # warp in c, 20 s after entering it
        ("medium", "p2", "estimated time"),  # old format, single candidate by time
        ("strong", "p1", "participant"),
        ("strong", "p2", "message id"),
    ]
    assert unattributed == []  # the 12:40 line is followed by a backtrack: a warp elsewhere


def test_s3_late_warp_inside_the_zone_is_not_flagged(tmp_path):
    late = LOGS.replace("igt_ms=40000", "igt_ms=200000")
    path = tmp_path / "server.log"
    path.write_text(late)
    findings, _ = sig.s3_grace_warp(sig.parse_logs([path]), _s3_bundle())
    assert ("medium", "p1") not in {(f.strength, f.run.id) for f in findings}


def test_s3_warp_back_to_another_visited_node_is_not_inside_it():
    # The server logs the zone query, then records the warp as a backtrack
    # with the same in-game time and message id.
    run = make_run(
        [
            e("start", 0, "spawn"),
            e("a", 10, mid=5),
            e("b", 60, mid=6),
            e("a", 100, "backtrack", mid=7),
        ]
    )
    line = sig.LogLine(
        at=T0,
        kind="grace_query",
        race_id="r1",
        participant_id="p1",
        node="a",
        grace="1",
        igt_ms=100_000,
        message_id=7,
    )
    bundle = make_bundle([run], {"s1": chain("start", "a", "b")}, races={"r1": {"id": "r1"}})
    findings, _ = sig.s3_grace_warp([line], bundle)
    assert findings == []


def test_estimate_time_prefers_the_logs():
    bundle = _s3_bundle()
    run = bundle.runs[1]
    at, source = sig.estimate_time(run, 2, {})
    # The first message id (launch + 1 ms) stands for the launch.
    assert source.startswith("estimate")
    assert at == datetime(2026, 9, 28, 12, 29, 10, 1000, tzinfo=UTC)
    at, source = sig.estimate_time(run, 2, {("r2", run.history[2]["message_id"]): T0})
    assert (at, source) == (T0, "server log")


# --- evaluation, report, CLI ---------------------------------------------------


def _e2e_bundle(root: Path) -> Path:
    graph = {
        "nodes": {
            name: {"type": kind, "layer": i, "entrances": [], "exits": []}
            for i, (name, kind) in enumerate(
                [
                    ("start", "start"),
                    ("l1", "boss_arena"),
                    ("l2", "boss_arena"),
                    ("l3", "boss_arena"),
                    ("l4", "boss_arena"),
                    ("l5", "final_boss"),
                ]
            )
        },
        "edges": [
            {"from": a, "to": b}
            for a, b in [("start", "l1"), ("l1", "l2"), ("l2", "l3"), ("l3", "l4"), ("l4", "l5")]
        ],
    }
    history = [
        {"node_id": "start", "igt_ms": 0, "type": "spawn"},
        {"node_id": "l1", "igt_ms": 10000, "type": "fog", "message_id": 1},
        {"node_id": "l5", "igt_ms": 30000, "type": "fog", "message_id": 2},
    ]
    participant = {
        "race_id": "r1",
        "status": "finished",
        "igt_ms": 60000,
        "created_at": "2026-09-26T12:00:00+00:00",
        "finished_at": "2026-09-26T12:30:00+00:00",
    }
    return write_bundle(
        root,
        users=[
            {"id": "u1", "name": "player_0001", "created_at": "2026-01-01T00:00:00+00:00"},
            {"id": "u2", "name": "player_0002", "created_at": "2026-01-01T00:00:00+00:00"},
        ],
        races=[
            {
                "id": "r1",
                "name": "Race",
                "seed_id": "s1",
                "is_target": True,
                "started_at": "2026-09-26T12:00:00+00:00",
            },
            {"id": "r0", "name": "Old", "seed_id": "s1", "is_target": False},
        ],
        participants=[
            {
                **participant,
                "id": "p1",
                "user_id": "u1",
                "zone_history": history,
                "is_target": True,
            },
            {
                **participant,
                "id": "p0",
                "race_id": "r0",
                "user_id": "u2",
                "zone_history": history,
                "is_target": False,
            },
        ],
        seeds=[{"id": "s1", "pool_name": "standard", "graph": graph}],
    )


def test_main_writes_both_reports_for_the_targets(tmp_path):
    bundle = _e2e_bundle(tmp_path / "bundle")
    identities = tmp_path / "ids.json"
    identities.write_text(json.dumps({"player_0001": {"twitch_username": "alice"}}))
    prefix = tmp_path / "out" / "sig"
    assert (
        sig.main(
            ["--bundle", str(bundle), "--identities", str(identities), "--out-prefix", str(prefix)]
        )
        == 0
    )
    report = json.loads((tmp_path / "out" / "sig.json").read_text())
    jumps = [f for f in report["findings"] if f["signature"] == "layer_jump"]
    # Only the target race's run is listed; the history run counts in the base rates.
    assert [f["run"]["id"] for f in jumps] == ["p1"]
    assert jumps[0]["players"][0]["name"] == "alice"
    assert report["base_rates"]["layer_jump"]["medium"] == {"history": 1, "target": 1}
    markdown = (tmp_path / "out" / "sig.md").read_text()
    assert "player_0001 (alice)" in markdown and "## Base rates" in markdown
    assert "S2_STRONG_RATIO=0.75" in markdown  # the thresholds in force head the report


def test_main_player_scope_lists_history_runs(tmp_path):
    bundle = _e2e_bundle(tmp_path / "bundle")
    prefix = tmp_path / "out" / "sig"
    sig.main(["--bundle", str(bundle), "--player", "player_0002", "--out-prefix", str(prefix)])
    report = json.loads((tmp_path / "out" / "sig.json").read_text())
    assert {f["run"]["id"] for f in report["findings"]} == {"p0"}


def test_main_refuses_to_write_into_the_bundle(tmp_path):
    bundle = _e2e_bundle(tmp_path / "bundle")
    with pytest.raises(SystemExit, match="inside the bundle"):
        sig.main(["--bundle", str(bundle), "--out-prefix", str(bundle / "sig")])


def test_resolve_player_by_pseudonym_or_real_name(tmp_path):
    bundle = sig.load_bundle(_e2e_bundle(tmp_path / "bundle"))
    identities = {"player_0002": {"twitch_username": "Bob"}}
    assert sig.resolve_player("player_0002", bundle, {}) == "u2"
    assert sig.resolve_player("bob", bundle, identities) == "u2"
    with pytest.raises(SystemExit, match="no player"):
        sig.resolve_player("carol", bundle, identities)
