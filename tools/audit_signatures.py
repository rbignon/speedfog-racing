#!/usr/bin/env python3
"""Check an audit bundle's runs against the known signatures of cheating and irregularities.

Second pass of the run audit (docs/RUN_AUDIT.md): the isolated analyst looks
for what nobody knows yet, this tool makes sure what is known is never
missed. It reads a bundle written by tools/audit_extract.py, and optionally
the server's logs, never the database, and writes a Markdown report and a
JSON file, strongest findings first. Findings are review aids with figures,
not verdicts.

Signatures (thresholds are the constants below):

    S1 deaths_stop           a death loop (2+ deaths in a node), then no death
                             at all over a long tail, against the deaths
                             expected there
    S2 impossible_traversal  a clean traversal faster than every other run
                             through the same gates against the same boss
    S3 grace_warp            (logs) a warp through the grace menu to an
                             unvisited node, or into the node just entered
    S4 save_restore          a game restart that brings the in-game time back
    S5 layer_jump            a fog entry skipping layers, or a position change
                             into a node the run never visited
    S6 fresh_account         a new account with a strong result (context)
    S7 platform              playoff cutoff never applied, organizer racing
                             their own event, in-game time faster than the
                             server clock
    S8 debug_flags           cheat-tool flags reported by the mod

Usage:
    python3 tools/audit_signatures.py --bundle ~/src/speedfog-audit/2026-09-30 \\
        [--logs qualifier.log] [--identities ~/.speedfog-audit/2026-09-30.identities.json] \\
        [--scope targets|all | --player NAME] [--out-prefix PATH]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from bisect import bisect_left
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = Path.home() / ".speedfog-audit"

IGT_SCALE = 0.96  # the game's timer runs at 0.96 x real time
PROCESS_GAP = 50_000  # message ids of one game process sit closer than this
BOSS_TYPES = frozenset({"major_boss", "boss_arena", "final_boss"})
MAJOR_TYPES = frozenset({"major_boss", "final_boss"})
STRENGTHS = ("strong", "medium", "weak", "info")
# The only node fields the signatures read: graphs are reduced to them on load.
GRAPH_NODE_KEYS = ("type", "layer", "boss_name", "entrances", "exits")
# participants.created_at (the join time) was added on 2026-04-26, stamping
# every older participant with that instant (production): their join is unknown.
JOINS_UNKNOWN_UNTIL = datetime(2026, 4, 26, 18, 30, 24, 285100, tzinfo=UTC)

# S1 deaths_stop
S1_MIN_STRUGGLE_DEATHS = 2
S1_MIN_TAIL_LAYERS = 10
S1_MIN_TAIL_MAJORS = 3
S1_MIN_RATE_VISITS = 10
S1_MIN_HISTORY_RUNS = 3
S1_STRONG_P = 0.001
S1_MEDIUM_P = 0.01
# S2 impossible_traversal
S2_MIN_REFS = 20
S2_STRONG_MIN_REFS = 50
S2_MEDIUM_RATIO = 0.85
S2_STRONG_RATIO = 0.75
S2_LOOSE_MIN_REFS = 30
# S3 grace_warp
S3_RECENT_ENTRY_MS = 120_000
S3_BACKTRACK_WINDOW_S = 2
S3_CANDIDATE_SLACK = timedelta(minutes=5)
# S4 save_restore
S4_DODGE_MS = 60_000
# S5 layer_jump
S5_REAL_JUMP_MAX_GAP = 3
# S6 fresh_account
S6_MAX_ACCOUNT_AGE = timedelta(hours=2)
S6_MAX_RUNS = 2
# S7 platform
S7_DEFAULT_CUTOFF = 10
S7_WALL_SLACK_S = 60


def parse_time(value: Any) -> datetime | None:
    """An ISO instant from the bundle; a naive one is read as UTC."""
    if not value:
        return None
    moment = datetime.fromisoformat(str(value))
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def entry_type(entry: Mapping[str, Any]) -> str:
    """An entry's type; the oldest histories predate the field and hold fog entries only."""
    return str(entry.get("type") or "fog")


@dataclass
class Graph:
    nodes: dict[str, dict[str, Any]]
    succ: dict[str, set[str]]

    @classmethod
    def from_json(cls, graph: Mapping[str, Any] | None) -> Graph:
        graph = graph or {}
        succ: dict[str, set[str]] = defaultdict(set)
        for edge in graph.get("edges") or []:
            succ[str(edge["from"])].add(str(edge["to"]))
        nodes = {
            str(node_id): {k: node[k] for k in GRAPH_NODE_KEYS if k in node}
            for node_id, node in (graph.get("nodes") or {}).items()
        }
        return cls(nodes=nodes, succ=dict(succ))

    def layer(self, node: str) -> int | None:
        value = self.nodes.get(node, {}).get("layer")
        return value if isinstance(value, int) else None

    def kind(self, node: str) -> str | None:
        value = self.nodes.get(node, {}).get("type")
        return str(value) if value is not None else None

    def boss(self, node: str) -> str | None:
        value = self.nodes.get(node, {}).get("boss_name")
        return str(value) if value is not None else None

    def successors(self, node: str) -> set[str]:
        return self.succ.get(node, set())

    def entrance_text(self, node: str, came_from: str) -> str | None:
        for gate in self.nodes.get(node, {}).get("entrances") or []:
            if gate.get("from") == came_from:
                return str(gate.get("text"))
        return None

    def exit_text(self, node: str, to: str) -> str | None:
        for gate in self.nodes.get(node, {}).get("exits") or []:
            if gate.get("to") == to:
                return str(gate.get("text"))
        return None


EMPTY_GRAPH = Graph(nodes={}, succ={})


@dataclass
class Run:
    """A participation in a race, or a solo session."""

    kind: str  # "race" or "training"
    id: str
    user_id: str
    race_id: str | None
    seed_id: str | None
    status: str
    created_at: datetime | None
    finished_at: datetime | None
    last_igt_change_at: datetime | None
    igt_ms: int
    death_count: int
    history: list[dict[str, Any]]
    is_target: bool
    debug_flags: dict[str, Any] | None = None
    # Disqualified by the race staff; status then holds the run's own outcome.
    disqualified: bool = False

    @property
    def end(self) -> datetime | None:
        return self.finished_at or self.last_igt_change_at


@dataclass
class Bundle:
    path: Path
    manifest: dict[str, Any]
    users: dict[str, dict[str, Any]]
    races: dict[str, dict[str, Any]]
    seeds: dict[str, dict[str, Any]]
    events: dict[str, dict[str, Any]]
    runs: list[Run]
    graphs: dict[str, Graph]
    by_race: dict[str, list[Run]] = field(init=False)

    def __post_init__(self) -> None:
        self.by_race = defaultdict(list)
        for run in self.runs:
            if run.race_id is not None:
                self.by_race[run.race_id].append(run)

    def graph(self, run: Run) -> Graph:
        return self.graphs.get(run.seed_id or "", EMPTY_GRAPH)

    def pool(self, run: Run) -> str | None:
        seed = self.seeds.get(run.seed_id or "")
        return str(seed["pool_name"]) if seed and seed.get("pool_name") else None

    def race_runs(self, race_id: str) -> list[Run]:
        return self.by_race.get(race_id, [])


