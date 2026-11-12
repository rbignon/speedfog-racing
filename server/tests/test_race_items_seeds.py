"""Items races draw only seeds that carry the race items plugin."""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import Race, RaceStatus, Seed, SeedStatus, User, UserRole
from speedfog_racing.services.race_items import (
    CatalogEntry,
    extract_race_item_catalog,
    seed_has_race_items,
    use_flag_map,
)
from speedfog_racing.services.seed_service import assign_seed_to_race, reroll_seed_for_race

ENTRY = {
    "name": "Banana",
    "icon": "banana",
    "goods_id": 100,
    "use_flag": 5,
    "remove_flag": 6,
    "effect_speffect": None,
    "duration_ms": None,
}


def _items_graph() -> dict:
    return {
        "total_layers": 5,
        "nodes": [],
        "plugins": {"race_items": {"enabled": True}},
        "race_items": {"banana": ENTRY},
    }


def _plain_graph() -> dict:
    return {"total_layers": 5, "nodes": []}


def test_seed_has_race_items():
    assert seed_has_race_items(_items_graph())
    assert not seed_has_race_items({**_items_graph(), "race_items": {}})
    assert not seed_has_race_items(
        {**_items_graph(), "plugins": {"race_items": {"enabled": False}}}
    )
    assert not seed_has_race_items({"race_items": {"banana": ENTRY}})
    assert not seed_has_race_items(_plain_graph())


def test_extract_catalog_skips_malformed_entries():
    graph = _items_graph()
    graph["race_items"] = {
        "banana": ENTRY,
        "no_goods": {k: v for k, v in ENTRY.items() if k != "goods_id"},
        "string_flag": {**ENTRY, "remove_flag": "6"},
        "not_a_dict": 3,
    }
    catalog = extract_race_item_catalog(graph)
    assert list(catalog) == ["banana"]
    assert catalog["banana"] == CatalogEntry("Banana", "banana", 100, 5, 6, None, None)
    assert extract_race_item_catalog(_plain_graph()) == {}


def test_use_flag_map_skips_the_shield():
    shield = {**ENTRY, "name": "Shield", "use_flag": None}
    graph = _items_graph()
    graph["race_items"] = {"shield": shield, "banana": ENTRY}
    assert use_flag_map(extract_race_item_catalog(graph)) == {5: "banana"}


@pytest.fixture
async def rs_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def rs_client(rs_session):
    async def override_get_db():
        async with rs_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


