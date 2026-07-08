"""Integration tests for stats service and API."""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from speedfog_racing.api.stats import (
    BOSS_NODE_TYPES,
    DUNGEON_NODE_TYPES,
    _aggregate_zone_stats,
    _resolve_node_display,
    get_zone_detail,
    get_zone_index,
    get_zone_stats,
)
from speedfog_racing.database import Base
from speedfog_racing.models import (
    EloHistory,
    Participant,
    ParticipantStatus,
    PlayerTraitScores,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.services.stats_service import (
    resolve_dominant_traits,
    update_elo_ratings,
    update_player_traits,
)


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def finished_race(async_session):
    """Create a finished race with 3 participants (2 finished, 1 abandoned with igt>0)."""
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
            winner = await db.get(User, user_ids[0])
            assert winner.elo_rating > 1500.0
            abandoner = await db.get(User, user_ids[2])
            assert abandoner.elo_rating < 1500.0

    async def test_creates_elo_history_entries(self, async_session, finished_race):
        race_id, user_ids = finished_race
        async with async_session() as db:
            await update_elo_ratings(race_id, db)

        async with async_session() as db:
            entries = (await db.execute(select(EloHistory))).scalars().all()
            assert len(entries) == 3

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
        """Abandoned with igt_ms=0 should be excluded entirely."""
        async with async_session() as db:
            users = [
                User(
                    twitch_id=f"t{i}",
                    twitch_username=f"p{i}",
                    api_token=f"t{i}",
                    role=UserRole.USER,
                )
                for i in range(2)
            ]
            org = User(
                twitch_id="org2", twitch_username="org2", api_token="to2", role=UserRole.ORGANIZER
            )
            db.add_all([*users, org])
            await db.flush()
            seed = Seed(
                seed_number="s2",
                pool_name="standard",
                graph_json={"nodes": {}},
                total_layers=3,
                folder_path="/t/s2",
                status=SeedStatus.CONSUMED,
            )
            db.add(seed)
            await db.flush()
            race = Race(
                name="R2",
                organizer_id=org.id,
                seed_id=seed.id,
                status=RaceStatus.FINISHED,
                started_at=datetime.now(UTC),
            )
            db.add(race)
            await db.flush()
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=users[0].id,
                    mod_token="m0",
                    status=ParticipantStatus.FINISHED,
                    igt_ms=2_000_000,
                    death_count=5,
                )
            )
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=users[1].id,
                    mod_token="m1",
                    status=ParticipantStatus.ABANDONED,
                    igt_ms=0,
                    death_count=0,
                )
            )
            await db.commit()
            rid = race.id
            uid_finished = users[0].id
            uid_abandoned = users[1].id

        async with async_session() as db:
            await update_elo_ratings(rid, db)

        async with async_session() as db:
            finished_user = await db.get(User, uid_finished)
            abandoned_user = await db.get(User, uid_abandoned)
            # Only 1 eligible player, no pairs possible
            assert finished_user.elo_races == 0
            assert abandoned_user.elo_races == 0

    async def test_difficulty_injection_uses_race_seeds_not_consumed_status(self, async_session):
        """Difficulty average must include DISCARDED seeds from past races.

        Pool rotation marks consumed seeds as DISCARDED. If the average only
        considers CONSUMED seeds, it excludes most historical data and skews
        the difficulty factor. This test uses asymmetric difficulty scores
        so it would fail if the query filtered by SeedStatus.CONSUMED only.

        Setup:
        - Past race seed (DISCARDED, difficulty=50)
        - Current race seed (CONSUMED, difficulty=150)
        - Correct global avg = (50 + 150) / 2 = 100
        - Buggy avg (CONSUMED only) = 150

        For the current race (difficulty=150):
        - Correct factor: 150/100 = 1.5, bonus = 5.0 * 0.5 = +2.5 per player
        - Buggy factor: 150/150 = 1.0, bonus = 0
        """
        async with async_session() as db:
            org = User(
                twitch_id="diff_org",
                twitch_username="diff_org",
                api_token="diff_org_t",
                role=UserRole.ORGANIZER,
            )
            users = [
                User(
                    twitch_id=f"diff_u{i}",
                    twitch_username=f"diff_p{i}",
                    api_token=f"diff_tok{i}",
                    role=UserRole.USER,
                )
                for i in range(4)
            ]
            db.add_all([org, *users])
            await db.flush()

            # Past race seed: DISCARDED (pool was rotated), easy seed
            seed_past = Seed(
                seed_number="past1",
                pool_name="standard",
                graph_json={"nodes": {}, "total_layers": 2},
                total_layers=2,
                folder_path="/test/past1",
                status=SeedStatus.DISCARDED,
                difficulty_score=50.0,
            )
            # Current race seed: CONSUMED, hard seed
            seed_current = Seed(
                seed_number="curr1",
                pool_name="standard",
                graph_json={"nodes": {}, "total_layers": 5},
                total_layers=5,
                folder_path="/test/curr1",
                status=SeedStatus.CONSUMED,
                difficulty_score=150.0,
            )
            db.add_all([seed_past, seed_current])
            await db.flush()

            # Past finished race with the DISCARDED seed
            race_past = Race(
                name="Past Race",
                organizer_id=org.id,
                seed_id=seed_past.id,
                status=RaceStatus.FINISHED,
                is_public=True,
                started_at=datetime.now(UTC),
            )
            db.add(race_past)
            await db.flush()
            db.add_all(
                [
                    Participant(
                        race_id=race_past.id,
                        user_id=users[0].id,
                        mod_token="dp0",
                        status=ParticipantStatus.FINISHED,
                        igt_ms=2_000_000,
                    ),
                    Participant(
                        race_id=race_past.id,
                        user_id=users[1].id,
                        mod_token="dp1",
                        status=ParticipantStatus.FINISHED,
                        igt_ms=3_000_000,
                    ),
                ]
            )
            await db.commit()
            past_id = race_past.id

        async with async_session() as db:
            await update_elo_ratings(past_id, db)

        # Create current race with the harder seed
        async with async_session() as db:
            race_current = Race(
                name="Current Race",
                organizer_id=org.id,
                seed_id=seed_current.id,
                status=RaceStatus.FINISHED,
                is_public=True,
                started_at=datetime.now(UTC),
            )
            db.add(race_current)
            await db.flush()
            db.add_all(
                [
                    Participant(
                        race_id=race_current.id,
                        user_id=users[2].id,
                        mod_token="dc0",
                        status=ParticipantStatus.FINISHED,
                        igt_ms=2_000_000,
                    ),
                    Participant(
                        race_id=race_current.id,
                        user_id=users[3].id,
                        mod_token="dc1",
                        status=ParticipantStatus.FINISHED,
                        igt_ms=3_000_000,
                    ),
                ]
            )
            await db.commit()
            current_id = race_current.id

        async with async_session() as db:
            await update_elo_ratings(current_id, db)

        # The current race (difficulty=150) should get a positive bonus
        # because 150 > global avg of 100, giving factor=1.5.
        # Both players should receive bonus = 5.0 * (1.5 - 1.0) = +2.5
        async with async_session() as db:
            current_entries = (
                (await db.execute(select(EloHistory).where(EloHistory.race_id == current_id)))
                .scalars()
                .all()
            )
            current_sum = sum(e.delta for e in current_entries)
            # Sum of deltas must be positive (difficulty bonus injected).
            # If the query only looked at CONSUMED seeds, avg=150,
            # factor=1.0, bonus=0, and sum would be ~0 (zero-sum pairwise).
            assert current_sum > 2.0


