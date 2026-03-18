# Global Stats Page Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a public `/stats` page with ELO leaderboard, zone/boss analytics, and behavioral player profiles, plus a "Play Style" section on user profile pages.

**Architecture:** New `services/stats_service.py` for ELO and trait computation, new `api/stats.py` for public endpoints, new DB models (`EloHistory`, `PlayerTraitScores`) + columns on `User`. Frontend: new `/stats` route with 4 tabs, updated profile page. ELO computed incrementally at race finish; zone/boss stats aggregated on the fly.

**Tech Stack:** Python/FastAPI, SQLAlchemy 2.0 async, Pydantic v2, SvelteKit 5 with runes, TypeScript

**Spec:** `docs/specs/2026-03-18-global-stats-page.md`

---

## File Structure

### Server (new files)

- `server/speedfog_racing/services/stats_service.py` -- ELO algorithm, trait scoring, zone/boss aggregation, admin recalc
- `server/speedfog_racing/api/stats.py` -- Public stats API routes (`/api/stats/*`)
- `server/tests/test_elo.py` -- ELO algorithm unit tests
- `server/tests/test_traits.py` -- Trait scoring unit tests
- `server/tests/test_stats_api.py` -- Stats API integration tests

### Server (modified files)

- `server/speedfog_racing/models.py` -- Add `EloHistory`, `PlayerTraitScores` models; add `elo_rating`, `elo_races` to `User`
- `server/speedfog_racing/schemas.py` -- Add Pydantic response schemas for stats endpoints
- `server/speedfog_racing/api/__init__.py` -- Mount stats router
- `server/speedfog_racing/api/races.py` -- Call stats update on race finish
- `server/speedfog_racing/services/race_lifecycle.py` -- Call stats update on auto-finish
- `server/speedfog_racing/api/admin.py` -- Add recalculate endpoint
- `server/speedfog_racing/api/users.py` -- Add `/users/{username}/traits` endpoint

### Frontend (new files)

- `web/src/routes/stats/+page.svelte` -- Stats page with 4 tabs
- `web/src/lib/components/stats/LeaderboardTab.svelte` -- ELO leaderboard tab
- `web/src/lib/components/stats/ZonesTab.svelte` -- Zone analytics tab
- `web/src/lib/components/stats/BossesTab.svelte` -- Boss analytics tab
- `web/src/lib/components/stats/PlayersTab.svelte` -- Player profiles tab
- `web/src/lib/components/PlayStyle.svelte` -- Play Style card (shared between stats page and profile)

### Frontend (modified files)

- `web/src/lib/api.ts` -- Add stats types and fetch functions
- `web/src/routes/+layout.svelte` -- Add Stats link to navbar
- `web/src/routes/user/[username]/+page.svelte` -- Add Play Style section

---

## Chunk 1: Data Models & ELO Algorithm

### Task 1: Add new DB models and User columns

**Files:**

- Modify: `server/speedfog_racing/models.py`

- [ ] **Step 1: Add EloHistory model and PlayerTraitScores model to models.py**

After the existing `Invite` model (end of file), add the following. Also add `Index` and `Float` to the `sqlalchemy` imports at the top of the file.

```python
class EloHistory(Base):
    __tablename__ = "elo_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    race_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("races.id"), nullable=False)
    elo_before: Mapped[float] = mapped_column(nullable=False)
    elo_after: Mapped[float] = mapped_column(nullable=False)
    delta: Mapped[float] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    __table_args__ = (
        Index("ix_elo_history_user_created", "user_id", "created_at"),
    )


class PlayerTraitScores(Base):
    __tablename__ = "player_trait_scores"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), primary_key=True
    )
    dominant_trait: Mapped[str | None] = mapped_column(nullable=True)
    rusher: Mapped[int] = mapped_column(default=0)
    cautious: Mapped[int] = mapped_column(default=0)
    resilient: Mapped[int] = mapped_column(default=0)
    rage_quitter: Mapped[int] = mapped_column(default=0)
    explorer: Mapped[int] = mapped_column(default=0)
    pathfinder: Mapped[int] = mapped_column(default=0)
    boss_slayer: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
```

Add imports at top: `Index` from `sqlalchemy`.

- [ ] **Step 2: Add elo_rating and elo_races columns to User model**

In the `User` class (after `last_seen` at line 81), add:

```python
    elo_rating: Mapped[float] = mapped_column(default=1500.0)
    elo_races: Mapped[int] = mapped_column(default=0)
```

- [ ] **Step 3: Run the test suite to verify models load**

Run: `cd server && uv run pytest tests/test_health.py -v`
Expected: PASS (tables are created from metadata, so new models are validated)

- [ ] **Step 4: Commit**

```bash
git add server/speedfog_racing/models.py
git commit -m "feat: add EloHistory, PlayerTraitScores models and User ELO columns"
```

### Task 2: ELO algorithm core (pure functions)

**Files:**

- Create: `server/speedfog_racing/services/stats_service.py`
- Create: `server/tests/test_elo.py`

- [ ] **Step 1: Write failing tests for ELO computation**

Create `server/tests/test_elo.py`:

```python
"""Tests for ELO algorithm."""

import pytest

from speedfog_racing.services.stats_service import compute_elo_deltas


class TestComputeEloDeltas:
    """Test the pure ELO delta computation function."""

    def test_two_players_equal_rating_close_finish(self):
        """Close finish between equal players: minimal change."""
        players = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 3_000_000, "finished": True},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 3_005_000, "finished": True},
        ]
        deltas = compute_elo_deltas(players)
        # Close finish (5s gap), equal ratings: very small delta
        assert deltas["a"] > 0
        assert deltas["b"] < 0
        assert abs(deltas["a"]) < 5.0  # Should be small

    def test_two_players_equal_rating_large_gap(self):
        """Large gap between equal players: significant change."""
        players = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 2_000_000, "finished": True},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 3_500_000, "finished": True},
        ]
        deltas = compute_elo_deltas(players)
        # 25 min gap on ~46 min median: large delta
        assert deltas["a"] > 10.0
        assert deltas["b"] < -10.0

    def test_higher_rated_player_wins_small_change(self):
        """Favorite winning gives less ELO than an upset."""
        players = [
            {"user_id": "a", "elo": 1800.0, "igt_ms": 2_000_000, "finished": True},
            {"user_id": "b", "elo": 1200.0, "igt_ms": 3_500_000, "finished": True},
        ]
        deltas = compute_elo_deltas(players)
        assert deltas["a"] > 0  # Winner gains
        assert deltas["a"] < 10.0  # But not much (expected win)

    def test_upset_large_change(self):
        """Lower-rated player winning gives more ELO."""
        players = [
            {"user_id": "a", "elo": 1200.0, "igt_ms": 2_000_000, "finished": True},
            {"user_id": "b", "elo": 1800.0, "igt_ms": 3_500_000, "finished": True},
        ]
        deltas = compute_elo_deltas(players)
        assert deltas["a"] > 20.0  # Big gain for upset

    def test_three_players(self):
        """Three-player race: sum of deltas is zero."""
        players = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 2_000_000, "finished": True},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 2_500_000, "finished": True},
            {"user_id": "c", "elo": 1500.0, "igt_ms": 3_000_000, "finished": True},
        ]
        deltas = compute_elo_deltas(players)
        assert abs(sum(deltas.values())) < 0.01  # Zero-sum
        assert deltas["a"] > deltas["b"] > deltas["c"]

    def test_abandoned_player_loses_max(self):
        """Abandoned player (igt_ms > 0) loses to all finishers."""
        players = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 2_500_000, "finished": True},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 100_000, "finished": False},
        ]
        deltas = compute_elo_deltas(players)
        assert deltas["a"] > 0
        assert deltas["b"] < 0
        # Abandon = S=0 for abandoner, should be max loss for equal rating
        assert deltas["b"] < -10.0

    def test_single_player_no_change(self):
        """Single player: no pairwise comparisons, no change."""
        players = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 2_500_000, "finished": True},
        ]
        deltas = compute_elo_deltas(players)
        assert deltas == {"a": 0.0}

    def test_two_abandoned_players(self):
        """Two abandoned players: both get S=0 against each other (draw)."""
        players = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 100_000, "finished": False},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 200_000, "finished": False},
        ]
        deltas = compute_elo_deltas(players)
        # Both abandoned with equal rating: zero change
        assert abs(deltas["a"]) < 0.01
        assert abs(deltas["b"]) < 0.01
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_elo.py -v`
Expected: FAIL (ImportError, `compute_elo_deltas` does not exist)

