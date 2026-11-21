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
- It answers `relay_release` with a `relay_state` carrying the same `handoff_id`, a fixed fake `CharacterState` and the team IGT, and `relay_take` with `relay_taken`; only then does it report progress, its first report carrying the IGT given in `relay_take`.
- Its role comes from `RelayInfo.role` (`auth_ok`, `relay_update`). It stops once its own member is `abandoned` or `disqualified`, or its team is finished, abandoned or disqualified.

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

A waiting runner whose lock is raised and who is away from the Chapel (map `m10_01_00_00`, read with the position the shell already reads every frame) is sent back once the gate window is over: 5 s since the lock was raised, or a loading exit since. The warp raises `chapel_warp_flag`; a raise that starts no load is lowered after 5 s and raised again, up to 3 raises, then the status line shows "Warp to the Chapel failed", the flag is lowered, and the warp is not tried again until the next loading exit. A warp ends on any frame where the player is not loaded after a raise, and as soon as the map reads the Chapel; the warp flag is never written on a frame inside `SETTLE`. A warp whose load ends away from the Chapel counts as a landing: after 2 landings in one locked stretch the return is given up for good (same status line, the landing map id logged at warn level), and readiness stays false; a loading exit does not reset the count, reaching the Chapel or the lock going down does. A dead runner (HP 0) is not warped; HP is read only while a return may start (no warp running, not given up, past the gate window) or a take waits for a frame. A take received and not started yet is sent back like a waiting runner. A warp still running is dropped, its flag lowered if it is still on, when the role turns `holder` (a take started included) or the relay stops being live.

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

A capture is asked (`Effect::CaptureRelayState`, carrying a generation) only for the holder of a live relay, connected, on a frame with a readable position, on the race save, and one at a time: while one is in flight no other is asked. Two bounds keep the machine from depending on the shell. A capture not answered 12 s after it was asked is abandoned and a new one may be asked, and its late answer is dropped: an answer counts only for the capture in flight, identified by its generation (two checkpoint captures both carry a null `handoff_id`). After a failed capture (answer `None`) none is asked for 500 ms. The shell delivers the answer on the game thread, as an input of the machine, with the generation of the effect; a worker never calls into the machine. The answer is `relay_state { handoff_id, state, igt_ms }`, the state fitted to the wire caps first (a single warn names how many values were cut) and `igt_ms` the held IGT of the answer frame.

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

The server's `relay_take { handoff_id, state, igt_ms, defeat_flags, warp_flag, zone_name }` gives the runner the baton. The machine decides; the shell writes the game (`Effect::WriteCharacterStats`, `Effect::SetIgt`, `Effect::ApplyRelayItems`) and sends `relay_taken` (`Effect::SendRelayTaken`). Until the shell's game access for a state exists, the stat write only logs and the apply answers at once with nothing given; the IGT is written.

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

The shell. The apply runs on the shell's worker thread; its outcome comes back on the game thread as an input of the machine (`relay_state_applied`, with the generation of the effect): the apply is over, whatever part of it could not be done (the shell logs that), and the take goes on. An answer for any other apply than the one in flight is ignored, and a newer take waits for the apply in flight to answer. An apply not answered within 20 s (`APPLY_ABANDON`, under the server's 30 s) is abandoned: the take goes on to its acknowledgement with what got written (the IGT at least), and the status line reads "Baton taken: items may be missing". A shell that never answers therefore cannot hold the runner at the Chapel for ever. A socket drop during a take changes nothing of it: an apply answered meanwhile is acknowledged on the first connected frame after the reconnection, and the take the server sends again after `auth_ok` is applied once.

