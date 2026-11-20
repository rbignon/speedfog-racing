# Relay races

A relay race is a team race on a single seed: the teammates of a team share one
run, and only one of them holds the baton (plays) at a time.

## Rules

- A team has 2 to 6 members.
- Each member may play at most `ceil(total_layers / active_members) + 1` layers
  of the run.
- A teammate who goes offline while holding the baton has 60 seconds to come
  back before the baton can be taken from them.
- A `relay_take` request must be acknowledged within 30 seconds.
- A `relay_release` request must be answered within 15 seconds.
- A team with no activity for 30 minutes is considered inactive.
- The save a teammate takes the baton with must be fresh: its IGT must not
  exceed 60 seconds (`MAX_FRESH_IGT_MS`).
- The relay wire contract starts at protocol 1.19 (`RELAY_MIN_PROTOCOL`).

## Seeds

A relay seed carries a top-level `relay` object in its `graph.json` (generator
version 4.15), written when the relay plugin is enabled. The pools enable it in
`tools/pools/_base.toml`. The block holds the event flags the mod and the server
share:

| Key                | Value      | Meaning                             |
| ------------------ | ---------- | ----------------------------------- |
| `lock_flag`        | 1050290500 | the baton lock                      |
| `chapel_warp_flag` | 1050290501 | the chapel warp                     |
| `warp_flag_base`   | 1050290510 | first of the warp flags             |
| `warp_flag_count`  | 490        | how many warp flags follow the base |
| `zone_flag_base`   | 1050294000 | first of the zone flags             |

`Seed.relay` is true when `relay` is a non-empty object (`seed_has_relay` in
`services/relay.py`). The pool scan sets it when it adds a seed, and an indexed
column serves every filter, so no query parses `graph_json`. The migration
backfills the seeds scanned before the column existed. `relay_flags` returns the
block without `warp_flag_count`.

A relay race draws only relay seeds (`get_available_seed(..., require_relay=True)`,
the same AVAILABLE then SEEN fallback and speedrun floor as any normal draw). When
the pool has none, the draw fails with `No relay seed available in pool '<pool>'`,
on the first draw and on a reroll alike.

`GET /api/pools` reports `relay_available` per pool: its AVAILABLE and SEEN relay
seeds, the ones a relay race can draw. Seeds generated before the plugin was
enabled carry no block and never count; regenerate a pool to get relay seeds.

## Teams

## Start

## Baton

## Cap

## Progress and guards

## Lifecycle

## Exclusions

## Outside the live page

## Web

## Bot

## In-game checklist