- [ ] **Step 3: Implement compute_elo_deltas**

Create `server/speedfog_racing/services/stats_service.py`:

```python
"""Stats computation: ELO ratings and behavioral traits."""

from statistics import median
from typing import Any

K_FACTOR = 32
STARTING_ELO = 1500.0
MIN_RACES_FOR_DISPLAY = 3
DOMINANT_TRAIT_THRESHOLD = 40


def compute_elo_deltas(
    players: list[dict[str, Any]],
) -> dict[str, float]:
    """Compute ELO rating changes for all players in a race.

    Each player dict must have: user_id, elo, igt_ms, finished (bool).
    Players with finished=False are treated as abandoned (S=0 against finishers).
    Returns a dict mapping user_id to delta (float).
    """
    n = len(players)
    if n < 2:
        return {p["user_id"]: 0.0 for p in players}

    finisher_igts = [p["igt_ms"] for p in players if p["finished"]]
    if finisher_igts:
        ref_time = median(finisher_igts) * 0.3
    else:
        ref_time = 1.0  # Avoid division by zero; all abandoned

    deltas: dict[str, float] = {p["user_id"]: 0.0 for p in players}

    for i in range(n):
        for j in range(i + 1, n):
            a, b = players[i], players[j]
            # Expected scores
            ea = 1.0 / (1.0 + 10.0 ** ((b["elo"] - a["elo"]) / 400.0))
            eb = 1.0 - ea

            # Actual scores with margin of victory
            sa, sb = _actual_scores(a, b, ref_time)

            # Accumulate pairwise deltas
            deltas[a["user_id"]] += K_FACTOR * (sa - ea)
            deltas[b["user_id"]] += K_FACTOR * (sb - eb)

    # Normalize by (N-1) pairwise comparisons per player
    for uid in deltas:
        deltas[uid] /= n - 1

    return deltas


def _actual_scores(
    a: dict[str, Any], b: dict[str, Any], ref_time: float
) -> tuple[float, float]:
    """Compute actual scores for a pair with margin of victory."""
    a_fin, b_fin = a["finished"], b["finished"]

    if a_fin and b_fin:
        gap = abs(a["igt_ms"] - b["igt_ms"])
        margin = min(gap / ref_time, 1.0) if ref_time > 0 else 0.0
        if a["igt_ms"] <= b["igt_ms"]:
            return 0.5 + 0.5 * margin, 0.5 - 0.5 * margin
        else:
            return 0.5 - 0.5 * margin, 0.5 + 0.5 * margin
    elif a_fin and not b_fin:
        return 1.0, 0.0
    elif not a_fin and b_fin:
        return 0.0, 1.0
    else:
        # Both abandoned: draw
        return 0.5, 0.5
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_elo.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add server/speedfog_racing/services/stats_service.py server/tests/test_elo.py
git commit -m "feat: ELO algorithm with margin-of-victory scoring"
```

### Task 3: ELO database integration (update_elo_ratings)

**Files:**

- Modify: `server/speedfog_racing/services/stats_service.py`
- Create: `server/tests/test_stats_api.py` (start with ELO integration)

- [ ] **Step 1: Write failing test for update_elo_ratings**

Create `server/tests/test_stats_api.py`:

```python
"""Integration tests for stats service and API."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    EloHistory,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.services.stats_service import update_elo_ratings


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def finished_race(async_session):
    """Create a finished race with 3 participants (2 finished, 1 abandoned)."""
    async with async_session() as db:
        users = []
        for i in range(3):
            u = User(
                twitch_id=f"u{i}",
                twitch_username=f"player{i}",
                api_token=f"tok{i}",
                role=UserRole.USER,
            )
            users.append(u)
        organizer = User(
            twitch_id="org",
            twitch_username="organizer",
            api_token="tok_org",
            role=UserRole.ORGANIZER,
        )
        db.add_all([*users, organizer])
        await db.flush()

        seed = Seed(
            seed_number="s1",
            pool_name="standard",
            graph_json={"nodes": {}, "total_layers": 5},
            total_layers=5,
            folder_path="/test/s1",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Test Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        participants = [
            Participant(
                race_id=race.id,
                user_id=users[0].id,
                mod_token="mt0",
                status=ParticipantStatus.FINISHED,
                igt_ms=2_000_000,
                death_count=10,
            ),
            Participant(
                race_id=race.id,
                user_id=users[1].id,
                mod_token="mt1",
                status=ParticipantStatus.FINISHED,
                igt_ms=2_800_000,
                death_count=15,
            ),
            Participant(
                race_id=race.id,
                user_id=users[2].id,
                mod_token="mt2",
                status=ParticipantStatus.ABANDONED,
                igt_ms=500_000,
                death_count=5,
            ),
        ]
        db.add_all(participants)
        await db.commit()

        return race.id, [u.id for u in users]


class TestUpdateEloRatings:
    async def test_updates_user_elo_after_race(self, async_session, finished_race):
        race_id, user_ids = finished_race
        async with async_session() as db:
            await update_elo_ratings(race_id, db)

        async with async_session() as db:
            for uid in user_ids:
                user = await db.get(User, uid)
                assert user.elo_races == 1
            # Winner should have gained
            winner = await db.get(User, user_ids[0])
            assert winner.elo_rating > 1500.0
            # Abandoner should have lost
            abandoner = await db.get(User, user_ids[2])
            assert abandoner.elo_rating < 1500.0

    async def test_creates_elo_history_entries(self, async_session, finished_race):
        race_id, user_ids = finished_race
        async with async_session() as db:
            await update_elo_ratings(race_id, db)

        async with async_session() as db:
            entries = (await db.execute(select(EloHistory))).scalars().all()
            assert len(entries) == 3  # One per rated player

    async def test_idempotent(self, async_session, finished_race):
        race_id, user_ids = finished_race
        async with async_session() as db:
            await update_elo_ratings(race_id, db)
        async with async_session() as db:
            await update_elo_ratings(race_id, db)

        async with async_session() as db:
            entries = (await db.execute(select(EloHistory))).scalars().all()
            assert len(entries) == 3  # Still 3, not 6

    async def test_skips_non_playing_abandoned(self, async_session):
        """Abandoned with igt_ms=0 should be excluded."""
        async with async_session() as db:
            users = [
                User(twitch_id=f"t{i}", twitch_username=f"p{i}", api_token=f"t{i}", role=UserRole.USER)
                for i in range(2)
            ]
            org = User(twitch_id="org2", twitch_username="org2", api_token="to2", role=UserRole.ORGANIZER)
            db.add_all([*users, org])
            await db.flush()
            seed = Seed(seed_number="s2", pool_name="standard", graph_json={"nodes": {}}, total_layers=3, folder_path="/t/s2", status=SeedStatus.CONSUMED)
            db.add(seed)
            await db.flush()
            race = Race(name="R2", organizer_id=org.id, seed_id=seed.id, status=RaceStatus.FINISHED, started_at=datetime.now(UTC))
            db.add(race)
            await db.flush()
            db.add(Participant(race_id=race.id, user_id=users[0].id, mod_token="m0", status=ParticipantStatus.FINISHED, igt_ms=2_000_000, death_count=5))
            db.add(Participant(race_id=race.id, user_id=users[1].id, mod_token="m1", status=ParticipantStatus.ABANDONED, igt_ms=0, death_count=0))
            await db.commit()
            rid = race.id
            uid_finished = users[0].id
            uid_abandoned = users[1].id

        async with async_session() as db:
            await update_elo_ratings(rid, db)

        async with async_session() as db:
            finished_user = await db.get(User, uid_finished)
            abandoned_user = await db.get(User, uid_abandoned)
            assert finished_user.elo_races == 0  # Only 1 eligible, no pairs
            assert abandoned_user.elo_races == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_stats_api.py -v`
Expected: FAIL (ImportError, `update_elo_ratings` does not exist)

- [ ] **Step 3: Implement update_elo_ratings in stats_service.py**

Add to `server/speedfog_racing/services/stats_service.py`:

