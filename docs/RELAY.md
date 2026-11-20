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

`prepare_relay_start` then fixes the teams: a member who is not READY is set ABANDONED (disqualified members keep their status). They stay attached to their team, so nobody is without one, and `team_cap` computes the cap on the members present. Each started team becomes READY and its baton goes to `first_runner_id` when that member is READY, else to its first READY member by `created_at`.

A reset (`reset_race`) calls `reset_relay_race`: every team goes through `reset_relay_team` and every member gets `relay_zones = 0` and `relay_validated = False` (the left-out members return to REGISTERED with the other participants). Names, colors, placeholders and `first_runner_id` survive, so the setup choices are kept. A seed re-roll calls it too; it only ever happens in setup, where the teams are already fresh.

## Baton

## Cap

A runner may play `ceil(total_layers / active_members) + 1` zones (`relay_cap`),
`total_layers` being the seed's. `active_members` counts the team's members whose
status is neither abandoned nor disqualified (`is_active_member`); `team_cap` never
divides by zero (at least one member) and is recomputed when a member leaves.

## Progress and guards

On a relay race the live messages (`race_state`, `leaderboard_update`, `player_update`,
and `auth_ok.participants`) carry one row per team, built by `relay_team_to_info`
from the `RelayTeamRow`s of `leaderboard_entries`; every broadcast of the leaderboard
passes those entries, and a runner's `player_update` goes out as their team's row
(`load_relay_row`, a query of its own: the entity is loaded without the field). The row shape is in `docs/PROTOCOL.md` ("Relay rows"). A loader
feeding these rows must not defer `RelayTeam.zone_history`.

## Lifecycle

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

## Web

## Bot

## In-game checklist
