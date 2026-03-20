"""Integration tests for stats service and API."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from speedfog_racing.api.stats import (
    BOSS_NODE_TYPES,
    DUNGEON_NODE_TYPES,
    _aggregate_zone_stats,
    _resolve_node_display,
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
from speedfog_racing.services.stats_service import update_elo_ratings, update_player_traits


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
            },
            "cave_e5f6": {"type": "mini_dungeon", "display_name": "Coastal Cave", "layer": 1},
            "margit_g7h8": {"type": "boss_arena", "display_name": "Margit", "layer": 2},
            "raya_i9j0": {"type": "legacy_dungeon", "display_name": "Raya Lucaria", "layer": 3},
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
            # Only 1 race, need MIN_RACES_FOR_TRAITS (3), so per-race traits should be 0
            assert scores.rusher == 0
            assert scores.cautious == 0
            assert scores.explorer == 0

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

    async def test_aggregate_zone_stats_detects_backtracks(
        self, async_session, three_races_with_zone_history
    ):
        """Player 1 backtracks to stormveil, so stormveil should have backtrack count."""
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
            # Player 1 backtracks to stormveil in each of the 3 races
            assert stormveil["backtrack_count"] == 3


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
            for nid, (display, ntype) in node_display.items():
                if "final" in nid:
                    assert ntype == "final_boss"
                if "margit" in nid:
                    # boss_arena should NOT be in stats.py BOSS_NODE_TYPES
                    assert ntype == "boss_arena"
                    assert ntype not in BOSS_NODE_TYPES

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
