# Race Items

A community race option (`Race.race_items`) that gives a runner a Mario Kart style item for each boss kill. The item hurts other runners, and the rank decides which items a runner can draw: mild or defensive ones for the leader, punitive ones for the runners at the back.

This document is the operational reference for the server side (rules, lifecycle, inventory reconciliation and persistence) and the mod side (flags, load gating, effects, overlay). The wire messages are in `PROTOCOL.md`; how the mod reports use flags and its inventory is in `EVENT_FLAG_TRACKING.md`.

---

## Rules

- On for community races only: never in Daily Seeds, speedrun runs (Set Seed, Random Seed), solo training sessions or event races (the admin attach of a race with items to an event slot is a 422).
- On `/race/new`, the option is the "Race items" checkbox of the Advanced options (hidden for speedrun and Set Seed races), its label carrying a gold "New" badge styled like the speedrun page's "Beta" one.
- A seed supports items when `graph_json["plugins"]["race_items"]["enabled"]` is true and `graph_json["race_items"]` (the catalog, `{goods, items}` since graph.json 4.12) holds at least one valid item; the pool scan stores the answer in `Seed.race_items`. A seed generated before 4.12 (a flat `{item_key: entry}` catalog, one goods per item) supports none: the migration `24e50b1ae2f9` cleared `Seed.race_items` on those already scanned, so items races no longer draw them. An items race only draws seeds that support them.
- Switching the option on in SETUP over a seed without the plugin redraws the seed (`apply_seed_reroll` with `count_as_reroll=False`: the option did it, not a player, so it is no reroll for the boards); with no seed to draw it is a 400 and the option stays off.
- Any change of the option (on or off, with or without a redraw) closes every connected mod of the race with code 1000, as a race reset does: the catalog and the protocol gate below only apply at auth, so each mod reconnects and authenticates again, gets the catalog that matches, and an older mod meets the gate. Spectators stay connected.
- A runner holds at most one item. A boss kill made while holding one grants nothing, then or later.
- Only playing runners are ever targets; finished, abandoned and disqualified runners are skipped.
- An items race needs a mod speaking protocol 1.13 or later (`RACE_ITEMS_MIN_PROTOCOL`); older mods are refused at auth.
- Items races stay out of the speedrun boards, the community stats and the generator calibration, since items distort clear times and deaths.
- Items and deathless can be combined; nothing validates the choice.

## Item order

Draws and targets rank the playing runners in item order (`item_standings` in `server/speedfog_racing/websocket/race/items.py`, `item_order` in `services/race_items.py`). It starts from the leaderboard order (`sort_leaderboard`: deepest layer, then layer entry IGT), then each runner moves up past every runner directly above it that it leads by `race_items_igt_lead_s` (60 s) or more in IGT at the same point, and stops at the first it does not. The lead is the difference of their `gap_ms` (`leaderboard_gaps` in `websocket/race/manager.py`, the gaps the leaderboard shows: IGT behind the leaderboard leader on the same layer, LiveSplit style). A runner without a gap neither moves nor is passed.

Why: the mod freezes IGT during loading fades, so time lost outside IGT (slow loads, a crash and relaunch) leaves a runner on a shallower layer while it may be ahead in IGT, which ranks the race. A study of 501 finished simultaneous races (2026-11-14, finishers only, the time each lost outside IGT spread over its loads, sampled every minute) found the two orders differ at 29% of the instants, mostly by small leads (25 s at the median), with 1.6% of runner pairs inverted by 60 s or more and 17% of races holding an inversion of 2 min or more at some point. Where they disagree, the IGT order matched the final ranking 64% of the time, and 86% for leads of 60 s or more. The threshold keeps the order the runners see on the board unless the IGT lead is a real one, so a Red Shell rarely hits someone other than the runner listed just above.

## Tiers

Among the playing runners, in item order (index `i` of `n`):

| Tier   | Runners                                |
| ------ | -------------------------------------- |
| front  | `n <= 2`: index 0; otherwise `3*i < n` |
| middle | `3*i < 2*n` (only when `n > 2`)        |
| back   | the rest (with `n <= 2`: index 1)      |