```python
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.models import (
    EloHistory,
    Participant,
    ParticipantStatus,
    Race,
    User,
)

logger = logging.getLogger(__name__)


async def update_elo_ratings(race_id: Any, db: AsyncSession) -> None:
    """Compute and persist ELO changes for a finished race. Idempotent."""
    # Check if already computed
    existing = await db.execute(
        select(EloHistory.id).where(EloHistory.race_id == race_id).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        return

    # Load race with participants
    race = await db.get(Race, race_id, options=[selectinload(Race.participants)])
    if race is None:
        return

    # Build player list: FINISHED + ABANDONED with igt_ms > 0
    players = []
    for p in race.participants:
        if p.status == ParticipantStatus.FINISHED:
            players.append({
                "user_id": p.user_id,
                "igt_ms": p.igt_ms,
                "finished": True,
            })
        elif p.status == ParticipantStatus.ABANDONED and p.igt_ms > 0:
            players.append({
                "user_id": p.user_id,
                "igt_ms": p.igt_ms,
                "finished": False,
            })

    if len(players) < 2:
        return  # No pairwise comparisons possible

    # Load current ELO for each player
    user_ids = [p["user_id"] for p in players]
    users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
    users_by_id = {u.id: u for u in users_result.scalars().all()}

    for p in players:
        p["elo"] = users_by_id[p["user_id"]].elo_rating

    deltas = compute_elo_deltas(players)

    # Apply deltas and create history
    for p in players:
        user = users_by_id[p["user_id"]]
        delta = deltas[p["user_id"]]
        elo_before = user.elo_rating
        user.elo_rating = elo_before + delta
        user.elo_races += 1
        db.add(EloHistory(
            user_id=user.id,
            race_id=race_id,
            elo_before=elo_before,
            elo_after=user.elo_rating,
            delta=delta,
        ))

    await db.commit()
```

Update the imports at top of the file (consolidate the `from typing import Any` already there).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_stats_api.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add server/speedfog_racing/services/stats_service.py server/tests/test_stats_api.py
git commit -m "feat: update_elo_ratings DB integration with idempotency"
```

### Task 4: Hook ELO into race finish paths

**Files:**

- Modify: `server/speedfog_racing/api/races.py:1236-1271`
- Modify: `server/speedfog_racing/services/race_lifecycle.py:13-45`

- [ ] **Step 1: Add ELO call to finish_race endpoint**

In `server/speedfog_racing/api/races.py`, add import at top:

```python
from speedfog_racing.services.stats_service import update_elo_ratings, update_player_traits
```

In the `finish_race` function, after the commit (line ~1259) and before the reload, add:

```python
        await update_elo_ratings(race_id, db)
        await update_player_traits(race_id, db)
```

Note: `update_player_traits` will be implemented in Task 6. For now, add a stub in stats_service.py:

```python
async def update_player_traits(race_id: Any, db: AsyncSession) -> None:
    """Placeholder: compute and persist trait scores for race participants."""
    pass
```

- [ ] **Step 2: Add ELO call to check_race_auto_finish**

In `server/speedfog_racing/services/race_lifecycle.py`, the function returns `True` when race transitions to FINISHED. The caller needs to trigger stats update. Since `check_race_auto_finish` takes a `db` session, add the call inside:

Add import:

```python
from speedfog_racing.services.stats_service import update_elo_ratings, update_player_traits
```

After the status is set to FINISHED (before the function returns `True`), add:

```python
        await update_elo_ratings(race.id, db)
        await update_player_traits(race.id, db)
```

- [ ] **Step 3: Run existing race lifecycle tests to verify no regression**

Run: `cd server && uv run pytest tests/test_race_lifecycle.py tests/test_races.py -v --timeout=30`
Expected: All existing tests PASS

- [ ] **Step 4: Commit**

```bash
git add server/speedfog_racing/api/races.py server/speedfog_racing/services/race_lifecycle.py server/speedfog_racing/services/stats_service.py
git commit -m "feat: hook ELO computation into both race finish paths"
```

---

## Chunk 2: Behavioral Traits

### Task 5: Trait scoring pure functions

**Files:**

- Modify: `server/speedfog_racing/services/stats_service.py`
- Create: `server/tests/test_traits.py`

- [ ] **Step 1: Write failing tests for trait computation**

Create `server/tests/test_traits.py`:

```python
"""Tests for behavioral trait scoring."""

import pytest

from speedfog_racing.services.stats_service import (
    compute_rusher_score,
    compute_cautious_score,
    compute_explorer_score,
    compute_pathfinder_score,
    compute_boss_slayer_score,
    compute_resilient_score,
    compute_rage_quitter_score,
)


class TestRusherScore:
    def test_fastest_with_most_deaths(self):
        """Player who finishes 1st but dies most scores high."""
        igts = [100, 200, 300]  # player is fastest
        deaths = [20, 10, 5]  # player dies most
        score = compute_rusher_score(igts, deaths, player_index=0)
        assert score > 0.8

    def test_slowest_with_fewest_deaths(self):
        """Player who finishes last but dies least scores 0."""
        igts = [300, 200, 100]  # player is slowest
        deaths = [5, 10, 20]  # player dies least
        score = compute_rusher_score(igts, deaths, player_index=0)
        assert score == 0.0

    def test_single_player(self):
        """Single player: no ranking possible."""
        score = compute_rusher_score([100], [5], player_index=0)
        assert score == 0.0


class TestCautiousScore:
    def test_few_deaths_but_slow(self):
        """Few deaths but slow: high cautious score."""
        igts = [300, 200, 100]
        deaths = [2, 10, 15]
        score = compute_cautious_score(igts, deaths, player_index=0)
        assert score > 0.8

    def test_fast_with_many_deaths(self):
        """Fast but many deaths: 0 cautious."""
        igts = [100, 200, 300]
        deaths = [20, 10, 5]
        score = compute_cautious_score(igts, deaths, player_index=0)
        assert score == 0.0


class TestExplorerScore:
    def test_high_coverage_high_backtrack(self):
        visited = {"a", "b", "c", "d", "e"}
        total_nodes = 6
        history = [
            {"node_id": "a"}, {"node_id": "b"}, {"node_id": "c"},
            {"node_id": "b"},  # backtrack
            {"node_id": "d"}, {"node_id": "e"},
        ]
        score = compute_explorer_score(visited, total_nodes, history)
        # coverage = 5/6 = 0.83, backtrack = 1/6 = 0.17
        # raw = 0.6*0.83 + 0.4*0.17 = 0.566
        assert 0.5 < score < 0.7

    def test_no_backtrack(self):
        visited = {"a", "b"}
        history = [{"node_id": "a"}, {"node_id": "b"}]
        score = compute_explorer_score(visited, 10, history)
        # coverage = 2/10 = 0.2, backtrack = 0
        assert 0.1 < score < 0.15


class TestPathfinderScore:
    def test_unique_path(self):
        player_nodes = {"a", "b", "c", "d"}
        others_nodes = {"a", "b"}
        score = compute_pathfinder_score(player_nodes, others_nodes)
        # unique = {c, d}, proportion = 2/4 = 0.5
        assert score == pytest.approx(0.5)

    def test_identical_paths(self):
        player_nodes = {"a", "b", "c"}
        others_nodes = {"a", "b", "c", "d"}
        score = compute_pathfinder_score(player_nodes, others_nodes)
        assert score == 0.0

    def test_empty_others(self):
        """Solo player: no others to compare, score 0."""
        score = compute_pathfinder_score({"a", "b"}, set())
        assert score == 0.0


class TestBossSlayerScore:
    def test_zero_deaths_on_hard_boss(self):
        """0 deaths vs avg 10 = perfect score."""
        player_boss_deaths = {"boss_a": 0}
        avg_boss_deaths = {"boss_a": 10.0}
        boss_weights = {"boss_a": 1.0}
        score = compute_boss_slayer_score(
            player_boss_deaths, avg_boss_deaths, boss_weights
        )
        assert score == pytest.approx(1.0)

    def test_average_deaths(self):
        """Equal to average = score 0."""
        player_boss_deaths = {"boss_a": 10}
        avg_boss_deaths = {"boss_a": 10.0}
        boss_weights = {"boss_a": 1.0}
        score = compute_boss_slayer_score(
            player_boss_deaths, avg_boss_deaths, boss_weights
        )
        assert score == pytest.approx(0.0)

    def test_no_bosses(self):
        score = compute_boss_slayer_score({}, {}, {})
        assert score == 0.0


class TestResilientScore:
    def test_always_finishes_far_behind(self):
        """100% completion, big gaps: high score."""
        finished_races = 10
        total_races = 10
        gap_ratios = [0.5, 0.6, 0.4, 0.7, 0.5, 0.3, 0.6, 0.5, 0.4, 0.5]
        score = compute_resilient_score(finished_races, total_races, gap_ratios)
        assert score > 60

    def test_leader_always(self):
        """Always wins: gap_ratio=0, low resilient score."""
        score = compute_resilient_score(10, 10, [0.0] * 10)
        assert score < 10

    def test_never_finishes(self):
        """0 finished races: score 0."""
        score = compute_resilient_score(0, 10, [])
        assert score == 0