def load_bundle(path: Path) -> Bundle:
    data = path / "data"
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    users = {str(u["id"]): u for u in read_jsonl(data / "users.jsonl")}
    races = {str(r["id"]): r for r in read_jsonl(data / "races.jsonl")}
    seeds: dict[str, dict[str, Any]] = {}
    graphs: dict[str, Graph] = {}
    for seed in read_jsonl(data / "seeds.jsonl"):
        graphs[str(seed["id"])] = Graph.from_json(seed.pop("graph", None))
        seeds[str(seed["id"])] = seed
    events = {str(e["id"]): e for e in read_jsonl(data / "events.jsonl")}
    runs: list[Run] = []
    for row in read_jsonl(data / "participants.jsonl"):
        race = races.get(str(row["race_id"]), {})
        joined = parse_time(row.get("created_at"))
        # A disqualified run is audited on what it did, not on the sanction.
        disqualified = row["status"] == "disqualified"
        status = row.get("status_before_disqualification") if disqualified else None
        runs.append(
            Run(
                kind="race",
                id=str(row["id"]),
                user_id=str(row["user_id"]),
                race_id=str(row["race_id"]),
                seed_id=race.get("seed_id"),
                status=str(status or row["status"]),
                created_at=joined if joined and joined > JOINS_UNKNOWN_UNTIL else None,
                finished_at=parse_time(row.get("finished_at")),
                last_igt_change_at=parse_time(row.get("last_igt_change_at")),
                igt_ms=int(row.get("igt_ms") or 0),
                death_count=int(row.get("death_count") or 0),
                history=list(row.get("zone_history") or []),
                is_target=bool(row.get("is_target")),
                debug_flags=row.get("debug_flags") or None,
                disqualified=disqualified,
            )
        )
    for row in read_jsonl(data / "training_sessions.jsonl"):
        runs.append(
            Run(
                kind="training",
                id=str(row["id"]),
                user_id=str(row["user_id"]),
                race_id=None,
                seed_id=row.get("seed_id"),
                status=str(row["status"]),
                created_at=parse_time(row.get("created_at")),
                finished_at=parse_time(row.get("finished_at")),
                last_igt_change_at=None,
                igt_ms=int(row.get("igt_ms") or 0),
                death_count=int(row.get("death_count") or 0),
                history=list(row.get("zone_history") or []),
                is_target=bool(row.get("is_target")),
            )
        )
    return Bundle(
        path=path,
        manifest=manifest,
        users=users,
        races=races,
        seeds=seeds,
        events=events,
        runs=runs,
        graphs=graphs,
    )


@dataclass
class Process:
    """One game process: its launch on the player's clock (epoch ms) and its entries."""

    launch_ms: int
    entries: list[int]


def split_processes(history: list[dict[str, Any]]) -> list[Process]:
    """Group a history's entries by game process, from their message ids.

    The mod seeds its message counter with the PC's clock at launch, then adds
    one per message: a large jump or a decrease means a new process. Entries
    without an id (spawn) join the next process.
    """
    processes: list[Process] = []
    pending: list[int] = []
    last: int | None = None
    for index, entry in enumerate(history):
        raw = entry.get("message_id")
        if raw is None:
            pending.append(index)
            continue
        mid = int(raw)
        if processes and last is not None and 0 <= mid - last < PROCESS_GAP:
            processes[-1].entries.extend([*pending, index])
        else:
            processes.append(Process(launch_ms=mid, entries=[*pending, index]))
        pending = []
        last = mid
    if pending and processes:
        processes[-1].entries.extend(pending)
    return processes


@dataclass(frozen=True)
class Traversal:
    index: int  # the entry into the node
    node: str
    boss: str | None
    came_from: str | None
    exit_to: str  # a node id, or "finish"
    ms: int
    gate_key: tuple[str, str | None, str, str] | None
    boss_key: tuple[str, str | None]


def clean_traversals(run: Run, graph: Graph) -> list[Traversal]:
    """First entries into a node, with no death there, directly followed by a fog into a successor.

    A re-entry is left out: its boss may be dead already and its route known,
    so it is not comparable with a first visit. The final node of a finished
    run counts until the finish. The gate key names the entrance used (from
    the node of the entry just before) and the exit taken.
    """
    history = run.history
    out: list[Traversal] = []
    seen: set[str] = set()
    for index, entry in enumerate(history):
        node = str(entry["node_id"])
        visited = node in seen
        seen.add(node)
        if visited or entry_type(entry) not in ("fog", "spawn") or entry.get("deaths"):
            continue
        if index + 1 < len(history):
            following = history[index + 1]
            if entry_type(following) != "fog" or following[
                "node_id"
            ] not in graph.successors(node):
                continue
            exit_to = str(following["node_id"])
            ms = int(following["igt_ms"]) - int(entry["igt_ms"])
            exit_text = graph.exit_text(node, exit_to)
        else:
            if (
                run.status != "finished"
                or node not in graph.nodes
                or graph.successors(node)
            ):
                continue
            exit_to, exit_text = "finish", "finish"
            ms = run.igt_ms - int(entry["igt_ms"])
        if ms <= 0:
            continue
        came_from = str(history[index - 1]["node_id"]) if index > 0 else None
        entrance = graph.entrance_text(node, came_from) if came_from else None
        boss = graph.boss(node)
        gate = (node, boss, entrance, exit_text) if entrance and exit_text else None
        out.append(
            Traversal(index, node, boss, came_from, exit_to, ms, gate, (node, boss))
        )
    return out


@dataclass
class Finding:
    signature: str
    strength: str
    title: str
    run: Run | None = None
    races: list[str] = field(default_factory=list)
    players: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    entry_index: int | None = None

    def __post_init__(self) -> None:
        if self.run is not None:
            if self.run.race_id and self.run.race_id not in self.races:
                self.races.insert(0, self.run.race_id)
            if self.run.user_id not in self.players:
                self.players.insert(0, self.run.user_id)
            if self.run.disqualified:
                self.evidence["disqualified"] = True


def check_out_prefix(prefix: Path, bundle: Path, repo_root: Path = REPO_ROOT) -> Path:
    """Resolve the output prefix, refusing the bundle and the repository.

    An analyst rerun in the bundle would read a report written there.
    """
    prefix = prefix.expanduser().resolve()
    for root, what in (
        (bundle.resolve(), "the bundle"),
        (repo_root.resolve(), "the repository"),
    ):
        if prefix == root or root in prefix.parents:
            raise SystemExit(f"refusing {prefix}: it is inside {what}")
    return prefix