@pytest.fixture
async def three_races_with_zone_history(async_session):
    """Create 3 finished races with zone_history data for trait computation.

    Player 0 (rusher pattern): fast IGT, many deaths, few nodes visited.
    Player 1 (cautious/explorer pattern): slow IGT, few deaths, many nodes visited.
    Player 2 (medium): average on all dimensions.
    """
    graph_json = {
        "nodes": {
            "start_a1b2": {"type": "start", "display_name": "Chapel", "layer": 0},
            "stormveil_c3d4": {
                "type": "legacy_dungeon",
                "display_name": "Stormveil Castle",
                "layer": 1,
                "zones": ["stormveil", "stormveil_gate"],
            },
            "cave_e5f6": {
                "type": "mini_dungeon",
                "display_name": "Coastal Cave",
                "layer": 1,
                "zones": ["coastal_cave"],
            },
            "margit_g7h8": {"type": "boss_arena", "display_name": "Margit", "layer": 2},
            "raya_i9j0": {
                "type": "legacy_dungeon",
                "display_name": "Raya Lucaria",
                "layer": 3,
                "zones": ["raya_lucaria"],
            },
            "final_k1l2": {"type": "final_boss", "display_name": "Loretta", "layer": 4},
        },
        "total_layers": 5,
    }

    async with async_session() as db:
        users = [
            User(
                twitch_id=f"zh{i}",
                twitch_username=f"zhp{i}",
                api_token=f"zht{i}",
                role=UserRole.USER,
                elo_races=3,
            )
            for i in range(3)
        ]
        org = User(
            twitch_id="zhorg",
            twitch_username="zhorg",
            api_token="zhtorg",
            role=UserRole.ORGANIZER,
        )
        db.add_all([*users, org])
        await db.flush()

        race_ids = []
        for r_idx in range(3):
            seed = Seed(
                seed_number=f"sz{r_idx}",
                pool_name="standard",
                graph_json=graph_json,
                total_layers=5,
                folder_path=f"/t/sz{r_idx}",
                status=SeedStatus.CONSUMED,
            )
            db.add(seed)
            await db.flush()

            race = Race(
                name=f"Zone Race {r_idx}",
                organizer_id=org.id,
                seed_id=seed.id,
                status=RaceStatus.FINISHED,
                started_at=datetime.now(UTC),
            )
            db.add(race)
            await db.flush()
            race_ids.append(race.id)

            # Vary times slightly per race but keep the pattern consistent
            time_mult = 1.0 + r_idx * 0.1  # 1.0, 1.1, 1.2

            # Player 0: fast, many deaths, visits few nodes (rusher)
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=users[0].id,
                    mod_token=f"zm0r{r_idx}",
                    status=ParticipantStatus.FINISHED,
                    igt_ms=int(1_800_000 * time_mult),
                    death_count=25,
                    zone_history=[
                        {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                        {"node_id": "stormveil_c3d4", "igt_ms": 300_000, "deaths": 10},
                        {"node_id": "margit_g7h8", "igt_ms": 800_000, "deaths": 8},
                        {"node_id": "final_k1l2", "igt_ms": 1_500_000, "deaths": 7},
                    ],
                )
            )
            # Player 1: slow, few deaths, visits many nodes (cautious + explorer)
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=users[1].id,
                    mod_token=f"zm1r{r_idx}",
                    status=ParticipantStatus.FINISHED,
                    igt_ms=int(3_200_000 * time_mult),
                    death_count=5,
                    zone_history=[
                        {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                        {"node_id": "stormveil_c3d4", "igt_ms": 400_000, "deaths": 1},
                        {"node_id": "cave_e5f6", "igt_ms": 800_000, "deaths": 1},
                        {"node_id": "stormveil_c3d4", "igt_ms": 1_200_000},
                        {"node_id": "margit_g7h8", "igt_ms": 1_600_000, "deaths": 1},
                        {"node_id": "raya_i9j0", "igt_ms": 2_200_000, "deaths": 2},
                        {"node_id": "final_k1l2", "igt_ms": 3_000_000, "deaths": 0},
                    ],
                )
            )
            # Player 2: medium stats
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=users[2].id,
                    mod_token=f"zm2r{r_idx}",
                    status=ParticipantStatus.FINISHED,
                    igt_ms=int(2_500_000 * time_mult),
                    death_count=12,
                    zone_history=[
                        {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                        {"node_id": "stormveil_c3d4", "igt_ms": 350_000, "deaths": 4},
                        {"node_id": "margit_g7h8", "igt_ms": 900_000, "deaths": 5},
                        {"node_id": "raya_i9j0", "igt_ms": 1_800_000, "deaths": 3},
                        {"node_id": "final_k1l2", "igt_ms": 2_300_000, "deaths": 0},
                    ],
                )
            )

        await db.commit()
        return race_ids, [u.id for u in users]