class TestRageQuitterScore:
    def test_half_abandoned(self):
        score = compute_rage_quitter_score(abandoned=5, total=10)
        assert score == pytest.approx(50.0)

    def test_no_abandons(self):
        score = compute_rage_quitter_score(abandoned=0, total=10)
        assert score == 0.0

    def test_no_races(self):
        score = compute_rage_quitter_score(abandoned=0, total=0)
        assert score == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_traits.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement trait scoring pure functions**

Add to `server/speedfog_racing/services/stats_service.py`:

```python
def _compute_ranks(values: list[int | float]) -> list[float]:
    """Compute 1-indexed ranks with average rank for ties."""
    n = len(values)
    sorted_indices = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and values[sorted_indices[j + 1]] == values[sorted_indices[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1-indexed
        for k in range(i, j + 1):
            ranks[sorted_indices[k]] = avg_rank
        i = j + 1
    return ranks


def compute_rusher_score(
    igts: list[int], deaths: list[int], player_index: int
) -> float:
    """Rusher: fast but dies a lot. Returns 0-1."""
    n = len(igts)
    if n < 2:
        return 0.0
    igt_ranks = _compute_ranks(igts)
    death_ranks = _compute_ranks(deaths)
    raw = max(0.0, death_ranks[player_index] - igt_ranks[player_index]) / (n - 1)
    return min(raw, 1.0)


def compute_cautious_score(
    igts: list[int], deaths: list[int], player_index: int
) -> float:
    """Cautious: few deaths but slow. Returns 0-1."""
    n = len(igts)
    if n < 2:
        return 0.0
    igt_ranks = _compute_ranks(igts)
    death_ranks = _compute_ranks(deaths)
    raw = max(0.0, igt_ranks[player_index] - death_ranks[player_index]) / (n - 1)
    return min(raw, 1.0)


def compute_explorer_score(
    visited_nodes: set[str], total_nodes: int, history: list[dict[str, Any]]
) -> float:
    """Explorer: high coverage + backtracking. Returns 0-1."""
    if total_nodes == 0 or not history:
        return 0.0
    coverage = len(visited_nodes) / total_nodes
    seen: set[str] = set()
    backtracks = 0
    for entry in history:
        nid = entry.get("node_id", "")
        if nid in seen:
            backtracks += 1
        seen.add(nid)
    backtrack_rate = backtracks / len(history) if history else 0.0
    return 0.6 * coverage + 0.4 * backtrack_rate


def compute_pathfinder_score(
    player_nodes: set[str], others_nodes: set[str]
) -> float:
    """Pathfinder: unique routing. Returns 0-1."""
    if not player_nodes or not others_nodes:
        return 0.0
    unique = player_nodes - others_nodes
    return len(unique) / len(player_nodes)


def compute_boss_slayer_score(
    player_boss_deaths: dict[str, int],
    avg_boss_deaths: dict[str, float],
    boss_weights: dict[str, float],
) -> float:
    """Boss Slayer: fewer deaths than avg on hard bosses. Returns 0-1."""
    if not player_boss_deaths or not avg_boss_deaths:
        return 0.0
    total_weight = 0.0
    weighted_score = 0.0
    for boss_id, player_deaths in player_boss_deaths.items():
        avg = avg_boss_deaths.get(boss_id, 0.0)
        weight = boss_weights.get(boss_id, 1.0)
        if avg > 0:
            score = max(0.0, 1.0 - player_deaths / avg)
        else:
            score = 1.0 if player_deaths == 0 else 0.0
        weighted_score += score * weight
        total_weight += weight
    return weighted_score / total_weight if total_weight > 0 else 0.0


def compute_resilient_score(
    finished_races: int, total_races: int, gap_ratios: list[float]
) -> float:
    """Resilient: finishes despite being behind. Returns 0-100."""
    if total_races == 0 or finished_races == 0:
        return 0.0
    completion_rate = finished_races / total_races
    avg_gap = sum(gap_ratios) / len(gap_ratios) if gap_ratios else 0.0
    # Normalize: 100% completion + 50% avg gap = ~75
    raw = completion_rate * avg_gap
    return min(raw * 150.0, 100.0)


def compute_rage_quitter_score(abandoned: int, total: int) -> float:
    """Rage Quitter: high abandon rate. Returns 0-100."""
    if total == 0:
        return 0.0
    return (abandoned / total) * 100.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_traits.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add server/speedfog_racing/services/stats_service.py server/tests/test_traits.py
git commit -m "feat: behavioral trait scoring pure functions (7 traits)"
```

### Task 6: update_player_traits DB integration

**Files:**

- Modify: `server/speedfog_racing/services/stats_service.py`
- Modify: `server/tests/test_stats_api.py`

- [ ] **Step 1: Write failing test for update_player_traits**

Add to `server/tests/test_stats_api.py`:

```python
from speedfog_racing.models import PlayerTraitScores
from speedfog_racing.services.stats_service import update_player_traits


@pytest.fixture
async def race_with_zone_history(async_session):
    """Create a finished race with zone_history data for trait computation."""
    graph_json = {
        "nodes": {
            "start_a1b2": {"type": "start", "display_name": "Chapel", "layer": 0},
            "stormveil_c3d4": {"type": "legacy_dungeon", "display_name": "Stormveil Castle", "layer": 1},
            "cave_e5f6": {"type": "mini_dungeon", "display_name": "Coastal Cave", "layer": 1},
            "margit_g7h8": {"type": "boss_arena", "display_name": "Margit", "layer": 2},
            "raya_i9j0": {"type": "legacy_dungeon", "display_name": "Raya Lucaria", "layer": 3},
            "final_k1l2": {"type": "final_boss", "display_name": "Loretta", "layer": 4},
        },
        "total_layers": 5,
    }
    async with async_session() as db:
        users = [
            User(twitch_id=f"zh{i}", twitch_username=f"zhp{i}", api_token=f"zht{i}", role=UserRole.USER)
            for i in range(3)
        ]
        org = User(twitch_id="zhorg", twitch_username="zhorg", api_token="zhtorg", role=UserRole.ORGANIZER)
        db.add_all([*users, org])
        await db.flush()

        seed = Seed(
            seed_number="sz1", pool_name="standard", graph_json=graph_json,
            total_layers=5, folder_path="/t/sz1", status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Zone Race", organizer_id=org.id, seed_id=seed.id,
            status=RaceStatus.FINISHED, started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        # Player 0: fast, many deaths, visits few nodes (rusher)
        # Player 1: slow, few deaths, visits many nodes (cautious + explorer)
        # Player 2: medium, medium deaths
        participants = [
            Participant(
                race_id=race.id, user_id=users[0].id, mod_token="zm0",
                status=ParticipantStatus.FINISHED, igt_ms=1_800_000, death_count=25,
                zone_history=[
                    {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                    {"node_id": "stormveil_c3d4", "igt_ms": 300_000, "deaths": 10},
                    {"node_id": "margit_g7h8", "igt_ms": 800_000, "deaths": 8},
                    {"node_id": "final_k1l2", "igt_ms": 1_500_000, "deaths": 7},
                ],
            ),
            Participant(
                race_id=race.id, user_id=users[1].id, mod_token="zm1",
                status=ParticipantStatus.FINISHED, igt_ms=3_200_000, death_count=5,
                zone_history=[
                    {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                    {"node_id": "stormveil_c3d4", "igt_ms": 400_000, "deaths": 1},
                    {"node_id": "cave_e5f6", "igt_ms": 800_000, "deaths": 1},
                    {"node_id": "stormveil_c3d4", "igt_ms": 1_200_000},  # backtrack
                    {"node_id": "margit_g7h8", "igt_ms": 1_600_000, "deaths": 1},
                    {"node_id": "raya_i9j0", "igt_ms": 2_200_000, "deaths": 2},
                    {"node_id": "final_k1l2", "igt_ms": 3_000_000, "deaths": 0},
                ],
            ),
            Participant(
                race_id=race.id, user_id=users[2].id, mod_token="zm2",
                status=ParticipantStatus.FINISHED, igt_ms=2_500_000, death_count=12,
                zone_history=[
                    {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                    {"node_id": "stormveil_c3d4", "igt_ms": 350_000, "deaths": 4},
                    {"node_id": "margit_g7h8", "igt_ms": 900_000, "deaths": 5},
                    {"node_id": "raya_i9j0", "igt_ms": 1_800_000, "deaths": 3},
                    {"node_id": "final_k1l2", "igt_ms": 2_300_000, "deaths": 0},
                ],
            ),
        ]
        db.add_all(participants)
        await db.commit()
        return race.id, [u.id for u in users]


class TestUpdatePlayerTraits:
    async def test_creates_trait_scores(self, async_session, race_with_zone_history):
        race_id, user_ids = race_with_zone_history
        async with async_session() as db:
            await update_player_traits(race_id, db)

        async with async_session() as db:
            for uid in user_ids:
                scores = await db.get(PlayerTraitScores, uid)
                assert scores is not None
                assert 0 <= scores.rusher <= 100
                assert 0 <= scores.cautious <= 100

    async def test_rusher_scores_highest_for_fast_deadly_player(
        self, async_session, race_with_zone_history
    ):
        race_id, user_ids = race_with_zone_history
        async with async_session() as db:
            await update_player_traits(race_id, db)

        async with async_session() as db:
            scores_p0 = await db.get(PlayerTraitScores, user_ids[0])
            scores_p1 = await db.get(PlayerTraitScores, user_ids[1])
            # Player 0 is faster with more deaths: higher rusher
            assert scores_p0.rusher > scores_p1.rusher

    async def test_cautious_scores_highest_for_careful_player(
        self, async_session, race_with_zone_history
    ):
        race_id, user_ids = race_with_zone_history
        async with async_session() as db:
            await update_player_traits(race_id, db)

        async with async_session() as db:
            scores_p0 = await db.get(PlayerTraitScores, user_ids[0])
            scores_p1 = await db.get(PlayerTraitScores, user_ids[1])
            # Player 1 is slower with fewer deaths: higher cautious
            assert scores_p1.cautious > scores_p0.cautious
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_stats_api.py::TestUpdatePlayerTraits -v`
Expected: FAIL