@dataclass
class SampleSet:
    """One measure over many runs, for leave-one-out lookups (a run never meets itself)."""

    values: list[int] = field(default_factory=list)
    by_owner: dict[str, list[int]] = field(default_factory=dict)
    total: int = 0

    def add(self, value: int, owner: str) -> None:
        self.values.append(value)
        self.by_owner.setdefault(owner, []).append(value)
        self.total += value

    def freeze(self) -> None:
        self.values.sort()

    def count(self, owner: str) -> int:
        return len(self.values) - len(self.by_owner.get(owner, ()))

    def smallest(self, owner: str, k: int = 2) -> list[int]:
        skip = Counter(self.by_owner.get(owner, ()))
        out: list[int] = []
        for value in self.values:
            if skip[value]:
                skip[value] -= 1
                continue
            out.append(value)
            if len(out) == k:
                break
        return out

    def below(self, value: int, owner: str) -> int:
        """How many values of other runs are strictly below ``value``."""
        own = sum(1 for v in self.by_owner.get(owner, ()) if v < value)
        return bisect_left(self.values, value) - own

    def mean(self, owner: str) -> float | None:
        n = self.count(owner)
        if n <= 0:
            return None
        return (self.total - sum(self.by_owner.get(owner, ()))) / n


def _tables() -> dict[tuple[Any, ...], SampleSet]:
    return defaultdict(SampleSet)


@dataclass
class References:
    gate: dict[tuple[Any, ...], SampleSet] = field(default_factory=_tables)
    boss: dict[tuple[Any, ...], SampleSet] = field(default_factory=_tables)
    node_deaths: dict[tuple[Any, ...], SampleSet] = field(default_factory=_tables)
    type_deaths: dict[tuple[Any, ...], SampleSet] = field(default_factory=_tables)

    def freeze(self) -> None:
        for table in (self.gate, self.boss, self.node_deaths, self.type_deaths):
            for samples in table.values():
                samples.freeze()


def node_deaths(run: Run) -> dict[str, int]:
    """Deaths per node the run visited (0 for a node it survived)."""
    out: dict[str, int] = {}
    for entry in run.history:
        node = str(entry["node_id"])
        out[node] = out.get(node, 0) + int(entry.get("deaths") or 0)
    return out


def build_references(bundle: Bundle) -> References:
    """Every run's clean traversal times and per-node deaths, by gate key and by boss."""
    refs = References()
    for run in bundle.runs:
        graph = bundle.graph(run)
        pool = bundle.pool(run)
        for traversal in clean_traversals(run, graph):
            if traversal.gate_key is not None:
                refs.gate[traversal.gate_key].add(traversal.ms, run.id)
            if graph.kind(traversal.node) in BOSS_TYPES:
                refs.boss[traversal.boss_key].add(traversal.ms, run.id)
        for node, deaths in node_deaths(run).items():
            if node not in graph.nodes:
                continue
            refs.node_deaths[(node, graph.boss(node))].add(deaths, run.id)
            refs.type_deaths[(pool, graph.kind(node))].add(deaths, run.id)
    refs.freeze()
    return refs


def s2_impossible_traversal(run: Run, graph: Graph, refs: References) -> list[Finding]:
    """Clean traversals far under the fastest of the other runs through the same gates."""
    findings: list[Finding] = []
    for traversal in clean_traversals(run, graph):
        reference = "same gates and boss"
        samples = refs.gate.get(traversal.gate_key) if traversal.gate_key else None
        if samples is None or samples.count(run.id) < S2_MIN_REFS:
            loose = refs.boss.get(traversal.boss_key)
            if (
                graph.kind(traversal.node) not in BOSS_TYPES
                or loose is None
                or loose.count(run.id) < S2_LOOSE_MIN_REFS
            ):
                continue
            samples, reference = loose, "same boss, any gates (loose reference)"
        n = samples.count(run.id)
        best = samples.smallest(run.id, 2)
        ratio = traversal.ms / best[0]
        if ratio >= S2_MEDIUM_RATIO:
            continue
        strong = ratio < S2_STRONG_RATIO and n >= S2_STRONG_MIN_REFS
        findings.append(
            Finding(
                signature="impossible_traversal",
                strength="strong" if strong else "medium",
                title=(
                    f"{traversal.node} cleared in {traversal.ms / 1000:.1f} s, "
                    f"{ratio:.2f} x the fastest of {n} other runs"
                ),
                run=run,
                evidence={
                    "node": traversal.node,
                    "boss": traversal.boss,
                    "came_from": traversal.came_from,
                    "exit": traversal.exit_to,
                    "time_s": round(traversal.ms / 1000, 1),
                    "floor_s": round(best[0] / 1000, 1),
                    "second_s": round(best[1] / 1000, 1) if len(best) > 1 else None,
                    "ratio": round(ratio, 2),
                    "references": n,
                    "faster_runs": samples.below(traversal.ms, run.id),
                    "reference": reference,
                },
                entry_index=traversal.index,
            )
        )
    return findings


def expected_deaths(
    node: str, graph: Graph, refs: References, run_id: str, pool: str | None
) -> float:
    """Mean deaths per visit of a node's boss key, else of its type in its pool."""
    for samples in (
        refs.node_deaths.get((node, graph.boss(node))),
        refs.type_deaths.get((pool, graph.kind(node))),
    ):
        if samples is not None and samples.count(run_id) >= S1_MIN_RATE_VISITS:
            return samples.mean(run_id) or 0.0
    return 0.0


def death_ratios(bundle: Bundle, refs: References) -> dict[str, float]:
    """Per run, the player's actual over expected deaths on their other runs (1 if too few)."""
    per_user: dict[str, list[tuple[str, int, float]]] = defaultdict(list)
    for run in bundle.runs:
        if not run.history:
            continue
        graph, pool = bundle.graph(run), bundle.pool(run)
        deaths = node_deaths(run)
        expected = sum(expected_deaths(n, graph, refs, run.id, pool) for n in deaths)
        per_user[run.user_id].append((run.id, sum(deaths.values()), expected))
    ratios: dict[str, float] = {}
    for runs in per_user.values():
        for run_id, _, _ in runs:
            others = [(a, x) for rid, a, x in runs if rid != run_id and x > 0]
            if len(others) < S1_MIN_HISTORY_RUNS:
                ratios[run_id] = 1.0
                continue
            ratios[run_id] = sum(a for a, _ in others) / sum(x for _, x in others)
    return ratios


def _major_percentile(
    run: Run, graph: Graph, refs: References, start: int, stop: int
) -> float | None:
    """Median percentile of the run's clean major-boss clears between two entry indexes."""
    values: list[float] = []
    for traversal in clean_traversals(run, graph):
        if (
            not start <= traversal.index < stop
            or graph.kind(traversal.node) not in MAJOR_TYPES
        ):
            continue
        samples = refs.boss.get(traversal.boss_key)
        if samples is None or samples.count(run.id) < S1_MIN_RATE_VISITS:
            continue
        values.append(100 * samples.below(traversal.ms, run.id) / samples.count(run.id))
    return round(statistics.median(values), 1) if values else None


