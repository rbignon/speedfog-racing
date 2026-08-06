"""Test admin API endpoints."""

import json
import tempfile
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Caster,
    DailySeedSchedule,
    Participant,
    ParticipantStatus,
    Pool,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    TrainingSession,
    TrainingSessionStatus,
    User,
    UserRole,
)


@pytest.fixture
async def async_engine():
    """Create async test database engine."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):
    """Create async session factory."""
    async_session_maker = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return async_session_maker


@pytest.fixture
async def admin_user(async_session):
    """Create an admin user."""
    async with async_session() as db:
        user = User(
            twitch_id="admin123",
            twitch_username="admin_user",
            api_token="admin_test_token",
            role=UserRole.ADMIN,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def regular_user(async_session):
    """Create a regular user."""
    async with async_session() as db:
        user = User(
            twitch_id="user123",
            twitch_username="regular_user",
            api_token="user_test_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
def seed_pool_dir():
    """Create a temporary seed pool directory with zip files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pool_dir = Path(tmpdir) / "standard"
        pool_dir.mkdir()

        zip_path = pool_dir / "seed_abc123.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(
                "speedfog_abc123/graph.json",
                json.dumps({"total_layers": 10, "nodes": []}),
            )

        yield tmpdir


@pytest.fixture
def test_client(async_session):
    """Create test client with async database override."""
    from httpx import ASGITransport, AsyncClient

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")

    yield client

    app.dependency_overrides.clear()


# =============================================================================
# Admin Endpoint Tests
# =============================================================================


