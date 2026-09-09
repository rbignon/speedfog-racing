"""Admin management of tournament events."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import Pool, Race, Seed, SeedStatus, User, UserRole

T0 = datetime(2026, 9, 23, 8, tzinfo=UTC)
DOC = {
    "slug": "season-one",
    "name": "Season One",
    "partner_name": "Ignite",
    "starts_at": T0.isoformat(),
    "qualifier_ends_at": (T0 + timedelta(days=7)).isoformat(),
    "ends_at": "2026-10-26T00:00:00+00:00",
    "newcomer_threshold": 5,
    "config": {
        "modes": [{"key": "standard", "label": "Standard"}],
        "seeds_per_mode": 2,
        "stages": [
            {
                "key": "semi_a",
                "label": "Semi A",
                "kind": "semi",
                "date": "2026-10-04T19:00:00Z",
                "races": 3,
                "seeds": [1, 4],
            },
            {
                "key": "final",
                "label": "Final",
                "kind": "final",
                "date": "2026-10-25T19:00:00Z",
                "races": 3,
                "from": ["semi_a"],
                "advance": 2,
            },
        ],
        "rules": [],
    },
}


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def test_client(async_session):
    from httpx import ASGITransport, AsyncClient

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


@pytest.fixture
async def users(async_session):
    async with async_session() as db:
        admin = User(
            twitch_id="a", twitch_username="root", api_token="tok-root", role=UserRole.ADMIN
        )
        orga = User(
            twitch_id="o", twitch_username="orga", api_token="tok-orga", role=UserRole.ORGANIZER
        )
        # "standard" is auto-seeded by the conftest listener when the pools table is created.
        db.add_all([admin, orga, Pool(name="boss_rush", config={})])
        await db.commit()
        await db.refresh(admin)
        await db.refresh(orga)
        return admin, orga


ADMIN = {"Authorization": "Bearer tok-root"}


@pytest.mark.asyncio
async def test_upsert_requires_admin(test_client, users):
    async with test_client as client:
        response = await client.post(
            "/api/admin/events", json=DOC, headers={"Authorization": "Bearer tok-orga"}
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_upsert_creates_then_updates(test_client, users):
    async with test_client as client:
        created = await client.post("/api/admin/events", json=DOC, headers=ADMIN)
        assert created.status_code == 200, created.text
        assert created.json()["phase"] in ("upcoming", "qualifier", "cut", "playoffs", "finished")
        renamed = dict(DOC, name="Fog Cup")
        updated = await client.post("/api/admin/events", json=renamed, headers=ADMIN)
        assert updated.json()["name"] == "Fog Cup"
        assert updated.json()["id"] == created.json()["id"]
        listed = await client.get("/api/admin/events", headers=ADMIN)
    assert [e["slug"] for e in listed.json()] == ["season-one"]


@pytest.mark.asyncio
async def test_upsert_rejects_unknown_mode_pool(test_client, users):
    doc = dict(DOC, config=dict(DOC["config"], modes=[{"key": "nope", "label": "Nope"}]))
    async with test_client as client:
        response = await client.post("/api/admin/events", json=doc, headers=ADMIN)
    assert response.status_code == 422
    assert "nope" in response.text


async def _race(db, orga, pool: str, number: str, **kw) -> Race:
    seed = Seed(
        seed_number=number,
        pool_name=pool,
        graph_json={"total_layers": 5, "nodes": []},
        total_layers=5,
        folder_path=f"/seeds/{number}.zip",
        status=SeedStatus.CONSUMED,
    )
    db.add(seed)
    await db.flush()
    kw.setdefault("late_join_window_minutes", 10080)
    kw.setdefault("race_duration_minutes", 10080)
    race = Race(
        name=number,
        organizer_id=orga.id,
        seed_id=seed.id,
        is_public=False,
        open_registration=True,
        **kw,
    )
    db.add(race)
    await db.flush()
    return race


@pytest.mark.asyncio
async def test_attach_validates_slot_pool_and_uniqueness(test_client, users, async_session):
    _, orga = users
    async with async_session() as db:
        std = await _race(db, orga, "standard", "s1")
        boss = await _race(db, orga, "boss_rush", "b1")
        other = await _race(db, orga, "standard", "s2")
        await db.commit()
    async with test_client as client:
        event_id = (await client.post("/api/admin/events", json=DOC, headers=ADMIN)).json()["id"]

        bad_slot = await client.post(
            f"/api/admin/races/{std.id}/event",
            json={"event_id": event_id, "slot": "qualifier:standard:9"},
            headers=ADMIN,
        )
        assert bad_slot.status_code == 422

        wrong_pool = await client.post(
            f"/api/admin/races/{boss.id}/event",
            json={"event_id": event_id, "slot": "qualifier:standard:1"},
            headers=ADMIN,
        )
        assert wrong_pool.status_code == 422 and "pool" in wrong_pool.text

        ok = await client.post(
            f"/api/admin/races/{std.id}/event",
            json={"event_id": event_id, "slot": "qualifier:standard:1"},
            headers=ADMIN,
        )
        assert ok.status_code == 200
        assert ok.json()["exclude_from_stats"] is True
        assert ok.json()["event_id"] == event_id
        assert ok.json()["event_slot"] == "qualifier:standard:1"

        taken = await client.post(
            f"/api/admin/races/{other.id}/event",
            json={"event_id": event_id, "slot": "qualifier:standard:1"},
            headers=ADMIN,
        )
        assert taken.status_code == 409

        detached = await client.post(
            f"/api/admin/races/{std.id}/event", json={"event_id": None}, headers=ADMIN
        )
        assert detached.status_code == 200
        assert detached.json()["event_id"] is None
        assert detached.json()["event_slot"] is None
    async with async_session() as db:
        row = (await db.execute(select(Race).where(Race.id == std.id))).scalar_one()
        assert row.event_id is None and row.event_slot is None


@pytest.mark.asyncio
async def test_attach_stage_slot_requires_room_for_the_field(test_client, users, async_session):
    _, orga = users
    async with async_session() as db:
        small = await _race(db, orga, "standard", "s3", max_participants=1)
        await db.commit()
    async with test_client as client:
        event_id = (await client.post("/api/admin/events", json=DOC, headers=ADMIN)).json()["id"]
        response = await client.post(
            f"/api/admin/races/{small.id}/event",
            json={"event_id": event_id, "slot": "semi_a:1"},
            headers=ADMIN,
        )
    assert response.status_code == 422 and "max_participants" in response.text


@pytest.mark.asyncio
async def test_attach_rejects_daily_seed(test_client, users, async_session):
    _, orga = users
    async with async_session() as db:
        daily = await _race(db, orga, "standard", "d1", daily_date=date(2026, 9, 1))
        await db.commit()
    async with test_client as client:
        event_id = (await client.post("/api/admin/events", json=DOC, headers=ADMIN)).json()["id"]
        response = await client.post(
            f"/api/admin/races/{daily.id}/event",
            json={"event_id": event_id, "slot": "qualifier:standard:1"},
            headers=ADMIN,
        )
    assert response.status_code == 422 and "daily" in response.text


@pytest.mark.asyncio
async def test_attach_qualifier_rejects_mismatched_window(test_client, users, async_session):
    _, orga = users
    async with async_session() as db:
        race = await _race(
            db,
            orga,
            "standard",
            "s4",
            late_join_window_minutes=60,
            race_duration_minutes=10080,
        )
        await db.commit()
    async with test_client as client:
        event_id = (await client.post("/api/admin/events", json=DOC, headers=ADMIN)).json()["id"]
        response = await client.post(
            f"/api/admin/races/{race.id}/event",
            json={"event_id": event_id, "slot": "qualifier:standard:1"},
            headers=ADMIN,
        )
    assert response.status_code == 422 and "late_join" in response.text


@pytest.mark.asyncio
async def test_attach_qualifier_rejects_unset_window(test_client, users, async_session):
    """Both durations NULL must not vacuously satisfy the equality check."""
    _, orga = users
    async with async_session() as db:
        race = await _race(
            db,
            orga,
            "standard",
            "s5",
            late_join_window_minutes=None,
            race_duration_minutes=None,
        )
        await db.commit()
    async with test_client as client:
        event_id = (await client.post("/api/admin/events", json=DOC, headers=ADMIN)).json()["id"]
        response = await client.post(
            f"/api/admin/races/{race.id}/event",
            json={"event_id": event_id, "slot": "qualifier:standard:1"},
            headers=ADMIN,
        )
    assert response.status_code == 422 and "late_join" in response.text


@pytest.mark.asyncio
async def test_attach_stage_slot_succeeds_without_excluding_from_stats(
    test_client, users, async_session
):
    _, orga = users
    async with async_session() as db:
        race = await _race(db, orga, "standard", "s6", max_participants=2)
        await db.commit()
    async with test_client as client:
        event_id = (await client.post("/api/admin/events", json=DOC, headers=ADMIN)).json()["id"]
        response = await client.post(
            f"/api/admin/races/{race.id}/event",
            json={"event_id": event_id, "slot": "semi_a:1"},
            headers=ADMIN,
        )
    assert response.status_code == 200, response.text
    assert response.json()["exclude_from_stats"] is False