def s1_deaths_stop(
    run: Run, graph: Graph, refs: References, pool: str | None, ratio: float
) -> list[Finding]:
    """A death loop, then a long tail without a single death, against what was expected."""
    history = run.history
    deaths = node_deaths(run)
    first: dict[str, int] = {}
    last: dict[str, int] = {}
    for index, entry in enumerate(history):
        first.setdefault(str(entry["node_id"]), index)
        last[str(entry["node_id"])] = index
    for node in first:  # in order of first visit
        if deaths.get(node, 0) < S1_MIN_STRUGGLE_DEATHS:
            continue
        tail = history[last[node] + 1 :]
        if any(entry.get("deaths") for entry in tail):
            continue
        tail_nodes = list(
            dict.fromkeys(
                str(x["node_id"]) for x in tail if entry_type(x) != "backtrack"
            )
        )
        layers = {graph.layer(n) for n in tail_nodes} - {None}
        majors = [n for n in tail_nodes if graph.kind(n) in MAJOR_TYPES]
        if len(layers) < S1_MIN_TAIL_LAYERS or len(majors) < S1_MIN_TAIL_MAJORS:
            continue
        lam = ratio * sum(
            expected_deaths(n, graph, refs, run.id, pool) for n in tail_nodes
        )
        p_zero = math.exp(-lam)
        if p_zero >= S1_MEDIUM_P:
            return []  # the earliest qualifying struggle decides
        after = last[node] + 1
        spent = int(history[after]["igt_ms"]) - int(history[first[node]]["igt_ms"])
        return [
            Finding(
                signature="deaths_stop",
                strength="strong" if p_zero < S1_STRONG_P else "medium",
                title=(
                    f"{deaths[node]} deaths in {node}, then none over {len(layers)} layers "
                    f"where {lam:.1f} were expected"
                ),
                run=run,
                evidence={
                    "struggle_node": node,
                    "struggle_boss": graph.boss(node),
                    "struggle_deaths": deaths[node],
                    "struggle_s": round(spent / 1000, 1),
                    "tail_layers": len(layers),
                    "tail_major_bosses": len(majors),
                    "expected_deaths": round(lam, 2),
                    "player_ratio": round(ratio, 2),
                    "p_zero": float(f"{p_zero:.2g}"),
                    "major_pct_before": _major_percentile(run, graph, refs, 0, after),
                    "major_pct_after": _major_percentile(
                        run, graph, refs, after, len(history)
                    ),
                },
                entry_index=first[node],
            )
        ]
    return []


def daily_points(rank: int, n: int) -> int:
    """The qualifier formula: 100 to first, proportional down the field, never below 1."""
    value = round(100 * (n - rank + 1) / n)
    if rank != 1:
        value = min(value, 99)
    return max(1, value)


def rank_effect(
    run: Run, bundle: Bundle, lower_ms: int, upper_ms: int
) -> dict[str, Any]:
    """A finished race run's rank, then with the erased time's bounds added back."""
    # The official field: other disqualified runs are out of it.
    race_runs = [
        r
        for r in bundle.race_runs(run.race_id or "")
        if r.id == run.id or not r.disqualified
    ]
    others = [r.igt_ms for r in race_runs if r.status == "finished" and r.id != run.id]

    def rank(igt: int) -> int:
        return 1 + sum(1 for x in others if x < igt)

    effect: dict[str, Any] = {
        "rank": rank(run.igt_ms),
        "rank_with_lower": rank(run.igt_ms + lower_ms),
        "rank_with_upper": rank(run.igt_ms + upper_ms),
        "finishers": len(others) + 1,
    }
    race = bundle.races.get(run.race_id or "", {})
    if str(race.get("event_slot") or "").startswith("qualifier:"):
        n = sum(
            1
            for r in race_runs
            if len(r.history) >= 2 and r.status in ("finished", "abandoned")
        )
        n = max(n, effect["finishers"])
        for key in ("", "_with_lower", "_with_upper"):
            effect[f"points{key}"] = daily_points(effect[f"rank{key}"], n)
    return effect


def s4_save_restore(run: Run, bundle: Bundle) -> list[Finding]:
    """Game restarts that bring the in-game time back down: erased time and its effect."""
    history = run.history
    processes = split_processes(history)
    findings: list[Finding] = []
    for k in range(1, len(processes)):
        before = [i for p in processes[:k] for i in p.entries]
        first = next(
            (
                i
                for i in processes[k].entries
                if history[i].get("message_id") is not None
            ),
            None,
        )
        prev_first = next(
            (
                i
                for i in processes[k - 1].entries
                if history[i].get("message_id") is not None
            ),
            None,
        )
        if first is None or prev_first is None or not before:
            continue
        reached = max(int(history[i]["igt_ms"]) for i in before)
        resumed = int(history[first]["igt_ms"])
        if resumed >= reached:
            continue
        lower = reached - resumed
        gap_ms = processes[k].launch_ms - processes[k - 1].launch_ms
        upper = max(
            lower,
            round(int(history[prev_first]["igt_ms"]) + IGT_SCALE * gap_ms - resumed),
        )
        evidence: dict[str, Any] = {
            "reached_s": round(reached / 1000, 1),
            "resumed_s": round(resumed / 1000, 1),
            "erased_min_s": round(lower / 1000, 1),
            "erased_max_s": round(upper / 1000, 1),
            "restart_after_s": round(gap_ms / 1000),
        }
        strength = "info"
        if run.kind == "race" and run.status == "finished":
            effect = rank_effect(run, bundle, lower, upper)
            evidence["effect"] = effect
            if effect["rank_with_lower"] != effect["rank"]:
                strength = "medium"
        if lower < S4_DODGE_MS:
            strength = "weak"
            evidence["note"] = (
                "a restart instead of a quit-out skips the quit-out penalty"
            )
        findings.append(
            Finding(
                signature="save_restore",
                strength=strength,
                title=(
                    f"game restarted, in-game time back from {reached / 1000:.0f} s "
                    f"to {resumed / 1000:.0f} s"
                ),
                run=run,
                evidence=evidence,
                entry_index=first,
            )
        )
    return findings


