# Race Items

A community race option (`Race.race_items`) that gives a runner a Mario Kart style item for each boss kill. The item hurts other runners, and the rank decides which items a runner can draw: mild or defensive ones for the leader, punitive ones for the runners at the back.

This document is the operational reference for the server side: rules, lifecycle, inventory reconciliation and persistence. The wire messages are in `PROTOCOL.md`; how the mod reports use flags and its inventory is in `EVENT_FLAG_TRACKING.md`.

---

## Rules

- On for community races only: never in Daily Seeds, speedrun runs (Set Seed, Random Seed), solo training sessions or event races (the admin attach of a race with items to an event slot is a 422).
- A seed supports items when `graph_json["plugins"]["race_items"]["enabled"]` is true and `graph_json["race_items"]` (the catalog) is a non-empty dict; the pool scan stores the answer in `Seed.race_items`. An items race only draws seeds that support them.
- Switching the option on in SETUP over a seed without the plugin redraws the seed (`apply_seed_reroll` with `count_as_reroll=False`: the option did it, not a player, so it is no reroll for the boards); with no seed to draw it is a 400 and the option stays off.
- Any change of the option (on or off, with or without a redraw) closes every connected mod of the race with code 1000, as a race reset does: the catalog and the protocol gate below only apply at auth, so each mod reconnects and authenticates again, gets the catalog that matches, and an older mod meets the gate. Spectators stay connected.
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

The draw is weighted inside the tier's pool (`race_items_weights`, base key to weight, missing is 1, 0 excludes the item; a tier whose weights are all 0 draws uniformly). A draw of `rune_pouch` becomes the variant matching progress: `current_layer / total_layers` below 1/3 gives `rune_pouch_1`, below 2/3 `rune_pouch_2`, else `rune_pouch_3`. A drawn key absent from the seed's catalog grants nothing (logged).

### Damage curve

For banana and red shell, with `h` the target's current HP as a percentage of max HP and `B` the base damage: `h >= floor + B` deals `B`; `tail + floor <= h < floor + B` deals `h - floor` (lands at the floor); below that it deals `tail`; at least 1 HP always remains. `floor` is `race_items_damage_floor_pct` (20) and `tail` is `race_items_damage_tail_pct` (5). The mod computes the damage when it applies the effect, since only it knows the current HP; the parameters travel with the effect.

## Lifecycle

1. **Boss kill.** The boss kill hook (`BaseModHandler._on_boss_killed`) fires once per new kill, after the commit and the broadcast, outside any DB session. It never fires for the final boss, a replay, a re-report, a kill at IGT 0 or less, or a kill whose node has no visit.
2. **Draw.** `grant_item` (`server/speedfog_racing/websocket/race/items.py`) opens its own session and loads the field. It grants nothing when items are off, the runner is not playing, or the runner holds an item. Otherwise it picks the tier from the runner's rank, draws the key, bumps `Participant.item_grant_count`, stores the held item as unconfirmed, logs a `grant` event and commits.
3. **Grant.** The server sends `item_grant {grant_id, item, banner}` to the runner's own mod. The grant id counts up per participant and never repeats.
4. **Confirm.** The mod spawns the goods and answers `item_received {grant_id}`; the server sets `confirmed` when the id matches the held grant, and ignores anything else.
5. **Reconnect.** An unconfirmed grant is re-sent right after `auth_ok` at every (re)auth, and after an inventory report that lacks it (see below), until the mod confirms it. The mod ignores a grant id it already has.
6. **Use.** Using the goods makes the plugin's EMEVD set the item's use flag, which the mod reports at once through `event_flag`. The handler matches use flags (the `use_flag` of each catalog entry, `use_flag_map`, cached per graph) after the usual gates (race running, no countdown, runner playing, initialized history, plausible IGT) and before the `event_map` lookup, and never adds a `zone_history` entry. After the session, the `_on_item_used` hook resolves the use; it does nothing when the race has items off, and outside races (training) it is a no-op. The flag is acked once the hook returns, so a use lost before its resolution committed (a server restart) is replayed by the mod.
7. **Resolve.** `resolve_item_use` (same module) acts only when the runner holds exactly the used item, otherwise it logs the use and ignores it. That covers a stray copy, and the replay of a resolved use whose ACK was lost, since the resolution cleared the held item; only a new grant of the same item between a use and its replay would let the replay spend it. It clears the held item and resolves the targets among the playing runners in `sort_leaderboard` order. For each target:
   - a held Shield blocks the item: the Shield is spent (even when its holder is offline) and its holder gets `item_remove` for `shield` with a banner;
   - otherwise a target whose mod is connected gets `item_effect` (effect, banner, reminder);
   - otherwise the target is offline and the effect is dropped, a miss for the sender.

   A target counts as hit when its mod is connected at resolution, before the send: if that send then fails (the socket died meanwhile), the effect is lost but the sender's result still reads `Hit {name}` and the log says `hit`.

   A self item (Mushroom, Rune Pouch) applies through the game's own use: no target, no `item_effect`. An item with no valid target is still consumed. One `use` event is logged with every target's outcome (`hit`, `blocked` or `offline`).