- [ ] **Step 3: Implement update_player_traits**

Replace the stub in `stats_service.py` with the full implementation. The key design: for per-race traits (rusher, cautious, explorer, pathfinder, boss_slayer), we query ALL finished race participations for the player and average the raw scores across races. This ensures scores improve with more data and are not just based on the last race.

Add `func` to the sqlalchemy imports at the top of the file:

```python
from sqlalchemy import func, select
```

Then add:

```python
BOSS_NODE_TYPES = {"boss_arena", "major_boss", "final_boss"}
ZONE_NODE_TYPES = {"legacy_dungeon", "mini_dungeon"}
MIN_RACES_FOR_TRAITS = 3


async def update_player_traits(race_id: Any, db: AsyncSession) -> None:
    """Recompute trait scores for all participants of a finished race.

    For each participant, queries ALL their finished races to average
    per-race trait scores across their full history.
    """
    race = await db.get(
        Race, race_id,
        options=[selectinload(Race.participants)],
    )
    if race is None:
        return

    # Get user_ids of participants who played (FINISHED or ABANDONED with igt > 0)
    user_ids = [
        p.user_id for p in race.participants
        if p.status == ParticipantStatus.FINISHED
        or (p.status == ParticipantStatus.ABANDONED and p.igt_ms > 0)
    ]

    for user_id in user_ids:
        await _recompute_traits_for_user(user_id, db)

    await db.commit()


async def _recompute_traits_for_user(user_id: Any, db: AsyncSession) -> None:
    """Recompute all trait scores for a single user across all their races."""
    # Load all finished participations with race data
    all_participations = (await db.execute(
        select(Participant)
        .where(
            Participant.user_id == user_id,
            Participant.status == ParticipantStatus.FINISHED,
        )
        .options(
            selectinload(Participant.race)
            .selectinload(Race.participants),
            selectinload(Participant.race)
            .selectinload(Race.seed),
        )
    )).scalars().all()

    # Count global stats
    total_participated = (await db.execute(
        select(func.count()).where(
            Participant.user_id == user_id,
            Participant.status.in_([
                ParticipantStatus.FINISHED, ParticipantStatus.ABANDONED,
            ]),
            Participant.igt_ms > 0,
        )
    )).scalar() or 0

    total_abandoned_playing = (await db.execute(
        select(func.count()).where(
            Participant.user_id == user_id,
            Participant.status == ParticipantStatus.ABANDONED,
            Participant.igt_ms > 0,
        )
    )).scalar() or 0

    total_finished = len(all_participations)

    # Per-race trait accumulators
    rusher_scores: list[float] = []
    cautious_scores: list[float] = []
    explorer_scores: list[float] = []
    pathfinder_scores: list[float] = []
    boss_slayer_scores: list[float] = []
    gap_ratios: list[float] = []

    for pp in all_participations:
        race_obj = pp.race
        seed = race_obj.seed
        if seed is None:
            continue

        finishers = [
            rp for rp in race_obj.participants
            if rp.status == ParticipantStatus.FINISHED
        ]
        if len(finishers) < 2:
            continue

        graph = seed.graph_json
        nodes = graph.get("nodes", {})
        total_nodes = len(nodes)

        igts = [f.igt_ms for f in finishers]
        deaths = [f.death_count for f in finishers]
        player_idx = next(
            i for i, f in enumerate(finishers) if f.user_id == user_id
        )

        # Rusher / Cautious
        rusher_scores.append(compute_rusher_score(igts, deaths, player_idx))
        cautious_scores.append(compute_cautious_score(igts, deaths, player_idx))

        # Explorer
        history = pp.zone_history or []
        visited = {e.get("node_id", "") for e in history if e.get("node_id")}
        explorer_scores.append(
            compute_explorer_score(visited, total_nodes, history)
        )

        # Pathfinder
        others = set()
        for f in finishers:
            if f.user_id != user_id:
                for e in (f.zone_history or []):
                    nid = e.get("node_id", "")
                    if nid:
                        others.add(nid)
        pathfinder_scores.append(compute_pathfinder_score(visited, others))

        # Boss Slayer
        player_boss_deaths: dict[str, int] = {}
        boss_death_totals: dict[str, list[int]] = {}
        for f in finishers:
            for e in (f.zone_history or []):
                nid = e.get("node_id", "")
                node_info = nodes.get(nid, {})
                if node_info.get("type") in BOSS_NODE_TYPES:
                    d = e.get("deaths", 0)
                    boss_death_totals.setdefault(nid, []).append(d)
                    if f.user_id == user_id:
                        player_boss_deaths[nid] = d
        avg_bd = {
            bid: sum(v) / len(v) for bid, v in boss_death_totals.items() if v
        }
        boss_slayer_scores.append(
            compute_boss_slayer_score(player_boss_deaths, avg_bd, avg_bd)
        )

        # Gap ratio for resilient
        leader_igt = min(igts)
        if leader_igt > 0:
            gap_ratios.append((pp.igt_ms - leader_igt) / leader_igt)

    # Average per-race traits (require MIN_RACES_FOR_TRAITS)
    def avg_or_zero(vals: list[float]) -> int:
        if len(vals) < MIN_RACES_FOR_TRAITS:
            return 0
        return round(sum(vals) / len(vals) * 100)

    scores = {
        "rusher": avg_or_zero(rusher_scores),
        "cautious": avg_or_zero(cautious_scores),
        "explorer": avg_or_zero(explorer_scores),
        "pathfinder": avg_or_zero(pathfinder_scores),
        "boss_slayer": avg_or_zero(boss_slayer_scores),
        "resilient": round(compute_resilient_score(
            total_finished, total_participated, gap_ratios
        )) if total_finished >= MIN_RACES_FOR_TRAITS else 0,
        "rage_quitter": round(compute_rage_quitter_score(
            total_abandoned_playing, total_participated
        )),
    }

    # Dominant trait
    max_score = max(scores.values())
    dominant = None
    if max_score >= DOMINANT_TRAIT_THRESHOLD:
        dominant = max(scores, key=scores.get)

    # Upsert
    existing = await db.get(PlayerTraitScores, user_id)
    if existing:
        for key, val in scores.items():
            setattr(existing, key, val)
        existing.dominant_trait = dominant
        existing.updated_at = datetime.now(UTC)
    else:
        db.add(PlayerTraitScores(
            user_id=user_id,
            dominant_trait=dominant,
            **scores,
        ))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_stats_api.py tests/test_traits.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add server/speedfog_racing/services/stats_service.py server/tests/test_stats_api.py
git commit -m "feat: update_player_traits with all 7 behavioral trait scores"
```

---

## Chunk 3: Stats API Endpoints

### Task 7: Pydantic response schemas

