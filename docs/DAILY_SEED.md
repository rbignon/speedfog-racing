# Daily Seed

A "Daily Seed" is a single race created automatically every day at 08:00 UTC, open for 24 hours, that anyone can play and compare with other players. It does not affect ELO, has its own dedicated landing page, and reuses the regular Race entity (one Race per UTC calendar day).

## Overview

```
Daily creation loop (every 60s)
        │
        ▼
  close_expired_races()             ── close yesterday's daily if still RUNNING
        │
        ▼
  Lookup Race WHERE daily_date = today
        │
   exists ──────────────────────────► skip
        │ no
        ▼
  daily_seed_schedule[today.weekday()] -> pool_name
        │
        ▼
  INSERT Race (organizer = system:daily, daily_date, exclude_from_elo,
               status=RUNNING, started_at = 08:00 UTC, late_join = duration = 1440)
        │
        ▼
  assign_seed_to_race  +  notify_daily_seed_created (Discord)
```

The race lives in the regular `races` table, plays through the regular state machine ([RACE_LIFECYCLE.md](RACE_LIFECYCLE.md)), and is exposed through dedicated discovery endpoints (`/api/daily/*`). The `late_join_window_minutes = race_duration_minutes = 1440` setup means the registration window covers the entire 24h, so any visitor can join until the race ends.

---

## Data Model

### Race columns

| Column             | Type                    | Notes                                                                                                    |
| ------------------ | ----------------------- | -------------------------------------------------------------------------------------------------------- |
| `daily_date`       | `date`, nullable        | Canonical UTC rotation date. NULL on regular races. A race is a Daily Seed iff `daily_date IS NOT NULL`. |
| `exclude_from_elo` | `bool`, default `false` | Generic "skip ELO and ELO-rated stats" flag. Read by `update_elo_ratings` and stat aggregation queries.  |

Two indexes back the column:

- `uq_races_daily_date`: partial UNIQUE index `WHERE daily_date IS NOT NULL`. Hard guarantee that two Daily Seeds cannot share a rotation date. Backed by `IntegrityError` handling in the creation loop for concurrent ticks.
- `ix_races_daily_date`: regular index, used by lookups (`/api/daily/{date}`, `/api/daily/recent`, exclusion filters in regular race listings).

Both `daily_date` and `exclude_from_elo` are exposed on `RaceResponse` and `RaceDetailResponse`, so the frontend branches on them without a separate flag.

### `daily_seed_schedule` table

```
weekday    int   primary key   -- 0 = Monday, 6 = Sunday
pool_name  text  not null      -- FK pools.name
```

The Alembic migration seeds the seven rows with `pool_name = 'standard'`. Admins rotate themes from the `Daily` tab in `/admin` (see "Pool Rotation Schedule" below). The pool name capitalized is the theme label rendered in UI and Discord.

A weekday-based pattern (Monday = X, Tuesday = Y, ...) is intentional: it gives the community a recognizable rhythm. Per-date overrides are out of scope.

### System user

A row inserted by the migration:

```
twitch_id            'system:daily'
twitch_username      'speedfog_daily'
twitch_display_name  'Daily Seed'
role                 UserRole.SYSTEM
api_token            null
```

The `system:` prefix on `twitch_id` keeps the namespace disjoint from real Twitch IDs. `UserRole.SYSTEM` is a dedicated role with no login path: this user never receives an OAuth flow and never makes API calls, so `api_token` is null.

The user only exists to satisfy the non-nullable `Race.organizer_id` foreign key on Daily Seeds. Because `users.api_token` was non-nullable before this feature, the same migration relaxes the column to `NULL`.

### `ParticipantPreview` additions

`ParticipantPreview` (used by `RaceResponse.participant_previews` and `RaceListResponse`) gains two fields on top of the existing `placement: int | None`:

| Field    | Type                | Notes                                                                |
| -------- | ------------------- | -------------------------------------------------------------------- |
| `status` | `ParticipantStatus` | Always populated.                                                    |
| `igt_ms` | `int \| None`       | Final IGT when `status == FINISHED`; treat as in-progress otherwise. |

The `DailyBanner` and dashboard summary use these fields to render finishers count and fastest IGT without paying for the full `ParticipantResponse` payload.

### Migration

A single Alembic migration (`ba25d0d70148_add_daily_seed_support`):

