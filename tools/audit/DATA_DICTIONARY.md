# Data dictionary

This bundle is an export of the SpeedFog Racing database, made for an audit of
run integrity. This file says what the data means and how the platform
produces it. It deliberately says nothing about what to look for.

All timestamps are ISO 8601 in UTC. All ids are UUIDs unless stated otherwise.
Every `*.jsonl` file under `data/` holds one JSON object per line.
`manifest.json` states the export time, the latest activity in the database,
the review window (`since`), the event under review, whether names are
pseudonymized, and the row count of each file.

When names are pseudonymized, each person appears as `player_NNNN` (in order
of account creation). The same pseudonyms replace known Twitch logins and
display names inside free text: race names, custom rules, chat messages and
the text fields of event configs. Nicknames and misspellings can still show
through, and a login that is also an ordinary word is replaced wherever that
word appears. System accounts, such as the organizer of the daily seeds, keep
their names.

## The platform

**SpeedFog** is an Elden Ring randomizer built on FogMod: a seed is a layered
directed acyclic graph (DAG) of zones, from a start node (the Chapel of
Anticipation) to a final boss. Each node is a cluster of one or more zones.
Each node has exits, which are fog gates leading to nodes of the next layer;
paths merge and split. A runner picks which fog gate to take without knowing
where it leads, unless they know the seed. Every edge goes from one layer to
the next, so every path from start to finish crosses every layer. Runs are
ranked on in-game time (IGT).

**Pools** are game modes (`standard`, `sprint`, `boss_rush`, and others). In
`boss_rush` every node is a boss arena. A pool's `config` holds its display
name, rules text and generator settings. Seeds are generated in advance, in
batches, with the settings of the day (see Changes over time).

**Bosses are randomized per seed** in most pools: the same arena can hold a
different boss in another seed, major bosses included. A node's
`display_name` is the vanilla label of the place (it can name a boss that is
not there); its `boss_name` is the boss actually placed in this seed.

**Seed pack.** Each participant downloads a zip holding the randomized game
files, the racing mod (a DLL loaded into the game), and a config carrying that
participant's token. The seed graph itself (`graph.json`) is removed from the
pack. The run must start from a new save: a participant only becomes `playing`
when the first IGT their mod reports is at most 60 seconds.

**The mod** reads game memory. It reports IGT and the game's death counter
about once per second (`status_update`), reports fog traversals (event flags),
reports position changes without a fog traversal (`zone_query`), and reports
the weapons equipped in each hand. It draws an in-game overlay.

**Race lifecycle.** A race goes `setup` -> `running` -> `finished`.
`late_join_window_minutes` is how long after `started_at` a user can still
join; `race_duration_minutes` is when the race closes automatically. A
participant goes `registered` -> `ready` (mod connected) -> `playing` ->
`finished` or `abandoned`. A participant can leave a race only while it is in
`setup`. Besides a runner's own choice, the server sets `abandoned`:

- on a non-daily running race, when a playing runner's IGT has not changed
  for 30 minutes (and in some cases when a registered runner never
  connected);
- when a race closes, for every runner not finished;
- on a `deathless` race, at the first death.

**Resets and rerolls.** A run in the data is not always a runner's first
contact with its seed:

- An organizer can reset a running or finished race back to `setup`. This
  wipes every participant's zone history, IGT and layer, keeps the same seed,
  and leaves no trace in the data.
- An admin can reroll a daily seed: every run on it is wiped, the race gets a
  new seed, and the old seed goes back to the pool, where a later race or solo
  session can draw it again.

**Asynchronous races.** Daily seeds (`daily_date` set) and event qualifier
seeds (`event_slot` starting with `qualifier:`) stay open over a long window,
and each runner starts whenever they like within it.

**Events.** `events.jsonl` holds each event's dates and `config`: modes,
`seeds_per_mode` (the qualifier seeds per mode), stages, and the rules text
shown to players. The qualifier races also carry `custom_rules`.

