# Performance Audit -- Backend & WebSocket

**Date:** 2026-04-05
**Scope:** `server/speedfog_racing/` (REST API + services + WebSocket layer)
**Type:** Static code analysis + scalability reasoning (no runtime profiling performed)
**Out of scope:** SvelteKit frontend, Rust mod, runtime benchmarks
**Implementation status:** Updated 2026-04-06

## Methodology

Code-level audit of ~15k lines across `api/`, `services/`, `websocket/`, `models.py`. Each finding was validated against the actual source. Scalability numbers below assume a target **reference load**:

- 50 concurrent running races
- 20 participants per race (= 1,000 live mod connections)
- 100 spectators per race (= 5,000 spectator connections)
- 30 zone transitions per participant per race
- ~50k lifetime participants in DB

This is ~10x the current observed traffic, sized to reveal what will break first as the platform grows.

## Executive summary

The backend is structurally sound: async-first, SQLAlchemy async with `selectinload`, optimistic locking via `Race.version`, per-room WebSocket broadcast with timeouts, dedicated background tasks. No naive synchronous blocking I/O in hot paths.

However, **three classes of issues will become painful at the reference load**:

1. **No persistence-layer tuning** -- missing indexes on hot filter columns force sequential scans on every inactivity tick, leaderboard query, and stats page hit.
2. **Repeated heavy DB work in hot paths** -- trait recomputation is O(N^2) per race finish; zone stats page loads the entire history without filtering; per-status-update full participant reloads.
3. **In-process global state** -- the `ConnectionManager` singleton in `websocket/manager.py` makes horizontal scaling impossible; inactivity monitor and chat cleanup run in-process.

No memory leaks, no lock contention, no broken async boundaries were found. Broadcast serialization is already done once per message (not per-connection, an earlier hypothesis that turned out false on re-check).

---

## Findings

Severity scale: **Critical** (will break under load), **High** (degrades UX at scale), **Medium** (wastes resources), **Low** (cleanup).

### CRITICAL

#### C1 -- Admin analytics loads 4 full tables on every dashboard hit

`services/analytics_service.py:64-69`

> **DONE** (commit 9b787f3). KPIs replaced with `func.count()` aggregate queries. Raw data loads windowed to 13 weeks for weekly/heatmap/timezone sections.

```python
users: list[User] = list((await db.execute(select(User))).scalars().all())
races: list[Race] = list((await db.execute(select(Race))).scalars().all())
participants: list[Participant] = list((await db.execute(select(Participant))).scalars().all())
training_sessions: list[TrainingSession] = list((await db.execute(...)).scalars().all())
```

No `WHERE`, no `LIMIT`. All aggregation is done in Python. Called by `GET /api/admin/analytics` (admin.py:151).

**Impact at reference load:** ~60 MB of ORM objects loaded per call. If an admin dashboard auto-refreshes every 30s with 2 admins viewing, that is ~240 MB/minute of object churn and 4 full-table scans per 30s. Connection pool and GC will spike.

---

#### C2 -- `GET /stats/zones` loads every eligible participant ever

`api/stats.py:328-353`

> **PARTIALLY DONE** (commit d09ab1b). Items 1 and 3 implemented: `?days=90` query parameter added (default 90, range 1..3650); output was already capped at 5 entries per category. Item 2 (persistent cache) deferred.

```python
query = (
    select(Participant)
    .where(or_(Participant.status == FINISHED,
               (Participant.status == ABANDONED) & (Participant.igt_ms > 0)))
    .options(selectinload(Participant.race).selectinload(Race.seed))
)
participants = (await db.execute(query)).scalars().all()
```

Then iterates all participants, merges zones by display name, computes backtracks. No pagination, no date filter, no result cap.

**Impact at reference load:** ~50k participant rows + full Race + full Seed.graph_json eager-loaded. `graph_json` is a large JSON blob per seed (hundreds of nodes), and eager loading through participant.race.seed pulls it all. Single request easily exceeds 100 MB. Hit by unauthenticated spectators on `/stats`.

**Remaining work:**

- P2.1: Persistent cache for zone stats (hourly background rebuild, `zone_stats_cache` table or in-memory TTL dict). Would make `/stats/zones` O(1).

---

### HIGH

#### H1 -- Missing indexes on hot filter columns

`models.py` (entire file)

> **DONE** (commits f39718b, eb8f168). New indexes: `ix_participants_status_igt_change`, `ix_races_started_at`, `ix_chat_messages_user`. Existing indexes from initial schema (`ix_races_status`, `ix_seeds_pool_status`) and from migration 163dac67f6db (`ix_participants_user_race_status`, `ix_participants_race_user`, `ix_races_organizer`, `ix_training_sessions_user_status`) declared in models.py for autogenerate sync.

