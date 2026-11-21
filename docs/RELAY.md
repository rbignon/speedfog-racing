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
- Every member's save must be fresh: at their first report after the start, the
  team's first holder and each waiting teammate alike, its IGT must not exceed 60
  seconds (`MAX_FRESH_IGT_MS`). A runner who takes the baton later plays on the
  team's IGT, which the take gives their game.
- The relay wire contract starts at protocol 1.19 (`RELAY_MIN_PROTOCOL`).

Relay races are off unless the server setting `RELAY_RACES_ENABLED` is true
(`settings.relay_races_enabled`, false by default, listed in both `.env.example`
files): until the shipped mod speaks protocol 1.19, nobody could join one. While off,
`POST /api/races` refuses a `relay_team_size` (400 `Relay races are not available
yet`) and `GET /api/pools` reports `relay_available` 0 for every pool. Races already
created stay as they are.

## Seeds

A relay seed carries a top-level `relay` object in its `graph.json` (generator
version 4.15), written when the relay plugin is enabled. The pools enable it in
`tools/pools/_base.toml`. The block holds the event flags the mod and the server
share:

| Key                | Value      | Meaning                                                                                                                                                           |
| ------------------ | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `lock_flag`        | 1050290500 | while ON, no graph warp takes the player and the Chapel map refuses fast travel                                                                                   |
| `chapel_warp_flag` | 1050290501 | raised, it warps the player to the Chapel grace and clears itself                                                                                                 |
| `warp_flag_base`   | 1050290510 | `warp_flag_base + n`, raised, warps the player to the entrance of connection n and clears itself; n is the connection's zone-tracking flag minus `zone_flag_base` |
| `warp_flag_count`  | 490        | how many warp flags follow the base                                                                                                                               |
| `zone_flag_base`   | 1050294000 | first of the zone-tracking flags                                                                                                                                  |

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
seeds, the ones a relay race can draw (0 everywhere while relay races are off, see
"Rules"). Seeds generated before the plugin was enabled carry no block and never
count; regenerate a pool to get relay seeds.

## Teams

A relay race has `Race.relay_team_size` (2 to 6, `RELAY_TEAM_SIZE_MIN` and
`RELAY_TEAM_SIZE_MAX`; null on every other race, `Race.is_relay`) and
`Race.relay_runners_create_teams` (default true). Its teams are `RelayTeam` rows
(`Race.relay_teams`, selectin-loaded with the race, in `created_at` order; the mod
handlers' 1 Hz loads leave it out with `raiseload`, so a solo heartbeat pays no query
for it). A team
carries the progress a solo participant carries on its own row (zone, layer, IGT,
deaths, zone history, layer entry IGTs), plus the baton (`holder_id`,
`holder_offline_since`, `baton_free`), `first_runner_id`, `entry_flag_id`, the last
`character_state` with its IGT, and `placeholder` (created by the organizer, kept
while empty). Names are at most 40 characters, `Team {n}` by default
(`default_team_name`: the lowest n at or above the team count plus one that is free).

`Participant.relay_team_id` is the runner's team, `relay_zones` the zones counted
for them and `relay_validated` the fresh-save gate. The three keys between
participants and teams (`participants.relay_team_id`, `relay_teams.first_runner_id`,
`relay_teams.holder_id`) are `ON DELETE SET NULL` and form a cycle, so the two
keys towards participants are created after both tables (`use_alter`).
`RelayTeam.members` is read only and loaded only by an explicit `selectinload`.

The leaderboard ranks teams. `relay_rows` turns the teams and the participants
into `RelayTeamRow`s, shaped like a participant (`id`, `status`, `current_zone`,
`current_layer`, `igt_ms`, `death_count`, `color_index`, `zone_history`,
`layer_entry_igts`, all read from the team) with the `members`, the `cap` and the
`holder`. An empty team is a row only in setup. `leaderboard_entries` returns the
participants of a solo race and the team rows of a relay race.
`reset_relay_team` puts a team back to a fresh one (progress, baton and state
cleared, status registered; name, color, placeholder and `first_runner_id` kept).

### Who may do what

Every route below works on a relay race in SETUP only (a late-join window never
exists on a relay race). A runner is never registered without a team: `join_race`,
`accept_invite`, the organizer's `add_participant` and the team routes all place the
runner through `place_in_team` (`api/relay_teams.py`), and every removal (`leave`,
the organizer's removal) goes through `vacate_team`. `POST /join`, the accept route
and `add_participant` take `{relay_team_id}` or `{create_team: true}`; an invite made
for an unknown user carries none, the invitee picks on the invite page.

- Joining is joining a team with a free slot (`relay_team_size`) or creating one. A
  runner already in a team who joins another is moved, in one step, and is not
  registered twice. Leaving one's team is leaving the race.
- A team a runner created disappears when it empties; a placeholder (created by the
  organizer) stays empty until the organizer deletes it, which needs it empty.
- When `relay_runners_create_teams` is off, runners only join the organizer's
  teams; the organizer may still create teams and move runners.
- With open registration, `max_participants` counts runners, not teams: a runner
  creating a team on a full race is refused with 409 `Race is full`.
- A leaving member who was `first_runner_id` clears it (null means the first member
  registered). A new team takes the next color of the palette (highest plus one) and
  its members take the team color.
- Members and the organizer rename a team and choose its first runner; the first
  runner must be a member.
- Placement locks the team rows it decides on (`SELECT ... FOR UPDATE`, ascending id,
  so a move locks the target and the team left in one order) and counts the members
  after the lock: two runners cannot both take the last slot, and a team deleted
  while someone joins it answers 404 instead of leaving them without a team. Team
  deletion and `vacate_team` take the same lock.
- Every change ends like `join_race`: the leaderboard and the race state are broadcast.

| Case                                                          | Answer                                          |
| ------------------------------------------------------------- | ----------------------------------------------- |
| Not a relay race                                              | 400 `Not a relay race`                          |
| Race not in SETUP                                             | 400 `Teams can only be changed in SETUP status` |
| Relay join without a choice                                   | 400 `Pick a team to join a relay race`          |
| Unknown team, or a team of another race                       | 404                                             |
| Team full                                                     | 409 `Team is full`                              |
| Already in that team                                          | 409                                             |
| Runner creating a team while `relay_runners_create_teams` off | 403                                             |
| Rename or first-runner change by a non-member, non-organizer  | 403                                             |
| `first_runner_id` not a member                                | 400                                             |
| Delete of a team with members                                 | 409 `Team has members`                          |
| Organizer-only route by someone else                          | 403                                             |
| Blank name, or longer than 40 characters                      | 422                                             |

## Start

`POST /races/{id}/start` on a relay race replaces the participant minimum by `relay_start_error` (400 with its text), for every role, admins included: late join is excluded from relay races, and a lone tester uses the bot.

- A team counts when it has at least one member; teams without member are ignored.
- At least 2 teams that count, otherwise `At least 2 teams are required to start a relay race`.
- Each such team needs at least 2 READY members, otherwise `<team name> needs at least 2 ready runners`.

`prepare_relay_start` then fixes the teams: a member who is not READY is set ABANDONED (disqualified members keep their status). They stay attached to their team, so nobody is without one, and `team_cap` computes the cap on the members present. Each started team becomes READY and its baton goes to `first_runner_id` when that member is READY, else to its first READY member by `created_at`. A holder whose mod is not connected at the start is stamped offline from the race's `started_at` (`holder_offline_since`), the countdown's end: the 60 s wait starts with the race, and reads 60 through the countdown. After the start broadcasts, every connected member's mod gets a `relay_update` (`send_row_relay_updates`, team by team): its `holder_id`, its own `role`, `team_status` READY, and for a member left out its own `members[].status` abandoned.

A reset (`reset_race`) calls `reset_relay_race`: every team goes through `reset_relay_team` and every member gets `relay_zones = 0` and `relay_validated = False` (the left-out members return to REGISTERED with the other participants). Names, colors, placeholders and `first_runner_id` survive, so the setup choices are kept. A seed re-roll calls it too; it only ever happens in setup, where the teams are already fresh.

## Baton

What a mod is told about its team lives in `RelayInfo` (`websocket/race/relay.py`, wire shapes in `PROTOCOL.md`, protocol 1.19). It is sent in `auth_ok` and again, one message per connected member with its own `role` and `gates_locked`, by `send_relay_updates`. `auth_ok` goes out before the socket is registered, so its `RelayInfo` reads the runner as the registration leaves them: connected (`members[].online`, and `holder_online` for a returning holder) and not ready. A relay race refuses a mod below `RELAY_MIN_PROTOCOL` (1.19) at auth with `RELAY_OLD_MOD_MESSAGE`; other races still accept a 1.18 mod.

- Role: `holder` only for the team's holder while the baton is not free. When `baton_free` is set the nominal holder reads `waiting` with `baton_free_in_s: 0`, like everyone else.
- `baton_free_in_s` (`services/relay.py`): 0 when `baton_free` is set or there is no holder; null while the holder is connected; otherwise `RELAY_OFFLINE_WAIT_S` (60) minus the seconds since `holder_offline_since`, kept between 0 and 60 (a stamp at the race start is in the future during the countdown). A holder absent with no stamp yet (its socket just gone, before its disconnect is recorded) reads the whole 60: the rule is 60 seconds of absence, always.
- `gates_locked`: a holder whose `relay_zones` reached the team's cap.
- `zone_name`: the node of `entry_flag_id` in the graph's `event_map`, else the start node.
- Readiness: `RaceRoom.relay_ready` holds the members loaded at the Chapel with their lock raised. Leaderboard rows and `RelayInfo.members` both read it (`ready` is false for a member whose mod is not connected). It goes with the member's current socket: a disconnect, an eviction after a failed send or a replacement by a newer socket drops the member from it, and the mod sends `relay_ready` again after every `auth_ok`.

### Operations

`RelayModHandler` hands the five baton messages to the operations of
`websocket/race/relay.py`. A payload that does not parse (its pydantic model, the
`CharacterState` bounds: list lengths, and every integer non-negative, at most
2^31 - 1, an item id at most 2^32 - 1; an IGT out of range) is dropped, so a stored
state always fits the mod's types: a team replays it at every take. A refused request gets a
`relay_refused` to the asker, the first matching row winning (codes in `RelayRefusal`,
each with its `RELAY_REFUSAL_MESSAGES` text):

| Request                 | Refusals, in order                                                                                                                                                                                                                                                                                                                               |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `relay_handoff_request` | Race not running, in its countdown, or team neither ready nor playing: `busy`. A handoff in flight (not expired): `busy`. Sender not the holder (`holds_baton`): `not_holder`. Target not a teammate (or the sender), out, not connected or not ready: `target_unavailable`. Not validated: `not_validated`. At or over the cap: `target_at_cap` |
| `relay_take_request`    | The same two `busy`. Baton not free (`baton_is_free`): `holder_online`. Asker out: `target_unavailable`. Not validated: `not_validated`. Not ready: `not_ready`. At or over the cap: `at_cap`                                                                                                                                                    |

`receive_refusal` (`services/relay.py`) holds the member checks of both rows. The
nominal holder of a free baton reads `waiting` and may take it like anyone; the flip
then goes back to them.

- **Handoff accepted**: a handoff in phase `release` (a `PendingHandoff` in
  `RaceRoom.relay_pending`), and `relay_release {handoff_id, to_name}` to the holder.
- **`relay_state` with that `handoff_id`**, in time, from the giver who still holds the
  baton: the state is stored (below), then the baton flips to the target, unless the
  target is out by then.
- **`relay_state` with `handoff_id` null** from the holder: a checkpoint, stored the
  same way, no flip, no answer. The mod sends one at each zone entry, so a takeover
  after a crash has something recent.
- **Any other `relay_state`** (an expired or unknown handoff, or not from the holder)
  flips nothing. From the holder the state is still kept as a checkpoint. The sender
  gets a `relay_update`, which tells a giver who already went back to the Chapel that it
  still holds the baton.
- **Stored**: `character_state` (the parsed `CharacterState`) and
  `character_state_igt_ms`, the team IGT once raised to the reported IGT. A state
  whose IGT the wrong-save guard refuses (`is_igt_plausible` against the team's
  `igt_ms` and `last_igt_change_at`, or the race's `started_at` while the team has no
  such stamp, so the forward check is never off; the holder's `status_update`
  judgment) is never kept, and does not raise the team IGT: it may come from another
  save, and the next receiver would get it. As a checkpoint it is dropped (the
  previous one stays); as the answer to a release it flips nothing: the handoff is
  dropped, the holder stays holder and gets a `relay_update`.
- **Only from a PLAYING team**: a team still READY (the race runs, its first holder
  has not reported yet) has not passed its fresh-save gate, so its holder may sit on
  an old save. Nothing of its `relay_state` is kept and the team IGT stays 0, but its
  answer to a release still flips the baton: the receiver gets `state: null` and
  `igt_ms: 0`, so its first report passes the team's gate and the team plays.
- **Take accepted**: the baton flips to the asker with the stored state (null before
  any checkpoint) and the team's `igt_ms`, the last IGT received.
- **An absent holder with no stamp**: a take request that finds the holder's mod not
  connected and no `holder_offline_since` (the socket is gone, by a disconnect or an
  eviction, and its disconnect hook has not run yet) stamps it now, under the locks,
  and is refused with `holder_online`; the team gets a `relay_update`, so its mods
  count the 60 s down from then.
- **Flip**: `holder_id` is the receiver, `holder_offline_since` cleared, `baton_free`
  false; a handoff in phase `take`, its timer started with it before the commit (a
  failure after the commit still leaves a take that expires); `relay_take`
  (`handoff_id`, `state`, `igt_ms`, `defeat_flags`, `warp_flag`, `zone_name`) to the
  receiver; `relay_update` to the team, whose `role: waiting` is what makes the
  giver's mod lock and go to the Chapel. A receiver whose mod is no longer connected
  gets a free baton at once (`baton_free`), and no take is awaited from them.
- **Before `relay_taken`**: from the flip until its acknowledgement, the receiver's
  game still carries its own save's IGT and deaths, so the progress gate hears it as
  a waiting runner (`awaiting_take`): its `event_flag` and `zone_query` are
  acknowledged and recorded nowhere, its `status_update` is neither judged nor
  applied, no row is broadcast. The awaited take is registered before the flip
  commits, so no message slips in between. The mod sends no progress between
  `relay_take` and `relay_taken`. A receiver whose mod reconnects while its take is
  awaited (its game crashed, its socket dropped) gets the same `relay_take` again
  (`PendingHandoff.take`, same `handoff_id`, applied once by the mod) after its
  `auth_ok`, just before the team's `relay_update`, even once the timer fired: its `relay_taken` then takes the free baton
  back as a late one does. The awaited take lives in the room's memory only: after a
  server restart during a pending take it is lost, with its 30 s timer, so the
  receiver is heard as the holder as soon as it reconnects and its late `relay_taken`
  is ignored.
- **`relay_taken`** with the pending id, from its receiver: the handoff is over (its
  timer cancelled), `relay_update` to the team and a leaderboard broadcast. Late (the
  timer fired and nobody took the baton since), it also clears `baton_free`: the
  receiver plays on.
- **Timer**: a take still pending after 30 s sets `baton_free` and sends
  `relay_update`: any teammate under their cap, the giver and the receiver included,
  may take it. It does so only while the receiver still holds the baton and the baton
  can still move (race running, team ready or playing); closing the room (a reset or a
  deletion) cancels it. A release not answered in 15 s is dropped at the next request
  or by its own expiry check: the holder simply stays holder.
- **`relay_state` before `relay_taken`**: a receiver whose take is pending is not heard
  there either: its state is not kept and the team IGT does not move.
- **`relay_ready {ready}`** adds the sender to `RaceRoom.relay_ready` (while its mod is
  connected) or removes it, then `relay_update` when that changed. Readiness goes with
  the member's current socket: a disconnect, an eviction after a failed send, or a
  replacement by a newer socket removes it, and the mod reports it again.
- **Connections** (`member_connection_changed`): when the holder's mod disconnects,
  `holder_offline_since` is set to now and their pending release dropped (the mods
  count the 60 s down from `baton_free_in_s`); when it reconnects the stamp is
  cleared. Any member still in the race gets the same stamp on their own row
  (`last_igt_change_at`, the 30 minute offline rule of "Lifecycle"). Any member's
  arrival or departure sends the team a `relay_update` (`online`, `holder_online`), and
  a receiver whose take is awaited gets it again first (above). A returning ex-holder
  authenticates as `waiting`. The disconnect of a socket that a newer one replaced
  changes nothing.

| Duration | Constant                  | Meaning                                                        |
| -------- | ------------------------- | -------------------------------------------------------------- |
| 60 s     | `RELAY_OFFLINE_WAIT_S`    | An offline holder keeps the baton that long                    |
| 15 s     | `RELAY_RELEASE_TIMEOUT_S` | The holder answers `relay_release` with its state              |
| 30 s     | `RELAY_TAKE_TIMEOUT_S`    | The receiver acknowledges `relay_take`, else the baton is free |

### Where the receiver lands

- `warp_flag` (`relay_warp_flag`): `warp_flag_base + (entry_flag_id - zone_flag_base)`,
  the entrance of the last zone the team entered through a fog gate. Backtracks never
  move `entry_flag_id`, so a holder who went back hands over the furthest zone.
  `zone_name` names it. Both are null before the team's first gate: the receiver is
  unlocked at the Chapel, with no warp.
- `defeat_flags` (`team_defeat_flags`): the defeat flag of every node the team's
  history marks killed, the current zone's included, sorted. On a takeover the state is
  the last checkpoint, but the flags come from the history: a boss killed after the
  checkpoint stays dead for the taker, and the runes it gave are lost.
- `igt_ms`: the team's IGT, which the receiver's game takes.
- Nobody at or over their cap receives the baton, the final zone included.

### Ordering

`RaceRoom.relay_lock` serializes the operations above (and the take timer) per race, in
memory. All but `relay_ready` read the team through `team_for_update`, which row-locks
it (`SELECT ... FOR UPDATE`, a no-op on SQLite); `set_ready` reads only the member's
team id, without a lock. The committing loads of the progress messages take the same
row lock ("Progress and guards"), so a flip and a progress write of one team are
ordered by the database. The lock order is always `relay_lock`, then the team row.
Teams and participants reference each other, and the ORM flushes a participant's
UPDATE before a team's, so a transaction that writes rows of both tables locks its
team rows explicitly first (`SELECT ... FOR UPDATE`), before it changes any member:

- one team through `team_for_update` or its twin `RelayModHandler._team_select`: the
  progress commits, `member_connection_changed`, `member_out` (every way out of
  "Lifecycle"), and `finish_team`'s committing load;
- a race's teams in ascending id through `lock_race_teams` (`services/relay.py`): the
  start (`prepare_relay_start`), a reset and a reroll (`reset_relay_race`), the forced
  end (`finalize_race`);
- the teams a placement touches, in ascending id (`_lock_teams` in
  `api/relay_teams.py`: joins, moves, leaving, team deletion);
- the restart (`stamp_offline_runners`) updates the teams in a statement before the one
  that updates the members.

Two such transactions therefore never wait on each other in opposite orders. A write to
one table only needs no order: a flip, a checkpoint and the take timer write the team, a
member's fresh-save validation writes the member (as an UPDATE guarded on the status it
read, so it never brings back a member who went out meanwhile).

## Cap

A runner may play `ceil(total_layers / active_members) + 1` zones (`relay_cap`),
`total_layers` being the seed's. `active_members` counts the team's members whose
status is neither abandoned nor disqualified (`is_active_member`); `team_cap` never
divides by zero (at least one member) and is recomputed when a member leaves.

Each zone counts for one runner, in `Participant.relay_zones`:

- A zone whose boss the server tracks (a defeat flag of `extract_boss_flags`)
  counts for the runner who kills that boss: each new kill adds one to the holder
  who reported it (`_on_boss_kill_recorded`), in the commit that stamps the kill,
  since a replay of the flag is a duplicate and could not count it again. A re-report
  is no new kill and counts nothing, including the defeat flags a handoff set on a
  receiver's game, which its mod reports again after a restart.
