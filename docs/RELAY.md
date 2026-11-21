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
seeds, the ones a relay race can draw. Seeds generated before the plugin was
enabled carry no block and never count; regenerate a pool to get relay seeds.

## Teams

A relay race has `Race.relay_team_size` (2 to 6, `RELAY_TEAM_SIZE_MIN` and
`RELAY_TEAM_SIZE_MAX`; null on every other race, `Race.is_relay`) and
`Race.relay_runners_create_teams` (default true). Its teams are `RelayTeam` rows
(`Race.relay_teams`, selectin-loaded with the race, in `created_at` order). A team
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

`prepare_relay_start` then fixes the teams: a member who is not READY is set ABANDONED (disqualified members keep their status). They stay attached to their team, so nobody is without one, and `team_cap` computes the cap on the members present. Each started team becomes READY and its baton goes to `first_runner_id` when that member is READY, else to its first READY member by `created_at`. A holder whose mod is not connected at the start is stamped offline from the race's `started_at` (`holder_offline_since`), the countdown's end: the 60 s wait starts with the race, and reads 60 through the countdown.

A reset (`reset_race`) calls `reset_relay_race`: every team goes through `reset_relay_team` and every member gets `relay_zones = 0` and `relay_validated = False` (the left-out members return to REGISTERED with the other participants). Names, colors, placeholders and `first_runner_id` survive, so the setup choices are kept. A seed re-roll calls it too; it only ever happens in setup, where the teams are already fresh.

## Baton

What a mod is told about its team lives in `RelayInfo` (`websocket/race/relay.py`, wire shapes in `PROTOCOL.md`, protocol 1.19). It is sent in `auth_ok` and again, one message per connected member with its own `role` and `gates_locked`, by `send_relay_updates`. A relay race refuses a mod below `RELAY_MIN_PROTOCOL` (1.19) at auth with `RELAY_OLD_MOD_MESSAGE`; other races still accept a 1.18 mod.

- Role: `holder` only for the team's holder while the baton is not free. When `baton_free` is set the nominal holder reads `waiting` with `baton_free_in_s: 0`, like everyone else.
- `baton_free_in_s` (`services/relay.py`): 0 when `baton_free` is set or there is no holder; null while the holder is connected; otherwise `RELAY_OFFLINE_WAIT_S` (60) minus the seconds since `holder_offline_since`, kept between 0 and 60 (a stamp at the race start is in the future during the countdown). A holder absent with no stamp yet (its socket just gone, before its disconnect is recorded) reads the whole 60: the rule is 60 seconds of absence, always.
- `gates_locked`: a holder whose `relay_zones` reached the team's cap.
- `zone_name`: the node of `entry_flag_id` in the graph's `event_map`, else the start node.
- Readiness: `RaceRoom.relay_ready` holds the members loaded at the Chapel with their lock raised. Leaderboard rows and `RelayInfo.members` both read it (`ready` is false for a member whose mod is not connected). It goes with the member's current socket: a disconnect, an eviction after a failed send or a replacement by a newer socket drops the member from it, and the mod sends `relay_ready` again after every `auth_ok`.

### Operations

`RelayModHandler` hands the five baton messages to the operations of
`websocket/race/relay.py`. A payload that does not parse (its pydantic model, the
`CharacterState` bounds, an IGT out of range) is dropped. A refused request gets a
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
  `igt_ms` and `last_igt_change_at`, the holder's `status_update` judgment) is never
  kept, and does not raise the team IGT: it may come from another save, and the next
  receiver would get it. As a checkpoint it is dropped (the previous one stays); as
  the answer to a release it flips nothing: the handoff is dropped, the holder stays
  holder and gets a `relay_update`.
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
  commits, so no message slips in between. It lives in the room's memory only: after
  a server restart during a pending take it is lost, with its 30 s timer, so the
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
  arrival or departure sends the team a `relay_update` (`online`, `holder_online`). A
  returning ex-holder authenticates as `waiting`. The disconnect of a socket that a
  newer one replaced changes nothing.

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
member's fresh-save validation and a cancelled disqualification write the member (the
validation as an UPDATE guarded on the status it read, so it never brings back a member
who went out meanwhile).

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
  change of holder.
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
  the team's end get its final result instead (below).
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

Cancelling a disqualification restores the member's own row and never the team: their
saved status comes back, but a run still going in a team that is out ends ABANDONED, as at
the race's finish.

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

## Bot

`tools/relay_bot.py` plays fake relay runners over the mod WebSocket, so the server and the web can be exercised without the game. From `server/`, against a local database only (it refuses any other unless `--force`), while the dev server runs:

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

## In-game checklist