def s5_layer_jump(run: Run, graph: Graph) -> list[Finding]:
    """Fog entries that skip layers, and position changes into nodes never visited."""
    history = run.history
    findings: list[Finding] = []
    visited: set[str] = set()
    deepest = -1
    previous_fog: int | None = None
    for index, entry in enumerate(history):
        node = str(entry["node_id"])
        layer = graph.layer(node)
        kind = entry_type(entry)
        if kind == "backtrack" and node not in visited and layer is not None:
            findings.append(
                Finding(
                    signature="layer_jump",
                    strength="strong" if layer > deepest + 1 else "medium",
                    title=f"position changed into {node} (layer {layer}), never visited",
                    run=run,
                    evidence={
                        "kind": "unvisited_position",
                        "node": node,
                        "layer": layer,
                        "deepest_before": deepest,
                        "igt_s": round(int(entry["igt_ms"]) / 1000, 1),
                    },
                    entry_index=index,
                )
            )
        elif kind == "fog" and previous_fog is not None and layer is not None:
            before = history[previous_fog]
            before_layer = graph.layer(str(before["node_id"]))
            if before_layer is not None and layer - before_layer > 1:
                a, b = before.get("message_id"), entry.get("message_id")
                gap = int(b) - int(a) if a is not None and b is not None else None
                real = gap is not None and 0 <= gap <= S5_REAL_JUMP_MAX_GAP
                findings.append(
                    Finding(
                        signature="layer_jump",
                        strength="medium" if real else "weak",
                        title=(
                            f"from layer {before_layer} to layer {layer} in one fog "
                            f"({'sequence break' if real else 'messages lost'})"
                        ),
                        run=run,
                        evidence={
                            "kind": "sequence_break" if real else "lost_messages",
                            "from_node": str(before["node_id"]),
                            "to_node": node,
                            "from_layer": before_layer,
                            "to_layer": layer,
                            "spent_s": round(
                                (int(entry["igt_ms"]) - int(before["igt_ms"])) / 1000, 1
                            ),
                            "message_gap": gap,
                        },
                        entry_index=index,
                    )
                )
        if kind in ("fog", "spawn"):
            previous_fog = index
        visited.add(node)
        if layer is not None:
            deepest = max(deepest, layer)
    return findings


def _finisher_rank(run: Run, bundle: Bundle) -> tuple[int, int]:
    """The run's rank among its race's finishers, other disqualified runs left out."""
    finishers = [
        r.igt_ms
        for r in bundle.race_runs(run.race_id or "")
        if r.status == "finished" and (r.id == run.id or not r.disqualified)
    ]
    return 1 + sum(1 for x in finishers if x < run.igt_ms), len(finishers)


def s6_fresh_account(
    run: Run, bundle: Bundle, run_counts: Mapping[str, int]
) -> list[Finding]:
    """A brand new account (made around the race) with a top-quarter finish."""
    if run.kind != "race" or run.status != "finished" or run.created_at is None:
        return []
    created = parse_time(bundle.users.get(run.user_id, {}).get("created_at"))
    started = parse_time(bundle.races.get(run.race_id or "", {}).get("started_at"))
    if created is None:
        return []
    fresh = created >= run.created_at - S6_MAX_ACCOUNT_AGE or (
        started is not None and created >= started
    )
    if not fresh or run_counts.get(run.user_id, 0) > S6_MAX_RUNS:
        return []
    rank, finishers = _finisher_rank(run, bundle)
    if rank > math.ceil(finishers / 4):
        return []
    return [
        Finding(
            signature="fresh_account",
            strength="weak",
            title=f"account created around the race, {rank} of {finishers}",
            run=run,
            evidence={
                "account_created": created.isoformat(),
                "joined": run.created_at.isoformat(),
                "race_started": started.isoformat() if started else None,
                "runs_in_all": run_counts.get(run.user_id, 0),
                "rank": rank,
                "finishers": finishers,
            },
        )
    ]


def s7_igt_vs_wall(run: Run) -> list[Finding]:
    """In-game time that outran the server clock between joining and the last IGT change."""
    end = run.end
    if run.created_at is None or end is None or run.igt_ms <= 0:
        return []
    # A join time after the end is not one: participants that predate their
    # created_at column (2026-04-26) carry the migration's time instead.
    if run.created_at > end:
        return []
    wall_s = (end - run.created_at).total_seconds()
    needed_s = run.igt_ms / 1000 / IGT_SCALE
    if needed_s <= wall_s + S7_WALL_SLACK_S:
        return []
    return [
        Finding(
            signature="platform",
            strength="strong",
            title="in-game time faster than the server clock",
            run=run,
            evidence={
                "kind": "igt_faster_than_wall",
                "igt_s": round(run.igt_ms / 1000, 1),
                "wall_s": round(wall_s, 1),
                "real_time_needed_s": round(needed_s, 1),
            },
        )
    ]


def s7_platform(bundle: Bundle) -> list[Finding]:
    """Race-level checks: playoff cutoffs never applied, organizers racing their own event."""
    findings: list[Finding] = []
    for race_id, race in bundle.races.items():
        slot = str(race.get("event_slot") or "")
        started = parse_time(race.get("started_at"))
        if (
            not slot
            or slot.startswith("qualifier:")
            or race.get("race_duration_minutes")
        ):
            continue
        finishers = [r for r in bundle.race_runs(race_id) if r.status == "finished"]
        finishers = [r for r in finishers if r.finished_at is not None]
        if started is None or not finishers:
            continue
        first = min(r.finished_at for r in finishers if r.finished_at is not None)
        event = bundle.events.get(str(race.get("event_id") or ""), {})
        cutoff = int(
            (event.get("config") or {}).get("playoff_cutoff_minutes", S7_DEFAULT_CUTOFF)
        )
        minutes = math.ceil((first - started).total_seconds() / 60) + cutoff
        deadline = started + timedelta(minutes=minutes)
        late = [
            r
            for r in finishers
            if r.finished_at is not None and r.finished_at > deadline
        ]
        findings.append(
            Finding(
                signature="platform",
                strength="medium",
                title=f"playoff cutoff never applied in {race.get('name')}",
                races=[race_id],
                players=[r.user_id for r in late],
                evidence={
                    "kind": "cutoff_missing",
                    "deadline": deadline.isoformat(),
                    "late_finishers": [
                        {
                            "user_id": r.user_id,
                            "finished_at": r.finished_at.isoformat()
                            if r.finished_at
                            else None,
                            "late_by_s": round(
                                (r.finished_at - deadline).total_seconds()
                            )
                            if r.finished_at
                            else None,
                        }
                        for r in late
                    ],
                },
            )
        )
    organizing: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for race_id, race in bundle.races.items():
        if not race.get("event_id"):
            continue
        for run in bundle.race_runs(race_id):
            if run.user_id == race.get("organizer_id"):
                organizing[(str(race["event_id"]), run.user_id)].append(
                    (race_id, run.status)
                )
    for (event_id, user_id), items in organizing.items():
        findings.append(
            Finding(
                signature="platform",
                strength="info",
                title=f"organizer racing {len(items)} races of the event they organize",
                races=[race_id for race_id, _ in items],
                players=[user_id],
                evidence={
                    "kind": "organizer_racing",
                    "event_id": event_id,
                    "races": [
                        {"race": bundle.races[r].get("name"), "status": s}
                        for r, s in items
                    ],
                },
            )
        )
    return findings