@pytest.mark.asyncio
async def test_scan_requires_auth(test_client):
    """Scan endpoint requires authentication."""
    async with test_client as client:
        response = await client.post("/api/admin/seeds/scan")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_scan_requires_admin(test_client, regular_user):
    """Scan endpoint requires admin role."""
    async with test_client as client:
        response = await client.post(
            "/api/admin/seeds/scan",
            headers={"Authorization": f"Bearer {regular_user.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_scan_works_for_admin(test_client, admin_user, seed_pool_dir):
    """Scan endpoint works for admin users."""
    with patch("speedfog_racing.services.seed_service.settings") as mock_settings:
        mock_settings.seeds_pool_dir = seed_pool_dir

        async with test_client as client:
            response = await client.post(
                "/api/admin/seeds/scan",
                headers={"Authorization": f"Bearer {admin_user.api_token}"},
                json={"pool_name": "standard"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["added"] == 1
            assert data["pool_name"] == "standard"


@pytest.mark.asyncio
async def test_discard_pool_endpoint(test_client, admin_user, async_session):
    """Discard endpoint marks available seeds as discarded."""
    # Add seeds directly to database
    async with async_session() as db:
        db.add(
            Seed(
                seed_number="d001",
                pool_name="training_standard",
                graph_json={"total_layers": 5},
                total_layers=5,
                folder_path="/test/seed_d001.zip",
                status=SeedStatus.AVAILABLE,
            )
        )
        db.add(
            Seed(
                seed_number="d002",
                pool_name="training_standard",
                graph_json={"total_layers": 5},
                total_layers=5,
                folder_path="/test/seed_d002.zip",
                status=SeedStatus.AVAILABLE,
            )
        )
        db.add(
            Seed(
                seed_number="d003",
                pool_name="training_standard",
                graph_json={"total_layers": 5},
                total_layers=5,
                folder_path="/test/seed_d003.zip",
                status=SeedStatus.CONSUMED,
            )
        )
        await db.commit()

    async with test_client as client:
        response = await client.post(
            "/api/admin/seeds/discard",
            json={"pool_name": "training_standard"},
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        # discard_pool marks both AVAILABLE and CONSUMED seeds as DISCARDED
        assert data["discarded"] == 3
        assert data["pool_name"] == "training_standard"

        # Verify stats show updated counts
        stats_response = await client.get(
            "/api/admin/seeds/stats",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert stats_response.status_code == 200
        pools = stats_response.json()["pools"]
        assert pools["training_standard"]["available"] == 0
        assert pools["training_standard"]["discarded"] == 3
        assert pools["training_standard"]["consumed"] == 0


@pytest.mark.asyncio
async def test_discard_pool_requires_admin(test_client, regular_user):
    """Discard endpoint requires admin role."""
    async with test_client as client:
        response = await client.post(
            "/api/admin/seeds/discard",
            json={"pool_name": "standard"},
            headers={"Authorization": f"Bearer {regular_user.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_stats_requires_admin(test_client, regular_user):
    """Stats endpoint requires admin role."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/seeds/stats",
            headers={"Authorization": f"Bearer {regular_user.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_stats_works_for_admin(test_client, admin_user, async_session):
    """Stats endpoint returns correct data for admin."""
    # Add a seed directly to database
    async with async_session() as db:
        seed = Seed(
            seed_number="s999",
            pool_name="standard",
            graph_json={"total_layers": 5},
            total_layers=5,
            folder_path="/test/seed_999",
            status=SeedStatus.AVAILABLE,
        )
        db.add(seed)
        await db.commit()

    async with test_client as client:
        response = await client.get(
            "/api/admin/seeds/stats",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "pools" in data
        assert "standard" in data["pools"]
        assert data["pools"]["standard"]["available"] == 1


# =============================================================================
# User Management Tests
# =============================================================================


@pytest.fixture
async def organizer_user(async_session):
    """Create an organizer user."""
    async with async_session() as db:
        user = User(
            twitch_id="org456",
            twitch_username="organizer_user",
            api_token="organizer_test_token",
            role=UserRole.ORGANIZER,
            last_seen=datetime(2026, 1, 15, tzinfo=UTC),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.mark.asyncio
async def test_list_users_requires_admin(test_client, regular_user):
    """List users requires admin role."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {regular_user.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_users_forbidden_for_organizer(test_client, organizer_user):
    """Organizer role cannot access admin endpoints."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {organizer_user.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_users_works_for_admin(test_client, admin_user, regular_user, organizer_user):
    """Admin can list all users."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 3
        usernames = {u["twitch_username"] for u in data}
        assert "admin_user" in usernames
        assert "regular_user" in usernames
        assert "organizer_user" in usernames


@pytest.mark.asyncio
async def test_list_users_separates_daily_and_regular_race_counts(
    test_client, admin_user, regular_user, async_session
):
    """race_count excludes daily races; daily_count counts only daily races."""
    async with async_session() as db:
        seed_regular = Seed(
            seed_number="user_regular_seed",
            pool_name="standard",
            graph_json={"nodes": [], "edges": [], "layers": []},
            total_layers=1,
            folder_path="/fake/regular/seed",
            status=SeedStatus.CONSUMED,
        )
        seed_daily = Seed(
            seed_number="user_daily_seed",
            pool_name="standard",
            graph_json={"nodes": [], "edges": [], "layers": []},
            total_layers=1,
            folder_path="/fake/daily/seed",
            status=SeedStatus.CONSUMED,
        )
        db.add_all([seed_regular, seed_daily])
        await db.flush()

        regular_race = Race(
            name="Regular Race",
            organizer_id=admin_user.id,
            seed_id=seed_regular.id,
            status=RaceStatus.FINISHED,
        )
        daily_race_a = Race(
            name="Daily A",
            organizer_id=admin_user.id,
            seed_id=seed_daily.id,
            status=RaceStatus.FINISHED,
            daily_date=date(2026, 5, 4),
        )
        daily_race_b = Race(
            name="Daily B",
            organizer_id=admin_user.id,
            seed_id=seed_daily.id,
            status=RaceStatus.FINISHED,
            daily_date=date(2026, 5, 5),
        )
        db.add_all([regular_race, daily_race_a, daily_race_b])
        await db.flush()

        db.add_all(
            [
                Participant(
                    race_id=regular_race.id,
                    user_id=regular_user.id,
                    status=ParticipantStatus.FINISHED,
                ),
                Participant(
                    race_id=daily_race_a.id,
                    user_id=regular_user.id,
                    status=ParticipantStatus.FINISHED,
                ),
                Participant(
                    race_id=daily_race_b.id,
                    user_id=regular_user.id,
                    status=ParticipantStatus.FINISHED,
                ),
            ]
        )
        await db.commit()

    async with test_client as client:
        response = await client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        target = next(u for u in data if u["twitch_username"] == "regular_user")
        assert target["race_count"] == 1
        assert target["daily_count"] == 2


@pytest.mark.asyncio
async def test_update_user_role_to_organizer(test_client, admin_user, regular_user):
    """Admin can promote user to organizer."""
    async with test_client as client:
        response = await client.patch(
            f"/api/admin/users/{regular_user.id}",
            json={"role": "organizer"},
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "organizer"


@pytest.mark.asyncio
async def test_update_user_role_to_user(test_client, admin_user, organizer_user):
    """Admin can demote organizer to user."""
    async with test_client as client:
        response = await client.patch(
            f"/api/admin/users/{organizer_user.id}",
            json={"role": "user"},
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "user"


@pytest.mark.asyncio
async def test_update_user_role_to_admin_rejected(test_client, admin_user, regular_user):
    """Cannot set admin role via API."""
    async with test_client as client:
        response = await client.patch(
            f"/api/admin/users/{regular_user.id}",
            json={"role": "admin"},
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_update_user_requires_admin(test_client, regular_user, organizer_user):
    """Regular users cannot update roles."""
    async with test_client as client:
        response = await client.patch(
            f"/api/admin/users/{organizer_user.id}",
            json={"role": "user"},
            headers={"Authorization": f"Bearer {regular_user.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_admin_role_rejected(test_client, admin_user):
    """Cannot change an admin's role."""
    async with test_client as client:
        response = await client.patch(
            f"/api/admin/users/{admin_user.id}",
            json={"role": "user"},
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 400
        assert "admin" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_nonexistent_user(test_client, admin_user):
    """Updating a nonexistent user returns 404."""
    async with test_client as client:
        response = await client.patch(
            "/api/admin/users/00000000-0000-0000-0000-000000000000",
            json={"role": "organizer"},
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 404


# =============================================================================
# Global Activity Feed Tests
# =============================================================================


@pytest.fixture
async def activity_data(async_session, admin_user, regular_user):
    """Create activity data: a race with participant, organizer, caster, and a training session."""
    async with async_session() as db:
        seed = Seed(
            seed_number="activity_seed_001",
            pool_name="standard",
            graph_json={"nodes": [], "edges": [], "layers": []},
            total_layers=1,
            folder_path="/fake/seed/path",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Test Activity Race",
            organizer_id=admin_user.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
        )
        db.add(race)
        await db.flush()

        participant = Participant(
            race_id=race.id,
            user_id=regular_user.id,
            status=ParticipantStatus.FINISHED,
            igt_ms=120000,
            death_count=5,
        )
        db.add(participant)

        caster = Caster(
            race_id=race.id,
            user_id=regular_user.id,
        )
        db.add(caster)

        training = TrainingSession(
            user_id=regular_user.id,
            seed_id=seed.id,
            status=TrainingSessionStatus.FINISHED,
            igt_ms=90000,
            death_count=3,
        )
        db.add(training)

        await db.commit()
        return {"race": race, "participant": participant, "caster": caster, "training": training}


@pytest.mark.asyncio
async def test_activity_requires_admin(test_client, regular_user):
    """Activity endpoint requires admin role."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/activity",
            headers={"Authorization": f"Bearer {regular_user.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_activity_requires_auth(test_client):
    """Activity endpoint requires authentication."""
    async with test_client as client:
        response = await client.get("/api/admin/activity")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_activity_works_for_admin(test_client, admin_user, activity_data):
    """Admin can access the global activity feed."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/activity",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "has_more" in data
        # 1 race_participant + 1 race_organizer + 1 race_caster + 1 training = 4
        assert data["total"] == 4
        types = {i["type"] for i in data["items"]}
        assert "race_participant" in types
        assert "race_organizer" in types
        assert "race_caster" in types
        assert "training" in types


@pytest.mark.asyncio
async def test_activity_items_include_user(test_client, admin_user, activity_data):
    """Activity items include user info."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/activity",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            assert "user" in item
            user = item["user"]
            assert "id" in user
            assert "twitch_username" in user


@pytest.mark.asyncio
async def test_activity_includes_mod_connected(test_client, admin_user, activity_data):
    """Activity items expose is_mod_connected (False when no live mod is connected)."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/activity",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            if item["type"] in ("race_participant", "training"):
                assert item["is_mod_connected"] is False
            else:
                assert "is_mod_connected" not in item


@pytest.mark.asyncio
async def test_activity_mod_connected_true(test_client, admin_user, activity_data, monkeypatch):
    """When the in-memory manager reports a connected mod, the flag is True."""
    from speedfog_racing.api import admin as admin_module

    monkeypatch.setattr(
        admin_module.race_manager,
        "is_mod_connected",
        lambda race_id, participant_id: True,
    )
    monkeypatch.setattr(
        admin_module.training_manager,
        "is_mod_connected",
        lambda session_id: True,
    )

    async with test_client as client:
        response = await client.get(
            "/api/admin/activity",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            if item["type"] in ("race_participant", "training"):
                assert item["is_mod_connected"] is True


@pytest.mark.asyncio
async def test_activity_merges_organizer_into_participant(
    test_client, admin_user, regular_user, async_session
):
    """Mixed scenario: a self-hosted race is merged, a hosted-only race keeps both rows."""
    async with async_session() as db:
        seed = Seed(
            seed_number="merge_seed_001",
            pool_name="standard",
            graph_json={"nodes": [], "edges": [], "layers": []},
            total_layers=1,
            folder_path="/fake/seed/path",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        # Race A: admin organizes and plays — should produce a single merged row.
        race_a = Race(
            name="Self-Hosted",
            organizer_id=admin_user.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
        )
        # Race B: admin only organizes (regular_user plays) — should keep both rows.
        race_b = Race(
            name="Hosted Only",
            organizer_id=admin_user.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
        )
        db.add_all([race_a, race_b])
        await db.flush()

        db.add_all(
            [
                Participant(
                    race_id=race_a.id,
                    user_id=admin_user.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=60000,
                ),
                Participant(
                    race_id=race_b.id,
                    user_id=regular_user.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=70000,
                ),
            ]
        )
        await db.commit()

        race_a_id = str(race_a.id)
        race_b_id = str(race_b.id)

    async with test_client as client:
        response = await client.get(
            "/api/admin/activity",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()

    by_race: dict[str, dict[str, dict]] = {}
    for item in data["items"]:
        by_race.setdefault(item["race_id"], {})[item["type"]] = item

    # Race A: merged into a single participant row tagged as organizer.
    assert "race_organizer" not in by_race[race_a_id]
    assert by_race[race_a_id]["race_participant"]["is_organizer"] is True

    # Race B: organizer and participant rows are both kept; participant is not the organizer.
    assert "race_organizer" in by_race[race_b_id]
    assert by_race[race_b_id]["race_participant"]["is_organizer"] is False


@pytest.mark.asyncio
async def test_activity_daily_race_emits_daily_participant(
    test_client, admin_user, regular_user, async_session
):
    """A participant in a race with daily_date set must appear as daily_participant
    (not race_participant); the race must NOT also produce a separate organizer
    entry, since dailies are system-organized."""
    async with async_session() as db:
        seed = Seed(
            seed_number="daily_act_seed",
            pool_name="standard",
            graph_json={"nodes": [], "edges": [], "layers": []},
            total_layers=1,
            folder_path="/fake/daily/seed",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Daily Race",
            organizer_id=admin_user.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            daily_date=date(2026, 5, 5),
        )
        db.add(race)
        await db.flush()

        db.add(
            Participant(
                race_id=race.id,
                user_id=regular_user.id,
                status=ParticipantStatus.FINISHED,
                igt_ms=120000,
                death_count=2,
            )
        )
        await db.commit()

    async with test_client as client:
        response = await client.get(
            "/api/admin/activity",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
    assert response.status_code == 200
    data = response.json()
    types = [i["type"] for i in data["items"]]
    assert "daily_participant" in types
    assert "race_participant" not in types
    # Daily races must not yield a separate race_organizer entry
    assert "race_organizer" not in types

    daily_item = next(i for i in data["items"] if i["type"] == "daily_participant")
    assert daily_item["daily_date"] == "2026-05-05"
    assert daily_item["pool_name"] == "standard"
    assert daily_item["igt_ms"] == 120000
    assert daily_item["death_count"] == 2


@pytest.mark.asyncio
async def test_activity_pagination(test_client, admin_user, activity_data):
    """Activity endpoint supports offset and limit."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/activity?limit=2&offset=0",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["total"] == 4
        assert data["has_more"] is True

        response2 = await client.get(
            "/api/admin/activity?limit=2&offset=2",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        data2 = response2.json()
        assert len(data2["items"]) == 2
        assert data2["has_more"] is False


@pytest.mark.asyncio
async def test_activity_orders_by_date_across_sources(
    test_client, admin_user, regular_user, async_session
):
    """SQL-level pagination must order rows from every source by date desc.

    Builds three rows whose sort dates straddle each other (training newest,
    race participant in the middle, organizer-only race oldest) and checks
    the timeline returns them in that order, not grouped by source.
    """
    async with async_session() as db:
        seed = Seed(
            seed_number="ordering_seed_001",
            pool_name="standard",
            graph_json={"nodes": [], "edges": [], "layers": []},
            total_layers=1,
            folder_path="/fake/ordering/seed",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        old_race = Race(
            name="Old Hosted",
            organizer_id=admin_user.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        mid_race = Race(
            name="Mid Race",
            organizer_id=admin_user.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            started_at=datetime(2026, 3, 1, tzinfo=UTC),
        )
        db.add_all([old_race, mid_race])
        await db.flush()

        # admin participates in mid_race so it produces a single merged
        # race_participant card (no separate race_organizer entry); this keeps
        # exactly one row per type in the response.
        db.add(
            Participant(
                race_id=mid_race.id,
                user_id=admin_user.id,
                status=ParticipantStatus.FINISHED,
                igt_ms=60000,
            )
        )
        training = TrainingSession(
            user_id=regular_user.id,
            seed_id=seed.id,
            status=TrainingSessionStatus.FINISHED,
            igt_ms=30000,
        )
        db.add(training)
        await db.commit()
        # Force a deterministic created_at newer than mid_race.started_at.
        training.created_at = datetime(2026, 5, 1, tzinfo=UTC)
        await db.commit()

    async with test_client as client:
        response = await client.get(
            "/api/admin/activity",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
    assert response.status_code == 200
    data = response.json()
    types = [item["type"] for item in data["items"]]
    # Pin the row count so a future fixture leak surfaces as a count mismatch
    # rather than a confusing ordering failure.
    assert len(types) == 3
    # training (May) > race_participant (March) > race_organizer (January)
    training_idx = types.index("training")
    participant_idx = types.index("race_participant")
    organizer_idx = types.index("race_organizer")
    assert training_idx < participant_idx < organizer_idx


# =============================================================================
# In-Flight Races Tests
# =============================================================================


@pytest.fixture
async def inflight_races(async_session, admin_user, regular_user):
    """Create a mix of races so the admin in-flight endpoint can be exercised:

    - a PRIVATE RUNNING race organized by ``regular_user`` (admin is not a member),
    - a PUBLIC SETUP race,
    - a FINISHED race (must be excluded),
    - a SETUP daily race (must be excluded).
    """
    async with async_session() as db:
        seed = Seed(
            seed_number="inflight_seed",
            pool_name="standard",
            graph_json={"nodes": [], "edges": [], "layers": []},
            total_layers=1,
            folder_path="/fake/inflight/seed",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        private_running = Race(
            name="Private Running",
            organizer_id=regular_user.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            is_public=False,
            started_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        public_setup = Race(
            name="Public Setup",
            organizer_id=regular_user.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            is_public=True,
        )
        finished = Race(
            name="Finished Race",
            organizer_id=regular_user.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
        )
        daily_setup = Race(
            name="Daily Setup",
            organizer_id=regular_user.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            daily_date=date(2026, 6, 2),
        )
        db.add_all([private_running, public_setup, finished, daily_setup])
        await db.commit()


@pytest.mark.asyncio
async def test_admin_races_requires_auth(test_client):
    """In-flight races endpoint requires authentication."""
    async with test_client as client:
        response = await client.get("/api/admin/races")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_races_requires_admin(test_client, regular_user):
    """In-flight races endpoint requires admin role."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/races",
            headers={"Authorization": f"Bearer {regular_user.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_races_lists_non_finished_including_private(
    test_client, admin_user, inflight_races
):
    """Admin sees every non-finished race, private ones included, but not
    finished or daily races."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/races",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        races = response.json()["races"]
        names = {r["name"] for r in races}
        assert names == {"Private Running", "Public Setup"}

        # The whole point of the tab: a private race the admin isn't part of is
        # surfaced and serialized as private.
        private = next(r for r in races if r["name"] == "Private Running")
        assert private["is_public"] is False


@pytest.mark.asyncio
async def test_admin_races_orders_running_before_setup(test_client, admin_user, inflight_races):
    """Running races sort ahead of setup races."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/races",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        statuses = [r["status"] for r in response.json()["races"]]
        assert statuses == ["running", "setup"]


# =============================================================================
# Reported Seed Management Tests
# =============================================================================


@pytest.mark.asyncio
async def test_reported_seeds_list(test_client, admin_user, organizer_user, async_session):
    """Admin can list reported seeds."""
    async with async_session() as db:
        # Config name ("Boss Rush Mode") deliberately differs from the
        # title-cased normalized name ("Boss Rush"), so the assertion below
        # fails if the response title-cases pool_name instead of reading the
        # Seed -> Pool join.
        db.add(Pool(name="boss_rush", enabled=True, config={"name": "Boss Rush Mode"}))
        db.add(
            Seed(
                seed_number="rep001",
                pool_name="boss_rush",
                graph_json={"total_layers": 5, "nodes": {}},
                total_layers=5,
                folder_path="/test/rep001",
                status=SeedStatus.REPORTED,
                reported_by_id=organizer_user.id,
                reported_reason="broken fog gate",
                reported_at=datetime.now(UTC),
            )
        )
        await db.commit()

    async with test_client as client:
        response = await client.get(
            "/api/admin/reported-seeds",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["seed_number"] == "rep001"
        assert data[0]["pool_name"] == "boss_rush"
        # Resolved via the Seed -> Pool join, not the raw normalized name.
        assert data[0]["pool_display_name"] == "Boss Rush Mode"
        assert data[0]["reported_reason"] == "broken fog gate"
        assert data[0]["reported_by"] == "organizer_user"


@pytest.mark.asyncio
async def test_reported_seeds_requires_admin(test_client, regular_user):
    """Non-admin cannot list reported seeds."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/reported-seeds",
            headers={"Authorization": f"Bearer {regular_user.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_resolve_seed_discard(test_client, admin_user, organizer_user, async_session):
    """Admin can discard a reported seed."""
    async with async_session() as db:
        seed = Seed(
            seed_number="resolve_d",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": {}},
            total_layers=5,
            folder_path="/test/resolve_d",
            status=SeedStatus.REPORTED,
            reported_by_id=organizer_user.id,
            reported_at=datetime.now(UTC),
        )
        db.add(seed)
        await db.commit()
        seed_id = str(seed.id)

    async with test_client as client:
        response = await client.post(
            f"/api/admin/seeds/{seed_id}/resolve",
            headers={
                "Authorization": f"Bearer {admin_user.api_token}",
                "Content-Type": "application/json",
            },
            json={"action": "discard"},
        )
        assert response.status_code == 200

    async with async_session() as db:
        result = await db.execute(select(Seed).where(Seed.seed_number == "resolve_d"))
        assert result.scalar_one().status == SeedStatus.DISCARDED


@pytest.mark.asyncio
async def test_resolve_seed_restore(test_client, admin_user, organizer_user, async_session):
    """Admin can restore a reported seed to AVAILABLE."""
    async with async_session() as db:
        seed = Seed(
            seed_number="resolve_r",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": {}},
            total_layers=5,
            folder_path="/test/resolve_r",
            status=SeedStatus.REPORTED,
            reported_by_id=organizer_user.id,
            reported_reason="false alarm",
            reported_at=datetime.now(UTC),
        )
        db.add(seed)
        await db.commit()
        seed_id = str(seed.id)

    async with test_client as client:
        response = await client.post(
            f"/api/admin/seeds/{seed_id}/resolve",
            headers={
                "Authorization": f"Bearer {admin_user.api_token}",
                "Content-Type": "application/json",
            },
            json={"action": "restore"},
        )
        assert response.status_code == 200

    async with async_session() as db:
        result = await db.execute(select(Seed).where(Seed.seed_number == "resolve_r"))
        seed = result.scalar_one()
        assert seed.status == SeedStatus.AVAILABLE
        assert seed.reported_by_id is None
        assert seed.reported_reason is None
        assert seed.reported_at is None


# =============================================================================
# Pool Management Tests
# =============================================================================


@pytest.fixture
async def seeded_pools(async_session):
    """Seed an extra disabled pool alongside the auto-seeded "standard"
    row (added by the ``after_create`` listener in conftest.py)."""
    async with async_session() as db:
        db.add(Pool(name="sprint", enabled=False, config={"name": "Sprint"}))
        # No display name in config: exercises the title-case fallback.
        db.add(Pool(name="long_run", enabled=False, config={}))
        # Training pool: exercises the ``type`` field plumbing.
        db.add(
            Pool(
                name="solo_practice",
                enabled=False,
                config={"name": "Solo Practice", "type": "training"},
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_admin_list_pools_includes_disabled(test_client, admin_user, seeded_pools):
    """GET /admin/pools returns both enabled and disabled pools."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/pools",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        body = response.json()
        pools_by_name = {p["name"]: p for p in body}
        assert pools_by_name["standard"]["enabled"] is True
        assert pools_by_name["sprint"]["enabled"] is False
        # display_name uses the config name, falling back to the title-cased
        # normalized name when the config has none.
        assert pools_by_name["sprint"]["display_name"] == "Sprint"
        assert pools_by_name["long_run"]["display_name"] == "Long Run"
        # ``type`` surfaces the pool config's type, defaulting to "race" when
        # the config omits it (the admin UI suffixes training pools with " (Solo)").
        assert pools_by_name["solo_practice"]["type"] == "training"
        assert pools_by_name["long_run"]["type"] == "race"


@pytest.mark.asyncio
async def test_admin_list_pools_requires_admin(test_client, regular_user):
    async with test_client as client:
        response = await client.get(
            "/api/admin/pools",
            headers={"Authorization": f"Bearer {regular_user.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_toggle_pool_enabled(test_client, admin_user, seeded_pools):
    """PATCH /admin/pools/{name} flips the enabled flag and persists."""
    async with test_client as client:
        response = await client.patch(
            "/api/admin/pools/standard",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
            json={"enabled": False},
        )
        assert response.status_code == 200
        assert response.json()["enabled"] is False

        # Re-enable
        response = await client.patch(
            "/api/admin/pools/standard",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
            json={"enabled": True},
        )
        assert response.status_code == 200
        assert response.json()["enabled"] is True


@pytest.mark.asyncio
async def test_admin_toggle_pool_unknown(test_client, admin_user):
    """PATCH /admin/pools/{unknown} returns 404."""
    async with test_client as client:
        response = await client.patch(
            "/api/admin/pools/ghost",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
            json={"enabled": False},
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_public_pools_hides_disabled(async_session, seeded_pools):
    """GET /api/pools filters out pools with enabled=False."""
    from httpx import ASGITransport, AsyncClient

    async def override_get_db():
        async with async_session() as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db
    # Seed one available seed in each pool so get_pool_stats picks them up.
    async with async_session() as db:
        db.add(
            Seed(
                seed_number="std_001",
                pool_name="standard",
                graph_json={"total_layers": 5},
                total_layers=5,
                folder_path="/tmp/x.zip",
                status=SeedStatus.AVAILABLE,
            )
        )
        db.add(
            Seed(
                seed_number="spr_001",
                pool_name="sprint",
                graph_json={"total_layers": 3},
                total_layers=3,
                folder_path="/tmp/y.zip",
                status=SeedStatus.AVAILABLE,
            )
        )
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/pools")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    data = response.json()
    assert "standard" in data
    assert "sprint" not in data


# =============================================================================
# Daily Seed Schedule Tests
# =============================================================================


@pytest.fixture
async def daily_schedule_pools(async_session):
    """Seed pools used by the daily-schedule tests:
    - ``standard`` is auto-seeded (race, enabled).
    - ``sprint`` race pool, enabled.
    - ``boss_rush`` race pool, disabled.
    - ``training_standard`` training pool, enabled.
    """
    async with async_session() as db:
        db.add(Pool(name="sprint", enabled=True, config={"name": "Sprint"}))
        db.add(Pool(name="boss_rush", enabled=False, config={"name": "Boss Rush"}))
        db.add(
            Pool(
                name="training_standard",
                enabled=True,
                config={"name": "Training Standard", "type": "training"},
            )
        )
        for weekday in range(7):
            db.add(DailySeedSchedule(weekday=weekday, pool_name="standard"))
        await db.commit()


@pytest.mark.asyncio
async def test_admin_list_daily_schedule(test_client, admin_user, daily_schedule_pools):
    """GET /admin/daily-schedule returns the 7 schedule rows ordered by weekday
    plus the list of selectable race pools (enabled, non-training)."""
    async with test_client as client:
        response = await client.get(
            "/api/admin/daily-schedule",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        body = response.json()
        schedule = body["schedule"]
        assert [row["weekday"] for row in schedule] == [0, 1, 2, 3, 4, 5, 6]
        assert all(row["pool_name"] == "standard" for row in schedule)
        assert all(row["pool_display_name"] == "Standard" for row in schedule)
        assert all(row["deathless"] is False for row in schedule)

        available = body["available_pools"]
        names = {opt["name"] for opt in available}
        assert "standard" in names
        assert "sprint" in names
        # Disabled and training pools must not be selectable.
        assert "boss_rush" not in names
        assert "training_standard" not in names


@pytest.mark.asyncio
async def test_admin_list_daily_schedule_keeps_disabled_persisted_pool(
    test_client, admin_user, daily_schedule_pools, async_session
):
    """A schedule row that points to a now-disabled pool still comes back
    (the frontend renders it as ``(unavailable)``); the disabled pool is
    just absent from ``available_pools``."""
    async with async_session() as db:
        from speedfog_racing.services import set_pool_enabled

        await set_pool_enabled(db, "standard", False)

    async with test_client as client:
        response = await client.get(
            "/api/admin/daily-schedule",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert all(row["pool_name"] == "standard" for row in body["schedule"])
        assert "standard" not in {opt["name"] for opt in body["available_pools"]}


@pytest.mark.asyncio
async def test_admin_list_daily_schedule_requires_admin(
    test_client, regular_user, daily_schedule_pools
):
    async with test_client as client:
        response = await client.get(
            "/api/admin/daily-schedule",
            headers={"Authorization": f"Bearer {regular_user.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_update_daily_schedule_success(
    test_client, admin_user, daily_schedule_pools, async_session
):
    """PATCH updates the row and persists."""
    async with test_client as client:
        response = await client.patch(
            "/api/admin/daily-schedule/2",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
            json={"pool_name": "sprint"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["weekday"] == 2
        assert body["pool_name"] == "sprint"
        assert body["pool_display_name"] == "Sprint"

    async with async_session() as db:
        row = await db.get(DailySeedSchedule, 2)
        assert row is not None
        assert row.pool_name == "sprint"


@pytest.mark.asyncio
async def test_admin_update_daily_schedule_unknown_pool(
    test_client, admin_user, daily_schedule_pools, async_session
):
    async with test_client as client:
        response = await client.patch(
            "/api/admin/daily-schedule/0",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
            json={"pool_name": "ghost"},
        )
        assert response.status_code == 400
        assert "does not exist" in response.json()["detail"]
    async with async_session() as db:
        row = await db.get(DailySeedSchedule, 0)
        assert row is not None
        assert row.pool_name == "standard"


@pytest.mark.asyncio
async def test_admin_update_daily_schedule_deathless_only(
    test_client, admin_user, daily_schedule_pools, async_session
):
    """PATCH with only ``deathless`` flips the flag and keeps the pool."""
    async with test_client as client:
        response = await client.patch(
            "/api/admin/daily-schedule/3",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
            json={"deathless": True},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["weekday"] == 3
        assert body["pool_name"] == "standard"
        assert body["pool_display_name"] == "Standard"
        assert body["deathless"] is True

    async with async_session() as db:
        row = await db.get(DailySeedSchedule, 3)
        assert row is not None
        assert row.pool_name == "standard"
        assert row.deathless is True


@pytest.mark.asyncio
async def test_admin_update_daily_schedule_pool_only_keeps_deathless(
    test_client, admin_user, daily_schedule_pools, async_session
):
    """PATCH with only ``pool_name`` does not reset the deathless flag."""
    async with async_session() as db:
        row = await db.get(DailySeedSchedule, 4)
        assert row is not None
        row.deathless = True
        await db.commit()

    async with test_client as client:
        response = await client.patch(
            "/api/admin/daily-schedule/4",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
            json={"pool_name": "sprint"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["pool_name"] == "sprint"
        assert body["deathless"] is True

    async with async_session() as db:
        row = await db.get(DailySeedSchedule, 4)
        assert row is not None
        assert row.pool_name == "sprint"
        assert row.deathless is True


@pytest.mark.asyncio
async def test_admin_update_daily_schedule_disabled_pool(
    test_client, admin_user, daily_schedule_pools, async_session
):
    async with test_client as client:
        response = await client.patch(
            "/api/admin/daily-schedule/0",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
            json={"pool_name": "boss_rush"},
        )
        assert response.status_code == 400
        assert "disabled" in response.json()["detail"]
    async with async_session() as db:
        row = await db.get(DailySeedSchedule, 0)
        assert row is not None
        assert row.pool_name == "standard"


@pytest.mark.asyncio
async def test_admin_update_daily_schedule_training_pool(
    test_client, admin_user, daily_schedule_pools, async_session
):
    async with test_client as client:
        response = await client.patch(
            "/api/admin/daily-schedule/0",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
            json={"pool_name": "training_standard"},
        )
        assert response.status_code == 400
        assert "training" in response.json()["detail"]
    async with async_session() as db:
        row = await db.get(DailySeedSchedule, 0)
        assert row is not None
        assert row.pool_name == "standard"


@pytest.mark.asyncio
async def test_admin_update_daily_schedule_invalid_weekday(
    test_client, admin_user, daily_schedule_pools
):
    async with test_client as client:
        response = await client.patch(
            "/api/admin/daily-schedule/7",
            headers={"Authorization": f"Bearer {admin_user.api_token}"},
            json={"pool_name": "standard"},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_admin_update_daily_schedule_requires_admin(
    test_client, regular_user, daily_schedule_pools
):
    async with test_client as client:
        response = await client.patch(
            "/api/admin/daily-schedule/0",
            headers={"Authorization": f"Bearer {regular_user.api_token}"},
            json={"pool_name": "standard"},
        )
        assert response.status_code == 403