Only 2 explicit indexes exist (`ix_elo_history_user_created`, `ix_chat_messages_race_channel_created`). Missing on heavily filtered columns:

| Table           | Missing index                  | Used by                                  |
| --------------- | ------------------------------ | ---------------------------------------- |
| `participants`  | `(status, last_igt_change_at)` | inactivity_monitor.py:39-56 (every 60s)  |
| `participants`  | `(race_id, status)`            | broadcast leaderboard, all race queries  |
| `participants`  | `(user_id, status)`            | stats_service trait recomputation        |
| `races`         | `(status)`                     | running-race queries, inactivity monitor |
| `races`         | `(started_at)`                 | date-range aggregations, analytics       |
| `races`         | `(is_public, status)`          | public races listing in races.py         |
| `seeds`         | `(pool_name, status)`          | seed selection (seed_service)            |
| `chat_messages` | user_id FK                     | user-scoped chat queries                 |

**Impact at reference load:** Inactivity monitor runs every 60s and filters `Participant.status IN (...)` against 50k rows. Without an index, that is a seq-scan every minute, forever. On PostgreSQL with a cold buffer cache, this is a few hundred ms per tick. With 50 concurrent running races triggering broadcast queries, inactivity scans will contend with status updates.

---

#### H2 -- Trait recomputation is O(races x participants) per race finish

`services/stats_service.py:286-302` and `:317-335`

> **PARTIALLY DONE** (commits d478107, 483f674). Item 1 implemented: `update_player_traits` + `resolve_dominant_traits` moved to a background `asyncio.create_task` with its own DB session. Serialized via `asyncio.Lock` to prevent concurrent `resolve_dominant_traits` from corrupting global percentile rankings. Items 2 (incremental scoring) and 3 (batch SQL) deferred.

```python
async def update_player_traits(race_id, db):
    race = await db.get(Race, race_id, options=[selectinload(Race.participants)])
    user_ids = [p.user_id for p in race.participants if ...]
    for user_id in user_ids:
        await _recompute_traits_for_user(user_id, db)   # one call per user
```

And inside `_recompute_traits_for_user`:

```python
all_participations = (await db.execute(
    select(Participant)
    .where(Participant.user_id == user_id, Participant.status == FINISHED)
    .options(
        selectinload(Participant.race).selectinload(Race.participants),
        selectinload(Participant.race).selectinload(Race.seed),
    )
)).scalars().all()
```

For each user in the finishing race, we reload **all their past finished races**, with all participants of those races, and all seeds. A user with 50 prior races triggers ~50 races' worth of eager-loaded participants and large `graph_json` blobs.

**Impact at reference load:** 20-person race finish => 20 `_recompute_traits_for_user` calls. Each user with ~50 prior races => ~50 Race rows + full participants eager load per call. That is ~1,000 Race loads, millions of graph_json bytes. Now runs in background so the HTTP response is fast, but DB load still exists.

**Remaining work:**

- P3.3: Incremental trait scoring (per-race trait contribution table, aggregate on read). Would eliminate the full-history rescan.

---

#### H3 -- Inactivity monitor opens 3 DB sessions per affected race

`services/inactivity_monitor.py:38-85` and `:104-143`

> **DONE** (commit 823102a). Merged auto-finish check + broadcast into a single session per affected race. Session count per tick reduced from 1+2N to 1+N.

Per monitor tick, for each race with abandonments:

1. Session 1: load stale participants + their Race + Race.participants (lines 38-56).
2. Session 2: reload Race with participants to check auto-finish (lines 76-83).
3. Session 3: reload Race with participants + user + casters + seed for the broadcast (lines 105-114).

Three sessions opened, three separate transactions, three round-trips for data that overlaps significantly.

**Impact at reference load:** At 50 races and say 5 with abandonments per tick, that is 15 session creations per minute on top of the main flow. Not catastrophic, but unnecessary connection churn.

---

#### H4 -- `manager` is an in-process singleton

`websocket/manager.py:623` (`manager = ConnectionManager()`)

> **DONE** (commit 5279bcf). Scaling section added to `docs/WEBSOCKET_LIFECYCLE.md` documenting the constraint and Redis pub/sub path forward.

The connection manager holds all WebSocket rooms and connections in a single Python dict: `self.rooms: dict[uuid.UUID, RaceRoom]`. Mod state, spectator state, leaderboard broadcasts all live in process memory.

