# Progression System & Seasonal Content Design

Player retention and long-term progression system for SpeedFog Racing: XP/levels, daily quests, monthly themed seasons with dedicated leaderboards, and in-game overlay feedback.

## Context

### Problem

Players lack reasons to return between organized races. Training exists but has no "pull". Active players (50-60 weekly) have no sense of progression beyond ELO. The mod needs a meta-game that rewards regular engagement and gives each session a sense of purpose.

### Community snapshot (April 2026)

- 184 accounts, 94 with at least 1 race, 44 with 3+ races
- ~20 races/week (3/day average), median 4 participants per race, peak 25
- 56 unique players in the last week, strong upward trend
- Training well-used: 452 sessions, 102 unique trainers, 68 in the last 30 days
- Core of ~10 players at 10+ races; long tail of occasional players (1-5 races)

### Design approach

Hybrid XP + Challenges (Approach C): XP/levels as the progression backbone, fueled by quests AND natural play. Quests act as multipliers and memorable milestones, not mandatory grind. Casual players progress just by playing; invested players have daily objectives.

## XP & Levels

### XP sources

| Source                    | XP              | Condition                   |
| ------------------------- | --------------- | --------------------------- |
| Finish a race             | 100             | FINISHED status             |
| Race placement            | +50 / +30 / +20 | 1st / 2nd / 3rd             |
| Race with 5+ participants | +25             | Encourages larger races     |
| Finish a training run     | 30              | FINISHED status             |
| Daily quest completed     | 40-60           | Depends on difficulty       |
| Seasonal quest completed  | 200-400         | Depends on difficulty       |
| Race on seasonal pool     | x1.5 multiplier | Applied to base race XP     |
| Training on seasonal pool | x1.5 multiplier | Applied to base training XP |

Races give ~3x more than training to preserve competitive incentive, but training remains a viable source for players who cannot coordinate a race.

### Level curve

Formula: `xp_for_level(n) = 200 * n + 10 * n^2`

| Level | Cumulative XP | Rough equivalent     |
| ----- | ------------- | -------------------- |
| 1     | 210           | 2 races              |
| 5     | 1,250         | 10 races             |
| 10    | 3,000         | ~3 active weeks      |
| 20    | 8,000         | ~2 active months     |
| 50    | 35,000        | Very invested player |

### Global vs seasonal level

- **Global level**: Never resets. Cumulates all activity. Long-term prestige.
- **Seasonal level**: Resets each month. Earned only from seasonal pool races/training + seasonal quests. This IS the monthly leaderboard (no separate seasonal ELO).

The permanent ELO system remains the competitive ranking, unchanged.

## Quests

### Daily quests

3 quests per day, generated automatically at midnight UTC. Each drawn from a catalog with randomized parameters. Completable in races or training (unless marked race-only). The system picks 3 quests from different categories to guarantee variety.

**Quest catalog (examples):**

| Category    | Quest                                      | Variable params               |
| ----------- | ------------------------------------------ | ----------------------------- |
| Survival    | Clear N zones without dying                | N = 3-8                       |
| Survival    | Finish a run with fewer than N deaths      | N = 5-15                      |
| Boss        | Kill N major bosses                        | N = 2-5                       |
| Boss        | Kill a specific boss without dying         | Boss = random from major_boss |
| Speed       | Finish a run in under N minutes            | N = adapted to pool           |
| Speed       | Clear a zone in under N seconds            | N = adapted to tier           |
| Exploration | Visit N distinct zones in a run            | N = 10-20                     |
| Exploration | Backtrack at least N times in a run        | N = 2-5                       |
| Pathing     | Finish a run without backtracking          |                               |
| Competitive | Finish a race in top 3                     | Race only                     |
| Competitive | Finish a race ahead of a higher-ELO player | Race only                     |

Missed daily quests can be completed within a 48h sliding window: the player sees today's 3 quests plus yesterday's uncompleted quests (if any). Once 48h have passed since a quest's `active_date`, it expires and is no longer shown.

### Seasonal quests

5-8 quests defined manually at each season start, tied to the theme. Active for the full month. Mix of one-shot and cumulative:

- **CUMULATIVE** quests track progress across all runs on the seasonal pool (e.g., "Kill 5 magma dragons" increments each time one is killed, across any number of runs).
- **PER_RUN** quests must be completed within a single run (e.g., "Kill Rykard without dying").