## Items

Catalog keys come from the seed (`graph.json` `race_items`, read by `extract_race_item_catalog` in `server/speedfog_racing/services/race_items.py`): `goods` by goods key (`goods_id`, `use_flag`, `remove_flag`, `icon`, `icon_id`) and `items` by item key (`name`, `icon`, `icon_id`, `goods`, `effect_speffect`, `duration_ms`). Every usable item is held as the one Race Item goods (`race_item`, use flag `1050290101`); the Shield, never used, is held as its own goods (`shield`, no use flag). An item on a goods the catalog lacks is dropped. The rules (target, effect, banner wording) live in `ITEM_RULES` in the same module. Positions (just ahead, just behind, best-ranked) are in item order.

| Item                            | Tiers (default) | Target                         | Effect                                   |
| ------------------------------- | --------------- | ------------------------------ | ---------------------------------------- |
| `shield`                        | middle          | passive                        | blocks the next item aimed at the holder |
| `rune_pouch` (`_1`, `_2`, `_3`) | front           | self                           | grants runes (its effect row)            |
| `banana`                        | front           | the playing runner just behind | damage, base `race_items_banana_pct`     |
| `red_shell`                     | middle, back    | the playing runner just ahead  | damage, base `race_items_red_shell_pct`  |
| `mushroom`                      | front, middle   | self                           | infinite stamina (its effect row)        |
| `hammer`                        | middle          | every other playing runner     | fat roll (load at 97% of max)            |
| `ink`                           | middle          | every other playing runner     | exits hidden (overlay only)              |
| `blue_shell`                    | back            | the best-ranked playing runner | max HP halved                            |
| `lightning`                     | back            | every other playing runner     | slowed                                   |
| `flask_stopper`                 | back            | every other playing runner     | flasks blocked                           |
| `toxic_blossom`                 | back            | every other playing runner     | poisoned                                 |

The draw is weighted inside the tier's pool: `race_items_tier_weights` maps each tier to its item weights (base key to weight), so an item can sit in several tiers; the pool is the tier's items with a weight above 0 that the seed's catalog has. When the pool is empty nothing is granted (logged as `race item draw: nothing to draw`, no `item_grant_count` bump, no event). A draw of `rune_pouch` becomes the variant matching progress: `current_layer / total_layers` below 1/3 gives `rune_pouch_1`, below 2/3 `rune_pouch_2`, else `rune_pouch_3`. A drawn key absent from the seed's catalog grants nothing (logged).

### Damage curve

For banana and red shell, with `h` the target's current HP as a percentage of max HP and `B` the base damage: `h >= floor + B` deals `B`; `tail + floor <= h < floor + B` deals `h - floor` (lands at the floor); below that it deals `tail`; at least 1 HP always remains. `floor` is `race_items_damage_floor_pct` (20) and `tail` is `race_items_damage_tail_pct` (10); the bases are `race_items_red_shell_pct` (40) and `race_items_banana_pct` (15). The mod computes the damage when it applies the effect, since only it knows the current HP; the parameters travel with the effect.

## Lifecycle