**Impact at reference load:** This is fine vertically (a single FastAPI worker can handle thousands of WS connections). But it blocks horizontal scaling, you cannot add a second uvicorn worker or a second server instance without a pub/sub bus. If memory or CPU on the single process saturates, there is no straightforward scale-out path.

**Remaining work:**

- P3.2: Redis pub/sub for WS broadcasts when horizontal scaling becomes necessary.

---

### MEDIUM

#### M1 -- Every `status_update` triggers a full participant reload

`websocket/mod.py:426-515`

> **PARTIALLY DONE** (commit 2f03c53). graph_json cached at connect time and passed to `handle_status_update`. Common path (no death, no became_playing) now uses `_load_participant_no_seed` (skips race.seed eager-load). Uncommon path (leaderboard/death broadcast) still does a full reload. Full per-connection caching of race.participants was not viable because participant data (igt_ms, layer, zone_history) changes every tick.

```python
async with session_maker() as db:
    participant = await _load_participant_light(db, participant_id)
    # ...update + commit...
    await db.commit()

# Then, if became_playing or delta>0:
async with session_maker() as db:
    participant = await _load_participant(db, participant_id)  # 5+ joins
```

`_load_participant` eager-loads participant -> user, race -> seed, race -> all participants -> all users, race -> casters -> all users. Done on every IGT tick that bumps delta.

**Impact at reference load:** 20 participants x 30 zones x (maybe) 1-2 death updates = ~1,000 heavy reloads per race. Each reload touches 5+ tables. At 50 races: ~50k reloads per race run. Largest avoidable DB load in the system.

**Remaining work:**

- M2 (delta leaderboard) would reduce the number of broadcasts that trigger the heavy reload path.

---

#### M2 -- Leaderboard broadcast payload is ~5 KB x every broadcast

`websocket/manager.py:303-357`

> **NOT DONE.** Deferred to a later phase.

Good news: the JSON payload is serialized **once** per broadcast (`message.model_dump_json()` at line 357, then passed as string to every socket). Zone history is correctly excluded by default (`include_zone_history=False`, see manager.py:537-545).

Remaining issue: each `ParticipantInfo` still includes twitch_display_name, avatar_url, is_live, stream_url, gap_ms, layer_entry_igt, etc., 15+ fields x 20 participants x every broadcast.

**Impact at reference load:** ~5 KB x 20 broadcasts/min/race x 100 spectators x 50 races = ~500 MB/min egress.

**Remaining work:**

- Split into two message types: **full snapshot** on connect + on status transitions, **delta** on routine ticks (just `{participant_id, igt_ms, current_layer, current_zone, gap_ms}`). Cuts broadcast payload by ~80%.

---

#### M3 -- Zone stats merge uses O(N) lookups in `node_seed_date` tracking

`api/stats.py:288-325` and `:355-415` (the build function)

> **DONE** implicitly by C2 (the 90-day window caps the input dataset).

The zone merging step iterates `seen_nids` and does string-keyed dict merges. Combined with the full-history load in C2, this is the dominant CPU cost of `/stats/zones`.

**Impact at reference load:** Once C2 is fixed (cached aggregates), this disappears. Low value to optimize in isolation.

---

#### M4 -- `broadcast_to_spectators` waits on slowest spectator (up to 5s)

`websocket/manager.py:87-108`

> **NOT DONE.** Deferred (low effort/impact ratio at current scale).

```python
results = await asyncio.gather(*(_send(c) for c in snapshot))
```

`_send` has `asyncio.wait_for(..., timeout=SEND_TIMEOUT=5s)`. `gather` waits for all futures. A next broadcast queued behind it will start 5s late if one spectator stalls.

**Impact at reference load:** With 100 spectators per room, statistically some will stall. Leaderboard updates arrive late to everyone when one spectator is slow.

**Remaining work:**

- P3.1: Per-connection async send queue (fire-and-forget broadcasts, backpressure per client). ~2 days.

---

#### M5 -- `get_layer_entry_igt` scans full zone_history per participant per broadcast

`websocket/manager.py:598-602` (caller) and `utils` (callee)

> **DONE** (commit b0cd5ed). `layer_entry_igts` JSON column added to Participant, populated at the 5 sites where `current_layer` changes via `_set_layer` helper (first-write-wins). `sort_leaderboard` reads the cache first, falls back to the legacy scan for pre-migration rows.

`sort_leaderboard` calls `get_layer_entry_igt(p.zone_history, p.current_layer, graph_json)` for each participant. The callee does a linear scan of zone_history looking for the first entry at `current_layer`.

**Impact at reference load:** 20 participants x 30 history entries x every broadcast x many broadcasts. Not CPU-bound, but pure overhead.

