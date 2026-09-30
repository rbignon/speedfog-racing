#!/usr/bin/env python3
"""Export a self-contained data bundle for a run-integrity audit.

The bundle holds what an analyst needs to look for suspicious runs: every
race, participation and solo session with its zone history, the seed graphs,
the users, the pools, and the chat of the races under review. The analyst can
be a person, or an LLM session started in the bundle's folder with no access
to the repository. The bundle also gets a copy of tools/audit/: the data
dictionary (what the fields mean) and the brief (what is asked). Neither says
anything about what earlier audits found.

Races under review ("targets") are those started at or after --since, plus
every race attached to --event whatever its start. Solo sessions created at or
after --since are targets too. Everything else is exported as history, because
baselines need each player's past runs and each zone's past clear times.

The export is read-only. On PostgreSQL it runs in one REPEATABLE READ, READ
ONLY transaction, so a bundle taken from a live database is a consistent
snapshot. Mod tokens and API tokens are never exported.

Twitch names are replaced by stable pseudonyms (player_0001 is the oldest
account) unless --real-names is given, since a name can prime an analyst. The
same replacement runs over the free text that repeats them: race names, custom
rules, chat messages (system messages such as "x has joined the race" carry
display names) and event configs (the withdrawn list). It only knows the exact
logins and display names of four characters or more, so a nickname or a
misspelling in someone's message goes through, and a login that is also an
ordinary word gets replaced wherever that word appears. System accounts (the
daily seeds' organizer) are not people and keep their names. The mapping back
to real names
goes to --identities, by default under ~/.speedfog-audit/: it may sit
neither in the bundle nor in the folder around it. Twitch account ids are
exported as a rank (1 = the oldest Twitch account among the users), which
keeps their order without the id that would name the account.

The bundle directory must be new or empty and must sit outside the repository:
it holds personal data, and an analyst session started in it must not reach
the code.

Usage:
    cd server && uv run python ../tools/audit_extract.py \\
        --since 2026-09-23T08:00:00Z --event season-one \\
        --out ~/src/speedfog-audit/2026-09-30
"""

from __future__ import annotations

import argparse
import asyncio
import enum
import json
import re
import shutil
import sys
import uuid
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT_DOCS = Path(__file__).resolve().parent / "audit"
BUNDLE_DOCS = ("DATA_DICTIONARY.md", "BRIEF.md")
WEAPONS_JSON = REPO_ROOT / "server" / "data" / "weapons.json"
# Where pseudonym mappings go by default: away from the bundle and from its
# parent folder, which an analyst session started in the bundle could list.
IDENTITIES_DIR = Path.home() / ".speedfog-audit"

# Node fields kept for the seeds of history runs: enough to place a zone in
# its layer, know what kind of zone it is, and which boss stands there (bosses
# are randomized per seed; display_name is the vanilla label). Target seeds
# keep their whole graph.
COMPACT_NODE_KEYS = (
    "type",
    "layer",
    "tier",
    "display_name",
    "zones",
    "boss_name",
    "randomized_bosses",
)

# Event config fields that are free text (names can appear in them). The rest
# of the config is structure (mode, stage and slot keys) and stays untouched.
EVENT_TEXT_KEYS = ("withdrawn", "rules", "playoff_rules", "facts")

# Shorter names are too likely to be ordinary words in free text.
MIN_SCRUBBED_NAME = 4


def jsonable(value: Any) -> Any:
    """A database value as plain JSON; a naive datetime is read as UTC (SQLite drops the offset)."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    return value


def pseudonyms(users: Iterable[Mapping[str, Any]]) -> dict[Any, str]:
    """Stable pseudonyms in account-creation order: player_0001 is the oldest account."""
    ordered = sorted(
        users, key=lambda u: (jsonable(u["created_at"]) or "", str(u["id"]))
    )
    width = max(4, len(str(len(ordered))))
    return {u["id"]: f"player_{i:0{width}d}" for i, u in enumerate(ordered, 1)}


def unchanged(value: Any) -> Any:
    return value


def name_scrubber(
    users: Iterable[Mapping[str, Any]], aliases: Mapping[Any, str]
) -> Callable[[Any], Any]:
    """Replace known logins and display names by their alias in free text.

    Whole words only, in any case, longest name first; the returned function
    walks strings inside lists and dicts too.
    """
    names: dict[str, str] = {}
    for u in users:
        if u["id"] not in aliases:
            continue
        for name in (u["twitch_username"], u["twitch_display_name"]):
            if name and len(name) >= MIN_SCRUBBED_NAME:
                names.setdefault(name.casefold(), aliases[u["id"]])
    if not names:
        return unchanged
    alternatives = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    pattern = re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)

    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            # A match the regex folded differently from casefold() is still
            # replaced, never left in clear.
            return pattern.sub(
                lambda m: names.get(m.group(0).casefold(), "player_unknown"), value
            )
        if isinstance(value, Mapping):
            return {k: scrub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value

    return scrub


def twitch_ranks(users: Iterable[Mapping[str, Any]]) -> dict[Any, int]:
    """Rank of each user's Twitch account id, 1 for the smallest (Twitch ids grow over time)."""
    ordered = sorted(
        users, key=lambda u: (len(u["twitch_id"]), u["twitch_id"], str(u["id"]))
    )
    return {u["id"]: i for i, u in enumerate(ordered, 1)}