1. **Boss kill.** The boss kill hook (`BaseModHandler._on_boss_killed`) fires once per new kill, after the commit and the broadcast, outside any DB session. It never fires for the final boss, a replay, a re-report, a kill at IGT 0 or less, or a kill whose node has no visit.
2. **Draw.** `grant_item` (`server/speedfog_racing/websocket/race/items.py`) opens its own session and loads the field. It grants nothing when items are off, the runner is not playing, or the runner holds an item. Otherwise it picks the tier from the runner's rank in item order, draws the key, bumps `Participant.item_grant_count`, stores the held item as unconfirmed with the kill's IGT, logs a `grant` event and commits.
3. **Grant.** The server sends `item_grant {grant_id, item, banner}` to the runner's own mod. The grant id counts up per participant and never repeats.
4. **Confirm.** The mod writes the item's icon into its goods' row, spawns the goods (the Race Item, or the Shield's own goods) and answers `item_received {grant_id}`; the server sets `confirmed` when the id matches the held grant, and ignores anything else.
5. **Reconnect.** `auth_ok` carries `held_item`, the item held (confirmed or not), so a restarted mod restores the Race Item's icon and the held row. An unconfirmed grant is re-sent right after `auth_ok` at every (re)auth, and after every inventory report until it is confirmed, the report that confirms it included (see below). The mod ignores a grant id it already has.
6. **Use.** Using the Race Item makes the plugin's EMEVD set its use flag, the same for every item, which the mod reports at once through `event_flag`. The handler matches use flags (the `use_flag` of each catalog goods, `use_flag_map`: use flag to goods key, cached per graph) after the usual gates (race running, no countdown, runner playing, initialized history, plausible IGT) and before the `event_map` lookup, and never adds a `zone_history` entry. After the session, the `_on_item_used` hook resolves the use; it does nothing when the race has items off, and outside races (training) it is a no-op. The flag is acked once the hook returns, so a use lost before its resolution committed (a server restart) is replayed by the mod.
7. **Resolve.** `resolve_item_use` (same module) acts only when the runner holds an item of the used goods, whatever item it is: the held item says what the use does. Otherwise it logs the use and ignores it, and a goods without a use flag (the Shield) is never used. That covers a stray copy, and the replay of a resolved use whose ACK was lost, since the resolution cleared the held item. A use older in IGT than the held item's grant (`held_item.igt_ms`, the kill's IGT) is ignored too: made before the kill that granted the item, it can only be the replay of an earlier use, so a replay never spends an item granted since (any item: they share the goods). It clears the held item and resolves the targets among the playing runners in item order. For each target:
   - a held Shield blocks the item: the Shield is spent (even when its holder is offline) and its holder gets `item_remove` for the `shield` goods with a banner;
   - otherwise a target whose mod is connected gets `item_effect` (effect, banner, reminder);
   - otherwise the target is offline and the effect is dropped, a miss for the sender.

   A target counts as hit when its mod is connected at resolution, before the send: if that send then fails (the socket died meanwhile), the effect is lost but the sender's result still reads `Hit {name}` and the log says `hit`.

   The Blue Shell's target is the leader at the time of use, the sender included: drawn at the back and used once leading, it hits its own sender (as in Mario Kart), who then gets both the `item_effect` (banner `from yourself`) and a result reading `Hit yourself`.

   A self item (Mushroom, Rune Pouch) has no target: its effect row (`effect_speffect`: the Mushroom's stamina, the Rune Pouch's runes) goes to the sender's own mod as an `item_effect` without banner or reminder, which its result carries. An item with no valid target is still consumed. One `use` event is logged with every target's outcome (`hit`, `blocked` or `offline`; none for a self item).

