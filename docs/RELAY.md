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
- A member plays the whole race on the save that was validated: the validation draws
  a token that binds them to it.
- Each runner keeps their own character: a handoff carries the team's time and world
  (its IGT, the lit graces, the bosses killed, the zone to restart), nothing of the
  character.
- The loot of the graph's bosses (items and runes) goes to every member of the team.
- Waiting runners wait at the Roundtable Hold.
- The relay wire contract starts at protocol 1.19 (`RELAY_MIN_PROTOCOL`).

Relay races are off unless the server setting `RELAY_RACES_ENABLED` is true
(`settings.relay_races_enabled`, false by default, listed in both `.env.example`
files): until the shipped mod speaks protocol 1.19, nobody could join one. While off,
`POST /api/races` refuses a `relay_team_size` (400 `Relay races are not available
yet`) and `GET /api/pools` reports `relay_available` 0 for every pool. Races already
created stay as they are.

## Seeds

A relay seed carries a top-level `relay` object in its `graph.json` (generator
version 4.16), written when the relay plugin is enabled. The pools enable it in
`tools/pools/_base.toml`. The block holds the event flags the mod and the server
share:

| Key                    | Value      | Meaning                                                                                                                                                                   |
| ---------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `lock_flag`            | 1050290500 | while ON, no graph warp takes the player: the fog gates are inert; it touches no fast travel                                                                              |
| `chapel_warp_flag`     | 1050290501 | raised, it warps the player to the Chapel grace and clears itself                                                                                                         |
| `warp_flag_base`       | 1050290510 | `warp_flag_base + n`, raised, warps the player to the entrance of connection n and clears itself; n is the connection's zone-tracking flag minus `zone_flag_base`         |
| `warp_flag_count`      | 490        | the number of warp flags, from `warp_flag_base` up                                                                                                                        |
| `zone_flag_base`       | 1050294000 | first of the zone-tracking flags                                                                                                                                          |
| `travel_lock_flag`     | 1050290503 | while ON, the Chapel and Roundtable Hold maps refuse fast travel; it touches no graph warp                                                                                |
| `roundtable_warp_flag` | 1050290504 | raised, it warps the player to the Roundtable Hold and clears itself                                                                                                      |
| `token_flag_base`      | 1050297900 | bit `b` of the member's 24-bit save token is the flag `token_flag_base + b` ("One character per member")                                                                  |
| `token_bits`           | 24         | the number of token flags, from `token_flag_base` up                                                                                                                      |
| `loot`                 | object     | what each boss gives, keyed by the boss's defeat flag: `runes`, `rune_speffect`, `received_flag`, `pickup_flags` and `items` (`id`, `qty`); empty for a seed with no boss |

`Seed.relay` is true when `relay` is the whole 4.16 block: an object holding a
`loot` object (possibly empty) and each flag of the table but `warp_flag_count` as
an integer (`seed_has_relay` in `services/relay.py`). A seed exported without a
build, an earlier block, or a block missing one of those flags is not a relay seed.
The pool scan sets it when it adds a seed, and an indexed column serves every
filter, so no query parses `graph_json`. The migrations backfill the seeds scanned
before the column existed and recompute it when the rule changes; the one for the
4.16 block tells that block by two of the keys 4.16 added, its `loot` object and
its integer `roundtable_warp_flag` (the others are `travel_lock_flag`,
`token_flag_base` and `token_bits`), and reads only the rows marked relay, since
the rule only narrowed. `relay_flags` returns those flags, the
fields of `RelayFlags` (neither `warp_flag_count` nor `loot`), and None exactly when
`seed_has_relay` is false: a relay seed's flags always build the `RelayFlags` a mod
is sent.

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
for them and `relay_validated` the fresh-save gate, `relay_token` the token that
gate draws and `relay_bound` whether their mod wrote it into the save ("One
character per member"). The three keys between
participants and teams (`participants.relay_team_id`, `relay_teams.first_runner_id`,
`relay_teams.holder_id`) are `ON DELETE SET NULL` and form a cycle, so the two
keys towards participants are created after both tables (`use_alter`).
`RelayTeam.members` is read only and loaded only by an explicit `selectinload`.

The leaderboard ranks teams. `relay_rows` turns the teams and the participants
into `RelayTeamRow`s, shaped like a participant (`id`, `status`, `current_zone`,
`current_layer`, `igt_ms`, `death_count`, `color_index`, `zone_history`,
`layer_entry_igts`, all read from the team) with the `members`, the `cap` and the
`holder`. An empty team is a row only in setup. In setup the row's `status` reads
READY once the team's first runner is READY (the team can start), REGISTERED before;
the team's own status, which `RelayInfo.team_status` carries, stays REGISTERED until
the start, so a mod's leaderboard reads `ready` while nothing relay-specific is live
yet. `leaderboard_entries` returns the participants of a solo race and the team rows
of a relay race.
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
- A team has a first runner (`first_runner_id`) exactly when it has a member: the
  runner who creates a team, or enters a team that has none (a placeholder), is its
  first runner, and a first runner who leaves (or moves) hands it to the earliest
  remaining member by `created_at` (none when the team is left empty). Choosing a
  first runner takes the team's row lock, as placement does, and reads the chosen
  member again under it. A new team takes the next color of the palette (highest plus
  one) and its members take the team color.
- Members and the organizer rename a team and choose its first runner; the first
  runner must be a member.
- Placement locks the team rows it decides on (`SELECT ... FOR UPDATE`, ascending id,
  so a move locks the target and the team left in one order) and counts the members
  after the lock: two runners cannot both take the last slot, and a team deleted
  while someone joins it answers 404 instead of leaving them without a team. Team
  deletion and `vacate_team` take the same lock.
- Every change ends like `join_race`: the leaderboard and the race state are broadcast,
  and a runner who registers through a team route gets the same line in the
  participants chat, `{name} has joined the race`.

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
| One user registering twice at once (the second insert loses)  | 409 `Already a participant in this race`        |

## Start

`POST /races/{id}/start` on a relay race replaces the participant minimum by `relay_start_error` (400 with its text), for every role, admins included: late join is excluded from relay races, and a lone tester uses the bot.

- A team counts when it has at least one member; teams without member are ignored.
- At least 2 teams that count, otherwise `At least 2 teams are required to start a relay race`.
- Each such team needs its first runner READY, the runner its run starts with, otherwise `<team name>'s first runner is not ready` (`<team name> has no first runner` for a team whose first runner is missing, which only data older than the rule of "Who may do what" can show). Its other members need not be ready: a first runner alone may start their team's run.

`prepare_relay_start` then fixes the teams: each started team becomes READY and its baton goes to `first_runner_id`. The members who are not READY keep their status (REGISTERED, or DISQUALIFIED after a reset): a REGISTERED member is still in the race, as a solo runner who has not connected yet, and may connect and join the run later (their first report validates their save; "Cap"); the no-show rule takes them out 30 minutes into the race otherwise ("Lifecycle"). A holder whose mod is not connected at the start is stamped offline from the race's `started_at` (`holder_offline_since`), the countdown's end: the 60 s wait starts with the race, and reads 60 through the countdown. After the start broadcasts, every connected member's mod gets a `relay_update` (`send_row_relay_updates`, team by team): its `holder_id`, its own `role`, `team_status` READY. The start marks every participant connection playing (a REGISTERED member's page stays behind the spoiler wall), then gives the ones already out their own status back (a runner disqualified before a reset).

A reset (`reset_race`) calls `reset_relay_race`: every team goes through `reset_relay_team` and every member gets `relay_zones = 0`, `relay_validated = False`, `relay_token = None` and `relay_bound = False` (the members out return to REGISTERED with the other participants). Names, colors, placeholders and `first_runner_id` survive, so the setup choices are kept. A seed re-roll calls it too; it only ever happens in setup, where the teams are already fresh.

## Baton

What a mod is told about its team lives in `RelayInfo` (`websocket/race/relay.py`, wire shapes in `PROTOCOL.md`, protocol 1.19). It is sent in `auth_ok` and again, one message per connected member with its own `role` and `gates_locked`, by `send_relay_updates`. `auth_ok` goes out before the socket is registered, so its `RelayInfo` reads the runner as the registration leaves them: connected (`members[].online`, and `holder_online` for a returning holder) and not ready. A relay race refuses a mod below `RELAY_MIN_PROTOCOL` (1.19) at auth with `RELAY_OLD_MOD_MESSAGE`; other races still accept a 1.18 mod.

- Role: `holder` only for the team's holder while the baton is not free. When `baton_free` is set the nominal holder reads `waiting` with `baton_free_in_s: 0`, like everyone else.
- `baton_free_in_s` (`services/relay.py`): 0 when `baton_free` is set or there is no holder; null while the holder is connected; otherwise `RELAY_OFFLINE_WAIT_S` (60) minus the seconds since `holder_offline_since`, kept between 0 and 60 (a stamp at the race start is in the future during the countdown). A holder absent with no stamp yet (its socket just gone, before its disconnect is recorded) reads the whole 60: the rule is 60 seconds of absence, always.
- `gates_locked`: a holder whose `relay_zones` reached the team's cap.
- `zone_name`: the node of `entry_flag_id` in the graph's `event_map`, else the start node.
- `token`, `bound`: the receiving member's own save token (null until their save is validated) and whether their mod confirmed writing it ("One character per member").
- Readiness: `RaceRoom.relay_ready` holds the members loaded at the Roundtable Hold with their lock raised. Leaderboard rows and `RelayInfo.members` both read it (`ready` is false for a member whose mod is not connected). It goes with the member's current socket: a disconnect, an eviction after a failed send or a replacement by a newer socket drops the member from it, and the mod sends `relay_ready` again after every `auth_ok`.

### Operations

`RelayModHandler` hands the six relay messages of a mod (`relay_ready`,
`relay_handoff_request`, `relay_take_request`, `relay_state`, `relay_taken`,
`relay_bound`) to the operations of `websocket/race/relay.py`. A payload that does
not parse (its pydantic model, the `CharacterState` bounds: at most 1000
`grace_flags`, each an integer from 0 to 2^31 - 1; an IGT out of range) is dropped,
so a stored state always fits the mod's types: a team replays it at every take.
`CharacterState` has that single field: a handoff carries the lit graces and nothing
of the character, each runner keeping their own. A state with other fields (one
stored before this shape, or sent by an older mod) reads as its graces, the rest
ignored. A refused request gets a `relay_refused` to the asker, the first matching
row winning (codes in `RelayRefusal`, each with its `RELAY_REFUSAL_MESSAGES` text):

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
  target is out by then, or at or over the cap, which may have dropped since the
  request (a teammate's save validated, "Cap"): the giver then gets `relay_refused`
  `target_at_cap` and a `relay_update`, and keeps the baton.
- **`relay_state` with `handoff_id` null** from the holder: a checkpoint, stored the
  same way, no flip, no answer. The mod sends one at each zone entry, so a takeover
  after a crash has something recent.
- **Any other `relay_state`** (an expired or unknown handoff, or not from the holder)
  flips nothing. From the holder the state is still kept as a checkpoint. The sender
  gets a `relay_update`, which tells a giver who already went back to the Roundtable Hold that it
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
  giver's mod lock and go to the Roundtable Hold. A receiver whose mod is no longer
  connected gets a free baton at once (`baton_free`), and no take is awaited from them.
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
  back as a late one does. The room is kept while a take is
  awaited, even with nobody connected (`ConnectionManager.drop_room_if_idle`; the
  timer's end, fired or stopped, lets an empty room go): a receiver who reconnects
  after every socket of the race dropped still gets its take again, and no timer
  outlives its room. The awaited take lives in the room's memory only: after a
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
  a receiver whose take is awaited gets it again first (above). A member still in the
  race, in a team still in it, who connects then gets the team's loot ("Boss loot"). A
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
  `zone_name` names it. Before the team's first gate `warp_flag` is `chapel_warp_flag`
  (waiting runners are at the Roundtable Hold, so a take before the first gate warps
  them to the Chapel) and `zone_name` is null.
- `defeat_flags` (`team_defeat_flags`): the defeat flag of every node the team's
  history marks killed, the current zone's included, sorted. On a takeover the state is
  the last checkpoint, but the flags come from the history: a boss killed after the
  checkpoint stays dead for the taker.
- `igt_ms`: the team's IGT, which the receiver's game takes.
- Nobody at or over their cap receives the baton, the final zone included.

### Boss loot

The team shares the loot of its bosses: what a boss of the run's graph gives (items
and runes) reaches every member, each keeping their own character. The seed says what
each boss gives (`relay.loot`, keyed by the defeat flag, "Seeds"): `loot_entry`
(`services/relay.py`) reads one entry as a `RelayLootEntry`, and `team_loot` the entry
of every boss the team's history marks killed, in the order of `team_defeat_flags`,
among the bosses whose kill the server counts (the defeat flags of
`extract_boss_flags`): the final boss, whose kill the finish stamps on the team's
history, is left out. They go out in `relay_loot` (`entries`, `paid`, `announce`; wire
shapes in `PROTOCOL.md`):

- **At a counted kill** (`send_kill_loot`, from `RelayModHandler._on_boss_killed`):
  the boss's entry to each connected member still in the race. The member who
  reported the kill gets `paid: true` and `announce: null`: their own game paid the
  boss, so their mod only marks it received. Each teammate gets `paid: false` and
  `announce` `{runner, boss}`, for a banner: the killer's name (as `members[].name`)
  and the boss's (`relay_boss_name`: the node's `boss_name`, the boss fought, else
  its `display_name`, the zone, else its id). A
  re-report or a replay of the flag is no new kill and sends nothing.
- **After a connection** (`send_team_loot`, from `member_connection_changed`): a
  member still in the race, in a team still in it, whose mod connects gets, after the
  `relay_update` of the connection, one `relay_loot` with the entry of every boss the
  team killed, `paid: false`, `announce: null`. A member who was offline at a kill, or
  who joins the run late, catches up; one who was connected gets those entries again.
- **Nothing** goes to a member who is out (abandoned or disqualified), to a team that
  is over (finished, abandoned or disqualified: its run is done, so a member of a
  finished team who connects gets nothing either), to another team, or before the
  team's first kill. The final boss has no entry: its kill is the finish, and no
  `relay_loot` ever carries it. A kill whose node has no usable entry (missing, or out
  of the wire bounds) is counted and broadcast as any kill, sends no `relay_loot`, and
  logs a warning (`loot_entry`); a catch-up leaves that boss out, with the same
  warning.
- **A failed send** of a kill's loot is logged, and the kill's `relay_update` still
  goes out: the kill is committed by then.

The server stores nothing about who received what: each mod decides from its own save
whether an entry is still to give (its `received_flag`), so an entry may reach a mod
any number of times. The kill's sends run under `relay_section`, once the kill's
session is closed and before its `relay_update` ("Ordering"); the catch-up runs under
the `relay_lock` that `member_connection_changed` holds.

### One character per member

Each member plays the run on a character and a save of their own, and the fresh-save
gate checks that save once, at their first report after the start ("Progress and
guards"). The IGT cannot hold a member to that save afterwards: a new character
starts at an IGT of 0 and would pass the gate as well, a waiting runner's IGT is
never judged once validated, and a take gives the receiver's game the team's IGT.
Without more, a waiting runner could load another character, or create a new one
and collect the team's boss loot again ("Boss loot": each mod gives what its own
save has not received). The member is therefore bound to the save their validation
proved fresh by a token:

- **The draw.** The validation draws the member's token (`draw_relay_token` in
  `services/relay.py`: 1 to `RELAY_TOKEN_MAX`, 2^24 - 1, from `secrets`; 0, a save
  with none of the seed's token flags raised, never) into `Participant.relay_token`.
  A waiting member's is drawn by the guarded UPDATE that validates them
  (`_validate_member`, on `relay_validated` false), the first holder's by the team's
  first report (`_on_first_init`) only when they have none: a member validated as a
  waiting runner, who then received the baton of a team not playing yet, keeps the
  token drawn then. One validation, one draw.
- **To that member only.** `RelayInfo.token` is built for the receiving mod (like
  `role`): the member's own token once their save is validated, null before, never
  in `members[]`. The `relay_update` of the validation carries it.
- **`relay_bound {token}`.** The mod writes the token into the save (the seed's
  token flags, `token_flag_base` and `token_bits`, "Seeds") and confirms with this
  message. `RelayModHandler` hands it to `confirm_bound` (`websocket/race/relay.py`),
  under `relay_lock`: one UPDATE of the member alone sets `relay_bound` where the
  member is validated, holds that token and is not bound yet, and that member's mod
  then gets a `relay_update` (`RelayInfo.bound` true). Any other `relay_bound` (another
  token, a member not validated, a member already bound) changes nothing and is
  answered by nothing; a token outside 1 to 2^24 - 1 does not parse and is dropped.
- **Reset.** A reset clears the token and the binding with the validation ("Start"):
  the next start draws new tokens.

The server draws, stores, sends, and records the confirmation; the check is the
mod's. Once bound, the mod treats a save that does not carry the token as a wrong
save. The server never sees the save: it cannot tell a save that carries the token
from one that does not, and a member whose mod never confirms simply reads
`bound: false`.

### Ordering

`RaceRoom.relay_lock` serializes the operations above (and the take timer) per race, in
memory. All but `relay_ready` and `relay_bound` read the team through `team_for_update`,
which row-locks it (`SELECT ... FOR UPDATE`, a no-op on SQLite); `set_ready` reads only
the member's team id, without a lock, and `confirm_bound` writes the member's row
alone. The committing loads of the progress messages take the same row lock ("Progress and guards"), so a flip and a progress write of one team are
ordered by the database. The lock order is always `relay_lock`, then the team row.
The `relay_update` a progress message triggers (a teammate's first validation, the
team's first report, a gate, a counted kill) is read and sent under `relay_section`
too, once the message's own session is closed (so that order holds), as a flip's
updates are: an update read before a flip's commit can therefore never reach a mod
after the flip's `relay_take`, where it would name the giver as holder and make the
receiver's mod give the take up. The lock is one per race, so it now also serializes
the progress updates of every team of the race: a member socket that stalls (each send
waits up to `SEND_TIMEOUT`, 5 s, before the socket is evicted) delays every team's
updates and baton operations behind it.
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
read, so it never brings back a member who went out meanwhile), and so do a waiting
runner's own death counter (an UPDATE that leaves a member who is out alone) and a
member's `relay_bound` (an UPDATE guarded on their token).

## Cap

A runner may play `ceil(total_layers / active_members) + 1` zones (`relay_cap`),
`total_layers` being the seed's. `active_members` counts the team's members who play:
PLAYING (their save passed the fresh-save gate, at their first report) or FINISHED
(`shares_cap`). A member who never connected (REGISTERED), or who is connected
without a validated save yet (READY: at the title screen, creating their character),
takes no share: they cannot take the baton, so a runner playing alone is not held to
a cap made for them. In setup and before the first reports, the cap therefore reads
as if the runner were alone. `team_cap` never divides by zero (at least one member)
and moves when a member's save is validated (the cap drops; the validation's
`relay_update` carries it) or a member goes out (the cap rises). A holder already
past a dropped cap reads `gates_locked: true` at once and must hand off to a teammate
under it; a release already asked flips only if its target is still under the cap
("Operations").

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
  then) and recorded nowhere; their `status_update` only runs their own fresh-save gate and keeps
  their own death counter ("Deaths" below), and no row is broadcast for it.
  The legacy `finished` message is ignored.
- **Fresh save for every member.** The team's first report, its first holder's,
  passes the team's gate (IGT at most 60 s, `MAX_FRESH_IGT_MS`): the team becomes
  PLAYING and that holder is validated. Any other member's first report once the
  race runs (countdown over) sets `relay_validated` and moves them from READY to
  PLAYING when its IGT is at most 60 s; above, they get `error` `fresh_save_required`
  and stay unvalidated. Once validated, a waiting runner's IGT is never judged. Each
  validation draws the member's token, which binds them to that save (Baton, "One
  character per member"). The seed check is the mod's (it compares its pack with
  `RaceInfo.seed_id`).
- **Wrong save.** `is_igt_plausible` judges the holder's IGT against the team's
  `igt_ms` and `last_igt_change_at`.
- **Deaths.** Each save counts its own deaths. A member's `death_count` holds the
  last raw count their mod reported: as holder, stored in the commit that applies
  the report; without the baton, stored when it changes (`_store_own_deaths`, an
  UPDATE of the member alone, never of a member who is out), so a death made while
  waiting (a giver dying on its way back to the Roundtable Hold) is not taken for one
  made as holder at the next take. The team's count moves by what the holder's
  counter moved (`team.death_count + reported - member.death_count`), so it carries
  on across a change of holder. When the member goes out, or the team ends, their row
  takes the team's count instead ("Lifecycle").
- **History.** Every entry the team's history gains carries `runner_id`, the
  holder's participant id. A fog gate stores its flag in `entry_flag_id`, the zone a
  handoff restarts (`RelayInfo.zone_name`); a backtrack seen through `zone_query`
  never changes it.
- **Per-save data.** The holder's debug flags land on their own row and alert the
  staff as on a solo race.
- **Reconnection.** A reconnecting holder gets the `zone_update` of the team's zone,
  a waiting runner none.