8. **Result.** The sender gets `item_result` (banner, plus the reminder for a self item). The handler sends the removals, the effects, then the result.

Grants, confirmations and uses run under `RaceRoom.items_lock`, so concurrent connections cannot grant, confirm or spend over each other: two items aimed at one Shield holder spend the Shield once. A grant after a kill and a use also send their messages under the lock, so a later item message to a runner cannot overtake them.

### Inventory reconciliation

The mod sends `item_inventory {items}` (the race items present in the game) once per game load, after that load's first flag poll and before any pending spawn, and once per reconnect. The server treats it as the truth about the goods, under the same lock; keys absent from the seed's catalog are ignored:

| Held item                  | Report  | Outcome                                                             |
| -------------------------- | ------- | ------------------------------------------------------------------- |
| unconfirmed                | present | confirmed                                                           |
| confirmed                  | absent  | cleared and logged `lost`, so the runner can draw again             |
| unconfirmed                | absent  | kept, its goods may not be spawned yet: its `item_grant` is re-sent |
| any reported item not held | present | `item_remove` without banner sent, logged `take_back`               |

### Result and block banners

The banner title is the catalog `name`. The sender's result line:

| Outcome              | Line                                                                                            |
| -------------------- | ----------------------------------------------------------------------------------------------- |
| hits                 | `Hit {name}`, or `Hit {n} runners`; with Shield blocks too, `, {k} blocked` is appended         |
| Shield blocks only   | `Blocked by {name}'s shield`, or `Blocked by {k} shields`                                       |
| no target            | `Missed: nobody ahead` (Red Shell), `Missed: nobody behind` (Banana), `Missed: no other runner` |
| targets, all offline | `Missed`                                                                                        |
| self item            | `Infinite stamina for {s} s` (Mushroom, with its reminder), `Runes added` (Rune Pouch)          |

The result detail is `{pct}% HP` for a damage item, `{s} s` for a timed one, else empty. A target's banner reads `from {sender}` under the item's target line. A Shield holder whose Shield blocked sees title `Shield`, line `Blocked {item name}`, detail `from {sender}`.

## Persistence

- `Participant.held_item`: `{"grant_id": int, "item": str, "confirmed": bool}` or null. The column is JSON: reassign a new dict, never mutate in place.
- `Participant.item_grant_count`: grants handed out so far; a reset keeps it, so ids never repeat.
- `race_item_events`: the item log (`race_id`, `participant_id`, `kind`, `item`, `igt_ms`, `targets`, `created_at`); `kind` is `grant`, `use`, `lost` or `take_back`. Kept for audits and later web use.

## Server settings

`race_items_weights`, `race_items_banana_pct`, `race_items_red_shell_pct`, `race_items_damage_floor_pct`, `race_items_damage_tail_pct` in `config.py`, overridable from `.env`. They travel with the effects, so tuning needs neither a mod release nor new seeds. The four percentages are clamped to 0..100 when they are sent (the mod reads each as a byte), and the banners quote the clamped value.

## Exclusions

Items races are kept out of the speedrun boards (an unranked reason in `race_unranked_code` and `counts_on_boards_clause`), the community stats and traits (`counts_for_community_stats`) and the generator calibration queries of `tools/extract_zone_times.py`. Race rewards and highlights still apply.