- **Qualifier scoring**, per seed and by rank: with `n` qualified runs (at
  least two zone history entries, finished or abandoned), rank `r` scores
  `round(100 * (n - r + 1) / n)`, never below 1, and only rank 1 reaches 100.
  Finished runs rank by IGT; abandoned runs come after them, deeper layer
  first, then lower IGT. The ladder sums each player's best seed per mode and
  needs a score in every mode.
- **Playoff races** (stages and showcases) score on the event's
  `playoff_points` table (100/70/40/20 by default), by IGT, among the runs
  finished before the race ends; every other runner scores 0. When the first
  runner finishes, the server sets the race's `race_duration_minutes` so that
  it closes `playoff_cutoff_minutes` later, on the wall clock.

**Solo sessions** (`training_sessions.jsonl`) are runs on a seed outside any
race, from training pools. A user draws a seed they have not played yet, until
they have played the whole pool; after that any seed of the pool can come
again. A session's page is public and shows the full seed graph, and the other
runs on the same seed are public too (as ghosts).

## Who can see what, during a running race

What a runner can know about a seed and about the other runners, as the
platform works at the time of the export:

- **Web race page, as displayed.** A viewer who is not a participant sees no
  map while the late-join window is open or while `private_dag` is set. An
  active participant sees only their own progress. A participant who has
  finished or abandoned sees the whole map and every runner's path. The
  organizer, and casters (`casters.jsonl`) once the race is running, see the
  map.
- **Web race page, as transmitted.** Every browser that opens a race page,
  logged in or not, racing or not, receives the full seed graph and every
  participant's zone history over the page's WebSocket. The hiding above is
  done by the page itself, and the page exposes a console helper
  (`__debugDagFull()`) that displays the full map. Anyone with the page open
  can therefore know the whole graph and the other runners' paths and times.
- **In game.** The overlay leaderboard shows each runner's status, layer, IGT
  and deaths. On a synchronous race, the mod receives every runner's live
  state, current zone included. On an asynchronous race, it receives the other
  runners "projected" to the viewer's own IGT: each appears where their own
  run was when their IGT matched the viewer's. Zones appear only in the mod's
  debug panel, which lists every participant's current zone; its hotkey is
  unset by default and can be set in the mod's local config file.
- **Chat.** Each race has two channels. `participants` is readable by users
  with a role in the race (participant, organizer, caster) and by admins.
  `public` is closed during `setup` and for active racers; it opens to a
  participant once they finish or abandon, to other viewers once the
  late-join window has closed, and to everyone once the race is finished.
  Messages with no `user_id` are system messages (joins, finishes, starts).
- **Outside the platform.** Runners often stream on Twitch. Streams and VODs
  are not in the data.

## Clocks and in-game time

- **Server clock.** `created_at`, `started_at`, `finished_at`,
  `last_igt_change_at`, `last_seen` and chat timestamps come from the server.
- **Client clock.** `zone_history[].message_id` comes from the player's PC.
  When the mod starts, which happens when the game process starts, it seeds a
  counter with the PC's wall clock in milliseconds since the Unix epoch. The
  counter then increases by one for each event message the mod sends (fog
  traversal or zone query). Ids from one game process therefore sit close
  together, and a new game process starts from a new, much larger base. The PC
  clock can be off from the server's.
- **IGT.** Elden Ring's timer advances at 0.96 times real time, and only while
  a save is loaded. The mod corrects the game's framerate-dependent rounding
  and holds the timer still during black loading fades (see Changes over time
  for when). For continuous play, elapsed IGT is therefore about 0.96 times
  the wall time, minus loading fades and time spent at the title menu.
- **Quit-outs** (quit to title, reload the save) are allowed. On the reload
  after a quit-out detected during a running race or a solo session, the mod
  adds a penalty to the timer (`quit_out_penalty_ms`, 2000 ms by default).
- **Reloads and other saves.** Within one game process, the mod classifies a
  reload by what the IGT does. A drop of less than 60 s is a quit-out (penalty
  above). A larger drop is taken as a backup restore or another save, with no
  penalty. A forward jump of more than 10 s is taken as a wrong save, and race
  interaction is frozen until the race save is back. A new game process has no
  memory of the IGT before it.