def s8_debug_flags(run: Run) -> list[Finding]:
    """Cheat-tool flags the mod reported (first observation of each)."""
    findings: list[Finding] = []
    for name, info in sorted((run.debug_flags or {}).items()):
        detail = info if isinstance(info, Mapping) else {}
        findings.append(
            Finding(
                signature="debug_flags",
                strength="strong",
                title=f"cheat-tool flag {name}",
                run=run,
                evidence={"flag": name, **detail},
            )
        )
    return findings


@dataclass(frozen=True)
class LogLine:
    at: datetime
    kind: str  # "grace_query", "unvisited", "backtrack" or "event_flag"
    race_id: str
    participant_id: str | None
    node: str | None
    grace: str | None
    igt_ms: int | None
    message_id: int | None


JOURNAL_ISO = re.compile(
    r"^(?P<iso>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:[.,]\d+)?(?:Z|[+-]\d\d:?\d\d))\s"
)
PY_RECORD = re.compile(
    r"(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d{3} - speedfog_racing\.websocket\.handler"
    r" - [A-Z]+ - (?P<msg>.*?)\s*$"
)
# Since 2026-10-01 mod lines end with "race=R participant=P" ("race=R" before auth);
# before, with "entity=R" (the race). Solo sessions use "training=T" and never match.
_REF = r"(?:race=(?P<race>\S+)(?: participant=(?P<participant>\S+))?|entity=(?P<entity>\S+))"
GRACE_QUERY = re.compile(
    r"^zone_query: node_id=(?P<node>\S+) strategy=(?P<strategy>\S+) candidates=\S+"
    r" grace=(?P<grace>\S+) map_id=\S+(?: igt_ms=(?P<igt>\S+) message_id=(?P<mid>\S+))? "
    + _REF
    + "$"
)
UNVISITED = re.compile(
    r"^zone_query resolved to unvisited node via grace: node=(?P<node>\S+)"
    r" grace_entity_id=(?P<grace>\S+) " + _REF + r" message_id=(?P<mid>\S+)$"
)
BACKTRACK = re.compile(
    r"^zone_query backtrack: \S+ -> (?P<node>\S+)(?: message_id=(?P<mid>\S+))?"
    r" (?:for (?P<old>\S+)|" + _REF + ")$"
)
EVENT_FLAG = re.compile(r"^event_flag: .*?message_id=(?P<mid>\d+) " + _REF + "$")
LOG_PATTERNS = (
    ("grace_query", GRACE_QUERY),
    ("unvisited", UNVISITED),
    ("backtrack", BACKTRACK),
    ("event_flag", EVENT_FLAG),
)


def _int(value: str | None) -> int | None:
    return int(value) if value and value.lstrip("-").isdigit() else None


def _iso(value: str) -> datetime:
    value = value.replace(",", ".").replace("Z", "+00:00")
    if re.search(r"[+-]\d{4}$", value):
        value = f"{value[:-2]}:{value[-2:]}"
    return datetime.fromisoformat(value)


def _parse_message(message: str, at: datetime) -> LogLine | None:
    for kind, pattern in LOG_PATTERNS:
        match = pattern.match(message)
        if match is None:
            continue
        groups = match.groupdict()
        race = groups.get("race") or groups.get("entity") or groups.get("old")
        if not race:
            return None
        if kind == "grace_query" and (
            groups.get("strategy") != "grace" or _int(groups.get("grace")) is None
        ):
            return None  # only warps through the grace menu carry a grace
        return LogLine(
            at=at,
            kind=kind,
            race_id=race,
            participant_id=groups.get("participant"),
            node=groups.get("node"),
            grace=groups.get("grace"),
            igt_ms=_int(groups.get("igt")),
            message_id=_int(groups.get("mid")),
        )
    return None


def parse_logs(paths: Iterable[Path], utc_offset_hours: float = 0.0) -> list[LogLine]:
    """The server's mod log lines that the signatures read, oldest first."""
    offset = timezone(timedelta(hours=utc_offset_hours))
    lines: list[LogLine] = []
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                record = PY_RECORD.search(raw)
                if record is None:
                    continue
                journal = JOURNAL_ISO.match(raw)
                if journal:
                    at = _iso(journal["iso"])
                else:
                    at = datetime.fromisoformat(record["ts"]).replace(tzinfo=offset)
                parsed = _parse_message(record["msg"], at.astimezone(UTC))
                if parsed is not None:
                    lines.append(parsed)
    lines.sort(key=lambda line: line.at)
    return lines


def log_times(lines: Iterable[LogLine]) -> dict[tuple[str, int], datetime]:
    """Server time of each (race, message id) the logs name."""
    return {
        (line.race_id, line.message_id): line.at
        for line in lines
        if line.message_id is not None
    }


def estimate_time(
    run: Run, index: int, times: Mapping[tuple[str, int], datetime]
) -> tuple[datetime | None, str]:
    """When an entry happened: from the logs, else from the game's launch on the player's clock."""
    entry = run.history[index]
    mid = entry.get("message_id")
    if run.race_id and mid is not None and (run.race_id, int(mid)) in times:
        return times[(run.race_id, int(mid))], "server log"
    for process in split_processes(run.history):
        if index not in process.entries:
            continue
        first = next(
            (
                i
                for i in process.entries
                if run.history[i].get("message_id") is not None
            ),
            None,
        )
        if first is None:
            break
        since_first = (
            int(entry["igt_ms"]) - int(run.history[first]["igt_ms"])
        ) / IGT_SCALE
        launch = datetime.fromtimestamp(process.launch_ms / 1000, UTC)
        return launch + timedelta(
            milliseconds=since_first
        ), "estimate from the player's clock"
    return None, "unknown"


def _run_by_message(bundle: Bundle, race_id: str, message_id: int | None) -> Run | None:
    if message_id is None:
        return None
    runs = bundle.race_runs(race_id)
    for run in runs:
        if any(entry.get("message_id") == message_id for entry in run.history):
            return run
    for run in runs:
        for process in split_processes(run.history):
            ids = [
                int(run.history[i]["message_id"])
                for i in process.entries
                if run.history[i].get("message_id") is not None
            ]
            if ids and min(ids) <= message_id <= max(ids) + PROCESS_GAP:
                return run
    return None


def _entered_at(run: Run, node: str, igt_ms: int) -> int | None:
    """IGT of the entry into ``node`` if the runner is in it at ``igt_ms``."""
    before = [entry for entry in run.history if int(entry["igt_ms"]) <= igt_ms]
    if not before or before[-1]["node_id"] != node:
        return None
    for entry in reversed(before):
        if entry["node_id"] == node and entry_type(entry) in ("fog", "spawn"):
            return int(entry["igt_ms"])
    return None