Log lines, which time a take in game: `[RELAY] Take received` (handoff id, with or without a state, the IGT, the warp flag), `[RELAY] Take started` (counts of items, graces and bosses), `[RELAY] Take applied` (`elapsed_ms` of the apply), `[RELAY] Take acknowledged` (`elapsed_ms` since the receipt), `[RELAY] Take given up` (the reason), `[RELAY] Apply not answered, abandoned`, `[RELAY] IGT does not read the team's, take acknowledged anyway`, `[RELAY] Holder role window ended`, `[RELAY] Holder role not confirmed in time` (the confirmation window ran out with no word from the server), `[RELAY] Take received again, in progress` (the server sent the take in progress again: nothing changes), `[RELAY] Take received again, acknowledged again` (it sent one already acknowledged: it is answered again on the next connected frame) and `[RELAY] Take acknowledged again` (that answer going out). The baton key logs `[RELAY] Baton menu opened` (teammates, eligible; debug level), `[RELAY] Baton menu closed by itself` (debug level), `[RELAY] Request refused` (the server's `code` and `message`, warn level), `[RELAY] Handoff requested` (the teammate), `[RELAY] Take requested` and `[RELAY] Request not answered, forgotten` (the 10 s bound).

What only the game proves for a take: the IGT write takes effect by the next frame, 0 included (an acknowledgement waits for it, but nothing proves the game does not undo it); the game's IGT never runs faster than wall time and no other writer adds time during a take (the window's upper bound relies on both); the lock lowered and the warp flag raised on the same frame are both honoured; the connection warp lands at the gate's exit and sets the zone flag; the game saves the written IGT across a quit-out.

### The baton key

One key, F8 by default, does everything. The machine receives it as a per-frame input (`TickInput.relay_key_down`; repeated key-down events of the OS are the same press) and produces the menu's state and the requests; the shell binds the key and draws (`mod/src/core/relay_menu.rs` holds the pure timers).

The holder. A press opens the menu, a list of the other team members, the highlight on the first teammate who can receive. The opening press neither advances nor confirms. A tap (a press and a release shorter than 1 s) moves the highlight to the next teammate, wrapping; holding the key 1 s confirms the highlighted one and sends `relay_handoff_request { to_participant_id }`, then closes the menu. The menu closes by itself 5 s after the last press or release while the key is up. The menu is possible only for the holder of a live relay, past the countdown (the server answers `busy` during it), with no release waiting, no take in progress or in its confirmation window and no request unanswered; anywhere else it closes and a press already down when it became possible is ignored until released.

Each row shows the teammate's counter as the server gives it ("2/5 zones") and, when it cannot receive, why, in the order of the server's refusal for a handoff target: out of the race (finished, abandoned or disqualified), not in game (offline or not ready at the Chapel), no fresh save (not validated; a member may simply not have reported yet, so the row never says its save was refused), at the cap (`zones >= cap`). An unknown member status is unavailable too. A teammate who cannot receive is shown but never highlighted or confirmed. The rows are built when a `RelayInfo` is received and read from the echo (`members`, `cap`); the machine guesses nothing. A `relay_update` under the open menu keeps the highlight on the same participant id wherever the list now puts it; when that teammate is no longer available the highlight returns to the first and the press in progress is spent, and so is a press that began while nobody was highlighted (it was aimed at someone else: it neither taps nor confirms, and a new press is needed). A team nobody can receive, or a team of one after abandons, opens the menu with its reasons (or no row) and confirms nothing.

A waiting runner. Holding the key 1 s sends `relay_take_request`, only when all hold: the relay is live (team `ready` or `playing`, the race running) and past the countdown; `baton_free_in_s` reads 0 now (counted down from the seconds in the `RelayInfo` as received, `relay_free_in_s`; a countdown shows the wait and offers nothing; in setup nothing is offered, the info reading no holder and 0 for everyone); no take is in progress; the runner's own entry is validated with `zones < cap`; and the last `relay_ready` this mod sent was `true` (its own readiness: the echo in `members[].ready` reads false after an `auth_ok`). A hold that started before the take was offered does not count.

One request at a time. After a handoff or take request nothing more is sent, and the menu does not open, until the server answers (`relay_release` for a handoff, `relay_take` for a take, or `relay_refused`) or the runner's role changes or its relay ends, or `REQUEST_TIMEOUT` (10 s) passes; a socket drop forgets it. A `relay_refused { code, message }` shows `message` in the status line (3 s, open menu or not) and frees the key; the mod logs `code` and branches on none.

Per frame, the key costs two timers and a few comparisons; the row strings are built on receipt and cached.