- **`relay_update`** goes to the team's connected mods whenever `RelayInfo` changes
  here: a member passes the fresh-save gate (`validated`, `cap`, the holder's
  `gates_locked`, that member's own `token`), the team's first report (the first
  holder's `token`), each fog gate (`zone_name`, maybe a
  count), each counted kill (`members[].zones`, `gates_locked`), the finish
  (`team_status`); the baton operations send their own (Baton, "Operations").
- **Finish.** The holder's final boss flag runs `finish_team`, `handle_finished` on
  the team: FINISHED, `finished_at`, the layer set to the seed's total, the final
  boss counted for the holder, `copy_team_result` (status, IGT, finish time, deaths
  and layer onto the members still in, a disqualified team leaving them abandoned, a
  member never validated going out instead; never `zone_history`), the public line
  `{team name} has finished the race!`, then
  auto-finish and the same broadcasts, and a `relay_update` telling the team's mods
  their race is over. Once every team is finished or out, every participant row is
  terminal and the race finishes.

## Lifecycle

A member goes out alone: the team plays on without them, and is out only when nobody is
left in it. There is no automatic reassignment of the baton, ever.

| Way out                                               | Who              | The member                                                                                                                    | Chat line (public unless noted)                                |
| ----------------------------------------------------- | ---------------- | ----------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `POST /races/{id}/abandon`                            | the member       | REGISTERED, READY or PLAYING to ABANDONED                                                                                     | `{name} has abandoned the race.`                               |
| `DELETE /races/{id}/participants/{pid}`, race RUNNING | organizer, admin | the same, the row kept in its team (400 `Cannot remove: current status is '<status>'` for a member already out)               | `{name} has been removed from the race` (participants channel) |
| `POST /races/{id}/participants/{pid}/disqualify`      | organizer, admin | DISQUALIFIED as on a solo race; the team is out                                                                               | none                                                           |
| `POST /admin/users/{id}/ban`, race RUNNING            | admin            | the same disqualification ("Account banned"), unless already out by then; the mod is closed                                   | none                                                           |
| Inactivity monitor, offline 30 minutes                | server           | PLAYING to ABANDONED                                                                                                          | `{name} has abandoned the race due to inactivity.`             |
| Inactivity monitor, no-show                           | server           | REGISTERED or READY (never validated) 30 minutes into the race, whether it has a `race_duration_minutes` or not, to ABANDONED | the same                                                       |
| Inactivity monitor, team IGT stale 30 minutes         | server           | the holder to ABANDONED                                                                                                       | the same                                                       |

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
- The cap is recomputed on the members who share it (`team_cap`, "Cap"): every
  member's `cap` and the holder's `gates_locked` can move.
- The team is out (ABANDONED) once no member is left in. A disqualification puts it out
  at once (DISQUALIFIED), finished or not: what a cheater obtained reached the team.
- A team out gets `copy_team_result`: its members still in take its status, IGT, finish
  time, deaths and layer (a disqualified team leaves them ABANDONED; a member already out
  keeps their own snapshot). So does a team that finishes, except for a member who never
  played (`relay_validated` false: never connected, or never reported since the start),
  who goes out with the team instead, as a member going out then: ABANDONED with the
  snapshot and no finish time, never credited with a finish they had no part in. A team
  that was still in the race and goes out while the race runs gets the public line
  `{team name} is out.` (never twice, nor after the race finished).

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
  validated. On a relay race that branch runs whether the race has a `race_duration_minutes`
  or not (a solo race with one leaves its no-shows to the hard close): nobody takes the
  baton from a connected holder, so a first holder who never plays would keep it until
  the forced end, and a no-show (who takes no share of the cap, "Cap") would keep their
  team in the race after its last runner went out. A connected waiting runner who
  validated has no stamp and is never inactive: they wait by design.
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
- A member who went out before the team's end did not finish the race: whatever the team did afterwards, their row has no placement and reads DNF with their own snapshot (IGT, layer). A placement is for the runners who were in the race when their team finished; members still in carry the team's placement, except a member who never played, who goes out at the team's end ("Lifecycle").
- Race card previews (`race_response`): finished members are ordered by team result and carry their team's placement; a member who left early is not finished and has none.
- Discord podium (`build_podium(participants, teams)`): with teams, one entry per finished team, named after the team, with the team's IGT; at most three.
- Profile activity: `RaceParticipantActivity.relay_team_name` is the team the user played for (`Participant.relay_team`, a read-only relationship loaded with the profile query, heavy team columns deferred). The activity list shows it before the placement as plain text. Counting is unchanged: a relay race counts for nothing outside itself.

## Web

Race creation (`/race/new`): Relay is a fourth tile of the Format field, next to Classic, Elden Drift and Speedrun (formats exclude each other, so relay needs no handling of race items or speedrun). Its panel holds "Teams of [n]" (2 to 6, default 3) and the cap sentence of `relayCapSentence` in `web/src/lib/relay.ts`, which applies the server's formula (`ceil(total_layers / team_size) + 1`) to the selected pool's `layers_count` ("30 zones, teams of 3: 11 zones max per runner."). A pool's seeds may differ in layer count (the category key `<pool>@<layers>` exists for that), so the sentence is the pool's nominal count, and the race's own `relay_cap` is the figure that binds. The sentence is omitted when the pool has no `layers_count`. The game mode tabs count `PoolInfo.relay_available` (AVAILABLE plus SEEN seeds carrying the relay block). While relay races are off on the server every count is 0: the Relay tile stays, but no game mode can be picked, the page reads "No relay seed in any game mode yet." and Create stays disabled (the pools carry no reason, so the text cannot tell that case apart). With relay on, the late joiners and deathless options leave the advanced options (the request sends `late_join_window_minutes: null` and `deathless: false`), a line under the trigger says so, the registration hint says players pick a team, and the open registration maximum is labelled "max runners". `createRace` takes the team size as its last parameter (`relay_team_size`).

Setup page (`/race/[id]`): the participant list of the left sidebar becomes `RelayTeamList`, grouped by team in the server's order. A team has a header (color, name, members / size, "Edit" for its members and the organizer, "Delete" for the organizer on an empty team), a "Starts: <runner>" line (the team's first runner; "Change" opens a select of the members) and the usual `ParticipantCard` per member. A team with a free slot ends with a dashed button, "+ Join this team" for a visitor and "Move to this team" for a runner of another team (`teamSlotAction`); "+ Create a team" closes the list (always for the organizer, who adds an empty placeholder team; for a runner or visitor who can register only while "Runners can create teams" is on). That checkbox is the organizer's, and when it is off the header maximum counts the teams' seats (`relayCapacity`) and the race is full when they are. The cross of a card (organizer) opens a menu: "Move to <team>" for each team with a free slot, and "Remove from race". The map slot's join button reads "Pick a team to join" and scrolls to the list. The start button follows `relayStartBlocker` (the server's `relay_start_error` texts), for every role.

The team list follows other users' changes by re-fetching the REST race each time `raceStore.participants` is replaced while a relay race is in setup (every team change makes the server broadcast the leaderboard rows; the newest answer wins when fetches overlap); a member's live status comes from the `relay_members` of the team rows. The runner's own changes replace the race with the answer of the REST call (`onChanged`). `joinRace`, `acceptInvite` and `addParticipant` take an optional team choice (`{relay_team_id}` or `{create_team: true}`): the invite page and the organizer's add-participant search show a select of the teams with a free slot plus "New team" (`teamChoiceOptions`; an invite page offers it only while runners may create teams). The five team routes are `createRelayTeam`, `updateRelayTeam`, `deleteRelayTeam`, `joinRelayTeam` and `moveRelayParticipant` in `web/src/lib/api.ts`.