1. Adds `daily_date` (nullable) and `exclude_from_elo` (NOT NULL DEFAULT false) on `races`.
2. Creates `uq_races_daily_date` (partial unique) and `ix_races_daily_date`.
3. Relaxes `users.api_token` to nullable.
4. Adds the `SYSTEM` value to the PostgreSQL `userrole` enum inside an `autocommit_block()` (`ALTER TYPE ... ADD VALUE` cannot run inside a transaction).
5. Inserts the system user (idempotent: `ON CONFLICT DO NOTHING` on PostgreSQL, `INSERT OR IGNORE` on SQLite).
6. Creates `daily_seed_schedule` and seeds it with seven rows pointing at `standard`.

---

## Daily Creation Loop

Module: `services/daily_seed_loop.py`. Started in the FastAPI lifespan alongside `inactivity_monitor_loop` and `hard_close_loop`. Polls every 60 seconds.

### Rotation date

```python
def daily_date_for(now: datetime) -> date:
    return (now.astimezone(UTC) - timedelta(hours=8)).date()
```

The Daily Seed window starts at 08:00 UTC; instants before that hour still belong to the previous day's seed. This is the single source of truth used by both the creation loop and the lookup endpoints.

### Tick procedure

Each tick (`create_daily_seed_if_needed`) does:

1. **Roll yesterday.** Call `close_expired_races(session_maker)`. Same idempotent primitive used by `hard_close_loop`; safe under concurrent ticks because it relies on the optimistic-locking status transition.
2. **Existence check.** Look up `Race WHERE daily_date = today`. Skip if found.
3. **Overlap guard.** Look up any prior daily still in `RUNNING` (`daily_date < today AND status == RUNNING`). If one remains after step 1, log an error and skip. Two RUNNING dailies must never be exposed by the API.
4. **Schedule lookup.** `daily_seed_schedule[today.weekday()]`. Missing row -> log an error, skip.
5. **Pool check.** Resolve the pool by name; if it is missing or `enabled = False`, log an error and skip.
6. **System user check.** Resolve `twitch_id = 'system:daily'`. Missing -> log and skip.
7. **Insert + seed assignment + commit.** The race is created with strict 08:00 UTC alignment regardless of how late the tick fires:

   ```
   organizer_id              = system_user.id
   daily_date                = today
   exclude_from_elo          = True
   is_public                 = True
   open_registration         = True
   max_participants          = None
   private_dag               = False
   late_join_window_minutes  = 1440
   race_duration_minutes     = 1440
   status                    = RUNNING
   started_at                = datetime(today, 08:00, UTC)
   seeds_released_at         = started_at
   ```

   `assign_seed_to_race` picks a seed in the same transaction. The whole `add` / `flush` / `assign` / `commit` is wrapped in an `IntegrityError` guard: PostgreSQL enforces the partial unique index at flush time, so a concurrent tick (e.g. on boot) loses its INSERT and falls through to a clean rollback + INFO log.

8. **Re-fetch + Discord.** Re-fetch the race with eager-loaded `organizer`, `seed`, `participants.user`, then call `notify_daily_seed_created(race, previous_race)` outside the DB session. The previous race is looked up for `daily_date = today - 1 day` to render yesterday's podium.

### Skip conditions (return None)

| Condition                                         | Severity | Recovery                                         |
| ------------------------------------------------- | -------- | ------------------------------------------------ |
| Race already exists for `today`                   | normal   | Next tick when `today` rolls over.               |
| Previous daily still RUNNING                      | error    | Operator intervention; next tick retries.        |
| Schedule row missing for `today.weekday()`        | error    | Insert the row; next tick retries.               |
| Pool missing or disabled                          | error    | Re-enable the pool or reassign the schedule row. |
| System user missing                               | error    | Re-run the migration.                            |
| `assign_seed_to_race` raised (no available seeds) | error    | Top up the pool; next tick retries.              |
| `IntegrityError` on insert (concurrent tick)      | info     | Other worker won; next tick is a no-op.          |

### Strict 08:00 alignment

`started_at` is hard-coded to `08:00 UTC` of the rotation date, even when the loop fires at 08:03 (server restart at 08:02). Combined with `seeds_released_at = started_at`, this means `GET /api/races/{id}/my-seed-pack` is immediately available after a participant joins, including when creation catches up a few minutes late.

---

## Pool Rotation Schedule

The schedule is data, not code: `daily_seed_schedule` rows define which pool runs on which weekday. Admins edit the rotation from the `Daily` tab in `/admin`, which calls:

- `GET /api/admin/daily-schedule` -> the seven rows plus the list of pools eligible to be assigned (enabled, non-training).
- `PATCH /api/admin/daily-schedule/{weekday}` with `{ "pool_name": "<name>" }` -> updates one row, validating that the pool exists, is enabled, and is not a training pool.