### Overlay

What a relay runner reads is data built once, in `mod/src/core/relay_view.rs` (`RelayView`), and cached on the machine (`relay_view()`): the strings are rebuilt on `auth_ok`, on each `relay_update`, when the machine's role changes (a take received, given up, acknowledged, its confirmation window over), when the displayed layer changes, when the key's label is set, and once per displayed second of an offline holder's countdown (the machine counts down from the seconds in the `RelayInfo` as received and compares the displayed second once per tick). Nothing is formatted per frame; the hold progress is a number (`relay_hold_progress`). Geometry is pure (`mod/src/core/item_banner.rs`, `relay_block_layout`, `relay_block_bounds`): the title hangs from the same height as the item banner's icon, rows are 1.6 line heights, sizes follow the screen's width (its height times 16/9 on an ultrawide); the drawing measures the texts, cuts every name and zone to `text_max_width` with its truncation helper, and the bounds stay inside the display.

Nothing relay-specific is shown while the team is not live (setup, finished, abandoned, disqualified), when the runner is out while the team plays on, or on an unknown role or team status. The BATON line of the panel reads the holder ("Kahleeya"), "you" for the holder, "free" when the baton can be taken, "nobody" when none is named and it is not free, then the runner's own counter against the cap as given ("you 2/5 zones", "3/5 zones" as holder, "6/5 zones" past the cap) and the key hint ("F8 pass" for the holder, "F8 take" when it can take).

The waiting banner, top centre, for a runner who waits:

- Holder online: "WAITING FOR THE BATON", "<holder> is in <zone>" ("<holder> holds the baton" without a zone), "Zone 9 of 12. You: 2/5 zones.".
- Holder offline, wait running: "<HOLDER> IS OFFLINE", "The baton can be taken in 42 s", "It goes back to <holder> if they return before then.".
- Baton free: "THE BATON IS FREE" and one of "<holder> has been offline for over a minute", "The holder left the race" (nobody is named), "The handoff was not completed" (holder online, or the runner itself). Its last line is "Hold F8 to take the baton and restart <zone>." with the hold bar, or "No fresh save: you cannot take the baton." (not validated), or "You are at your cap.", checked in the server's order. Until the runner is at the Chapel with the lock asserted the prompt reads "Not ready yet: wait at the Chapel.", and "Waiting for the server" while its request is in flight.

The holder's menu, opened by the key: "PASS THE BATON", one row per teammate not out (name, then the counter or the reason as in "The baton key"), the highlight, the hold bar, and "F8 next hold F8 to pass closes by itself after 5 s" (with no one eligible only the last part, and "Nobody can take the baton right now" or, with no teammate left, "No teammate can take the baton"). The transient banners ("YOU HAVE THE BATON", "BATON PASSED TO <runner>", "QUOTA REACHED: PASS THE BATON") use the 4 s race item banner.

Which block is on screen: the waiting banner and the item banner hang from the same band, and the fullscreen countdown's ring crosses it, so the waiting banner shows only with no menu open, no item banner and no countdown (`relay_wait_visible`); the open menu shows over an item banner and yields to the countdown (`relay_menu_visible`). `gap_uses_local_igt` says when a leaderboard gap takes the runner's local IGT: its own row, playing, and on a relay race only the live holder (a waiting runner's own IGT is not its team's), and `am_i_abandoned` reads a relay member out while its team plays on as out.

### Game access

The shell's relay worker (`mod/src/dll/tracker.rs`) runs one job at a time, on a thread of its own, so the character is never read by two jobs at once. A job asked while another runs waits behind it, and a newer request replaces the one waiting: the machine asks again only once it has given up its previous request, so a release that pre-empts a checkpoint is started as soon as the checkpoint's job ends, and the checkpoint's answer is dropped by its generation. The answer goes to the machine on the game thread, at the start of the first frame after the job ended, with the identity the job was asked with; a thread that panicked, or that the OS did not start, answers as a failed job. Per frame the worker costs an `Option` check and an atomic load.