---

#### M6 -- Spectator chat history issues a second query for trait scores

`websocket/spectator.py:95-131`

> **DONE** (commit c486c29). `outerjoin(PlayerTraitScores)` folded into the chat history query. Single round-trip.

```python
# Query 1: chat messages + users (join)
result = await db.execute(select(ChatMessageModel, User).join(User, ...)...)
rows = list(reversed(result.all()))
# Query 2: trait scores for those users
trait_results = await db.execute(select(PlayerTraitScores).where(...in_(user_ids)))
```

Two queries. With spectators connecting at rate, this doubles the chat-history query load.

**Impact at reference load:** A burst of 100 spectators connecting to a race = 200 DB queries (2 per connect) just for chat history + traits.

---

### LOW

#### L1 -- Mod authentication eager-loads the full race tree

`websocket/mod.py:319-328`

> **NOT DONE.** Left as-is; the caller needs the full tree immediately after auth for the connect broadcast, so a two-step load would not save a round-trip.

`authenticate_mod` applies the full `_participant_load_options()` chain (participant -> user, race -> seed, race -> all participants -> users, race -> casters -> users) just to verify a token. The heavy load is only needed after auth succeeds.

---

#### L2 -- Mod disconnect re-loads participant for the farewell broadcast

`websocket/mod.py:305-316`

> **DONE** (commit 97bac1e). Disconnect handler now uses `_load_race_participants` (Race.participants + users only) with the connect-time `graph_json` cached. Skips seed + casters eager loads.

On disconnect we open a new session and reload the participant to broadcast connection status. Full reload is needed because other participants' data (igt_ms, layer) changes during the session, but the seed and casters are not needed.

---

#### L3 -- `_pattern_regex_cache` in i18n service is unbounded

`services/i18n.py:249`

> **DONE** (commit c67e50d). Replaced with `@lru_cache(maxsize=256)`.

```python
_pattern_regex_cache: dict[str, re.Pattern[str]] = {}
```

Dict grows forever as new translation patterns are seen. Not a problem today (fixed template set), but worth noting.

---

#### L4 -- Rate limiting is in-process only

`rate_limit.py`

> **NOT DONE.** Same horizontal-scaling constraint as H4. No action until multi-worker deployment is needed.

Rate limit state lives in the process. Same horizontal-scaling constraint as H4, same impact (zero until you actually need multiple workers).

---

## False alarms checked

These looked suspicious but are fine:

- **`races.py:460-465` count-then-fetch pagination** -- standard pattern, count is a subquery, PostgreSQL optimizes well.
- **`api/stats.py:59` `.all()` on User leaderboard** -- `WHERE elo_races >= 3` bounds the result at a few hundred rows.
- **`broadcast_to_all` "serializes per-connection"** -- it does not. The string is built once and passed to sockets as-is.
- **Zone history stored as JSON column (not normalized)** -- appropriate given the access pattern (always read as a whole, rarely queried by substructure).
- **No connection pooling config** -- SQLAlchemy async defaults (pool_size=5, max_overflow=10) are fine for single-worker deployments at current scale; revisit when horizontal scaling happens.

---

## Action plan

### Implemented (2026-04-06)

| Item | Finding                                                             | Commit           |
| ---- | ------------------------------------------------------------------- | ---------------- |
| P1.1 | H1: Composite DB indexes                                            | f39718b, eb8f168 |
| P1.2 | C2: `/stats/zones` date filter (90d default)                        | d09ab1b          |
| P1.3 | C1: Analytics SQL aggregates + 13-week window                       | 9b787f3          |
| P1.4 | H2: Background trait recomputation + asyncio.Lock                   | d478107, 483f674 |
| P1.5 | H3: Inactivity monitor session consolidation                        | 823102a          |
| P2.3 | M1: graph_json cached per WS connection                             | 2f03c53          |
| P2.4 | M5: `layer_entry_igts` precomputed on Participant                   | b0cd5ed          |
| P2.5 | M6: Chat history outerjoin on PlayerTraitScores                     | c486c29          |
| P4.2 | L2: Lightweight disconnect broadcast                                | 97bac1e          |
| P4.3 | L3: lru_cache on regex cache                                        | c67e50d          |
| --   | H4: Document WS single-process constraint                           | 5279bcf          |
| --   | Code review fixes (task ref, dead code, em dash, model consistency) | 5d82765          |
| --   | Regression fixes (asyncio.Lock, `is not None` check)                | 483f674          |
| --   | Migration fix (duplicate indexes from initial schema)               | eb8f168          |

### Remaining work