def compact_graph(graph: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """A seed graph reduced to its structure, for seeds only history runs used."""
    if not graph:
        return None
    nodes = graph.get("nodes") or {}
    return {
        "total_layers": graph.get("total_layers"),
        "nodes": {
            node_id: {k: node[k] for k in COMPACT_NODE_KEYS if k in node}
            for node_id, node in nodes.items()
        },
        "edges": [{"from": e["from"], "to": e["to"]} for e in graph.get("edges") or []],
        "care_package": graph.get("care_package"),
        "weapon_upgrade": graph.get("weapon_upgrade"),
    }


def parse_since(raw: str) -> datetime:
    """An ISO instant; a naive one is read as UTC."""
    moment = datetime.fromisoformat(raw)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def check_paths(
    out: Path, identities: Path, repo_root: Path = REPO_ROOT
) -> tuple[Path, Path]:
    """Resolve the bundle and identities paths, refusing anything that could leak.

    Both must be outside the repository. The identities file must stay out of
    the bundle and of the folder around it (an analyst in the bundle could list
    it); the bundle must be new or empty.
    """
    out = out.expanduser().resolve()
    identities = identities.expanduser().resolve()
    repo_root = repo_root.resolve()
    for path in (out, identities):
        if path == repo_root or repo_root in path.parents:
            raise SystemExit(f"refusing {path}: it is inside the repository")
    if out.parent in identities.parents:
        raise SystemExit(
            f"refusing {identities}: the identities file must stay out of the bundle "
            "and of the folder around it"
        )
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise SystemExit(f"refusing {out}: the bundle directory must be new or empty")
    return out, identities


def write_row(handle: TextIO, row: Mapping[Any, Any]) -> None:
    handle.write(json.dumps(jsonable(row), ensure_ascii=False) + "\n")


async def export(
    maker: async_sessionmaker[AsyncSession],
    out: Path,
    identities: Path,
    *,
    since: datetime,
    event_slug: str | None,
    real_names: bool,
) -> dict[str, Any]:
    """Write the bundle into ``out`` (already checked) and return its manifest."""
    from sqlalchemy import func, or_, select, text

    from speedfog_racing.models import (
        Caster,
        ChatMessage,
        Event,
        EventSignup,
        Participant,
        Pool,
        Race,
        Seed,
        TrainingSession,
        User,
        UserRole,
    )

    data = out / "data"
    counts: dict[str, int] = {}

    def dump(name: str, rows: Iterable[Mapping[Any, Any]]) -> None:
        with open(data / name, "w", encoding="utf-8") as handle:
            n = 0
            for row in rows:
                write_row(handle, row)
                n += 1
        counts[name] = n

    async with maker() as db:
        if db.bind.dialect.name == "postgresql":
            await db.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )

        event_id = None
        if event_slug is not None:
            event_id = (
                await db.execute(select(Event.id).where(Event.slug == event_slug))
            ).scalar_one_or_none()
            if event_id is None:
                raise SystemExit(f"no event with slug {event_slug!r}")
        data.mkdir(parents=True, exist_ok=True)

        # Users first: every other file refers to them by id only.
        users = [
            dict(r)
            for r in (
                await db.execute(
                    select(
                        User.id,
                        User.twitch_id,
                        User.twitch_username,
                        User.twitch_display_name,
                        User.role,
                        User.created_at,
                        User.last_seen,
                        User.timezone,
                        User.locale,
                    )
                )
            ).mappings()
        ]
        people = [u for u in users if u["role"] != UserRole.SYSTEM]
        aliases = {} if real_names else pseudonyms(people)
        scrub = unchanged if real_names else name_scrubber(users, aliases)
        ranks = twitch_ranks(users)
        user_rows = []
        for u in users:
            user_row = {k: u[k] for k in ("id", "role", "created_at", "last_seen")}
            if real_names:
                user_row["twitch_id"] = u["twitch_id"]
            else:
                user_row["twitch_id_rank"] = ranks[u["id"]]
            user_row |= {"timezone": u["timezone"], "locale": u["locale"]}
            user_row["name"] = aliases.get(u["id"], u["twitch_username"])
            if real_names:
                user_row["display_name"] = u["twitch_display_name"]
            user_rows.append(user_row)
        dump("users.jsonl", user_rows)

        target_filter = Race.started_at >= since
        if event_id is not None:
            target_filter = or_(target_filter, Race.event_id == event_id)
        races = [
            dict(r)
            for r in (
                await db.execute(
                    select(
                        Race.id,
                        Race.name,
                        Race.organizer_id,
                        Race.seed_id,
                        Race.status,
                        Race.config,
                        Race.created_at,
                        Race.scheduled_at,
                        Race.started_at,
                        Race.seeds_released_at,
                        Race.finished_at,
                        Race.is_public,
                        Race.open_registration,
                        Race.max_participants,
                        Race.late_join_window_minutes,
                        Race.race_duration_minutes,
                        Race.custom_rules,
                        Race.private_dag,
                        Race.deathless,
                        Race.daily_date,
                        Race.exclude_from_stats,
                        Race.event_id,
                        Race.event_slot,
                        target_filter.label("is_target"),
                    )
                )
            ).mappings()
        ]
        for race in races:
            race["is_target"] = bool(race["is_target"])
            race["name"] = scrub(race["name"])
            race["custom_rules"] = scrub(race["custom_rules"])
        target_races = {r["id"] for r in races if r["is_target"]}
        dump("races.jsonl", races)

        seed_ids = {r["seed_id"] for r in races if r["seed_id"] is not None}
        target_seeds = {
            r["seed_id"] for r in races if r["is_target"] and r["seed_id"] is not None
        }

        with open(data / "participants.jsonl", "w", encoding="utf-8") as handle:
            n = 0
            stream = await db.stream(
                select(
                    Participant.id,
                    Participant.race_id,
                    Participant.user_id,
                    Participant.status,
                    Participant.created_at,
                    Participant.finished_at,
                    Participant.igt_ms,
                    Participant.death_count,
                    Participant.current_layer,
                    Participant.current_zone,
                    Participant.last_igt_change_at,
                    Participant.zone_history,
                    Participant.layer_entry_igts,
                ).order_by(Participant.created_at)
            )
            async for row in stream.mappings():
                write_row(handle, {**row, "is_target": row["race_id"] in target_races})
                n += 1
            counts["participants.jsonl"] = n

        target_training = 0
        with open(data / "training_sessions.jsonl", "w", encoding="utf-8") as handle:
            n = 0
            stream = await db.stream(
                select(
                    TrainingSession.id,
                    TrainingSession.user_id,
                    TrainingSession.seed_id,
                    TrainingSession.status,
                    TrainingSession.created_at,
                    TrainingSession.finished_at,
                    TrainingSession.igt_ms,
                    TrainingSession.death_count,
                    TrainingSession.current_zone,
                    TrainingSession.zone_history,
                ).order_by(TrainingSession.created_at)
            )
            async for row in stream.mappings():
                created = row["created_at"]
                if created is not None and created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                is_target = created is not None and created >= since
                target_training += is_target
                seed_ids.add(row["seed_id"])
                write_row(handle, {**row, "is_target": is_target})
                n += 1
            counts["training_sessions.jsonl"] = n

        with open(data / "seeds.jsonl", "w", encoding="utf-8") as handle:
            n = 0
            if seed_ids:
                stream = await db.stream(
                    select(
                        Seed.id,
                        Seed.seed_number,
                        Seed.pool_name,
                        Seed.total_layers,
                        Seed.difficulty_score,
                        Seed.status,
                        Seed.created_at,
                        Seed.graph_json,
                    ).where(Seed.id.in_(seed_ids))
                )
                async for row in stream.mappings():
                    seed = dict(row)
                    graph = seed.pop("graph_json")
                    full = seed["id"] in target_seeds
                    seed["graph"] = graph if full else compact_graph(graph)
                    seed["graph_is_full"] = full
                    write_row(handle, seed)
                    n += 1
            counts["seeds.jsonl"] = n

        dump(
            "pools.jsonl",
            (await db.execute(select(Pool.name, Pool.enabled, Pool.config))).mappings(),
        )
        dump(
            "casters.jsonl",
            (await db.execute(select(Caster.race_id, Caster.user_id))).mappings(),
        )
        chat: list[Mapping[Any, Any]] = []
        if target_races:
            chat = [
                {**m, "message": scrub(m["message"])}
                for m in (
                    await db.execute(
                        select(
                            ChatMessage.id,
                            ChatMessage.race_id,
                            ChatMessage.channel,
                            ChatMessage.user_id,
                            ChatMessage.message,
                            ChatMessage.reply_to_id,
                            ChatMessage.created_at,
                        )
                        .where(ChatMessage.race_id.in_(target_races))
                        .order_by(ChatMessage.created_at)
                    )
                ).mappings()
            ]
        dump("chat_messages.jsonl", chat)
        events = (
            await db.execute(
                select(
                    Event.id,
                    Event.slug,
                    Event.name,
                    Event.starts_at,
                    Event.qualifier_ends_at,
                    Event.ends_at,
                    Event.newcomer_threshold,
                    Event.config,
                )
            )
        ).mappings()
        dump(
            "events.jsonl",
            (
                {
                    **e,
                    "config": {
                        k: scrub(v) if k in EVENT_TEXT_KEYS else v
                        for k, v in (e["config"] or {}).items()
                    },
                }
                for e in events
            ),
        )
        dump(
            "event_signups.jsonl",
            (
                await db.execute(
                    select(
                        EventSignup.event_id,
                        EventSignup.user_id,
                        EventSignup.created_at,
                    )
                )
            ).mappings(),
        )

        latest_join = (
            await db.execute(select(func.max(Participant.created_at)))
        ).scalar()
        latest_training = (
            await db.execute(select(func.max(TrainingSession.created_at)))
        ).scalar()

    shutil.copyfile(WEAPONS_JSON, data / "weapons.json")
    for name in BUNDLE_DOCS:
        shutil.copyfile(AUDIT_DOCS / name, out / name)

    manifest: dict[str, Any] = jsonable(
        {
            "generated_at": datetime.now(UTC),
            "latest_activity": {
                "participant_joined": latest_join,
                "training_session_created": latest_training,
            },
            "since": since,
            "event": event_slug,
            "pseudonymized": not real_names,
            "targets": {
                "races": len(target_races),
                "training_sessions": target_training,
            },
            "files": counts,
        }
    )
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    if not real_names:
        by_alias = {
            aliases[u["id"]]: {
                "id": str(u["id"]),
                "twitch_username": u["twitch_username"],
                "twitch_display_name": u["twitch_display_name"],
            }
            for u in people
        }
        identities.parent.mkdir(parents=True, exist_ok=True)
        identities.write_text(json.dumps(by_alias, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export a data bundle for a run-integrity audit."
    )
    parser.add_argument(
        "--since",
        required=True,
        type=parse_since,
        help="start of the review window, ISO 8601 (naive = UTC)",
    )
    parser.add_argument("--event", help="event slug whose races are all under review")
    parser.add_argument(
        "--out", required=True, type=Path, help="bundle directory (new or empty)"
    )
    parser.add_argument(
        "--identities",
        type=Path,
        help=f"pseudonym mapping file (default: {IDENTITIES_DIR}/<out name>.identities.json)",
    )
    parser.add_argument(
        "--real-names",
        action="store_true",
        help="keep Twitch names instead of pseudonyms",
    )
    args = parser.parse_args()
    identities = args.identities or IDENTITIES_DIR / f"{args.out.name}.identities.json"
    out, identities = check_paths(args.out, identities)

    # Must run from server/ (cd server && uv run python ../tools/audit_extract.py)
    sys.path.insert(0, str(Path.cwd()))
    import speedfog_racing.api  # noqa: F401  (settles the api <-> services import cycle)
    from speedfog_racing.database import async_session_maker

    manifest = asyncio.run(
        export(
            async_session_maker,
            out,
            identities,
            since=args.since,
            event_slug=args.event,
            real_names=args.real_names,
        )
    )
    print(json.dumps(manifest, indent=2))
    if not args.real_names:
        print(f"identities: {identities}")


if __name__ == "__main__":
    main()