A change to the row for the _current_ weekday does not affect today's already-emitted Daily Seed (the seed was assigned at creation time and is stored on the race row); it takes effect the next time that weekday rolls around. The admin UI surfaces this with a `Today` badge and an inline note.

The pool must exist in `pools` and be `enabled = True`; otherwise the next 08:00 tick logs an error and skips creation. The fallback seeded by the migration is `standard` for all seven weekdays.

---

## API Endpoints

Discovery surface for Daily Seeds. All three live under `/api/daily`.

| Endpoint                        | Returns              | Description                                                                                                                                                                                                                  |
| ------------------------------- | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /api/daily/today`          | `RaceResponse`       | The current rotation day's daily, or 404 if creation has not happened yet.                                                                                                                                                   |
| `GET /api/daily/{yyyy-mm-dd}`   | `RaceDetailResponse` | Look up by rotation date. Used by `/daily/[date]`.                                                                                                                                                                           |
| `GET /api/daily/recent?limit=N` | `RaceListResponse`   | Past dailies (`daily_date IS NOT NULL AND daily_date < today`) ordered by date desc. `limit` clamped to `[1, 30]`, default 7.                                                                                                |
| `GET /api/daily/week`           | `DailyWeekResponse`  | The seven calendar-week cells (Mon..Sun ISO order) consumed by the home, dashboard, and daily-detail grid. Optional `?date=YYYY-MM-DD` query parameter anchors the returned week on the date's ISO week (defaults to today). |

Route resolution is unambiguous: `today` and `recent` are literal segments, `{daily_date}` only matches strings parseable as `%Y-%m-%d` (otherwise 404). The "today" lookup uses `daily_date_for(now_utc)` so it switches over at exactly 08:00 UTC.

`POST /api/races/{race_id}/join` is unchanged: the existing late-join logic accepts joins on RUNNING races while `late_join_window_minutes` is set and the registration window is still open. Daily Seeds inherit this behavior with no special code path.

### Exclusion from regular surfaces

Endpoints whose audience is "regular races" filter Daily Seeds out explicitly:

- `GET /api/races` and the joinable subquery: `WHERE Race.daily_date IS NULL`.
- `services/stats_service.py` ELO aggregates: `Race.exclude_from_elo.is_(False)` on every join.
- `services/analytics_service.py` admin dashboard: every race-side query filters with `Race.daily_date.is_(None)` so KPIs, weekly trends, heatmaps, pool usage and top organizers reflect community-organized racing only.

The Daily nav indicator on the frontend uses `GET /api/daily/today` rather than `GET /api/races/joinable`, which assumes scheduled races and would not yield the right answer.

---

## Reroll Path

The existing endpoint `POST /api/races/{race_id}/reroll-seed` is the recovery tool when the daily seed is broken (e.g. crashes the game at launch, no one can play). It accepts Daily Seeds in `RUNNING` status, reusing the same handler as setup-phase rerolls.

Branching inside the handler:

| Aspect              | Regular race                              | Daily Seed                                                                                                                                                                                      |
| ------------------- | ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Allowed status      | `SETUP`                                   | `RUNNING`                                                                                                                                                                                       |
| Permission          | `_require_organizer` (organizer or admin) | Same. Organizer is the system user, so in practice only admins.                                                                                                                                 |
| Participant reset   | n/a (no participants yet)                 | All participants reset to `REGISTERED` (`current_zone`, `current_layer`, `igt_ms`, `death_count`, `finished_at`, `zone_history`, `last_igt_change_at` cleared; `layer_entry_igts` set to `{}`). |
| `seeds_released_at` | unchanged (gated until release)           | Set to `now()` so participants can re-download immediately.                                                                                                                                     |
| Public chat message | "Seed has been rerolled"                  | "Seed has been rerolled. All previous runs are invalidated."                                                                                                                                    |

Race version bumps via the existing optimistic-lock UPDATE; `reroll_seed_for_race` releases the previous seed back to AVAILABLE (unless DISCARDED) and assigns a fresh one from the same pool. The frontend detects the participant reset via the standard `race_state` push and shows a toast.

---

## ELO and Analytics Skip

`update_elo_ratings` (in `services/stats_service.py`) early-returns when `race.exclude_from_elo` is true. The check is inside the function rather than only at the call site, because the admin "replay ELO history" tool calls the same function. No `EloHistory` rows are written for excluded races, and no rating shifts are applied.

ELO-rated aggregations elsewhere in `stats_service` (leaderboards, user stats) join through `Race.exclude_from_elo.is_(False)` so excluded races never appear in the ranked surfaces.

The flag is generic: any future race type that should not affect ELO can opt in by setting `exclude_from_elo = True` without further wiring.

Admin analytics (`services/analytics_service.py`) excludes Daily Seeds from race-side aggregates by filtering on `Race.daily_date.is_(None)` rather than using `exclude_from_elo`. The Stats tab measures community racing activity; system-organized dailies would inflate counts and skew per-race averages. Training-side aggregates are unaffected because training sessions have no daily concept.

---

## Frontend Surfaces

The frontend exposes a Daily Seed through three surfaces, all consuming `daily_date` from the standard `RaceResponse`/`RaceDetailResponse` payloads.

### Routes

- `/`, `/dashboard`, and `/daily/[date]`: all three surfaces call `GET /api/daily/week` to populate the `DailyWeekGrid.svelte` component. `/daily/[date]` passes the URL date as the `?date=` anchor so the grid lands on the week containing the viewed daily, with that cell highlighted ("you are here"). The grid renders prev/next arrows on every surface for inline week navigation. On `/daily/[date]` the cell matching the viewed race is patched live from the page's existing WebSocket subscription via `applyLiveDailyDayUpdate` (`web/src/lib/daily.ts`), so participant counts and the viewer's status strip stay in sync with the rest of the page; `/` and `/dashboard` have no race-scoped WS, so they keep using the server snapshot directly. When the daily window crosses its end while the page is open (`now > race_ends_at`), `/daily/[date]` refetches `/api/daily/week` once so the canonical "today" badge moves from the just-finished cell to the new active day (and picks up the next daily's `race_id` if the 08:00 UTC cron has already generated it).
- `/daily` (`web/src/routes/daily/+page.ts`): server-side load that fetches `GET /api/daily/today`. If a daily exists, it issues a 307 to `/daily/{daily_date}`. If the request fails (404 or network), the route falls through to an empty-state component.
- `/daily/[date]/+page.svelte`: the dedicated landing page for a given rotation date. The same component renders the live daily and any past daily; it branches on whether `now < race_ends_at`. Layout mirrors `/race/[id]` with daily-specific adaptations (single public chat tab, no `RaceStatus` badge, no participants list during setup, "Play now" CTA on the DAG area when the viewer is not yet a participant). The `DownloadModal` is reused with `actionLabel = "Download Seed Package"` so the same flow lands the per-participant zip.

### Components

- `DailyWeekGrid.svelte`: rendered on `/` (variant `home`, replaces the previous banner) and on `/dashboard` (variant `dashboard`, replaces the previous "Today + recent dailies" section). Shows seven cells for the current calendar week (Monday through Sunday in ISO order) with one of four states per cell: `missing_past` (no race row for that past day), `past` (clickable, single winner row + participants count + viewer's status strip if logged in), `today` (uses the standard neutral border with a soft gold outer glow, a small gold "TODAY" header badge, plus a state-driven bottom strip), `future` (greyed out, pool from `daily_seed_schedule` + "Opens in HH:MM" countdown). On past cells the body shows only the placement-1 finisher (medal + name + IGT) on a single line; the rest of the API-supplied podium is unused here so the cell stays one row tall regardless of finisher count. The today cell never renders a winner row even after the first finisher comes in, to avoid spoiling the in-progress race; it stays on the "Daily seed incoming" / "X players" placeholder until the day rolls over to `past`. Both `today` and any played `past` cell carry a full-width bottom strip whose label and color depend on the viewer's participant status: "PLAY NOW" (green) when anonymous or `my_result == null` on today, "IN PROGRESS" (orange) for `registered`/`ready`/`playing`, a split `✓` (left) + `placement/total · IGT` (right) layout (green text on muted grey) when finished, "ABANDONED" (muted grey) when abandoned or signed up but never played. The finished strip's split (rather than a single inline string) keeps the check mark as a state badge and the score as data, with breathing room between them; the green color carries the "finished" semantics so the word "DONE" is not rendered.

The cell body (winner row or "No finishers" / "Daily seed incoming" / "X players" placeholder) is wrapped in a flex-grow container that vertically centers the body between the pool name (top) and the bottom strip, so the row of seven cells lines up regardless of which placeholder a cell shows. Past cells the viewer did not participate in render an invisible placeholder strip (`visibility: hidden`) so the body's vertical centering matches sibling cells that do carry a real strip; without the placeholder, the body would expand into the strip's slot and the winner row would drift downward versus its neighbors. Mobile (under 640px) switches the grid to a horizontal-scroll strip with the today cell auto-centered on mount.

- `RaceControls.svelte`: detects `race.daily_date !== null` (`isDaily`) and adapts the reroll confirmation copy to "Rerolling will discard all current and finished runs for this Daily Seed". The button is admin-only because the system organizer cannot log in.

### Top-bar nav indicator

The root layout (`web/src/routes/+layout.svelte`) calls `GET /api/daily/today` for logged-in users and renders a green dot next to the `Daily` link when `daily.my_role !== 'participating'`. The dot disappears as soon as the user has joined, regardless of subsequent finished or abandoned status.

### DAG visibility

DAG rendering on `/daily/[date]` follows the standard race rules with `late_join_window_minutes == race_duration_minutes`, so `private_dag` has no effect during the 24h window:

| Viewer                               | Daily running                         | Daily ended    |
| ------------------------------------ | ------------------------------------- | -------------- |
| Non-logged or non-participant        | "Play now" placeholder                | `MetroDagFull` |
| Participant `REGISTERED` / `READY`   | Empty `MetroDagProgressive`           | `MetroDagFull` |
| Participant `PLAYING`                | `MetroDagProgressive` (own path)      | `MetroDagFull` |
| Participant `FINISHED` / `ABANDONED` | `MetroDagFull` (with other finishers) | `MetroDagFull` |

Hiding the DAG from non-participants while the daily is running is intentional: every spectator is a potential player, and exposing the path graph would spoil approach choices that the player should make blind. After T+24h the DAG becomes public for everyone.

The leaderboard, by contrast, is always visible to everyone, even on a running daily, even to non-participants. That visibility is the social pressure that makes the format work. The current-zone label next to a still-playing competitor follows the same rule as `/race/[id]`: hidden while the late-join window is open (so a potential late joiner cannot harvest positional intel by spectating) or while the viewer is still racing themselves; revealed to participants who have finished or abandoned, and to everyone once the daily ends. Selecting a leaderboard row highlights that runner's path on `MetroDagFull`, mirroring the race page (Ctrl/Cmd-click extends the selection, Escape clears it).

---

## Discord Notification

A single message per rotation day, sent right after a successful daily creation, in the community channel. No mention.

`notify_daily_seed_created(race, previous_race)` in `discord.py`:

- Title: `🌅 Daily Seed - {Month Day}` using the UTC rotation date so every viewer reads the same day label.
- Body: pool display name (capitalized), closes-at line as `<t:UNIX:R>` (so each viewer sees their own local time), `[Play now](/daily)` link.
- Yesterday's podium block: top three finishers with medals and IGT, plus the total finisher count, computed from `previous_race.participants` filtered to `FINISHED`. Omitted if `previous_race` is `None` (first ever, or yesterday was skipped) or had no finishers.

The notification is best-effort: any HTTP error is logged but does not fail the loop tick. To avoid double-posting, `fire_race_finished_notifications` suppresses the regular finished-race embed for races where `daily_date is not None`: the daily already announced itself at creation with the prior podium.

---

## In-mod replay leaderboard

Daily Seeds are async: a player joining at hour 18 of the 24h window would
otherwise see a leaderboard already populated with finishers, killing the
sense of competition. To preserve immersion in the in-game overlay, the
server projects the mod's `leaderboard_update` to the viewer's current IGT:
finishers and concurrent runners appear at the position they had when their
own IGT matched the viewer's. See
[`docs/specs/2026-05-06-daily-replay-leaderboard-design.md`](specs/2026-05-06-daily-replay-leaderboard-design.md)
for the exact projection rules.

Scope is mod-only: web spectators (`/daily/[date]`, OBS overlays) keep
seeing the real state, since the daily is already explicitly spoilers-OK on
the web side. The protocol shape is unchanged; see
[PROTOCOL.md](PROTOCOL.md#leaderboard_update) for the per-mod projection
note.

---

## See also

- [RACE_LIFECYCLE.md](RACE_LIFECYCLE.md) for the underlying race / participant state machines (Daily Seeds reuse them as-is).
- [SEED_PIPELINE.md](SEED_PIPELINE.md) for seed assignment and reroll mechanics.
- [STATS.md](STATS.md) for the ELO computation that `exclude_from_elo` short-circuits.
- [PROTOCOL.md](PROTOCOL.md) for the REST and WebSocket payload reference.