**Files:**

- Modify: `server/speedfog_racing/schemas.py`

- [ ] **Step 1: Add stats response schemas**

Add to the end of `server/speedfog_racing/schemas.py`:

```python
# --- Stats ---

class LeaderboardPlayer(BaseModel):
    twitch_username: str
    twitch_display_name: str | None
    twitch_avatar_url: str | None
    elo_rating: int  # Displayed as rounded int
    elo_races: int
    wins: int
    losses: int
    trend_delta: int
    provisional: bool


class CommunityStats(BaseModel):
    total_races: int
    active_players: int
    total_deaths: int
    hours_raced: float


class LeaderboardResponse(BaseModel):
    players: list[LeaderboardPlayer]
    community: CommunityStats


class ZoneStatEntry(BaseModel):
    display_name: str
    type: str
    total_deaths: int
    avg_deaths_per_visit: float


class ZoneVisitEntry(BaseModel):
    display_name: str
    type: str
    visit_rate: float
    total_visits: int


class ZoneStatsResponse(BaseModel):
    deadliest: list[ZoneStatEntry]
    most_visited: list[ZoneVisitEntry]


class BossStatEntry(BaseModel):
    display_name: str
    type: str
    encounters: int
    avg_deaths: float
    max_deaths: int
    avg_time_ms: int


class BossStatsResponse(BaseModel):
    bosses: list[BossStatEntry]


class TraitPlayerEntry(BaseModel):
    twitch_username: str
    twitch_display_name: str | None
    twitch_avatar_url: str | None
    score: int
    elo_rating: int


class PlayerProfilesResponse(BaseModel):
    profiles: dict[str, list[TraitPlayerEntry]]


class TraitScoresDetail(BaseModel):
    rusher: int
    cautious: int
    resilient: int
    rage_quitter: int
    explorer: int
    pathfinder: int
    boss_slayer: int


class UserTraitsResponse(BaseModel):
    dominant_trait: str | None
    scores: TraitScoresDetail | None
    elo_rating: int
    elo_rank: int | None
    elo_trend_delta: int
```

- [ ] **Step 2: Run linting**

Run: `cd server && uv run ruff check schemas.py && uv run mypy speedfog_racing/schemas.py`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add server/speedfog_racing/schemas.py
git commit -m "feat: add Pydantic schemas for stats API responses"
```

### Task 8: Stats API routes (leaderboard, zones, bosses, players)

**Files:**

- Create: `server/speedfog_racing/api/stats.py`
- Modify: `server/speedfog_racing/api/__init__.py`

- [ ] **Step 1: Create stats router with leaderboard endpoint**

Create `server/speedfog_racing/api/stats.py`:

```python
"""Public stats API routes."""

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.database import get_db
from speedfog_racing.models import (
    EloHistory,
    Participant,
    ParticipantStatus,
    PlayerTraitScores,
    Race,
    RaceStatus,
    Seed,
    User,
)
from speedfog_racing.schemas import (
    BossStatEntry,
    BossStatsResponse,
    CommunityStats,
    LeaderboardPlayer,
    LeaderboardResponse,
    PlayerProfilesResponse,
    TraitPlayerEntry,
    ZoneStatEntry,
    ZoneStatsResponse,
    ZoneVisitEntry,
)

logger = logging.getLogger(__name__)
router = APIRouter()

BOSS_NODE_TYPES = {"boss_arena", "major_boss", "final_boss"}
ZONE_NODE_TYPES = {"legacy_dungeon", "mini_dungeon"}


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(db: AsyncSession = Depends(get_db)):
    # Players with at least 1 rated race, sorted by ELO
    users = (await db.execute(
        select(User).where(User.elo_races > 0).order_by(User.elo_rating.desc())
    )).scalars().all()

    players = []
    for user in users:
        # Wins: count of 1st place finishes
        # Get all races where this user finished
        participations = (await db.execute(
            select(Participant).where(
                Participant.user_id == user.id,
                Participant.status == ParticipantStatus.FINISHED,
            ).options(selectinload(Participant.race).selectinload(Race.participants))
        )).scalars().all()

        wins = 0
        for p in participations:
            if p.race.status != RaceStatus.FINISHED:
                continue
            finishers = [
                rp for rp in p.race.participants
                if rp.status == ParticipantStatus.FINISHED
            ]
            if finishers:
                best = min(finishers, key=lambda x: (x.igt_ms, x.death_count))
                if best.user_id == user.id:
                    wins += 1

        losses = len([
            p for p in participations if p.race.status == RaceStatus.FINISHED
        ]) - wins

        # Trend: sum of last 3 deltas
        recent_deltas = (await db.execute(
            select(EloHistory.delta)
            .where(EloHistory.user_id == user.id)
            .order_by(EloHistory.created_at.desc())
            .limit(3)
        )).scalars().all()
        trend_delta = round(sum(recent_deltas))

        players.append(LeaderboardPlayer(
            twitch_username=user.twitch_username,
            twitch_display_name=user.twitch_display_name,
            twitch_avatar_url=user.twitch_avatar_url,
            elo_rating=round(user.elo_rating),
            elo_races=user.elo_races,
            wins=wins,
            losses=losses,
            trend_delta=trend_delta,
            provisional=user.elo_races < 3,
        ))

    # Community stats
    total_races = (await db.execute(
        select(func.count()).select_from(Race).where(Race.status == RaceStatus.FINISHED)
    )).scalar() or 0

    thirty_days_ago = datetime.now(UTC) - timedelta(days=30)
    active_players = (await db.execute(
        select(func.count(func.distinct(Participant.user_id)))
        .select_from(Participant)
        .join(Race)
        .where(
            Participant.status == ParticipantStatus.FINISHED,
            Race.status == RaceStatus.FINISHED,
            Race.started_at >= thirty_days_ago,
        )
    )).scalar() or 0

    total_deaths = (await db.execute(
        select(func.sum(Participant.death_count))
        .where(Participant.status == ParticipantStatus.FINISHED)
    )).scalar() or 0

    total_igt_ms = (await db.execute(
        select(func.sum(Participant.igt_ms))
        .where(Participant.status == ParticipantStatus.FINISHED)
    )).scalar() or 0
    hours_raced = total_igt_ms / 3_600_000.0

    return LeaderboardResponse(
        players=players,
        community=CommunityStats(
            total_races=total_races,
            active_players=active_players,
            total_deaths=total_deaths,
            hours_raced=round(hours_raced, 1),
        ),
    )