def _maybe_in(run: Run, line: LogLine) -> bool:
    """Whether the run's estimated stay in the line's node covers the line's time."""
    history = run.history
    for index, entry in enumerate(history):
        if entry["node_id"] != line.node:
            continue
        start, _ = estimate_time(run, index, {})
        if start is None:
            continue
        stop = (
            estimate_time(run, index + 1, {})[0]
            if index + 1 < len(history)
            else run.end
        )
        stop = stop or start
        if start - S3_CANDIDATE_SLACK <= line.at <= stop + S3_CANDIDATE_SLACK:
            return True
    return False


def _warp(
    run: Run, line: LogLine, strength: str, title: str, attribution: str
) -> Finding:
    return Finding(
        signature="grace_warp",
        strength=strength,
        title=title,
        run=run,
        evidence={
            "log_time": line.at.isoformat(),
            "node": line.node,
            "grace": line.grace,
            "igt_s": round(line.igt_ms / 1000, 1) if line.igt_ms is not None else None,
            "message_id": line.message_id,
            "attribution": attribution,
        },
    )


def s3_grace_warp(
    lines: list[LogLine], bundle: Bundle
) -> tuple[list[Finding], list[dict[str, Any]]]:
    """Warps through the grace menu that a legitimate run cannot make (race runs only)."""
    participants = {run.id: run for run in bundle.runs if run.kind == "race"}
    backtracks: dict[str, list[datetime]] = defaultdict(list)
    for line in lines:
        if line.kind == "backtrack":
            backtracks[line.race_id].append(line.at)
    findings: list[Finding] = []
    unattributed: list[dict[str, Any]] = []
    for line in lines:
        if line.race_id not in bundle.races or line.kind not in (
            "unvisited",
            "grace_query",
        ):
            continue
        run = participants.get(line.participant_id or "")
        if line.kind == "unvisited":
            attribution = "participant"
            if run is None:
                run, attribution = (
                    _run_by_message(bundle, line.race_id, line.message_id),
                    "message id",
                )
            if run is None:
                unattributed.append({"line": line, "candidates": []})
                continue
            title = f"warp to {line.node}, never visited, through grace {line.grace}"
            findings.append(_warp(run, line, "strong", title, attribution))
            continue
        if run is not None and line.igt_ms is not None:
            entered = _entered_at(run, line.node or "", line.igt_ms)
            if entered is None or line.igt_ms - entered >= S3_RECENT_ENTRY_MS:
                continue
            since = (line.igt_ms - entered) / 1000
            title = f"warp inside {line.node}, {since:.0f} s after entering it"
            findings.append(_warp(run, line, "medium", title, "participant"))
            continue
        # Old format: no participant and no in-game time. A warp to another node is
        # followed by its backtrack line (and seen by S5); keep the in-zone ones.
        if any(
            0 <= (at - line.at).total_seconds() <= S3_BACKTRACK_WINDOW_S
            for at in backtracks[line.race_id]
        ):
            continue
        candidates = [r for r in bundle.race_runs(line.race_id) if _maybe_in(r, line)]
        if len(candidates) == 1:
            title = f"warp inside {line.node} (attributed by estimated time)"
            findings.append(
                _warp(candidates[0], line, "medium", title, "estimated time")
            )
        else:
            unattributed.append(
                {"line": line, "candidates": [r.id for r in candidates]}
            )
    return findings, unattributed


def evaluate(
    bundle: Bundle, lines: list[LogLine]
) -> tuple[list[Finding], list[dict[str, Any]]]:
    """Every signature on every run (the base rates need them all), then the race checks."""
    refs = build_references(bundle)
    ratios = death_ratios(bundle, refs)
    counts = Counter(run.user_id for run in bundle.runs)
    findings: list[Finding] = []
    for run in bundle.runs:
        graph = bundle.graph(run)
        findings += s1_deaths_stop(
            run, graph, refs, bundle.pool(run), ratios.get(run.id, 1.0)
        )
        findings += s2_impossible_traversal(run, graph, refs)
        findings += s4_save_restore(run, bundle)
        findings += s5_layer_jump(run, graph)
        findings += s6_fresh_account(run, bundle, counts)
        findings += s7_igt_vs_wall(run)
        findings += s8_debug_flags(run)
    findings += s7_platform(bundle)
    grace, unattributed = s3_grace_warp(lines, bundle)
    return findings + grace, unattributed


def is_target(finding: Finding, bundle: Bundle) -> bool:
    if finding.run is not None:
        return finding.run.is_target
    return any(
        bundle.races.get(race_id, {}).get("is_target") for race_id in finding.races
    )


def in_scope(
    finding: Finding, scope: str, bundle: Bundle, player_id: str | None
) -> bool:
    if scope == "player":
        return player_id in finding.players
    return scope == "all" or is_target(finding, bundle)


def base_rates(
    findings: list[Finding], bundle: Bundle
) -> dict[str, dict[str, dict[str, int]]]:
    """Distinct runs (or races) firing each signature and strength, history versus targets."""
    seen: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for finding in findings:
        bucket = "target" if is_target(finding, bundle) else "history"
        subject = finding.run.id if finding.run else ",".join(finding.races)
        seen[(finding.signature, finding.strength, bucket)].add(subject)
    rates: dict[str, dict[str, dict[str, int]]] = {}
    for (signature, strength, bucket), subjects in seen.items():
        cell = rates.setdefault(signature, {}).setdefault(
            strength, {"history": 0, "target": 0}
        )
        cell[bucket] = len(subjects)
    return rates


def resolve_player(name: str, bundle: Bundle, identities: Mapping[str, Any]) -> str:
    """A user id from a pseudonym, or from a real Twitch login through the identities."""
    alias = name
    for pseudonym, info in identities.items():
        if str(info.get("twitch_username", "")).lower() == name.lower():
            alias = pseudonym
    for user_id, user in bundle.users.items():
        if user.get("name") == alias:
            return user_id
    raise SystemExit(f"no player named {name!r} in the bundle")


def _player(
    user_id: str, bundle: Bundle, identities: Mapping[str, Any]
) -> dict[str, Any]:
    pseudonym = str(bundle.users.get(user_id, {}).get("name") or user_id)
    real = identities.get(pseudonym, {}).get("twitch_username")
    return {"user_id": user_id, "pseudonym": pseudonym, "name": real}


def _label(player: Mapping[str, Any]) -> str:
    if player.get("name") and player["name"] != player["pseudonym"]:
        return f"{player['pseudonym']} ({player['name']})"
    return str(player["pseudonym"])


