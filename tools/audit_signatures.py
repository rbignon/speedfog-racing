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

import json
import math
import statistics
from bisect import bisect_left
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
# S4 save_restore
S4_DODGE_MS = 60_000


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
                created_at=parse_time(row.get("created_at")),
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
    """Entries into a node with no death there, directly followed by a fog into a successor.

    The final node of a finished run counts until the finish. The gate key
    names the entrance used (from the node of the entry just before, so a
    re-entry after a respawn counts from where the runner respawned) and the
    exit taken.
    """
    history = run.history
    out: list[Traversal] = []
    for index, entry in enumerate(history):
        if entry_type(entry) not in ("fog", "spawn") or entry.get("deaths"):
            continue
        node = str(entry["node_id"])
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