Cumulative quests show real-time progress in-game: killing magma dragon 3 of 5 triggers an overlay notification "Magma Dragons: 3/5", and completing it shows "Magma Dragons: 5/5".

Example for "Season Volcans":

- "Kill 5 magma dragons (Makar, Theodorix)" (300 XP, cumulative)
- "Finish 8 races on the Volcans pool" (250 XP, cumulative, race-only)
- "Accumulate fewer than 50 deaths across 5 runs" (300 XP, cumulative)
- "Kill Rykard without dying" (400 XP, one-shot)
- "Finish 1st on a Volcans pool race" (350 XP, one-shot)
- "Finish a run without backtracking" (300 XP, one-shot)

### Quest detection

Detection is server-side, based on data already reported by the mod (zone_history, death_count, igt_ms, event_flags). The mod does not need to know about quests: it reports raw facts, the server evaluates.

Real-time quests (deathless streak, zone clear time) are evaluated server-side on each `event_flag` or `status_update` received via WebSocket.

## Seasons

### Lifecycle

1. **Preparation (~7 days before)**: Generate the themed pool via existing tools (`generate_pool.py` with a dedicated TOML). Announce on Discord with theme and quests.
2. **Start (1st of the month, 00:00 UTC)**: Server job transitions season from UPCOMING to ACTIVE. Seasonal pool appears in the pool list, quests are revealed, seasonal leaderboard starts at zero.
3. **In progress**: Players race/train on the seasonal pool, complete quests. Seasonal leaderboard visible on the site.
4. **End (last day, 23:59 UTC)**: Server job transitions to FINISHED. Leaderboard is frozen, rewards are attributed automatically.
5. **Archive**: Seasonal leaderboard remains viewable in history ("Season 1: Volcans, May 2026"). Pool is hidden from active rotation.

### Themed pools

Each season has a specific pool TOML inheriting from `_base.toml`. A single pool serves both races and training (seeds are consumed in races, remain available for training, matching current behavior).

The seasonal pool is only visible in the race creation and training UI when a season with status ACTIVE references it. Otherwise it is hidden.

Examples:

| Season       | Theme                         | Pool constraints                                                                                  |
| ------------ | ----------------------------- | ------------------------------------------------------------------------------------------------- |
| Volcans      | Volcano Manor / Mt. Gelmir    | final_boss_candidates restricted to Rykard, Fire Giant. High volcanic legacy_dungeon probability. |
| Boss Rush    | Bosses everywhere             | major_bosses = 15+, mini_dungeons = 2, short layers                                               |
| DLC          | Shadow of the Erdtree content | DLC-only zones and bosses                                                                         |
| Endurance    | Very long runs                | min_layers = 40, max_layers = 50                                                                  |
| Total Random | Chaos                         | randomize_bosses = "all", everything randomized                                                   |

### Seasonal leaderboard

The seasonal leaderboard ranks players by seasonal level (XP earned on the seasonal pool during the month). It encodes both performance and engagement:

- Winning races gives more XP than losing (placement bonuses)
- Seasonal quests reward thematic exploits (not just "play a lot")
- Seasonal pool races/training get a x1.5 XP multiplier

A player who does 15 races and often finishes top 3 can beat one who does 25 races but finishes mid-pack. Neither pure grind nor pure skill.

### Rewards

By seasonal level tier:

| Tier              | Reward                                                                    |
| ----------------- | ------------------------------------------------------------------------- |
| Level 3           | Season badge on web profile (permanent)                                   |
| Level 8           | Seasonal name effect on overlay (active during the following season only) |
| Level 15          | Seasonal title on profile ("Survivor of the Volcans")                     |
| Level 25          | Permanent seasonal name effect (gradient themed to the season's colors)   |
| #1 on leaderboard | Exclusive title + special icon                                            |

### Name effects

Players have an **active name effect** configurable in settings on the website. Available options:

| Option                        | How to unlock                        | Duration                                               |
| ----------------------------- | ------------------------------------ | ------------------------------------------------------ |
| Default (current solid color) | Always available                     | Permanent                                              |
| Last season's effect          | Reach level 8 of the previous season | Active only during the following season, then replaced |
| Permanent season N effect     | Reach level 25 of season N           | Permanent, collectible                                 |

Each season has its own visual style tied to the theme: red/orange tones for Volcans, blue/purple for DLC, acid green for Total Random, etc.

The chosen effect is stored in `overlay_settings` on the User model (field already exists), sent to the mod via `auth_ok`, and applied by the mod to the player's name on the leaderboard overlay. All participants see each player's effect.

## In-Game Feedback (Overlay)

### Ticker on line 1

The first line of the overlay currently shows the race/training name. It becomes a **priority ticker**: when an event occurs, the title text is temporarily replaced, then fades back.

**Message queue**: Events stack in a priority queue. Each message displays for 3-4 seconds with fade in/out. If the queue is empty, the run title returns. Messages are processed highest priority first.

| Event                    | Message                             | Priority |
| ------------------------ | ----------------------------------- | -------- |
| Level up                 | "Level 12!"                         | High     |
| Quest completed          | "Quest: Kill 5 Magma Dragons (5/5)" | High     |
| Quest progress           | "Magma Dragons: 3/5"                | Low      |
| XP gained (end of run)   | "+150 XP"                           | Medium   |
| Seasonal quest completed | "Season Quest: No Backtrack Run"    | High     |

Low-priority messages only display when the queue is empty (no cascade interruptions).

### Run summary

When the player finishes a run, the server sends a summary. The ticker plays a sequence: "+180 XP" then "Level 14!" (if level up).

### Name effect rendering on leaderboard

Leaderboard lines have two distinct styles:

- **Player name**: rendered with the player's active name effect (gradient, custom color, or default white)
- **Race data** (position, layers, IGT): status color unchanged (yellow=ready, white=playing, green=finished, gray=abandoned)

This preserves status readability while making name effects visible.

## Data Model

### New tables

#### Season

| Column       | Type        | Description                           |
| ------------ | ----------- | ------------------------------------- |
| id           | UUID        | PK                                    |
| name         | String(100) | "Saison Volcans"                      |
| slug         | String(50)  | Unique, URL-friendly                  |
| pool_name    | String(50)  | Logical FK to the pool TOML           |
| theme_colors | JSON        | `["#FF4500", "#FF8C00"]` for gradient |
| starts_at    | DateTime    | 1st of the month 00:00 UTC            |
| ends_at      | DateTime    | Last day 23:59 UTC                    |
| status       | Enum        | UPCOMING / ACTIVE / FINISHED          |

#### QuestTemplate

| Column               | Type        | Description                                                          |
| -------------------- | ----------- | -------------------------------------------------------------------- |
| id                   | UUID        | PK                                                                   |
| category             | String(50)  | "survival", "boss", "speed", "exploration", "pathing", "competitive" |
| quest_type           | Enum        | DAILY / SEASONAL                                                     |
| title_template       | String(200) | "Kill {count} {boss_type}"                                           |
| description_template | String(500) | Description with placeholders                                        |
| eval_type            | Enum        | PER_RUN / CUMULATIVE                                                 |
| eval_config          | JSON        | Metric configuration (see Quest Evaluation)                          |
| xp_min / xp_max      | Integer     | XP reward range for daily generation                                 |

#### QuestInstance

| Column      | Type        | Description                                                  |
| ----------- | ----------- | ------------------------------------------------------------ |
| id          | UUID        | PK                                                           |
| template_id | UUID        | FK QuestTemplate (nullable for hand-crafted seasonal quests) |
| season_id   | UUID        | FK Season (nullable; null = daily quest)                     |
| title       | String(200) | Resolved title                                               |
| description | String(500) | Resolved description                                         |
| eval_type   | Enum        | PER_RUN / CUMULATIVE                                         |
| eval_config | JSON        | Resolved metric config with concrete params                  |
| xp_reward   | Integer     | Final reward                                                 |
| active_date | Date        | Day this quest is active (daily) or null (seasonal)          |

#### PlayerQuestProgress

| Column            | Type     | Description      |
| ----------------- | -------- | ---------------- |
| id                | UUID     | PK               |
| user_id           | UUID     | FK User          |
| quest_instance_id | UUID     | FK QuestInstance |
| current_value     | Integer  | Progress (3/5)   |
| completed         | Boolean  |                  |
| completed_at      | DateTime | nullable         |

#### PlayerXP

| Column    | Type    | Description                                   |
| --------- | ------- | --------------------------------------------- |
| user_id   | UUID    | PK composite                                  |
| season_id | UUID    | PK composite (nullable; null = global)        |
| total_xp  | Integer | Cumulative XP                                 |
| level     | Integer | Derived level (cached to avoid recomputation) |

### Table modifications

**Race**: add `season_id` (UUID, FK Season, nullable). A race linked to a season draws from the seasonal pool and grants seasonal XP.

**User.overlay_settings**: stores name effect preferences:

```json
{
  "active_effect": "s1-volcans",
  "unlocked_effects": ["default", "s1-volcans"],
  "last_season_effect": "s2-dlc"
}
```

### Quest evaluation metrics

~8 base metrics, each with a dedicated evaluator function:

| Metric                | Evaluated on      | Parameters                                                                           |
| --------------------- | ----------------- | ------------------------------------------------------------------------------------ |
| `boss_kills`          | event_flag (boss) | node_filter, target                                                                  |
| `boss_kill_deathless` | event_flag (boss) | node_filter, target                                                                  |
| `deathless_streak`    | event_flag (zone) | target                                                                               |
| `run_completed`       | end of run        | constraints (max_deaths, max_backtracks, max_igt_ms)                                 |
| `runs_finished`       | end of run        | target, race_only (bool, explicit flag; when true, training completions are ignored) |
| `zones_visited`       | event_flag (zone) | target, node_filter (optional)                                                       |
| `finish_position`     | end of race       | max_position                                                                         |
| `zone_clear_time`     | event_flag (zone) | node_filter, max_time_ms                                                             |

Example eval_config values:

"Kill 5 magma dragons" (CUMULATIVE):

```json
{
  "metric": "boss_kills",
  "node_filter": { "boss_name": ["Magma Wyrm Makar", "Great Wyrm Theodorix"] },
  "target": 5
}
```

"Kill Rykard without dying" (PER_RUN):

```json
{
  "metric": "boss_kill_deathless",
  "node_filter": { "boss_name": ["Rykard, Lord of Blasphemy"] },
  "target": 1
}
```

"Finish a run without backtracking" (PER_RUN):

```json
{ "metric": "run_completed", "constraints": { "max_backtracks": 0 } }
```

"Clear 8 zones without dying" (PER_RUN):

```json
{ "metric": "deathless_streak", "target": 8 }
```

## Architecture

### Server: new files

| File                         | Responsibility                                                        |
| ---------------------------- | --------------------------------------------------------------------- |
| `services/season_service.py` | Season lifecycle (activation, closure, reward attribution)            |
| `services/quest_service.py`  | Daily generation, real-time evaluation, progress tracking             |
| `services/xp_service.py`     | XP attribution, level calculation, level-up detection                 |
| `api/seasons.py`             | Public endpoints (active season, seasonal leaderboard, player quests) |
| `api/quests.py`              | Player endpoints (active quests, progress)                            |
| `api/admin.py`               | Extended with season + seasonal quest CRUD                            |

### Server: WebSocket integration

Current flow in `websocket/mod.py`:

```
event_flag received -> zone_resolver -> zone_history update -> broadcast leaderboard
```

Becomes:

```
event_flag received -> zone_resolver -> zone_history update -> quest_service.evaluate(event)
                                                                  |
                                                                  v (if progress)
                                                            send quest_progress to mod
                                                                  |
                                                                  v
                                                            broadcast leaderboard
```

`quest_service.evaluate()` receives context (participant, event_flag, current zone_history) and checks all active quests for the player. It loads active quests (cacheable in memory on the WebSocket handler) and each metric evaluator is a pure function taking context and returning a progress delta.

### Server: end of run

When a participant finishes (race or training), the server:

1. Evaluates PER_RUN quests in a final pass
2. Awards base XP (run finished + placement + seasonal pool bonus)
3. Awards XP for completed quests
4. Checks for level-up (global and seasonal)
5. Sends `run_summary` to the mod

### Server: background jobs

| Job                  | Frequency    | Action                                                                  |
| -------------------- | ------------ | ----------------------------------------------------------------------- |
| Daily quest rotation | Midnight UTC | Generate 3 QuestInstance from DAILY QuestTemplates, distinct categories |
| Season activation    | Hourly       | Transition UPCOMING to ACTIVE when starts_at reached                    |
| Season closure       | Hourly       | Transition ACTIVE to FINISHED when ends_at passed, attribute rewards    |

### Mod: changes

| File               | Change                                                                       |
| ------------------ | ---------------------------------------------------------------------------- |
| `core/protocol.rs` | New messages: `quest_progress`, `level_up`, `run_summary` (Server -> Client) |
| `dll/ui.rs`        | Line 1 ticker: priority message queue with fade in/out, timer                |
| `dll/ui.rs`        | Name rendering with gradient: parse `name_effect` from `leaderboard_update`  |
| `dll/websocket.rs` | Handler for new messages, push into ticker queue                             |

### Mod: ticker implementation

```rust
struct TickerMessage {
    text: String,
    priority: Priority,  // High, Medium, Low
    duration_ms: u32,     // 3000-4000
}

struct Ticker {
    queue: VecDeque<TickerMessage>,
    current: Option<(TickerMessage, Instant)>,
    default_text: String,  // race name
    fade_progress: f32,    // 0.0 -> 1.0
}
```

Each frame: if current message expired, pop next by priority. If queue empty, fade back to default_text.

### Mod: gradient name rendering

`name_effect` arrives in `leaderboard_update` per participant. The mod stores a `HashMap<ParticipantId, NameEffect>`. At render time, if a player has a gradient, the name is drawn character-by-character with linear interpolation between the two theme colors. Status colors (yellow/white/green/gray) remain on position, layers, and IGT columns.

### Web: new pages and components

| Route/Component                      | Description                                                                              |
| ------------------------------------ | ---------------------------------------------------------------------------------------- |
| `/seasons`                           | Seasons page: active season (leaderboard, quests, time remaining) + past seasons archive |
| `/seasons/[slug]`                    | Season detail (leaderboard, quests, winners if finished)                                 |
| `components/QuestTracker.svelte`     | Player quest widget: daily + seasonal, progress bars                                     |
| `components/SeasonBanner.svelte`     | Homepage banner when a season is active (theme, time remaining, CTA)                     |
| `components/XpBar.svelte`            | XP bar in dashboard + player profile                                                     |
| `components/NameEffectPicker.svelte` | Name effect selector in settings                                                         |
| Modified: `PoolSelector`             | Seasonal pool with themed highlight and shimmer effect                                   |
| Modified: `dashboard`                | Quest section + XP/level progress                                                        |
| Modified: `user/[id]`                | Global level, season badges, active name effect                                          |

### Web: pool selector UI

The seasonal pool appears at the top of the pool list in race creation and training start, with:

- Border/background in the season's theme_colors
- A "Season" badge or season name
- Subtle shimmer/glow CSS effect
- Normal pools below in their usual sort_order

### WebSocket protocol additions

**Server -> Client (mod):**

```
quest_progress { quest_id: str, title: str, current: int, target: int, completed: bool, xp_reward: int }
level_up { new_level: int, is_seasonal: bool }
run_summary { xp_gained: int, quests_completed: int, new_level: int | null }
```

**Additions to existing messages:**

`auth_ok`: add `name_effect: { type: "gradient", colors: ["#FF4500", "#FF8C00"] } | null` per participant, add `active_quests: [{ quest_id, title, current, target }]` for the authenticated player.

`leaderboard_update`: add `name_effect` per participant entry.

## Operator Workflow (Monthly)

1. **Create pool TOML** (`tools/pools/season_volcans.toml`), inheriting `_base` with themed constraints
2. **Generate seeds**: `python generate_pool.py season_volcans --count 30`
3. **Ingest seeds**: server startup or admin endpoint
4. **Create season via admin API**: `POST /api/admin/seasons` with name, slug, pool_name, theme_colors, dates
5. **Create seasonal quests via admin API**: `POST /api/admin/seasons/{id}/quests` with quest definitions
6. **Verify**: `GET /api/admin/seasons/{slug}/preview` to check everything
7. **Wait**: server auto-activates on start date, auto-closes on end date, auto-attributes rewards

Manual effort per month: find a theme, write a TOML, generate 30 seeds, make 2-3 API calls. Everything else is automated.