@router.get("/zones", response_model=ZoneStatsResponse)
async def get_zone_stats(
    pool: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    deadliest, most_visited = await _aggregate_zone_stats(db, pool, ZONE_NODE_TYPES)
    return ZoneStatsResponse(deadliest=deadliest, most_visited=most_visited)


@router.get("/bosses", response_model=BossStatsResponse)
async def get_boss_stats(
    pool: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    bosses = await _aggregate_boss_stats(db, pool)
    return BossStatsResponse(bosses=bosses)


@router.get("/players", response_model=PlayerProfilesResponse)
async def get_player_profiles(db: AsyncSession = Depends(get_db)):
    all_scores = (await db.execute(
        select(PlayerTraitScores)
        .where(PlayerTraitScores.dominant_trait.isnot(None))
        .options()
    )).scalars().all()

    user_ids = [s.user_id for s in all_scores]
    users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
    users_by_id = {u.id: u for u in users_result.scalars().all()}

    profiles: dict[str, list[TraitPlayerEntry]] = {
        "rusher": [], "cautious": [], "resilient": [], "rage_quitter": [],
        "explorer": [], "pathfinder": [], "boss_slayer": [],
    }

    for s in all_scores:
        trait = s.dominant_trait
        if trait not in profiles:
            continue
        user = users_by_id.get(s.user_id)
        if not user:
            continue
        score_val = getattr(s, trait, 0)
        profiles[trait].append(TraitPlayerEntry(
            twitch_username=user.twitch_username,
            twitch_display_name=user.twitch_display_name,
            twitch_avatar_url=user.twitch_avatar_url,
            score=score_val,
            elo_rating=round(user.elo_rating),
        ))

    # Sort each trait list by score descending, limit to 10
    for trait in profiles:
        profiles[trait].sort(key=lambda x: x.score, reverse=True)
        profiles[trait] = profiles[trait][:10]

    return PlayerProfilesResponse(profiles=profiles)


async def _aggregate_zone_stats(
    db: AsyncSession, pool: str | None, node_types: set[str]
) -> tuple[list[ZoneStatEntry], list[ZoneVisitEntry]]:
    """Aggregate zone stats from all finished participants."""
    query = (
        select(Participant, Seed.graph_json, Seed.pool_name)
        .join(Race, Participant.race_id == Race.id)
        .join(Seed, Race.seed_id == Seed.id)
        .where(
            Participant.status == ParticipantStatus.FINISHED,
            Race.status == RaceStatus.FINISHED,
        )
    )
    if pool:
        query = query.where(Seed.pool_name == pool)

    results = (await db.execute(query)).all()

    # Track deaths and visits per zone display_name
    zone_deaths: dict[str, int] = defaultdict(int)
    zone_visits: dict[str, int] = defaultdict(int)
    zone_types: dict[str, str] = {}
    zone_race_visits: dict[str, set] = defaultdict(set)  # zone -> set of race_ids
    total_races_set: set = set()

    for participant, graph_json, _ in results:
        nodes = graph_json.get("nodes", {})
        total_races_set.add(participant.race_id)
        visited_in_race: set[str] = set()

        for entry in (participant.zone_history or []):
            nid = entry.get("node_id", "")
            node_info = nodes.get(nid, {})
            ntype = node_info.get("type", "")
            if ntype not in node_types:
                continue
            display_name = node_info.get("display_name", nid)
            zone_types[display_name] = ntype
            zone_deaths[display_name] += entry.get("deaths", 0)
            zone_visits[display_name] += 1
            if display_name not in visited_in_race:
                visited_in_race.add(display_name)
                zone_race_visits[display_name].add(participant.race_id)

    total_races = len(total_races_set) or 1

    deadliest = sorted(
        [
            ZoneStatEntry(
                display_name=name,
                type=zone_types[name],
                total_deaths=zone_deaths[name],
                avg_deaths_per_visit=round(zone_deaths[name] / max(zone_visits[name], 1), 1),
            )
            for name in zone_deaths
        ],
        key=lambda x: x.total_deaths,
        reverse=True,
    )

    most_visited = sorted(
        [
            ZoneVisitEntry(
                display_name=name,
                type=zone_types[name],
                visit_rate=round(len(zone_race_visits[name]) / total_races, 2),
                total_visits=zone_visits[name],
            )
            for name in zone_visits
        ],
        key=lambda x: x.visit_rate,
        reverse=True,
    )

    return deadliest, most_visited


async def _aggregate_boss_stats(
    db: AsyncSession, pool: str | None
) -> list[BossStatEntry]:
    """Aggregate boss stats from all finished participants."""
    query = (
        select(Participant, Seed.graph_json)
        .join(Race, Participant.race_id == Race.id)
        .join(Seed, Race.seed_id == Seed.id)
        .where(
            Participant.status == ParticipantStatus.FINISHED,
            Race.status == RaceStatus.FINISHED,
        )
    )
    if pool:
        query = query.where(Seed.pool_name == pool)

    results = (await db.execute(query)).all()

    boss_data: dict[str, dict[str, Any]] = {}  # display_name -> {type, deaths[], times[]}

    for participant, graph_json in results:
        nodes = graph_json.get("nodes", {})
        history = participant.zone_history or []

        for i, entry in enumerate(history):
            nid = entry.get("node_id", "")
            node_info = nodes.get(nid, {})
            ntype = node_info.get("type", "")
            if ntype not in BOSS_NODE_TYPES:
                continue

            display_name = node_info.get("display_name", nid)
            if display_name not in boss_data:
                boss_data[display_name] = {"type": ntype, "deaths": [], "times": []}

            boss_data[display_name]["deaths"].append(entry.get("deaths", 0))

            # Time in boss: diff to next entry or to finish
            entry_igt = entry.get("igt_ms", 0)
            if i + 1 < len(history):
                next_igt = history[i + 1].get("igt_ms", entry_igt)
            else:
                next_igt = participant.igt_ms
            boss_data[display_name]["times"].append(next_igt - entry_igt)

    bosses = sorted(
        [
            BossStatEntry(
                display_name=name,
                type=data["type"],
                encounters=len(data["deaths"]),
                avg_deaths=round(sum(data["deaths"]) / len(data["deaths"]), 1),
                max_deaths=max(data["deaths"]),
                avg_time_ms=round(sum(data["times"]) / len(data["times"])),
            )
            for name, data in boss_data.items()
            if data["deaths"]
        ],
        key=lambda x: x.avg_deaths,
        reverse=True,
    )

    return bosses
```

- [ ] **Step 2: Mount stats router**

In `server/speedfog_racing/api/__init__.py`, add:

```python
from speedfog_racing.api.stats import router as stats_router

api_router.include_router(stats_router, prefix="/stats", tags=["stats"])
```

- [ ] **Step 3: Run linting**

Run: `cd server && uv run ruff check speedfog_racing/api/stats.py && uv run mypy speedfog_racing/api/stats.py`

- [ ] **Step 4: Commit**

```bash
git add server/speedfog_racing/api/stats.py server/speedfog_racing/api/__init__.py
git commit -m "feat: stats API routes (leaderboard, zones, bosses, players)"
```

### Task 9: User traits endpoint + admin recalculate

**Files:**

- Modify: `server/speedfog_racing/api/users.py`
- Modify: `server/speedfog_racing/api/admin.py`
- Modify: `server/speedfog_racing/services/stats_service.py`

- [ ] **Step 1: Add /users/{username}/traits endpoint**

In `server/speedfog_racing/api/users.py`, add the endpoint after the existing profile endpoint:

```python
from speedfog_racing.models import EloHistory, PlayerTraitScores
from speedfog_racing.schemas import TraitScoresDetail, UserTraitsResponse


@router.get("/{username}/traits", response_model=UserTraitsResponse)
async def get_user_traits(
    username: str,
    db: AsyncSession = Depends(get_db),
):
    user = (await db.execute(
        select(User).where(User.twitch_username == username)
    )).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    scores = await db.get(PlayerTraitScores, user.id)

    # ELO rank
    elo_rank = None
    if user.elo_races >= 3:
        rank_count = (await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.elo_races >= 3, User.elo_rating > user.elo_rating)
        )).scalar() or 0
        elo_rank = rank_count + 1

    # Trend
    recent_deltas = (await db.execute(
        select(EloHistory.delta)
        .where(EloHistory.user_id == user.id)
        .order_by(EloHistory.created_at.desc())
        .limit(3)
    )).scalars().all()
    trend_delta = round(sum(recent_deltas))

    # Enforce 3-race minimum: return null scores if not enough races
    finished_count = (await db.execute(
        select(func.count()).where(
            Participant.user_id == user.id,
            Participant.status == ParticipantStatus.FINISHED,
        )
    )).scalar() or 0

    scores_detail = None
    dominant_trait = None
    if scores and finished_count >= 3:
        dominant_trait = scores.dominant_trait
        scores_detail = TraitScoresDetail(
            rusher=scores.rusher,
            cautious=scores.cautious,
            resilient=scores.resilient,
            rage_quitter=scores.rage_quitter,
            explorer=scores.explorer,
            pathfinder=scores.pathfinder,
            boss_slayer=scores.boss_slayer,
        )

    return UserTraitsResponse(
        dominant_trait=dominant_trait,
        scores=scores_detail,
        elo_rating=round(user.elo_rating),
        elo_rank=elo_rank,
        elo_trend_delta=trend_delta,
    )
```

Add needed imports (`func` from sqlalchemy, etc.).

- [ ] **Step 2: Add admin recalculate endpoint**

Add `recalculate_all_stats` to `stats_service.py`:

```python
async def recalculate_all_stats(db: AsyncSession) -> None:
    """Clear all ELO/trait data and replay from scratch."""
    await db.execute(EloHistory.__table__.delete())
    await db.execute(PlayerTraitScores.__table__.delete())

    # Reset all users' ELO
    from speedfog_racing.models import User as UserModel
    all_users = (await db.execute(select(UserModel))).scalars().all()
    for u in all_users:
        u.elo_rating = STARTING_ELO
        u.elo_races = 0
    await db.commit()

    # Replay all finished races in chronological order
    races = (await db.execute(
        select(Race)
        .where(Race.status == RaceStatus.FINISHED)
        .order_by(Race.started_at.asc())
    )).scalars().all()

    for race in races:
        await update_elo_ratings(race.id, db)
        await update_player_traits(race.id, db)
```

In `server/speedfog_racing/api/admin.py`, add:

```python
from speedfog_racing.services.stats_service import recalculate_all_stats