Live leaderboard (`Leaderboard.svelte`, race page and results): a relay race's rows are its teams (`relay_members` set), through the same component and the same store as a solo race, whose rows render as before. A team row shows the team name in place of the runner's (a button, not a profile link) with the connection dot of the holder, the zone fraction, time, gap and deaths. The second line is `relayHolderLine`: "<holder>, <zone>" (the zone cut like any row's, its full name in the tooltip, dropped while run details are hidden), "<holder> offline" when the holder has no mod connection, "Baton free" when a playing team's row names no holder: the holder abandoned and nobody has taken the baton, or the baton is free under a nominal holder (a take nobody acknowledged, a handoff to a runner who had just disconnected), where the server sends no `relay_holder` since nobody plays. A team shows its members by default; the chevron and the team name fold them and unfold them again (a click elsewhere on the row still selects it for the comparison): each with `relayMemberLabel` and "zones/cap" as the server sends them (`relay_members[].zones`, `relay_cap`). States: "playing" (the row's `relay_holder_id`), "waiting", "ready" (before the start), "finished", "out" (abandoned or disqualified, whatever the team does); the holder and a waiting member add ", offline" when `online` is false. A member links to their profile when the REST race knows them (`memberUsers`), else shows the name. The folded set is a `SvelteSet` of row ids inside the component, so a team the viewer folded stays folded through row replacement and re-ordering. `reuseIfUnchanged` compares deeply, so an unchanged team keeps its row object although `relay_members` is a fresh array in each message, and a holder change or a member's count change yields a new one. The rules card of a relay race starts with `relayRuleLine` ("Relay: 30 zones, teams of 3, 11 zones max per runner on a full team (higher on a smaller one)."; a team's member list shows its own live cap, which is higher for a team with fewer members and moves when a save is validated or after an abandon). A member's profile link opens in a new tab and does not select the row. The OBS leaderboard overlay (`LeaderboardOverlay`, its own component) is unchanged: a team row reads as any row through the same data, with the team name (the row's display name) and the team's fraction, time and gap, and no holder line or member list. What the staff know per runner shows on the row of the runner's team (`byLiveRow` in `web/src/lib/relay.ts`): the "Flagged" chip of a cheat detection, and the reason of a disqualification in the DQ label's tooltip.

Cast Setup is not offered on a relay race, by its button or by `?cast=1`: the cast scenes seat runners, and a relay race's rows are teams.

Map (`/race/[id]`, live, finished and the replay): the map components are fed the team rows unchanged, so a relay race draws one path per team in the team's color with the team's marker at its current zone, and nothing per runner (no handoff marker on the path). The team name is the row's display name (`twitch_username` is `team-<8 chars>` and is never shown on its own), and no map component links a row to a profile. Selection of two teams opens the layer comparison on row ids as for runners. In the zone popup (`NodePopup`, "Visited by") a team's line reads "<team>, <runner>": `relayRunnerAt` (`web/src/lib/relay.ts`) takes the `runner_id` the server writes on each `zone_history` entry (the holder when the entry was written) from the node's last entry that is not a backtrack, and names it from the row's own `relay_members`. A zone restarted after a handoff therefore names the runner who got out of it. No runner is shown (the line is the team name alone) when the entry has no `runner_id` (solo race, or a team's first entry written before a holder existed) or when the runner is not in `relay_members`; members who are out stay listed, so a runner who abandoned is still named. `computeVisitors` reads `relay_members` from the row at click time, so the paths do not depend on it: `pathParticipants` in `MetroDagFull.svelte` compares only the zone history, current zone, color, name, status and IGT, and a member's `online`, `ready` or `zones` change redraws nothing. The replay of a finished relay race replays the teams (one path per team, the team's zone history), and the personal highlights of a runner are their team's.

## Bot

`tools/relay_bot.py` plays fake relay runners over the mod WebSocket, so the server and the web can be exercised without the game. From `server/`, against a local database only (it refuses any other unless `--force`), while the dev server runs with `RELAY_RACES_ENABLED=true` (needed to create the race the bots join):

```
uv run python ../tools/relay_bot.py <race_id> --team Alpha=bot1,bot2 --team Beta=bot3,bot4
```

Each bot is a local user. In setup the tool places them in the named team through `place_in_team` (a team missing from the race is created and named; never name the organizer), one at a time in the order of the `--team` options, each in its own transaction as one join per runner. Teams and members are listed by creation time (on PostgreSQL, the time of the transaction), so the teams it creates and the bots it places are listed in that order, the first bot of a team it creates starting that team's run. A refused placement (a full team) stops the tool with the bots before it left in the race; a second start places the rest. Each bot then connects over `/ws/mod/<race>` with its own mod token and `PROTOCOL_VERSION`, and behaves as the server expects of a mod:

- It sends `ready`, and once the race runs its first `status_update` with an IGT of at most 60 s (the fresh-save gate), then `relay_ready {ready: true}` while it waits (again after every `auth_ok`: readiness does not survive the socket).
- It answers `relay_release` with a `relay_state` carrying the same `handoff_id`, its `CharacterState` (below) and the team IGT, and `relay_take` with `relay_taken`; only then does it report progress, its first report carrying the IGT given in `relay_take`.
- Its role comes from `RelayInfo.role` (`auth_ok`, `relay_update`). It stops once its own member is `abandoned` or `disqualified`, or its team is finished, abandoned or disqualified.
- It confirms its token: a `RelayInfo` (`auth_ok`, `relay_update`) with a `token` and `bound` false is answered at once with `relay_bound {token}` (a bot has no save to write it into), once per token: updates that still read unbound do not draw another, a token read again after the socket reopened (`auth_ok`) or after a null token (a race reset) is confirmed again, and nothing is sent once `bound` reads true.
- It prints one line for a `relay_loot` (`loot: <n> entries, paid=<bool>, <runner> defeated <boss>`) and answers nothing: it has no game to give anything to.
- Its event flags are numbered as a mod numbers its own: from the tool's launch time in ms, one more per message, one counter for all its bots. They never carry on from the team's history: the server drops a fog flag whose id the team already recorded, a team's history mixes its members' ids, and one more than a mod's last recorded id is the id that mod sends next.

The state a bot hands over is, by default, one with no lit grace. `--state FILE` gives every bot the state in `FILE` instead: a `CharacterState` JSON (`grace_flags` only: up to 1000 grace event flags, `BonfireWarpParam.eventflag_id`; the list may be left out), checked at startup against the server's own model (`CharacterState` in `server/speedfog_racing/websocket/schemas.py`). A file that cannot be read, or that the server would drop, stops the tool with the reason. A bot holder passes the baton to the game's runner, and the server's `relay_take` carries the bot's state. For example:

```json
{ "grace_flags": [71190, 76101] }
```

Two parts are tested. The decisions are the pure `next_action(bot, message)` (the answer to one server message), `bound_reply(bot)` (the token confirmation owed once a `RelayInfo` was taken in) and `tick(bot)` (what it sends on its own each second), covered by `tools/test_relay_bot.py` (no socket, no database). What the console does in the database is covered by `server/tests/test_relay_bot_console.py`, on SQLite rows: the setup insert (the teams created and named, the bots placed, a refused placement keeping the bots before it), and on a running race the load of bots already in it, then `status`. The listing order is not: SQLite's creation times have a resolution of a second. The same file covers the ids of the event flags the bots send (none taken from the team's history, none shared by two bots). The socket loop and the commands that send have no other test: checklist 0.1 is what runs them against a server (that needs a database at head and a pool regenerated with the relay plugin).

Console commands:

| Command                     | Effect                                                                                                                                                                                                              |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `status`                    | Teams (status, holder, zone, IGT) and each member's zones over the cap                                                                                                                                              |
| `walk BOT`                  | The holder takes the next gate of the forward path (refused while its gates are locked)                                                                                                                             |
| `boss BOT`                  | The holder kills the boss of its zone (its defeat flag): a zone counts for whoever kills its boss, or exits it when it has none                                                                                     |
| `pass BOT TO`               | The holder asks to hand the baton to the teammate named `TO`                                                                                                                                                        |
| `take BOT`                  | A waiting bot asks for the baton, once `baton_free_in_s` has run down to 0 (counted from the `RelayInfo` as received, as the mod does: the server sends no update when it runs out)                                 |
| `offline BOT`, `online BOT` | Close the bot's socket and stay away, then connect it again                                                                                                                                                         |
| `mute BOT on\|off`          | A muted bot ignores `relay_take`, which exercises the 30 s acknowledgement timeout                                                                                                                                  |
| `finish BOT`                | The holder sends the seed's finish event from any zone (the server credits the final boss): its team finishes, and the console warns when it is not at the final boss, as that finish proves nothing about the walk |
| `quit`                      | Leave                                                                                                                                                                                                               |

A walk needs the race to run and the bot to hold the baton. A race needs a relay seed (`Seed.relay`), so a local database whose pools were never regenerated with the relay plugin cannot start one.

## Mod

The mod side of a relay race, one subsection per piece. The race state machine (`mod/src/core/race_machine.rs`) is pure; the shell only feeds it messages and executes its effects.

### Overview

What the mod does on a relay race, in the order a runner lives it:

1. Every member starts a New Game; the mod reports its save's IGT and the server validates it, drawing the member's token, which the mod writes into the save and confirms ("Roles", "The save token"). Nothing is locked in setup.
2. At the start the server names the roles. A waiting runner is locked (the fog gates inert, fast travel refused from the Chapel and the Roundtable Hold), sent to the Roundtable Hold, and tells the server when it is there and ready ("Lock and Roundtable"). It sees who holds the baton, and a countdown when the holder is offline ("Overlay").
3. The holder plays as on any race. At each zone entry the mod reads the graces lit and sends them as a checkpoint ("Giving the baton", "Game access").
4. The holder presses the baton key, picks a teammate and holds it; the server asks for the state, which the mod sends, and the server flips the baton: the giver is locked and sent to the Roundtable Hold ("The baton key", "Giving the baton").
5. A waiting runner takes a free baton with the same key, or receives a handoff. The mod writes the team's IGT, raises the giver's lit graces and the team's boss defeat flags, unlocks, warps to the team's zone (to the Chapel before the team's first gate) and says so to the server ("Taking the baton", "What a state carries", "Game access"). Nothing of the character is written: each runner keeps their own.
6. When the team finishes, the runner is out or the race stops, the mod lowers both locks and shows nothing of the relay ("Roles").

Throughout, the save must be the member's own: once the member's token is drawn, a save that carries another value, or none once the member is bound, is a wrong save, into which nothing is written and from which nothing is sent; a save that carries none before the member is bound gets the token written ("The save token").

The server also sends each member the loot of the team's bosses (`relay_loot`, "Boss loot" under "Baton"). This mod parses the message and drops it with a debug line (`[RELAY] Loot received`): giving the loot is not built.

The constants of all of the above, read from the code (the line is the declaration):

| Constant                  | Value                          | Defined in                            | What it bounds                                                                                                                  |
| ------------------------- | ------------------------------ | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `ROUNDTABLE_MAP_ID`       | `0x0B0A_0000` (`m11_10_00_00`) | `mod/src/core/relay.rs:24`            | The map id the position read gives at the Roundtable Hold (unconfirmed, fact L1)                                                |
| `SETTLE`                  | 2.5 s                          | `mod/src/core/relay.rs:28`            | Loaded time after a loading exit before a relay flag is written                                                                 |
| `GATE_WINDOW`             | 5 s                            | `mod/src/core/relay.rs:32`            | After the lock is raised, before a runner away from the Roundtable Hold is sent there                                           |
| `WARP_RETRY`              | 5 s                            | `mod/src/core/relay.rs:34`            | A warp flag that started no load is lowered after this long                                                                     |
| `WARP_ATTEMPTS`           | 3                              | `mod/src/core/relay.rs:36`            | Raises of a warp flag before the warp is given up                                                                               |
| `WARP_LANDINGS_MAX`       | 2                              | `mod/src/core/relay.rs:42`            | Warps of the mod ending away from the Roundtable Hold, per locked stretch, before the return is given up (a relaunch resets it) |
| `WARP_RELOWER`            | 100 ms                         | `mod/src/core/relay.rs:215` (private) | A lowered warp flag stays down this long before it is raised again                                                              |
| `RELEASE_CAPTURE_TIMEOUT` | 12 s                           | `mod/src/core/relay.rs:46`            | A release is captured and answered within this, from its receipt                                                                |
| `RELEASE_WINDOW`          | 15 s                           | `mod/src/core/relay.rs:50`            | The server's wait for the answer: a flip later than this after an answer is not that handoff                                    |
| `CAPTURE_ABANDON`         | 12 s                           | `mod/src/core/relay.rs:55`            | A capture unanswered this long is abandoned by the machine                                                                      |
| `CAPTURE_RETRY`           | 500 ms                         | `mod/src/core/relay.rs:58`            | No capture is asked this long after a failed one                                                                                |
| `READ_WINDOW_MAX`         | 1 s                            | `mod/src/core/relay_capture.rs:16`    | A capture's reads must end within this, between its two map reads                                                               |
| `APPLY_DEADLINE`          | 15 s                           | `mod/src/core/relay_apply.rs:17`      | The shell stops writing an apply this long after the ask                                                                        |
| `APPLY_ABANDON`           | 20 s                           | `mod/src/core/relay.rs:69`            | The machine abandons an apply the shell has not answered, and acknowledges the take                                             |
| `TAKE_STARTS_MAX`         | 3                              | `mod/src/core/relay.rs:75`            | Starts of one take: an apply a load cut starts the take again, until the last start's apply                                     |
| `APPLY_WRITES_PER_FRAME`  | 16                             | `mod/src/core/relay_apply.rs:23`      | The ceiling of flag raises in one frame's batch: what paces an apply                                                            |
| `SLOW_APPLY_ENV`          | `SPEEDFOG_RELAY_SLOW_APPLY`    | `mod/src/core/relay_apply.rs:33`      | Test aid: milliseconds between two writes of an apply, off when absent (never set for a real race)                              |
| `APPLY_FRAME_BUDGET`      | 1.5 ms                         | `mod/src/core/relay_apply.rs:30`      | Wall time of one frame's batch, checked after each write once one was made (a guard a normal apply does not reach)              |
| `IGT_WRITE_SLACK`         | 2 s                            | `mod/src/core/relay.rs:96`            | How far above the wall time since the last start's write a take's IGT may read and still count as written                       |
| `IGT_WRITE_RETRY`         | 500 ms (`CAPTURE_RETRY`)       | `mod/src/core/relay.rs:92`            | A take's IGT write that did not take is repeated no sooner than this                                                            |
| `TAKEN_CONFIRM`           | 5 s                            | `mod/src/core/relay.rs:64`            | After `relay_taken`: the holder role outlives a contrary update, a reconnection's replays wait, this long                       |
| `REQUEST_TIMEOUT`         | 10 s                           | `mod/src/core/relay.rs:81`            | A handoff or take request unanswered this long is forgotten                                                                     |
| `WRITE_ATTEMPTS`          | 3                              | `mod/src/core/relay_token.rs:15`      | Writes of the token into one save that do not read back, before the mod stops writing it there (until a load or a new token)    |
| `UNREADABLE_RETRY`        | 500 ms                         | `mod/src/core/relay_token.rs:19`      | A read of the token flags that found one unreadable is asked again no sooner than this                                          |
| `HOLD_TO_CONFIRM`         | 1 s                            | `mod/src/core/relay_menu.rs:13`       | The hold that confirms a teammate or a take                                                                                     |
| `MENU_AUTO_CLOSE`         | 5 s                            | `mod/src/core/relay_menu.rs:16`       | The menu closes by itself this long after the last press or release                                                             |
| `MAX_STATE_GRACES`        | 1000                           | `mod/src/core/relay_capture.rs:20`    | Grace flags in a state on the wire                                                                                              |
| `MAX_STATE_INT`           | 2147483647                     | `mod/src/core/relay_capture.rs:22`    | The largest grace flag of a state on the wire                                                                                   |
| `BANNER_DURATION`         | 4 s                            | `mod/src/core/item_feed.rs:132`       | The transient relay banners ("YOU HAVE THE BATON" and the others), and the shortest "BATON PASSED" shows                        |
| `PULSE_PERIOD`            | 1.2 s                          | `mod/src/core/relay_view.rs:25`       | One pulse of the line under "BATON PASSED": full, faint, full                                                                   |
| `PULSE_MIN`               | 0.35                           | `mod/src/core/relay_view.rs:27`       | The faintest that pulsing line gets (opacity)                                                                                   |

The status line shows a message for 3 s (`mod/src/core/race_machine.rs:2056`, inline). The server's side of the same timings (60 s offline wait, 15 s release, 30 s take) is in "Baton".

### Roles

The server names the role: `RelayInfo.role` (`holder` or `waiting`) comes in `auth_ok` and in every `relay_update`, which replaces the team whole. The mod never derives a role from anything else, with one exception the server's word also makes: a `relay_take` received reads `holder` until it is acknowledged or given up, and so does the confirmation window after its `relay_taken` ("Taking the baton"). An unknown role or status (a build older than the server) is never read as a decision: the machine keeps its current lock state and offers nothing.

On a relay race the leaderboard rows are teams: a row's `id` is the team id (`RelayInfo.team_id`), not the runner's participant id. The runner's row is therefore the team row (`my_row_id`, its index found again with every `RelayInfo`, so a move to another team in setup moves it at once), which is what the finish, out, layer and leaderboard logic reads (`am_i_finished`, the layer snapshot before a zone reveal, the gap and the highlighted row of the overlay). On any other race it is the participant's own row, as before. The runner's own participant id stays what saved event flags are keyed on.

A runner's relay is in one of three states:

- Live: the race runs (countdown included) and the team status is `ready` or `playing`. Locks, takes and the token apply only then. In setup every member reads `team_status: "registered"`, `role: "waiting"` and no holder, the first runner included, so a role alone says nothing before the start.
- Over: the team status is `finished`, `abandoned` or `disqualified` (over for every member), or the runner's own entry in `members` is `abandoned` or `disqualified` while the team plays on (then `am_i_abandoned` is also true).
- Neither: setup, or a status the mod does not know.

The runner's own `online` and `ready` in `members` are never read: the `RelayInfo` of `auth_ok` reads them `true` and `false` whatever the mod does, and readiness is the value the mod sends. The runner's own `status`, `zones` and `validated` are read, and the `relay_update` that follows `auth_ok` is the authoritative copy.

A role turning `waiting` clears the revealed zone and any pending one, so the exits of the zone just left do not stay on the panel. A `relay_refused` shows the server's `message` in the status line and logs its `code`; the mod branches on no code.

What a waiting runner's mod still sends is as on any race: once the countdown is over it reports `status_update` with its own save's IGT, which is how the server validates the save (`members[].validated`) and draws the member's token ("The save token"), and it shows `fresh_save_required` through the existing blocking banner. Every member starts a New Game at the start, like the first runner; the mod resets no IGT at a race start.

LiveSplit on a relay race is not addressed: it keeps following the local game (a waiting runner's own save, the team's once a take wrote it) and the arrivals of the team row.

### Lock and Roundtable

The seed carries two saved event flags that hold a runner (`RelayInfo.flags`): the lock (`lock_flag`), while on, keeps the seed's fog gates from reacting; the travel lock (`travel_lock_flag`), while on, makes the Chapel and the Roundtable Hold maps refuse fast travel, from the map screen and from their grace (anywhere else fast travel stays open). A third flag (`roundtable_warp_flag`), raised, warps the player to the Roundtable Hold, by the Table of Lost Grace; the seed lowers it itself after the warp, and sets no respawn point with it. Both locks are saved, so they survive a quit-out and a game restart: the machine never assumes their state. It knows what the server says and what it wrote itself in this process, and writes the server's word again once after every loading exit and whenever the word changes.

What the locks should read, decided on receipt of a message and re-checked as a few comparisons per frame:

| The server says                                                                                                                                                                      | Lock                                                                                    | Travel lock                    |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------- | ------------------------------ |
| No relay; or a live relay whose role this build does not know; or a team status it does not know (unless the runner is a holder with open gates, whose locks are lowered)            | left alone                                                                              | left alone                     |
| The runner is out, the team is finished, abandoned or disqualified, the race is not running (finished, reset to setup), or the team is `registered` (setup), whatever the role reads | lowered                                                                                 | lowered                        |
| A `relay_take` received and not yet acknowledged, whatever the role reads                                                                                                            | raised, until the take's acknowledgement lowers it ("Taking the baton")                 | raised, lowered with the lock  |
| Live, role `waiting`                                                                                                                                                                 | raised                                                                                  | raised                         |
| Live, role `holder`, `gates_locked` (the cap)                                                                                                                                        | raised, and the banner "QUOTA REACHED: PASS THE BATON" shows once when the cap turns on | lowered: the holder may travel |
| Live, role `holder` otherwise                                                                                                                                                        | lowered                                                                                 | lowered                        |

The travel lock follows the lock except for a holder with no take in progress (`relay_travel_lock_wanted`): at their cap the lock holds a holder's gates, not their travels, so they can leave a dead end, shop and pass the baton from anywhere. Once the baton leaves them, they wait like anyone, both locks raised.

Nothing is locked in setup, the first runner included: the locks come only with the `relay_update` the server sends at the start (countdown included). A giver is locked and sent to the Roundtable Hold only when a `relay_update` shows it `waiting`, never on its own after sending its state. An over runner wins over every other reading, an unknown role included.

Every relay flag write (the two locks, the warp flags, the token of "The save token") waits until the player is loaded on the race save (position readable, no wrong save by the IGT or by the token) and `SETTLE` (2.5 s) has passed since the last loading exit: a flag written during a loading screen can be missed by the seed's events. The two locks are written in one batch: a frame that writes one of them again writes the other (`relay_asserted` covers both; every loading exit clears it). A write the shell cannot make (the flag's category not found, the flag manager not reachable) is logged by the shell, `[RACE] Game flag not written` with `flag_id` and `value`, once per failed write (at warn level while the player is loaded, which is when relay flags are written; at debug level otherwise, where the death marker flags of a message fail by the dozen at the title screen). The machine changes nothing then: it believes the value it asked for until the next loading exit asserts it again, and nothing is read back. Each lock logs its changes, `[RELAY] Lock raised` or `[RELAY] Lock lowered`, `[RELAY] Travel lock raised` or `[RELAY] Travel lock lowered`, with a `reason`: `waiting`, `cap` or `take` for a raise; `holder`, `relay over`, `race not running`, `relay not started` or `take` for a lower.

A waiting runner whose locks are raised and asserted and who is away from the Roundtable Hold (map `m11_10_00_00`, `ROUNDTABLE_MAP_ID`, read with the position the shell already reads every frame) is sent there once the gate window is over: 5 s since the lock was raised, or a loading exit since. This is how every waiting runner gets there: a New Game starts at the Chapel, so at the race start the waiting runners are warped from the Chapel during the countdown, while the first holder stays where it is. The warp raises `roundtable_warp_flag`; a raise that starts no load is lowered after 5 s and raised again, up to 3 raises, then the status line shows "Warp to the Roundtable Hold failed", the flag is lowered, and the warp is not tried again until the next loading exit. A warp ends on any frame where the player is not loaded after a raise, and as soon as the map reads the Roundtable Hold; the warp flag is never written on a frame inside `SETTLE`. A load that one of these warps started and that ends away from the Roundtable Hold counts as a landing (no other load does: a new character's first load at the Chapel, a respawn after a death outside a warp): after 2 landings in one locked stretch the return is given up for good (same status line, the landing map logged at warn level), and readiness stays false; a loading exit does not reset the count, reaching the Roundtable Hold or the lock going down does. A relaunch of the game resets the landing count (it lives in the process), which is how a runner stranded by a given-up return is freed. A dead runner (HP 0) is not warped; since the seed's Roundtable warp sets no respawn point, a runner who dies at the Roundtable Hold respawns at the grace they rested at last and is sent back. HP is read only while a return may start (no warp running, not given up, past the gate window) or a take waits for a frame. A take received and not started yet, or put back by a load that cut its apply ("Taking the baton"), is sent back like a waiting runner. A warp still running is dropped, its flag lowered if it is still on, when the role turns `holder` (a take started included) or the relay stops being live. Log lines: `[RELAY] Warp to the Roundtable` (each raise), `[RELAY] Warp failed` (its raises spent; warn level), `[RELAY] Warp to the Roundtable landed elsewhere` (`map`, as `mWW_XX_YY_DD` in decimal, and `landings`; warn level).

What only the game proves about the locks and the Roundtable Hold (the in-game checklist, section A and the steps it names). "Before the Roundtable revision" names a build that held waiting runners at the Chapel with the lock alone and copied the giver's character at a take:

| Id  | Fact                                                                                                                                                                                                                                                | Source                                                         | Confirmed in game                                                                                                                                                                                                 |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| L1  | The Roundtable Hold's map id, as `GameState::loaded_map_id` reads it, is `0x0B0A_0000` (`m11_10_00_00`)                                                                                                                                             | `ROUNDTABLE_MAP_ID`                                            | No (a wrong value shows as two loading screens, then "Warp to the Roundtable Hold failed"). The same read gave the Chapel as `0x0A01_0000` (`m10_01_00_00`): yes, 2026-11-23 (A2, before the Roundtable revision) |
| L2  | A flag written on a loaded frame once `SETTLE` has passed is honoured by the seed's events: the lock makes the gates inert, the warp flags warp                                                                                                     | `docs/plugins/relay.md` (speedfog)                             | Yes, 2026-11-23, before the Roundtable revision: the lock (A1), the Chapel warp flag (A3), a connection warp flag (D2)                                                                                            |
| L3  | The locks the mod writes survive loading exits and a quit-out, and one changed by hand during a load is written again after it                                                                                                                      | `relay_asserted`                                               | The lock: yes, 2026-11-23 (A5, A6, C1, before the Roundtable revision). The travel lock, written in the same batch: no                                                                                            |
| L4  | A runner away from the Roundtable Hold is warped there through `roundtable_warp_flag` after `GATE_WINDOW` (from the Chapel during the countdown, from the world after a load), lands by the Table of Lost Grace and reads `ROUNDTABLE_MAP_ID` there | `maintain_relay`                                               | No. The same return to the Chapel through `chapel_warp_flag`: yes, 2026-11-23 (A2, A3, before the Roundtable revision)                                                                                            |
| L5  | `GameState::read_hp` reads 0 for a dead runner and above 0 for a living one                                                                                                                                                                         | `FrameSnapshot.hp`                                             | Yes, 2026-11-23 (A3, A4)                                                                                                                                                                                          |
| L6  | The server hears `relay_ready` true only from a runner at the Roundtable Hold with both locks asserted and its token bound, and refuses a take or a handoff otherwise                                                                               | `Effect::SendRelayReady`                                       | At the Chapel with the lock alone: yes, 2026-11-23 (A2, A7, D0, before the Roundtable revision). At the Roundtable Hold with both locks and the token: no                                                         |
| L7  | The seed lowers a warp flag itself after the warp and reads a lower followed by a raise as a new warp                                                                                                                                               | `docs/plugins/relay.md` (speedfog)                             | The Chapel warp flag, driven by this mod: yes, 2026-11-23 (A3, before the Roundtable revision). The Roundtable warp flag: no                                                                                      |
| L8  | The travel lock the mod writes makes the Chapel and the Roundtable Hold refuse fast travel, from the map and from their grace, and touches nothing else                                                                                             | `relay_travel_lock_wanted`; `docs/plugins/relay.md` (speedfog) | No (the seed's own check of it, its check 16, is not recorded either)                                                                                                                                             |
| L9  | A holder at their cap (the lock raised, the travel lock lowered) finds the gates inert and fast travel open, and can pass the baton from wherever they travelled                                                                                    | `relay_travel_lock_wanted`                                     | No                                                                                                                                                                                                                |

`relay_ready { ready }` tells the server a waiting runner is loaded at the Roundtable Hold with both locks raised (asserted since the last loading exit, no warp running), on a save that carries its token, bound, as read on a settled frame (or no token drawn yet: "The save token"). The mod sends its current value, true or false, on every change and on the reconnection frame after every `auth_ok`: readiness does not survive the socket. A holder never sends true, nor a runner whose take is in progress, nor a runner on a wrong save. The messages queued while the socket was down are dropped at the reconnection; readiness goes again on the reconnection frame. Log line: `[RELAY] Ready sent` (`ready`).

### What a state carries

A handoff carries the giver's lit graces (`CharacterState`, its one field `grace_flags`) and nothing of the character: each runner keeps their own attributes, level, runes, equipment and inventory, and a take writes none of them. The team's dead bosses come with the take, not with the state (`relay_take.defeat_flags`, "Taking the baton").

The receiver raises only those of the state's grace flags that are graces of its own game (the `eventflag_id` of a `BonfireWarpParam` row), so a state from a tampered or newer teammate cannot make it raise any other flag, and only those of the take's defeat flags that are the seed's bosses (`boss_flags`). A state with other fields than `grace_flags` reads as its graces.

Before sending, the state is fitted to the server's wire caps (1000 grace flags, `MAX_STATE_GRACES`; each at most 2^31 - 1, `MAX_STATE_INT`): the flags are sorted and deduplicated, the first values are kept, a flag above the integer cap is dropped, and the count of values cut is returned for the shell to log (`fit_to_wire`, `mod/src/core/relay_capture.rs`). Which graces stay never depends on the order they were read in.

### Giving the baton

The holder's mod answers the server's `relay_release { handoff_id, to_name }` with its state (the lit graces), and sends a checkpoint of it at every zone entry. The machine decides; the shell reads the game on a worker thread and answers through `RaceMachine::relay_state_captured` ("Game access").

A capture is asked (`Effect::CaptureRelayState`, carrying a generation) only for the holder of a live relay, connected, on a frame with a readable position, on the race save, and one at a time: while one is in flight no other is asked. Two bounds keep the machine from depending on the shell. A capture not answered 12 s after it was asked is abandoned and a new one may be asked, and its late answer is dropped: an answer counts only for the capture in flight, identified by its generation (two checkpoint captures both carry a null `handoff_id`). After a failed capture (answer `None`) none is asked for 500 ms. The shell delivers the answer on the frame thread, as an input of the machine, with the generation of the effect; a worker never calls into the machine. The answer is `relay_state { handoff_id, state, igt_ms }`, the state fitted to the wire caps first (a single warn names how many values were cut) and `igt_ms` the held IGT of the answer frame.

| Event                                                                                                                                                                                  | What the machine does                                                                                                                                                                                                                                                                                                   |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `relay_release` to a live holder                                                                                                                                                       | Remembers it (`handoff_id`, `to_name`) with a deadline 12 s after receipt, under the server's 15 s. A release for the id already pending changes nothing; a release with another id replaces the pending one. A release to a waiting runner, an unknown role, a runner out or a team over, or without relay is ignored. |
| Release pending, a loaded frame                                                                                                                                                        | Asks the capture. A release's capture in flight is waited for; a checkpoint's is abandoned at once (its late answer dropped by its generation) and the release asked on the same frame, not up to 12 s behind it.                                                                                                       |
| Answer `Some(state)` for the pending release                                                                                                                                           | Sends `relay_state` with the release's `handoff_id`, and remembers `to_name` with the time of the answer. Nothing is locked, no warp, no banner: the server decides.                                                                                                                                                    |
| Answer `None` (a loading screen, the grace flags unreadable, a load during the reads)                                                                                                  | Sends nothing. A release stays pending and is asked again on the first loaded frame 500 ms or more after the failure, until its deadline; a checkpoint is dropped.                                                                                                                                                      |
| Deadline reached with no answer sent                                                                                                                                                   | The release is dropped and the status line reads "Handoff cancelled: character not readable" (no capture read in time: a loading screen, the grace flags unreadable, a wrong save). A capture still in flight answers for nothing and is not sent. The server cancels at 15 s and the holder simply stays holder.       |
| The role turns `waiting`, the runner goes out, the team ends or the race stops while a capture is pending                                                                              | The release is dropped and the answer, if it comes, is not sent.                                                                                                                                                                                                                                                        |
| The socket drops (any status but connected, or a frame seen disconnected)                                                                                                              | The pending release is forgotten (the server cancelled it and a reconnection does not repeat it), a capture in flight answers for nothing, a checkpoint not yet asked is dropped. After the reconnection nothing stale is sent.                                                                                         |
| The server's `relay_update` reads this runner `waiting` within 15 s of the answer (a flip learnt from an `auth_ok` after a reconnect shows no banner: only a `relay_update` pushes it) | The flip: the giver's banner "BATON PASSED TO <NAME>" (the release's `to_name`) takes the waiting banner's place until the player is blocked ("Overlay"), and both locks and the return to the Roundtable Hold of "Lock and Roundtable" follow, as for any `waiting` update. The remembered release is then forgotten.  |
| A `relay_update` that still reads `holder`                                                                                                                                             | The server refused or ignored the answer (an expired or unknown `handoff_id`, an IGT its wrong-save guard refuses, a target gone out). Nothing changes here. The remembered release stays until the 15 s window ends, so a flip that comes later is still recognised.                                                   |
| A `relay_update` turning the runner `waiting` more than 15 s after the answer, or with no answered release                                                                             | A takeover or another handoff: no "BATON PASSED" banner.                                                                                                                                                                                                                                                                |

A checkpoint (`handoff_id: null`) is asked when a zone is revealed to a live holder, which is when the entry shows on screen, not when the server names it. It is skipped while a capture is in flight (dropped, not queued: the server's stored state can then be one zone behind until the next zone entry), and when a release is pending at the same reveal the release takes the one capture (a release's state is kept by the server as the latest checkpoint too). A reveal while the socket is down asks nothing and nothing is sent after the reconnection: the server keeps only the latest checkpoint, and the next zone sends a fresher one. A team still `ready` keeps no state: the server ignores the checkpoint and the mod does not special-case it.

A capped giver (its gates already locked for the cap) is warped to the Roundtable Hold right after the flip, with no 5 s window: its lock time dates from the cap, not from the flip. This is accepted. Its travel lock, down while it held the baton at its cap, is raised at the flip, on the frame of the warp's first raise. The cap banner is not shown again: it shows once, when the cap turns on. Its "BATON PASSED" banner therefore stays over the loading screen of that warp until its 4 s are done.

The mod writes no lock and no warp on a release or on a capture: the locks follow the server's word, so a cancelled handoff never leaves a holder locked. Log lines: `[RELAY] Release received` (`handoff_id`, `to`), `[RELAY] Release ignored: not the holder of a live relay` (warn level), `[RELAY] Release not captured in time, dropped` (warn level), `[RELAY] Capture not answered, abandoned` (warn level), `[RELAY] State captured` (`handoff_id`, `graces`) when the state goes out, and at debug level `[RELAY] Release repeated`, `[RELAY] Release dropped: no longer the holder`, `[RELAY] Checkpoint capture abandoned for a release`, `[RELAY] State not readable`, `[RELAY] Captured state not sent: stale` and `[RELAY] Captured state not sent: release gone`.

### Taking the baton

The server's `relay_take { handoff_id, state, igt_ms, defeat_flags, warp_flag, zone_name }` gives the runner the baton. The machine decides; the shell writes the game (`Effect::SetIgt`, `Effect::ApplyRelayFlags`, see "Game access") and sends `relay_taken` (`Effect::SendRelayTaken`). Nothing of the character is written: the take carries the team's time and world, not a build.

Receipt. A take is ignored without a relay being played (no relay, the runner out or its team over, the race not running). A take whose `handoff_id` is the one in progress changes nothing: the server sends it again after a reconnection, and it is applied once. One whose id is the last take this process acknowledged is answered with `relay_taken` again on the next connected frame, nothing written: its first answer died with the old socket (the reconnection drops what was queued). Any other replaces the take in progress, whatever the cached role. At a new take's receipt the progress of the waiting save is dropped, with one info line: the deferred, pending and in-flight event flags, the in-flight zone queries, a zone waiting to be revealed, and event flags a previous launch saved. The server ignored them from a waiting runner, and replayed after `relay_taken` they would be heard as the team's. `relay_ready false` goes out if `true` was the last value sent.

| Step            | On the first frame that is                                                                                                                                                                                                            | Effects, in order                                                                                                                                                                                                                                                                                                                  |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Start           | loaded, `SETTLE` passed, on the race save, at the Roundtable Hold, HP above 0, connected, both locks raised and asserted, the save's token judged by a read on a settled frame since the last load, no capture and no apply in flight | `SetIgt { igt_ms }` (on every take, also without a state: the runner's own IGT would fail the team's fresh-save gate, or freeze the team's IGT as a rollback), then `ApplyRelayFlags` (the state's grace flags, none without a state; the take's defeat flags among the seed's `boss_flags`)                                       |
| Acknowledgement | after the shell's answer: loaded, `SETTLE` passed, on the race save, HP above 0, connected, the game's IGT reads in the window of "The IGT written is checked" (or its 20 s bound is reached)                                         | both locks lowered, the first raise of the warp flag when `warp_flag` is set, `relay_taken`; the banner "YOU HAVE THE BATON" with "You start at the entrance of <zone_name>" ("of the team's zone" without a name), or "You start from the Chapel" when the warp flag is the Chapel's (`chapel_warp_flag`, or no warp flag at all) |

The IGT and the world are written while the locks still hold the runner at the Roundtable Hold, then both locks are lowered, then the warp flag is raised: a holder warped before its lock is lowered would arrive in the zone locked, and one unlocked before the team's IGT is written could play on its own. The IGT written is checked: the acknowledgement frame must read an IGT in a window only a write that took can produce, from `igt_ms` up to `igt_ms` plus the wall time since the last start frame plus `IGT_WRITE_SLACK` (2 s). The window applies at `igt_ms` 0 too (`[0, elapsed + slack]`, so a write of 0 that took is acknowledged on the first frame, and an unreadable IGT is outside it): a runner whose own IGT is 20 minutes and whose write failed must not report 20 minutes as the team's. A reading below the window is a write that did not take yet; a reading above it is the runner's own IGT still ticking (the normal case for most takes after the first, the runner having waited at the Roundtable Hold). On such a frame the acknowledgement waits and `SetIgt` is emitted again, no sooner than `IGT_WRITE_RETRY` (500 ms) after the last write. This guarantees that a write which failed, came late or was undone is not acknowledged while the game reads outside the window; it does not prove the game keeps the value afterwards. `APPLY_ABANDON` after the take's last start, if the IGT still reads outside the window, the take is acknowledged anyway with a warn line and the status "Baton taken: time not confirmed" and the guard references cleared (the server's own guards judge the reports). An apply the shell never answered is abandoned at the same bound with the status "Baton taken: graces may be missing".

A runner away from the Roundtable Hold when its take comes is first sent there by the return of "Lock and Roundtable" (a take not started counts as waiting there). There is no local timeout: a take waits for its start frame as long as it is not given up, and a return to the Roundtable Hold given up leaves it waiting (the server frees the baton at 30 s; a teammate's take then gives this one up). While a take is written no return to the Roundtable Hold starts; one put back by a load (below) is sent back there again if the load landed elsewhere. A take starts only on the member's own save: never on a wrong save, and not before the save's token was read on a settled frame since the last load ("The save token").

A load that cuts the apply. The shell's answer says how the apply's writes ended ("Game access"). When a load ended them (`MapChanged`: a death or a quit-out at the Roundtable Hold during the apply), the take is put back to its received state, unless it has been started `TAKE_STARTS_MAX` (3) times already: the first loaded, settled frame at the Roundtable Hold that a start needs (above) starts it again, with the same `handoff_id`, the state and the defeat flags kept on the take since its receipt (a death respawns away from the Hold: the return of "Lock and Roundtable" brings the runner back first). The restart writes the IGT again and asks a new apply (a new generation), which raises every flag again (a flag raised twice is harmless). The IGT written again discards the time since the previous start (the cut apply, the load and the settle are not counted for the team), at most about 20 s over two restarts. Both locks stay raised, no progress goes out and the IGT guards stay skipped through the whole span, and the acknowledgement's IGT window and bound run from the last start. The apply that ends the last start is acknowledged however it ended; after a load the status line then reads "Baton taken: graces may be missing" (the IGT's status shows instead when both apply). An apply that ended complete, on its deadline, as not wanted or without a plan is acknowledged on the next frame that allows it.

IGT guards. The start frame rebases them on the IGT written: the last good and last observed IGT become `igt_ms` (no reference at all for `igt_ms` 0, a team still `ready`, as after a race start: the machine reads 0 as no reading), the blackscreen freeze baseline is dropped, and a quit-out not yet consumed is forgotten. The jump to the team's IGT is therefore no save reload (whose flush would forget the reported bosses), no wrong save and no quit-out. The defeat flags written join the reported flags, so the boss scans never read or report them as the runner's own kills; after a process restart they are reported again, which the server counts as no new kill ("Cap"). From the frame after the first start to the acknowledgement (across a load that puts the take back, and each restart rebasing them again) the reload, wrong-save and quit-out classifications are skipped, their references held at the take's IGT, because until the written IGT shows the game reads the runner's own (a reading far below the team's would otherwise read as a reload and clear the take's reported bosses, or start a new attempt). The acknowledgement rebases them on the reading when it is in the window; at the bound, or when the take is given up or replaced after it started, they are cleared as at a race start, so the next frame seeds them from what the game reads (stale references would read the runner's own IGT as a reload, a quit-out or a wrong save). They are live again from the next frame.

What is held. From the receipt to the frame that sends `relay_taken` (`progress_held`), nothing the server would judge against the team goes out: no `status_update`, no `event_flag` (no flag is read: the scans capture, clear and report nothing, so a flag stays as the game left it), no `zone_query` at a loading exit, no replay on a reconnection, no `relay_state` (no capture is asked, a release is ignored). The frame that sends `relay_taken` sends no progress after it; the next one resumes the scans, so the zone flag the take's warp raises is captured and reported as the team's at the warp's loading exit, and the status updates carry the team's IGT. Both locks stay raised from the receipt to the acknowledgement whatever the role reads, and are written lowered once by the acknowledgement; the warp's loading exit asserts them lowered again after `SETTLE`, with no raise in between.

The warp is a flag warp as in "Lock and Roundtable", on `warp_flag`: the connection's warp flag, whose seed event takes the player to that gate's exit and lowers the flag, or, before the team's first gate, the Chapel's warp flag, which takes the player to the Chapel grace. A raise that starts no load is lowered after 5 s and raised again, 3 raises at most, then the flag is lowered and the status line reads "Warp failed: travel from the map" (the locks are down: the runner may fast travel). `relay_taken` has gone out with the first raise: a warp that never loads does not hold it back. The warp counts no landing toward the cap of the return to the Roundtable Hold and is not limited by it. It is dropped, its flag lowered if still on, when the runner stops holding the baton (a newer take, a waiting role, its relay over, the race stopped).

Precedence. A `relay_update` received during a take replaces the cached info, not the take: the locks stay raised, no return to the Roundtable Hold starts while the take is written (only one put back by a load is sent back, as above), and the take goes on to `relay_taken` whatever role the update reads (after the server's 30 s the update reads the runner `waiting` with the baton free; the server still accepts a late `relay_taken`). The take is given up, without `relay_taken` ever, when an update or an `auth_ok` names another holder or none, the runner is out or its team over, or the race stops running (finished, reset); the locks then follow the role again. What was already written stays: a later take writes the IGT again, and a raised flag stays raised.

Role. The machine's role reads `holder` from the receipt until the take is given up, then for `TAKEN_CONFIRM` (5 s) after `relay_taken` unless the server speaks first: an update naming the runner holder confirms it, one naming another holder or none ends the window (the runner waits again and is locked), and an `auth_ok` ends it (the server sends the take again while it awaits it). Inside the window an update reading the runner waiting with itself named and the baton free is the server's 30 s timer crossing a late `relay_taken`: it changes nothing. After the window the server's word rules again.

A reconnection before the acknowledgement is confirmed. A `relay_taken` can die with a socket the mod does not know is dead yet, and the progress that follows it (the zone flag of the take's warp, sent at the warp's loading exit) goes into the same void and stays in flight. After the reconnection the server, which never heard the acknowledgement, still awaits it: it would acknowledge and drop whatever progress it hears first, and the team's zone entry would be lost until the next gate. So from a take's acknowledgement until the server confirms it, a reconnection replays nothing at once: the event flags and zone queries in flight, the flags buffered while disconnected and the reconnection's rescan wait. The confirmation is a `relay_update` naming the runner holder with its own role `holder`, while no take is in progress and no acknowledgement is due again; an `auth_ok` confirms nothing, since after a reconnection it reads the runner holder while the server may still await the acknowledgement. The replays go on the first connected frame after the confirmation, or after the frame whose `relay_taken` answers the take the server sends again (whichever comes first), so that the server hears the acknowledgement before them; an update naming another holder or none, or a relay over, releases them too. They are bounded: with neither within `TAKEN_CONFIRM` (5 s) after the reconnection they go anyway, so the machine never holds progress for ever. The frame that sends them reads the flags for the rescan, as a reconnection frame does. Outside that span a reconnection replays at once, on relay and other races alike. Only the replays wait: progress made in the meantime (a loading exit's flags, a kill) goes as usual, a residual the span's length (the server's answers follow its `auth_ok` at once) keeps small.

The shell. The IGT write is done on the start frame itself. The apply is read and planned on the shell's worker thread and written on the frame thread, a bounded batch per frame, within 15 s of its start ("Game access"); its outcome comes back on the frame thread as an input of the machine (`relay_state_applied`, with the generation of the effect and how its writes ended: `ApplyEnd`, or none when its plan never came): the apply is over, nothing more of it will be written, whatever part of it could not be done (the shell logs that), and the take goes on, to its acknowledgement or, after a load, to a new start (above). An answer for any other apply than the one in flight is ignored, and a newer take waits for the apply in flight to answer. An apply not answered within 20 s (`APPLY_ABANDON`, under the server's 30 s) is abandoned: the take goes on to its acknowledgement with what got written (the IGT at least), and the status line reads "Baton taken: graces may be missing". A shell that never answers therefore cannot hold the runner at the Roundtable Hold for ever. A socket drop during a take changes nothing of it: an apply answered meanwhile is acknowledged on the first connected frame after the reconnection, and the take the server sends again after `auth_ok` is applied once.

Log lines, which time a take in game: `[RELAY] Take received` (handoff id, `with_state`, `igt_ms`, `warp_flag`), `[RELAY] Take ignored: no relay being played` (warn level), `[RELAY] Take replaced by a newer one`, `[RELAY] Progress of the waiting save dropped` (the counts dropped), `[RELAY] Take started` (`start`, 1 to 3, `igt_ms`, and the counts of `graces` and `bosses`), `[RELAY] Take applied` (`elapsed_ms` of the apply, its `end`), `[RELAY] Apply cut by a load, the take starts again at the Roundtable` (`start`, the start whose apply was cut), `[RELAY] Apply cut by a load at its last start, take acknowledged anyway` (warn level), `[RELAY] Take acknowledged` (`elapsed_ms` since the receipt), `[RELAY] Take given up` (the reason), `[RELAY] Apply not answered, abandoned`, `[RELAY] IGT does not read the team's, take acknowledged anyway`, `[RELAY] Warp to the zone` (`flag`), `[RELAY] Warp to the zone raised again`, `[RELAY] Warp to the zone failed` (warn level), `[RELAY] Holder role window ended`, `[RELAY] Holder role not confirmed in time: the server's word rules again` (the confirmation window ran out with no word from the server), `[RELAY] Take acknowledgement settled` (`confirmed`: true for the server's confirmation, false when another holder, none or a relay over ended the wait), `[RELAY] Reconnection replays held until the take is confirmed`, `[RELAY] Reconnection replays released` (`reason`: `confirmed`, `acknowledged again`, `no longer the holder` or `not confirmed in time`; `sent`: false when the race no longer takes them), `[RELAY] Take not confirmed in time, reconnection replays go anyway` (warn level), `[RELAY] Take received again, in progress` (the server sent the take in progress again: nothing changes), `[RELAY] Take received again, acknowledged again` (it sent one already acknowledged: it is answered again on the next connected frame) and `[RELAY] Take acknowledged again` (that answer going out). The baton key logs `[RELAY] Baton menu opened` (teammates, eligible; debug level), `[RELAY] Baton menu closed by itself` (debug level), `[RELAY] Request refused` (the server's `code` and `message`, warn level), `[RELAY] Handoff requested` (the teammate), `[RELAY] Take requested` and `[RELAY] Request not answered, forgotten` (the 10 s bound).

What only the game proves for a take:

| Id  | Fact                                                                                                                                                    | Confirmed in game                                                                                                                                                     |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T1  | The IGT write takes effect by the next frame, 0 included (an acknowledgement waits for it, but nothing proves the game does not undo it)                | Yes, 2026-11-23 (D0, D1); whether one of those takes wrote 0 is not recorded                                                                                          |
| T2  | The game's IGT never runs faster than wall time and no other writer adds time during a take (the window's upper bound relies on both)                   | Yes, 2026-11-23 (D1)                                                                                                                                                  |
| T3  | The locks lowered and the warp flag raised on the same frame are all honoured                                                                           | The lock and a connection warp flag: yes, 2026-11-23 (D2, before the Roundtable revision). With the travel lock lowered on the same frame, at the Roundtable Hold: no |
| T4  | The connection warp lands at the gate's exit and sets the zone flag                                                                                     | From the Chapel: yes, 2026-11-23 (D2, before the Roundtable revision). From the Roundtable Hold: no                                                                   |
| T5  | The game saves the written IGT across a quit-out                                                                                                        | No                                                                                                                                                                    |
| T6  | The take before the team's first gate (both locks lowered and `chapel_warp_flag` raised on one frame, at the Roundtable Hold) lands at the Chapel grace | No                                                                                                                                                                    |

### The save token

A member plays the race on the save their validation proved fresh ("One character per member" under "Baton"): the server draws a token at the validation and sends it to that member only (`RelayInfo.token`, from 1 to 2^24 - 1, null before), with `bound`, true once it recorded the member's `relay_bound`. The mod keeps the token in the save itself, bit `b` in the saved event flag `token_flag_base + b` over `token_bits` (24) flags (`RelayInfo.flags`; the seed's flag category 1050297, which they share with the loot received flags and the seed's page flag: an event of the seed allocates the category, and nothing in the seed reads the token). The rules are pure (`mod/src/core/relay_token.rs`: `value_of`, `writes`, `judge`); the machine decides when to read and when to write (`judge_relay_token`, `maintain_relay`); the shell reads and writes the flags on the frames asked, on the frame thread (`eldenring::relay::read_token`, `write_token`).

When it is read. Only while the relay is live for the runner and a token is drawn: nothing is read on another race, in setup, before the member's validation or once the runner's relay is over. Then on loaded frames: the first loaded frame after each load, again the first settled frame after it (`SETTLE` since the loading exit), whose verdict replaces the first (the flags may not hold the loaded save's values at once), after every `auth_ok`, whenever the server's `token` or `bound` changes, and on the frame after a write. The shell reads the flags only on a frame the machine asks for (`FrameNeeds.relay_token`), resolving their category page once and reading each bit from it. A read that finds a flag unreadable leaves the verdict as it was and is asked again no sooner than 500 ms later (`UNREADABLE_RETRY`), with one warn line per load once a settled frame finds them so, `[RELAY] Token flags not readable` (the seed's category not allocated), and debug lines otherwise. While no read is due the token costs a few comparisons per frame.

What a read decides (`judge`, first thing in the frame, before anything is written or sent):

| The flags hold       | `bound` | Verdict       | What the mod does                                                                                    |
| -------------------- | ------- | ------------- | ---------------------------------------------------------------------------------------------------- |
| (no token drawn yet) |         | `NotExpected` | Nothing: the save is not judged                                                                      |
| the member's token   | false   | `Confirm`     | Sends `relay_bound { token }`, once per connection, on a connected frame (`[RELAY] Token confirmed`) |
| the member's token   | true    | `Good`        | Nothing                                                                                              |
| 0 (no token)         | false   | `Write`       | Writes the token, when the read was taken on a settled frame (below)                                 |
| 0                    | true    | `Wrong`       | A wrong save (below): the member's save carries the token, so this one is not theirs                 |
| any other value      | either  | `Wrong`       | A wrong save                                                                                         |

The write. On the frame of a `Write` verdict read on a settled frame (loaded, on the race save, no read due since): one `Effect::WriteRelayToken` carrying the 24 flags, each up or down (`relay_token::writes`), the first of the frame's relay writes. The shell writes them with one category page and logs only how many failed (`[RELAY] Token flags not written`, `failed` and `total`; warn level), never a flag or a value; the machine logs `[RELAY] Token written` (`attempt`). The next frame reads them back, and its `Confirm` verdict sends `relay_bound`. After `WRITE_ATTEMPTS` (3) writes that do not read back the mod stops writing into that save, with one warn line, `[RELAY] Token not written, given up`; the count starts again at each loading exit and with a new token. The token is written wherever the runner is, holder or waiting.

A wrong save. A `Wrong` verdict sets `relay_wrong_token` and logs `[RELAY] Token mismatch, wrong save` (warn level, with `read`, the value the save holds, and `matches=false`; the member's own token never reaches a log line). The overlay shows the wrong-save banner, "WRONG SAVE LOADED" and "Reload your race save", as for a wrong save the IGT finds, and the machine treats the save the same way (`save_ok()`): no relay flag is written (the locks, the warps, the token), no take is started or acknowledged, no readiness, no `status_update`, `event_flag`, `zone_query` or `relay_state` goes out, no quit-out penalty is written (a pending one is dropped), and the IGT guards learn nothing from its readings. The first loaded frame after a load already judges, so nothing of a wrong save leaves from its first loaded frame; the settled read then confirms or lifts that verdict. The banner lifts when a read finds the member's token again (`[RELAY] Token matches again, resuming`; the IGT guards then start again from the race save's next reading), when the token is no longer judged and the server holds none, the runner's relay is over or the race no longer runs (`[RELAY] Token no longer judged, wrong save lifted`), and when the relay info goes (`[RELAY] No relay any more, wrong save lifted`). An unknown team status lifts nothing.

Readiness and takes. Readiness needs a `Good` verdict (or `NotExpected`) from a read taken on a settled frame, so a waiting runner is not ready from the moment the server's token or binding changes until its save reads bound: the token is written, read back and confirmed, and the server's `bound` read, a second or so. The first report that draws the token waits for the countdown's end (no `status_update` goes out during it), and by then a runner who started at the Chapel is usually still on its way to the Roundtable Hold, not ready yet: it then sends its first `relay_ready true` once bound, with no drop before it. A runner already ready when the token arrives goes not ready (`relay_ready false`) and ready again once bound. A take starts only once the save's token was judged by a read on a settled frame since the last load, never on a wrong save. A save other than the member's loaded in the middle of a take (a quit-out, then another character) is therefore held off: a receiver is ready, so its token is bound, and the other save reads as wrong; the take is neither started again nor acknowledged, and nothing is written into that save, until the member's own save is loaded again (the server frees the baton at 30 s meanwhile, and a late `relay_taken` takes it back if nobody else did).

Limits, accepted:

- A race reset clears every token, and the next start draws new ones. A character kept from before the reset still carries the previous token and reads as a wrong save: after a reset every member starts a New Game, as the fresh-save gate asks anyway.
- A game that ends (a crash, a kill) between the token's confirmation and the game's next save of the flags leaves the member bound on a save that holds no token: that save and any new character read as wrong, and only a race reset frees the member.
- A read back that finds neither 0 nor the token (a write that landed in part) reads as a wrong save on the member's own fresh save, and nothing is written again; a new character recovers, since the member is not bound yet.
- A first read after a load that finds the member's token on another save (the previous save's values still in place, if the game does that) lets that save's progress out until the settled read, at most `SETTLE` (2.5 s) later; the IGT guard still catches a forward jump meanwhile.
- A holder on a wrong save can still ask for a handoff with the key: no capture is asked on a wrong save, so the release is cancelled at 12 s ("Handoff cancelled: character not readable").

What only the game proves about the token (the in-game checklist, A2b, A5 and section K):

| Id  | Fact                                                                                                                                                                      | Source                                                                                     | Confirmed in game                                                                                                  |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| S1  | The token flags (`token_flag_base` and the 23 after it, category 1050297) read on a loaded frame: the seed's page event allocates their category                          | `eldenring::relay::read_token`; `docs/plugins/relay.md` (speedfog), "Second flag category" | No (the seed's own check of it, its check 19, is not recorded either)                                              |
| S2  | The 24 writes of one `Effect::WriteRelayToken` land on one frame and read back on the next                                                                                | `eldenring::relay::write_token`                                                            | No                                                                                                                 |
| S3  | The token flags written are saved: they read the same after a quit-out and after a relaunch                                                                               | `docs/plugins/relay.md` (speedfog)                                                         | No                                                                                                                 |
| S4  | A new character reads none of them (0)                                                                                                                                    | `docs/plugins/relay.md` (speedfog)                                                         | No                                                                                                                 |
| S5  | On the first loaded frame after a load the flags hold the loaded save's values, not the previous save's                                                                   | `judge_relay_token`                                                                        | No (a "WRONG SAVE LOADED" of about 2.5 s after loading the right save says they do not; the settled read lifts it) |
| S6  | The wrong-save banner shows on a save that carries another token or none, nothing is written into it or sent from it, and it lifts when the member's save is loaded again | `relay_wrong_token`, `save_ok()`                                                           | No                                                                                                                 |

### The baton key

One key, F8 by default, does everything. The machine receives it as a per-frame input (`TickInput.relay_key_down`; repeated key-down events of the OS are the same press) and produces the menu's state and the requests; the shell binds the key and draws (`mod/src/core/relay_menu.rs` holds the pure timers).

The holder. A press opens the menu, a list of the other team members, the highlight on the first teammate who can receive. The opening press neither advances nor confirms. A tap (a press and a release shorter than 1 s) moves the highlight to the next teammate, wrapping; holding the key 1 s confirms the highlighted one and sends `relay_handoff_request { to_participant_id }`, then closes the menu. The menu closes by itself 5 s after the last press or release while the key is up. The menu is possible only for the holder of a live relay, past the countdown (the server answers `busy` during it), with no release waiting, no take in progress or in its confirmation window and no request unanswered; anywhere else it closes and a press already down when it became possible is ignored until released.

Each row shows the teammate's counter as the server gives it ("2/5 zones") and, when it cannot receive, why, in the order of the server's refusal for a handoff target: out of the race (finished, abandoned or disqualified), not in game (offline or not ready at the Roundtable Hold), no fresh save (not validated; a member may simply not have reported yet, so the row never says its save was refused), at the cap (`zones >= cap`). An unknown member status is unavailable too. A teammate who cannot receive is shown but never highlighted or confirmed. The rows are built when a `RelayInfo` is received and read from the echo (`members`, `cap`); the machine guesses nothing. A `relay_update` under the open menu keeps the highlight on the same participant id wherever the list now puts it; when that teammate is no longer available the highlight returns to the first and the press in progress is spent, and so is a press that began while nobody was highlighted (it was aimed at someone else: it neither taps nor confirms, and a new press is needed). A team nobody can receive, or a team of one after abandons, opens the menu with its reasons (or no row) and confirms nothing.

A waiting runner. Holding the key 1 s sends `relay_take_request`, only when all hold: the relay is live (team `ready` or `playing`, the race running) and past the countdown; `baton_free_in_s` reads 0 now (counted down from the seconds in the `RelayInfo` as received, `relay_free_in_s`; a countdown shows the wait and offers nothing; in setup nothing is offered, the info reading no holder and 0 for everyone); no take is in progress; the runner's own entry is validated with `zones < cap`; and the last `relay_ready` this mod sent was `true` (its own readiness: the echo in `members[].ready` reads false after an `auth_ok`). A hold that started before the take was offered does not count.

One request at a time. After a handoff or take request nothing more is sent, and the menu does not open, until the server answers (`relay_release` for a handoff, `relay_take` for a take, or `relay_refused`) or the runner's role changes or its relay ends, or `REQUEST_TIMEOUT` (10 s) passes; a socket drop forgets it. A `relay_refused { code, message }` shows `message` in the status line (3 s, open menu or not) and frees the key; the mod logs `code` and branches on none.

Per frame, the key costs two timers and a few comparisons; the row strings are built on receipt and cached.

### Overlay

What a relay runner reads is data built once, in `mod/src/core/relay_view.rs` (`RelayView`), and cached on the machine (`relay_view()`): the strings are rebuilt on `auth_ok`, on each `relay_update`, when the machine's role changes (a take received, given up, acknowledged, its confirmation window over), when the displayed layer changes, when the key's label is set, and once per displayed second of an offline holder's countdown (the machine counts down from the seconds in the `RelayInfo` as received and compares the displayed second once per tick). Nothing is formatted per frame; the hold progress is a number (`relay_hold_progress`). Geometry is pure (`mod/src/core/item_banner.rs`, `relay_block_layout`, `relay_block_bounds`): the title hangs from the same height as the item banner's icon, rows are 1.6 line heights, sizes follow the screen's width (its height times 16/9 on an ultrawide); the drawing measures the texts, cuts every name and zone to `text_max_width` with its truncation helper, and the bounds stay inside the display.

Nothing relay-specific is shown while the team is not live (setup, finished, abandoned, disqualified), when the runner is out while the team plays on, or on an unknown role or team status. The BATON line of the panel reads the holder ("Kahleeya"), "you" for the holder, "free" when the baton can be taken, "nobody" when none is named and it is not free, then the runner's own counter against the cap as given ("you 2/5 zones", "3/5 zones" as holder, "6/5 zones" past the cap) and the key hint ("F8 pass" for the holder, "F8 take" only while the take is actually offered, `relay_baton_hint`: not while the banner says "Not ready yet" or "Waiting for the server").

The waiting banner, top centre, for a runner who waits:

- Giver, from the flip of a handoff it answered ("Giving the baton"): "BATON PASSED TO <RUNNER>", "Returning to the Roundtable Hold..." (pulsing), no detail. It stands in for whichever waiting banner the view holds until the player is blocked: the first frame not loaded (the warp's loading screen, a death's, a gate warp still in flight), the map reading the Roundtable Hold, or the return given up (its raises spent, or `WARP_LANDINGS_MAX` landings elsewhere). It never lasts less than `BANNER_DURATION`, so a giver already at the Roundtable Hold, or warped at once (a capped giver, the banner then over the loading screen), still reads it; it goes at once when the runner stops waiting (a take, the relay over). The text is built once at the flip (`relay_view::passed_banner`) and its end is a few comparisons per frame in `maintain_relay` (`PassedBanner`, `mod/src/core/relay.rs`). A takeover shows none.
- Holder online: "WAITING FOR THE BATON", "<holder> is in <zone>" ("<holder> holds the baton" without a zone), "Zone 9 of 12. You: 2/5 zones.".
- Holder offline, wait running: "<HOLDER> IS OFFLINE", "The baton can be taken in 42 s", "It goes back to <holder> if they return before then.".
- Baton free: "THE BATON IS FREE" and one of "<holder> has been offline for over a minute", "The holder left the race" (nobody is named), "The handoff was not completed" (holder online, or the runner itself). Its last line is "Hold F8 to take the baton at the entrance of <zone>." with the hold bar, or "No fresh save: you cannot take the baton." (not validated), or "You are at your cap.", checked in the server's order. Until the runner is ready (at the Roundtable Hold with both locks asserted, on a save whose token reads bound or before any token is drawn: "Lock and Roundtable", "The save token") the prompt reads "Not ready yet: wait at the Roundtable Hold.", and "Waiting for the server" while its request is in flight.

The holder's menu, opened by the key: "PASS THE BATON", one row per teammate not out (name, then the counter or the reason as in "The baton key"), the highlight, the hold bar, and the hint `F8 next   hold F8 to pass   closes by itself after 5 s` (its three parts are separated by three spaces; with no one eligible only the last part, and "Nobody can take the baton right now" or, with no teammate left, "No teammate can take the baton"). The transient banners ("YOU HAVE THE BATON", "QUOTA REACHED: PASS THE BATON") use the 4 s race item banner.

A save that is not the member's shows the wrong-save banner, "WRONG SAVE LOADED" and "Reload your race save" (`render_wrong_save_warning` in `mod/src/dll/ui.rs`), whether the IGT or the token found it ("The save token").

The key and its drawing (`mod/src/dll/hotkey.rs`, `ui.rs`). The key is `relay` in the `[keybindings]` of `speedfog_racing.toml` (default `f8`, `none` unbinds it, and every key hint is then replaced by the one line "No baton key bound: set `relay` in the config", the BATON line showing no hint and the waiting banner no hold bar; the key names are the table of `mod/src/core/key_names.rs`, aliases mapping to the first name listed; the race config the server generates writes `relay = "f8"`, a training config does not). The defaults of the mod's keys are F9 (panel), F10 (leaderboard) and F8 (baton). The shell reads the key's level each frame, and only on a relay race (`TickInput.relay_key_down`): ImGui's key state, true only while the game window is the foreground window of the process. ImGui learns of a release only through the game's own window messages, so a key released while another window had the focus would stay down for good: the level drops as soon as the game loses the focus and stays down until ImGui reports the key up, so returning to the game with the key already released is no hold. The frame where the focus is lost also tells the machine (`TickInput.relay_key_cancel`) that the press was cut short: the menu and the take hold drop it, so it is no tap (the highlight does not move) and no confirm, and the menu's auto-close is left to count from the last real press or release. The hint's label is the configured key's name in upper case (`Hotkey::label`), given to the machine with `set_relay_key` (`None` for an unbound key).

One block at a time hangs top centre, in a full-screen click-through window (the item banner's flags, so no widget takes focus): the menu when open, else the race item banner when one shows, else the waiting banner. What is drawn:

- Waiting banner (`render_relay_wait`, from `relay_wait_banner`): the title in its tone (fog `purple` for "WAITING FOR THE BATON", ember `danger` for "<HOLDER> IS OFFLINE", verdigris `success` for "THE BATON IS FREE", brass `gold` for "BATON PASSED TO <RUNNER>"), the line in `text`, its opacity and its shadow's times `relay_wait_line_alpha` (the pulse of "BATON PASSED": from 1 down to `PULSE_MIN` and back every `PULSE_PERIOD`, a cosine computed at draw time; 1 otherwise), the detail in `text_disabled`; with the hold prompt, a bar of the menu's width centred under the detail, its track `text` at 0.15 alpha, its fill `success`, filled by the hold's progress.
- Menu (`render_relay_menu`): "PASS THE BATON" in brass (`gold`); one row per teammate, the name left in the body face and the counter or reason right in mono (a row that cannot receive in `text_disabled`); the highlighted row filled with `gold` at 0.18 alpha, outlined at 0.6, the hold bar along its bottom (track `text` at 0.15, fill `gold`); below the rows, the note when nobody can receive (and in place of the rows when there are none), then the key hints in `text_disabled`.
- The transient banners ("YOU HAVE THE BATON", "QUOTA REACHED: PASS THE BATON") are the item banner with no icon, laid out with the relay block's geometry (`banner_layout_for`: same top and sizes as the waiting banner and the menu, so a banner replaces the waiting banner in place): gold title for the gains. The item banner of a race item, with its icon, is unchanged.
- BATON line (`render_relay_line`, in the panel under the tier line): "BATON" in fog (`purple`), the holder, the counter in `text_disabled`, the hint right aligned in `text_disabled`, all mono.
- A waiting runner's panel: the zone is the one the server names, the IGT and the deaths are the team row's.

Every text from the server is cut to the layout's `text_max_width` with `truncate_to_width`, and the cut and its measured width are kept (`CutCache` in `ui.rs`, keyed on the text, the width limit and the pixel size): a frame in between compares strings and allocates nothing. The banner faces carry the ellipsis for that.

Which block is on screen: the waiting banner and the item banner hang from the same band, and the fullscreen countdown's ring crosses it, so the waiting banner shows only with no menu open, no item banner and no countdown (`relay_wait_visible`); the open menu shows over an item banner and yields to the countdown (`relay_menu_visible`). `gap_uses_local_igt` says when a leaderboard gap takes the runner's local IGT: its own row, playing, and on a relay race only the live holder (a waiting runner's own IGT is not its team's), and `am_i_abandoned` reads a relay member out while its team plays on as out.

### Game access

Two threads of the mod touch the game here. The frame thread is the tracker's own: the Present hook, where the overlay draws and the machine ticks once per frame. It is not one of the game's own threads, and nothing the mod writes from it is synchronised with them, as the race items' and the lock's writes are not. The worker is a thread of the shell's, for reads that take time.

The shell's relay worker (`mod/src/dll/tracker.rs`) runs one job at a time, on a thread of its own named `relay-worker` (the name Tracy and a debugger show), so a capture never scans the grace flags while an apply raises them. Its scheduling is pure (`mod/src/core/job_queue.rs`): a job asked while another runs waits behind it, in order; a waiting job of a replaceable kind is replaced, in its place, by a newer job of the same kind, and a job of a kind that is not replaceable is never dropped. A capture is replaceable: the machine asks again only once it has given up its previous request, so a release that pre-empts a checkpoint is started as soon as the checkpoint's job ends, and the checkpoint's answer is dropped by its generation. An apply is not: every apply is answered, once, and it stays the running job until its writes have ended (below), so a job asked meanwhile waits behind the writes too. The answer goes to the machine on the frame thread, at the start of the first frame after the job ended, with the identity the job was asked with; a thread that panicked, or that the OS did not start, answers as a failed job. A job that never ends blocks the worker for the session: the jobs behind it never start, and the machine cancels each release at 12 s. Per frame the worker costs an `Option` check and an atomic load.

A capture (`mod/src/eldenring/relay.rs`; what its reads must pass and the state they build, in `mod/src/core/relay_capture.rs`) reads, in order: the game's grace flags (the `eventflag_id` of every `BonfireWarpParam` row: the first relay job of the process reads them, outside the timed reads, then they are kept, the regulation not changing in a session), the loaded map, whether each grace flag is set, then the loaded map again. Any of these fails the capture (answer `None`: a release is asked again 500 ms later, a checkpoint is dropped), never a state partly read:

- no map loaded when the reads begin (`NotLoaded`);
- the map read differently, or not at all, at their end, or the reads took over 1 s (`READ_WINDOW_MAX`, taken as shorter than any load): a load may have come in between (`LoadDuringCapture`);
- the event flag reader down, or none of the grace flags read (`FlagsUnreadable`).

A grace table that does not read fails no capture: it is warned once per session, with the cause (`NotIndexed`, its name not in the game's param index, or `NoUsableRow`), and left empty, so the states of the session carry no grace. A grace flag the reader cannot read counts as not lit, and how many there were is logged: the reader answers the same for a flag of a category the game does not hold, and one grace row the game does not use must not fail every capture. The state is then fitted to the wire caps ("What a state carries"). A capture writes nothing. Every read of the game goes through `ReadProcessMemory` (libeldenring's pointer chains behind the loaded map, the event flag reader), which fails rather than faults on an unmapped address, as the item spawner's own thread already reads flags off the tracker's frame thread. The param rows are not: they are dereferenced directly (libeldenring hands out references into the game's param tables, which live for the session) and one field is copied out of each, as the race items read and write their param rows.

What a capture relies on, and whether the game has confirmed it:

| Id  | Fact                                                                                                                                | Source                                                          | Confirmed in game                                       |
| --- | ----------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | ------------------------------------------------------- |
| R1  | A grace is lit when the event flag `BonfireWarpParam.eventflag_id` of its row is set; the table goes by the name `BonfireWarpParam` | libeldenring param codegen                                      | Yes, 2026-11-23 (C2, C3)                                |
| R2  | The loaded map id reads `None` during a loading screen                                                                              | `GameState::loaded_map_id`, the readability read of every frame | Yes, at every loading exit of the zone tracking         |
| R3  | A load (the map unloaded, then one loaded again) lasts over 1 s                                                                     | `READ_WINDOW_MAX`                                               | No (checklist E2: a capture across the start of a load) |

Log lines: `[RELAY] Worker job started` (the job: its `handoff_id` and generation), `[RELAY] Worker job queued behind the running one` (the running and the queued job), `[RELAY] Worker job replaced while it waited` (the job dropped), `[RELAY] Worker thread not started, job failed` (warn level) and `[RELAY] Worker thread panicked, job failed` (error level). The first relay job of a process logs `[RELAY] Grace flags read` (`flags`: how many), or for a table that does not read `[RELAY] Param table unreadable, no grace transfers this session` (warn level, once: the `table` and the `cause`). Each capture logs `[RELAY] Character read` (generation, `graces_scanned`, `graces_unreadable`, `graces`: how many are lit, `elapsed_ms`) or `[RELAY] Character not read` (generation, the `failure`, `elapsed_ms`; warn level), and `[RELAY] State cut to the wire caps` (`cut`; warn level) when the state was over the caps. The machine logs `[RELAY] State captured` when it sends the state.

A take writes the game in two parts ("Taking the baton"); the shell side is `mod/src/eldenring/relay.rs`, the rules `mod/src/core/relay_apply.rs`. The IGT is the existing write (`Effect::SetIgt`, `GameState::write_igt`), made on the take's start frame, before the effect returns.

The apply (`Effect::ApplyRelayFlags`) is a worker job. Its thread reads and plans, and writes nothing: the game's grace flags (as a capture reads them), then the plan (`plan`): the state's grace flags that are graces of this game (any other is left out and counted, `not_grace`), then the take's boss defeat flags (the machine kept only the seed's bosses), each flag once. The writes are made on the frame thread, after the machine's tick, from the frame after the plan: the grace flags, then the defeat flags. They are not synchronised with the game's own threads: a flag raise is a read-modify-write of a byte the game may write at the same moment, and nothing proves it never does (the lock's writes rely on the same). A frame's batch stops at 16 raises (`APPLY_WRITES_PER_FRAME`) or once 1.5 ms of its own wall time is spent (`APPLY_FRAME_BUDGET`), whichever comes first, after at least one write, so an apply moves on every frame. A flag raise was measured with Tracy at about 13 µs (six raises, 2026-11-23, checklist D7 and D8): at the ceiling the largest state, 1000 graces and a team's bosses, is raised in about 64 frames (about 1 s at 60 fps), and the budget is a guard a normal apply does not reach. A test aid, never to be set for a real race: when the environment variable `SPEEDFOG_RELAY_SLOW_APPLY` holds a number of milliseconds at the mod's start (read once by the tracker, absent, unparsable or 0 means off), the apply makes at most one write per that interval instead of a batch per frame, so a kill, a quit-out or a cut connection can be placed inside an apply (checklist F1, F2, F4); the pacing rule is `ApplyRun::set_min_interval` (`mod/src/core/relay_apply.rs`) and the mod logs one warn line at start, `[RELAY] Slow apply is on (test aid): one write per interval`. The stop rules and `APPLY_DEADLINE` are unchanged, so a slow apply of a plan longer than the deadline divided by the interval ends on the deadline with the writes left counted. Off, it costs a field test per frame. The loaded map is read again right after a batch that wrote. A flag is raised through the event flag reader as the lock is (`set_flag_cached`, the category page resolved at the frame's first flag). A write counts as done before it is tried, so a frame that panics never writes it twice, and the write it panicked on counts as failed. The writes end for good at the first of:

- every write tried (a failed one is counted and its flag logged);
- a frame since the ask (the plan's reads included) that read another map or none: a loading screen (quit-out, death, a warp) started, so nothing is written into what the game is rebuilding, even once the map reads the Roundtable Hold again;
- the take no longer applying (given up, replaced by a newer take, abandoned: `RaceMachine::relay_apply_wanted`);
- 15 s since the ask (`APPLY_DEADLINE`, under the machine's 20 s `APPLY_ABANDON`), whatever is left.

Then the machine gets `relay_state_applied`, on the frame thread, once per apply: nothing of that apply is written after it. An apply whose plan never comes (its thread panicked or did not start) answers too, nothing written. The answer carries how the writes ended. A stop by a load (`MapChanged`) is not final for the take: the machine starts it again once the runner is loaded and settled at the Roundtable Hold, up to 3 starts ("Taking the baton"), and the new apply raises every flag again (a flag raised twice is harmless). Any other stop (the deadline, the take no longer applying), or a load at the last start, is final: the take is acknowledged with what got written, and nothing tries the rest again. The graces not yet raised are then lost for the team, because the next handoff captures this runner's lit graces; the boss defeat flags come again from the server with every take, so only this runner's world misses them. Per frame, with no relay job running, the apply costs an `Option` check; while one runs, a walk of the jobs queued (each apply watches the frame's map from its ask on) and the running apply's batch.

What an apply relies on, and whether the game has confirmed it:

| Id  | Fact                                                                                                              | Source                     | Confirmed in game                                                                       |
| --- | ----------------------------------------------------------------------------------------------------------------- | -------------------------- | --------------------------------------------------------------------------------------- |
| W1  | A grace whose `BonfireWarpParam.eventflag_id` is set is lit and fast travel goes to it                            | libeldenring param codegen | Yes, 2026-11-23 (D7)                                                                    |
| W2  | A boss whose defeat flag is set stays dead and its fog gate open, the seed's events reading the flag              | the seed's boss flags      | Yes, 2026-11-23 (D7)                                                                    |
| W3  | A flag raised from the frame thread (a read-modify-write of its byte) loses no bit the game sets in the same byte | the lock's writes          | The lock's byte: yes. The bytes of graces and bosses: no bit seen lost, 2026-11-23 (D7) |
| W4  | A quit-out or a death shows as a frame with no loaded map before the game rebuilds the flags                      | `GameState::loaded_map_id` | At every loading exit, yes; at the start of a load during an apply: no (F4)             |

Log lines of a take: `[RELAY] IGT written` (`ms`), or `[RELAY] IGT not written (IGT unwritable)` (warn level). The apply: `[RELAY] Worker job started` (the job: its `handoff_id`, generation and counts), then from its thread `[RELAY] Grace flags read` at the first relay job of a process, and `[RELAY] Apply planned` (generation; `defeats`; `graces`; `not_grace` and `not_graces`, the state's flags that are no grace; `elapsed_ms`). The end: `[RELAY] State applied` (`handoff_id`, generation, `written`: the raises made and failed, by kind, `elapsed_ms` since the ask), or `[RELAY] State applied in part` (with `end`: `Deadline`, `MapChanged`, `NotWanted`, or `Complete` with failures; `failed`: the flags whose raise failed; `left`: the writes not made; warn level), or `[RELAY] State not applied (its plan never came)` (warn level). The machine then logs `[RELAY] Take applied` and, on the first frame whose IGT reads in its window, `[RELAY] Take acknowledged`.

## Before enabling relay races

Relay races are off behind a server setting. What must be done at launch:

1. The web help page lists the baton key with the other shortcuts: add it to the block that lists F9 and F10 in `web/src/routes/help/+page.svelte`. It is left out while relay races are off, so that the page does not advertise a key that does nothing.
2. Turn the server setting on ("Rules": `RELAY_RACES_ENABLED`).
3. Release a mod build that speaks the relay protocol (`docs/PROTOCOL.md`, "Protocol Version"), so the seed packs carry it.
4. Regenerate the pools with the relay plugin at graph.json 4.16, so relay seeds exist: a seed of an earlier block is not a relay seed ("Seeds").
5. Build the mod's side of the boss loot. The server sends each member the loot of the team's bosses (`relay_loot`, "Boss loot"), and this mod parses the message and drops it with a debug line: a runner keeps their own character, so a team whose loot is not given shares only its dead bosses and lit graces. A relay race must not be opened to players before the mod gives the loot.
6. Check that nothing players read or run sets `SPEEDFOG_RELAY_SLOW_APPLY` ("Game access"): it is a test aid that slows every apply of a take, and a real race must never carry it.
7. Run the in-game checklist below.

## Not proven yet

Server and web:

- The row-lock discipline ("Ordering": `SELECT ... FOR UPDATE` on the team rows, in one order) has only run on SQLite, which ignores `FOR UPDATE`. The tests check the statements PostgreSQL receives, never two transactions contending for a team on PostgreSQL. (The migrations were run up, down and up again on PostgreSQL 17, and `alembic check` finds no drift on the relay tables and columns.)
- The relay bot ran end to end against a server on 2026-11-23 (checklist 0.1), before it confirmed tokens and printed the loot it is sent: those two have run against no server yet ("Bot"; checklist 0.1 runs them).
- The web screens of a relay race were seen in a browser through the checklist's section 0 on 2026-11-23 (the race creation tile, the setup team list, the team rows of the leaderboard). The team map and its popup, the invite page's team select and the finished-race page ("Web", "Outside the live page") have no step and are tested through their pure functions only.

Mod: the facts tables of "Mod" say what the game has confirmed. Sections 0, A, B, C and D0 to D8 of the in-game checklist ran on 2026-11-23 with a build that held waiting runners at the Chapel with the lock alone and copied the giver's character at a take ("before the Roundtable revision"); the facts they settled that this build keeps as they were are recorded in the tables with that date. This build has not run in the game: the unit tests cover the pure machine (`cargo test --lib`) and the shell type-checks for Windows. What only the game proves, each step of the checklist naming the facts it settles:

- The locks and the Roundtable Hold, L1, L3, L4 and L6 to L9 ("Lock and Roundtable"; checklist A, with E1, E10, F8 and F9): above all the Roundtable Hold's map id (L1), without which no runner is ever ready, then the Roundtable warp, the travel lock on both maps and a capped holder's travels.
- The save token, S1 to S6 ("The save token"; checklist A2b, A5 and K): above all that its flags read (S1) and are saved (S3), without which no runner is ever ready after a reload.
- Reading the graces across the start of a load, R3 ("Game access"; checklist E2).
- Raising flags across the start of a load, W4 ("Game access"; checklist F4).
- Taking, T3 to T6 ("Taking the baton"; checklist D0, D1, D2, E3, E4 and F6): both locks lowered and a warp flag raised on one frame at the Roundtable Hold, the take before the team's first gate landing at the Chapel, the connection warp from the Hold, the IGT surviving a quit-out; and a take's duration with the largest state (D8).
- Giving, the key and the overlay as drawn (checklist B, D0b, E1, E10, E11, F7): the Roundtable strings in their banners, the locks and the return to the Roundtable Hold after a flip, the menu with five teammates and long names, the focus rule in the menu. B, C8 and D0b ran on 2026-11-23, before the Roundtable revision, with the Chapel's strings.
- The restarts (checklist F1, F2, F4): a take sent again after a crash or a reconnection, applied and acknowledged once, and a take started again after a load cut its apply.
- The cost per frame (checklist H): the spans of the machine, the overlay, the apply and the token under Tracy.
- The boss loot: the server sends `relay_loot` ("Boss loot"); this mod parses it and drops it with a debug line (`[RELAY] Loot received`). Giving it is not built, and no step of the checklist covers it.

Known limits, accepted when they were recorded and each visible in the checklist:

- An apply stopped before its end leaves the graces not yet raised missing for the team, since the next handoff captures this runner's lit graces (the boss flags come again with every take): only on the apply's 15 s deadline, or after three applies of one take cut by a load (a death or a quit-out at the Roundtable Hold each time). A load before that starts the take again, raising everything again; a game killed during an apply is applied again by the relaunched process (the server sends the take again); a cut connection does not stop the apply.
- An apply raises the grace flags first, then the defeat flags. Raising a defeat flag while waiting started no loading screen and no event at the Chapel (D7, 2026-11-23, before the Roundtable revision); at the Roundtable Hold it is assumed the same (D7 watches it). A load one started would cut the apply and start the take again.
- A receiver whose mod reconnects in game between its `auth_ok` and the take sent again can see the locks flap for a frame or two.
- The save token's limits ("The save token"): after a race reset every member needs a new character; a game that ends between the token's confirmation and the game's next save leaves the member bound on a save without the token, which only a race reset frees; a holder on a wrong save can still ask for a handoff, which is then cancelled at 12 s.
- LiveSplit on a relay race is not addressed ("Roles").

Open points for the project owner, decisions rather than defects of the build, each left as it is today:

- An offline holder keeps playing unlocked for as long as its link is down: nothing locks it until its mod hears the server again, even once a teammate has taken the baton after the 60 s wait. What it lights or kills meanwhile reaches the team later: through its next checkpoint once it holds the baton again after it reconnects (its captures carry its lit graces), or, for a kill, reported after a relaunch of its game. Two runners can thus progress in parallel, one of them offline. A mod that locks itself after 60 s without a link would also lock a holder through any long outage when nobody takes over (a gameplay trade-off); a server-side check (refusing a kill that is not at the team's current zone) is the other way.
- A reconnection that holds its replays (its take's acknowledgement not confirmed yet, "Taking the baton") holds only the replays, for about one round trip with the server. New progress made meanwhile (the flags of a loading exit, a kill) still goes out at once: a server still awaiting the take drops it, or it overtakes the zone entry being held. And any `relay_update` naming the runner holder that the server sends in that window for another reason (a teammate's readiness or validation) is taken for the confirmation, which releases the replays before the acknowledgement the server awaits. Closing both would take the server echoing the acknowledged `handoff_id` in its update.
- A take started again after a load writes its IGT again, so the time since the previous start (the cut apply, the load and the settle) is not counted for the team: at most about 20 s over two restarts.

## In-game checklist

One protocol, to follow from top to bottom, on a Windows build of the mod. The sections go in play order, the most dangerous unknowns first (the Roundtable Hold's map id and the save token, on which every runner's readiness depends, then the writes of a take), so that a crash or a corrupt save shows before time is invested. The order is also read-only first: before the read-only checks of section C the mod writes only its two locks and the Roundtable warp flag (section A), and the token's flags (A2b, in the seed's flag category 1050297, which they share with the loot received flags and the seed's page flag, and which nothing in the seed reads for the token). Without them no runner is ever ready, so no later step can be tested. The first take, which writes the IGT and raises flags, comes in section D.

Each step says what to do (**Do**), what must be seen (**See**), the log line to look for (**Log**, quoted as the code emits it; its fields come on the same log line), what a failure looks like and what it means (**Failure**), and the fact it settles (**Proves**, an id of the facts tables of "Mod": `L` in "Lock and Roundtable", `T` in "Taking the baton", `S` in "The save token", `R` and `W` in "Game access"). When a fact is confirmed, change its "Confirmed in game" cell to the date and the step; when it is refuted, say so in the same cell and open the matching fix. A step keeps its id from one version of this protocol to the next, so that a record keeps naming the same step: the ids that are skipped belong to steps this build has no use for. The cells already hold what a run of sections 0, A, B, C and D0 to D8 settled on 2026-11-23 ("before the Roundtable revision", see "Lock and Roundtable") for the facts this build keeps as they were; every step below is still to run on this build.

The seed side (the lock, the warp flags, the Chapel warp, the fast travel refusal) was checked by hand, without this mod, with Cheat Engine: `docs/plugins/relay.md` of the speedfog repository, "In-game checks" 1 to 15. Those are not asked again. Its checks 16 to 19 (the travel lock on both maps, the lock alone, the Roundtable warp, the flag category of the token) are not recorded as done there: run them by hand first, on a seed of the pool, so that a fault of the seed does not read as one of the mod's (A1, A2, A2b, A8 and E10 are where the mod meets them). That document records as not checked the lock on the gate events when it is raised during a load (its check 13), a warp raised while sitting at a grace or with a menu open (its checks 15 and 18) and the cutscene transitions: steps A6, E3 and E4 below are where the mod meets them.

### Before you start

- **Mod build.** On Windows, from this branch: `cd mod && cargo build --lib --release`. Note `git rev-parse --short HEAD`: the first line of the mod log carries the commit (`SpeedFog Racing mod starting...`, with `commit`). Copy `target/release/speedfog_racing.dll` over `tools/assets/speedfog_racing.dll` on the server machine (`MOD_DLL_PATH`): every seed zip the server hands out afterwards carries that DLL. A second build with `--features profile-tracy` is needed for the steps that say Tracy ("docs/MOD_PROFILING.md": Tracy v0.13.1, a profiling DLL is never distributed). Use the plain build for everything else.
- **Server.** The dev server on :8000 with `RELAY_RACES_ENABLED=true` in `server/.env` (restart it), started without `--reload` (a reload on an edit drops every socket). Its log is the terminal it runs in; the lines this checklist quotes start with `Relay`.
- **Pool.** A pool regenerated with the relay plugin (graph.json 4.16; `tools/pools/_base.toml` enables it), scanned with `cd server && uv run speedfog-scan-seeds --pool <pool>`. `GET /api/pools` must report `relay_available` above 0 for it. Each race consumes a seed: plan the races below and add copies of a relay seed under new names, scanned again, as the race items protocol does.
- **Races.** Six, and a seventh when a second player is there, created on `/race/new` with the Relay tile. Race 0, bots only (0.1). Race 0b, teams of 2, `Starts: bot1`: 0.3 (you join Alpha but keep your game closed until the start). Race 1, teams of 2, `Starts: bot1`: sections A and B. Race 2, teams of 2, `Starts: you`: section C. Race 3, teams of 2, `Starts: bot1`: sections D, K, E (E1 to E9) and F. Race 4, teams of 6, `Starts: you`: E10 to E13 (the cap, the menu with five teammates, the final boss, the banners) and section G, which ends the race in each way. Race 5, teams of 2, `Starts: you`, only with a second player: E9. Every race has two teams: Alpha (you and the bots of your team; you and the second player in race 5) and Beta (two bots; at least 2 teams must count, each with its first runner ready). You are the race's organizer.
- **Teammates.** One game instance, so the bot stands in for the teammates: from `server/`, `uv run python ../tools/relay_bot.py <race_id> --team Alpha=bot1 --team Beta=bot2,bot3 [--state FILE]` (race 0: `--team Alpha=bot1,bot4 --team Beta=bot2,bot3`; race 4: `--team Alpha=bot1,bot2,bot3,bot4,bot5 --team Beta=bot6,bot7`). The bots are local users; never name yourself. In setup the tool places them in their teams (a team missing from the race is created); started again later, with another `--state`, it only reconnects bots already in the race. The bot (see "Bot") holds the baton, passes it (`pass`), takes it (`take`), acknowledges a take or ignores it (`mute`), goes offline and comes back, walks, kills a boss, finishes, and confirms its token. It cannot carry anything of its own: as a giver it sends the same state for the whole run, `FAKE_STATE` by default (`{"grace_flags": []}`, no grace) or the file given with `--state`, and it sends no checkpoint. So a take that must carry graces uses a `--state` file; the giver side of the mod (capture, release) needs your game as the holder; and a full circle between two real characters needs a second player on a second PC (**two players**: they join your team from their own account, with their own fresh save and the same DLL).
- **Characters.** A fresh New Game for every race you play, a waiting one included: the fresh-save gate asks it, and a save carries the token of the race that validated it. Character G is race 2's: you light graces as its holder (at least five, some by hand with Cheat Engine if the run is short: `Event Flags by ID` on the `eventflag_id` of a `BonfireWarpParam` row, read in Smithbox); section C reads them. Character R is race 3's, the receiver of sections D to F, with a new one for race 4.
- **State files**, for the bot, from `server/`, written in step C9 (its table lists every file, its content, its step and what `[RELAY] Apply planned` must show): each a `CharacterState`, `{"grace_flags": [...]}`, checked by the tool at startup against the server's own model.
- **Log.** `speedfog_racing.log`, in the folder of the DLL (the `lib` folder of the seed pack). It is appended to from run to run: note its size, or delete it with the game closed, before a section. The level is `info`; set the environment variable `RUST_LOG=debug` in the shell that launches the game for the steps that say debug (it is read once at start). Every relay line starts with `[RELAY]`.
- **Slow apply (test aid).** Steps F1, F2 and F4 need an apply that lasts about 10 s: launch the game with `SPEEDFOG_RELAY_SLOW_APPLY=500` (the log says `[RELAY] Slow apply is on (test aid): one write per interval`) and give `s8.json` of C9, 20 grace flags. Race 3 carries the boss the team killed in D7, whose defeat flag every take raises again, after the graces: an apply's writes are the `graces` and the `defeats` of `[RELAY] Apply planned` (20 and 1 after D7, more defeats if the team killed another boss since). With one boss that is 21 writes, about 10 s at one write per 500 ms (the first is at once), inside the 15 s deadline. Every apply of the file plans the same writes, whatever the save already holds: a grace raised again is a write like any other. Unset the variable and relaunch afterwards.
- **Fresh save.** Every runner of a race, the waiting ones included, starts a New Game on the seed (IGT at most 60 s at the first report). A relaunch of the game in the middle of a race reloads the same character and is fine. Back up the save files before section A: from there the mod writes its locks and the token into the save, and from section D a take's IGT and flags.
- **Tools.** Cheat Engine with The Grand Archives table (`Event Flags > Event Flags by ID`, re-type the ID after an action: its `State` is a snapshot) for the locks, the warp flags and the token's flags; Smithbox for grace flag ids. The flags of a seed are in its `graph.json` under `relay`: `lock_flag` 1050290500, `chapel_warp_flag` 1050290501, `travel_lock_flag` 1050290503, `roundtable_warp_flag` 1050290504, `warp_flag_base` 1050290510, `token_flag_base` 1050297900 over `token_bits` 24 (see "Seeds").
- **Record** each step as pass, fail or not reached, with the log lines. A failure that the step marks as stopping ends the section: nothing after it can be tested.

### 0. Validation

- **0.1. The bots alone, before the game joins** (race 0: two teams of two bots, no game, `--team Alpha=bot1,bot4 --team Beta=bot2,bot3`). **Do:** start the tool, start the race from the web once every bot reports ready, then drive it: `status`, `walk bot1`, `boss bot1`, `pass bot1 bot4`, `offline` the holder of a team and `take` with its mate after 60 s, `mute` a taker and wait 30 s, `online`, `finish` each team. **See:** the console and the web's team rows follow, the race finishes when both teams have; at `boss bot1`, on a boss with loot, each bot of Alpha prints a `loot:` line (bot1's with `paid=True`). **Log (server):** `Relay member bound to their save:` once per bot (each confirms the token it is sent), `Relay baton flipped`, `Relay take acknowledged`, `Relay take not acknowledged, baton free` (the muted taker), `Relay team finished`, `Race finished`. **Failure:** the tool stops in its setup insert or its socket loop: fix the tool before any game step. **Proves:** the bot's setup, socket loop, token confirmation and console, and the server's baton operations against a real client ("Not proven yet").
- **0.2. The game joins and every member is validated.** **Do:** in race 1, create Alpha and Beta in the web, join Alpha with your game's account, choose `Starts: bot1` for Alpha, start the bot tool (no `--state`: its bots never give in race 1). Launch the game from your pack with the mod: its connection makes you ready on the web from the title screen on, and the mod's leaderboard reads a team `ready` once its first runner is (Alpha's is bot1). Start a New Game and load into the world (past the character creation, in control of your character), then start the race from the web within about 45 s: your first report after the 10 s countdown must read an IGT of at most 60 s. **See:** nothing is locked in setup: the gates react, fast travel works (check it on a character of its own before the New Game of the race: the time it takes would fail the fresh-save gate). Validation is not shown by the bot's `status` nor by the web's team row: it is in the server log. **Log (mod):** `[WS] Race started!`; **(server):** `Relay member validated:` for you and for each waiting bot (a team's first holder is validated by the team's first report, which logs no such line), then `Relay member bound to their save:` for every member. **Failure:** a game that loaded an old save instead of a new one shows the blocking banner "Please start a New Game", and the server logs `Rejected stale save (relay member)` instead of `Relay member validated:` for it. Try it once with a used character: a handoff to that runner is answered `not_validated` (bot console: `refused: not_validated: ...`) only if the runner is connected and ready at the Roundtable Hold with both locks raised; otherwise the server answers `target_unavailable` first (its checks are in that order). Then start a New Game. **Proves:** the fresh-save gate for a waiting member (server side, seen through the mod).
- **0.3. A runner who shows up late** (race 0b, the bot tool as in race 1). **Do:** create Alpha and Beta, join Alpha with your game's account, choose `Starts: bot1` for Alpha, start the bot tool, and keep your game closed: launched, its mod would make you ready even from the title screen. Start the race from the web: it starts (each team's first runner is ready), and you stay `registered`, in Alpha. Read the bot console's `status`. Then launch the game, start a New Game and load into the world. **See:** before you launch, Alpha's cap is a lone runner's, `layers + 1` (only bot1 plays); once your mod connects the web shows you ready and the cap does not move; at your first report you are validated (the web reads you playing) and Alpha's cap drops to `ceil(layers / 2) + 1` in `status`. You are then sent to the Roundtable Hold and wait for the baton with the waiting banner (no take here: the first take is D0). **Log (server):** `Participant ready:` at your connection, then `Relay member validated:` with your IGT and `Relay member bound to their save:`. **Failure:** the cap dropping at the connection (it must wait for the validated save), a start refused for you not being ready, or you left `abandoned` at the start. A New Game loaded too long before your first report shows "Please start a New Game" (`Rejected stale save (relay member)`). If you never report, the no-show rule takes you out 30 minutes into the race. **Proves:** a member not ready at the start stays in the race and joins it later; the cap counts only the members whose save is validated.

### A. The lock and the Roundtable (race 1, you wait, bot1 holds)

If A2 or A2b fails, stop: no runner is ever ready, and nothing after it can be tested. The writes of this section are the two locks, the Roundtable warp flag and the token's flags, the only ones before the reads of C (see the introduction). Whenever the gates still react or fast travel works where the mod says it raised a lock, look for `[RACE] Game flag not written` (warn level) with `flag_id=1050290500` (the lock) or `flag_id=1050290503` (the travel lock): the shell could not write the flag. Without that line the write was made and the game did not honour it, or the seed's flag id is wrong. Cheat Engine tells which: the flag reads ON or OFF.

- **A1. The locks come with the start.** **Do:** stand at the Chapel's fog gate, its prompt shown, when the countdown starts; try F8 (hold it): nothing happens. **See:** within a moment of the start the gate's prompt goes; no lock before the start. About 5 s later the mod warps you to the Roundtable Hold (A2). **Log:** `[WS] Race started!`, then `[RELAY] Lock raised` and `[RELAY] Travel lock raised`, both with `reason="waiting"`, on the same frame. **Failure:** no `Lock raised` line: the machine did not read the relay (check the `auth_ok`, the protocol version, the team status); the line but the gate still prompts: `[RACE] Game flag not written` with `flag_id=1050290500` means the write failed; without it the write is not honoured (nothing is read back) or `lock_flag` is wrong. **Proves:** L2. The holder's side of the key during the countdown is not testable by one person (the server answers `busy`): the unit tests cover it.
- **A2. The Roundtable Hold's map id, as the mod reads it.** **Do:** after A1, do nothing for 60 s. **See:** one loading screen, about 5 s after the locks (during the countdown), that lands you at the Roundtable Hold by the Table of Lost Grace, then nothing more: no second loading screen, the character stays put. The first holder of a race stays where it is (C1 shows it for your game). **Log:** `[RELAY] Warp to the Roundtable` once, then, once there and settled, `[RELAY] Ready sent` with `ready=true` (the mod reports ready only at the Roundtable Hold with both locks asserted and its save's token bound, or none drawn yet: an initial `Ready sent` with `ready=false` is normal, and the `ready=true` usually waits for the token of A2b). No `[RELAY] Warp to the Roundtable landed elsewhere`. **Failure:** a second loading screen a few seconds after the landing, and the status "Warp to the Roundtable Hold failed": the mod does not read the Roundtable Hold as `ROUNDTABLE_MAP_ID` (`0x0B0A_0000`). The status shows for 3 s only: the durable evidence is the log, with `[RELAY] Warp to the Roundtable landed elsewhere` twice, its `map` field (`mWW_XX_YY_DD`, in decimal) being where the position read puts you, the value to put in `ROUNDTABLE_MAP_ID` with each part as a hexadecimal byte (`m11_10_00_00` is `0x0B0A_0000`). The mod then stops for the process, nobody is ever ready and the relay stalls: STOP. A landing somewhere else than the Roundtable Hold is the seed's warp (`roundtable_warp_flag`, the seed's check 18). No loading screen and no `Warp to the Roundtable` line points at the HP read or the position read (L5): record it. **Proves:** L1 (with `ready=true`), L4 (from the Chapel), L6 (the mod's side).
- **A2b. The token binds your save.** **Do:** nothing: your first report after the countdown validates your save, and the server sends your token. **See:** no "WRONG SAVE LOADED" at any time. **Log (mod):** `[RELAY] Token written` (`attempt=1`), then `[RELAY] Token confirmed` and `[WS] Sending: relay_bound`; `[RELAY] Ready sent` with `ready=true` a second or so after `Token confirmed`, once the server's answer reads you bound: as a rule your first `ready=true` of the race, since your first report waits for the countdown's end, when you are usually still on your way to the Roundtable Hold. If a `ready=true` went out before your first report, a `ready=false` comes with the token and the `ready=true` after the binding. **(server):** `Relay member validated:` with your IGT, then `Relay member bound to their save:`. **Failure:** `[RELAY] Token flags not readable` (warn level): the token's flags do not read, their category is not allocated on this seed (the seed's check 19): STOP, nobody is ever ready. `[RELAY] Token written` three times, then `[RELAY] Token not written, given up` (warn level): the writes do not read back; with `[RELAY] Token flags not written` (warn level, `failed` of `total`) the shell could not write them. `[RELAY] Token mismatch, wrong save` on this fresh character: a read that did not hold the save's values (S5) or a write that landed in part; note `read`. **Proves:** S1, S2.
- **A3. Sent back from the world.** **Do:** with Cheat Engine, raise a connection warp flag (1050290510 plus any n of the seed's build output) to put yourself in the world, then do nothing. **See:** `Ready sent` with `ready=false` as you leave the Roundtable Hold; about 3 s after you land (the loading exit closes the gate window, then the settle), you are warped back to the Roundtable Hold, one loading screen, then `ready=true` again. **Log:** `[RELAY] Warp to the Roundtable`, `[RELAY] Ready sent`; no `landed elsewhere` line (a warp raised by hand is no landing of the mod's). **Failure:** you stay in the world: the return never starts (HP read as 0 for a living runner, `L5`, or the map read as the Roundtable Hold while away); a log with `[RELAY] Warp failed` and the status "Warp to the Roundtable Hold failed" means the raise started no load three times (the seed did not react to the flag, `L7`). **Proves:** L4 (from the world), L5 (for living), L7 (the seed lowers the Roundtable warp flag and reacts to a later raise).
- **A4. A dead runner is not warped.** **Do:** raise a connection warp flag into a zone with enemies and die there at once (or fall). **See:** no warp while dead; you respawn at the grace you rested at last (the Chapel's on a new character), then the mod warps you to the Roundtable Hold. **Log:** no `Warp to the Roundtable` while the death screen shows; no `landed elsewhere` (a respawn is no landing). **Failure:** a warp during the death screen. **Proves:** L5 (for dead).
- **A5. The locks and the token across a quit-out and a relaunch.** **Do:** quit to the title and load the character; then close the game, launch it again, load. **See:** each time, after about 3 s, fast travel is refused at the Roundtable Hold (the map and the Table of Lost Grace), both flags read ON in Cheat Engine, no "WRONG SAVE LOADED" (the save carries its token), and you are ready again. **Log:** after the relaunch, `[RELAY] Lock raised` and `[RELAY] Travel lock raised` again (the process knows nothing of the old one); after a plain quit-out no new lock line (the locks are written again silently after each loading exit); no `[RELAY] Token mismatch, wrong save` and no `[RELAY] Token written` (a good read logs nothing); `[RELAY] Ready sent` with `ready=true`. A "WRONG SAVE LOADED" that shows for about 2.5 s after a load and lifts by itself (`[RELAY] Token mismatch, wrong save`, then `[RELAY] Token matches again, resuming`) means the first read after a load does not hold the loaded save's values: record it against S5, it is no failure of this step. **Failure:** fast travel back after a load: the write is lost or the saved flag was not read as raised; a "WRONG SAVE LOADED" that stays: the token was not saved (S3). **Proves:** L3, L8 (the travel lock kept), S3.
- **A6. A lock changed during a loading screen.** **Do:** raise a connection warp flag with Cheat Engine; during the loading screen of the warp, set the lock (1050290500) and the travel lock (1050290503) OFF by hand; the mod then warps you back (A3). Repeat once while the Roundtable Hold loads. **See:** after the load and about 3 s, both read ON again (the mod rewrote them) and fast travel is refused at the Roundtable Hold. **Log:** none (a rewrite is silent). **Failure:** a lock stays OFF until the next load. This is the generator's open check 13 as the mod meets it. **Proves:** L3.
- **A7. Readiness reaches the server.** The mod's side is A2's `Ready sent`; the server's side is its acceptance of a take or a handoff for this runner (D0): it refuses a runner who is not ready at the Roundtable Hold with both locks asserted and its token bound (`target_unavailable`, `not_ready`). **Proves:** L6.
- **A8. The travel lock on both maps.** **Do:** at the Roundtable Hold, open the map and pick a grace; then sit at the Table of Lost Grace and pick a grace from its travel menu. Then raise the Chapel warp flag (1050290501) with Cheat Engine, and as soon as you land at the Chapel open the map and pick a grace: the mod sends you back about 3 s after the landing, a tight window (the seed's check 16 covers that map by hand). **See:** each time fast travel is refused with the game's own message. **Log:** none. **Failure:** fast travel works: `[RACE] Game flag not written` with `flag_id=1050290503` means the write failed; without it, the seed does not gate that map. **Proves:** L8.

### B. The key and the overlay, waiting side (race 1, you wait)

- **B1. Holder online.** **See:** top centre "WAITING FOR THE BATON", "bot1 is in <zone>", "Zone 9 of 12. You: 0/<cap> zones." (the values of the race); the BATON line of the panel names bot1 with your counter and no key hint (no take is offered). Hold F8 for 2 s: nothing is sent. **Failure:** a take request (`[RELAY] Take requested`) while the holder is online. **Proves:** the overlay strings and the key gate.
- **B2. Holder offline.** **Do:** `offline bot1`, watch for 20 s, then `online bot1`, then `offline bot1` again and leave it. **See:** an ember "BOT1 IS OFFLINE", "The baton can be taken in 42 s" counting down second by second, "It goes back to bot1 if they return before then."; the BATON line reads "bot1". After `online bot1` the banner returns to "WAITING FOR THE BATON". **Failure:** a countdown that stalls or runs ahead of the server's (the baton can be taken only at 0). **Proves:** the countdown, the reconnection.
- **B3. The free baton.** **Do:** wait for the 60 s of the second `offline`. **See:** a verdigris "THE BATON IS FREE", "bot1 has been offline for over a minute", "Hold F8 to take the baton at the entrance of <zone>." with a hold bar (or "Not ready yet: wait at the Roundtable Hold." within about 3 s of a load; "No fresh save: you cannot take the baton." and "You are at your cap." appear when those hold); the BATON line reads "free" with "F8 take". The baton stays free while bot1 stays offline. Do not take it here: the take writes the game and comes in D0. **Failure:** a prompt before 60 s, none after. **Proves:** the free-baton texts, `baton_free_in_s`.
- **B4. Sizes.** **Do:** look at B1 to B3 at 1920x1080 first, then 1280x720 and 3440x1440, against the approved mockup. **See:** the block keeps its place, follows the screen's height on the ultrawide, nothing overlaps the compass or the panel, no empty band above a banner, "Not ready yet: wait at the Roundtable Hold." fits its line. **Proves:** the layout numbers.
- **B5. The key rebound.** **Do:** set `relay = "g"` under `[keybindings]` in `speedfog_racing.toml` (next to the DLL), relaunch the game and load; then `relay = "none"`, relaunch; then put `relay = "f8"` back, relaunch. **See:** the hints carry the new label; with `none` every hint reads "No baton key bound: set `relay` in the config", the waiting banner shows no hold bar, nothing can be taken or passed. After each relaunch both locks are raised again after about 3 s (`[RELAY] Lock raised`, `[RELAY] Travel lock raised`). **Proves:** the key table and config.
- **B6. Focus loss.** **Do:** with the take offered (B3), hold F8, alt-tab away, release, come back. **See:** the hold did not confirm and no request was sent (`[RELAY] Take requested` absent); the first press after returning may be absorbed (record whether it is). **Failure:** a take request on return. **Proves:** the focus rule of "The baton key".

Reset race 1 from the web (a reset lowers the locks of every mod still connected), then create race 2.

### C. Capture (race 2, character G, you hold, read-only)

You are the first holder, with character G (see "Before you start"): the mod reads the lit graces at each zone entry and writes nothing into the game but its locks (lowered for a holder here) and the token your first report draws (A2b). Race 2 ends with C9: the state files of section D start from it.

- **C1. The locks for a holder.** **See:** after the start you stay at the Chapel (the first holder is not sent to the Roundtable Hold), the gates react and fast travel works (both locks are lowered); `[RELAY] Lock lowered` and `[RELAY] Travel lock lowered` show once, with the `reason` of the moment they were first written (`race not running` in setup, `holder` once the race runs). **Do:** raise the lock and the travel lock by hand (Cheat Engine), then quit to the title and load. **See:** about 3 s after the load the prompt of the gates is back and fast travel works (a stale lock on a holder is lowered at the first settled frame after a load). **Proves:** L3 (the holder side).
- **C2. The first checkpoint.** **Do:** take a fog gate (enter a zone). **See:** no hitch. **Log:** `[RELAY] Worker job started`, then (the first relay job of the process only) `[RELAY] Grace flags read` with a nonzero `flags`, `[RELAY] Character read`, `[RELAY] State captured`. **Failure:** `[RELAY] Param table unreadable, no grace transfers this session` (the table is not found under its name: `R1`); `[RELAY] Character not read` names the `failure` (warn level): note it, it settles which read is wrong. **Proves:** R1.
- **C3. What was read, against the character.** **See in the `[RELAY] Character read` line:** `graces` is the number of graces lit on the map, `graces_unreadable` 0, `graces_scanned` the `flags` of `Grace flags read`, `elapsed_ms` a few ms, far under the 1 s read window (`READ_WINDOW_MAX`). Light one more grace (rest at it, or by hand) and take another gate: `graces` is one more. The server keeps the state: `select character_state from relay_teams` on the local database shows your team's `grace_flags`. **Failure:** a count off: a lit grace whose flag does not read set (`R1`). **Proves:** R1.
- **C6. The first capture of a process reads the table itself.** **Do:** relaunch the game, reload, take a gate. **See:** `[RELAY] Grace flags read` comes before `[RELAY] Character read` (a relay race has no race items to prewarm the params), and the capture ends well within a release's 12 s. **Proves:** R1.
- **C7. The mod reads only.** **See:** the lit graces, the inventory and the equipment are the same before and after the checkpoint. **Failure:** anything changed: stop and send the log. **Proves:** the capture writes nothing.
- **C8. The holder's menu, read-only.** **Do:** with `RUST_LOG=debug` set, press F8 and tap, without holding. **See:** "PASS THE BATON", one row per teammate (bot1 with its counter, "2/5 zones"-style), the highlight on the first teammate who can receive, a tap moves it (wrapping), the menu closes by itself 5 s after the last press while the key is up; a hold released before 1 s sends nothing. `offline bot1`: its row is dim "not in game" and is never highlighted; `online bot1`. **Log (debug level only, so `RUST_LOG=debug`):** `[RELAY] Baton menu opened`, `[RELAY] Baton menu closed by itself`. **Proves:** the menu's timers and rows.
- **C9. The state files.** **Do:** write the files of the table below in `server/`. A grace flag is the `eventflag_id` of a `BonfireWarpParam` row (Smithbox), nonzero; the ones G lit are in the server's stored state (C3). **See:** each file loads in the bot tool without a warning. Then reset race 2, create race 3 (`Starts: bot1`) and start it with a fresh New Game character R.

| File                | Contains                                                                                                     | Used in        | `[RELAY] Apply planned` must show |
| ------------------- | ------------------------------------------------------------------------------------------------------------ | -------------- | --------------------------------- |
| none (no `--state`) | the bot's default state: no grace                                                                            | D1, D2, E3, E4 | `graces` 0, `not_grace` 0         |
| `s6.json`           | 3 grace flags of graces R has not lit (zones R has not visited), and the flag `999999999`, which is no grace | D7             | `graces` 3, `not_grace` 1         |
| `s7.json`           | the grace flag of every `BonfireWarpParam` row, 1000 at most                                                 | D8             | `graces` the file's count         |
| `s8.json`           | 20 grace flags                                                                                               | F1, F2, F4     | `graces` 20                       |

**Proves:** the files of section D hold real grace flags of the game.

### D. A take, smallest first (race 3, character R)

Race 3 starts with `Starts: bot1` and a fresh character R. Each step from D1 is a take of a chosen state: your game waits at the Roundtable Hold, the bot holds, and the state is the bot's `--state` file (none: its default, no grace). To get the baton back to the bot, hand it over with F8 (hold 1 s on bot1), as D0b does the first time; then restart the bot tool with the next file (`quit`, then the same command with another `--state`) and run `pass bot1 <you>`. The common reading of a take: **Log:** `[RELAY] Take received` (with `with_state`, `igt_ms`, `warp_flag`), `[RELAY] Progress of the waiting save dropped`, `[RELAY] Take started` (`start`, `igt_ms`, `graces`, `bosses`), `[RELAY] IGT written`, `[RELAY] Worker job started`, `[RELAY] Apply planned`, `[RELAY] State applied`, `[RELAY] Take applied`, `[RELAY] Lock lowered` and `[RELAY] Travel lock lowered` (`reason="take"`), `[RELAY] Warp to the zone` (`flag`: the gate's warp flag, or the Chapel's, 1050290501, before the team's first gate) and `[RELAY] Take acknowledged` (`elapsed_ms`); **(server):** `Relay take acknowledged`. **See:** the banner "YOU HAVE THE BATON" with "You start at the entrance of <zone>" or "You start from the Chapel", then a loading screen into the zone, or to the Chapel grace. Your build never changes at a take: before D0, note R's level, attributes and runes (the status screen), its equipment and a few items of its inventory, and check after every take of this section that they are the same (a take writes nothing of the character). Note `elapsed_ms` of `Take acknowledged` in each step: well under the server's 30 s.

- **D0. The smallest take: the free baton, state null, before the team's first gate.** **Do:** with R waiting at the Roundtable Hold and ready (A2's lines), `offline bot1` before it walks, wait the 60 s, hold F8 for 1 s once "Hold F8 to take the baton" shows. **See:** "Waiting for the server" for an instant, then the banner "YOU HAVE THE BATON" with "You start from the Chapel" in the place the waiting banner was (same title height, no jump, no empty band), both locks lowered, one loading screen that lands you at the Chapel grace, the IGT the team's, your build unchanged. **Log:** `[RELAY] Take requested`, `[RELAY] Take received` with `with_state=false` and `warp_flag=Some(1050290501)`, `[RELAY] Take started` (`graces=0`), `[RELAY] IGT written`, `[RELAY] Take applied`, `[RELAY] Lock lowered` and `[RELAY] Travel lock lowered` (`reason="take"`), `[RELAY] Warp to the zone` with `flag=1050290501`, `[RELAY] Take acknowledged`; **(server):** `Relay baton flipped`, `Relay take acknowledged`. **Failure:** `[RELAY] Request refused` (warn level, with the server's `code` and `message`: `not_ready` means the server never heard `ready=true`, `L6`); no `Take received` after the request and `[RELAY] Request not answered, forgotten` 10 s later; you stay at the Roundtable Hold with `[RELAY] Warp to the zone raised again`, then `[RELAY] Warp to the zone failed` and the status "Warp failed: travel from the map" (the Chapel warp flag did not warp, `T6`); a crash here is the IGT write or the locks. This is the first take, and the smallest there is (no state, no flag). **Proves:** L6, T1, T3, T6, and the null-state take.
- **D0b. The first handoff, from your game.** **Do:** now that you hold the baton, press F8, tap to bot1, hold 1 s. **See:** the menu closes, the banner "BATON PASSED TO BOT1" in gold with "Returning to the Roundtable Hold..." pulsing under it, at the title height of the waiting banner that follows (no jump); both locks are raised at once and, about 5 s later (the gate window), you are warped to the Roundtable Hold (one loading screen); the banner stays until that loading screen starts, then "WAITING FOR THE BATON" shows. **Failure (banner):** "WAITING FOR THE BATON" before the loading screen, or "BATON PASSED" still on screen at the Roundtable Hold after it. **Log:** `[RELAY] Handoff requested`, `[RELAY] Release received`, `[RELAY] Character read`, `[RELAY] State captured` (`handoff_id` set), then after the server's update `[RELAY] Lock raised` and `[RELAY] Travel lock raised` (`reason="waiting"`) and `[RELAY] Warp to the Roundtable`; **(server):** `Relay release asked`, `Relay baton flipped`. **Failure:** you stay unlocked in the zone (the server's update never read `waiting`: the release answer was refused: look for `Dropped relay_state on implausible IGT` or `Relay state not kept, team not playing yet`); the status "Handoff cancelled: character not readable" (the capture did not read in 12 s: `[RELAY] Release not captured in time, dropped`). **Proves:** the giving path end to end, L2, L4 (after a flip).
- **D1. A state with no grace, before the team's first gate.** The bot's default state (no `--state`), bot1 not having walked yet (`warp_flag` the Chapel's). **See:** "You start from the Chapel"; both locks lower and you land at the Chapel grace; the IGT reads the team's, no "WRONG SAVE LOADED", no quit-out penalty; your level, attributes, runes and inventory are R's from before the take. **Log:** `[RELAY] Take received` with `with_state=true`, `[RELAY] IGT written`, `[RELAY] Apply planned` with every count 0, `[RELAY] Take acknowledged`. **Failure:** the IGT not at the team's after 20 s: `[RELAY] IGT does not read the team's, take acknowledged anyway` and the status "Baton taken: time not confirmed" (the write does not take, or is undone: `T1`, `T2`); a crash here is the write itself. **Proves:** T1, T2, T3, T6 with a state in the message.
- **D2. A gate: the warp to the zone.** **Do:** `walk bot1` twice (a gate, then another), hand over again with the default state (the receiver gets the IGT only). **See:** after "You start at the entrance of <zone>", both locks lower and you are warped to that gate's exit: you stand at the entrance of the zone the team last entered; the zone flag is set (the zone shows on the map and the web), a boss arena is entered with its fog closed behind you. **Log:** `[RELAY] Warp to the zone`; none of `[RELAY] Warp to the zone raised again` or `[RELAY] Warp to the zone failed`. **Failure:** the status "Warp failed: travel from the map" (three raises started no load: the warp flag did not warp). **Proves:** T3, T4.
- **D7. Flags: boss and graces.** `s6.json`, after `boss bot1` on a zone (so the team's `defeat_flags` carries a boss). **Precondition:** before the take, note R's own lit graces and kills, and that R has not lit the three graces of the file. **See:** the three graces are lit for you and fast travel goes to them, the boss the team killed is dead in its arena with its fog open, and every grace and kill you had is still there (one missing is a neighbour bit lost by a flag raise); the flag that is no grace is ignored. Watch whether raising a defeat flag at the Roundtable Hold starts an event (a banner, a reward, a warp): report it, as a loading screen it started would cut the apply and start the take again. **Log:** `[RELAY] Apply planned` with `graces` 3, `defeats` counted, `not_grace` 1 and `not_graces` naming the flag; `[RELAY] State applied` with `written` showing `defeats_failed: 0` and `graces_failed: 0`. **Proves:** W1, W2, W3.
- **D8. A large state, with Tracy (slow apply off).** `s7.json` (every grace of the game), with the profiling build and Tracy connected. **See:** every grace lit on the map, the game does not stutter. **Log:** `[RELAY] Apply planned` (`graces` the file's count), `[RELAY] State applied` (not `in part` with `Deadline`), `[RELAY] Take acknowledged` `elapsed_ms`. **Tracy:** `relay_apply_frame` stays under the 1.5 ms budget (`APPLY_FRAME_BUDGET`, plus one write), `relay.raise_flag` gives each raise's cost (about 13 µs measured), nothing of `relay.capture`, `relay.grace_flags` or `relay.apply_plan` on the frame thread; a `relay_apply_frame` or a `relay.raise_flag` well above those figures is a finding. **Timing:** `Take received` to `Take acknowledged` under 15 s passes; above 20 s is a finding to report before release (the server frees the baton at 30 s). **Failure:** `relay_apply_frame` over several ms a frame, `[RELAY] State applied in part` with `Deadline`. **Proves:** W1 and W3 at scale, and the take's duration with the largest state.

### K. The token (race 3, you wait)

After D8 you hold the baton: hand it back to bot1 (F8, hold 1 s on bot1), as D0b does, and wait at the Roundtable Hold. A2b and A5 showed the token written, confirmed and kept across a reload; this section shows what it holds back.

- **K1. The token across a quit-out and a relaunch, after takes.** **Do:** quit to the title and load R; then close the game, relaunch, load. **See:** no "WRONG SAVE LOADED", and you are ready again; watch the first seconds after each load. **Log:** no `[RELAY] Token mismatch, wrong save`, no `[RELAY] Token written`; `[RELAY] Ready sent` with `ready=true`. A "WRONG SAVE LOADED" for about 2.5 s after the load that lifts by itself (`[RELAY] Token mismatch, wrong save`, then `[RELAY] Token matches again, resuming`) says the first read after a load does not hold the loaded save's values: record it against S5, it is no failure of this step. **Failure:** a "WRONG SAVE LOADED" that stays: the token was not saved (S3). **Proves:** S3, S5.
- **K2. A New Game in the middle of the race.** **Do:** quit to the title, start a New Game on another save slot, on the same seed, and load into the world. Then run `pass bot1 <you>` on the bot console. **See:** "WRONG SAVE LOADED" and "Reload your race save" within a moment of the load, for as long as that character is loaded; the mod writes nothing into it (no lock: the Chapel's gate reacts and fast travel works; no warp to the Roundtable Hold), sends no progress (the web shows nothing of it), and is never ready, so the pass is refused (bot console: `refused: target_unavailable: ...`). **Log:** `[RELAY] Token mismatch, wrong save` (warn level, `read=0`, `matches=false`); the `[RELAY] Ready sent` with `ready=false` of your quit-out, and no `ready=true` while that character is loaded; no `[RELAY] Token written` (you are bound: a save without the token is not yours, and is never written into). **Failure:** `[RELAY] Token written` (the token went into another character: the binding is broken), `ready=true`, a lock written, a status update reaching the server. **Proves:** S4 (`read=0`), S6.
- **K3. The race character loaded again plays on.** **Do:** quit to the title and load R. **See:** the banner goes, both locks come back (fast travel refused at the Roundtable Hold), and you are ready again. **Log:** `[RELAY] Token matches again, resuming`, `[RELAY] Ready sent` with `ready=true`. **Failure:** the banner stays on R: the read does not find the token on the race save (S3). **Proves:** S6 (the lift).

Two limits are known and are recorded rather than tested ("The save token"): after a race reset every member needs a new character (a character kept from before the reset carries the previous token, which reads as wrong once the new start draws another); and a game that ends (a crash, a kill) between the token's confirmation and the game's next save leaves the member bound on a save without the token, which only a race reset frees.

### E. The full handoff, the cap and the takeovers (race 3, race 5, then race 4)

- **E1. A handoff under stress (race 3).** **Do:** each time press F8 and hold on bot1, then note where you end up. Pass the baton: in the middle of a boss fight; at a gate prompt; during the one second of a fog gate; while sitting at a grace; with the inventory or the map open; just before dying (confirm, then die at once: a capture reads only the map and the grace flags, so the state is read while you die, or, once the death's loading screen has begun, again after the respawn; the flip then finds you dead or respawning). **See:** you always reach the Roundtable Hold, locked, within a few seconds of the server's flip: both locks are raised and the warp to the Roundtable Hold follows after the 5 s gate window (a loading exit since closes the window at once); a warp through the gate that you were already in the middle of is the generator's documented limit (the lock raised during that second comes too late), after which the mod sends you to the Roundtable Hold. A dead runner waits for the respawn first. **Log:** `[RELAY] Release received`, `[RELAY] State captured`, `[RELAY] Lock raised` and `[RELAY] Travel lock raised` (`reason="waiting"`), `[RELAY] Warp to the Roundtable`; `[RELAY] Release not captured in time, dropped` plus the status "Handoff cancelled: character not readable" if the capture never read within 12 s (then the server cancels at 15 s and you stay the holder, unlocked: nothing stranded). **Failure:** you stay locked away from the Roundtable Hold with no warp, or unlocked after the flip: a lock decision that did not follow the server's word. One case is expected, not a failure: a giver who hands off in the middle of a fight and dies twice, each time between a warp's raise and its load, respawns twice away from the Roundtable Hold, which counts two landings (`WARP_LANDINGS_MAX`): the return is given up for this process and the giver stays locked where it respawned until a relaunch of the game, which resets the count and sends it there. The log tells it apart from a wrong map id: two `[RELAY] Warp to the Roundtable landed elsewhere` lines whose `map` is where you respawned (A2 proved the Roundtable Hold's), each after a `[RELAY] Warp to the Roundtable` and your death, then the status "Warp to the Roundtable Hold failed". **Proves:** L2, L4, L5.
- **E2. A capture across the start of a load.** **Do:** confirm a handoff and start a fast travel at once, several times. This is a tight window: the capture lasts a few ms from the confirmation, so only a fast travel started within that time meets it; repeat 10 times or more and record how many reached it (none reached is a result, the unit tests cover the machine). **See:** every capture either reads in full or fails safe: **Log:** `[RELAY] Character read` with the counts of C3, or `[RELAY] Character not read` with `LoadDuringCapture` or `NotLoaded` (warn level), nothing sent, and the release captured again after the load (or cancelled when the load outlasts its 12 s). A state never goes out partly read. **Failure:** a state with fewer graces than you lit reaching the server (`select character_state from relay_teams`). **Proves:** R2, R3.
- **E3. A take whose zone entry is a sending gate or a cutscene transition (race 3).** **Do:** `walk bot1` until it enters a zone through a sending gate or a cutscene transition (the build output of the seed names them), then `pass bot1 <you>` with the default state (nothing to raise: this step is about the warp). **See:** the plain warp of the connection lands at the gate's exit with no cutscene and none of the story flags the vanilla event sets: note what the zone looks like and whether the way on works (the generator documents it as not checked in game). **Log:** `[RELAY] Warp to the zone`. **Proves:** T4 for those entrances.
- **E4. A take while sitting at the Table of Lost Grace, with a menu open.** **Do:** sit at the Table of Lost Grace (or open the map) while bot1 passes you the baton with the default state. **See:** note when the take starts and where the warp lands: the generator documents that a warp flag has no guard on the player's state (its checks 15 and 18); the take starts only on a loaded, settled frame with HP above 0. **Log:** `[RELAY] Take started`, `[RELAY] Warp to the zone`. **Proves:** T3, T4 with a menu or a grace sitting in the way.
- **E5. The takeover of a free baton, with the state the server holds (race 3).** **Do:** hand the baton to bot1 (E1's way), then `offline bot1`, wait for "THE BATON IS FREE" and hold F8. **See:** the server holds your own last state (your game answered the release, not the bot), so your own lit graces come back: `[RELAY] Apply planned` shows `graces` the count of your last capture; the IGT is the team's and you restart the team's zone; if the server held no state, `with_state=false`. The bot's `--state` file is received only through a bot-to-you handoff (section D). **Log:** `[RELAY] Take received` with `with_state=true`; **(server):** `Relay baton flipped`. A take asked before the 60 s are over is refused by the server (`Relay request refused: participant=... code=holder_online` in its log); the mod does not offer it earlier. **Proves:** the takeover with a stored state.
- **E6. The organizer removes the holder (race 3).** **Do:** while bot1 holds and you wait, remove bot1 from the race (the cross of its card in the web, or `DELETE /api/races/{race_id}/participants/{participant_id}` with the race running). **See:** at once "THE BATON IS FREE" with "The holder left the race" and the hold prompt (no 60 s wait); hold F8 to take it. **Log:** `Relay member out` (server), `[RELAY] Take received`; the state is the last one the server holds (yours), so `[RELAY] Apply planned` shows `graces` the count of your last capture. **Proves:** the member-out update path of the baton.
- **E7. Your game dies as the holder, then relaunches (race 3).** **Do:** kill the game while you hold, relaunch and load. There is no deadline for the first case: the server keeps you holder until someone takes the baton, which the bot may do only after the 60 s of your absence, so a relaunch of a couple of minutes is fine as long as nobody types `take`. Then again, but after the relaunch has begun let `take bot1` run once 60 s have passed (the bot takes the free baton), and relaunch afterwards. **See:** the role of the server applies: in the first case you are still the holder (gates react once the stale locks are lowered, after about 3 s); in the second you are waiting: locked, sent to the Roundtable Hold. **Log:** `[RELAY] Lock lowered` (`reason="holder"`) or `[RELAY] Lock raised` (`reason="waiting"`), `[RELAY] Warp to the Roundtable`. **Failure:** a stale lock left on a holder, or a waiting runner left free in the world.
- **E8. A refused request.** **Do:** hold F8 on bot1 within the same second as `offline bot1` on the bot console. **See:** the server's message in the status line, you stay unlocked where you are (`[RELAY] Request refused`, warn level, with `code` and `message`; **bot console:** nothing). This is a sub-second window: the menu greys a row as soon as the server's update arrives, so one person rarely hits it; if it is not reached, say so (the refusal display is covered by the unit tests, not by the game). **Proves:** the refusal display.
- **E9. Two players: both ways with real characters (race 5).** This step needs a second human on a second PC, with their own account, fresh save and the same DLL: one person cannot do it. It has a race of its own, race 5 (teams of 2, `Starts: you`): Alpha is you and the second player, who joins it from their account with a fresh save and a character of another starting class than yours; Beta is two bots (`--team Beta=bot2,bot3` alone). **Do:** hand the baton from one to the other and back several times, after lighting graces and killing a boss. **See:** each runner keeps their own build (level, attributes, runes, equipment, inventory) through every take, the receiver finds the giver's lit graces lit and the team's bosses dead, the giver is locked and at the Roundtable Hold, each side's overlay shows the other as the holder, and after a takeover of a free baton (kill the holder's game, wait 60 s, take) the receiver gets the last checkpoint's graces. **Proves:** R1, W1, W2 with a real giver, the checkpoint a takeover replays, and that a build never travels.
- **E10. The cap (race 4, teams of 6).** **Do:** play zones as the holder (the cap is about `ceil(layers / 6) + 1`; `status` of the bot console shows it). Once at the cap, raise the Chapel warp flag (1050290501) with Cheat Engine: you land at the Chapel and stay there (a holder is not sent to the Roundtable Hold). There, the Chapel's fog gate shows no prompt, and fast travel to a grace you lit earlier works, from the map and from the Chapel's grace: the Chapel is one of the two maps the travel lock gates, so this is the proof that it stays down. Fast travel to the Roundtable Hold too if the map offers it (a character that never waited there may not have it), then back to a grace of your zone, and pass the baton from wherever you are. **See:** when your count reaches the cap, once, the banner "QUOTA REACHED: PASS THE BATON" (4 s, no icon); your gates are inert (the lock is raised) but fast travel works (the travel lock stays down); the BATON line counts "6/5 zones"-style past the cap; the menu still passes the baton, and after the flip the travel lock is raised too, with the warp to the Roundtable Hold right away (no 5 s window) if you are away from it; in the menu a teammate at the cap reads "at the cap". A waiting runner at the cap sees "You are at your cap." on a free baton. **Log:** `[RELAY] Lock raised` (`reason="cap"`) with no `[RELAY] Travel lock raised` until the flip, then `[RELAY] Travel lock raised` (`reason="waiting"`) and `[RELAY] Warp to the Roundtable`. **Failure:** the banner twice, gates still reacting, or fast travel refused at the Chapel while you hold the baton at the cap (`[RELAY] Travel lock raised` before the flip: the travel lock follows the lock; without it, the seed's gate). **Proves:** the cap path, L9.
- **E11. The menu with five teammates and long names (race 4).** **Do:** give the bots long usernames (a 40 character one, and one in a script the faces lack, created as local users) and open the menu. **See:** every name cut with an ellipsis, never wider than the box or off screen, the counter never cut; the highlight follows a tap and wraps; an unavailable row (offline, out, at the cap, no fresh save) is dim and never highlighted; with nobody available the note shows; the hold bar fills in 1 s and the pass goes out at full; the menu shows over a transient banner and yields to the countdown. **Proves:** the menu's layout. A team of six is the server's maximum.
- **E12. A capped holder who fights the final boss is still accepted (race 4, bots).** **Do:** make bot2 the holder (`pass`), `walk bot2` until it is refused at its cap, then `finish bot2`. **See:** the server still finishes the team: the cap never blocks the final boss ("Cap"); the bot console and the web show the team finished. **Log (server):** `Relay team finished`. **Failure:** the team stays unfinished. **Proves:** the Cap rule for the final boss, against a real server.
- **E13. The transient banners replace the waiting banner in its place.** **Do:** in D0 and E10 look at "YOU HAVE THE BATON" and "QUOTA REACHED: PASS THE BATON" against the waiting banner that comes before or after. **See:** each banner shows for 4 s with its title at the same height as the waiting banner's, no jump of the title and no empty band above it (a title that jumps is the item banner's old position). "BATON PASSED TO <runner>" is the waiting banner itself (D0b), so it cannot jump. **Proves:** the relay banner layout.

### F. Restarts and interruptions (race 3, slow apply on)

F1, F2 and F4 need an apply that lasts about 10 s: launch the game with `SPEEDFOG_RELAY_SLOW_APPLY=500` ("Before you start"; the log says `[RELAY] Slow apply is on (test aid): one write per interval`) and give `s8.json` of C9 (20 graces, then the defeat flag of D7's boss: 21 writes, about 10 s inside the 15 s deadline; a longer state would end on the deadline). `[RELAY] Apply planned` shows `graces` 20 and `defeats` 1 (more if the team killed another boss since D7) each time. Unset the variable and relaunch afterwards.

- **F1. The game dies during a take.** **Do:** `pass bot1 <you>` with `s8.json` under the slow apply, kill the game 4 s after `[RELAY] Take started`, relaunch (still with the variable) and load. **See:** the take is applied again by the new process and acknowledged once, the 20 graces lit at the end. The new process plans the same writes (`graces` 20), whatever the reloaded save kept of the first apply: a grace raised again is harmless. **Log (server):** `Relay take sent again on reconnect`, then one `Relay take acknowledged`; **(mod, after the relaunch):** `[RELAY] Take received` (the same `handoff_id`), then the usual take lines, once. **Failure:** the baton free after 30 s (`Relay take not acknowledged, baton free`) and never taken back: the take was never sent again or never acknowledged. **Proves:** the replay of a take.
- **F2. The network is cut during the apply.** **Do:** `pass bot1 <you>` with `s8.json` under the slow apply; 3 s after `[RELAY] Take started`, cut the connection to the server for 5 s (disable the adapter, or block the server's port with the firewall). **See:** the take is applied once (the 20 graces lit), `relay_taken` goes after the reconnection. **Log (mod):** `[RELAY] Take received again, in progress` (the server's resend) or `[RELAY] Take received again, acknowledged again` then `[RELAY] Take acknowledged again`; **(server):** one `Relay take acknowledged`. **Proves:** the reconnection during a take.
- **F3. Nothing of the waiting save reaches the team.** **Do:** after F1 or F2, look at the team's history in the web. **See:** no zone, flag or IGT of your waiting save in it. **Log (mod):** `[RELAY] Progress of the waiting save dropped` at each take. **Proves:** the progress hold.
- **F4. A quit-out, or a death, during the apply.** **Do:** `pass bot1 <you>` with `s8.json` under the slow apply; quit to the title (or die, if you find a way at the Roundtable Hold) 3 s after `[RELAY] Apply planned`, well before `[RELAY] State applied`. **See:** nothing raised after the loading screen began, the game and the save intact. After reloading (the character loaded again at the Roundtable Hold after a quit-out; after a death, the respawn at the grace you rested at last, then the mod's return to the Roundtable Hold), the take starts again once the Hold has settled, its apply plans the same 21 writes, and the take is acknowledged once, with the 20 graces lit. **Log:** `[RELAY] State applied in part` with `end=MapChanged` and `left` above 0, `[RELAY] Apply cut by a load, the take starts again at the Roundtable` (`start=1`), after the reload `[RELAY] Take started` with `start=2`, a second `[RELAY] Apply planned`, `[RELAY] State applied`, `[RELAY] Take applied` and `[RELAY] Take acknowledged`. **Failure:** the take acknowledged right after the reload (no second `Take started`) with graces missing: the restart did not happen. **Proves:** the load boundary (W4, and `MapChanged`) and the restart of a take a load cut.
- **F6. A quit-out right after a take.** **Do:** after `[RELAY] Take acknowledged`, quit to the title and load. **See:** the IGT is the team's (not the old save's), no "WRONG SAVE LOADED", no quit-out penalty (`[RACE] Quit-out IGT penalty applied` absent). **Proves:** T5.
- **F7. A press cut short by a focus loss, in the menu.** **Do:** open the menu, hold F8, alt-tab away, release, come back. **See:** no confirmation, the highlight did not move, the 5 s auto-close was not restarted by the loss; a tap after returning moves the highlight. **Proves:** the focus rule for the menu.
- **F8. The locks across many loads (waiting).** **Do:** while waiting, quit to the title and load several times (or die, if you find a way: the respawn is away from the Roundtable Hold and the mod sends you back, counting no landing). **See:** after each load both flags read ON in Cheat Engine and fast travel is refused at the Roundtable Hold. **Proves:** L3, L8.
- **F9. Readiness after a reconnection.** **Do:** cut the connection for a few seconds while waiting at the Roundtable Hold, then look at the log. **See:** after the reconnection `[RELAY] Ready sent` with `ready=true` again (readiness does not survive the socket), and `pass bot1 <you>` (bot console, with the command typed and Enter pressed right after) is accepted. Then the narrow part: type `pass bot1 <you>` without Enter, raise a connection warp flag (A3), and press Enter as soon as its loading screen starts, before the mod has brought you back and settled: `Ready sent` with `ready=false` has gone out, and the pass is refused `target_unavailable` (bot console: `refused: target_unavailable: ...`). **Proves:** L6.

### G. The end of a relay (race 4)

After each case, reset the race from the web (a reset lowers the locks of every connected mod and puts everyone back in setup), start a New Game and start again. In every case: **See** that the gates react, fast travel works, no relay banner or prompt shows, and no `[RELAY] Warp to the Roundtable` follows. **Log:** `[RELAY] Lock lowered` and `[RELAY] Travel lock lowered`, with the reason in the case.

- **G1. The team finishes.** `finish bot1` while bot1 holds and you wait. `reason="relay over"`. **Server:** `Relay team finished`.
- **G2. You abandon, the team plays on** (the web's Abandon while waiting). `reason="relay over"`; no waiting banner (you are out); the abandoned notice shows.
- **G3. The organizer removes you while you wait**: as G2 through `DELETE /api/races/{race_id}/participants/{participant_id}` or the card's cross.
- **G4. A team out.** Disqualify a teammate (the organizer's route): your team is out and your locks lower. `reason="relay over"`.
- **G5. The race finishes.** Force-finish it (the organizer or an admin): `reason="relay over"` (or `"race not running"` when the race's own message comes first).
- **G6. A reset.** Reset while you wait: `reason="race not running"` or `"relay not started"`.
- **G7. A relaunch after the race ended.** Close the game, launch it with the pack of the finished race, load: the mod reads a team that is over and lowers both locks at the first settled frame (gates react, fast travel works). A save left locked by a race whose pack you no longer launch stays locked: a mod on a non-relay race leaves the locks alone. Record whether such a save's gates are inert and its Roundtable Hold refuses fast travel; the recovery is in "If something goes wrong". **Failure:** gates still inert after the finished race's pack: the locks were not lowered. **Proves:** the locks' lowering cases.

### H. Performance (the profiling build, Tracy connected, slow apply off)

The steps of C and D say when to look. Overall, with Tracy ("docs/MOD_PROFILING.md"):

- **H1.** Waiting banner shown, then the menu open, then the BATON line: `relay_wait`, `relay_menu`, `relay_line` and `maintain_relay` stay in the microseconds, once per frame. A name that changes shows one spike, not a steady cost (the title's glyph offsets are cached with its cut).
- **H2.** A capture and an apply: `relay.capture`, `relay.grace_scan`, `relay.grace_flags` (the first relay job of a process) and `relay.apply_plan` appear on the thread `relay-worker` and never on the frame thread; `relay_job_poll` on the frame thread is an `Option` check; the frame time holds during both.
- **H3.** `relay_apply_frame` and its `relay.raise_flag` (D8): the measure for `APPLY_WRITES_PER_FRAME` and `APPLY_FRAME_BUDGET`.
- **H4.** In a race that is not a relay race (a normal race with the same DLL), F8 does nothing and the foreground-window query of the key never appears in the trace.
- **H5.** The token: `relay.read_token` and `relay_token_judge` appear only on the frames a read is due (a load, its settle, an `auth_ok`, a change of the server's token or binding, the frame after a write), never once per frame; `relay.write_token` and `relay_token_write` once per write.

### If something goes wrong

- **A runner stuck locked.** A waiting runner is locked at the Roundtable Hold by design: it is freed when the baton is passed to it, taken, or when the team's relay ends. If the status says "Warp to the Roundtable Hold failed" and the log has two `[RELAY] Warp to the Roundtable landed elsewhere` lines, the mod gave up the return for this process (`WARP_LANDINGS_MAX`): relaunching the game resets the count. If it fails again the Roundtable Hold's map id is wrong (A2): put the logged `map` into `ROUNDTABLE_MAP_ID` and rebuild.
- **"WRONG SAVE LOADED" on the right character.** The token flags of that save do not hold the member's token. Load the character whose first report of this race validated you; if none holds it (the game ended before it saved the token, "The save token"), only a race reset frees the member.
- **The organizer removes the member.** The route `DELETE /api/races/{race_id}/participants/{participant_id}` (race running) puts the member out and the mod lowers its locks on the server's update. Resetting the race lowers every lock too.
- **By hand, if all else fails.** The locks are the event flags `lock_flag` and `travel_lock_flag` of the seed (`graph.json`, `relay`; 1050290500 and 1050290503 on the pools of this project): set them OFF with Cheat Engine (`Event Flags by ID`, re-type the ID after the action). The mod writes them again at the next loading exit if the server still says `waiting`, so end the race (or remove the member) first, or close the game, then lower them with a flag tool before loading.
- **A take that never ends.** The mod gives up its apply at 20 s (`APPLY_ABANDON`, status "Baton taken: graces may be missing") and acknowledges; a take whose applies a load keeps cutting is acknowledged after its third start (`TAKE_STARTS_MAX`). The server frees the baton at 30 s. Another teammate can take it then.
- **Logs to send.** `speedfog_racing.log` (from the first line: it carries the commit), the server's `Relay` lines of the same minutes, the bot console, the `--state` file used, the time of the event, and a screenshot of the overlay or the status screen when the step is about what is shown. For a performance step, the Tracy trace.

### Closing

When the sections are done, update the "Confirmed in game" cells of the facts tables (L, T, S, R, W), turn the matching lines of "Not proven yet" into confirmed or refuted, and record the take's measured duration for the largest state, `APPLY_WRITES_PER_FRAME` and `APPLY_FRAME_BUDGET` in the constants table of "Mod". The crate version, the mod release, the mod's side of the boss loot, the web help page's key line and turning `RELAY_RACES_ENABLED` on in production are the project owner's ("Before enabling relay races").