class TestUpdatePlayerTraits:
    async def test_creates_trait_scores(self, async_session, three_races_with_zone_history):
        race_ids, user_ids = three_races_with_zone_history
        # Process all 3 races so each player has 3 finished participations
        for rid in race_ids:
            async with async_session() as db:
                await update_player_traits(rid, db)

        async with async_session() as db:
            for uid in user_ids:
                scores = await db.get(PlayerTraitScores, uid)
                assert scores is not None
                assert 0 <= scores.rusher <= 100
                assert 0 <= scores.cautious <= 100
                assert 0 <= scores.explorer <= 100
                assert 0 <= scores.pathfinder <= 100
                assert 0 <= scores.boss_slayer <= 100
                assert 0 <= scores.resilient <= 100
                assert 0 <= scores.rage_quitter <= 100

    async def test_rusher_scores_highest_for_fast_deadly_player(
        self, async_session, three_races_with_zone_history
    ):
        race_ids, user_ids = three_races_with_zone_history
        for rid in race_ids:
            async with async_session() as db:
                await update_player_traits(rid, db)

        async with async_session() as db:
            scores_p0 = await db.get(PlayerTraitScores, user_ids[0])
            scores_p1 = await db.get(PlayerTraitScores, user_ids[1])
            # Player 0 (fast + high deaths) should have higher rusher than player 1
            assert scores_p0.rusher > scores_p1.rusher

    async def test_cautious_scores_highest_for_careful_player(
        self, async_session, three_races_with_zone_history
    ):
        race_ids, user_ids = three_races_with_zone_history
        for rid in race_ids:
            async with async_session() as db:
                await update_player_traits(rid, db)

        async with async_session() as db:
            scores_p0 = await db.get(PlayerTraitScores, user_ids[0])
            scores_p1 = await db.get(PlayerTraitScores, user_ids[1])
            # Player 1 (slow + low deaths) should have higher cautious than player 0
            assert scores_p1.cautious > scores_p0.cautious

    async def test_explorer_scores_highest_for_thorough_player(
        self, async_session, three_races_with_zone_history
    ):
        race_ids, user_ids = three_races_with_zone_history
        for rid in race_ids:
            async with async_session() as db:
                await update_player_traits(rid, db)

        async with async_session() as db:
            scores_p0 = await db.get(PlayerTraitScores, user_ids[0])
            scores_p1 = await db.get(PlayerTraitScores, user_ids[1])
            # Player 1 visits more nodes and backtracks, higher explorer
            assert scores_p1.explorer > scores_p0.explorer

    async def test_below_min_races_returns_zero(self, async_session):
        """With fewer than MIN_RACES_FOR_TRAITS finished races, per-race traits should be 0."""
        graph_json = {
            "nodes": {
                "start_a1b2": {"type": "start", "display_name": "Chapel", "layer": 0},
                "final_k1l2": {"type": "final_boss", "display_name": "Loretta", "layer": 1},
            },
            "total_layers": 2,
        }
        async with async_session() as db:
            u1 = User(
                twitch_id="min1",
                twitch_username="min1",
                api_token="mint1",
                role=UserRole.USER,
            )
            u2 = User(
                twitch_id="min2",
                twitch_username="min2",
                api_token="mint2",
                role=UserRole.USER,
            )
            org = User(
                twitch_id="minorg",
                twitch_username="minorg",
                api_token="mintorg",
                role=UserRole.ORGANIZER,
            )
            db.add_all([u1, u2, org])
            await db.flush()

            seed = Seed(
                seed_number="smin",
                pool_name="standard",
                graph_json=graph_json,
                total_layers=2,
                folder_path="/t/smin",
                status=SeedStatus.CONSUMED,
            )
            db.add(seed)
            await db.flush()

            race = Race(
                name="Min Race",
                organizer_id=org.id,
                seed_id=seed.id,
                status=RaceStatus.FINISHED,
                started_at=datetime.now(UTC),
            )
            db.add(race)
            await db.flush()

            db.add_all(
                [
                    Participant(
                        race_id=race.id,
                        user_id=u1.id,
                        mod_token="mmin0",
                        status=ParticipantStatus.FINISHED,
                        igt_ms=1_000_000,
                        death_count=5,
                        zone_history=[{"node_id": "start_a1b2", "igt_ms": 0}],
                    ),
                    Participant(
                        race_id=race.id,
                        user_id=u2.id,
                        mod_token="mmin1",
                        status=ParticipantStatus.FINISHED,
                        igt_ms=2_000_000,
                        death_count=10,
                        zone_history=[{"node_id": "start_a1b2", "igt_ms": 0}],
                    ),
                ]
            )
            await db.commit()
            rid = race.id
            uid = u1.id

        async with async_session() as db:
            await update_player_traits(rid, db)

        async with async_session() as db:
            scores = await db.get(PlayerTraitScores, uid)
            assert scores is not None
            # Only 1 race, need MIN_RACES_FOR_TRAITS (3), so all traits should be 0
            assert scores.rusher == 0
            assert scores.cautious == 0
            assert scores.explorer == 0
            assert scores.pathfinder == 0
            assert scores.boss_slayer == 0
            assert scores.resilient == 0
            assert scores.rage_quitter == 0
            assert scores.dominant_trait is None

    async def test_dominant_trait_uses_percentile_ranking(self, async_session):
        """Dominant trait should be the one where the player ranks best
        relative to all other players, not the highest raw score."""
        async with async_session() as db:
            # Create 4 users with pre-computed trait scores.
            # Player A: rusher=80, boss_slayer=90 -- raw max is boss_slayer,
            #   but all 4 players have high boss_slayer (80-95), while only
            #   player A has a high rusher. So percentile-wise, rusher wins.
            users = []
            for i in range(4):
                u = User(
                    twitch_id=f"pct{i}",
                    twitch_username=f"pct{i}",
                    api_token=f"pcttok{i}",
                    role=UserRole.USER,
                )
                users.append(u)
            db.add_all(users)
            await db.flush()

            seed = Seed(
                seed_number="pct_seed",
                pool_name="standard",
                graph_json={"nodes": {}, "total_layers": 1},
                total_layers=1,
                folder_path="/t/pct",
                status=SeedStatus.CONSUMED,
            )
            db.add(seed)
            await db.flush()
            for r in range(3):
                race = Race(
                    name=f"PCT R{r}",
                    organizer_id=users[0].id,
                    seed_id=seed.id,
                    status=RaceStatus.FINISHED,
                )
                db.add(race)
                await db.flush()
                for j, u in enumerate(users):
                    db.add(
                        Participant(
                            race_id=race.id,
                            user_id=u.id,
                            mod_token=f"pct_{r}_{j}",
                            status=ParticipantStatus.FINISHED,
                            igt_ms=1_000_000,
                            death_count=0,
                        )
                    )

            scores_data = [
                # (rusher, cautious, explorer, pathfinder, boss_slayer, resilient, rage_quitter)
                (80, 10, 10, 10, 90, 20, 0),  # Player A: high rusher AND boss_slayer
                (20, 10, 10, 10, 95, 20, 0),  # Player B: very high boss_slayer
                (15, 10, 10, 10, 85, 20, 0),  # Player C: high boss_slayer
                (10, 10, 10, 10, 80, 20, 0),  # Player D: high boss_slayer
            ]
            for user, (ru, ca, ex, pf, bs, re, rq) in zip(users, scores_data):
                db.add(
                    PlayerTraitScores(
                        user_id=user.id,
                        rusher=ru,
                        cautious=ca,
                        explorer=ex,
                        pathfinder=pf,
                        boss_slayer=bs,
                        resilient=re,
                        rage_quitter=rq,
                        dominant_trait=None,
                    )
                )
            await db.commit()
            uid_a = users[0].id

        # Run the percentile resolution
        async with async_session() as db:
            await resolve_dominant_traits(db)

        async with async_session() as db:
            scores_a = await db.get(PlayerTraitScores, uid_a)
            # Player A's raw max is boss_slayer (90), but all players have
            # high boss_slayer. Player A is rank 1 in rusher (80 vs 20/15/10),
            # which is a better percentile than rank 2 in boss_slayer (90 < 95).
            assert scores_a.dominant_trait == "rusher"
            assert scores_a.dominant_description is not None
            assert "4" in scores_a.dominant_description  # "among 4 players"

    async def test_no_dominant_when_not_in_top_half(self, async_session):
        """If a player isn't in the top 50% on any trait, no dominant trait."""
        async with async_session() as db:
            users = []
            for i in range(4):
                u = User(
                    twitch_id=f"nod{i}",
                    twitch_username=f"nod{i}",
                    api_token=f"nodtok{i}",
                    role=UserRole.USER,
                )
                users.append(u)
            db.add_all(users)
            await db.flush()

            seed = Seed(
                seed_number="nod_seed",
                pool_name="standard",
                graph_json={"nodes": {}, "total_layers": 1},
                total_layers=1,
                folder_path="/t/nod",
                status=SeedStatus.CONSUMED,
            )
            db.add(seed)
            await db.flush()
            for r in range(3):
                race = Race(
                    name=f"NOD R{r}",
                    organizer_id=users[0].id,
                    seed_id=seed.id,
                    status=RaceStatus.FINISHED,
                )
                db.add(race)
                await db.flush()
                for j, u in enumerate(users):
                    db.add(
                        Participant(
                            race_id=race.id,
                            user_id=u.id,
                            mod_token=f"nod_{r}_{j}",
                            status=ParticipantStatus.FINISHED,
                            igt_ms=1_000_000,
                            death_count=0,
                        )
                    )

            # Player D is last or tied-last on every trait
            scores_data = [
                (80, 80, 80, 80, 80, 80, 0),
                (70, 70, 70, 70, 70, 70, 0),
                (60, 60, 60, 60, 60, 60, 0),
                (10, 10, 10, 10, 10, 10, 0),  # Player D: bottom on everything
            ]
            for user, (ru, ca, ex, pf, bs, re, rq) in zip(users, scores_data):
                db.add(
                    PlayerTraitScores(
                        user_id=user.id,
                        rusher=ru,
                        cautious=ca,
                        explorer=ex,
                        pathfinder=pf,
                        boss_slayer=bs,
                        resilient=re,
                        rage_quitter=rq,
                        dominant_trait=None,
                    )
                )
            await db.commit()
            uid_d = users[3].id

        async with async_session() as db:
            await resolve_dominant_traits(db)

        async with async_session() as db:
            scores_d = await db.get(PlayerTraitScores, uid_d)
            assert scores_d.dominant_trait is None
            assert scores_d.dominant_description is None

    async def test_dominant_trait_tiebreak_uses_raw_score(self, async_session):
        """When two traits have the same percentile, prefer the one with higher raw score."""
        async with async_session() as db:
            users = []
            for i in range(3):
                u = User(
                    twitch_id=f"tie{i}",
                    twitch_username=f"tie{i}",
                    api_token=f"tietok{i}",
                    role=UserRole.USER,
                )
                users.append(u)
            db.add_all(users)
            await db.flush()

            seed = Seed(
                seed_number="tie_seed",
                pool_name="standard",
                graph_json={"nodes": {}, "total_layers": 1},
                total_layers=1,
                folder_path="/t/tie",
                status=SeedStatus.CONSUMED,
            )
            db.add(seed)
            await db.flush()
            for r in range(3):
                race = Race(
                    name=f"TIE R{r}",
                    organizer_id=users[0].id,
                    seed_id=seed.id,
                    status=RaceStatus.FINISHED,
                )
                db.add(race)
                await db.flush()
                for j, u in enumerate(users):
                    db.add(
                        Participant(
                            race_id=race.id,
                            user_id=u.id,
                            mod_token=f"tie_{r}_{j}",
                            status=ParticipantStatus.FINISHED,
                            igt_ms=1_000_000,
                            death_count=0,
                        )
                    )

            # Player A is rank 1 on both rusher and explorer (same percentile),
            # but has higher raw rusher score
            scores_data = [
                (90, 10, 80, 10, 10, 10, 0),  # Player A: rank 1 rusher (90) AND explorer (80)
                (50, 10, 50, 10, 10, 10, 0),
                (20, 10, 20, 10, 10, 10, 0),
            ]
            for user, (ru, ca, ex, pf, bs, re, rq) in zip(users, scores_data):
                db.add(
                    PlayerTraitScores(
                        user_id=user.id,
                        rusher=ru,
                        cautious=ca,
                        explorer=ex,
                        pathfinder=pf,
                        boss_slayer=bs,
                        resilient=re,
                        rage_quitter=rq,
                        dominant_trait=None,
                    )
                )
            await db.commit()
            uid_a = users[0].id

        async with async_session() as db:
            await resolve_dominant_traits(db)

        async with async_session() as db:
            scores_a = await db.get(PlayerTraitScores, uid_a)
            # Same percentile on rusher and explorer, but rusher=90 > explorer=80
            assert scores_a.dominant_trait == "rusher"

    async def test_dominant_trait_cleared_when_below_threshold(self, async_session):
        """A user previously holding a dominant trait loses it when they no longer
        meet the finished-races threshold (e.g. data fix, race deletion)."""
        async with async_session() as db:
            user = User(
                twitch_id="clr",
                twitch_username="clr",
                api_token="clrtok",
                role=UserRole.USER,
            )
            db.add(user)
            await db.flush()

            seed = Seed(
                seed_number="clr_seed",
                pool_name="standard",
                graph_json={"nodes": {}, "total_layers": 1},
                total_layers=1,
                folder_path="/t/clr",
                status=SeedStatus.CONSUMED,
            )
            db.add(seed)
            await db.flush()
            # Only 2 finished participations: below MIN_RACES_FOR_TRAITS
            for r in range(2):
                race = Race(
                    name=f"CLR R{r}",
                    organizer_id=user.id,
                    seed_id=seed.id,
                    status=RaceStatus.FINISHED,
                )
                db.add(race)
                await db.flush()
                db.add(
                    Participant(
                        race_id=race.id,
                        user_id=user.id,
                        mod_token=f"clr_{r}",
                        status=ParticipantStatus.FINISHED,
                        igt_ms=1_000_000,
                        death_count=0,
                    )
                )

            db.add(
                PlayerTraitScores(
                    user_id=user.id,
                    rusher=80,
                    cautious=10,
                    explorer=10,
                    pathfinder=10,
                    boss_slayer=10,
                    resilient=10,
                    rage_quitter=0,
                    dominant_trait="rusher",
                    dominant_description="Top 10% among 5 players",
                )
            )
            await db.commit()
            uid = user.id

        async with async_session() as db:
            await resolve_dominant_traits(db)

        async with async_session() as db:
            scores = await db.get(PlayerTraitScores, uid)
            assert scores.dominant_trait is None

    async def test_get_player_profiles_includes_private_only_finishers(self, async_session):
        """get_player_profiles surfaces users whose finishes are all private
        (elo_races=0). The endpoint gates on dominant_trait, not public-race count."""
        from speedfog_racing.api.stats import get_player_profiles

        async with async_session() as db:
            private_user = User(
                twitch_id="priv",
                twitch_username="priv_player",
                api_token="privtok",
                role=UserRole.USER,
                elo_races=0,
            )
            no_dominant = User(
                twitch_id="nod",
                twitch_username="no_dominant",
                api_token="nodtok",
                role=UserRole.USER,
                elo_races=10,
            )
            db.add_all([private_user, no_dominant])
            await db.flush()

            db.add(
                PlayerTraitScores(
                    user_id=private_user.id,
                    rusher=70,
                    cautious=10,
                    explorer=10,
                    pathfinder=10,
                    boss_slayer=10,
                    resilient=10,
                    rage_quitter=0,
                    dominant_trait="rusher",
                    dominant_description="Top 10% among 5 players",
                )
            )
            db.add(
                PlayerTraitScores(
                    user_id=no_dominant.id,
                    rusher=10,
                    cautious=10,
                    explorer=10,
                    pathfinder=10,
                    boss_slayer=10,
                    resilient=10,
                    rage_quitter=0,
                    dominant_trait=None,
                )
            )
            await db.commit()

        async with async_session() as db:
            response = await get_player_profiles(db)

        rusher_usernames = [p.twitch_username for p in response.profiles.get("rusher", [])]
        assert "priv_player" in rusher_usernames
        for entries in response.profiles.values():
            assert "no_dominant" not in [p.twitch_username for p in entries]

    async def test_upserts_on_recompute(self, async_session, three_races_with_zone_history):
        """Running update_player_traits again should update, not duplicate."""
        race_ids, user_ids = three_races_with_zone_history
        for rid in race_ids:
            async with async_session() as db:
                await update_player_traits(rid, db)

        # Run again on the last race
        async with async_session() as db:
            await update_player_traits(race_ids[-1], db)

        async with async_session() as db:
            # Should still have exactly one row per user
            from sqlalchemy import func as sqlfunc

            count = (
                await db.execute(select(sqlfunc.count()).select_from(PlayerTraitScores))
            ).scalar()
            assert count == 3  # One per user, not duplicated

    async def test_end_to_end_traits_with_percentile(
        self, async_session, three_races_with_zone_history
    ):
        """Full flow: compute raw traits then resolve dominant via percentile."""
        race_ids, user_ids = three_races_with_zone_history

        # Compute raw scores for all 3 races
        for rid in race_ids:
            async with async_session() as db:
                await update_player_traits(rid, db)

        # Resolve dominant traits via percentile
        async with async_session() as db:
            await resolve_dominant_traits(db)

        async with async_session() as db:
            scores = {}
            for uid in user_ids:
                scores[uid] = await db.get(PlayerTraitScores, uid)

            # Player 0 (rusher): should have rusher as dominant (ranks best on it)
            p0 = scores[user_ids[0]]
            assert p0.rusher > 0
            assert p0.dominant_trait is not None
            assert p0.dominant_description is not None
            assert "3" in p0.dominant_description  # "among 3 players"

            # Player 1 (cautious/explorer): should NOT have boss_slayer dominant
            # (which was the old bug with raw-score selection)
            p1 = scores[user_ids[1]]
            assert p1.dominant_trait is not None
            assert p1.dominant_trait in ("cautious", "explorer", "pathfinder")