- **Server checks.** On races, the server rejects gameplay messages whose IGT
  runs ahead of the wall clock elapsed since `last_igt_change_at` by more than
  60 s; solo sessions have no such check. The server stores a participant's
  `igt_ms` as the highest value reported.

## Changes over time

The history spans several versions of the mod and of the seed generator. Each
seed's pack carries the mod of its time. `seeds.created_at` is when the server
registered the seed, shortly after its batch was generated, so it bounds the
generation date from above and tells, roughly, with which settings the seed
was made. Changes that affect the data, as of the export:

| date       | change                                                                                                                         |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------ |
| 2026-05-28 | weapons start being tracked; quit-outs become allowed by the rules                                                             |
| 2026-06-21 | bosses drop a much wider choice of weapons, in every pool                                                                      |
| 2026-07-26 | quit-out penalty                                                                                                               |
| 2026-07-30 | every pool except the UWYG ones (`uwyg_rush`, later `uwyg_major`) goes back to a narrower, curated choice of boss weapon drops |
| 2026-08-01 | equipped weapons are upgraded automatically to the seed's level                                                                |
| 2026-08-10 | `deathless` race option                                                                                                        |
| 2026-08-12 | framerate-independent IGT, and IGT frozen during black loading fades                                                           |
| 2026-08-29 | poison, blood and occult weapons tracked (earlier, they were silently missing from `weapons`)                                  |
| 2026-09-18 | bosses no longer drop weapons in part of the pools (see below)                                                                 |

Since 2026-09-18 (fully from about 11:30 UTC that day; seeds generated
earlier that morning could still get a few), seeds generated in `standard`,
`sprint` and the pools built on them (`boss_rush`, `boss_shuffle`,
`linear_route`, `tarnished`, and their training versions) have no weapons
among boss drops. The other pools (`chill`, `expedition`, `hardcore` and its
variants, `uwyg_rush`, `uwyg_major`, and their training versions) still drop
weapons from bosses. In every pool, weapons can still come from items found in
the world and from ordinary enemies' drops. What counts is when the seed was
generated, not the race's date: a race can run on a seed generated earlier.
These settings were set for the season-one event and can change again.

## Files

### users.jsonl

| field            | meaning                                                                                                                              |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `id`             | user id                                                                                                                              |
| `name`           | pseudonym (`player_0001` is the oldest account), the Twitch login when names are not pseudonymized, or the login of a system account |
| `display_name`   | Twitch display name; present only when names are not pseudonymized                                                                   |
| `twitch_id_rank` | rank of the user's Twitch account id among all users, 1 for the smallest; Twitch hands ids out in increasing order over time         |
| `twitch_id`      | Twitch's numeric account id, in place of the rank when names are not pseudonymized                                                   |
| `role`           | `user`, `organizer`, `admin`, `system`; new accounts get `organizer` by default, so it says little                                   |
| `created_at`     | first login on the platform (logins go through Twitch)                                                                               |
| `last_seen`      | last login, or last authenticated connection to a race page                                                                          |
| `timezone`       | IANA timezone the web app reported from the user's browser, last value seen                                                          |
| `locale`         | UI language                                                                                                                          |
| `banned_at`      | when an admin banned the account; null when it is not banned (lifting a ban clears it, with no trace left)                           |
| `ban_reason`     | the reason the admin gave, shown to the user; names replaced as in chat                                                              |

### races.jsonl

