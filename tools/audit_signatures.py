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
from collections import defaultdict
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