class TestZoneStatsAggregation:
    async def test_aggregate_zone_stats_counts_deaths(
        self, async_session, three_races_with_zone_history
    ):
        """Zone aggregation should sum deaths and filter by dungeon types only."""
        race_ids, user_ids = three_races_with_zone_history
        async with async_session() as db:
            participants = (
                (
                    await db.execute(
                        select(Participant)
                        .where(Participant.status == ParticipantStatus.FINISHED)
                        .options(
                            selectinload(Participant.race).selectinload(Race.seed),
                        )
                    )
                )
                .scalars()
                .all()
            )
            seeds_by_id = {}
            for p in participants:
                if p.race and p.race.seed:
                    seeds_by_id[p.race.seed_id] = p.race.seed

            node_display = _resolve_node_display(seeds_by_id)
            zone_data = _aggregate_zone_stats(
                participants, seeds_by_id, DUNGEON_NODE_TYPES, node_display
            )

            # stormveil_c3d4 is legacy_dungeon, should be included
            assert any("Stormveil" in name for name in zone_data)
            # cave_e5f6 is mini_dungeon, should be included
            assert any("Coastal" in name for name in zone_data)
            # margit_g7h8 is boss_arena, should be excluded from dungeon stats
            assert not any("Margit" in name for name in zone_data)
            # final_k1l2 is final_boss, should be excluded
            assert not any("Loretta" in name for name in zone_data)

    async def test_aggregate_zone_stats_computes_times(
        self, async_session, three_races_with_zone_history
    ):
        """Time should be computed as difference between consecutive igt_ms entries."""
        race_ids, user_ids = three_races_with_zone_history
        async with async_session() as db:
            participants = (
                (
                    await db.execute(
                        select(Participant)
                        .where(Participant.status == ParticipantStatus.FINISHED)
                        .options(
                            selectinload(Participant.race).selectinload(Race.seed),
                        )
                    )
                )
                .scalars()
                .all()
            )
            seeds_by_id = {}
            for p in participants:
                if p.race and p.race.seed:
                    seeds_by_id[p.race.seed_id] = p.race.seed

            node_display = _resolve_node_display(seeds_by_id)
            zone_data = _aggregate_zone_stats(
                participants, seeds_by_id, DUNGEON_NODE_TYPES, node_display
            )

            # Each zone should have time entries with positive values
            for name, data in zone_data.items():
                assert data["times"], f"Zone {name} should have time entries"
                for t in data["times"]:
                    assert t > 0, f"Zone {name} has non-positive time {t}"

    async def test_aggregate_zone_stats_includes_zones_union(
        self, async_session, three_races_with_zone_history
    ):
        """Each merged entry's 'zones' is the sorted union of its contributors'
        zones. No two node_ids share a display_name in this fixture, so the
        union degenerates to each node's own zones list.
        """
        race_ids, user_ids = three_races_with_zone_history
        async with async_session() as db:
            participants = (
                (
                    await db.execute(
                        select(Participant)
                        .where(Participant.status == ParticipantStatus.FINISHED)
                        .options(
                            selectinload(Participant.race).selectinload(Race.seed),
                        )
                    )
                )
                .scalars()
                .all()
            )
            seeds_by_id = {}
            for p in participants:
                if p.race and p.race.seed:
                    seeds_by_id[p.race.seed_id] = p.race.seed

            node_display = _resolve_node_display(seeds_by_id)
            zone_data = _aggregate_zone_stats(
                participants, seeds_by_id, DUNGEON_NODE_TYPES, node_display
            )

            assert zone_data["Stormveil Castle"]["zones"] == ["stormveil", "stormveil_gate"]
            assert zone_data["Coastal Cave"]["zones"] == ["coastal_cave"]

    async def test_resolve_node_display_tolerates_missing_zones_key(self, async_session):
        """A graph node without a 'zones' key resolves to an empty list, not
        a KeyError: older/hand-authored seed graphs may not carry it.
        """
        graph_json = {
            "nodes": {
                "no_zones_key_ab12": {"type": "legacy_dungeon", "display_name": "No Zones"},
            },
            "total_layers": 1,
        }
        async with async_session() as db:
            org = User(
                twitch_id="nzorg",
                twitch_username="nzorg",
                api_token="nzorgt",
                role=UserRole.ORGANIZER,
            )
            db.add(org)
            await db.flush()
            seed = Seed(
                seed_number="nzseed",
                pool_name="standard",
                graph_json=graph_json,
                total_layers=1,
                folder_path="/t/nzseed",
                status=SeedStatus.CONSUMED,
            )
            db.add(seed)
            await db.commit()
            seed_id = seed.id

        async with async_session() as db:
            seed = (await db.execute(select(Seed).where(Seed.id == seed_id))).scalar_one()
            node_display = _resolve_node_display({seed_id: seed})
        info = node_display["no_zones_key_ab12"]
        assert (info.short_name, info.full_name, info.type, info.zones) == (
            "No Zones",
            "No Zones",
            "legacy_dungeon",
            [],
        )

    async def test_panels_use_short_name_index_and_detail_use_full_name(self, async_session):
        """A node whose full display_name contains an area prefix ('Ancient
        Ruins of Rauh - East') should surface the SHORT name ('East') on the
        top-5 panels (/stats/zones) but the FULL name everywhere else (the
        zone codex index and detail sheet).
        """
        graph_json = {
            "nodes": {
                "start_a1b2": {"type": "start", "display_name": "Chapel", "layer": 0},
                "rauh_x1y1": {
                    "type": "legacy_dungeon",
                    "display_name": "Ancient Ruins of Rauh - East",
                    "layer": 1,
                    "zones": ["rauh_east"],
                },
            },
            "total_layers": 2,
        }
        async with async_session() as db:
            user = User(
                twitch_id="pnu", twitch_username="pnu", api_token="pnut", role=UserRole.USER
            )
            org = User(
                twitch_id="pnorg",
                twitch_username="pnorg",
                api_token="pnorgt",
                role=UserRole.ORGANIZER,
            )
            db.add_all([user, org])
            await db.flush()

            seed = Seed(
                seed_number="pnseed",
                pool_name="standard",
                graph_json=graph_json,
                total_layers=2,
                folder_path="/t/pnseed",
                status=SeedStatus.CONSUMED,
            )
            db.add(seed)
            await db.flush()

            race = Race(
                name="Panel Naming Race",
                organizer_id=org.id,
                seed_id=seed.id,
                status=RaceStatus.FINISHED,
                started_at=datetime.now(UTC),
            )
            db.add(race)
            await db.flush()

            db.add(
                Participant(
                    race_id=race.id,
                    user_id=user.id,
                    mod_token="pnmod",
                    status=ParticipantStatus.FINISHED,
                    igt_ms=200_000,
                    death_count=2,
                    zone_history=[
                        {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                        {"node_id": "rauh_x1y1", "igt_ms": 100_000, "deaths": 2},
                    ],
                )
            )
            await db.commit()

        async with async_session() as db:
            panels = await get_zone_stats(pool=None, days=3650, db=db)
        async with async_session() as db:
            index = await get_zone_index(pool=None, days=3650, db=db)
        async with async_session() as db:
            detail = await get_zone_detail(node_id="rauh_x1y1", pool=None, days=3650, db=db)

        panel_names = {e.display_name for e in panels.deadliest}
        assert "East" in panel_names
        assert "Ancient Ruins of Rauh - East" not in panel_names

        index_entry = next(z for z in index.zones if z.node_id == "rauh_x1y1")
        assert index_entry.display_name == "Ancient Ruins of Rauh - East"

        assert detail.display_name == "Ancient Ruins of Rauh - East"

    async def test_aggregate_zone_stats_ignores_plain_revisits(
        self, async_session, three_races_with_zone_history
    ):
        """Player 1 re-enters stormveil via a plain fog entry: transit through an
        already-visited zone is not a backtrack. Only entries preceding a
        type "backtrack" entry count (the zone the player turned away from).
        """
        race_ids, user_ids = three_races_with_zone_history
        async with async_session() as db:
            participants = (
                (
                    await db.execute(
                        select(Participant)
                        .where(Participant.status == ParticipantStatus.FINISHED)
                        .options(
                            selectinload(Participant.race).selectinload(Race.seed),
                        )
                    )
                )
                .scalars()
                .all()
            )
            seeds_by_id = {}
            for p in participants:
                if p.race and p.race.seed:
                    seeds_by_id[p.race.seed_id] = p.race.seed

            node_display = _resolve_node_display(seeds_by_id)
            zone_data = _aggregate_zone_stats(
                participants, seeds_by_id, DUNGEON_NODE_TYPES, node_display
            )

            stormveil = next((d for n, d in zone_data.items() if "Stormveil" in n), None)
            assert stormveil is not None
            assert stormveil["backtrack_count"] == 0


class TestZoneIndexEndpoint:
    async def test_index_lists_dungeon_zones_sorted(
        self, async_session, three_races_with_zone_history
    ):
        async with async_session() as db:
            result = await get_zone_index(pool=None, days=3650, db=db)
        names = [z.display_name for z in result.zones]
        assert names == sorted(names)
        types = {z.type for z in result.zones}
        assert types <= {"legacy_dungeon", "mini_dungeon"}
        stormveil = next(z for z in result.zones if z.node_id == "stormveil_c3d4")
        assert stormveil.visits > 0
        assert stormveil.avg_time_ms > 0
        assert stormveil.zones == ["stormveil", "stormveil_gate"]

    async def test_index_excludes_boss_arenas(self, async_session, three_races_with_zone_history):
        async with async_session() as db:
            result = await get_zone_index(pool=None, days=3650, db=db)
        assert all(z.node_id != "margit_g7h8" for z in result.zones)

    async def test_no_merge_when_full_names_differ_but_share_last_segment(self, async_session):
        """Regression: two DIFFERENT physical locations whose full display_name
        happens to end in the same area segment ('Foo Ruins - East' and 'Bar
        Caves - East') must NOT be merged into a single index row. Merging is
        keyed on the full display_name, not the shortened last segment.
        """
        graph_json = {
            "nodes": {
                "start_a1b2": {"type": "start", "display_name": "Chapel", "layer": 0},
                "foo_f1f1": {
                    "type": "legacy_dungeon",
                    "display_name": "Foo Ruins - East",
                    "layer": 1,
                    "zones": ["foo_east"],
                },
                "bar_b2b2": {
                    "type": "legacy_dungeon",
                    "display_name": "Bar Caves - East",
                    "layer": 1,
                    "zones": ["bar_east"],
                },
            },
            "total_layers": 2,
        }
        async with async_session() as db:
            user_a = User(
                twitch_id="nma", twitch_username="nma", api_token="nmat", role=UserRole.USER
            )
            user_b = User(
                twitch_id="nmb", twitch_username="nmb", api_token="nmbt", role=UserRole.USER
            )
            org = User(
                twitch_id="nmorg",
                twitch_username="nmorg",
                api_token="nmorgt",
                role=UserRole.ORGANIZER,
            )
            db.add_all([user_a, user_b, org])
            await db.flush()

            seed = Seed(
                seed_number="nmseed",
                pool_name="standard",
                graph_json=graph_json,
                total_layers=2,
                folder_path="/t/nmseed",
                status=SeedStatus.CONSUMED,
            )
            db.add(seed)
            await db.flush()

            race = Race(
                name="No False Merge Race",
                organizer_id=org.id,
                seed_id=seed.id,
                status=RaceStatus.FINISHED,
                started_at=datetime.now(UTC),
            )
            db.add(race)
            await db.flush()

            db.add(
                Participant(
                    race_id=race.id,
                    user_id=user_a.id,
                    mod_token="nmmoda",
                    status=ParticipantStatus.FINISHED,
                    igt_ms=200_000,
                    death_count=1,
                    zone_history=[
                        {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                        {"node_id": "foo_f1f1", "igt_ms": 100_000, "deaths": 1},
                    ],
                )
            )
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=user_b.id,
                    mod_token="nmmodb",
                    status=ParticipantStatus.FINISHED,
                    igt_ms=250_000,
                    death_count=3,
                    zone_history=[
                        {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                        {"node_id": "bar_b2b2", "igt_ms": 120_000, "deaths": 3},
                    ],
                )
            )
            await db.commit()

        async with async_session() as db:
            result = await get_zone_index(pool=None, days=3650, db=db)

        names = {z.display_name for z in result.zones}
        assert "Foo Ruins - East" in names
        assert "Bar Caves - East" in names
        matching = [z for z in result.zones if z.node_id in ("foo_f1f1", "bar_b2b2")]
        assert len(matching) == 2


class TestZoneDetailEndpoint:
    """Fixture graph: stormveil_c3d4 is legacy_dungeon with visits and backtracks,
    margit_g7h8 is boss_arena (excluded from the dungeon codex).
    """

    GRAPH_WITH_UNVISITED_DUNGEON = {
        "nodes": {
            "start_a1b2": {"type": "start", "display_name": "Chapel", "layer": 0},
            "stormveil_c3d4": {
                "type": "legacy_dungeon",
                "display_name": "Stormveil Castle",
                "layer": 1,
            },
            "unvisited_z9z9": {
                "type": "legacy_dungeon",
                "display_name": "Unvisited Ruins",
                "layer": 2,
                "zones": ["unvisited_ruins"],
            },
        },
        "total_layers": 3,
    }

    async def test_detail_returns_aggregates(self, async_session, three_races_with_zone_history):
        async with async_session() as db:
            detail = await get_zone_detail(node_id="stormveil_c3d4", pool=None, days=3650, db=db)
        assert detail.node_id == "stormveil_c3d4"
        assert detail.type == "legacy_dungeon"
        assert detail.visits > 0
        assert detail.avg_time_ms is not None and detail.avg_time_ms > 0
        assert 0 <= detail.backtrack_rate
        assert detail.zones == ["stormveil", "stormveil_gate"]

    async def test_detail_404_for_unknown_node(self, async_session, three_races_with_zone_history):
        async with async_session() as db:
            with pytest.raises(HTTPException) as exc:
                await get_zone_detail(node_id="nonexistent_ffff", pool=None, days=3650, db=db)
        assert exc.value.status_code == 404

    async def test_detail_404_for_boss_arena(self, async_session, three_races_with_zone_history):
        async with async_session() as db:
            with pytest.raises(HTTPException) as exc:
                await get_zone_detail(node_id="margit_g7h8", pool=None, days=3650, db=db)
        assert exc.value.status_code == 404

    async def test_detail_zeroed_stats_for_zone_with_no_visits(self, async_session):
        """A dungeon node listed in the seed graph but never visited returns
        zeroed stats (not a 404): the zone exists, nobody has been there yet.
        """
        async with async_session() as db:
            user = User(
                twitch_id="zdu",
                twitch_username="zdu",
                api_token="zdut",
                role=UserRole.USER,
            )
            org = User(
                twitch_id="zdorg",
                twitch_username="zdorg",
                api_token="zdorgt",
                role=UserRole.ORGANIZER,
            )
            db.add_all([user, org])
            await db.flush()

            seed = Seed(
                seed_number="zdseed",
                pool_name="standard",
                graph_json=self.GRAPH_WITH_UNVISITED_DUNGEON,
                total_layers=3,
                folder_path="/t/zdseed",
                status=SeedStatus.CONSUMED,
            )
            db.add(seed)
            await db.flush()

            race = Race(
                name="Zero Visits Race",
                organizer_id=org.id,
                seed_id=seed.id,
                status=RaceStatus.FINISHED,
                started_at=datetime.now(UTC),
            )
            db.add(race)
            await db.flush()

            db.add(
                Participant(
                    race_id=race.id,
                    user_id=user.id,
                    mod_token="zdmod",
                    status=ParticipantStatus.FINISHED,
                    igt_ms=500_000,
                    death_count=1,
                    zone_history=[
                        {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                        {"node_id": "stormveil_c3d4", "igt_ms": 300_000, "deaths": 1},
                    ],
                )
            )
            await db.commit()

        async with async_session() as db:
            detail = await get_zone_detail(node_id="unvisited_z9z9", pool=None, days=3650, db=db)
        assert detail.node_id == "unvisited_z9z9"
        assert detail.display_name == "Unvisited Ruins"
        assert detail.type == "legacy_dungeon"
        assert detail.visits == 0
        assert detail.race_count == 0
        assert detail.avg_time_ms is None
        assert detail.avg_deaths_per_visit == 0.0
        assert detail.backtrack_rate == 0.0
        assert detail.zones == ["unvisited_ruins"]

    MERGED_CLUSTER_GRAPH = {
        "nodes": {
            "start_a1b2": {"type": "start", "display_name": "Chapel", "layer": 0},
            "stormveil_c3d4": {
                "type": "legacy_dungeon",
                "display_name": "Stormveil Castle",
                "layer": 1,
                "zones": ["stormveil", "stormveil_gate"],
            },
            "stormveil_alt99": {
                "type": "legacy_dungeon",
                "display_name": "Stormveil Castle",
                "layer": 1,
                "zones": ["stormveil", "stormveil_rooftops"],
            },
        },
        "total_layers": 2,
    }

    async def test_detail_echoes_requested_id_for_merged_cluster(self, async_session):
        """stormveil_c3d4 and stormveil_alt99 are two distinct cluster ids that
        share a display_name (asymmetric drop connectivity), so
        _aggregate_zone_stats merges them into one aggregate. Each id must
        still echo back its own requested node_id, not the merge's
        internal representative id, while sharing the same merged stats.

        Their zone compositions differ (asymmetric connectivity means each
        cluster variant reaches a different zone set): the detail response
        must reflect each sibling's OWN zones, not the merged union.
        """
        async with async_session() as db:
            user_a = User(
                twitch_id="mca", twitch_username="mca", api_token="mcat", role=UserRole.USER
            )
            user_b = User(
                twitch_id="mcb", twitch_username="mcb", api_token="mcbt", role=UserRole.USER
            )
            org = User(
                twitch_id="mcorg",
                twitch_username="mcorg",
                api_token="mcorgt",
                role=UserRole.ORGANIZER,
            )
            db.add_all([user_a, user_b, org])
            await db.flush()

            seed = Seed(
                seed_number="mcseed",
                pool_name="standard",
                graph_json=self.MERGED_CLUSTER_GRAPH,
                total_layers=2,
                folder_path="/t/mcseed",
                status=SeedStatus.CONSUMED,
            )
            db.add(seed)
            await db.flush()

            race = Race(
                name="Merged Cluster Race",
                organizer_id=org.id,
                seed_id=seed.id,
                status=RaceStatus.FINISHED,
                started_at=datetime.now(UTC),
            )
            db.add(race)
            await db.flush()

            db.add(
                Participant(
                    race_id=race.id,
                    user_id=user_a.id,
                    mod_token="mcmoda",
                    status=ParticipantStatus.FINISHED,
                    igt_ms=500_000,
                    death_count=1,
                    zone_history=[
                        {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                        {"node_id": "stormveil_c3d4", "igt_ms": 100_000, "deaths": 1},
                    ],
                )
            )
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=user_b.id,
                    mod_token="mcmodb",
                    status=ParticipantStatus.FINISHED,
                    igt_ms=600_000,
                    death_count=2,
                    zone_history=[
                        {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                        {"node_id": "stormveil_alt99", "igt_ms": 150_000, "deaths": 2},
                    ],
                )
            )
            await db.commit()

        async with async_session() as db:
            detail_a = await get_zone_detail(node_id="stormveil_c3d4", pool=None, days=3650, db=db)
        async with async_session() as db:
            detail_b = await get_zone_detail(node_id="stormveil_alt99", pool=None, days=3650, db=db)

        # Each response echoes the id that was actually requested.
        assert detail_a.node_id == "stormveil_c3d4"
        assert detail_b.node_id == "stormveil_alt99"
        # But both resolve to the same merged aggregate under the hood.
        assert detail_a.display_name == detail_b.display_name == "Stormveil Castle"
        assert detail_a.visits == detail_b.visits == 2
        assert detail_a.race_count == detail_b.race_count == 1
        assert detail_a.avg_deaths_per_visit == detail_b.avg_deaths_per_visit == 1.5
        assert detail_a.avg_time_ms == detail_b.avg_time_ms == 425_000
        # Each sibling's own composition, not the merged union.
        assert detail_a.zones == ["stormveil", "stormveil_gate"]
        assert detail_b.zones == ["stormveil", "stormveil_rooftops"]

    async def test_index_zones_is_union_of_merged_siblings(self, async_session):
        """The index entry for a merged display_name exposes the union of all
        contributing siblings' zones (unlike detail, which echoes only the
        requested sibling's own composition).
        """
        async with async_session() as db:
            user_a = User(
                twitch_id="iua", twitch_username="iua", api_token="iuat", role=UserRole.USER
            )
            user_b = User(
                twitch_id="iub", twitch_username="iub", api_token="iubt", role=UserRole.USER
            )
            org = User(
                twitch_id="iuorg",
                twitch_username="iuorg",
                api_token="iuorgt",
                role=UserRole.ORGANIZER,
            )
            db.add_all([user_a, user_b, org])
            await db.flush()

            seed = Seed(
                seed_number="iuseed",
                pool_name="standard",
                graph_json=self.MERGED_CLUSTER_GRAPH,
                total_layers=2,
                folder_path="/t/iuseed",
                status=SeedStatus.CONSUMED,
            )
            db.add(seed)
            await db.flush()

            race = Race(
                name="Index Union Race",
                organizer_id=org.id,
                seed_id=seed.id,
                status=RaceStatus.FINISHED,
                started_at=datetime.now(UTC),
            )
            db.add(race)
            await db.flush()

            db.add(
                Participant(
                    race_id=race.id,
                    user_id=user_a.id,
                    mod_token="iumoda",
                    status=ParticipantStatus.FINISHED,
                    igt_ms=500_000,
                    death_count=1,
                    zone_history=[
                        {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                        {"node_id": "stormveil_c3d4", "igt_ms": 100_000, "deaths": 1},
                    ],
                )
            )
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=user_b.id,
                    mod_token="iumodb",
                    status=ParticipantStatus.FINISHED,
                    igt_ms=600_000,
                    death_count=2,
                    zone_history=[
                        {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                        {"node_id": "stormveil_alt99", "igt_ms": 150_000, "deaths": 2},
                    ],
                )
            )
            await db.commit()

        async with async_session() as db:
            result = await get_zone_index(pool=None, days=3650, db=db)
        stormveil = next(z for z in result.zones if z.display_name == "Stormveil Castle")
        assert stormveil.zones == ["stormveil", "stormveil_gate", "stormveil_rooftops"]


class TestZoneEntriesCarryNodeId:
    async def test_zone_stats_entries_have_node_id(
        self, async_session, three_races_with_zone_history
    ):
        async with async_session() as db:
            result = await get_zone_stats(pool=None, days=3650, db=db)
        for entry in [
            *result.deadliest,
            *result.most_backtracked,
            *result.slowest,
            *result.fastest,
        ]:
            assert entry.node_id


class TestBossStatsFiltering:
    async def test_boss_stats_excludes_boss_arena(
        self, async_session, three_races_with_zone_history
    ):
        """Boss stats should only include major_boss and final_boss, not boss_arena."""
        race_ids, user_ids = three_races_with_zone_history
        async with async_session() as db:
            participants = (
                (
                    await db.execute(
                        select(Participant)
                        .where(Participant.status == ParticipantStatus.FINISHED)
                        .options(
                            selectinload(Participant.race).selectinload(Race.seed),
                        )
                    )
                )
                .scalars()
                .all()
            )
            seeds_by_id = {}
            for p in participants:
                if p.race and p.race.seed:
                    seeds_by_id[p.race.seed_id] = p.race.seed

            node_display = _resolve_node_display(seeds_by_id)

            # Verify type resolution
            for nid, info in node_display.items():
                if "final" in nid:
                    assert info.type == "final_boss"
                if "margit" in nid:
                    # boss_arena should NOT be in stats.py BOSS_NODE_TYPES
                    assert info.type == "boss_arena"
                    assert info.type not in BOSS_NODE_TYPES

    async def test_boss_stats_uses_boss_name_field(self, async_session):
        """Stats should prefer boss_name over randomized_boss and display_name."""
        graph_json = {
            "nodes": {
                "start_a1b2": {"type": "start", "display_name": "Chapel", "layer": 0},
                "loretta_661f": {
                    "type": "major_boss",
                    "display_name": "Royal Knight Loretta",
                    "boss_name": "Godskin Noble",
                    "randomized_bosses": ["Godskin Noble Boss"],
                    "layer": 1,
                },
                "gideon_x1y2": {
                    "type": "major_boss",
                    "display_name": "Ashen Leyndell - Gideon",
                    "boss_name": "Sir Gideon Ofnir, the All-Knowing",
                    "layer": 2,
                },
                "final_k1l2": {
                    "type": "final_boss",
                    "display_name": "Elden Beast",
                    "boss_name": "Elden Beast",
                    "layer": 3,
                },
            },
            "total_layers": 4,
        }

        async with async_session() as db:
            user = User(
                twitch_id="bn1",
                twitch_username="bnplayer",
                api_token="bnt1",
                role=UserRole.USER,
            )
            org = User(
                twitch_id="bnorg",
                twitch_username="bnorg",
                api_token="bntorg",
                role=UserRole.ORGANIZER,
            )
            db.add_all([user, org])
            await db.flush()

            seed = Seed(
                seed_number="bn_seed",
                pool_name="standard",
                graph_json=graph_json,
                total_layers=4,
                folder_path="/t/bn_seed",
                status=SeedStatus.CONSUMED,
            )
            db.add(seed)
            await db.flush()

            race = Race(
                name="Boss Name Race",
                organizer_id=org.id,
                seed_id=seed.id,
                status=RaceStatus.FINISHED,
                started_at=datetime.now(UTC),
            )
            db.add(race)
            await db.flush()

            db.add(
                Participant(
                    race_id=race.id,
                    user_id=user.id,
                    mod_token="bnmod",
                    status=ParticipantStatus.FINISHED,
                    igt_ms=2_000_000,
                    death_count=8,
                    zone_history=[
                        {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                        {"node_id": "loretta_661f", "igt_ms": 500_000, "deaths": 3},
                        {"node_id": "gideon_x1y2", "igt_ms": 1_000_000, "deaths": 3},
                        {"node_id": "final_k1l2", "igt_ms": 1_500_000, "deaths": 2},
                    ],
                )
            )
            await db.commit()

        from speedfog_racing.api.stats import get_boss_stats

        async with async_session() as db:
            result = await get_boss_stats(pool=None, db=db)

        boss_names = {b.display_name for b in result.bosses}

        # boss_name takes priority over randomized_bosses and display_name
        assert "Godskin Noble" in boss_names
        assert "Sir Gideon Ofnir, the All-Knowing" in boss_names
        assert "Elden Beast" in boss_names
        # These should NOT appear
        assert "Godskin Noble Boss" not in boss_names
        assert "Gideon" not in boss_names


class TestAbandonCountsAsBack:
    """Abandoning a race should count as a backtrack for the last zone/boss."""

    GRAPH_JSON = {
        "nodes": {
            "start_a1b2": {"type": "start", "display_name": "Chapel", "layer": 0},
            "stormveil_c3d4": {
                "type": "legacy_dungeon",
                "display_name": "Stormveil Castle",
                "layer": 1,
            },
            "raya_i9j0": {
                "type": "legacy_dungeon",
                "display_name": "Raya Lucaria",
                "layer": 2,
            },
            "godrick_m1n2": {
                "type": "major_boss",
                "display_name": "Godrick",
                "layer": 3,
            },
        },
        "total_layers": 4,
    }

    async def _make_participant(self, db, *, status, zone_history, igt_ms=1_000_000, suffix="ab"):
        """Helper: create user + seed + race + participant."""
        user = User(
            twitch_id=f"ab_{suffix}",
            twitch_username=f"ab_{suffix}",
            api_token=f"abt_{suffix}",
            role=UserRole.USER,
        )
        org = User(
            twitch_id=f"aborg_{suffix}",
            twitch_username=f"aborg_{suffix}",
            api_token=f"aborgt_{suffix}",
            role=UserRole.ORGANIZER,
        )
        db.add_all([user, org])
        await db.flush()

        seed = Seed(
            seed_number=f"abs_{suffix}",
            pool_name="standard",
            graph_json=self.GRAPH_JSON,
            total_layers=4,
            folder_path=f"/t/abs_{suffix}",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name=f"Abandon Race {suffix}",
            organizer_id=org.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        participant = Participant(
            race_id=race.id,
            user_id=user.id,
            mod_token=f"abmod_{suffix}",
            status=status,
            igt_ms=igt_ms,
            death_count=sum(e.get("deaths", 0) for e in zone_history),
            zone_history=zone_history,
        )
        db.add(participant)
        await db.commit()
        return participant

    async def test_zone_abandon_first_visit_counts_as_backtrack(self, async_session):
        """Abandon on a first-visit zone should add +1 backtrack."""
        async with async_session() as db:
            await self._make_participant(
                db,
                status=ParticipantStatus.ABANDONED,
                zone_history=[
                    {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                    {"node_id": "stormveil_c3d4", "igt_ms": 300_000, "deaths": 2},
                    {"node_id": "raya_i9j0", "igt_ms": 700_000, "deaths": 1},
                ],
                suffix="z1",
            )

        async with async_session() as db:
            participants = (
                (
                    await db.execute(
                        select(Participant).options(
                            selectinload(Participant.race).selectinload(Race.seed),
                        )
                    )
                )
                .scalars()
                .all()
            )
            seeds_by_id = {
                p.race.seed_id: p.race.seed for p in participants if p.race and p.race.seed
            }
            node_display = _resolve_node_display(seeds_by_id)
            zone_data = _aggregate_zone_stats(
                participants, seeds_by_id, DUNGEON_NODE_TYPES, node_display
            )

            raya = next((d for n, d in zone_data.items() if "Raya" in n), None)
            assert raya is not None
            assert raya["backtrack_count"] == 1

    async def test_zone_abandon_revisit_no_double_count(self, async_session):
        """Abandon on a revisited zone should NOT add a backtrack: the abandon
        rule only credits first-visit zones, and a plain fog re-entry is not
        a backtrack either."""
        async with async_session() as db:
            await self._make_participant(
                db,
                status=ParticipantStatus.ABANDONED,
                zone_history=[
                    {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                    {"node_id": "stormveil_c3d4", "igt_ms": 300_000, "deaths": 2},
                    {"node_id": "raya_i9j0", "igt_ms": 700_000, "deaths": 1},
                    # Return to stormveil via a fog gate, then abandon there
                    {"node_id": "stormveil_c3d4", "igt_ms": 1_000_000, "deaths": 0},
                ],
                suffix="z2",
            )

        async with async_session() as db:
            participants = (
                (
                    await db.execute(
                        select(Participant).options(
                            selectinload(Participant.race).selectinload(Race.seed),
                        )
                    )
                )
                .scalars()
                .all()
            )
            seeds_by_id = {
                p.race.seed_id: p.race.seed for p in participants if p.race and p.race.seed
            }
            node_display = _resolve_node_display(seeds_by_id)
            zone_data = _aggregate_zone_stats(
                participants, seeds_by_id, DUNGEON_NODE_TYPES, node_display
            )

            stormveil = next((d for n, d in zone_data.items() if "Stormveil" in n), None)
            assert stormveil is not None
            assert stormveil["backtrack_count"] == 0

    async def test_boss_abandon_counts_as_back(self, async_session):
        """Abandon on a boss (last entry) should set backed_last_visit=True."""
        async with async_session() as db:
            await self._make_participant(
                db,
                status=ParticipantStatus.ABANDONED,
                zone_history=[
                    {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                    {"node_id": "stormveil_c3d4", "igt_ms": 300_000, "deaths": 2},
                    {"node_id": "godrick_m1n2", "igt_ms": 700_000, "deaths": 5},
                ],
                suffix="b1",
            )

        from speedfog_racing.api.stats import get_boss_stats

        async with async_session() as db:
            result = await get_boss_stats(pool=None, db=db)

        godrick = next((b for b in result.bosses if b.display_name == "Godrick"), None)
        assert godrick is not None
        assert godrick.encounters == 1
        assert godrick.back_ratio == 1.0

    async def test_boss_abandon_not_last_entry_uses_normal_logic(self, async_session):
        """If abandoned but boss is NOT the last entry, normal backtrack logic applies."""
        async with async_session() as db:
            await self._make_participant(
                db,
                status=ParticipantStatus.ABANDONED,
                zone_history=[
                    {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                    {"node_id": "godrick_m1n2", "igt_ms": 300_000, "deaths": 5},
                    # Moved to a new zone (raya), then abandoned there
                    {"node_id": "raya_i9j0", "igt_ms": 700_000, "deaths": 1},
                ],
                suffix="b2",
            )

        from speedfog_racing.api.stats import get_boss_stats

        async with async_session() as db:
            result = await get_boss_stats(pool=None, db=db)

        godrick = next((b for b in result.bosses if b.display_name == "Godrick"), None)
        assert godrick is not None
        # raya_i9j0 was NOT visited before godrick, so no backtrack
        assert godrick.back_ratio == 0.0

    async def test_boss_multi_visit_sums_deaths_per_player(self, async_session):
        """A player who fights a boss across multiple visits should be counted once,
        with deaths summed (not treated as separate encounters per visit)."""
        async with async_session() as db:
            await self._make_participant(
                db,
                status=ParticipantStatus.FINISHED,
                zone_history=[
                    {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                    {"node_id": "godrick_m1n2", "igt_ms": 300_000, "deaths": 50},
                    # Backs out to a previously-visited zone, then returns to fight again
                    {"node_id": "start_a1b2", "igt_ms": 500_000, "deaths": 0},
                    {"node_id": "godrick_m1n2", "igt_ms": 700_000, "deaths": 40},
                    {"node_id": "raya_i9j0", "igt_ms": 900_000, "deaths": 1},
                ],
                suffix="mv1",
            )

        from speedfog_racing.api.stats import get_boss_stats

        async with async_session() as db:
            result = await get_boss_stats(pool=None, db=db)

        godrick = next((b for b in result.bosses if b.display_name == "Godrick"), None)
        assert godrick is not None
        # One player encountered the boss once, even across multiple visits
        assert godrick.encounters == 1
        # Deaths sum across fight visits: 50 + 40 = 90
        assert godrick.max_deaths == 90
        assert godrick.avg_deaths == 90.0

    async def test_boss_pure_backtrack_visitor_not_counted(self, async_session):
        """A player who only passes through a boss arena (0-death backtrack) should
        not count as an encounter."""
        async with async_session() as db:
            await self._make_participant(
                db,
                status=ParticipantStatus.FINISHED,
                zone_history=[
                    {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                    {"node_id": "stormveil_c3d4", "igt_ms": 300_000, "deaths": 2},
                    # Walks into godrick (0 deaths) then immediately backs to stormveil
                    {"node_id": "godrick_m1n2", "igt_ms": 500_000, "deaths": 0},
                    {"node_id": "stormveil_c3d4", "igt_ms": 550_000, "deaths": 0},
                ],
                suffix="pb1",
            )

        from speedfog_racing.api.stats import get_boss_stats

        async with async_session() as db:
            result = await get_boss_stats(pool=None, db=db)

        godrick = next((b for b in result.bosses if b.display_name == "Godrick"), None)
        # Pure-backtrack visitor: boss should not appear in stats at all
        assert godrick is None


class TestZoneBacktrackRule:
    """A zone is backtracked when the player turns away from it: its entry
    immediately precedes a type "backtrack" entry, unless the player comes
    right back to it (death/quit-out runback) or the preceding entry is
    itself a backtrack landing."""

    GRAPH_JSON = {
        "nodes": {
            "start_a1b2": {"type": "start", "display_name": "Chapel", "layer": 0},
            "stormveil_c3d4": {
                "type": "legacy_dungeon",
                "display_name": "Stormveil Castle",
                "layer": 1,
            },
            "raya_i9j0": {
                "type": "legacy_dungeon",
                "display_name": "Raya Lucaria",
                "layer": 2,
            },
            "cave_e5f6": {
                "type": "mini_dungeon",
                "display_name": "Coastal Cave",
                "layer": 2,
            },
            "godrick_m1n2": {
                "type": "major_boss",
                "display_name": "Godrick",
                "layer": 3,
            },
        },
        "total_layers": 4,
    }

    async def _make_participant(self, db, *, zone_history, suffix):
        """Helper: create user + seed + race + finished participant."""
        user = User(
            twitch_id=f"bt_{suffix}",
            twitch_username=f"bt_{suffix}",
            api_token=f"btt_{suffix}",
            role=UserRole.USER,
        )
        org = User(
            twitch_id=f"btorg_{suffix}",
            twitch_username=f"btorg_{suffix}",
            api_token=f"btorgt_{suffix}",
            role=UserRole.ORGANIZER,
        )
        db.add_all([user, org])
        await db.flush()

        seed = Seed(
            seed_number=f"bts_{suffix}",
            pool_name="standard",
            graph_json=self.GRAPH_JSON,
            total_layers=4,
            folder_path=f"/t/bts_{suffix}",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name=f"Backtrack Race {suffix}",
            organizer_id=org.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        participant = Participant(
            race_id=race.id,
            user_id=user.id,
            mod_token=f"btmod_{suffix}",
            status=ParticipantStatus.FINISHED,
            igt_ms=1_000_000,
            death_count=sum(e.get("deaths", 0) for e in zone_history),
            zone_history=zone_history,
        )
        db.add(participant)
        await db.commit()
        return participant

    async def _zone_counts(self, async_session):
        async with async_session() as db:
            participants = (
                (
                    await db.execute(
                        select(Participant).options(
                            selectinload(Participant.race).selectinload(Race.seed),
                        )
                    )
                )
                .scalars()
                .all()
            )
            seeds_by_id = {
                p.race.seed_id: p.race.seed for p in participants if p.race and p.race.seed
            }
            node_display = _resolve_node_display(seeds_by_id)
            zone_data = _aggregate_zone_stats(
                participants, seeds_by_id, DUNGEON_NODE_TYPES, node_display
            )
            return {name: data["backtrack_count"] for name, data in zone_data.items()}

    async def test_zone_before_backtrack_entry_counts(self, async_session):
        """The player turned away from raya (warped back to stormveil, then went
        elsewhere): raya is backtracked, the landing zone is not."""
        async with async_session() as db:
            await self._make_participant(
                db,
                zone_history=[
                    {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                    {"node_id": "stormveil_c3d4", "igt_ms": 100_000, "type": "fog"},
                    {"node_id": "raya_i9j0", "igt_ms": 300_000, "type": "fog"},
                    {"node_id": "stormveil_c3d4", "igt_ms": 400_000, "type": "backtrack"},
                    {"node_id": "godrick_m1n2", "igt_ms": 500_000, "type": "fog"},
                ],
                suffix="r1",
            )

        counts = await self._zone_counts(async_session)
        assert counts["Raya Lucaria"] == 1
        assert counts["Stormveil Castle"] == 0

    async def test_runback_to_same_zone_does_not_count(self, async_session):
        """Death/quit-out runback: the player re-enters the zone right after the
        backtrack entry, so they did not take another path."""
        async with async_session() as db:
            await self._make_participant(
                db,
                zone_history=[
                    {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                    {"node_id": "stormveil_c3d4", "igt_ms": 100_000, "type": "fog"},
                    {"node_id": "raya_i9j0", "igt_ms": 300_000, "type": "fog", "deaths": 1},
                    {"node_id": "stormveil_c3d4", "igt_ms": 400_000, "type": "backtrack"},
                    {"node_id": "raya_i9j0", "igt_ms": 450_000, "type": "fog"},
                ],
                suffix="r2",
            )

        counts = await self._zone_counts(async_session)
        assert counts["Raya Lucaria"] == 0
        assert counts["Stormveil Castle"] == 0

    async def test_backtrack_landing_followed_by_backtrack_not_counted(self, async_session):
        """Consecutive backtrack entries (multi-hop warp) credit only the zone
        the player originally turned away from, not the intermediate landings."""
        async with async_session() as db:
            await self._make_participant(
                db,
                zone_history=[
                    {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                    {"node_id": "stormveil_c3d4", "igt_ms": 100_000, "type": "fog"},
                    {"node_id": "raya_i9j0", "igt_ms": 200_000, "type": "fog"},
                    {"node_id": "cave_e5f6", "igt_ms": 300_000, "type": "fog"},
                    {"node_id": "raya_i9j0", "igt_ms": 400_000, "type": "backtrack"},
                    {"node_id": "stormveil_c3d4", "igt_ms": 450_000, "type": "backtrack"},
                    {"node_id": "godrick_m1n2", "igt_ms": 500_000, "type": "fog"},
                ],
                suffix="r3",
            )

        counts = await self._zone_counts(async_session)
        assert counts["Coastal Cave"] == 1
        assert counts["Raya Lucaria"] == 0
        assert counts["Stormveil Castle"] == 0

    async def test_backtrack_as_last_entry_counts(self, async_session):
        """A backtrack with no later entry still credits the zone turned away
        from: no return happened before the race ended."""
        async with async_session() as db:
            await self._make_participant(
                db,
                zone_history=[
                    {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                    {"node_id": "stormveil_c3d4", "igt_ms": 100_000, "type": "fog"},
                    {"node_id": "raya_i9j0", "igt_ms": 300_000, "type": "fog"},
                    {"node_id": "stormveil_c3d4", "igt_ms": 400_000, "type": "backtrack"},
                ],
                suffix="r4",
            )

        counts = await self._zone_counts(async_session)
        assert counts["Raya Lucaria"] == 1
        assert counts["Stormveil Castle"] == 0

    async def test_untyped_entries_are_not_backtracks(self, async_session):
        """Entries without a type key predate backtrack detection and are
        treated as fog traversals: they never mark the previous zone."""
        async with async_session() as db:
            await self._make_participant(
                db,
                zone_history=[
                    {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                    {"node_id": "stormveil_c3d4", "igt_ms": 100_000},
                    {"node_id": "raya_i9j0", "igt_ms": 300_000},
                    {"node_id": "stormveil_c3d4", "igt_ms": 400_000},
                ],
                suffix="r5",
            )

        counts = await self._zone_counts(async_session)
        assert counts["Raya Lucaria"] == 0
        assert counts["Stormveil Castle"] == 0

    async def test_multi_hop_runback_does_not_count(self, async_session):
        """The warp chain has an intermediate landing but still ends with the
        player back in the zone: a runback, not a path change."""
        async with async_session() as db:
            await self._make_participant(
                db,
                zone_history=[
                    {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                    {"node_id": "stormveil_c3d4", "igt_ms": 100_000, "type": "fog"},
                    {"node_id": "cave_e5f6", "igt_ms": 200_000, "type": "fog"},
                    {"node_id": "raya_i9j0", "igt_ms": 300_000, "type": "fog", "deaths": 1},
                    {"node_id": "stormveil_c3d4", "igt_ms": 400_000, "type": "backtrack"},
                    {"node_id": "cave_e5f6", "igt_ms": 450_000, "type": "backtrack"},
                    {"node_id": "raya_i9j0", "igt_ms": 500_000, "type": "fog"},
                ],
                suffix="r6",
            )

        counts = await self._zone_counts(async_session)
        assert counts["Raya Lucaria"] == 0
        assert counts["Stormveil Castle"] == 0
        assert counts["Coastal Cave"] == 0

    async def test_warp_chain_landing_back_in_zone_does_not_count(self, async_session):
        """A warp chain that lands back in the zone itself (then exits elsewhere)
        is a return to the zone, not turning away from it."""
        async with async_session() as db:
            await self._make_participant(
                db,
                zone_history=[
                    {"node_id": "start_a1b2", "igt_ms": 0, "type": "spawn"},
                    {"node_id": "stormveil_c3d4", "igt_ms": 100_000, "type": "fog"},
                    {"node_id": "raya_i9j0", "igt_ms": 300_000, "type": "fog"},
                    {"node_id": "stormveil_c3d4", "igt_ms": 400_000, "type": "backtrack"},
                    {"node_id": "raya_i9j0", "igt_ms": 450_000, "type": "backtrack"},
                    {"node_id": "godrick_m1n2", "igt_ms": 500_000, "type": "fog"},
                ],
                suffix="r7",
            )

        counts = await self._zone_counts(async_session)
        assert counts["Raya Lucaria"] == 0
        assert counts["Stormveil Castle"] == 0