@pytest.fixture
async def rs_organizer(rs_session):
    async with rs_session() as db:
        user = User(
            twitch_id="org_rs",
            twitch_username="organizer_rs",
            twitch_display_name="Organizer RS",
            api_token="org_rs_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.commit()
        return user


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {user.api_token}"}


def _seed(
    suffix: str, graph: dict, status: SeedStatus = SeedStatus.AVAILABLE, pool: str = "standard"
) -> Seed:
    return Seed(
        seed_number=f"rs_{suffix}",
        pool_name=pool,
        graph_json=graph,
        total_layers=5,
        folder_path=f"/test/rs_{suffix}",
        status=status,
    )


@pytest.mark.asyncio
async def test_items_race_draws_only_plugin_seeds(rs_session, rs_organizer):
    async with rs_session() as db:
        plain = _seed("plain", _plain_graph())
        items = _seed("items", _items_graph())
        db.add_all([plain, items])
        await db.commit()
        for i in range(10):
            race = Race(name=f"R{i}", organizer_id=rs_organizer.id, race_items=True)
            db.add(race)
            await db.flush()
            seed = await assign_seed_to_race(db, race, "standard", allow_seen=True)
            assert seed.id == items.id
            seed.status = SeedStatus.AVAILABLE  # free it for the next draw
        assert plain.status == SeedStatus.AVAILABLE


@pytest.mark.asyncio
async def test_create_items_race_without_plugin_seed_is_400(rs_client, rs_session, rs_organizer):
    async with rs_session() as db:
        db.add(_seed("plain", _plain_graph()))
        await db.commit()

    async with rs_client as client:
        resp = await client.post(
            "/api/races",
            json={"name": "Items race", "race_items": True},
            headers=_auth(rs_organizer),
        )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "No seed with race items available in pool 'standard'"
    async with rs_session() as db:
        assert (await db.execute(select(Race))).scalars().all() == []
        seed = (await db.execute(select(Seed))).scalar_one()
        assert seed.status == SeedStatus.AVAILABLE


@pytest.mark.asyncio
async def test_enabling_items_redraws_a_plain_seed_without_counting_a_reroll(
    rs_client, rs_session, rs_organizer, monkeypatch
):
    from speedfog_racing.api import races as races_api

    monkeypatch.setattr(races_api, "broadcast_race_info_update", AsyncMock())
    monkeypatch.setattr(races_api, "broadcast_race_state_update", AsyncMock())
    async with rs_session() as db:
        plain = _seed("plain", _plain_graph(), SeedStatus.CONSUMED)
        items = _seed("items", _items_graph())
        db.add_all([plain, items])
        await db.flush()
        race = Race(name="R", organizer_id=rs_organizer.id, seed_id=plain.id)
        db.add(race)
        await db.commit()
        race_id, plain_id, items_id = race.id, plain.id, items.id

    async with rs_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}", json={"race_items": True}, headers=_auth(rs_organizer)
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["race_items"] is True
    async with rs_session() as db:
        race = await db.get(Race, race_id)
        assert race.seed_id == items_id
        assert race.rerolled_without_report is False
        assert race.rerolled_seed_ids == [str(plain_id)]


@pytest.mark.asyncio
async def test_enabling_items_without_plugin_seed_is_400_and_stays_off(
    rs_client, rs_session, rs_organizer
):
    async with rs_session() as db:
        plain = _seed("plain", _plain_graph(), SeedStatus.CONSUMED)
        db.add_all([plain, _seed("other", _plain_graph())])
        await db.flush()
        race = Race(name="R", organizer_id=rs_organizer.id, seed_id=plain.id)
        db.add(race)
        await db.commit()
        race_id, plain_id = race.id, plain.id

    async with rs_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}", json={"race_items": True}, headers=_auth(rs_organizer)
        )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "No seed with race items available in pool 'standard'"
    async with rs_session() as db:
        race = await db.get(Race, race_id)
        assert race.race_items is False
        assert race.seed_id == plain_id


@pytest.mark.asyncio
async def test_reroll_of_items_race_keeps_the_plugin(rs_session, rs_organizer):
    async with rs_session() as db:
        current = _seed("cur", _items_graph(), SeedStatus.CONSUMED)
        db.add_all([current, _seed("plain", _plain_graph()), _seed("items", _items_graph())])
        await db.flush()
        race = Race(
            name="R",
            organizer_id=rs_organizer.id,
            seed_id=current.id,
            race_items=True,
            status=RaceStatus.SETUP,
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    async with rs_session() as db:
        race = (
            await db.execute(
                select(Race).where(Race.id == race_id).options(selectinload(Race.seed))
            )
        ).scalar_one()
        new_seed = await reroll_seed_for_race(db, race)
        assert new_seed.seed_number == "rs_items"
        assert race.rerolled_without_report is True

        # Only the current seed carries the plugin now: nothing to draw.
        with pytest.raises(ValueError, match="No other seed left"):
            await reroll_seed_for_race(db, race)


@pytest.mark.asyncio
async def test_pool_stats_count_race_items_seeds(rs_client, rs_session):
    async with rs_session() as db:
        db.add_all(
            [
                _seed("a", _items_graph()),
                _seed("b", _items_graph(), SeedStatus.SEEN),
                _seed("c", _items_graph(), SeedStatus.CONSUMED),
                _seed("d", _plain_graph()),
            ]
        )
        await db.commit()

    async with rs_client as client:
        resp = await client.get("/api/pools?type=race")
    assert resp.status_code == 200, resp.text
    assert resp.json()["standard"]["race_items_available"] == 2