8. **Result.** The sender gets `item_result` (banner, plus the reminder for a self item). The handler sends the removals, the effects (a self item's to its sender), then the result.

Grants, confirmations and uses run under `RaceRoom.items_lock`, so concurrent connections cannot grant, confirm or spend over each other: two items aimed at one Shield holder spend the Shield once. A grant after a kill and a use also send their messages under the lock, so a later item message to a runner cannot overtake them.

### Inventory reconciliation

The mod sends `item_inventory {goods}` (the race goods present in the game, by goods key) once per game load, after that load's first flag poll and before any pending spawn, and once per reconnect. The server treats it as the truth about the goods, under the same lock; the held item shows as its goods, and keys absent from the catalog's goods are ignored:

| Held item   | Report                | Outcome                                                                                 |
| ----------- | --------------------- | --------------------------------------------------------------------------------------- |
| unconfirmed | its goods present     | confirmed, and its `item_grant` re-sent once (see below)                                |
| confirmed   | its goods absent      | cleared and logged `lost`, so the runner can draw again                                 |
| unconfirmed | its goods absent      | kept, its goods may not be spawned yet: its `item_grant` is re-sent                     |
| any or none | another goods present | `item_remove {goods}` without banner sent, logged `take_back` (the goods key as `item`) |

Since every usable item shares the Race Item, a Race Item reported while the server holds an unconfirmed usable item confirms it, though the copy may have been granted as another item (a `give` over a held item, a stale copy). The grant re-sent with the confirmation tells the mod which item the copy now holds: the mod skips the spawn (the goods is there), writes the item's icon, shows its row and answers `item_received`, a no-op by then.

### Result and block banners

The banner title is the catalog `name`. The sender's result line:

| Outcome              | Line                                                                                            |
| -------------------- | ----------------------------------------------------------------------------------------------- |
| hits                 | `Hit {name}`, or `Hit {n} runners`; with Shield blocks too, `, {k} blocked` is appended         |
| Shield blocks only   | `Blocked by {name}'s shield`, or `Blocked by {k} shields`                                       |
| no target            | `Missed: nobody ahead` (Red Shell), `Missed: nobody behind` (Banana), `Missed: no other runner` |
| targets, all offline | `Missed`                                                                                        |
| self item            | `Infinite stamina for {s} s` (Mushroom, with its reminder), `Runes added` (Rune Pouch)          |

The result detail is `{pct}% HP` for a damage item, `{s} s` for a timed one, else empty; it stays empty when nothing landed (every target blocked, missed or offline), so it never reads as dealt. A target's banner reads `from {sender}` under the item's target line. A Shield holder whose Shield blocked sees title `Shield`, line `Blocked {item name}`, detail `from {sender}`.

## Persistence

- `Participant.held_item`: `{"grant_id": int, "item": str, "confirmed": bool, "igt_ms": int}` or null, `igt_ms` being the IGT of the grant (the boss kill; the runner's IGT for a `give` of the bot tool), read as 0 when absent (rows written before it). The column is JSON: reassign a new dict, never mutate in place.
- `Participant.item_grant_count`: grants handed out so far; a reset keeps it, so ids never repeat.
- `race_item_events`: the item log (`race_id`, `participant_id`, `kind`, `item`, `igt_ms`, `targets`, `created_at`); `kind` is `grant`, `use`, `lost` or `take_back`, and `item` is the item key (the goods key for a `take_back`). Kept for audits and later web use.

## Server settings

`race_items_tier_weights`, `race_items_banana_pct`, `race_items_red_shell_pct`, `race_items_damage_floor_pct`, `race_items_damage_tail_pct`, `race_items_hammer_load_pct` and `race_items_igt_lead_s` (the item order's lead, see Item order) in `config.py`, overridable from `.env`. They travel with the effects, so tuning needs neither a mod release nor new seeds. The percentages are clamped to 0..100 when they are sent (the mod reads each as a byte; the Hammer's to 0..99, since 100 could round past the max), and the banners quote the clamped value.

## Exclusions

Items races are kept out of the speedrun boards (an unranked reason in `race_unranked_code` and `counts_on_boards_clause`), the community stats and traits (`counts_for_community_stats`) and the generator calibration queries of `tools/extract_zone_times.py`. Race rewards and highlights still apply.

## Mod

The mod acts only while the race has `race_items` on (`RaceInfo.race_items`), the seed carries a `race_item_catalog` and the run is live (race running, runner not finished or abandoned).

### Flags

Each catalog goods has a goods id and event flags in category 1050290 (one page resolve for all of them): the Race Item a use flag (`1050290101`) and a removal flag (`1050290201`), the Shield only a removal flag (`1050290200`).

- **Use flag.** The Race Item's, whatever item it holds. Read on the same scans as the boss flags (10 Hz poll, loading exit, reconnect rescan), each scan. A set use flag is cleared in game at once and sent through `event_flag` with its `message_id`, ACK and replay, like a boss flag. It never joins `triggered_flags` (it fires again on the next use) and is no LiveSplit capture. The game consumed the goods: the mod forgets the item held as it, and its held row goes (a Shield, held as its own goods, stays).
- **Remove flag.** Only ever raised by the mod (`item_remove {goods}`, never on a wrong save); the game's own event clears it and the mod never does. The item held as that goods, and its row, go with it; an item held as the other goods stays. A removal raised during a load can fail silently: the inventory report at the exit of that same load, seconds later, still lists the goods and gets it taken back again (see Inventory reconciliation).

### Load gating

Grants and effects wait until the player is loaded on the race save (no wrong save, no outdated seed pack), then go on the first loaded frame, after its flag scan (use flags sent): each grant's icon write and spawn (answered with `item_received`), then the effects. Once per game load (loading exit) and once per reconnect frame, while connected, the held item's icon write and the `item_inventory` report come first, in this order: flag scan, icon, report, grants, effects; a loading exit while disconnected writes no icon and sends no report, the reconnect frame does both. A spawn that fails is retried at the next load or reconnect. The 15 s of an effect, its banner (none for the runner's own self item, whose `item_result` carries it) and its reminder start when it is applied. Once the run is over (race no longer running, runner finished or out), the grants, failed spawns and effects still waiting are dropped, not kept for a later load; a new start (a race reset run again) drops them too, with the reminder rows and the ink of the voided run.

### Effects

- `speffect`: the SpEffect is applied to the player.
- `equip_load` (the Hammer): the mod first sets the SpEffect row's max equip load rate so the player's current load sits at `load_pct`% of the max (97 by default, a fat roll), then applies it. The current load is the sum of the weights of the equipped weapons, armor and talismans (`ChrAsm.equipment_param_ids` at PlayerGameData + 0x398, read from EquipParamWeapon, EquipParamProtector and EquipParamAccessory through libeldenring's in-memory params, a weapon's row dropping its upgrade level); arrows and bolts are left out, their param weight is not a load weight (10 for plain Arrows); the max is PlayerGameData + 0x98C, the equipment screen's value. The rate is capped at 1, so a runner already that heavy is left alone, and a runner with nothing equipped (load 0) cannot be made heavier: both still see the banner and reminder. A running Hammer points at the same row, so the max read while it runs already includes the rate written last: when the max equals the last base times the last rate, the mod computes from that base (`core::equip_load::base_max`), so a second Hammer follows the current equipment instead of writing 1 and cancelling the first. An unreadable load, or params not indexed yet (`prewarm_params`), keeps the row's rate (the seed's 0.35, or the last one written). The log line `[ITEMS] Equip load rate set` gives `current` and `max`, to compare with the equipment screen.
- `damage`: computed when applied, with `h = 100 * hp / max_hp`: `h >= floor + base` deals `base`% of max HP; `h >= floor + tail` deals down to exactly `floor`%; otherwise `tail`%; at least 1 HP always remains. Max is the effective max HP (halved under a Blue Shell).
- `ink`: overlay only, see below.
- an unknown kind is ignored with a warning.

### Overlay

All sizes derive from the display size each frame (`core/item_banner.rs`); text is built on receipt, textures are loaded once at init, and the seconds left go through a reused buffer.

- **Banner**, 4 s, queued, fading in over 0.25 s and out over the last 0.5 s (`ItemFeed::banner_alpha`, applied to every colour it draws): top centre, block top at 13% of the screen height, over a gradient from the top edge (alpha 0.78) fading out at 48% of the height. Icon 7.5% of the width, title in uppercase Barlow Condensed 600 at 3.4% (letter spacing 0.08 em; danger colour for an effect received, gold otherwise), line in Public Sans at 1.6%, detail at 1.2% in the disabled text colour, each with a dark shadow.
- **Held row**: while the player holds an item, any item, a first row in the race panel, above the reminder rows, shows its icon and gold name, with no countdown. The held item is the one `auth_ok.held_item` names, then the last grant's; an `item_result`, which the server sends once it spent the item, forgets it. The row appears when the grant's goods is in the inventory (spawned, or already there; a new grant replaces it), follows every inventory read (shown while the held item's goods is in the inventory, so it comes back after a game restart), leaves on its goods' `item_remove`, a use of its goods or a new start, and stops showing once the run is over (finished or out). The name and icon come from the catalog (`race_item_catalog.items`).
- **Reminder rows**, in the race panel after the leaderboard and before the status message: icon, text (danger for an effect received, gold for the sender's own) and the seconds left, right aligned.
- No overlay tag marks a race with items: the race panel has no room to spare.
- **Ink**: while active, every exit row reads `-> ???` with no location line. The exits cache is rebuilt when the zone, the width or the ink state changes, not every frame.

### Icons

`mod/assets/race_items/<icon>.png` (160x160 PNG) are embedded in the DLL and uploaded once at init; an icon name the mod does not know draws `unknown.png`. The art comes from the generator repo: drop the final `race_items_icon_<icon>.png` files (1024x1024, the generator derives the in-game textures from them) in `speedfog/data/plugins/`, run `uv run tools/sync_race_item_icons.py` (it reads the names from the catalog's `[icons]`, checks every file is a square PNG of at least 160x160, copies nothing when any is bad, and writes each icon downscaled to 160x160: the banner draws it at 7.5% of the screen width, 144 px at 1080p, and the full-size art would weigh megabytes in the DLL), then release the mod. `unknown.png` is outside the catalog and edited by hand.

In game, the Race Item shows the held item's icon: the mod writes the item's `icon_id` into its goods' `EquipParamGoods` row in memory (`race_items::set_goods_icon`) before each grant's spawn, and for the held item again before every inventory report, at each loading exit and reconnection while connected (a game restart reloads the params; `auth_ok.held_item` names the item to the restarted mod). A write made before the params are indexed (`prewarm_params`) is skipped with a warning (`[ITEMS] Goods icon not set`), and the next one makes it. Before a first write it shows its own `item_box` icon (60396). The in-game textures come with the seed (icon ids 60385 to 60396).

## In-game test protocol

With the compiled mod and one game, on the local server. `tools/race_items_bot.py` plays the other runners: each bot is a local user whose mod is the script, so every item reaches you through the server's real rules. Where to look: the overlay, the mod log (`speedfog_racing.log` next to the DLL, `[ITEMS]` lines), the bot console, and `status` in that console (rank, tier, layer, held item of every runner).

### Setup

1. **Mod.** On Windows, `cd mod && cargo build --lib --release`, then copy `target/release/speedfog_racing.dll` over `tools/assets/speedfog_racing.dll` on the server machine: every seed zip the local server hands out carries that DLL (`MOD_DLL_PATH`).
2. **Server and web.** The dev server (`:8000`) and web (`:5173`) run; `WEBSOCKET_URL` in `server/.env` is the address the game PC reaches (the LAN address, not localhost).
3. **Seeds.** A pool folder `$SEEDS_POOL_DIR/race_items_test/` with a pool `config.toml` and race items seeds named `seed_<anything>.zip` (generated with `[plugin.race_items] enabled = true`, graph.json 4.12 or later), scanned with `cd server && uv run speedfog-scan-seeds --pool race_items_test`. Every race consumes a seed: add one copy per race under a new name and scan again.
4. **Race.** On the web, create a community race in that pool with Race items on, and join it.
5. **Bots.** `cd server && uv run python ../tools/race_items_bot.py <race_id> --bots <user1>,<user2>`, two local usernames; they join while the race is in setup and report ready. Keep the console open (`help` lists the commands).
6. **Start.** Download your seed zip from the race page, launch it, wait until your mod is ready, then start the race from the web.

Positions decide the targets, so the checks run in this order. The bots report your IGT, so the item order (above) follows the layers here: a bot is never ahead of you in IGT, nor you of a bot. Wait a few seconds after the start before driving the bots: until its first report of the running race, a bot is not playing and the server drops its flags (the console says so). Then go through the first fog gate: you lead (checks B). Afterwards, `ahead <user1>` walks that bot forward to the deepest layer while `<user2>` stays at the start: the field reads user1, you, user2 for checks C to F, so you draw middle items, you are the runner just behind user1 and just ahead of user2, and group items from either bot hit you. `give WHO ITEM` hands any item to a bot or to you (yours spawns at your next load: a fog gate or a quit-out).

### Checks

#### A. Grants and inventory (any position)

1. Kill a boss in game: the item lands as the Race Item, in the same quick slot every time, with the item's icon, the gold banner and the held row (`[ITEMS] Goods spawned`, then `item_received`); `status` shows it confirmed.
2. Quit out and reload, then restart the game: still one copy, with the item's icon and the held row back; `[ITEMS] Inventory read` lists the Race Item and no new spawn is requested (the grant was confirmed). `Goods already held, spawn skipped` only shows when the server sends a grant again, after a crash between the spawn and its `item_received`.
3. Use it: the slot greys out at 0 and the next grant refills it; the next `[ITEMS] Inventory read` no longer lists it, the held row goes, `status` shows nothing held. A targeted item shows on the console as `hit by ...` on a bot.
4. `give <you> mushroom`, load, use it: rolls and sprints cost no stamina for about 30 s, with its buff icon and the "Infinite stamina" reminder counting down.
5. `give <you> rune_pouch_2`, load, use it: 20000 runes and the "Runes added" banner.
6. `give <you> shield` while you hold a Race Item, then load: the Race Item leaves the inventory (take back), the Shield arrives.
7. `give <you> banana` while you hold a Race Item, then load: still one copy, now with the Banana's icon and row (`Goods already held, spawn skipped`, then `item_received`); `status` shows it confirmed.

#### B. While you lead (before `ahead`)

1. Blue Shell from user2 (`give <user2> blue_shell`, `use <user2>`): max HP halved for 15 s, current HP capped, never killed.

#### C. Items on you (after `ahead <user1>`; `give <bot> ITEM`, then `use <bot>`)

1. Red Shell from user2: HP drops by 40% of max and stays down. Repeat at low HP: the hit lands at 20%, then deals 10%, and never kills (`[ITEMS] Damage applied`).
2. Banana from user1: 15% of max HP.
3. Hammer from either bot: fat roll for 15 s, "Fat-roll" reminder. The log line `[ITEMS] Equip load rate set` gives `current` and `max`: `current` must match the equipment screen's load, once with a bow and arrows equipped and once without (arrows and bolts are left out of the sum), and the screen's max becomes `current / 0.97`. A second Hammer within the 15 s keeps you heavy instead of cancelling the first.
4. Lightning: forced slow walk for 15 s, then normal speed.
5. Flask Stopper: no flask for 15 s.
6. Toxic Blossom: poisoned; Neutralizing Boluses cure it.
7. Ink: every exit reads `-> ???` without location for 15 s, then comes back.
8. Two items in a row (one per bot): the banners queue, 4 s each, each fading in and out, and the reminder rows stack.

#### D. Shield

1. `give <you> shield`, load: the Shield lands as its own goods, not in a quick slot, and a gold Shield row shows in the race panel, also after a game restart. Then a Red Shell from user2: the row goes, your Shield leaves the inventory (removal event), your banner reads "Blocked Red Shell" from user2, and the bot's result reads "Blocked by <you>'s shield" with no damage detail.

#### E. Robustness

1. Network pull: cut the game PC's network and wait until the race page shows your mod disconnected (the server only notices a dead socket after a while), then a bot uses a Red Shell on you: the bot's result reads `Missed` and nothing replays once you are back. Use your own item while cut off: once back, its use resolves once (the use flag is replayed).
2. Alt-F4 right after using an item: after the restart, the use resolves once, neither lost nor doubled.
3. Reset: a bot uses an item on you during a loading screen, the organizer resets the race before it ends: once the race starts again, the old effect is not applied. The reset closes every mod socket: the bots connect again, report ready and walk from the start node once the race runs again.

#### F. Overlay and cost

1. The inventory detail panel shows each race item's large icon.
2. Tracy (`docs/MOD_PROFILING.md`): the banner and reminder paths cost nothing visible.