@router.post("/stats/recalculate")
async def recalculate_stats(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await recalculate_all_stats(db)
    return {"status": "ok"}
```

- [ ] **Step 3: Run tests**

Run: `cd server && uv run pytest tests/test_stats_api.py tests/test_admin.py -v --timeout=30`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add server/speedfog_racing/api/users.py server/speedfog_racing/api/admin.py server/speedfog_racing/services/stats_service.py
git commit -m "feat: user traits endpoint and admin stats recalculate"
```

---

## Chunk 4: Frontend

### Task 10: API types and fetch functions

**Files:**

- Modify: `web/src/lib/api.ts`

- [ ] **Step 1: Add stats types and fetch functions**

Add at the end of `web/src/lib/api.ts`:

```typescript
// --- Stats ---

export interface LeaderboardPlayer {
  twitch_username: string;
  twitch_display_name: string | null;
  twitch_avatar_url: string | null;
  elo_rating: number;
  elo_races: number;
  wins: number;
  losses: number;
  trend_delta: number;
  provisional: boolean;
}

export interface CommunityStats {
  total_races: number;
  active_players: number;
  total_deaths: number;
  hours_raced: number;
}

export interface LeaderboardResponse {
  players: LeaderboardPlayer[];
  community: CommunityStats;
}

export interface ZoneStatEntry {
  display_name: string;
  type: string;
  total_deaths: number;
  avg_deaths_per_visit: number;
}

export interface ZoneVisitEntry {
  display_name: string;
  type: string;
  visit_rate: number;
  total_visits: number;
}

export interface ZoneStatsResponse {
  deadliest: ZoneStatEntry[];
  most_visited: ZoneVisitEntry[];
}

export interface BossStatEntry {
  display_name: string;
  type: string;
  encounters: number;
  avg_deaths: number;
  max_deaths: number;
  avg_time_ms: number;
}

export interface BossStatsResponse {
  bosses: BossStatEntry[];
}

export interface TraitPlayerEntry {
  twitch_username: string;
  twitch_display_name: string | null;
  twitch_avatar_url: string | null;
  score: number;
  elo_rating: number;
}

export interface PlayerProfilesResponse {
  profiles: Record<string, TraitPlayerEntry[]>;
}

export interface TraitScoresDetail {
  rusher: number;
  cautious: number;
  resilient: number;
  rage_quitter: number;
  explorer: number;
  pathfinder: number;
  boss_slayer: number;
}

export interface UserTraitsResponse {
  dominant_trait: string | null;
  scores: TraitScoresDetail | null;
  elo_rating: number;
  elo_rank: number | null;
  elo_trend_delta: number;
}

export async function fetchLeaderboard(): Promise<LeaderboardResponse> {
  const res = await fetch(`${API_BASE}/stats/leaderboard`);
  if (!res.ok) throw new Error("Failed to fetch leaderboard");
  return res.json();
}

export async function fetchZoneStats(
  pool?: string,
): Promise<ZoneStatsResponse> {
  const params = pool ? `?pool=${pool}` : "";
  const res = await fetch(`${API_BASE}/stats/zones${params}`);
  if (!res.ok) throw new Error("Failed to fetch zone stats");
  return res.json();
}

export async function fetchBossStats(
  pool?: string,
): Promise<BossStatsResponse> {
  const params = pool ? `?pool=${pool}` : "";
  const res = await fetch(`${API_BASE}/stats/bosses${params}`);
  if (!res.ok) throw new Error("Failed to fetch boss stats");
  return res.json();
}

export async function fetchPlayerProfiles(): Promise<PlayerProfilesResponse> {
  const res = await fetch(`${API_BASE}/stats/players`);
  if (!res.ok) throw new Error("Failed to fetch player profiles");
  return res.json();
}

export async function fetchUserTraits(
  username: string,
): Promise<UserTraitsResponse> {
  const res = await fetch(`${API_BASE}/users/${username}/traits`);
  if (!res.ok) throw new Error("Failed to fetch user traits");
  return res.json();
}
```

- [ ] **Step 2: Run type check**

Run: `cd web && npm run check`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/api.ts
git commit -m "feat: add stats API types and fetch functions"
```

### Task 11: Stats page with 4 tabs

**Files:**

- Create: `web/src/routes/stats/+page.svelte`
- Create: `web/src/lib/components/stats/LeaderboardTab.svelte`
- Create: `web/src/lib/components/stats/ZonesTab.svelte`
- Create: `web/src/lib/components/stats/BossesTab.svelte`
- Create: `web/src/lib/components/stats/PlayersTab.svelte`

This task is large. The implementation should follow the mockups from the brainstorming session. Each tab component fetches its own data on mount.

- [ ] **Step 1: Create the stats page shell with tabs**

Create `web/src/routes/stats/+page.svelte` with 4 tabs routed via `?tab=` query param. Default tab: leaderboard. Each tab lazy-loads its component.

- [ ] **Step 2: Create LeaderboardTab.svelte**

Ranking table + sidebar with community stats and ELO explainer. Follow graphic charter (gold #1, tabular-nums, etc.).

- [ ] **Step 3: Create ZonesTab.svelte**

Two panels side-by-side: "Deadliest Zones" and "Most Visited Zones" with horizontal bar charts and type badges.

- [ ] **Step 4: Create BossesTab.svelte**

Table with sortable columns: boss name + type badge, encounters, avg deaths, max deaths, avg time.

- [ ] **Step 5: Create PlayersTab.svelte**

Grouped by dominant trait. Each section: category header with icon/color/description, top 3 player rows with "Show all" expand button.

- [ ] **Step 6: Run type check and lint**

Run: `cd web && npm run check && npm run lint`

- [ ] **Step 7: Commit**

```bash
git add web/src/routes/stats/ web/src/lib/components/stats/
git commit -m "feat: stats page with leaderboard, zones, bosses, players tabs"
```

### Task 12: Play Style component and profile page integration

**Files:**

- Create: `web/src/lib/components/PlayStyle.svelte`
- Modify: `web/src/routes/user/[username]/+page.svelte`

- [ ] **Step 1: Create PlayStyle.svelte**

Card component showing: dominant trait (icon + color + desc) + ELO (rank + value + trend) at top, 7 trait bars sorted by score desc. Uses `UserTraitsResponse` as prop.

Define trait metadata (name, color, icon, description) as a const map in the component.

- [ ] **Step 2: Integrate into user profile page**

In `web/src/routes/user/[username]/+page.svelte`:

- Import `fetchUserTraits` and `PlayStyle` component
- Add `traits` state variable, fetch alongside profile/activity/poolStats in `loadProfile()`
- Add the Play Style section between stats-grid and pool-stats-section
- Conditionally render only if traits data exists and has scores

- [ ] **Step 3: Run type check**

Run: `cd web && npm run check`

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/components/PlayStyle.svelte web/src/routes/user/\[username\]/+page.svelte
git commit -m "feat: Play Style card on user profile page"
```

### Task 13: Navbar Stats link

**Files:**

- Modify: `web/src/routes/+layout.svelte`

- [ ] **Step 1: Add Stats link between Discord and Help icons**

In `web/src/routes/+layout.svelte`, after the Discord icon link (line ~67) and before the Help icon (line ~68), add:

```svelte
<a href="/stats" class="nav-icon" aria-label="Stats" title="Community Stats">
    <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
        <path d="M3 13h2v8H3zm6-4h2v12H9zm6-6h2v18h-2zm6 10h2v8h-2z"/>
    </svg>
</a>
```

This is a simple bar chart icon, visible to all users (not auth-gated).

- [ ] **Step 2: Run lint**

Run: `cd web && npm run lint`

- [ ] **Step 3: Commit**

```bash
git add web/src/routes/+layout.svelte
git commit -m "feat: add Stats link to navbar"
```

---

## Chunk 5: Final Integration & Review

### Task 14: Run full test suite and fix issues

- [ ] **Step 1: Run server tests**

Run: `cd server && uv run pytest -v --timeout=30`
Expected: All PASS

- [ ] **Step 2: Run server linting**

Run: `cd server && uv run ruff check . && uv run ruff format . && uv run mypy speedfog_racing/`

- [ ] **Step 3: Run frontend checks**

Run: `cd web && npm run check && npm run lint`

- [ ] **Step 4: Fix any issues found**

- [ ] **Step 5: Final commit**

```bash
git add -u
git commit -m "fix: resolve linting and type issues from stats feature"
```

### Task 15: Code review

- [ ] **Step 1: Launch code review agent**

Use `superpowers:requesting-code-review` to review all changes against the spec.