def _finding_json(
    finding: Finding,
    bundle: Bundle,
    identities: Mapping[str, Any],
    times: Mapping[tuple[str, int], datetime],
) -> dict[str, Any]:
    window: dict[str, Any] | None = None
    if finding.run is not None and finding.entry_index is not None:
        at, source = estimate_time(finding.run, finding.entry_index, times)
        window = {
            "at": at.isoformat(timespec="seconds") if at else None,
            "source": source,
        }
    run = finding.run
    return {
        "signature": finding.signature,
        "strength": finding.strength,
        "title": finding.title,
        "players": [_player(p, bundle, identities) for p in finding.players],
        "races": [
            {
                "id": r,
                "name": bundle.races.get(r, {}).get("name"),
                "started_at": bundle.races.get(r, {}).get("started_at"),
            }
            for r in finding.races
        ],
        "run": {"kind": run.kind, "id": run.id, "race_id": run.race_id}
        if run
        else None,
        "evidence": finding.evidence,
        "window": window,
    }


def render_json(
    meta: dict[str, Any],
    findings: list[dict[str, Any]],
    rates: dict[str, Any],
    unattributed: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "meta": meta,
        "findings": findings,
        "base_rates": rates,
        "unattributed": unattributed,
    }


def render_markdown(
    meta: dict[str, Any],
    findings: list[dict[str, Any]],
    rates: dict[str, Any],
    unattributed: list[dict[str, Any]],
) -> str:
    lines = [
        f"# Known signatures: {meta['bundle']}",
        "",
        f"- Data up to: {meta['latest_activity']}",
        f"- Scope: {meta['scope']}",
        f"- Logs: {meta['logs'] or 'none (S3 not checked)'}",
        f"- Logs cover: {meta['logs_period'] or '-'}",
        f"- Thresholds: {', '.join(f'{k}={v}' for k, v in meta['thresholds'].items())}",
        "",
        "## Players",
        "",
        "| player | strongest | signatures |",
        "| ------ | --------- | ---------- |",
    ]
    by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        key = _label(finding["players"][0]) if finding["players"] else "(platform)"
        by_player[key].append(finding)
    order = sorted(
        by_player,
        key=lambda k: min(STRENGTHS.index(f["strength"]) for f in by_player[k]),
    )
    for key in order:
        strongest = min(by_player[key], key=lambda f: STRENGTHS.index(f["strength"]))
        names = ", ".join(sorted({f["signature"] for f in by_player[key]}))
        lines.append(f"| {key} | {strongest['strength']} | {names} |")
    lines += ["", "## Findings", ""]
    for finding in findings:
        who = ", ".join(_label(p) for p in finding["players"]) or "(platform)"
        lines.append(f"### [{finding['strength']}] {finding['signature']}: {who}")
        lines.append("")
        lines.append(f"- {finding['title']}")
        for race in finding["races"]:
            lines.append(f"- Race: {race['name']} ({race['started_at']}, {race['id']})")
        if finding["run"]:
            lines.append(f"- Run: {finding['run']['kind']} {finding['run']['id']}")
        evidence = "; ".join(f"{k}: {v}" for k, v in finding["evidence"].items())
        lines.append(f"- Evidence: {evidence}")
        if finding["window"] and finding["window"]["at"]:
            window = finding["window"]
            lines.append(f"- VOD time: around {window['at']} UTC ({window['source']})")
        lines.append("")
    lines += [
        "## Base rates",
        "",
        "Distinct runs (or races) firing each signature, over history and over targets.",
        "",
        "| signature | strength | history | targets |",
        "| --------- | -------- | ------- | ------- |",
    ]
    for signature in sorted(rates):
        for strength in STRENGTHS:
            cell = rates[signature].get(strength)
            if cell:
                lines.append(
                    f"| {signature} | {strength} | {cell['history']} | {cell['target']} |"
                )
    if unattributed:
        lines += ["", "## Unattributed log lines", ""]
        for row in unattributed:
            candidates = ", ".join(row["candidates"]) or "none"
            lines.append(
                f"- {row['at']} race {row['race_id']}: {row['kind']} {row['node']} "
                f"grace {row['grace']} (candidates: {candidates})"
            )
    return "\n".join(lines) + "\n"


def thresholds() -> dict[str, Any]:
    """The signature constants in force, for the report's header."""
    return {
        name: str(value) if isinstance(value, timedelta) else value
        for name, value in globals().items()
        if re.fullmatch(r"S\d_[A-Z_]+", name)
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check an audit bundle against known signatures."
    )
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--logs", type=Path, action="append", default=[])
    parser.add_argument("--logs-utc-offset", type=float, default=0.0)
    parser.add_argument("--identities", type=Path)
    scope_group = parser.add_mutually_exclusive_group()
    scope_group.add_argument("--scope", choices=("targets", "all"), default="targets")
    scope_group.add_argument("--player")
    parser.add_argument("--out-prefix", type=Path)
    args = parser.parse_args(argv)

    bundle_path = args.bundle.expanduser().resolve()
    prefix = check_out_prefix(
        args.out_prefix or DEFAULT_OUT_DIR / f"{bundle_path.name}.signatures",
        bundle_path,
    )
    bundle = load_bundle(bundle_path)
    identities: dict[str, Any] = (
        json.loads(args.identities.expanduser().read_text(encoding="utf-8"))
        if args.identities
        else {}
    )
    lines = parse_logs(args.logs, args.logs_utc_offset)
    player_id = resolve_player(args.player, bundle, identities) if args.player else None
    scope = "player" if player_id else str(args.scope)

    findings, unattributed = evaluate(bundle, lines)
    rates = base_rates(findings, bundle)
    selected = [f for f in findings if in_scope(f, scope, bundle, player_id)]
    selected.sort(
        key=lambda f: (STRENGTHS.index(f.strength), f.signature, f.players[:1])
    )
    times = log_times(lines)
    rendered = [_finding_json(f, bundle, identities, times) for f in selected]
    loose = [
        {
            "at": row["line"].at.isoformat(timespec="seconds"),
            "race_id": row["line"].race_id,
            "kind": row["line"].kind,
            "node": row["line"].node,
            "grace": row["line"].grace,
            "candidates": row["candidates"],
        }
        for row in unattributed
    ]
    meta = {
        "bundle": bundle_path.name,
        "latest_activity": bundle.manifest.get("latest_activity"),
        "scope": f"player {args.player}" if player_id else scope,
        "logs": [str(p) for p in args.logs],
        "logs_period": (
            f"{lines[0].at.isoformat(timespec='seconds')} to "
            f"{lines[-1].at.isoformat(timespec='seconds')}"
            if lines
            else None
        ),
        "thresholds": thresholds(),
    }
    prefix.parent.mkdir(parents=True, exist_ok=True)
    markdown_path = prefix.with_name(prefix.name + ".md")
    json_path = prefix.with_name(prefix.name + ".json")
    markdown_path.write_text(
        render_markdown(meta, rendered, rates, loose), encoding="utf-8"
    )
    json_path.write_text(
        json.dumps(render_json(meta, rendered, rates, loose), indent=2, default=str)
        + "\n",
        encoding="utf-8",
    )
    counts = Counter(f.strength for f in selected)
    print(f"{len(selected)} findings ({dict(counts)}): {markdown_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
