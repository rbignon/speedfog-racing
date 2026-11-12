# Race Items

A community race option (`Race.race_items`) that gives a runner a Mario Kart style item for each boss kill. The item hurts other runners, and the rank decides which items a runner can draw: mild or defensive ones for the leader, punitive ones for the runners at the back.

This document is the operational reference for the server side as built so far. Sections for the item use, resolution and removal (and for the mod) are added as those parts land.

---

## Rules

- On for community races only: never in Daily Seeds, speedrun runs (Set Seed, Random Seed), solo training sessions or event races.
- A seed supports items when `graph_json["plugins"]["race_items"]["enabled"]` is true and `graph_json["race_items"]` (the catalog) is a non-empty dict. An items race only draws seeds that support them.
- A runner holds at most one item. A boss kill made while holding one grants nothing, then or later.
- Only playing runners are ever targets; finished, abandoned and disqualified runners are skipped.
- An items race needs a mod speaking protocol 1.12 or later (`RACE_ITEMS_MIN_PROTOCOL`); older mods are refused at auth.
- Items races stay out of the speedrun boards, the community stats and the generator calibration, since items distort clear times and deaths.
- Items and deathless can be combined; nothing validates the choice.

## Tiers

Among the playing runners, in `sort_leaderboard` order (index `i` of `n`):

| Tier   | Runners                                |
| ------ | -------------------------------------- |
| front  | `n <= 2`: index 0; otherwise `3*i < n` |
| middle | `3*i < 2*n` (only when `n > 2`)        |
| back   | the rest (with `n <= 2`: index 1)      |

## Items

Catalog keys come from the seed (`graph.json` `race_items`: `name`, `icon`, `goods_id`, `use_flag`, `remove_flag`, `effect_speffect`, `duration_ms`). The rules (tier, target, banner wording) live in `ITEM_RULES` in `server/speedfog_racing/services/race_items.py`.

| Item                            | Tier   | Target                               | Effect                                   |
| ------------------------------- | ------ | ------------------------------------ | ---------------------------------------- |
| `shield`                        | front  | passive                              | blocks the next item aimed at the holder |
| `rune_pouch` (`_1`, `_2`, `_3`) | front  | self                                 | grants runes                             |
| `banana`                        | front  | the playing runner just behind       | damage, base `race_items_banana_pct`     |
| `red_shell`                     | middle | the playing runner just ahead        | damage, base `race_items_red_shell_pct`  |
| `mushroom`                      | middle | self                                 | infinite stamina                         |
| `hammer`                        | middle | every other playing runner           | forced fat-roll                          |
| `ink`                           | middle | every other playing runner           | exits hidden (overlay only)              |
| `blue_shell`                    | back   | the best-ranked other playing runner | max HP halved                            |
| `lightning`                     | back   | every other playing runner           | slowed                                   |
| `flask_stopper`                 | back   | every other playing runner           | flasks blocked                           |
| `toxic_blossom`                 | back   | every other playing runner           | poisoned                                 |

The draw is weighted inside the tier's pool (`race_items_weights`, base key to weight, missing is 1, 0 excludes the item). A draw of `rune_pouch` becomes the variant matching progress: `current_layer / total_layers` below 1/3 gives `rune_pouch_1`, below 2/3 `rune_pouch_2`, else `rune_pouch_3`. A drawn key absent from the seed's catalog grants nothing (logged).

### Damage curve

For banana and red shell, with `h` the target's current HP as a percentage of max HP and `B` the base damage: `h >= floor + B` deals `B`; `tail + floor <= h < floor + B` deals `h - floor` (lands at the floor); below that it deals `tail`; at least 1 HP always remains. `floor` is `race_items_damage_floor_pct` (20) and `tail` is `race_items_damage_tail_pct` (5). The mod computes the damage when it applies the effect, since only it knows the current HP; the parameters travel with the effect.

## Lifecycle (as built)

1. **Boss kill.** The boss kill hook (`BaseModHandler._on_boss_killed`) fires once per new kill, after the commit and the broadcast, outside any DB session. It never fires for the final boss, a replay, a re-report, a kill at IGT 0 or less, or a kill whose node has no visit.
2. **Draw.** `grant_item` (`server/speedfog_racing/websocket/race/items.py`) opens its own session and loads the field. It grants nothing when items are off, the runner is not playing, or the runner holds an item. Otherwise it picks the tier from the runner's rank, draws the key, bumps `Participant.item_grant_count`, stores the held item as unconfirmed, logs a `grant` event and commits.
3. **Grant.** The server sends `item_grant {grant_id, item, banner}` to the runner's own mod. The grant id counts up per participant and never repeats.
4. **Confirm.** The mod spawns the goods and answers `item_received {grant_id}`; the server sets `confirmed` when the id matches the held grant, and ignores anything else.
5. **Reconnect.** An unconfirmed grant is re-sent right after `auth_ok` at every (re)auth, until the mod confirms it.

Every read and write of the held items of a race runs under `RaceRoom.items_lock`, so concurrent connections cannot grant or confirm over each other.

## Persistence

- `Participant.held_item`: `{"grant_id": int, "item": str, "confirmed": bool}` or null. The column is JSON: reassign a new dict, never mutate in place.
- `Participant.item_grant_count`: grants handed out so far; a reset keeps it, so ids never repeat.
- `race_item_events`: the item log (`race_id`, `participant_id`, `kind`, `item`, `igt_ms`, `targets`, `created_at`); `kind` is `grant`, `use`, `lost` or `take_back`. Kept for audits and later web use.

## Server settings

`race_items_weights`, `race_items_banana_pct`, `race_items_red_shell_pct`, `race_items_damage_floor_pct`, `race_items_damage_tail_pct` in `config.py`, overridable from `.env`. They travel with the effects, so tuning needs neither a mod release nor new seeds.

## Exclusions

Items races are kept out of the speedrun boards (an unranked reason in `race_unranked_code` and `counts_on_boards_clause`), the community stats and traits (`counts_for_community_stats`) and the generator calibration queries of `tools/extract_zone_times.py`. Race rewards and highlights still apply.