| field                                                | meaning                                                                                                         |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `id`, `name`, `organizer_id`, `seed_id`              | identity; `name` is free text chosen by the organizer                                                           |
| `status`                                             | `setup`, `running`, `finished`                                                                                  |
| `created_at`, `scheduled_at`                         | creation, announced start                                                                                       |
| `started_at`                                         | effective start (after the countdown); asynchronous races start once and stay open                              |
| `seeds_released_at`                                  | when participants could download their packs                                                                    |
| `finished_at`                                        | when the race closed                                                                                            |
| `is_public`, `open_registration`, `max_participants` | listing and registration settings                                                                               |
| `late_join_window_minutes`, `race_duration_minutes`  | see Race lifecycle; on playoff races the first finish rewrites `race_duration_minutes`                          |
| `custom_rules`                                       | rules text shown to players                                                                                     |
| `private_dag`                                        | map hidden from spectators until the race finishes (display only, see Who can see what)                         |
| `deathless`                                          | the first death eliminates the runner (detected through the game's death counter)                               |
| `daily_date`                                         | set on daily seeds                                                                                              |
| `exclude_from_stats`                                 | kept out of the platform's statistics                                                                           |
| `event_id`, `event_slot`                             | attachment to an event: `qualifier:<mode>:<n>`, `<stage>:<n>` (playoffs), `<showcase>:<n>` (exhibition matches) |
| `config`                                             | race-level settings                                                                                             |
| `is_target`                                          | under review: started at or after `since`, or attached to the event under review                                |

### participants.jsonl

One participation of one user in one race.

| field                            | meaning                                                                                                                                                                                                                              |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `id`, `race_id`, `user_id`       | identity                                                                                                                                                                                                                             |
| `status`                         | `registered`, `ready`, `playing`, `finished`, `abandoned`, `disqualified`                                                                                                                                                            |
| `created_at`                     | when the user joined (self-join, invitation accepted, added by the organizer, or race creation for an organizer who races)                                                                                                           |
| `finished_at`                    | server time the finish was recorded                                                                                                                                                                                                  |
| `igt_ms`                         | highest IGT reported; the final IGT for a finished run                                                                                                                                                                               |
| `death_count`                    | the game's death counter as last reported; it can go down after a backup restore, unlike the per-entry `deaths`                                                                                                                      |
| `current_layer`                  | deepest layer reached (never decreases); set to the seed's `total_layers` on finish                                                                                                                                                  |
| `current_zone`                   | last known node                                                                                                                                                                                                                      |
| `last_igt_change_at`             | server time of the last IGT change                                                                                                                                                                                                   |
| `layer_entry_igts`               | `{layer: IGT at first entry}`                                                                                                                                                                                                        |
| `zone_history`                   | the run, see below                                                                                                                                                                                                                   |
| `debug_flags`                    | game debug flags (the practice tool and TarnishedTool switches: one shot, no death, infinite stamina...) the mod read as on during the race: `{name: {igt_ms, node_id, detected_at}}`, the first observation of each; null when none |
| `disqualified_at`                | when the race staff (its organizer or an admin) disqualified the runner; null otherwise. The run fields above are kept as they were; cancelling the disqualification clears this and the next two fields, with no trace left         |
| `disqualification_reason`        | the reason the staff gave, shown to the runner, the organizer and admins; names replaced as in chat                                                                                                                                  |
| `status_before_disqualification` | the status the runner had when disqualified, restored if the disqualification is cancelled                                                                                                                                           |
| `is_target`                      | the race is under review                                                                                                                                                                                                             |

### zone_history entries

In arrival order. The finish itself adds no entry: the last entry of a
finished run is its arrival in the final node. Fields:

- `node_id`: a node of the seed graph. Node ids are cluster ids, stable across
  seeds: the name of the cluster's main zone plus a short hash of the set of
  zones it groups. The same id means the same cluster in every seed. Two ids
  with the same main zone and a different hash are different clusters (one
  groups more zones than the other). Which boss stands in a cluster depends on
  the seed (`boss_name` in the seed graph).
- `type`:
  - `spawn`: added by the server at the run's first status report, at the
    seed's start node, with `igt_ms` 0 and no `message_id`;
  - `fog`: a fog gate traversal, detected through an event flag; the entry
    into `node_id`;
  - `backtrack`: a change of position without a fog traversal (death and
    respawn, teleport, warp, quit-out and reload); `node_id` is where the
    player now is.
- `igt_ms`: the IGT reported with that event.
- `message_id`: see Clocks. Absent on `spawn` entries.
- `deaths`: deaths while at this node, added to the most recent entry for that
  node.
- `weapons`: a list of `{ids, ticks}`. While this entry is current, the mod
  reports once per status update (about once per second) the weapon in the
  active slot of each hand. `ids` is the combination (one or two weapon ids),
  `ticks` the number of reports with it. Staves, seals, shields and torches are
  not tracked. Only equipped weapons are reported: inventory and pickups are
  not. A weapon id is `base + affinity * 100 + level`, where `base` is a
  multiple of 10000 (names in `weapons.json`), `affinity` is 0 standard, 1
  heavy, 2 keen, 3 quality, 4 fire, 5 flame art, 6 lightning, 7 sacred, 8
  magic, 9 cold, 10 poison, 11 blood, 12 occult, and `level` is the upgrade
  level (0 to 25, somber weapons 0 to 10).

### training_sessions.jsonl

Solo sessions (see The platform): `id`, `user_id`, `seed_id`, `status`
(`active`, `finished`, `abandoned`, `cancelled`), `created_at`,
`finished_at`, `igt_ms`, `death_count`, `current_zone`, `zone_history` (same
format), and `is_target` (created at or after `since`).

### seeds.jsonl

`id`, `seed_number`, `pool_name`, `total_layers`, `difficulty_score`,
`status`, `created_at` (when the server registered the seed, see Changes over
time), `graph_is_full`, `graph`.

For the seeds of races under review, `graph` is the full seed graph:

- `nodes`: `{node_id: {type, display_name, zones, layer, tier, boss_name,
randomized_bosses, exits, entrances, ...}}`. `type` is one of `start`,
  `major_boss`, `boss_arena`, `mini_dungeon`, `legacy_dungeon`, `final_boss`
  and a few others. `boss_name` is the boss placed there in this seed, and
  `randomized_bosses`, when present, lists the randomized bosses placed in the
  node. Each exit is `{fog_id, text, to, ...}`, where `text` describes where
  the fog gate stands and `to` is the node it leads to.
- `edges`: `[{from, to}]`.
- `care_package`: items every runner receives at the start (`type` 0 weapon,
  1 armor, 2 talisman, 3 goods such as sorceries, incantations and crystal
  tears, 4 ash of war).
- `weapon_upgrade`: upgrade level given to the care package's weapons (somber
  weapons get `floor(level / 2.5)`).