| Item | Finding                                                 | Effort | Priority                                       |
| ---- | ------------------------------------------------------- | ------ | ---------------------------------------------- |
| P2.1 | C2: Persistent cache for zone stats (hourly rebuild)    | 1d     | Next if /stats/zones shows load                |
| P2.2 | M2: Leaderboard delta messages (snapshot + delta split) | 1-2d   | Next if WS bandwidth is a concern              |
| P3.1 | M4: Per-connection async send queue (backpressure)      | 2d     | When slow spectators cause latency             |
| P3.2 | H4 + L4: Redis pub/sub + distributed rate limits        | 3-5d   | When horizontal scaling is needed              |
| P3.3 | H2: Incremental trait scoring (contribution table)      | 2-3d   | When trait recomputation DB load is measurable |

L1 (lightweight auth) was evaluated and left as-is: the caller needs the full tree immediately after auth for the connect broadcast.

---

## Benchmark suggestions

Before and after the implemented changes, add these measurements to CI or run manually:

1. `EXPLAIN ANALYZE` on the inactivity monitor's `SELECT` against a populated DB -- verify index usage after H1.
2. Hit `GET /api/admin/analytics` with timing -- compare before/after C1 on the prod dump.
3. Load test script: WebSocket client pool simulating 100 spectators + 20 mods in a single race, measure end-to-end broadcast latency (mod send -> spectator receive).

These are worth writing as a `server/tests/test_perf.py` marked `@pytest.mark.perf` and excluded from the default test run.

---

## Notes

- No findings in `auth.py`, `rate_limit.py`, `schemas.py`, `discord.py`, `twitch_live.py` -- these look fine.
- `race_lifecycle.py` and `zone_resolver.py` were scanned briefly, nothing flagged.
- This audit did not examine the frontend (SvelteKit) nor the Rust mod, per scope.
- No runtime profiling was performed -- all findings are static. The remaining items should be validated with real measurements before implementation.

---

## Summary (2026-04-06)

| #   | Severity | Finding                                       | Status     | Comment                                                                                                              |
| --- | -------- | --------------------------------------------- | ---------- | -------------------------------------------------------------------------------------------------------------------- |
| C1  | Critical | Analytics full-table scans                    | Done       | KPIs via `func.count()`, raw loads windowed to 13 weeks                                                              |
| C2  | Critical | `/stats/zones` unbounded load                 | Partial    | `?days=90` filter added; persistent cache (P2.1) deferred                                                            |
| H1  | High     | Missing composite indexes                     | Done       | 3 new indexes + 6 existing declared in models.py                                                                     |
| H2  | High     | Trait recomputation O(N^2) on finish          | Partial    | Moved to background task with `asyncio.Lock`; incremental scoring (P3.3) deferred                                    |
| H3  | High     | Inactivity monitor 3 sessions/race            | Done       | Merged auto-finish + broadcast into 1 session/race                                                                   |
| H4  | High     | In-process WS singleton                       | Documented | Scaling section in WEBSOCKET_LIFECYCLE.md; Redis pub/sub (P3.2) deferred                                             |
| M1  | Medium   | Full participant reload per tick              | Partial    | graph_json cached per connection, seed load skipped on common path; full reload still needed on death/became_playing |
| M2  | Medium   | Leaderboard broadcast payload size            | Not done   | Delta messages (P2.2) deferred                                                                                       |
| M3  | Medium   | Zone stats merge O(N)                         | Done       | Fixed implicitly by C2 (90-day window caps input)                                                                    |
| M4  | Medium   | Broadcast waits on slowest spectator          | Not done   | Per-connection send queue (P3.1) deferred                                                                            |
| M5  | Medium   | `get_layer_entry_igt` O(N) scan per broadcast | Done       | `layer_entry_igts` JSON column, populated on layer change, O(1) lookup with fallback                                 |
| M6  | Medium   | Chat history 2 queries for traits             | Done       | Single query via `outerjoin(PlayerTraitScores)`                                                                      |
| L1  | Low      | Auth eager-loads full race tree               | Won't fix  | Caller needs the full tree right after auth for connect broadcast                                                    |
| L2  | Low      | Disconnect reloads full participant           | Done       | Lightweight `_load_race_participants` + cached graph_json                                                            |
| L3  | Low      | Unbounded regex cache                         | Done       | `@lru_cache(maxsize=256)`                                                                                            |
| L4  | Low      | In-process rate limiting                      | Not done   | Same constraint as H4; deferred until multi-worker                                                                   |

**10 of 16 findings resolved, 3 partially resolved, 2 deferred, 1 won't fix.**