A capture (`mod/src/eldenring/relay.rs`; what its reads must pass and the state they build, in `mod/src/core/relay_capture.rs`) reads, in order: the goods param's types and the grace flags (the first capture of the process only, then kept: the regulation does not change in a session), the loaded map, the attributes, level and runes, the held inventory's normal and key lists, whether each grace flag is set, then the loaded map again. Any of these fails the capture (answer `None`: a release is asked again 500 ms later, a checkpoint is dropped), never a state partly read:

- no map loaded when the reads begin; the map read differently, or not at all, at their end; or the reads took over 1 s (`READ_WINDOW_MAX`, taken as shorter than any load): a load may have come in between;
- a param table that does not read (no row);
- stats unreadable or negative, or outside what a character can have ("What a state carries"; the values read are logged): a state the receiver would not write is not sent;
- the inventory unreadable (a list header that does not look like the layout, a count above its list's capacity, both lists empty);
- the event flag reader down, or none of the grace flags read.

A grace flag the reader cannot read counts as not lit, and how many there were is logged: the reader answers the same for a flag of a category the game does not hold, and one grace row the game does not use must not fail every capture. The items are the transferable ids among those held ("What a state carries"), a goods id looked up in the goods types read (a goods id with no row is not transferable). The state is then fitted to the wire caps. A capture writes nothing. Every read goes through `ReadProcessMemory` (libeldenring's pointer chains, the inventory copy, the event flag reader), which fails rather than faults on an unmapped address, as the item spawner's thread already reads flags off the render thread; the param rows are the game's static tables, read by value.

What a capture relies on, and whether the game has confirmed it:

| Fact                                                                                                                                                 | Source                                                                             | Confirmed in game                                         |
| ---------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | --------------------------------------------------------- |
| Stats: GameDataMan, `+0x8` (PlayerGameData), `+0x3C`: eight `i32` from vigor to arcane, the level at `+0x68`, the runes held at `+0x6C`              | libeldenring `Pointers::character_stats`; fromsoftware-rs `cs/player_game_data.rs` | Read by the practice tool, never by this mod              |
| Inventory lists at PlayerGameData `+0x410` (normal, then key), entries of `0x18` bytes, item id at `+4`, quantity at `+8`                            | `mod/src/eldenring/race_items.rs`, `mod/src/core/item_inventory.rs`                | Yes, through the race items (goods quantity, junk weapon) |
| An entry is empty when its item id has no valid category nibble                                                                                      | fromsoftware-rs `cs/player_game_data.rs`, `cs/item_id.rs`                          | No                                                        |
| Category nibbles: weapon `0x0`, armor `0x1`, talisman `0x2`, goods `0x4`, ash of war `0x8`                                                           | fromsoftware-rs `cs/item_id.rs`                                                    | Weapons yes (junk weapon), the others no                  |
| `EquipParamGoods.goods_type` and its values (at `0x3E` of the row as the codegen lays it out, after `icon_id` at `0x30`, which the race items write) | libeldenring param codegen; TarnishedTool `GoodsType`                              | No                                                        |
| A grace is lit when the event flag `BonfireWarpParam.eventflag_id` of its row is set; the table goes by the name `BonfireWarpParam`                  | libeldenring param codegen                                                         | No                                                        |
| The loaded map id reads `None` during a loading screen                                                                                               | `GameState::loaded_map_id`, the readability read of every frame                    | Yes, at every loading exit of the zone tracking           |
| A load (the map unloaded, then one loaded again) lasts over 1 s                                                                                      | `READ_WINDOW_MAX`                                                                  | No (checklist: a capture across the start of a load)      |

Log lines: `[RELAY] Worker job started` (the job: its `handoff_id` and generation), `[RELAY] Worker job queued behind the running one` (the running, queued and replaced jobs), `[RELAY] Worker thread not started, job failed` (warn level) and `[RELAY] Worker thread panicked, job failed` (error level). A capture logs `[RELAY] Goods types read` and `[RELAY] Grace flags read` (the counts, once per process), the inventory's `[ITEMS] Inventory list headers`, then `[RELAY] Character read` (generation, attributes, level, runes, the `held` item ids, the transferable `items`, `graces_scanned`, `graces_unreadable`, the `graces` lit, `elapsed_ms`) or `[RELAY] Character not read` (generation, the reason, `elapsed_ms`; warn level), and `[RELAY] State cut to the wire caps` (how many values; warn level) when the state was over the caps. The machine logs `[RELAY] State captured` when it sends the state.

## Not proven yet

- The row-lock discipline ("Ordering": `SELECT ... FOR UPDATE` on the team rows, in one order) has only run on SQLite, which ignores `FOR UPDATE`. The tests check the statements PostgreSQL receives, never two transactions contending for a team on PostgreSQL. (The migrations were run up, down and up again on PostgreSQL 17, and `alembic check` finds no drift on the relay tables and columns.)
- The relay bot has never been run end to end against a server ("Bot"): only its pure decisions are tested.

## In-game checklist

The mod lot writes the full list. Known to be owed from the server side:

- A receiver applies `relay_take` (state, `igt_ms`, `defeat_flags`, `warp_flag`) and lands at the entrance `zone_name` names, a boss its team killed staying dead.
- A giver locks and goes to the Chapel only on `role: waiting`; a cancelled or refused handoff leaves it unlocked.
- Each member's first report from a new save validates them; an old save shows `fresh_save_required`.
- A receiver whose game dies before `relay_taken` gets the same `relay_take` again after reconnecting and applies it once.
- A holder at the cap finds its gates locked (`gates_locked`); a member out, or a team finished or out, lowers its lock.
- The lock: a waiting runner at the Chapel finds the gates inert and fast travel refused; a holder finds them reacting; a quit-out and a relaunch keep the lock the server's word says (a stale lock on a holder is lowered on the first loaded frame); a flag written in a loaded, settled frame is reacted to by the seed's events, and a failed write (`set_flag_cached`) stays silent and is asserted again at the next load. The return to the Chapel: the map id the mod reads at the Chapel is `m10_01_00_00` (`0x0A010000`); the seed lowers the warp flag itself after the warp and reacts to a lower followed by a raise; a waiting runner sent into the world is warped back after about 5 s; a dead runner is held until it lives. `relay_ready` reaches the server after a reconnection, true at the Chapel and false elsewhere.
- A take acknowledged: the IGT the game reads right after the write is the team's (within the window), never faster than wall time with no other writer adding time, the lock lowered and the warp raised on one frame are both honoured, the warp lands at the gate's exit with the zone flag set, and a quit-out right after keeps the written IGT.
- A capture ("Game access"): at a zone entry as the holder, `[RELAY] Character read` gives the attributes, level and runes the status screen shows; `held` matches the inventory's entries (key items included); `items` holds every weapon, armor piece, talisman, ash of war, sorcery, incantation, spirit ash and crystal tear carried, and no consumable, key item, material or arrow (compare a few ids, a quiver included); `graces` is the number of graces lit on the map, with `graces_unreadable` 0 (otherwise grace rows the game does not hold, logged as unreadable); the first capture of a process is preceded by `[RELAY] Goods types read` and `[RELAY] Grace flags read` with nonzero counts (the tables are found under those names). A release is answered within its 12 s and the server keeps the state.
- A capture across the start of a load: confirm a handoff and start a fast travel at once, several times. Each capture either reads in full (`Character read`, the counts as above) or logs `[RELAY] Character not read` with `LoadDuringCapture` or `NotLoaded` and sends nothing, the release then captured after the load (or cancelled when the load outlasts its 12 s); a state with zeroed stats or an empty inventory never goes out.
- A capture's duration: `elapsed_ms` stays far under the 1 s read window (a few tens of ms expected; the first capture of a process also reads the param tables, before the window opens), and the frame rate holds during it (Tracy: `relay.capture` and `relay.grace_scan` on the worker thread, `relay_job_poll` on the game thread).
- The baton key (once bound): F8 opens the holder's menu, a tap moves on, a 1 s hold passes the baton, the menu closes after 5 s; a waiting runner's 1 s hold on a free baton takes it; neither works during the countdown.
- The two points of "Not proven yet", through the bot first, then with real games.