- `starting_goods`, `starting_runes` and similar starting resources,
  `boss_names`, `enemy_assignments`, `options`.

Starting class loadouts are set by the randomizer. They are not in the data,
except in the pools whose graphs carry a `class_loadout`.

For the other seeds (history races and all solo sessions), `graph` keeps only
the structure: `total_layers`, `nodes` (`type`, `layer`, `tier`,
`display_name`, `zones`, `boss_name`, `randomized_bosses`), `edges`,
`care_package`, `weapon_upgrade`.

### Other files

- `pools.jsonl`: `name`, `enabled`, `config`.
- `casters.jsonl`: `race_id`, `user_id` of each race's casters.
- `chat_messages.jsonl`: chat of the races under review only: `id`,
  `race_id`, `channel` (`participants` or `public`), `user_id` (null for
  system messages), `message`, `reply_to_id`, `created_at`. Messages are free
  text (see the note on pseudonyms at the top).
- `events.jsonl`: `id`, `slug`, `name`, `starts_at`, `qualifier_ends_at`,
  `ends_at`, `newcomer_threshold`, `config`.
- `event_signups.jsonl`: `event_id`, `user_id`, `created_at` (a runner saying
  they take part; running a qualifier seed enters them anyway).
- `weapons.json`: `{base_id: {name, wep_type}}`.

## Not in the data

- Server logs: rejected messages, quit-out and reload detections, wrong-save
  errors, WebSocket connections and disconnections.
- Streams and VODs.
- Server-side timestamps per zone history entry (only the client-side
  `message_id`).
- Character level, stats, health, damage dealt or taken, inventory, pickups,
  the starting class chosen.
- The exact version of the mod and of the game each run used (see Changes over
  time for what `seeds.created_at` tells).
- Runs wiped by a reset or a reroll.