- The final boss counts for its killer (`finish_team`).
- Any other zone counts for the runner who exits it: when a fog gate reaches a layer
  the team never reached and the zone left (the history entry before the gate's)
  passes `counts_zone_on_exit` (no tracked boss, not the final boss).

When a holder's count reaches the team's cap, the `relay_update` that follows reads
`gates_locked: true` for them: they must hand off to leave the zone. The server
still records what a holder at or over the cap does, since it cannot undo a kill or
a traversal the game allowed: a capped holder who kills a boss ends one over the
cap, and the final boss is always accepted.

## Progress and guards

On a relay race the live messages (`race_state`, `leaderboard_update`, `player_update`,
and `auth_ok.participants`) carry one row per team, built by `relay_team_to_info`
from the `RelayTeamRow`s of `leaderboard_entries`; every broadcast of the leaderboard
passes those entries. The row shape is in `docs/PROTOCOL.md` ("Relay rows"). A
loader feeding these rows must not defer `RelayTeam.zone_history`.

`handle_mod_websocket` gives a relay race's mods a `RelayModHandler`
(`websocket/race/relay_mod.py`). Its entity for `status_update`, `event_flag` and
`zone_query` is the runner's `RelayTeam`, loaded with its members, so the shared
handlers move the team's zone, layer, IGT, history and deaths, and a `player_update`
is the team's row. Its 1 Hz load leaves out the race's teams (`raiseload`): they
carry every team's history. No progress load reads `character_state` (deferred).

- **Gate.** Only the runner who holds the baton is listened to (`holds_baton`: the
  holder while the baton is not free, the rule of `RelayInfo.role`). A `status_update`
  is first judged on a light, lock-free read of the team's baton (every member reports
  about once a second); the holder's then goes through the shared handler, whose load
  row-locks the team (`SELECT ... FOR UPDATE`) and checks the baton again before it
  commits. An `event_flag` or a `zone_query` is decided the same way: a runner the
  gate does not hear is acknowledged on the lock-free read (with the race's condition
  error, as the shared handler sends it), so a slow waiting client never holds its
  team's row for a send; the holder's is checked again in the locked load. A flip
  takes the same lock (Baton, "Ordering"), so progress from a runner who no longer
  holds the baton is never applied. A holder whose `relay_take` is still
  unacknowledged is heard as a waiting runner (`awaiting_take`, read from the room's
  memory, so the pre-read stays lock-free; Baton, "Before `relay_taken`"). Anyone
  else's `event_flag` and `zone_query` are acknowledged (the mod replays them until
  then) and recorded nowhere; their `status_update` only runs their own fresh-save
  gate, and no row is broadcast for it. The legacy `finished` message is ignored.
- **Fresh save for every member.** The team's first report, its first holder's,
  passes the team's gate (IGT at most 60 s, `MAX_FRESH_IGT_MS`): the team becomes
  PLAYING and that holder is validated. Any other member's first report once the
  race runs (countdown over) sets `relay_validated` and moves them from READY to
  PLAYING when its IGT is at most 60 s; above, they get `error` `fresh_save_required`
  and stay unvalidated. Once validated, a waiting runner's IGT is never judged. The
  seed check is the mod's (it compares its pack with `RaceInfo.seed_id`).
- **Wrong save.** `is_igt_plausible` judges the holder's IGT against the team's
  `igt_ms` and `last_igt_change_at`.
- **Deaths.** Each save counts its own deaths. A member's `death_count` holds the
  last raw count their mod reported as holder, stored in the commit that applies
  the report; the team's count moves by what the holder's counter moved
  (`team.death_count + reported - member.death_count`), so it carries on across a
  change of holder. When the member goes out, or the team ends, their row takes the
  team's count instead ("Lifecycle").
- **History.** Every entry the team's history gains carries `runner_id`, the
  holder's participant id. A fog gate stores its flag in `entry_flag_id`, the zone a
  handoff restarts (`RelayInfo.zone_name`); a backtrack seen through `zone_query`
  never changes it.
- **Per-save data.** The holder's debug flags land on their own row and alert the
  staff as on a solo race.
- **Reconnection.** A reconnecting holder gets the `zone_update` of the team's zone,
  a waiting runner none.
- **`relay_update`** goes to the team's connected mods whenever `RelayInfo` changes
  here: a member passes the fresh-save gate, the team's first report, each fog gate
  (`zone_name`, maybe a count), each counted kill (`members[].zones`,
  `gates_locked`), the finish (`team_status`); the baton operations send their own
  (Baton, "Operations").
- **Finish.** The holder's final boss flag runs `finish_team`, `handle_finished` on
  the team: FINISHED, `finished_at`, the layer set to the seed's total, the final
  boss counted for the holder, `copy_team_result` (status, IGT, finish time, deaths
  and layer onto the members still in, a disqualified team leaving them abandoned;
  never `zone_history`), the public line `{team name} has finished the race!`, then
  auto-finish and the same broadcasts, and a `relay_update` telling the team's mods
  their race is over. Once every team is finished or out, every participant row is
  terminal and the race finishes.

## Lifecycle

A member goes out alone: the team plays on without them, and is out only when nobody is
left in it. There is no automatic reassignment of the baton, ever.

| Way out                                               | Who              | The member                                                                                                      | Chat line (public unless noted)                                |
| ----------------------------------------------------- | ---------------- | --------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `POST /races/{id}/abandon`                            | the member       | REGISTERED, READY or PLAYING to ABANDONED                                                                       | `{name} has abandoned the race.`                               |
| `DELETE /races/{id}/participants/{pid}`, race RUNNING | organizer, admin | the same, the row kept in its team (400 `Cannot remove: current status is '<status>'` for a member already out) | `{name} has been removed from the race` (participants channel) |
| `POST /races/{id}/participants/{pid}/disqualify`      | organizer, admin | DISQUALIFIED as on a solo race; the team is out                                                                 | none                                                           |
| `POST /admin/users/{id}/ban`, race RUNNING            | admin            | the same disqualification ("Account banned"), unless already out by then; the mod is closed                     | none                                                           |
| Inactivity monitor, offline 30 minutes                | server           | PLAYING to ABANDONED                                                                                            | `{name} has abandoned the race due to inactivity.`             |
| Inactivity monitor, no-show                           | server           | REGISTERED or READY (never validated) 30 minutes into a race without `race_duration_minutes` to ABANDONED       | the same                                                       |
| Inactivity monitor, team IGT stale 30 minutes         | server           | the holder to ABANDONED                                                                                         | the same                                                       |

What a member going out does (`apply_member_out`, `services/relay.py`):

- Their row takes a snapshot of the team's progress at that moment: its IGT, deaths and
  layer (their own status kept, no finish time, never `zone_history`). Every member's row
  thus tells how far the team was when that runner's race ended; the members still in at
  the team's end get its final result instead (below). A member disqualified after they
  went out (an abandon, then a cheat found) keeps the snapshot of when they left: only a
  member who was still in takes one (`take_member_out` passes `snapshot`).
- A baton they held is free at once: no holder, `baton_free`, no 60 s wait. The team's
  `last_igt_change_at` restarts, so the free baton gets the whole 30 minutes before the
  team is out for inactivity.
- The cap is recomputed on the members still in (`team_cap`): every member's `cap` and
  the holder's `gates_locked` can move.
- The team is out (ABANDONED) once no member is left in. A disqualification puts it out
  at once (DISQUALIFIED), finished or not: what a cheater obtained reached the team.
- A team out gets `copy_team_result`: its members still in take its status, IGT, finish
  time, deaths and layer (a disqualified team leaves them ABANDONED; a member already out
  keeps their own snapshot). A team that was still in the race and goes out while the
  race runs gets the public line `{team name} is out.` (never twice, nor after the race
  finished).

Cancelling a disqualification (`DELETE /races/{id}/participants/{pid}/disqualify`) is
refused on a relay race, 400 `A disqualification on a relay race cannot be cancelled`: the
disqualification put the member's team out and their teammates still in ABANDONED, and
neither the team nor those rows can be restored consistently. A disqualification on a
relay race is final, even after a reset.

Inactivity (`services/inactivity_monitor.py`, `INACTIVITY_TIMEOUT`, every minute):

- A member's `last_igt_change_at` is unused on a relay race, so it holds since when their
  mod is offline: set at its disconnect, cleared at its connect
  (`member_connection_changed`). The PLAYING branch of `abandon_inactive_participants`
  thus abandons a member offline for 30 minutes, and its no-show branch a member who never
  validated. A connected waiting runner has no stamp and is never inactive: they wait by
  design.
- `abandon_stale_relay_teams` watches the team's IGT instead of the waiting runners': a
  team in the race (PLAYING, or READY with a stamp: its first holder never reported and
  went out) whose `last_igt_change_at` is older than 30 minutes has its holder
  abandoned, and a team with no holder (a free baton nobody took in 30 minutes) is out
  itself. A take restarts the stamp too (the flip), so a runner who takes the baton late
  in that window gets the whole 30 minutes for their first report.
- Each runner the monitor takes out is judged again under the locks (their mod may have
  come back), and its lines are posted there, the team's after the member's. Each relay
  operation runs on its own: one failing (a deadlock abort) is logged and the pass goes
  on, the solo abandons already committed included.

The operations are `member_out` and `take_member_out` (`websocket/race/relay.py`), for a
REST route or the monitor, which have no mod handler. `relay_section` holds the race
room's `relay_lock` when the race has a room; without one nobody is connected, so no
handoff is in flight and nobody is to be told, and the team row lock alone orders the
write (no room is created for it: nothing would drop it). The team is then read through
`team_for_update` in a session of the operation's own, so a route never decides on rows
its request session loaded before the lock (it reads the race again afterwards), the
change and its chat lines are committed together, and after the commit `after_member_out`
runs, still under the lock:

- a handoff in flight naming a member out is dropped: a release whose giver or target is
  out, a take whose receiver is out (its timer cancelled, the baton they held already
  free), and any handoff of a team that is out;
- the team's members who are out get the public chat (`set_participant_status`);
- the team's mods get a `relay_update` (`holder_id` null with `baton_free_in_s` 0, `cap`,
  `gates_locked`, `team_status`). A member out reads their own `members[].status`; a team
  finished or out reads `team_status`, and its mods lower their lock.

The routes then broadcast the leaderboard and the race state, and run the auto-finish
check, as for a solo abandon; the monitor's loop does the same per race.

**Forced end.** `finalize_race` (force-finish, hard close) first puts out every team
neither finished nor out (`abandon_team`: ABANDONED, its result copied onto its members),
its rows locked and read again before the participant sweep, and sends those teams' mods
a `relay_update`.

**Auto-finish** needs no rule of its own: once every team has finished or is out, every
participant row is terminal, and the race finishes.

**Restart.** No mod is connected when the server starts: `stamp_offline_runners`, called
once in the lifespan before the loops, stamps on every running relay race the holder of a
team still in the race with no `holder_offline_since` (the 60 s wait starts at the
restart) and every PLAYING member with no `last_igt_change_at` (their 30 minutes too). The
handoffs in flight lived in memory and are lost (Baton, "Before `relay_taken`").

## Exclusions

A relay race (`Race.relay_team_size` set) stays out of everything that assumes one runner per run. Each line names where it is enforced.

- Options: `race_items`, `deathless` and a late-join window are refused at creation (`CreateRaceRequest.validate_relay`) and on edit (`update_race`); a mode other than `normal` is refused at creation.
- Events: `admin_attach_race_to_event` refuses a relay race; dailies never carry the column, since the daily loop never sets it.
- Speedrun boards: `race_unranked_code` returns `relay` first (`RELAY_UNRANKED_REASON`), and `counts_on_boards_clause` excludes the race in SQL.
- Community statistics (zones, bosses, weapons, traits, profile stats): `counts_for_community_stats` excludes the race.
- Rewards: `grant_race_win_rewards` returns early on a relay race, and `check_finish_reward_milestones` counts finished participations through a join on `Race` that skips relay races.
- Calibration tools: the four SQL filters of `tools/extract_zone_times.py` and `tools/extract_boss_weights.py` add `r.relay_team_size IS NULL`.
- Ghosts: nothing to exclude. `Race.projects_ghosts` is only true for dailies and qualifiers, which a relay race never is, and training ghosts read `TrainingSession` alone.

## Outside the live page

Pages that read participants (the finished-race page, race cards, profiles, the Discord notification) keep doing so: when a team finishes or is out, its result is copied onto each member's participant row (see Lifecycle). A member who left early keeps a snapshot of the team's progress at that moment, so member rows of one team can differ. Anything ranked or counted is therefore computed on the team, never by assuming the member rows are equal.

- Placements (`compute_race_stats`): a finished member is ranked by the result of their `RelayTeam` (IGT, then finish time), and teammates share the placement. The number of starters counts a team once (`coalesce(relay_team_id, id)` with IGT above 0), not its runners.
- A member who went out before the team's end did not finish the race: whatever the team did afterwards, their row has no placement and reads DNF with their own snapshot (IGT, layer). A placement is for the runners who were in the race when their team finished; members still in carry the team's placement.
- Race card previews (`race_response`): finished members are ordered by team result and carry their team's placement; a member who left early is not finished and has none.
- Discord podium (`build_podium(participants, teams)`): with teams, one entry per finished team, named after the team, with the team's IGT; at most three.
- Profile activity: `RaceParticipantActivity.relay_team_name` is the team the user played for (`Participant.relay_team`, a read-only relationship loaded with the profile query, heavy team columns deferred). The activity list shows it before the placement as plain text. Counting is unchanged: a relay race counts for nothing outside itself.

## Web

Race creation (`/race/new`): Relay is a fourth tile of the Format field, next to Classic, Elden Drift and Speedrun (formats exclude each other, so relay needs no handling of race items or speedrun). Its panel holds "Teams of [n]" (2 to 6, default 3) and the cap sentence of `relayCapSentence` in `web/src/lib/relay.ts`, which applies the server's formula (`ceil(total_layers / team_size) + 1`) to the selected pool's `layers_count` ("30 zones, teams of 3: 11 zones max per runner."). A pool's seeds may differ in layer count (the category key `<pool>@<layers>` exists for that), so the sentence is the pool's nominal count, and the race's own `relay_cap` is the figure that binds. The sentence is omitted when the pool has no `layers_count`. The game mode tabs count `PoolInfo.relay_available` (AVAILABLE plus SEEN seeds carrying the relay block). While relay races are off on the server every count is 0: the Relay tile stays, but no game mode can be picked, the page reads "No relay seed in any game mode yet." and Create stays disabled (the pools carry no reason, so the text cannot tell that case apart). With relay on, the late joiners and deathless options leave the advanced options (the request sends `late_join_window_minutes: null` and `deathless: false`), a line under the trigger says so, the registration hint says players pick a team, and the open registration maximum is labelled "max runners". `createRace` takes the team size as its last parameter (`relay_team_size`).

Setup page (`/race/[id]`): the participant list of the left sidebar becomes `RelayTeamList`, grouped by team in the server's order. A team has a header (color, name, members / size, "Edit" for its members and the organizer, "Delete" for the organizer on an empty team), a "Starts: <runner>" line (the chosen first runner, else the first member; "Change" opens a select of the members) and the usual `ParticipantCard` per member. A team with a free slot ends with a dashed button, "+ Join this team" for a visitor and "Move to this team" for a runner of another team (`teamSlotAction`); "+ Create a team" closes the list (always for the organizer, who adds an empty placeholder team; for a runner or visitor who can register only while "Runners can create teams" is on). That checkbox is the organizer's, and when it is off the header maximum counts the teams' seats (`relayCapacity`) and the race is full when they are. The cross of a card (organizer) opens a menu: "Move to <team>" for each team with a free slot, and "Remove from race". The map slot's join button reads "Pick a team to join" and scrolls to the list. The start button follows `relayStartBlocker` (the server's `relay_start_error` texts), for every role.

The team list follows other users' changes by re-fetching the REST race each time `raceStore.participants` is replaced while a relay race is in setup (every team change makes the server broadcast the leaderboard rows; the newest answer wins when fetches overlap); a member's live status comes from the `relay_members` of the team rows. The runner's own changes replace the race with the answer of the REST call (`onChanged`). `joinRace`, `acceptInvite` and `addParticipant` take an optional team choice (`{relay_team_id}` or `{create_team: true}`): the invite page and the organizer's add-participant search show a select of the teams with a free slot plus "New team" (`teamChoiceOptions`; an invite page offers it only while runners may create teams). The five team routes are `createRelayTeam`, `updateRelayTeam`, `deleteRelayTeam`, `joinRelayTeam` and `moveRelayParticipant` in `web/src/lib/api.ts`.

Live leaderboard (`Leaderboard.svelte`, race page and results): a relay race's rows are its teams (`relay_members` set), through the same component and the same store as a solo race, whose rows render as before. A team row shows the team name in place of the runner's (a button, not a profile link) with the connection dot of the holder, the zone fraction, time, gap and deaths. The second line is `relayHolderLine`: "<holder>, <zone>" (the zone cut like any row's, its full name in the tooltip, dropped while run details are hidden), "<holder> offline" when the holder has no mod connection, "Baton free" when a playing team has no holder (the holder abandoned and nobody has taken the baton). The chevron and the team name unfold the members (a click elsewhere on the row still selects it for the comparison): each with `relayMemberLabel` and "zones/cap" as the server sends them (`relay_members[].zones`, `relay_cap`). States: "playing" (the row's `relay_holder_id`), "waiting", "ready" (before the start), "finished", "out" (abandoned or disqualified, whatever the team does); the holder and a waiting member add ", offline" when `online` is false. A member links to their profile when the REST race knows them (`memberUsers`), else shows the name. The unfolded set is a `SvelteSet` of row ids inside the component, so it survives row replacement and re-ordering. `reuseIfUnchanged` compares deeply, so an unchanged team keeps its row object although `relay_members` is a fresh array in each message, and a holder change or a member's count change yields a new one. The rules card of a relay race starts with `relayRuleLine` ("Relay: 30 zones, teams of 3, 11 zones max per runner on a full team (higher on a smaller one)."; an unfolded team shows its own live cap, which is higher for a team with fewer members and moves after an abandon). A member's profile link opens in a new tab and does not select the row. The OBS leaderboard overlay (`LeaderboardOverlay`, its own component) is unchanged: a team row reads as any row through the same data, with the team name (the row's display name) and the team's fraction, time and gap, and no holder line or member list.

Map (`/race/[id]`, live, finished and the replay): the map components are fed the team rows unchanged, so a relay race draws one path per team in the team's color with the team's marker at its current zone, and nothing per runner (no handoff marker on the path). The team name is the row's display name (`twitch_username` is `team-<8 chars>` and is never shown on its own), and no map component links a row to a profile. Selection of two teams opens the layer comparison on row ids as for runners. In the zone popup (`NodePopup`, "Visited by") a team's line reads "<team>, <runner>": `relayRunnerAt` (`web/src/lib/relay.ts`) takes the `runner_id` the server writes on each `zone_history` entry (the holder when the entry was written) from the node's last entry that is not a backtrack, and names it from the row's own `relay_members`. A zone restarted after a handoff therefore names the runner who got out of it. No runner is shown (the line is the team name alone) when the entry has no `runner_id` (solo race, or a team's first entry written before a holder existed) or when the runner is not in `relay_members`; members who are out stay listed, so a runner who abandoned is still named. `computeVisitors` reads `relay_members` from the row at click time, so the paths do not depend on it: `pathParticipants` in `MetroDagFull.svelte` compares only the zone history, current zone, color, name, status and IGT, and a member's `online`, `ready` or `zones` change redraws nothing. The replay of a finished relay race replays the teams (one path per team, the team's zone history), and the personal highlights of a runner are their team's.

## Bot

`tools/relay_bot.py` plays fake relay runners over the mod WebSocket, so the server and the web can be exercised without the game. From `server/`, against a local database only (it refuses any other unless `--force`), while the dev server runs with `RELAY_RACES_ENABLED=true` (needed to create the race the bots join):

```
uv run python ../tools/relay_bot.py <race_id> --team Alpha=bot1,bot2 --team Beta=bot3,bot4
```

Each bot is a local user. In setup the tool places them in the named team through `place_in_team` (a team missing from the race is created and named; never name the organizer). Each bot then connects over `/ws/mod/<race>` with its own mod token and `PROTOCOL_VERSION`, and behaves as the server expects of a mod:

- It sends `ready`, and once the race runs its first `status_update` with an IGT of at most 60 s (the fresh-save gate), then `relay_ready {ready: true}` while it waits (again after every `auth_ok`: readiness does not survive the socket).
- It answers `relay_release` with a `relay_state` carrying the same `handoff_id`, its `CharacterState` (below) and the team IGT, and `relay_take` with `relay_taken`; only then does it report progress, its first report carrying the IGT given in `relay_take`.
- Its role comes from `RelayInfo.role` (`auth_ok`, `relay_update`). It stops once its own member is `abandoned` or `disqualified`, or its team is finished, abandoned or disqualified.

The state a bot hands over is, by default, a Vagabond at its starting level with nothing (level 9, its attribute sum minus 79, so the receiver's mod writes it). `--state FILE` gives every bot the state in `FILE` instead: a `CharacterState` JSON (`attributes`, `level`, `runes`, `items`, `grace_flags`), checked at startup against the server's own model (`CharacterState` in `server/speedfog_racing/websocket/schemas.py`). A file that cannot be read, or that the server would drop, stops the tool with the reason; a state whose stats the receiver's mod would not write (its level not the attribute sum minus 79, a value out of range) starts with a warning. This is how the in-game checklist's take steps (the items, the armor, the flags, the second apply, the tampered state, the quit-out during an apply) hand a real game a chosen state: a bot holder passes the baton to the game's runner, and the server's `relay_take` carries the bot's state. For example, a level 30 character with a Longsword +5, a Moonveil +3, the Kaiden Helm, the Crimson Amber Medallion, Glintstone Pebble, Lone Wolf Ashes, the Crimsonspill Crystal Tear and Ash of War: Lion's Claw (raw ids in decimal, category nibble included):

```json
{
  "attributes": [20, 12, 15, 18, 16, 9, 9, 10],
  "level": 30,
  "runes": 12345,
  "items": [
    2000005, 9060003, 268485456, 536871912, 1073745824, 1073973824, 1073752824,
    2147493648
  ],
  "grace_flags": []
}
```

`items` holds up to 4000 ids and `grace_flags` up to 1000 grace event flags (`BonfireWarpParam.eventflag_id`); the lists may be left out.

Only the pure decisions are validated: the setup insert, the socket loop, the console commands and `status` have never been run against a server (that needs a database at head and a pool regenerated with the relay plugin). The decisions are the pure `next_action(bot, message)` (the answer to one server message) and `tick(bot)` (what it sends on its own each second), covered by `tools/test_relay_bot.py` (no socket, no database).

Console commands:

| Command                     | Effect                                                                                                                                                                                                              |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `status`                    | Teams (status, holder, zone, IGT) and each member's zones over the cap                                                                                                                                              |
| `walk BOT`                  | The holder takes the next gate of the forward path (refused while its gates are locked)                                                                                                                             |
| `boss BOT`                  | The holder kills the boss of its zone (its defeat flag): a zone counts for whoever kills its boss, or exits it when it has none                                                                                     |
| `pass BOT TO`               | The holder asks to hand the baton to the teammate named `TO`                                                                                                                                                        |
| `take BOT`                  | A waiting bot asks for the baton, once `baton_free_in_s` is 0                                                                                                                                                       |
| `offline BOT`, `online BOT` | Close the bot's socket and stay away, then connect it again                                                                                                                                                         |
| `mute BOT on\|off`          | A muted bot ignores `relay_take`, which exercises the 30 s acknowledgement timeout                                                                                                                                  |
| `finish BOT`                | The holder sends the seed's finish event from any zone (the server credits the final boss): its team finishes, and the console warns when it is not at the final boss, as that finish proves nothing about the walk |
| `quit`                      | Leave                                                                                                                                                                                                               |

A walk needs the race to run and the bot to hold the baton. A race needs a relay seed (`Seed.relay`), so a local database whose pools were never regenerated with the relay plugin cannot start one.

## Mod

The mod side of a relay race, one subsection per piece. The race state machine (`mod/src/core/race_machine.rs`) is pure; the shell only feeds it messages and executes its effects.

### Overview

What the mod does on a relay race, in the order a runner lives it:

1. Every member starts a New Game; the mod reports its save's IGT and the server validates it ("Roles"). Nothing is locked in setup.
2. At the start the server names the roles. A waiting runner is locked and held at the Chapel, and tells the server when it is there and ready ("Lock and Chapel"). It sees who holds the baton, and a countdown when the holder is offline ("Overlay").
3. The holder plays as on any race. At each zone entry the mod reads the character and sends it as a checkpoint ("Giving the baton", "Game access").
4. The holder presses the baton key, picks a teammate and holds it; the server asks for the character, which the mod sends, and the server flips the baton: the giver is locked and sent back to the Chapel ("The baton key", "Giving the baton").
5. A waiting runner takes a free baton with the same key, or receives a handoff. The mod writes the character's stats, the team's IGT, the items, the bosses and the graces into the game, unlocks, warps to the team's zone and says so to the server ("Taking the baton", "What a state carries", "Game access").
6. When the team finishes, the runner is out or the race stops, the mod lowers the lock and shows nothing of the relay ("Roles").

The constants of all of the above, read from the code (the line is the declaration):

| Constant                  | Value                         | Defined in                            | What it bounds                                                                                              |
| ------------------------- | ----------------------------- | ------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `CHAPEL_MAP_ID`           | `0x0A010000` (`m10_01_00_00`) | `mod/src/core/relay.rs:19`            | The map id the position read gives at the Chapel (unconfirmed, fact L1)                                     |
| `SETTLE`                  | 2.5 s                         | `mod/src/core/relay.rs:23`            | Loaded time after a loading exit before a relay flag is written                                             |
| `GATE_WINDOW`             | 5 s                           | `mod/src/core/relay.rs:27`            | After the lock is raised, before a runner away from the Chapel is sent back                                 |
| `WARP_RETRY`              | 5 s                           | `mod/src/core/relay.rs:29`            | A warp flag that started no load is lowered after this long                                                 |
| `WARP_ATTEMPTS`           | 3                             | `mod/src/core/relay.rs:31`            | Raises of a warp flag before the warp is given up                                                           |
| `WARP_LANDINGS_MAX`       | 2                             | `mod/src/core/relay.rs:35`            | Warps ending away from the Chapel, per locked stretch, before the return is given up (a relaunch resets it) |
| `WARP_RELOWER`            | 100 ms                        | `mod/src/core/relay.rs:152` (private) | A lowered warp flag stays down this long before it is raised again                                          |
| `RELEASE_CAPTURE_TIMEOUT` | 12 s                          | `mod/src/core/relay.rs:39`            | A release is captured and answered within this, from its receipt                                            |
| `RELEASE_WINDOW`          | 15 s                          | `mod/src/core/relay.rs:43`            | The server's wait for the answer: a flip later than this after an answer is not that handoff                |
| `CAPTURE_ABANDON`         | 12 s                          | `mod/src/core/relay.rs:48`            | A capture unanswered this long is abandoned by the machine                                                  |
| `CAPTURE_RETRY`           | 500 ms                        | `mod/src/core/relay.rs:51`            | No capture is asked this long after a failed one                                                            |
| `READ_WINDOW_MAX`         | 1 s                           | `mod/src/core/relay_capture.rs:20`    | A capture's reads must end within this, between its two map reads                                           |
| `APPLY_DEADLINE`          | 15 s                          | `mod/src/core/relay_apply.rs:23`      | The shell stops writing an apply this long after the ask                                                    |
| `APPLY_ABANDON`           | 20 s                          | `mod/src/core/relay.rs:62`            | The machine abandons an apply the shell has not answered, and acknowledges the take                         |
| `APPLY_WRITES_PER_FRAME`  | 16                            | `mod/src/core/relay_apply.rs:29`      | The ceiling of writes in one frame's batch (provisional until measured)                                     |
| `SLOW_APPLY_ENV`          | `SPEEDFOG_RELAY_SLOW_APPLY`   | `mod/src/core/relay_apply.rs:38`      | Test aid: milliseconds between two writes of an apply, off when absent (never set for a real race)          |
| `APPLY_FRAME_BUDGET`      | 1.5 ms                        | `mod/src/core/relay_apply.rs:35`      | Wall time of one frame's batch, checked after each write once one was made (provisional)                    |
| `IGT_WRITE_SLACK`         | 2 s                           | `mod/src/core/relay.rs:83`            | How far above the wall time since the first write a take's IGT may read and still count as written          |
| `IGT_WRITE_RETRY`         | 500 ms (`CAPTURE_RETRY`)      | `mod/src/core/relay.rs:79`            | A take's IGT write that did not take is repeated no sooner than this                                        |
| `TAKEN_CONFIRM`           | 5 s                           | `mod/src/core/relay.rs:57`            | The holder role a take gave outlives a contrary update this long after `relay_taken`                        |
| `REQUEST_TIMEOUT`         | 10 s                          | `mod/src/core/relay.rs:68`            | A handoff or take request unanswered this long is forgotten                                                 |
| `HOLD_TO_CONFIRM`         | 1 s                           | `mod/src/core/relay_menu.rs:13`       | The hold that confirms a teammate or a take                                                                 |
| `MENU_AUTO_CLOSE`         | 5 s                           | `mod/src/core/relay_menu.rs:16`       | The menu closes by itself this long after the last press or release                                         |
| `MAX_STATE_ITEMS`         | 4000                          | `mod/src/core/relay_items.rs:23`      | Items in a state on the wire                                                                                |
| `MAX_STATE_GRACES`        | 1000                          | `mod/src/core/relay_items.rs:25`      | Grace flags in a state on the wire                                                                          |
| `MAX_STATE_INT`           | 2147483647                    | `mod/src/core/relay_items.rs:27`      | Every integer of a state on the wire                                                                        |
| `MAX_LIST_ENTRIES`        | `0x2000`                      | `mod/src/core/item_inventory.rs:31`   | An inventory list header with a larger capacity is not read                                                 |
| `BANNER_DURATION`         | 4 s                           | `mod/src/core/item_feed.rs:132`       | The transient relay banners ("YOU HAVE THE BATON" and the others)                                           |

The status line shows a message for 3 s (`mod/src/core/race_machine.rs:1884`, inline). The server's side of the same timings (60 s offline wait, 15 s release, 30 s take) is in "Baton".

### Roles

The server names the role: `RelayInfo.role` (`holder` or `waiting`) comes in `auth_ok` and in every `relay_update`, which replaces the team whole. The mod never derives a role from anything else, with one exception the server's word also makes: a `relay_take` received reads `holder` until it is acknowledged or given up, and so does the confirmation window after its `relay_taken` ("Taking the baton"). An unknown role or status (a build older than the server) is never read as a decision: the machine keeps its current lock state and offers nothing.

On a relay race the leaderboard rows are teams: a row's `id` is the team id (`RelayInfo.team_id`), not the runner's participant id. The runner's row is therefore the team row (`my_row_id`), which is what the finish, out, layer and leaderboard logic reads (`am_i_finished`, the layer snapshot before a zone reveal, the gap and the highlighted row of the overlay). On any other race it is the participant's own row, as before. The runner's own participant id stays what saved event flags are keyed on.

A runner's relay is in one of three states:

- Live: the race runs (countdown included) and the team status is `ready` or `playing`. Locks and takes apply only then. In setup every member reads `team_status: "registered"`, `role: "waiting"` and no holder, the first runner included, so a role alone says nothing before the start.
- Over: the team status is `finished`, `abandoned` or `disqualified` (over for every member), or the runner's own entry in `members` is `abandoned` or `disqualified` while the team plays on (then `am_i_abandoned` is also true).
- Neither: setup, or a status the mod does not know.

The runner's own `online` and `ready` in `members` are never read: the `RelayInfo` of `auth_ok` reads them `true` and `false` whatever the mod does, and readiness is the value the mod sends. The runner's own `status`, `zones` and `validated` are read, and the `relay_update` that follows `auth_ok` is the authoritative copy.

A role turning `waiting` clears the revealed zone and any pending one, so the exits of the zone just left do not stay on the panel. A `relay_refused` shows the server's `message` in the status line and logs its `code`; the mod branches on no code.

What a waiting runner's mod still sends is unchanged: once the countdown is over it reports `status_update` with its own save's IGT, which is how the server validates the save (`members[].validated`), and it shows `fresh_save_required` through the existing blocking banner. Every member starts a New Game at the start, like the first runner; the mod resets no IGT at a race start.

LiveSplit on a relay race is not addressed: it keeps following the local game (a waiting runner's own save, the team's once a take wrote it) and the arrivals of the team row.

### Lock and Chapel

The seed carries a saved event flag, the lock (`RelayInfo.flags.lock_flag`): while it is on, the seed's fog gates do not react and fast travel is refused. A second flag (`chapel_warp_flag`), when raised, warps the player to the Chapel (the start zone) and sets the respawn point there; the seed lowers it itself after the warp. The lock is saved, so it survives a quit-out and a game restart: the machine never assumes the flag's state. It knows what the server says and what it wrote itself in this process, and writes the server's word again once after every loading exit and whenever the word changes.

What the lock should read, decided on receipt of a message and re-checked as a few comparisons per frame:

| The server says                                                                                                                                                                      | Lock                                                                                    |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------- |
| No relay; or a live relay whose role this build does not know; or a team status it does not know (unless the runner is a holder with open gates, whose lock is lowered)              | left alone                                                                              |
| The runner is out, the team is finished, abandoned or disqualified, the race is not running (finished, reset to setup), or the team is `registered` (setup), whatever the role reads | lowered                                                                                 |
| A `relay_take` received and not yet acknowledged, whatever the role reads                                                                                                            | raised, until the take's acknowledgement lowers it ("Taking the baton")                 |
| Live, role `waiting`                                                                                                                                                                 | raised                                                                                  |
| Live, role `holder`, `gates_locked` (the cap)                                                                                                                                        | raised, and the banner "QUOTA REACHED: PASS THE BATON" shows once when the cap turns on |
| Live, role `holder` otherwise                                                                                                                                                        | lowered                                                                                 |

Nothing is locked in setup, the first runner included: the lock comes only with the `relay_update` the server sends at the start (countdown included). A giver is locked and sent to the Chapel only when a `relay_update` shows it `waiting`, never on its own after sending its state. An over runner wins over every other reading, an unknown role included.

Every relay flag write waits until the player is loaded on the race save (position readable, no wrong save) and `SETTLE` (2.5 s) has passed since the last loading exit: a flag written during a loading screen can be missed by the seed's events. A write the shell cannot make is silent: the machine believes the value it asked for until the next loading exit asserts it again, and nothing is read back.

A waiting runner whose lock is raised and who is away from the Chapel (map `m10_01_00_00`, read with the position the shell already reads every frame) is sent back once the gate window is over: 5 s since the lock was raised, or a loading exit since. The warp raises `chapel_warp_flag`; a raise that starts no load is lowered after 5 s and raised again, up to 3 raises, then the status line shows "Warp to the Chapel failed", the flag is lowered, and the warp is not tried again until the next loading exit. A warp ends on any frame where the player is not loaded after a raise, and as soon as the map reads the Chapel; the warp flag is never written on a frame inside `SETTLE`. A warp whose load ends away from the Chapel counts as a landing: after 2 landings in one locked stretch the return is given up for good (same status line, the landing map id logged at warn level), and readiness stays false; a loading exit does not reset the count, reaching the Chapel or the lock going down does. A relaunch of the game resets the landing count (it lives in the process), which is how a runner stranded by a given-up return is freed. A dead runner (HP 0) is not warped; HP is read only while a return may start (no warp running, not given up, past the gate window) or a take waits for a frame. A take received and not started yet is sent back like a waiting runner. A warp still running is dropped, its flag lowered if it is still on, when the role turns `holder` (a take started included) or the relay stops being live.

What only the game proves about the lock and the Chapel (the in-game checklist, section A and the steps it names):

| Id  | Fact                                                                                                                                                                    | Source                             | Confirmed in game                                                                                                 |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| L1  | The Chapel's map id, as `GameState::loaded_map_id` reads it, is `0x0A010000` (`m10_01_00_00`)                                                                           | `CHAPEL_MAP_ID`                    | No (a wrong value shows as two loading screens, then "Warp to the Chapel failed")                                 |
| L2  | A flag written on a loaded frame once `SETTLE` has passed is honoured by the seed's events: the lock makes the gates inert and refuses fast travel, the warp flags warp | `docs/plugins/relay.md` (speedfog) | The seed side by hand with Cheat Engine: yes. Written by this mod: no                                             |
| L3  | The lock the mod writes survives loading exits and a quit-out, and one changed by hand during a load is written again after it                                          | `relay_asserted`                   | No (the seed's own events once missed a lock raised during a load; the generator's fast travel gate polls it now) |
| L4  | A runner sent away from the Chapel is warped back after `GATE_WINDOW`, lands on the Chapel and reads `CHAPEL_MAP_ID` there                                              | `maintain_relay`                   | No                                                                                                                |
| L5  | `GameState::read_hp` reads 0 for a dead runner and above 0 for a living one                                                                                             | `FrameSnapshot.hp`                 | No                                                                                                                |
| L6  | The server hears `relay_ready` true only from a runner at the Chapel with the lock asserted, and refuses a take or a handoff otherwise                                  | `Effect::SendRelayReady`           | No                                                                                                                |
| L7  | The seed lowers a warp flag itself after the warp and reads a lower followed by a raise as a new warp                                                                   | `docs/plugins/relay.md` (speedfog) | By hand: yes. Driven by this mod: no                                                                              |

`relay_ready { ready }` tells the server a waiting runner is loaded at the Chapel with its lock raised (asserted since the last loading exit, no warp running). The mod sends its current value, true or false, on every change and on the reconnection frame after every `auth_ok`: readiness does not survive the socket. A holder never sends true, nor a runner whose take is in progress. The messages queued while the socket was down are dropped at the reconnection; readiness goes again on the reconnection frame.

### What a state carries

A handoff carries the giver's character (`CharacterState`: attributes, level, runes, items, grace flags). The rules are pure (`mod/src/core/relay_items.rs`); the one game parameter they need, `EquipParamGoods.goods_type`, is read by the shell and passed in. Stats and runes are replaced by the giver's, not merged. Items go by union, nothing is equipped, and the receiver gets only what it lacks:

| Category                             | Transferable                                                                                                                                 | Lacking when                                                                                                                                                                                                                                                                                           |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Weapon (`0x0`)                       | Not ammunition (ids `50000000` to `53999999`), not bare hands (base `110000`), upgrade level (last two digits) at most 25                    | The receiver owns no weapon of the same base (`id / 10000`), whatever its affinity and level. Given as the base plus the level, the highest among the giver's copies of that base, with no affinity (Heavy +7 and plain +3 of base `2000000` give `2000007`; an owned Keen +0 `2000200` gives nothing) |
| Armor (`0x1`)                        | Not the naked ids `10000`, `10100`, `10200`, `10300`                                                                                         | Exact id absent                                                                                                                                                                                                                                                                                        |
| Talisman (`0x2`), ash of war (`0x8`) | Always                                                                                                                                       | Exact id absent                                                                                                                                                                                                                                                                                        |
| Goods (`0x4`)                        | `goods_type` 5 and 17 (sorceries), 16 and 18 (incantations), 7 and 8 (spirit ashes), 10 (crystal tears); a goods id with no param row is not | Exact id absent                                                                                                                                                                                                                                                                                        |
| Any other category                   | Never                                                                                                                                        |                                                                                                                                                                                                                                                                                                        |

Consumables, flasks, key items, materials and ammunition never transfer. The receiver filters the giver's list through the same rules, so a state from a tampered or newer teammate cannot make it inject anything not recognisably transferable. Stats outside plausible bounds (attributes 1 to 99, level 1 to 713 and equal to the sum of the eight attributes minus 79, the game's rule, runes at most 999999999) are not written; the take still completes.

The weapon rule checks an id's shape only: it cannot tell a somber weapon (upgrade cap 10) from a standard one (cap 25), nor whether the id has a row in the weapon param table, so a level above 25 is dropped and the shell checks every id against its param table before giving it. The game has not confirmed the goods type values, the ammunition id range, the naked armor ids, or a weapon's upgrade cap per weapon.

Before sending, the state is fitted to the server's wire caps (4000 items, 1000 grace flags, every integer at most 2^31 - 1): both lists are sorted and deduplicated, the first values are kept, a grace flag above the integer cap is dropped, and the count of values cut is returned for the shell to log. Which items stay never depends on memory order; sorted order keeps weapons, armor and talismans ahead of goods and ashes of war.

### Giving the baton

The holder's mod answers the server's `relay_release { handoff_id, to_name }` with its character, and sends a checkpoint of it at every zone entry. The machine decides; the shell reads the game on a worker thread and answers through `RaceMachine::relay_state_captured` ("Game access").

A capture is asked (`Effect::CaptureRelayState`, carrying a generation) only for the holder of a live relay, connected, on a frame with a readable position, on the race save, and one at a time: while one is in flight no other is asked. Two bounds keep the machine from depending on the shell. A capture not answered 12 s after it was asked is abandoned and a new one may be asked, and its late answer is dropped: an answer counts only for the capture in flight, identified by its generation (two checkpoint captures both carry a null `handoff_id`). After a failed capture (answer `None`) none is asked for 500 ms. The shell delivers the answer on the frame thread, as an input of the machine, with the generation of the effect; a worker never calls into the machine. The answer is `relay_state { handoff_id, state, igt_ms }`, the state fitted to the wire caps first (a single warn names how many values were cut) and `igt_ms` the held IGT of the answer frame.

| Event                                                                                                                                                                                  | What the machine does                                                                                                                                                                                                                                                                                                   |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `relay_release` to a live holder                                                                                                                                                       | Remembers it (`handoff_id`, `to_name`) with a deadline 12 s after receipt, under the server's 15 s. A release for the id already pending changes nothing; a release with another id replaces the pending one. A release to a waiting runner, an unknown role, a runner out or a team over, or without relay is ignored. |
| Release pending, a loaded frame                                                                                                                                                        | Asks the capture. A release's capture in flight is waited for; a checkpoint's is abandoned at once (its late answer dropped by its generation) and the release asked on the same frame, not up to 12 s behind it.                                                                                                       |
| Answer `Some(state)` for the pending release                                                                                                                                           | Sends `relay_state` with the release's `handoff_id`, and remembers `to_name` with the time of the answer. Nothing is locked, no warp, no banner: the server decides.                                                                                                                                                    |
| Answer `None` (loading screen, character not in the world, read failure)                                                                                                               | Sends nothing. A release stays pending and is asked again on the first loaded frame 500 ms or more after the failure, until its deadline; a checkpoint is dropped.                                                                                                                                                      |
| Deadline reached with no answer sent                                                                                                                                                   | The release is dropped and the status line reads "Handoff cancelled: not in game". A capture still in flight answers for nothing and is not sent. The server cancels at 15 s and the holder simply stays holder.                                                                                                        |
| The role turns `waiting`, the runner goes out, the team ends or the race stops while a capture is pending                                                                              | The release is dropped and the answer, if it comes, is not sent.                                                                                                                                                                                                                                                        |
| The socket drops (any status but connected, or a frame seen disconnected)                                                                                                              | The pending release is forgotten (the server cancelled it and a reconnection does not repeat it), a capture in flight answers for nothing, a checkpoint not yet asked is dropped. After the reconnection nothing stale is sent.                                                                                         |
| The server's `relay_update` reads this runner `waiting` within 15 s of the answer (a flip learnt from an `auth_ok` after a reconnect shows no banner: only a `relay_update` pushes it) | The flip: the banner "BATON PASSED TO <NAME>" shows (the name of the release's `to_name`) and the lock and the return to the Chapel of "Lock and Chapel" follow, as for any `waiting` update. The remembered release is then forgotten.                                                                                 |
| A `relay_update` that still reads `holder`                                                                                                                                             | The server refused or ignored the answer (an expired or unknown `handoff_id`, an IGT its wrong-save guard refuses, a target gone out). Nothing changes here. The remembered release stays until the 15 s window ends, so a flip that comes later is still recognised.                                                   |
| A `relay_update` turning the runner `waiting` more than 15 s after the answer, or with no answered release                                                                             | A takeover or another handoff: no "BATON PASSED" banner.                                                                                                                                                                                                                                                                |

A checkpoint (`handoff_id: null`) is asked when a zone is revealed to a live holder, which is when the entry shows on screen, not when the server names it. It is skipped while a capture is in flight (dropped, not queued: the server's stored state can then be one zone behind until the next zone entry), and when a release is pending at the same reveal the release takes the one capture (a release's state is kept by the server as the latest checkpoint too). A reveal while the socket is down asks nothing and nothing is sent after the reconnection: the server keeps only the latest checkpoint, and the next zone sends a fresher one. A team still `ready` keeps no state: the server ignores the checkpoint and the mod does not special-case it.

A capped giver (its gates already locked for the cap) is warped to the Chapel right after the flip, with no 5 s window: its lock time dates from the cap, not from the flip. This is accepted. The cap banner is not shown again: it shows once, when the cap turns on.

The mod writes no lock and no warp on a release or on a capture: the lock follows the server's word, so a cancelled handoff never leaves a holder locked.

### Taking the baton

The server's `relay_take { handoff_id, state, igt_ms, defeat_flags, warp_flag, zone_name }` gives the runner the baton. The machine decides; the shell writes the game (`Effect::WriteCharacterStats`, `Effect::SetIgt`, `Effect::ApplyRelayItems`, see "Game access") and sends `relay_taken` (`Effect::SendRelayTaken`).

Receipt. A take is ignored without a relay being played (no relay, the runner out or its team over, the race not running). A take whose `handoff_id` is the one in progress changes nothing: the server sends it again after a reconnection, and it is applied once. One whose id is the last take this process acknowledged is answered with `relay_taken` again on the next connected frame, nothing written: its first answer died with the old socket (the reconnection drops what was queued). Any other replaces the take in progress, whatever the cached role. At a new take's receipt the progress of the waiting save is dropped, with one info line: the deferred, pending and in-flight event flags, the in-flight zone queries, a zone waiting to be revealed, and event flags a previous launch saved. The server ignored them from a waiting runner, and replayed after `relay_taken` they would be heard as the team's. `relay_ready false` goes out if `true` was the last value sent.

| Step            | On the first frame that is                                                                                                                                                                    | Effects, in order                                                                                                                                                                                                                                                                                                                                                            |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Start           | loaded, `SETTLE` passed, on the race save, at the Chapel, HP above 0, connected, the lock raised and asserted, no capture and no apply in flight                                              | `WriteCharacterStats` (only a state within the bounds of "What a state carries"), `SetIgt { igt_ms }` (on every take, also without a state: the runner's own IGT would fail the team's fresh-save gate, or freeze the team's IGT as a rollback), `ApplyRelayItems` (the state's items and grace flags, none without a state; the defeat flags among the seed's `boss_flags`) |
| Acknowledgement | after the shell's answer: loaded, `SETTLE` passed, on the race save, HP above 0, connected, the game's IGT reads in the window of "The IGT written is checked" (or its 20 s bound is reached) | the lock lowered, the first raise of the warp flag when `warp_flag` is set, `relay_taken`; the banner "YOU HAVE THE BATON" with "Restart <zone_name>", or "You start from the Chapel" without a gate                                                                                                                                                                         |

The stats, the IGT and the world are written while the lock still holds the runner at the Chapel, then the lock is lowered, then the warp flag is raised: a holder warped before its lock is lowered would arrive in the zone locked, and one unlocked before its build is written could play its own save. The IGT written is checked: the acknowledgement frame must read an IGT in a window only a write that took can produce, from `igt_ms` up to `igt_ms` plus the wall time since the start frame plus `IGT_WRITE_SLACK` (2 s). The window applies at `igt_ms` 0 too (`[0, elapsed + slack]`, so a write of 0 that took is acknowledged on the first frame, and an unreadable IGT is outside it): a runner whose own IGT is 20 minutes and whose write failed must not report 20 minutes as the team's. A reading below the window is a write that did not take yet; a reading above it is the runner's own IGT still ticking (the normal case for most takes after the first, the runner having waited at the Chapel). On such a frame the acknowledgement waits and `SetIgt` is emitted again, no sooner than `IGT_WRITE_RETRY` (500 ms) after the last write. This guarantees that a write which failed, came late or was undone is not acknowledged while the game reads outside the window; it does not prove the game keeps the value afterwards. `APPLY_ABANDON` after the take started, if the IGT still reads outside the window, the take is acknowledged anyway with a warn line and the status "Baton taken: time not confirmed" and the guard references cleared (the server's own guards judge the reports). An apply the shell never answered is abandoned at the same bound with the status "Baton taken: items may be missing".

A runner away from the Chapel when its take comes is first sent there by the return of "Lock and Chapel" (a take not started counts as waiting there). There is no local timeout: a take waits for its start frame as long as it is not given up, and a return to the Chapel given up leaves it waiting (the server frees the baton at 30 s; a teammate's take then gives this one up). Once a take has started no return to the Chapel starts.

IGT guards. The start frame rebases them on the IGT written: the last good and last observed IGT become `igt_ms` (no reference at all for `igt_ms` 0, a team still `ready`, as after a race start: the machine reads 0 as no reading), the blackscreen freeze baseline is dropped, and a quit-out not yet consumed is forgotten. The jump to the team's IGT is therefore no save reload (whose flush would forget the reported bosses), no wrong save and no quit-out. The defeat flags written join the reported flags, so the boss scans never read or report them as the runner's own kills; after a process restart they are reported again, which the server counts as no new kill ("Cap"). From the frame after the start to the acknowledgement the reload, wrong-save and quit-out classifications are skipped, their references held at the take's IGT, because until the written IGT shows the game reads the runner's own (a reading far below the team's would otherwise read as a reload and clear the take's reported bosses, or start a new attempt). The acknowledgement rebases them on the reading when it is in the window; at the bound, or when the take is given up or replaced after it started, they are cleared as at a race start, so the next frame seeds them from what the game reads (stale references would read the runner's own IGT as a reload, a quit-out or a wrong save). They are live again from the next frame.

What is held. From the receipt to the frame that sends `relay_taken` (`progress_held`), nothing the server would judge against the team goes out: no `status_update`, no `event_flag` (no flag is read: the scans capture, clear and report nothing, so a flag stays as the game left it), no `zone_query` at a loading exit, no replay on a reconnection, no `relay_state` (no capture is asked, a release is ignored). The frame that sends `relay_taken` sends no progress after it; the next one resumes the scans, so the zone flag the take's warp raises is captured and reported as the team's at the warp's loading exit, and the status updates carry the team's IGT. The lock stays raised from the receipt to the acknowledgement whatever the role reads, and is written lowered once by the acknowledgement; the warp's loading exit asserts it lowered again after `SETTLE`, with no raise in between.

The warp is a flag warp as in "Lock and Chapel", on `warp_flag` (the connection's warp flag: the seed's event takes the player to that gate's exit and lowers the flag). A raise that starts no load is lowered after 5 s and raised again, 3 raises at most, then the flag is lowered and the status line reads "Warp failed: travel from the map" (the lock is down: the runner may fast travel). `relay_taken` has gone out with the first raise: a warp that never loads does not hold it back. The warp counts no landing toward the cap of the return to the Chapel and is not limited by it. It is dropped, its flag lowered if still on, when the runner stops holding the baton (a newer take, a waiting role, its relay over, the race stopped).

Precedence. A `relay_update` received during a take replaces the cached info, not the take: the lock stays raised, no return to the Chapel starts once the take has started, and the take goes on to `relay_taken` whatever role the update reads (after the server's 30 s the update reads the runner `waiting` with the baton free; the server still accepts a late `relay_taken`). The take is given up, without `relay_taken` ever, when an update or an `auth_ok` names another holder or none, the runner is out or its team over, or the race stops running (finished, reset); the lock then follows the role again. What was already written stays: a later take overwrites the stats and the IGT, and items are a union.

Role. The machine's role reads `holder` from the receipt until the take is given up, then for `TAKEN_CONFIRM` (5 s) after `relay_taken` unless the server speaks first: an update naming the runner holder confirms it, one naming another holder or none ends the window (the runner waits again and is locked), and an `auth_ok` ends it (the server sends the take again while it awaits it). Inside the window an update reading the runner waiting with itself named and the baton free is the server's 30 s timer crossing a late `relay_taken`: it changes nothing. After the window the server's word rules again.

The shell. The stat write and the IGT write are done on the start frame itself. The apply is read and planned on the shell's worker thread and written on the frame thread, a bounded batch per frame, within 15 s of its start ("Game access"); its outcome comes back on the frame thread as an input of the machine (`relay_state_applied`, with the generation of the effect): the apply is over, nothing more of it will be written, whatever part of it could not be done (the shell logs that), and the take goes on. An answer for any other apply than the one in flight is ignored, and a newer take waits for the apply in flight to answer. An apply not answered within 20 s (`APPLY_ABANDON`, under the server's 30 s) is abandoned: the take goes on to its acknowledgement with what got written (the IGT at least), and the status line reads "Baton taken: items may be missing". A shell that never answers therefore cannot hold the runner at the Chapel for ever. A socket drop during a take changes nothing of it: an apply answered meanwhile is acknowledged on the first connected frame after the reconnection, and the take the server sends again after `auth_ok` is applied once.

Log lines, which time a take in game: `[RELAY] Take received` (handoff id, with or without a state, the IGT, the warp flag), `[RELAY] Take started` (counts of items, graces and bosses), `[RELAY] Take applied` (`elapsed_ms` of the apply), `[RELAY] Take acknowledged` (`elapsed_ms` since the receipt), `[RELAY] Take given up` (the reason), `[RELAY] Apply not answered, abandoned`, `[RELAY] IGT does not read the team's, take acknowledged anyway`, `[RELAY] Holder role window ended`, `[RELAY] Holder role not confirmed in time` (the confirmation window ran out with no word from the server), `[RELAY] Take received again, in progress` (the server sent the take in progress again: nothing changes), `[RELAY] Take received again, acknowledged again` (it sent one already acknowledged: it is answered again on the next connected frame) and `[RELAY] Take acknowledged again` (that answer going out). The baton key logs `[RELAY] Baton menu opened` (teammates, eligible; debug level), `[RELAY] Baton menu closed by itself` (debug level), `[RELAY] Request refused` (the server's `code` and `message`, warn level), `[RELAY] Handoff requested` (the teammate), `[RELAY] Take requested` and `[RELAY] Request not answered, forgotten` (the 10 s bound).

What only the game proves for a take:

| Id  | Fact                                                                                                                                     | Confirmed in game |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| T1  | The IGT write takes effect by the next frame, 0 included (an acknowledgement waits for it, but nothing proves the game does not undo it) | No                |
| T2  | The game's IGT never runs faster than wall time and no other writer adds time during a take (the window's upper bound relies on both)    | No                |
| T3  | The lock lowered and the warp flag raised on the same frame are both honoured                                                            | No                |
| T4  | The connection warp lands at the gate's exit and sets the zone flag                                                                      | No                |
| T5  | The game saves the written IGT across a quit-out                                                                                         | No                |

### The baton key

One key, F8 by default, does everything. The machine receives it as a per-frame input (`TickInput.relay_key_down`; repeated key-down events of the OS are the same press) and produces the menu's state and the requests; the shell binds the key and draws (`mod/src/core/relay_menu.rs` holds the pure timers).

The holder. A press opens the menu, a list of the other team members, the highlight on the first teammate who can receive. The opening press neither advances nor confirms. A tap (a press and a release shorter than 1 s) moves the highlight to the next teammate, wrapping; holding the key 1 s confirms the highlighted one and sends `relay_handoff_request { to_participant_id }`, then closes the menu. The menu closes by itself 5 s after the last press or release while the key is up. The menu is possible only for the holder of a live relay, past the countdown (the server answers `busy` during it), with no release waiting, no take in progress or in its confirmation window and no request unanswered; anywhere else it closes and a press already down when it became possible is ignored until released.

Each row shows the teammate's counter as the server gives it ("2/5 zones") and, when it cannot receive, why, in the order of the server's refusal for a handoff target: out of the race (finished, abandoned or disqualified), not in game (offline or not ready at the Chapel), no fresh save (not validated; a member may simply not have reported yet, so the row never says its save was refused), at the cap (`zones >= cap`). An unknown member status is unavailable too. A teammate who cannot receive is shown but never highlighted or confirmed. The rows are built when a `RelayInfo` is received and read from the echo (`members`, `cap`); the machine guesses nothing. A `relay_update` under the open menu keeps the highlight on the same participant id wherever the list now puts it; when that teammate is no longer available the highlight returns to the first and the press in progress is spent, and so is a press that began while nobody was highlighted (it was aimed at someone else: it neither taps nor confirms, and a new press is needed). A team nobody can receive, or a team of one after abandons, opens the menu with its reasons (or no row) and confirms nothing.

A waiting runner. Holding the key 1 s sends `relay_take_request`, only when all hold: the relay is live (team `ready` or `playing`, the race running) and past the countdown; `baton_free_in_s` reads 0 now (counted down from the seconds in the `RelayInfo` as received, `relay_free_in_s`; a countdown shows the wait and offers nothing; in setup nothing is offered, the info reading no holder and 0 for everyone); no take is in progress; the runner's own entry is validated with `zones < cap`; and the last `relay_ready` this mod sent was `true` (its own readiness: the echo in `members[].ready` reads false after an `auth_ok`). A hold that started before the take was offered does not count.

One request at a time. After a handoff or take request nothing more is sent, and the menu does not open, until the server answers (`relay_release` for a handoff, `relay_take` for a take, or `relay_refused`) or the runner's role changes or its relay ends, or `REQUEST_TIMEOUT` (10 s) passes; a socket drop forgets it. A `relay_refused { code, message }` shows `message` in the status line (3 s, open menu or not) and frees the key; the mod logs `code` and branches on none.

Per frame, the key costs two timers and a few comparisons; the row strings are built on receipt and cached.

### Overlay

What a relay runner reads is data built once, in `mod/src/core/relay_view.rs` (`RelayView`), and cached on the machine (`relay_view()`): the strings are rebuilt on `auth_ok`, on each `relay_update`, when the machine's role changes (a take received, given up, acknowledged, its confirmation window over), when the displayed layer changes, when the key's label is set, and once per displayed second of an offline holder's countdown (the machine counts down from the seconds in the `RelayInfo` as received and compares the displayed second once per tick). Nothing is formatted per frame; the hold progress is a number (`relay_hold_progress`). Geometry is pure (`mod/src/core/item_banner.rs`, `relay_block_layout`, `relay_block_bounds`): the title hangs from the same height as the item banner's icon, rows are 1.6 line heights, sizes follow the screen's width (its height times 16/9 on an ultrawide); the drawing measures the texts, cuts every name and zone to `text_max_width` with its truncation helper, and the bounds stay inside the display.

Nothing relay-specific is shown while the team is not live (setup, finished, abandoned, disqualified), when the runner is out while the team plays on, or on an unknown role or team status. The BATON line of the panel reads the holder ("Kahleeya"), "you" for the holder, "free" when the baton can be taken, "nobody" when none is named and it is not free, then the runner's own counter against the cap as given ("you 2/5 zones", "3/5 zones" as holder, "6/5 zones" past the cap) and the key hint ("F8 pass" for the holder, "F8 take" only while the take is actually offered, `relay_baton_hint`: not while the banner says "Not ready yet" or "Waiting for the server").

The waiting banner, top centre, for a runner who waits:

- Holder online: "WAITING FOR THE BATON", "<holder> is in <zone>" ("<holder> holds the baton" without a zone), "Zone 9 of 12. You: 2/5 zones.".
- Holder offline, wait running: "<HOLDER> IS OFFLINE", "The baton can be taken in 42 s", "It goes back to <holder> if they return before then.".
- Baton free: "THE BATON IS FREE" and one of "<holder> has been offline for over a minute", "The holder left the race" (nobody is named), "The handoff was not completed" (holder online, or the runner itself). Its last line is "Hold F8 to take the baton and restart <zone>." with the hold bar, or "No fresh save: you cannot take the baton." (not validated), or "You are at your cap.", checked in the server's order. Until the runner is at the Chapel with the lock asserted the prompt reads "Not ready yet: wait at the Chapel.", and "Waiting for the server" while its request is in flight.

The holder's menu, opened by the key: "PASS THE BATON", one row per teammate not out (name, then the counter or the reason as in "The baton key"), the highlight, the hold bar, and the hint `F8 next   hold F8 to pass   closes by itself after 5 s` (its three parts are separated by three spaces; with no one eligible only the last part, and "Nobody can take the baton right now" or, with no teammate left, "No teammate can take the baton"). The transient banners ("YOU HAVE THE BATON", "BATON PASSED TO <runner>", "QUOTA REACHED: PASS THE BATON") use the 4 s race item banner.

The key and its drawing (`mod/src/dll/hotkey.rs`, `ui.rs`). The key is `relay` in the `[keybindings]` of `speedfog_racing.toml` (default `f8`, `none` unbinds it, and every key hint is then replaced by the one line "No baton key bound: set `relay` in the config", the BATON line showing no hint and the waiting banner no hold bar; the key names are the table of `mod/src/core/key_names.rs`, aliases mapping to the first name listed; the race config the server generates writes `relay = "f8"`, a training config does not). The defaults of the mod's keys are F9 (panel), F10 (leaderboard) and F8 (baton). The shell reads the key's level each frame, and only on a relay race (`TickInput.relay_key_down`): ImGui's key state, true only while the game window is the foreground window of the process. ImGui learns of a release only through the game's own window messages, so a key released while another window had the focus would stay down for good: the level drops as soon as the game loses the focus and stays down until ImGui reports the key up, so returning to the game with the key already released is no hold. The frame where the focus is lost also tells the machine (`TickInput.relay_key_cancel`) that the press was cut short: the menu and the take hold drop it, so it is no tap (the highlight does not move) and no confirm, and the menu's auto-close is left to count from the last real press or release. The hint's label is the configured key's name in upper case (`Hotkey::label`), given to the machine with `set_relay_key` (`None` for an unbound key).

One block at a time hangs top centre, in a full-screen click-through window (the item banner's flags, so no widget takes focus): the menu when open, else the race item banner when one shows, else the waiting banner. What is drawn:

- Waiting banner (`render_relay_wait`): the title in its tone (fog `purple` for "WAITING FOR THE BATON", ember `danger` for "<HOLDER> IS OFFLINE", verdigris `success` for "THE BATON IS FREE"), the line in `text`, the detail in `text_disabled`; with the hold prompt, a bar of the menu's width centred under the detail, its track `text` at 0.15 alpha, its fill `success`, filled by the hold's progress.
- Menu (`render_relay_menu`): "PASS THE BATON" in brass (`gold`); one row per teammate, the name left in the body face and the counter or reason right in mono (a row that cannot receive in `text_disabled`); the highlighted row filled with `gold` at 0.18 alpha, outlined at 0.6, the hold bar along its bottom (track `text` at 0.15, fill `gold`); below the rows, the note when nobody can receive (and in place of the rows when there are none), then the key hints in `text_disabled`.
- The transient banners ("YOU HAVE THE BATON", "BATON PASSED TO <runner>", "QUOTA REACHED: PASS THE BATON") are the item banner with no icon, laid out with the relay block's geometry (`banner_layout_for`: same top and sizes as the waiting banner and the menu, so a banner replaces the waiting banner in place): gold title for the gains. The item banner of a race item, with its icon, is unchanged.
- BATON line (`render_relay_line`, in the panel under the tier line): "BATON" in fog (`purple`), the holder, the counter in `text_disabled`, the hint right aligned in `text_disabled`, all mono.
- A waiting runner's panel: the zone is the one the server names, the IGT and the deaths are the team row's.

Every text from the server is cut to the layout's `text_max_width` with `truncate_to_width`, and the cut and its measured width are kept (`CutCache` in `ui.rs`, keyed on the text, the width limit and the pixel size): a frame in between compares strings and allocates nothing. The banner faces carry the ellipsis for that.

Which block is on screen: the waiting banner and the item banner hang from the same band, and the fullscreen countdown's ring crosses it, so the waiting banner shows only with no menu open, no item banner and no countdown (`relay_wait_visible`); the open menu shows over an item banner and yields to the countdown (`relay_menu_visible`). `gap_uses_local_igt` says when a leaderboard gap takes the runner's local IGT: its own row, playing, and on a relay race only the live holder (a waiting runner's own IGT is not its team's), and `am_i_abandoned` reads a relay member out while its team plays on as out.

### Game access

Two threads of the mod touch the game here. The frame thread is the tracker's own: the Present hook, where the overlay draws and the machine ticks once per frame. It is not one of the game's own threads, and nothing the mod writes from it is synchronised with them, as the race items' and the lock's writes are not. The worker is a thread of the shell's, for reads that take time.

The shell's relay worker (`mod/src/dll/tracker.rs`) runs one job at a time, on a thread of its own named `relay-worker` (the name Tracy and a debugger show), so the character is never read by two jobs at once. Its scheduling is pure (`mod/src/core/job_queue.rs`): a job asked while another runs waits behind it, in order; a waiting job of a replaceable kind is replaced, in its place, by a newer job of the same kind, and a job of a kind that is not replaceable is never dropped. A capture is replaceable: the machine asks again only once it has given up its previous request, so a release that pre-empts a checkpoint is started as soon as the checkpoint's job ends, and the checkpoint's answer is dropped by its generation. An apply is not: every apply is answered, once, and it stays the running job until its writes have ended (below), so a job asked meanwhile waits behind the writes too. The answer goes to the machine on the frame thread, at the start of the first frame after the job ended, with the identity the job was asked with; a thread that panicked, or that the OS did not start, answers as a failed job. A job that never ends blocks the worker for the session: the jobs behind it never start, and the machine cancels each release at 12 s. Per frame the worker costs an `Option` check and an atomic load.

A capture (`mod/src/eldenring/relay.rs`; what its reads must pass and the state they build, in `mod/src/core/relay_capture.rs`) reads, in order: the goods param's types and the grace flags (the first capture of the process only, then kept: the regulation does not change in a session), the loaded map, the attributes, level and runes, the held inventory's normal and key lists, whether each grace flag is set, then the loaded map again. Any of these fails the capture (answer `None`: a release is asked again 500 ms later, a checkpoint is dropped), never a state partly read:

- no map loaded when the reads begin; the map read differently, or not at all, at their end; or the reads took over 1 s (`READ_WINDOW_MAX`, taken as shorter than any load): a load may have come in between;
- stats unreadable or negative, or outside what a character can have ("What a state carries"; the values read are logged): a state the receiver would not write is not sent;
- the inventory unreadable (a list header that does not look like the layout: nothing allocated, a count above its list's capacity, or a capacity above `0x2000` entries, `MAX_LIST_ENTRIES`; or both lists empty);
- the event flag reader down, or none of the grace flags read.

A param table that does not read fails no capture: it is warned once per session, with the table and the cause (its name not in the game's param index, or no usable row), and left empty. Without `EquipParamGoods` no goods is transferable (a goods id whose type cannot be found never is); without `BonfireWarpParam` the states carry no grace flag. A capture then still hands over the stats, weapons, armor, talismans and ashes of war. A grace flag the reader cannot read counts as not lit, and how many there were is logged: the reader answers the same for a flag of a category the game does not hold, and one grace row the game does not use must not fail every capture. The items are the transferable ids among those held ("What a state carries"), a goods id looked up in the goods types read (a goods id with no row is not transferable). The state is then fitted to the wire caps. A capture writes nothing. Every read of the character and its flags goes through `ReadProcessMemory` (libeldenring's pointer chains, the inventory copy, the event flag reader), which fails rather than faults on an unmapped address, as the item spawner's own thread already reads flags off the tracker's frame thread. The param rows are not: they are dereferenced directly (libeldenring hands out references into the game's param tables, which live for the session) and one field is copied out of each, as the race items read and write their param rows.

What a capture relies on, and whether the game has confirmed it:

| Id  | Fact                                                                                                                                                 | Source                                                                             | Confirmed in game                                                                                                                                                                                   |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1  | Stats: GameDataMan, `+0x8` (PlayerGameData), `+0x3C`: eight `i32` from vigor to arcane, the level at `+0x68`, the runes held at `+0x6C`              | libeldenring `Pointers::character_stats`; fromsoftware-rs `cs/player_game_data.rs` | Attributes and level: read by the practice tool, never by this mod. The runes word (`Pointers::runes`, the same `+0x6C`) is already read and logged by the Hunter feature (`[ITEMS] Hunter killed`) |
| R2  | Inventory lists at PlayerGameData `+0x410` (normal, then key), entries of `0x18` bytes, item id at `+4`, quantity at `+8`                            | `mod/src/eldenring/race_items.rs`, `mod/src/core/item_inventory.rs`                | Yes, through the race items (goods quantity, junk weapon)                                                                                                                                           |
| R3  | An entry is empty when its item id has no valid category nibble                                                                                      | fromsoftware-rs `cs/player_game_data.rs`, `cs/item_id.rs`                          | No                                                                                                                                                                                                  |
| R4  | Category nibbles: weapon `0x0`, armor `0x1`, talisman `0x2`, goods `0x4`, ash of war `0x8`                                                           | fromsoftware-rs `cs/item_id.rs`                                                    | Weapons yes (junk weapon), the others no                                                                                                                                                            |
| R5  | `EquipParamGoods.goods_type` and its values (at `0x3E` of the row as the codegen lays it out, after `icon_id` at `0x30`, which the race items write) | libeldenring param codegen; TarnishedTool `GoodsType`                              | No                                                                                                                                                                                                  |
| R6  | A grace is lit when the event flag `BonfireWarpParam.eventflag_id` of its row is set; the table goes by the name `BonfireWarpParam`                  | libeldenring param codegen                                                         | No                                                                                                                                                                                                  |
| R7  | The loaded map id reads `None` during a loading screen                                                                                               | `GameState::loaded_map_id`, the readability read of every frame                    | Yes, at every loading exit of the zone tracking                                                                                                                                                     |
| R8  | A load (the map unloaded, then one loaded again) lasts over 1 s                                                                                      | `READ_WINDOW_MAX`                                                                  | No (checklist E2: a capture across the start of a load)                                                                                                                                             |

Log lines: `[RELAY] Worker job started` (the job: its `handoff_id` and generation), `[RELAY] Worker job queued behind the running one` (the running and the queued job), `[RELAY] Worker job replaced while it waited` (the job dropped), `[RELAY] Worker thread not started, job failed` (warn level) and `[RELAY] Worker thread panicked, job failed` (error level). The first capture of a process logs `[RELAY] Goods types read` and `[RELAY] Grace flags read` (the counts), or for a table that does not read `[RELAY] Param table unreadable, no goods transfers this session` or `[RELAY] Param table unreadable, no grace transfers this session` (warn level, once: the `table` and the `cause`, `NotIndexed` or `NoUsableRow`). Each capture logs the inventory's `[ITEMS] Inventory list headers`, then `[RELAY] Character read` (generation, attributes, level, runes, `held`: how many item ids are held, `transferable`: how many pass, `items`: the transferable ids themselves, sorted, raw ids with their category nibble in decimal, `graces_scanned`, `graces_unreadable`, `graces`: how many are lit, `elapsed_ms`) with `[RELAY] Held item ids` before it at debug level (every id held, before the filter), or `[RELAY] Character not read` (generation, the reason, `elapsed_ms`; warn level; a stat check that failed names the attributes, level and runes read), and `[RELAY] State cut to the wire caps` (how many values; warn level) when the state was over the caps. The machine logs `[RELAY] State captured` when it sends the state.

A take writes the game in three parts ("Taking the baton"); the shell side is `mod/src/eldenring/relay.rs`, the rules `mod/src/core/relay_apply.rs`.

The stat write (`Effect::WriteCharacterStats`) is done on the take's start frame, before the effect returns: the stats chain is resolved once, the stats at that address are read and judged by the capture's rule (a chain that does not land on what reads as a character's stats is not written through), then the eight attributes, the level and the runes held are written, each as its own `i32` at its offset (`stat_writes`). The twelve bytes between the attributes and the level, and the rune memory after the runes, are never written. The stats are then read back and compared. A failed stat write fails no take. The IGT is the existing write (`Effect::SetIgt`, `GameState::write_igt`).

The apply (`Effect::ApplyRelayItems`) is a worker job. Its thread reads and plans, and writes nothing: the param rows (the first apply of the process reads them, then they are kept), the held inventory (read now, never taken from a cached list: a second apply of the same take, after a relaunch, finds what the first one gave and gives nothing again), then the plan (`plan`):

- Items: the state's ids go through the transfer rule again, on the receiver's side ("What a state carries"), then those the receiver lacks (`missing_items`), then each against its param rows: a weapon's `EquipParamWeapon` row without its upgrade level (the id less its last two digits, as the equip load finds a weapon's weight) and the `ReinforceParamWeapon` row `reinforceTypeId + level` (a somber weapon above +10 has none; a negative type has none at any level); an armor piece's `EquipParamProtector` row, a talisman's `EquipParamAccessory`, a goods' `EquipParamGoods` (its type already read), an ash of war's `EquipParamGem`, each at its param id. An id without its rows is left out and counted (`no_row`, `no_level`), never given. A table that does not read is warned once and gives nothing of its category for the session. An unreadable inventory gives nothing, and the flags are still raised.
- Flags: the take's boss defeat flags (the machine kept only the seed's bosses), then the state's grace flags that are graces of this game (`BonfireWarpParam`, as a capture reads them); any other grace flag is left out and counted (`not_grace`). Each flag comes once.

The writes are made on the frame thread, after the machine's tick, from the frame after the plan: the items (weapons, talismans, goods, ashes of war), the defeat flags, the grace flags, then the armor, last because this mod never gave armor before, so whatever that give does cannot hold up the rest. They are not synchronised with the game's own threads: a flag raise is a read-modify-write of a byte the game may write at the same moment, and nothing proves it never does (the lock's writes rely on the same). A frame's batch stops at 16 writes (`APPLY_WRITES_PER_FRAME`) or once 1.5 ms of its own wall time is spent (`APPLY_FRAME_BUDGET`), whichever comes first, after at least one write, so an apply moves on every frame; a give costs far more than a flag raise. Both numbers are provisional until measured with Tracy (checklist D8). A test aid, never to be set for a real race: when the environment variable `SPEEDFOG_RELAY_SLOW_APPLY` holds a number of milliseconds at the mod's start (read once by the tracker, absent, unparsable or 0 means off), the apply makes at most one write per that interval instead of a batch per frame, so a kill, a quit-out or a cut connection can be placed inside an apply (checklist F1, F2, F4, F5); the pacing rule is `ApplyRun::set_min_interval` (`mod/src/core/relay_apply.rs`) and the mod logs one warn line at start, `[RELAY] Slow apply is on (test aid): one write per interval`. The stop rules and `APPLY_DEADLINE` are unchanged, so a slow apply of a plan longer than the deadline divided by the interval ends on the deadline with the writes left counted. Off, it costs a field test per frame. The loaded map is read again right after a batch that wrote. A give is one unit through the game's own give function (`item_spawner::inject_one`: one of each spell, spirit ash and crystal tear, which are unique items; a weapon bare at the level planned), nothing equipped, as the race items give on the tracker's frame thread on a loaded player; the race items, refused on relay races, give nothing during a take. The other caller of that function, the seed's ashes of war, runs on its own thread at the first load of a fresh save, and nothing keeps it from calling the function at the same moment as a take: this is left as it is, the race items do not guard against it either. A flag is raised through the event flag reader as the lock is (`set_flag_cached`, the category page resolved at the frame's first flag). A write counts as done before it is tried, so a frame that panics never gives twice, and the write it panicked on counts as failed. The writes end for good at the first of:

- every write tried (a failed one is counted and its id logged);
- a frame since the ask (the plan's reads included) that read another map or none: a loading screen (quit-out, death, a warp) started, so nothing is written into what the game is rebuilding, even once the map reads the Chapel again;
- the take no longer applying (given up, replaced by a newer take, abandoned: `RaceMachine::relay_apply_wanted`);
- 15 s since the ask (`APPLY_DEADLINE`, under the machine's 20 s `APPLY_ABANDON`), whatever is left.

Then the machine gets `relay_state_applied`, on the frame thread, once per apply: nothing of that apply is written after it. An apply whose plan never comes (its thread panicked or did not start) answers too, nothing written. A stop before every write was tried is final: the take is acknowledged with what got written, and nothing tries the rest again. The items and graces not yet written are lost for the team, because the next handoff captures this runner's inventory and lit graces; the boss defeat flags come again from the server with every take, so only this runner's world misses them. Per frame, with no relay job running, the apply costs an `Option` check; while one runs, a walk of the jobs queued (each apply watches the frame's map from its ask on) and the running apply's batch.

What an apply relies on, and whether the game has confirmed it:

| Id  | Fact                                                                                                                                                                                           | Source                                                                                                                                                             | Confirmed in game                                                                                                           |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| W1  | Stats for the write: from vigor, the eight attributes at `+0x00` to `+0x1C`, twelve bytes the game uses otherwise, the level at `+0x2C`, the runes held at `+0x30`, the rune memory at `+0x34` | libeldenring `CharacterStats`                                                                                                                                      | Read: by the practice tool. Written by this mod: no                                                                         |
| W2  | The game takes the attributes written as the character's (status screen, max HP, FP and stamina recomputed) and keeps them across a quit-out                                                   |                                                                                                                                                                    | No                                                                                                                          |
| W3  | The game's give function gives one unit of a weapon, a talisman, a goods or an ash of war, unequipped                                                                                          | `mod/src/eldenring/item_spawner.rs`                                                                                                                                | Yes: goods, talismans and the junk weapon (race items, on the frame thread), ashes of war (the seed's, on their own thread) |
| W4  | It gives an armor piece (`0x10000000` and the protector id)                                                                                                                                    | Indirect: the practice tool's item spawner gives armor through the same call, with the same request (one unit, `dur` and `gem` at -1), from its own frame callback | Not by this mod                                                                                                             |
| W5  | A weapon given lands with no affinity, at the level asked or at the runner's best one (the Item Randomizer's auto-upgrade)                                                                     | "Junk weapon" in `RACE_ITEMS.md`                                                                                                                                   | Not for a level above +0                                                                                                    |
| W6  | A weapon's `EquipParamWeapon` row is its id less its upgrade level                                                                                                                             | `mod/src/core/equip_load.rs` (`weight_row`)                                                                                                                        | In use by the race items' equip load, not recorded as confirmed                                                             |
| W7  | A weapon at level `n` has the `ReinforceParamWeapon` row `reinforceTypeId + n`, and only for the levels it can reach                                                                           | the param's documented layout; libeldenring codegen (`reinforce_type_id`)                                                                                          | No                                                                                                                          |
| W8  | The game's param index holds `EquipParamGem` and `ReinforceParamWeapon` under those names                                                                                                      | libeldenring `param_names.json`                                                                                                                                    | No (the race items found `EquipParamWeapon`, `EquipParamProtector`, `EquipParamAccessory` and `EquipParamGoods`)            |
| W9  | A grace whose `BonfireWarpParam.eventflag_id` is set is lit and fast travel goes to it                                                                                                         | libeldenring param codegen                                                                                                                                         | No                                                                                                                          |
| W10 | A boss whose defeat flag is set stays dead and its fog gate open, the seed's events reading the flag                                                                                           | the seed's boss flags                                                                                                                                              | No                                                                                                                          |
| W11 | A flag raised from the frame thread (a read-modify-write of its byte) loses no bit the game sets in the same byte                                                                              | the lock's writes                                                                                                                                                  | The lock's byte: yes. The bytes of graces and bosses, shared with flags the game sets: no                                   |
| W12 | A quit-out or a death shows as a frame with no loaded map before the game rebuilds the inventory or the flags                                                                                  | `GameState::loaded_map_id`                                                                                                                                         | At every loading exit, yes; at the start of a load during an apply: no                                                      |

Log lines of a take: `[RELAY] Stats written` (`before`: the stats read before, the values written), or `[RELAY] Stats read back differ from the ones written` (`before`, `after`; warn level), or `[RELAY] Stats not written (unwritable, or what is there does not read as a character's stats)` (warn level). The apply: `[RELAY] Worker job started` (the job: its `handoff_id`, generation and counts), then from its thread `[ITEMS] Inventory list headers`, at the first apply of a process `[RELAY] Item rows read` (the row count of each table) or, for a table that does not read, `[RELAY] Param table unreadable, nothing of its category is given this session` (warn level, once: the `table` and the `cause`), `[RELAY] Inventory unreadable, no item given` (warn level) when it is, `[RELAY] Items left out for want of a param row` (warn level, one line per apply: `no_row`, `no_level` and the first 8 ids; a state this mod built has a row for every id, so this line means a table name or the weapon rule is wrong), and `[RELAY] Apply planned` (generation; `offered`: the state's item ids; `refused`: those the transfer rule refuses; `held`: the ids the receiver holds; `missing`; `no_row`, `no_level` and `unlisted`, the ids left out for want of a row; `items` and `armor`, the gives planned, and `gives`, their ids; `defeats`; `graces`; `not_grace` and `not_graces`, the flags that are no grace; `elapsed_ms`). Each give logs `func_item_inject called` (`encoded`, `output`). The end: `[RELAY] State applied` (`handoff_id`, generation, `written`: the writes made and failed by kind, `elapsed_ms` since the ask). For gives, `written` counts the calls made, not gives confirmed: the game's give function returns nothing the mod can check, so `armor: 1` can show for a piece the game refused, and only the inventory tells. Or the end is `[RELAY] State applied in part` (with `end`: `Deadline`, `MapChanged`, `NotWanted`, or `Complete` with failures; `failed`: the ids and flags whose write failed; `left`: the writes not made; warn level), or `[RELAY] State not applied (its plan never came)` (warn level). The machine then logs `[RELAY] Take applied` and, on the first frame whose IGT reads in its window, `[RELAY] Take acknowledged`.

## Before enabling relay races

Relay races are off behind a server setting. What must be done at launch:

1. The web help page lists the baton key with the other shortcuts: add it to the block that lists F9 and F10 in `web/src/routes/help/+page.svelte`. It is left out while relay races are off, so that the page does not advertise a key that does nothing.
2. Turn the server setting on ("Rules": `RELAY_RACES_ENABLED`).
3. Release a mod build that speaks the relay protocol (`docs/PROTOCOL.md`, "Protocol Version"), so the seed packs carry it.
4. Regenerate the pools with the relay plugin, so relay seeds exist ("Seeds").
5. Check that nothing players read or run sets `SPEEDFOG_RELAY_SLOW_APPLY` ("Game access"): it is a test aid that slows every apply of a take, and a real race must never carry it.
6. Run the in-game checklist below.

## Not proven yet

Server and web:

- The row-lock discipline ("Ordering": `SELECT ... FOR UPDATE` on the team rows, in one order) has only run on SQLite, which ignores `FOR UPDATE`. The tests check the statements PostgreSQL receives, never two transactions contending for a team on PostgreSQL. (The migrations were run up, down and up again on PostgreSQL 17, and `alembic check` finds no drift on the relay tables and columns.)
- The relay bot has never been run end to end against a server ("Bot"): only its pure decisions are tested (checklist 0.1).
- The web screens of a relay race have never been seen in a browser: the race creation tile and its cap sentence, the setup team list and its menus, the team rows of the leaderboard with their members, the team map and its popup, the invite page's team select, and the finished-race page ("Web", "Outside the live page"). They are tested through their pure functions only.
- A review recorded, and the server was not changed for it: `send_relay_updates` (`websocket/race/relay.py`) loads the team in a session of its own and sends afterwards, outside `relay_lock`. A `relay_update` read before a flip's commit and delivered after the `relay_take` would name the giver as holder: the receiver's mod then gives the take up and the server ignores the runner until its 30 s timer fires.

Mod: nothing of the Windows code has run in the game. The unit tests cover the pure machine (`cargo test --lib`) and the shell type-checks for Windows; what only the game proves is the facts tables, each step of the in-game checklist naming the ones it settles:

- The lock and the Chapel, L1 to L7 ("Lock and Chapel"; checklist A, with D0b, E1 and F8 to F9): above all the Chapel's map id (L1), without which no runner is ever ready.
- Reading the character, R1 to R8 ("Game access"; checklist C and E2): the stat offsets, the empty-entry rule, the category nibbles, the goods type offset, the grace parameter table and the 1 s read window.
- Writing the character, W1 to W12 ("Game access"; checklist D, F4 and F5): the stat write and what the game derives from it, the give function for each category (armor never given by this mod), the weapon level and its parameter rows, the parameter table names, the flag raises on bytes shared with the game's own flags, and the load boundary.
- Taking, T1 to T5 ("Taking the baton"; checklist D0, D1, D2, E3, E4 and F6): the IGT write and its window, the lock and the warp on one frame, the warp's landing and the IGT surviving a quit-out; and the take's duration against the server's 30 s, with `APPLY_WRITES_PER_FRAME` and `APPLY_FRAME_BUDGET` (provisional) settled by Tracy (D8).
- Giving, the key and the overlay as drawn (checklist B, C8, D0b, E1, E10, E11, F7): the release answered in time on a real inventory, the lock and the return to the Chapel after a flip, the layouts at 1920x1080, 1280x720 and 3440x1440, long names, the focus rule and the key rebound.
- The restarts (checklist F1, F2, F5): a take sent again after a crash or a reconnection, applied and acknowledged once.
- The cost per frame (checklist H): the spans of the machine, the overlay and the apply under Tracy.

Known limits, accepted when they were recorded and each visible in the checklist:

- A teammate who loses the game or the connection during an apply leaves the items not yet given missing for the team, since the next handoff captures this runner's inventory; the boss flags come again with every take.
- A save other than the runner's loaded in the middle of a take (a quit-out and a different character) is acknowledged with its own build and inventory: the mod's guards are blind to a save swap between a take's start and its acknowledgement, and only the server could catch it.
- An apply writes the items first (weapons, talismans, goods, ashes of war), then the defeat flags and the graces, armor last: slow gives can use the 15 s deadline before the flags are reached, and a grace not given is lost for the team. Whether the flags should go first is the project owner's decision once D8 has measured the gives.
- A spirit ash held at another upgrade level is a distinct goods id, so the receiver gets the giver's copy as a second one.
- A receiver whose mod reconnects in game between its `auth_ok` and the take sent again can see the lock flap for a frame or two.
- LiveSplit on a relay race is not addressed ("Roles").

## In-game checklist

One protocol, to follow from top to bottom, on a Windows build of the mod. Nothing in the mod's Windows code has run in the game when this is written: every step below is a prediction to confirm. The sections go in play order, the most dangerous unknowns first (the Chapel's map id, which everything else depends on, then the writes into the game), so that a crash or a corrupt save shows before time is invested. The order is also read-only first. The only writes before the read-only checks of section C are the mod's lock flag and, when it sends a runner back, its Chapel warp flag (section A): the lock is what holds a waiting runner at the Chapel and makes it ready, so without it no later step can be tested. The first take, which writes the character, comes in section D.

Each step says what to do (**Do**), what must be seen (**See**), the log line to look for (**Log**, quoted as the code emits it; its fields come on the same log line), what a failure looks like and what it means (**Failure**), and the fact it settles (**Proves**, an id of the facts tables of "Mod": `L` in "Lock and Chapel", `R` and `W` in "Game access", `T` in "Taking the baton"). When a fact is confirmed, change its "Confirmed in game" cell to the date and the step; when it is refuted, say so in the same cell and open the matching fix.

The seed side (the lock, the warp flags, the Chapel warp, the fast travel refusal) was checked by hand, without this mod, with Cheat Engine: `docs/plugins/relay.md` of the speedfog repository, "In-game checks" 1 to 15. Those are not asked again. This checklist tests that the mod drives them. That document records as not checked the lock on the gate events when it is raised during a load (its check 13), a warp raised while sitting at a grace or with a menu open (its check 15) and the cutscene transitions: steps A6, E3 and E4 below are where the mod meets them.

### Before you start

- **Mod build.** On Windows, from this branch: `cd mod && cargo build --lib --release`. Note `git rev-parse --short HEAD`: the first line of the mod log carries the commit (`SpeedFog Racing mod starting...`, with `commit`). Copy `target/release/speedfog_racing.dll` over `tools/assets/speedfog_racing.dll` on the server machine (`MOD_DLL_PATH`): every seed zip the server hands out afterwards carries that DLL. A second build with `--features profile-tracy` is needed for the steps that say Tracy ("docs/MOD_PROFILING.md": Tracy v0.13.1, a profiling DLL is never distributed). Use the plain build for everything else.
- **Server.** The dev server on :8000 with `RELAY_RACES_ENABLED=true` in `server/.env` (restart it), started without `--reload` (a reload on an edit drops every socket). Its log is the terminal it runs in; the lines this checklist quotes start with `Relay`.
- **Pool.** A pool regenerated with the relay plugin (graph.json 4.15; `tools/pools/_base.toml` enables it), scanned with `cd server && uv run speedfog-scan-seeds --pool <pool>`. `GET /api/pools` must report `relay_available` above 0 for it. Each race consumes a seed: plan the races below and add copies of a relay seed under new names, scanned again, as the race items protocol does.
- **Races.** Five, created on `/race/new` with the Relay tile. Race 0, bots only (0.1). Race 1, teams of 2, `Starts: bot1`: sections A and B. Race 2, teams of 2, `Starts: you`: section C. Race 3, teams of 2, `Starts: bot1`: sections D, E (E1 to E9) and F. Race 4, teams of 6, `Starts: you`: E10 to E13 (the cap, the menu with five teammates, the final boss, the banners) and section G, which ends the race in each way. Every race has two teams: Alpha (you and the bots of your team) and Beta (two bots: a team starts only with at least 2 ready runners, and at least 2 teams must count). You are the race's organizer.
- **Teammates.** One game instance, so the bot stands in for the teammates: from `server/`, `uv run python ../tools/relay_bot.py <race_id> --team Alpha=bot1 --team Beta=bot2,bot3 [--state FILE]` (race 0: `--team Alpha=bot1,bot4 --team Beta=bot2,bot3`; race 4: `--team Alpha=bot1,bot2,bot3,bot4,bot5 --team Beta=bot6,bot7`). The bots are local users; never name yourself. In setup the tool places them in their teams (a team missing from the race is created); started again later, with other `--state`, it only reconnects bots already in the race. The bot (see "Bot") holds the baton, passes it (`pass`), takes it (`take`), acknowledges a take or ignores it (`mute`), goes offline and comes back, walks, kills a boss, finishes. It cannot carry anything of its own: as a giver it sends the same state for the whole run, `FAKE_STATE` by default (a Vagabond at level 9, no item, no grace) or the file given with `--state`, and it sends no checkpoint. So a take that must carry items, armor, graces or a chosen build uses a `--state` file; the giver side of the mod (capture, release) needs your game as the holder; and a full circle between two real characters needs a second player on a second PC (**two players**: they join your team from their own account, with their own fresh save and the same DLL).
- **Characters.** Two kinds, different by construction. Character G: stocked with 150 to 200 items through Cheat Engine's item table (weapons, armor, talismans, sorceries, incantations, spirit ashes, crystal tears, ashes of war, plus consumables, a key item and a quiver), a few graces lit; it plays race 2 only and is used to produce captured states (section C). The partition of C9 needs at least 200 transferable ids (the `transferable` count of `[RELAY] Character read`): stock G with 220 or more. Character R: a fresh New Game character that holds none of those items, the receiver of sections D to F (a new one for each of races 1, 3 and 4). A take that gives something to G proves nothing: its plan has nothing to give.
- **State files**, for the bot, from `server/`: a partition of the ids captured from character G, built once in step C9 (its table lists every file, its content, its step and the `missing` that step must show). The example file of "Bot" is a format illustration only: its ids were never checked against the game's tables. Every file carries stats, level and runes: `s1`'s (the attributes `[20, 12, 15, 18, 16, 9, 9, 10]`, level 30, runes 12345) everywhere except `s0.json`, which is `{"attributes": [15, 10, 11, 14, 13, 9, 9, 7], "level": 1, "runes": 0, "items": [], "grace_flags": []}` (level 1 is not the attribute sum minus 79: the bot warns, and a receiver's mod writes no stat, only the IGT). A file is checked by the tool at startup.
- **Log.** `speedfog_racing.log`, in the folder of the DLL (the `lib` folder of the seed pack). It is appended to from run to run: note its size, or delete it with the game closed, before a section. The level is `info`; set the environment variable `RUST_LOG=debug` in the shell that launches the game for the steps that say debug (it is read once at start). Every relay line starts with `[RELAY]`.
- **Slow apply (test aid).** Steps F1, F2, F4 and F5 need an apply that lasts about 10 s: launch the game with `SPEEDFOG_RELAY_SLOW_APPLY=500` ("Before you start"; the log says `[RELAY] Slow apply is on (test aid): one write per interval`). Each step has its own file of C9, `s8a.json` to `s8d.json`, of 20 item ids, no grace flag and no armor piece: one write per 500 ms makes 20 writes about 9.5 s (the first is at once), inside the 15 s deadline, and the count of writes is the count of items. The sets are disjoint from every file of D, so R lacks them all: `missing` 20 on each first apply. Unset the variable and relaunch afterwards.
- **Fresh save.** Every runner of a race, the waiting ones included, starts a New Game on the seed (IGT at most 60 s at the first report). A relaunch of the game in the middle of a race reloads the same character and is fine. Back up the save files before section D: no step is meant to corrupt one, but D is the first time the mod writes the character (a take also writes the IGT of a save, which A and B never do).
- **Tools.** Cheat Engine with The Grand Archives table (`Event Flags > Event Flags by ID`, re-type the ID after an action: its `State` is a snapshot) for the lock and warp flags and to give a fresh character items; Smithbox for grace flag ids. The flags of a seed are in its `graph.json` under `relay`: `lock_flag` 1050290500, `chapel_warp_flag` 1050290501, `warp_flag_base` 1050290510 (see "Seeds").
- **Record** each step as pass, fail or not reached, with the log lines. A failure that the step marks as stopping ends the section: nothing after it can be tested.

### 0. Validation

- **0.1. The bots alone, before the game joins** (race 0: two teams of two bots, no game, `--team Alpha=bot1,bot4 --team Beta=bot2,bot3`). **Do:** start the tool, start the race from the web once every bot reports ready, then drive it: `status`, `walk bot1`, `boss bot1`, `pass bot1 bot4`, `offline` the holder of a team and `take` with its mate after 60 s, `mute` a taker and wait 30 s, `online`, `finish` each team. **See:** the console and the web's team rows follow, the race finishes when both teams have. **Log (server):** `Relay baton flipped`, `Relay take acknowledged`, `Relay take not acknowledged, baton free` (the muted taker), `Relay team finished`, `Race finished`. **Failure:** the tool stops in its setup insert or its socket loop (neither ever ran against a server): fix the tool before any game step. **Proves:** the bot's setup, socket loop and console, and the server's baton operations against a real client ("Not proven yet").
- **0.2. The game joins and every member is validated.** **Do:** in race 1, create Alpha and Beta in the web, join Alpha with your game's account, choose `Starts: bot1` for Alpha, start the bot tool (no `--state`: its bots never give in race 1). Launch the game from your pack with the mod, start a New Game and load into the world (the mod reports ready). Start the race from the web. **See:** nothing is locked in setup: the gates react, fast travel works. Validation is not shown by the bot's `status` nor by the web's team row: it is in the server log. **Log (mod):** `[WS] Race started!`; **(server):** `Relay member validated:` for you and for each bot. **Failure:** a game that loaded an old save instead of a new one shows the blocking banner "Please start a New Game", and the server logs `Rejected stale save (relay member)` instead of `Relay member validated:` for it. Try it once with a used character: a handoff to that runner is answered `not_validated` (bot console: `refused: not_validated: ...`) only if the runner is connected and ready at the Chapel with its lock raised; otherwise the server answers `target_unavailable` first (its checks are in that order). Then start a New Game. **Proves:** the fresh-save gate for a waiting member (server side, seen through the mod).

### A. The lock and the Chapel (race 1, you wait, bot1 holds)

If A2 fails, stop: nothing after it can be tested. The writes of this section are the lock flag and the Chapel warp flag, the only ones before the reads of C (see the introduction).

- **A1. The lock comes with the start.** **Do:** be at the Chapel when the countdown starts, try F8 (hold it): nothing happens. **See:** during the countdown and after the start, a fog gate of the Chapel shows no prompt, and fast travel from the map is refused with the game's own message, within about 3 s of the start (the settle is 2.5 s). No lock before the start. **Log:** `[WS] Race started!`, then `[RELAY] Lock raised` with `reason="waiting"`. **Failure:** no `Lock raised` line: the machine did not read the relay (check the `auth_ok`, protocol version, the team status); the line but the gate still prompts or fast travel works: the flag write is not honoured (a silent failure, nothing is read back) or `lock_flag` is wrong. **Proves:** L2. The holder's side of the key during the countdown is not testable by one person (the server answers `busy`): the unit tests cover it.
- **A2. The Chapel's map id, as the mod reads it.** **Do:** stay at the Chapel and do nothing for 60 s. **See:** no loading screen, no warp, the character stays put, but that alone proves nothing: the return to the Chapel also needs HP to read above 0, so a broken HP read gives no warp even with a wrong id. The proof is two positive log lines within a few seconds of the settle after the start. **Log:** `[RELAY] Lock raised` (`reason="waiting"`) and then `[RELAY] Ready sent` with `ready=true` (the mod reports ready only at the Chapel map with the lock asserted: an initial `Ready sent` with `ready=false` before the lock is normal). No `[RELAY] Warp to the Chapel` line. **Failure:** `Lock raised` but no `Ready sent` with `ready=true`, then a loading screen a few seconds after the start, a second one, and the status "Warp to the Chapel failed": the mod does not read the Chapel as `m10_01_00_00` (`CHAPEL_MAP_ID`, `0x0A010000`). The status shows for 3 s only: the durable evidence is the log, with `[RELAY] Warp to the Chapel landed elsewhere` twice, its `map` field being the id the position read gives at the Chapel (the value to put in `CHAPEL_MAP_ID`). The mod then does the two warps and stops for the process, nobody is ever ready and the relay stalls: STOP. `Lock raised` and `ready=true` absent with no warp lines either points at the HP read or the position read (L5): record it. **Proves:** L1 (with `ready=true`), L6 (the mod's side), and L4 for the landing.
- **A3. Sent back from the world.** **Do:** with Cheat Engine, raise a connection warp flag (1050290510 plus any n of the seed's build output) to put yourself in the world, then do nothing. **See:** `Ready sent` with `ready=false` as you leave the Chapel; about 5 s after the lock first held you (or after the first loading exit since), you are warped to the Chapel grace, one loading screen, then `ready=true` again. **Log:** `[RELAY] Warp to the Chapel`, `[RELAY] Ready sent`. **Failure:** you stay in the world: the return never starts (HP read as 0 for a living runner, `L5`, or the map read as the Chapel while away); a log with `[RELAY] Warp failed` and the status "Warp to the Chapel failed" means the raise started no load three times (the seed did not react to the flag, `L2`). **Proves:** L4, L5 (for living), L7 (the seed lowers the flag and reacts to a later raise).
- **A4. A dead runner is not warped.** **Do:** raise a connection warp flag into a zone with enemies and die there at once (or fall). **See:** no warp while dead; after the respawn you are at the Chapel and nothing more happens. **Log:** no `Warp to the Chapel` while the death screen shows. **Failure:** a warp during the death screen. **Proves:** L5 (for dead).
- **A5. The lock across a quit-out and a relaunch.** **Do:** quit to the title and load the character; then close the game, launch it again, load. **See:** each time, after about 3 s, gates show no prompt and fast travel is refused. **Log:** after the relaunch, `[RELAY] Lock raised` again (the process knows nothing of the old one); after a plain quit-out no new line (the lock is written again silently after each loading exit). **Failure:** a gate prompt or fast travel back after a load: the write is lost or the saved flag was not read as raised. **Proves:** L3.
- **A6. A lock changed during a loading screen.** **Do:** raise a connection warp flag with Cheat Engine; during the loading screen of the warp, set the lock flag OFF by hand; the mod then warps you back (A3). Repeat once while the Chapel loads. **See:** after the load and about 3 s, the gates are inert again and fast travel refused (the mod rewrote the lock). Also note whether the Chapel's own fog gate shows a prompt. **Log:** none (a rewrite is silent). **Failure:** the lock stays OFF until the next load. This is the generator's open check 13 as the mod meets it. **Proves:** L3.
- **A7. Readiness reaches the server.** The mod's side is A2's `Ready sent`; the server's side is its acceptance of a take or a handoff for this runner (D0): it refuses a runner who is not ready at the Chapel with the lock asserted (`target_unavailable`, `not_ready`). **Proves:** L6.

### B. The key and the overlay, waiting side (race 1, you wait)

- **B1. Holder online.** **See:** top centre "WAITING FOR THE BATON", "bot1 is in <zone>", "Zone 9 of 12. You: 0/<cap> zones." (the values of the race); the BATON line of the panel names bot1 with your counter and no key hint (no take is offered). Hold F8 for 2 s: nothing is sent. **Failure:** a take request (`[RELAY] Take requested`) while the holder is online. **Proves:** the overlay strings and the key gate.
- **B2. Holder offline.** **Do:** `offline bot1`, watch for 20 s, then `online bot1`, then `offline bot1` again and leave it. **See:** an ember "BOT1 IS OFFLINE", "The baton can be taken in 42 s" counting down second by second, "It goes back to bot1 if they return before then."; the BATON line reads "bot1". After `online bot1` the banner returns to "WAITING FOR THE BATON". **Failure:** a countdown that stalls or runs ahead of the server's (the baton can be taken only at 0). **Proves:** the countdown, the reconnection.
- **B3. The free baton.** **Do:** wait for the 60 s of the second `offline`. **See:** a verdigris "THE BATON IS FREE", "bot1 has been offline for over a minute", "Hold F8 to take the baton and restart <zone>." with a hold bar (or "Not ready yet: wait at the Chapel." within about 3 s of a load; "No fresh save: you cannot take the baton." and "You are at your cap." appear when those hold); the BATON line reads "free" with "F8 take". The baton stays free while bot1 stays offline. Do not take it here: the take writes the game and comes in D0. **Failure:** a prompt before 60 s, none after. **Proves:** the free-baton texts, `baton_free_in_s`.
- **B4. Sizes.** **Do:** look at B1 to B3 at 1920x1080 first, then 1280x720 and 3440x1440, against the approved mockup. **See:** the block keeps its place, follows the screen's height on the ultrawide, nothing overlaps the compass or the panel, no empty band above a banner. **Proves:** the layout numbers.
- **B5. The key rebound.** **Do:** set `relay = "g"` under `[keybindings]` in `speedfog_racing.toml` (next to the DLL), relaunch the game and load; then `relay = "none"`, relaunch; then put `relay = "f8"` back, relaunch. **See:** the hints carry the new label; with `none` every hint reads "No baton key bound: set `relay` in the config", the waiting banner shows no hold bar, nothing can be taken or passed. After each relaunch the lock is raised again after about 3 s (`[RELAY] Lock raised`). **Proves:** the key table and config.
- **B6. Focus loss.** **Do:** with the take offered (B3), hold F8, alt-tab away, release, come back. **See:** the hold did not confirm and no request was sent (`[RELAY] Take requested` absent); the first press after returning may be absorbed (record whether it is). **Failure:** a take request on return. **Proves:** the focus rule of "The baton key".

Reset race 1 from the web (a reset lowers the lock of every mod still connected), then create race 2.

### C. Capture (race 2, character G, you hold, read-only)

You are the first holder, with character G (stocked and with graces lit, see "Before you start"): the mod reads the character at each zone entry and writes nothing into the game. The only writes before these reads are the lock flag of section A (and its lowering for a holder here) and the Chapel warp flag of A3, which nothing can be tested without. Race 2 ends with C9: the states you build from the captured ids are the files of section D.

- **C1. The lock for a holder.** **See:** after the start, gates react and fast travel works (the lock was lowered); `[RELAY] Lock lowered` with `reason="holder"` may show. **Do:** raise the lock by hand (Cheat Engine), then quit to the title and load. **See:** about 3 s after the load the prompt of the gates is back (a stale lock on a holder is lowered at the first loaded frame after a load). **Proves:** L3 (the holder side).
- **C2. The first checkpoint.** **Do:** take a fog gate (enter a zone). **See:** no hitch. **Log:** `[RELAY] Worker job started`, then (first capture of the process only) `[RELAY] Goods types read` and `[RELAY] Grace flags read` with nonzero counts, `[ITEMS] Inventory list headers`, `[RELAY] Character read`, `[RELAY] State captured`. **Failure:** `[RELAY] Param table unreadable, no goods transfers this session` or `... no grace transfers this session` (a table is not found under its name: `R5`, `R6`); `[RELAY] Character not read` names the reason (warn level): note it, it settles which read is wrong. **Proves:** R1, R2, R5, R6.
- **C3. What was read, against the character.** **See in the `[RELAY] Character read` line:** `attributes`, `level`, `runes` are the status screen's; `held` is the number of the inventory's entries (key items included); `graces` is the number of graces lit on the map, `graces_unreadable` 0; `elapsed_ms` a few tens of ms, far under the 1 s read window (`READ_WINDOW_MAX`). The server keeps it: `select character_state is not null from relay_teams` on the local database is true for your team. **Failure:** a stat off, a count off by a few (a misread category nibble or an empty-entry rule; the next step finds which). **Proves:** R1, R2, R3, R8.
- **C4. The item ids, one by one.** **Do:** with `RUST_LOG=debug` (set before launching the game), compare the `items` field of `[RELAY] Character read` with the inventory: it must hold every weapon, armor piece, talisman, ash of war, sorcery, incantation, spirit ash and crystal tear carried, and no consumable, key item, material or arrow (the quiver's included). `[RELAY] Held item ids` (debug) lists every entry the inventory shows, no empty one. If you own a DLC weapon (an id family whose last two digits are not an upgrade level), its id must be in `items`: the +25 cut must not drop it. **Failure:** a missing family points at `goods_type` (`R5`) or the category nibble (`R4`); an empty entry listed points at the empty-entry rule (`R3`). This is the only check of those three. **Proves:** R3, R4, R5.
- **C5. A stat-raising talisman.** **Do:** equip a talisman or a Great Rune that raises an attribute, take a gate. **See:** the attributes of `Character read` are the base ones of the level-up screen. **Failure:** `[RELAY] Character not read` naming the attributes, level and runes read (the level check failed on raised values): every handoff by such a holder is cancelled, which is the finding. **Proves:** R1.
- **C6. The first capture of a process reads the tables itself.** **Do:** relaunch the game, reload, take a gate. **See:** `[RELAY] Goods types read` and `[RELAY] Grace flags read` come before `[RELAY] Character read` (a relay race has no race items to prewarm them), and the capture ends well within a release's 12 s. **Proves:** R5, R6.
- **C7. The mod reads only.** **See:** the inventory, the equipment and the lit graces are the same before and after the checkpoint. **Failure:** anything changed: stop and send the log. **Proves:** the capture writes nothing.
- **C8. The holder's menu, read-only.** **Do:** with `RUST_LOG=debug` set, press F8 and tap, without holding. **See:** "PASS THE BATON", one row per teammate (bot1 with its counter, "2/5 zones"-style), the highlight on the first teammate who can receive, a tap moves it (wrapping), the menu closes by itself 5 s after the last press while the key is up; a hold released before 1 s sends nothing. `offline bot1`: its row is dim "not in game" and is never highlighted; `online bot1`. **Log (debug level only, so `RUST_LOG=debug`):** `[RELAY] Baton menu opened`, `[RELAY] Baton menu closed by itself`. **Proves:** the menu's timers and rows.
- **C9. Build the state files, as a partition of the capture.** **Rule:** each id of the capture goes in exactly one file, so that R never receives an id twice, except where a step says it reuses a file on purpose. **Do:** from the `items` field of the `[RELAY] Character read` line of C3 (decimal ids; the category is the top nibble: weapons below 268435456, armor from 268435456, talismans from 536870912, goods from 1073741824, ashes of war from 2147483648), copy ids into the files below, in this order: first the four F sets, then the small D files, then the graces, then everything left into `s7.json`. The files are disjoint: `s2` to `s4` are not cumulative, each holds only its own id (plus the stats every file carries). Needed in total: 92 ids for the files below plus at least 100 for `s7.json`, so at least 192 (G is stocked with 220 or more); with fewer, `s7.json` falls under 100 and D8's large state proves less: stock G further and capture again. Each F set is 20 item ids with no grace flag and no armor piece, because the slow apply paces every plan step by its interval: with 500 ms, 20 writes take about 9.5 s (the first write is at once), inside the 15 s deadline, and an armor piece (written last) or a grace flag would change the count of writes and the order. **See:** each file loads in the bot tool without a warning other than the stats' one of `s0.json`. Then reset race 2, create race 3 (`Starts: bot1`) and start it with a fresh New Game character R.

| File                     | Contains                                                                                                                     | Used in                            | `missing` the step must show                                                 |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- | ---------------------------------------------------------------------------- |
| `s0.json`                | no item, no grace, implausible stats                                                                                         | D1, D2, E3, E4 (the IGT, the warp) | 0 (nothing to give)                                                          |
| `s1.json`                | no item, plausible stats                                                                                                     | D3                                 | 0                                                                            |
| `s2.json`                | 1 talisman                                                                                                                   | D4                                 | 1                                                                            |
| `s3.json`                | 1 standard weapon                                                                                                            | D5                                 | 1                                                                            |
| `s3c.json`               | the weapon of `s3.json` at another level (+1), a deliberate reuse of its base                                                | D5                                 | 0 (R owns the base)                                                          |
| `s3b.json`               | 1 somber weapon                                                                                                              | D5                                 | 1                                                                            |
| `s4.json`                | 1 armor piece                                                                                                                | D6                                 | 1                                                                            |
| `s6.json`                | no item, 3 grace flags and the flag that is no grace (`999999999`)                                                           | D7                                 | 0 items, `graces` 3, `not_grace` 1                                           |
| `s5.json`                | 8 ids: a weapon, an armor piece, a talisman, a sorcery, a spirit ash, a crystal tear, an ash of war and one more of any kind | D8                                 | 8                                                                            |
| `s7.json`                | every id left (at least 100)                                                                                                 | D8                                 | its whole count                                                              |
| `s8a.json` to `s8d.json` | 20 item ids each, no grace, no armor                                                                                         | F1, F2, F4, F5 (one each)          | 20 on the first apply; F1 and F5 apply their file again on purpose, see them |

The graces of `s6.json` are three `eventflag_id` values of `BonfireWarpParam` (Smithbox) that R has not lit. **Proves:** the files of section D are real captured states.

### D. Apply, smallest first (race 3, character R)

Race 3 starts with `Starts: bot1` and a fresh character R. Each step from D1 is a take of a chosen state: your game must be waiting at the Chapel and the bot the holder, and the state is the bot's `--state` file. **Precondition of every apply step: R holds none of the state's items**, because a take gives only what the receiver lacks. Check it from the log: `[RELAY] Apply planned` must show `missing` above 0 and `gives` naming the ids; with `missing` 0 the step proved nothing (R already held them: pick other ids in the file). To get the baton back to the bot, hand it over with F8 (hold 1 s on bot1), as D0b does the first time; then restart the bot tool with the next file (`quit`, then the same command with another `--state`) and run `pass bot1 <you>`. The common reading of a take: **Log:** `[RELAY] Take received` (with `with_state`, `igt_ms`, `warp_flag`), `[RELAY] Progress of the waiting save dropped`, `[RELAY] Take started` (counts), `[RELAY] IGT written`, `[RELAY] Worker job started`, `[RELAY] Apply planned`, `[RELAY] State applied`, `[RELAY] Take applied`, `[RELAY] Lock lowered` (`reason="take"`), `[RELAY] Warp to the zone` (when a gate was taken) and `[RELAY] Take acknowledged` (`elapsed_ms`); **(server):** `Relay take acknowledged`. **See:** the banner "YOU HAVE THE BATON" with "Restart <zone>" or "You start from the Chapel", then a warp into the zone. Note `elapsed_ms` of `Take acknowledged` in each step: well under the server's 30 s.

- **D0. The smallest take: the free baton, state null.** **Do:** with R waiting and the lock up (A2's two lines), `offline bot1`, wait the 60 s, hold F8 for 1 s once "Hold F8 to take the baton" shows. **See:** "Waiting for the server" for an instant, then the banner "YOU HAVE THE BATON" with "You start from the Chapel" in the place the waiting banner was (same title height, no jump, no empty band), the lock lowered (gates react), the IGT the team's, your build unchanged (bot1 never gave a state). **Log:** `[RELAY] Take requested`, `[RELAY] Take received` with `with_state=false`, `[RELAY] Take started`, `[RELAY] IGT written`, `[RELAY] Take applied`, `[RELAY] Lock lowered` (`reason="take"`), `[RELAY] Take acknowledged`; **(server):** `Relay baton flipped`, `Relay take acknowledged`. **Failure:** `[RELAY] Request refused` (warn, with the server's `code` and `message`: `not_ready` means the server never heard `ready=true`, `L6`); no `Take received` after the request and `Request not answered, forgotten` 10 s later; a crash here is the IGT write or the lock. This is the first write into the game, and the smallest there is (no stat, no item). **Proves:** L6, T1, T3, and the null-state take.
- **D0b. The first handoff, from your game.** **Do:** now that you hold the baton, press F8, tap to bot1, hold 1 s. **See:** the menu closes, the banner "BATON PASSED TO BOT1", at the title height of the waiting banner that follows (no jump); then, within about 3 s, the lock is raised and you are warped to the Chapel (one loading screen), gates inert. **Log:** `[RELAY] Handoff requested`, `[RELAY] Release received`, `[RELAY] State captured` (`handoff_id` set), then after the server's update `[RELAY] Lock raised` (`reason="waiting"`) and `[RELAY] Warp to the Chapel`; **(server):** `Relay release asked`, `Relay baton flipped`. **Failure:** you stay unlocked in the zone (the server's update never read `waiting`: the release answer was refused: look for `Dropped relay_state on implausible IGT` or `Relay state not kept`); the status "Handoff cancelled: not in game" (the capture did not read in 12 s: `[RELAY] Release not captured in time, dropped`). **Proves:** the giving path end to end, L2, L4.
- **D1. IGT only.** `s0.json`, with bot1 not having walked yet (no gate, `warp_flag` null). **See:** "You start from the Chapel"; the lock lowers (gates react), no warp; the IGT reads the team's, no "WRONG SAVE LOADED", no quit-out penalty. **Log:** `[RELAY] Stats not plausible, not written`, `[RELAY] IGT written`, `[RELAY] Apply planned` with every count 0, `[RELAY] Take acknowledged`. **Failure:** the IGT not at the team's after 20 s: `[RELAY] IGT does not read the team's, take acknowledged anyway` and the status "Baton taken: time not confirmed" (the write does not take, or is undone: `T1`, `T2`); a crash here is the write itself. **Proves:** T1, T2, T3 (the lock lowered at the acknowledgement) with a state in the message.
- **D2. A gate: the warp to the zone.** **Do:** `walk bot1` twice (a gate, then another), hand over again with `s0.json` (the receiver is again IGT only). **See:** after "Restart <zone>", the lock lowers and you are warped to that gate's exit: you stand at the entrance of the zone the team last entered; the zone flag is set (the zone shows on the map and the web), a boss arena is entered with its fog closed behind you. **Log:** `[RELAY] Warp to the zone`; none of `[RELAY] Warp to the zone raised again` or `... failed`. **Failure:** the status "Warp failed: travel from the map" (three raises started no load: the warp flag did not warp). **Proves:** T3, T4.
- **D3. The stats.** `s1.json`. **See:** the status screen shows level 30 and the file's attributes and runes; max HP, FP and stamina follow them (compare with a character built the same way); also the current HP and FP right after the write, the equip load, the cost of the next level, and the values after a rest at a grace and after a quit-out; nothing else of the character changed (the rune memory included). A take while the level-up menu is open: note what the menu shows afterwards and whether a level can be bought from the written values. With a stat-raising talisman on: `[RELAY] Stats not written (unwritable, or what is there does not read as a character's stats)` means the stats in memory were the raised ones. **Log:** `[RELAY] Stats written` (`before`, `attributes`, `level`, `runes`). **Failure:** `[RELAY] Stats read back differ from the ones written` (`before`, `after`), or a status screen unchanged: the offsets are wrong. **Proves:** W1, W2.
- **D4. One talisman.** `s2.json`. **Precondition:** R holds it not: `Apply planned` shows `missing` 1 and `gives` naming its id (`missing` 0 would prove nothing). **See:** the talisman is in the inventory, unequipped, one copy; one pickup notification at most. **Log:** `func_item_inject called` (`encoded` starting `0x2`), `[RELAY] Apply planned` with `no_row` 0, `no_level` 0, `not_grace` 0, `[RELAY] State applied` with `written` showing one give and no failure. **Failure:** the log ending on a `func_item_inject called` line (the game died inside the give); an item in `written` but not in the inventory (the give function returns nothing to check). **Proves:** W3. R holds afterwards: the start kit and that talisman.
- **D5. One weapon.** `s3.json`. **Precondition:** R holds no weapon of that base (`missing` 1). **See:** the weapon arrives bare (no affinity) at the level of the file, or at your best level if the seed upgrades weapons automatically (note which). Then, deliberately reusing its base, give back and take `s3c.json` (the same weapon at +1): `missing` 0, nothing arrives (R owns the base at another level). Then `s3b.json`, the somber weapon alone (`missing` 1). **Log:** `func_item_inject called` (`encoded` `0x00...`, the weapon id with no category nibble), `Apply planned` `no_row`/`no_level` 0 (a warning `[RELAY] Items left out for want of a param row` means the weapon rule or a table name is wrong). **Proves:** W3, W5, W6, W7, W8.
- **D6. One armor piece, alone.** `s4.json`: the first armor this mod gives. **Precondition:** R holds that piece not (`missing` 1). **See:** the piece in the inventory, unequipped. **Log:** `func_item_inject called` with `encoded` starting `0x1`. **Failure:** the game crashing or freezing on the give: stop D, send the log; armor is last in the apply order, so a defeat flag or a grace before it is already written. **Proves:** W4.
- **D7. Flags: boss and graces.** `s6.json` (no item, graces only), after `boss bot1` on a zone (so the team's `defeat_flags` carries a boss). **Precondition:** before the take, note R's own lit graces and kills, and that R has not lit the three graces (`Apply planned` shows `graces` 3, `missing` 0, `not_grace` 1). **See:** a grace of the file is lit for you and fast travel goes to it, the boss the team killed is dead in its arena with its fog open, and every grace and kill you had is still there (one missing is a neighbour bit lost by a flag raise); the grace flag that is no grace is ignored. Watch whether raising a defeat flag at the Chapel starts an event (a banner, a reward, a warp). **Log:** `Apply planned` with `defeats` and `graces` counted, `not_grace` 1 and `not_graces` naming the flag; `State applied` with no `defeats_failed` nor `graces_failed`. **Proves:** W9, W10, W11.
- **D8. A real state, then a large one, with Tracy (slow apply off).** `s5.json` (8 ids, `missing` 8), then `s7.json` (the rest of the capture, with the profiling build and Tracy connected). **Precondition:** R holds none of them (the partition guarantees it: earlier steps gave only the ids of `s2` to `s4`): `missing` of `s7.json` equals its count, at least 100. **See:** the items arrive one of each (a spirit ash R holds at another level arrives as a second copy: expected today, to record for the project owner), nothing is equipped, a flood of pickup popups is acceptable, the game does not stutter. **Log:** `Apply planned` (`offered`, `missing`, `items`, `armor`, `gives`), `State applied` (not `in part` with `Deadline`), `Take acknowledged` `elapsed_ms`. **Tracy:** `relay_apply_frame` stays near the 1.5 ms budget (`APPLY_FRAME_BUDGET`, plus one write), `relay.give` and `relay.raise_flag` give each write's cost, nothing of `relay.capture` or `relay.apply_plan` on the frame thread. This measure settles `APPLY_WRITES_PER_FRAME` (16) and `APPLY_FRAME_BUDGET`, both provisional. **Timing:** `Take received` to `Take acknowledged` under 15 s passes; above 20 s is a finding to report before release (the server frees the baton at 30 s). **Failure:** `relay_apply_frame` over several ms a frame, `State applied in part` with `Deadline`. **Proves:** W3, W4, W8 (the ash of war through `EquipParamGem`, its param table), W11, and the take's duration. The F files are disjoint from all of these, so R still lacks them.
- **D9. A tampered-looking state.** A `--state` file with an id that has no param row, a somber weapon at +25, a key item and a grace flag that is no grace. **See:** the take completes; nothing of them reaches the inventory or the flags. **Log:** `[RELAY] Apply planned` counts and names them (`refused`, `no_row`, `unlisted`, `not_graces`), `[RELAY] Items left out for want of a param row` (warn). **Proves:** the transfer rule on the receiving side.

### E. The full handoff, the cap and the takeovers (race 3, then race 4)

- **E1. A handoff under stress (race 3).** **Do:** each time press F8 and hold on bot1, then note where you end up. Pass the baton: in the middle of a boss fight; at a gate prompt; during the one second of a fog gate; while sitting at a grace; with the inventory or the map open; just after dying (confirm, then die: the release capture fails while dead). **See:** you always reach the Chapel, locked, within a few seconds of the server's flip: the lock is raised and the warp to the Chapel follows after the 5 s gate window (a loading exit since closes the window at once); a warp through the gate that you were already in the middle of is the generator's documented limit (the lock raised during that second comes too late), after which the mod sends you back. A dead runner waits for the respawn first. **Log:** `[RELAY] Release received`, `[RELAY] State captured`, `[RELAY] Lock raised` (`reason="waiting"`), `[RELAY] Warp to the Chapel`; `[RELAY] Release not captured in time, dropped` plus the status "Handoff cancelled: not in game" if the capture never read within 12 s (then the server cancels at 15 s and you stay the holder, unlocked: nothing stranded). **Failure:** you stay locked away from the Chapel with no warp, or unlocked after the flip: a lock decision that did not follow the server's word. **Proves:** L2, L4, L5.
- **E2. A capture across the start of a load.** **Do:** confirm a handoff and start a fast travel at once, several times. This is a tight window: the capture lasts a few tens of ms from the confirmation, so only a fast travel started within that time meets it; repeat 10 times or more and record how many reached it (none reached is a result, the unit tests cover the machine). **See:** every capture either reads in full or fails safe: **Log:** `[RELAY] Character read` with the counts of C3, or `[RELAY] Character not read` with `LoadDuringCapture` or `NotLoaded` (warn level), nothing sent, and the release captured again after the load (or cancelled when the load outlasts its 12 s). A state with zeroed stats or an empty inventory never goes out. **Failure:** a state with zero stats or no item reaching the server (check the receiver's status screen after the next take). **Proves:** R7, R8.
- **E3. A take whose zone entry is a sending gate or a cutscene transition (race 3).** **Do:** `walk bot1` until it enters a zone through a sending gate or a cutscene transition (the build output of the seed names them), then `pass bot1 <you>` with `s0.json` (nothing to give: this step is about the warp). **See:** the plain warp of the connection lands at the gate's exit with no cutscene and none of the story flags the vanilla event sets: note what the zone looks like and whether the way on works (the generator documents it as not checked in game). **Log:** `[RELAY] Warp to the zone`. **Proves:** T4 for those entrances.
- **E4. A take while sitting at the Chapel grace, with a menu open.** **Do:** sit at the Chapel grace (or open the map) while bot1 passes you the baton with `s0.json`. **See:** note when the take starts and where the warp lands: the generator documents that a warp flag has no guard on the player's state (check 15 of its list); the take starts only on a loaded, settled frame with HP above 0. **Log:** `[RELAY] Take started`, `[RELAY] Warp to the zone`. **Proves:** T3, T4 with a menu or a grace sitting in the way.
- **E5. The takeover of a free baton, with the state the server holds (race 3).** **Do:** hand the baton to bot1 (E1's way), then `offline bot1`, wait for "THE BATON IS FREE" and hold F8. **See:** the server holds your own last state (your game answered the release, not the bot), so your own build comes back: `Apply planned` shows `missing` 0 (R already holds it), the IGT is the team's and you restart the team's zone; if the server held no state, `with_state=false` and your build stays. The bot's `--state` file is received only through a bot-to-you handoff (section D). **Log:** `[RELAY] Take received` with `with_state=true`; **(server):** `Relay baton flipped`. A take asked before the 60 s are over is refused by the server (`Relay request refused: participant=... code=holder_online` in its log); the mod does not offer it earlier. **Proves:** the takeover with a stored state.
- **E6. The organizer removes the holder (race 3).** **Do:** while bot1 holds and you wait, remove bot1 from the race (the cross of its card in the web, or `DELETE /api/races/{race_id}/participants/{participant_id}` with the race running). **See:** at once "THE BATON IS FREE" with "The holder left the race" and the hold prompt (no 60 s wait); hold F8 to take it. **Log:** `Relay member out` (server), `[RELAY] Take received`; the state is the last one the server holds (yours), so `Apply planned` shows `missing` 0. **Proves:** the member-out update path of the baton.
- **E7. Your game dies as the holder, then relaunches (race 3).** **Do:** kill the game while you hold, relaunch and load. There is no deadline for the first case: the server keeps you holder until someone takes the baton, which the bot may do only after the 60 s of your absence, so a relaunch of a couple of minutes is fine as long as nobody types `take`. Then again, but after the relaunch has begun let `take bot1` run once 60 s have passed (the bot takes the free baton), and relaunch afterwards. **See:** the role of the server applies: in the first case you are still the holder (gates react once the stale lock is lowered, after about 3 s); in the second you are waiting: locked, sent to the Chapel. **Log:** `[RELAY] Lock lowered` (`reason="holder"`) or `[RELAY] Lock raised` (`reason="waiting"`), `[RELAY] Warp to the Chapel`. **Failure:** a stale lock left on a holder, or a waiting runner left free in the world.
- **E8. A refused request.** **Do:** hold F8 on bot1 within the same second as `offline bot1` on the bot console. **See:** the server's message in the status line, you stay unlocked where you are (`[RELAY] Request refused`, warn level, with `code` and `message`; **bot console:** nothing). This is a sub-second window: the menu greys a row as soon as the server's update arrives, so one person rarely hits it; if it is not reached, say so (the refusal display is covered by the unit tests, not by the game). **Proves:** the refusal display.
- **E9. Two players: both ways with real characters.** This step needs a second human on a second PC, with their own account, fresh save and the same DLL: one person cannot do it. The second player joins Alpha, with a fresh save of their own. **Do:** hand the baton from one to the other and back several times, with a state in the first (items, armor, graces lit, a boss killed). **See:** the receiver's build gains what it lacked (D3 to D7 with a real giver), the giver is locked and at the Chapel, each side's overlay shows the other as the holder, and after a takeover of a free baton (kill the holder's game, wait 60 s, take) the receiver gets the last checkpoint. **Proves:** R-and-W facts with a real giver, the checkpoint a takeover replays.
- **E10. The cap (race 4, teams of 6).** **Do:** play zones as the holder (the cap is about `ceil(layers / 6) + 1`; `status` of the bot console shows it). **See:** when your count reaches the cap, once, the banner "QUOTA REACHED: PASS THE BATON" (4 s, no icon); your gates are inert (the lock is raised); the BATON line counts "6/5 zones"-style past the cap; the menu still passes the baton and the capped runner is warped to the Chapel right after the flip with no 5 s window; in the menu a teammate at the cap reads "at the cap". A waiting runner at the cap sees "You are at your cap." on a free baton. **Log:** `[RELAY] Lock raised` (`reason="cap"`). **Failure:** the banner twice, or gates still reacting. **Proves:** the cap path.
- **E11. The menu with five teammates and long names (race 4).** **Do:** give the bots long usernames (a 40 character one, and one in a script the faces lack, created as local users) and open the menu. **See:** every name cut with an ellipsis, never wider than the box or off screen, the counter never cut; the highlight follows a tap and wraps; an unavailable row (offline, out, at the cap, no fresh save) is dim and never highlighted; with nobody available the note shows; the hold bar fills in 1 s and the pass goes out at full; the menu shows over a transient banner and yields to the countdown. **Proves:** the menu's layout. A team of six is the server's maximum.
- **E12. A capped holder who fights the final boss is still accepted (race 4, bots).** **Do:** make bot2 the holder (`pass`), `walk bot2` until it is refused at its cap, then `finish bot2`. **See:** the server still finishes the team: the cap never blocks the final boss ("Cap"); the bot console and the web show the team finished. **Log (server):** `Relay team finished`. **Failure:** the team stays unfinished. **Proves:** the Cap rule for the final boss, against a real server.
- **E13. The transient banners replace the waiting banner in its place.** **Do:** in D0, D0b and E10 look at "YOU HAVE THE BATON", "BATON PASSED TO <runner>" and "QUOTA REACHED: PASS THE BATON" against the waiting banner that comes before or after. **See:** each banner shows for 4 s with its title at the same height as the waiting banner's, no jump of the title and no empty band above it (a title that jumps is the item banner's old position). **Proves:** the relay banner layout.

### F. Restarts and interruptions (race 3, slow apply on)

F1, F2, F4 and F5 need an apply that lasts about 10 s: launch the game with `SPEEDFOG_RELAY_SLOW_APPLY=500` ("Before you start"; the log says `[RELAY] Slow apply is on (test aid): one write per interval`) and give `s8.json` (20 writes, about 10 s inside the 15 s deadline; a longer state would end on the deadline). `Apply planned` shows `missing` 20 each time (R lacks them; after F4 or F5 R holds some, so use a new set of 20 ids for each step). Unset the variable and relaunch afterwards.

- **F1. The game dies during a take.** **Do:** `pass bot1 <you>` with `s8a.json` under the slow apply, kill the game 4 s after `[RELAY] Take started`, relaunch (still with the variable) and load. **Precondition:** first apply `missing` 20. **See:** the take is applied again by the new process, a deliberate reuse of the same file: `missing` is now 20 less what the first apply gave (about 12, `Apply planned` after the relaunch), nothing duplicated, and the take acknowledged once. **Log (server):** `Relay take sent again on reconnect`, then one `Relay take acknowledged`; **(mod, after the relaunch):** `[RELAY] Take received` (the same `handoff_id`), then the usual take lines, once. **Failure:** the baton free after 30 s (`Relay take not acknowledged, baton free`): the take was never sent again or never acknowledged. **Proves:** the replay of a take.
- **F2. The network is cut during the apply.** **Do:** `pass bot1 <you>` with `s8b.json` under the slow apply; 3 s after `[RELAY] Take started`, cut the connection to the server for 5 s (disable the adapter, or block the server's port with the firewall). **Precondition:** `missing` 20. **See:** the take is applied once (all 20 end in R's inventory), `relay_taken` goes after the reconnection. **Log (mod):** `[RELAY] Take received again, in progress` (the server's resend) or `[RELAY] Take received again, acknowledged again` then `[RELAY] Take acknowledged again`; **(server):** one `Relay take acknowledged`. **Proves:** the reconnection during a take.
- **F3. Nothing of the waiting save reaches the team.** **Do:** after F1 or F2, look at the team's history in the web. **See:** no zone, flag or IGT of your waiting save in it. **Log (mod):** `[RELAY] Progress of the waiting save dropped` at each take. **Proves:** the progress hold.
- **F4. A quit-out, or a death, during the apply.** **Do:** `pass bot1 <you>` with `s8c.json` under the slow apply; quit to the title (or die) 3 s after `[RELAY] Apply planned`, well before `[RELAY] State applied`. **Precondition:** `missing` 20. **See:** nothing given after the loading screen began, the game and the save intact; after the reload the take is acknowledged. About 6 of the 20 were given, the other 14 stay missing for you and so for the team (expected: a stop is final; R does not receive them later). **Log:** `[RELAY] State applied in part` with `end=MapChanged`, no `func_item_inject called` after it, then `[RELAY] Take acknowledged`. **Proves:** the load boundary (W12, and `MapChanged`).
- **F5. A second apply after a relaunch.** **Do:** `pass bot1 <you>` with `s8d.json` under the slow apply; kill the game 4 s after `[RELAY] Apply planned`, relaunch with the variable, load. **Precondition:** first apply `missing` 20. **See:** the take sent again is applied by the new process, a deliberate reuse of the same file: `missing` counts only what the first did not give (20 less about 8), no duplicate in the inventory. **Proves:** the apply reads the inventory at its start.
- **F6. A quit-out right after a take.** **Do:** after `[RELAY] Take acknowledged`, quit to the title and load. **See:** the IGT is the team's (not the old save's), no "WRONG SAVE LOADED", no quit-out penalty (`[RACE] Quit-out IGT penalty applied` absent). **Proves:** T5.
- **F7. A press cut short by a focus loss, in the menu.** **Do:** open the menu, hold F8, alt-tab away, release, come back. **See:** no confirmation, the highlight did not move, the 5 s auto-close was not restarted by the loss; a tap after returning moves the highlight. **Proves:** the focus rule for the menu.
- **F8. The lock across many loads (waiting).** **Do:** while waiting, die at the Chapel and reload several times. **See:** after each load the gates show no prompt and fast travel is refused. **Proves:** L3.
- **F9. Readiness after a reconnection.** **Do:** cut the connection for a few seconds while waiting at the Chapel, then look at the log. **See:** after the reconnection `[RELAY] Ready sent` with `ready=true` again (readiness does not survive the socket), and `pass bot1 <you>` (bot console, with the command typed and Enter pressed right after) is accepted. Then the narrow part: raise a connection warp flag (A3) and press Enter on the already typed `pass bot1 <you>` within 3 s, before the mod warps you back (about 5 s after the lock held you): `Ready sent` with `ready=false` has gone out, and the pass is refused `target_unavailable` (bot console: `refused: target_unavailable: ...`). **Proves:** L6.

### G. The end of a relay (race 4)

After each case, reset the race from the web (a reset lowers the lock of every connected mod and puts everyone back in setup), start a New Game and start again. In every case: **See** that the gates react, fast travel works, no relay banner or prompt shows, and no `Warp to the Chapel` follows. **Log:** `[RELAY] Lock lowered`, with the reason in the case.

- **G1. The team finishes.** `finish bot1` while bot1 holds and you wait. `reason="relay over"`. **Server:** `Relay team finished`.
- **G2. You abandon, the team plays on** (the web's Abandon while waiting). `reason="relay over"`; no waiting banner (you are out); the abandoned notice shows.
- **G3. The organizer removes you while you wait**: as G2 through `DELETE /api/races/{race_id}/participants/{participant_id}` or the card's cross.
- **G4. A team out.** Disqualify a teammate (the organizer's route): your team is out and your lock lowers. `reason="relay over"`.
- **G5. The race finishes.** Force-finish it (the organizer or an admin): `reason="relay over"` (or `"race not running"` when the race's own message comes first).
- **G6. A reset.** Reset while you wait: `reason="race not running"` or `"relay not started"`.
- **G7. A relaunch after the race ended.** Close the game, launch it with the pack of the finished race, load: the mod reads a team that is over and lowers the lock at the first loaded frame (gates react). A save left locked by a race whose pack you no longer launch stays locked: a mod on a non-relay race leaves the lock alone. Record whether the gates of such a save are inert; the recovery is in "If something goes wrong". **Failure:** gates still inert after the finished race's pack: the lock was not lowered. **Proves:** the lock's lowering cases.

### H. Performance (the profiling build, Tracy connected, slow apply off)

The steps of C and D say when to look. Overall, with Tracy ("docs/MOD_PROFILING.md"):

- **H1.** Waiting banner shown, then the menu open, then the BATON line: `relay_wait`, `relay_menu`, `relay_line` and `maintain_relay` stay in the microseconds, once per frame. A name that changes shows one spike, not a steady cost (the title's glyph offsets are cached with its cut).
- **H2.** A capture and an apply: `relay.capture`, `relay.grace_scan` and `relay.apply_plan` appear on the thread `relay-worker` and never on the frame thread; `relay_job_poll` on the frame thread is an `Option` check; the frame time holds during both.
- **H3.** `relay_apply_frame` and its `relay.give` and `relay.raise_flag` (D8): the measure for `APPLY_WRITES_PER_FRAME` and `APPLY_FRAME_BUDGET`.
- **H4.** In a race that is not a relay race (a normal race with the same DLL), F8 does nothing and the foreground-window query of the key never appears in the trace.

### If something goes wrong

- **A runner stuck locked.** A waiting runner is locked at the Chapel by design: it is freed when the baton is passed to it, taken, or when the team's relay ends. If the status says "Warp to the Chapel failed" and the log has two `[RELAY] Warp to the Chapel landed elsewhere` lines, the mod gave up the return for this process (`WARP_LANDINGS_MAX`): relaunching the game resets the count. If it fails again the Chapel map id is wrong (A2): put the logged `map` into `CHAPEL_MAP_ID` and rebuild.
- **The organizer removes the member.** The route `DELETE /api/races/{race_id}/participants/{participant_id}` (race running) puts the member out and the mod lowers its lock on the server's update. Resetting the race lowers every lock too.
- **By hand, if all else fails.** The lock is the event flag `lock_flag` of the seed (`graph.json`, `relay`; 1050290500 on the pools of this project): set it OFF with Cheat Engine (`Event Flags by ID`, re-type the ID after the action). The mod writes it again at the next loading exit if the server still says `waiting`, so end the race (or remove the member) first, or close the game, then lower it with a flag tool before loading.
- **A take that never ends.** The mod gives up its apply at 20 s (`APPLY_ABANDON`, status "Baton taken: items may be missing") and acknowledges; the server frees the baton at 30 s. Another teammate can take it then.
- **Logs to send.** `speedfog_racing.log` (from the first line: it carries the commit), the server's `Relay` lines of the same minutes, the bot console, the `--state` file used, the time of the event, and a screenshot of the overlay or the status screen when the step is about what is shown. For a performance step, the Tracy trace.

### Closing

When the sections are done, update the "Confirmed in game" cells of the facts tables (L, R, W, T), turn the matching lines of "Not proven yet" into confirmed or refuted, and record the take's measured duration for the largest state, `APPLY_WRITES_PER_FRAME` and `APPLY_FRAME_BUDGET` in the constants table of "Mod". The crate version, the mod release, the web help page's key line and turning `RELAY_RACES_ENABLED` on in production are the project owner's ("Before enabling relay races").
