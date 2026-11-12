"""Admin management of tournament events."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Event,
    NameTemplateUnlock,
    Pool,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)

from .event_fixtures import bracketed, rewarded, stages_of
from .test_events_api import CONFIG as RANKED_CONFIG
from .test_events_api import _event as _ranked_event
from .test_events_api import _ranked_runners

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
                "seeds": [1, 2],
                "advance": 2,
            },
            {
                "key": "final",
                "label": "Final",
                "kind": "final",
                "date": "2026-10-25T19:00:00Z",
                "races": 3,
                "from": ["semi_a"],
            },
        ],
        "rules": [],
        "phase_override": "cut",
    },
}

QUARTERS_DOC = {
    **DOC,
    "config": {
        **DOC["config"],
        "stages": [
            *(
                {
                    "key": key,
                    "label": key.replace("_", " ").title(),
                    "kind": "quarter",
                    "date": f"2026-10-0{2 + i}T19:00:00Z",
                    "races": 3,
                    "seeds": seeds,
                    "advance": 2,
                }
                for i, (key, seeds) in enumerate(
                    [
                        ("quarter_a", [1, 8, 9, 16]),
                        ("quarter_b", [4, 5, 12, 13]),
                        ("quarter_c", [2, 7, 10, 15]),
                        ("quarter_d", [3, 6, 11, 14]),
                    ]
                )
            ),
            {
                "key": "semi_a",
                "label": "Semi A",
                "kind": "semi",
                "date": "2026-10-10T19:00:00Z",
                "races": 3,
                "from": ["quarter_a", "quarter_b"],
                "advance": 2,
            },
            {
                "key": "semi_b",
                "label": "Semi B",
                "kind": "semi",
                "date": "2026-10-11T19:00:00Z",
                "races": 3,
                "from": ["quarter_c", "quarter_d"],
                "advance": 2,
            },
            {
                "key": "final",
                "label": "Final",
                "kind": "final",
                "date": "2026-10-25T19:00:00Z",
                "races": 3,
                "from": ["semi_a", "semi_b"],
            },
        ],
    },
}


def _upsert(doc: dict[str, Any]) -> dict[str, Any]:
    """``doc`` as the admin upsert takes it: its flat stage list wrapped into brackets."""
    return {**doc, "config": bracketed(doc["config"])}


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
            "/api/admin/events", json=_upsert(DOC), headers={"Authorization": "Bearer tok-orga"}
        )
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method, path, body",
    [
        ("GET", "/api/admin/events", None),
        ("POST", f"/api/admin/races/{uuid.uuid4()}/event", {"event_id": None}),
        ("GET", f"/api/admin/events/{uuid.uuid4()}/rewards", None),
        ("POST", f"/api/admin/events/{uuid.uuid4()}/rewards/main/seated", None),
    ],
)
async def test_events_admin_endpoints_require_admin(test_client, users, method, path, body):
    async with test_client as client:
        response = await client.request(
            method, path, json=body, headers={"Authorization": "Bearer tok-orga"}
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_upsert_creates_then_updates(test_client, users):
    async with test_client as client:
        created = await client.post("/api/admin/events", json=_upsert(DOC), headers=ADMIN)
        assert created.status_code == 200, created.text
        assert created.json()["phase"] == "cut"
        renamed = dict(DOC, name="Fog Cup")
        updated = await client.post("/api/admin/events", json=_upsert(renamed), headers=ADMIN)
        assert updated.json()["name"] == "Fog Cup"
        assert updated.json()["id"] == created.json()["id"]
        listed = await client.get("/api/admin/events", headers=ADMIN)
    assert [e["slug"] for e in listed.json()] == ["season-one"]


@pytest.mark.asyncio
async def test_upsert_refreshes_the_cached_summary_of_a_settled_event(test_client, users):
    # Over since 2026-10-26 with no override: the listing caches its summary.
    doc = dict(DOC, config=dict(DOC["config"], phase_override=None))
    async with test_client as client:
        created = await client.post("/api/admin/events", json=_upsert(doc), headers=ADMIN)
        assert created.status_code == 200, created.text
        assert [e["name"] for e in (await client.get("/api/events")).json()] == ["Season One"]
        renamed = dict(doc, name="Fog Cup")
        await client.post("/api/admin/events", json=_upsert(renamed), headers=ADMIN)
        listed = await client.get("/api/events")
    assert [e["name"] for e in listed.json()] == ["Fog Cup"]


@pytest.mark.asyncio
async def test_upsert_rejects_unknown_mode_pool(test_client, users):
    doc = dict(DOC, config=dict(DOC["config"], modes=[{"key": "nope", "label": "Nope"}]))
    async with test_client as client:
        response = await client.post("/api/admin/events", json=_upsert(doc), headers=ADMIN)
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
async def test_admin_list_survives_a_stored_config_the_schema_rejects(
    test_client, users, async_session
):
    """Tightening the config schema can leave a stored document invalid, and the
    Events tab is where it gets repaired, so the list must still load."""
    _, orga = users
    async with async_session() as db:
        race = await _race(db, orga, "standard", "s9", max_participants=2)
        await db.commit()
    async with test_client as client:
        event_id = (
            await client.post("/api/admin/events", json=_upsert(DOC), headers=ADMIN)
        ).json()["id"]
        async with async_session() as db:
            event = await db.get(Event, uuid.UUID(event_id))
            (main,) = event.config["brackets"]
            stages = [dict(s) for s in main["stages"]]
            stages[0] = dict(stages[0], seeds=[1, 3])  # seed 2 is nobody's
            event.config = dict(event.config, brackets=[dict(main, stages=stages)])
            await db.commit()

        listed = await client.get("/api/admin/events", headers=ADMIN)
        assert listed.status_code == 200, listed.text
        row = listed.json()[0]
        # The document carries phase_override "cut", which no longer applies
        # now that it does not parse: the phase falls back to the dates.
        assert row["phase"] != "cut"
        assert "gap" in row["config_error"]
        assert stages_of(row["config"])[0]["seeds"] == [1, 3]

        # Attaching needs the parsed config, so it refuses, but as a 422 naming
        # the document rather than a 500.
        attached = await client.post(
            f"/api/admin/races/{race.id}/event",
            json={"event_id": event_id, "slot": "semi_a:1"},
            headers=ADMIN,
        )
    assert attached.status_code == 422, attached.text
    assert "gap" in attached.json()["detail"]


@pytest.mark.asyncio
async def test_upsert_refuses_config_that_orphans_an_attached_slot(
    test_client, users, async_session
):
    _, orga = users
    async with async_session() as db:
        std = await _race(db, orga, "standard", "s7")
        await db.commit()
    async with test_client as client:
        created = (await client.post("/api/admin/events", json=_upsert(DOC), headers=ADMIN)).json()
        event_id = created["id"]
        attached = await client.post(
            f"/api/admin/races/{std.id}/event",
            json={"event_id": event_id, "slot": "qualifier:standard:1"},
            headers=ADMIN,
        )
        assert attached.status_code == 200, attached.text

        dropped_mode = dict(
            DOC,
            config=dict(DOC["config"], modes=[{"key": "boss_rush", "label": "Boss Rush"}]),
        )
        rejected = await client.post("/api/admin/events", json=_upsert(dropped_mode), headers=ADMIN)
        assert rejected.status_code == 422
        assert "qualifier:standard:1" in rejected.text

        listed = await client.get("/api/admin/events", headers=ADMIN)
        assert listed.json()[0]["config"] == created["config"]

        relabeled = dict(
            DOC,
            config=dict(DOC["config"], modes=[{"key": "standard", "label": "Standard Mode"}]),
        )
        compatible = await client.post("/api/admin/events", json=_upsert(relabeled), headers=ADMIN)
        assert compatible.status_code == 200, compatible.text


@pytest.mark.asyncio
async def test_attach_validates_slot_pool_and_uniqueness(test_client, users, async_session):
    _, orga = users
    async with async_session() as db:
        std = await _race(db, orga, "standard", "s1")
        boss = await _race(db, orga, "boss_rush", "b1")
        other = await _race(db, orga, "standard", "s2")
        await db.commit()
    async with test_client as client:
        event_id = (
            await client.post("/api/admin/events", json=_upsert(DOC), headers=ADMIN)
        ).json()["id"]

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
        assert ok.json()["event_id"] == event_id
        assert ok.json()["event_slot"] == "qualifier:standard:1"
        # The race page reads the slot from the detail endpoint.
        detail = (await client.get(f"/api/races/{std.id}")).json()
        assert detail["event_id"] == event_id
        assert detail["event_slot"] == "qualifier:standard:1"

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
async def test_race_detail_names_its_event_by_slug(test_client, users, async_session):
    """The cast setup panel prefills its co-brand from it: the panel works in
    slugs, and no client endpoint maps an event id to one."""
    _, orga = users
    async with async_session() as db:
        race = await _race(db, orga, "standard", "s1")
        await db.commit()
    async with test_client as client:
        event_id = (
            await client.post("/api/admin/events", json=_upsert(DOC), headers=ADMIN)
        ).json()["id"]
        assert (await client.get(f"/api/races/{race.id}")).json()["event_slug"] is None

        attached = await client.post(
            f"/api/admin/races/{race.id}/event",
            json={"event_id": event_id, "slot": "qualifier:standard:1"},
            headers=ADMIN,
        )
        assert attached.status_code == 200
        detail = (await client.get(f"/api/races/{race.id}")).json()
        assert detail["event_slug"] == DOC["slug"]

        detached = await client.post(
            f"/api/admin/races/{race.id}/event", json={"event_id": None}, headers=ADMIN
        )
        assert detached.status_code == 200
        assert (await client.get(f"/api/races/{race.id}")).json()["event_slug"] is None


@pytest.mark.asyncio
async def test_attach_stage_slot_requires_room_for_the_field(test_client, users, async_session):
    _, orga = users
    async with async_session() as db:
        small = await _race(db, orga, "standard", "s3", max_participants=1)
        await db.commit()
    async with test_client as client:
        event_id = (
            await client.post("/api/admin/events", json=_upsert(DOC), headers=ADMIN)
        ).json()["id"]
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
        event_id = (
            await client.post("/api/admin/events", json=_upsert(DOC), headers=ADMIN)
        ).json()["id"]
        response = await client.post(
            f"/api/admin/races/{daily.id}/event",
            json={"event_id": event_id, "slot": "qualifier:standard:1"},
            headers=ADMIN,
        )
    assert response.status_code == 422 and "daily" in response.text


@pytest.mark.asyncio
async def test_attach_rejects_a_race_with_items(test_client, users, async_session):
    _, orga = users
    async with async_session() as db:
        race = await _race(db, orga, "standard", "i1", race_items=True, max_participants=2)
        await db.commit()
    async with test_client as client:
        event_id = (
            await client.post("/api/admin/events", json=_upsert(DOC), headers=ADMIN)
        ).json()["id"]
        response = await client.post(
            f"/api/admin/races/{race.id}/event",
            json={"event_id": event_id, "slot": "semi_a:1"},
            headers=ADMIN,
        )
    assert response.status_code == 422 and "race items" in response.text
    async with async_session() as db:
        assert (await db.get(Race, race.id)).event_id is None


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
        event_id = (
            await client.post("/api/admin/events", json=_upsert(DOC), headers=ADMIN)
        ).json()["id"]
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
        event_id = (
            await client.post("/api/admin/events", json=_upsert(DOC), headers=ADMIN)
        ).json()["id"]
        response = await client.post(
            f"/api/admin/races/{race.id}/event",
            json={"event_id": event_id, "slot": "qualifier:standard:1"},
            headers=ADMIN,
        )
    assert response.status_code == 422 and "late_join" in response.text


@pytest.mark.asyncio
async def test_attach_stage_slot_succeeds(test_client, users, async_session):
    _, orga = users
    async with async_session() as db:
        race = await _race(db, orga, "standard", "s6", max_participants=2)
        await db.commit()
    async with test_client as client:
        event_id = (
            await client.post("/api/admin/events", json=_upsert(DOC), headers=ADMIN)
        ).json()["id"]
        response = await client.post(
            f"/api/admin/races/{race.id}/event",
            json={"event_id": event_id, "slot": "semi_a:1"},
            headers=ADMIN,
        )
    assert response.status_code == 200, response.text
    assert response.json()["event_slot"] == "semi_a:1"


@pytest.mark.asyncio
async def test_attach_to_a_fed_stage_needs_room_for_every_source(test_client, users, async_session):
    _, orga = users
    async with async_session() as db:
        three = await _race(db, orga, "standard", "s10", max_participants=3)
        four = await _race(db, orga, "standard", "s11", max_participants=4)
        await db.commit()
    async with test_client as client:
        event_id = (
            await client.post("/api/admin/events", json=_upsert(QUARTERS_DOC), headers=ADMIN)
        ).json()["id"]
        refused = await client.post(
            f"/api/admin/races/{three.id}/event",
            json={"event_id": event_id, "slot": "semi_a:1"},
            headers=ADMIN,
        )
        accepted = await client.post(
            f"/api/admin/races/{four.id}/event",
            json={"event_id": event_id, "slot": "semi_a:1"},
            headers=ADMIN,
        )
    # Two quarters send two runners each.
    assert refused.status_code == 422 and "field of 4" in refused.text
    assert accepted.status_code == 200, accepted.text


@pytest.mark.asyncio
async def test_the_quarters_config_replaces_the_semis_one_under_attached_qualifiers(
    test_client, users, async_session
):
    """The rollout: the season's qualifier races stay attached while the
    stored semis config gives way to quarters."""
    _, orga = users
    async with async_session() as db:
        std = await _race(db, orga, "standard", "s12")
        await db.commit()
    async with test_client as client:
        event_id = (
            await client.post("/api/admin/events", json=_upsert(DOC), headers=ADMIN)
        ).json()["id"]
        attached = await client.post(
            f"/api/admin/races/{std.id}/event",
            json={"event_id": event_id, "slot": "qualifier:standard:1"},
            headers=ADMIN,
        )
        assert attached.status_code == 200, attached.text
        replaced = await client.post("/api/admin/events", json=_upsert(QUARTERS_DOC), headers=ADMIN)
    assert replaced.status_code == 200, replaced.text
    assert [s["key"] for s in stages_of(replaced.json()["config"])][:2] == [
        "quarter_a",
        "quarter_b",
    ]


SHOWCASE_DOC = {
    **DOC,
    "config": {
        **DOC["config"],
        "showcases": [{"key": "showcase", "label": "Ignite Showcase", "races": 3}],
    },
}


@pytest.mark.asyncio
async def test_a_showcase_slot_takes_any_field_and_keeps_its_races(
    test_client, users, async_session
):
    _, orga = users
    async with async_session() as db:
        duel = await _race(db, orga, "standard", "s20", max_participants=2)
        extra = await _race(db, orga, "standard", "s21")
        await db.commit()
    async with test_client as client:
        created = await client.post("/api/admin/events", json=_upsert(SHOWCASE_DOC), headers=ADMIN)
        event_id = created.json()["id"]
        # The runners are picked by hand: no field size to make room for.
        accepted = await client.post(
            f"/api/admin/races/{duel.id}/event",
            json={"event_id": event_id, "slot": "showcase:1"},
            headers=ADMIN,
        )
        assert accepted.status_code == 200, accepted.text
        beyond = await client.post(
            f"/api/admin/races/{extra.id}/event",
            json={"event_id": event_id, "slot": "showcase:4"},
            headers=ADMIN,
        )
        assert beyond.status_code == 422 and "races" in beyond.text

        dropped = await client.post("/api/admin/events", json=_upsert(DOC), headers=ADMIN)
        assert dropped.status_code == 422 and "showcase:1" in dropped.text


@pytest.mark.asyncio
async def test_upsert_refuses_a_withdrawn_name_that_matches_no_user(test_client, users):
    doc = dict(DOC, config=dict(DOC["config"], withdrawn=["ORGA", "ghost"]))
    async with test_client as client:
        response = await client.post("/api/admin/events", json=_upsert(doc), headers=ADMIN)
    assert response.status_code == 422
    assert "ghost" in response.text
    assert "ORGA" not in response.text


@pytest.mark.asyncio
async def test_upsert_refuses_a_caster_language_name_that_matches_no_user(test_client, users):
    doc = dict(DOC, config=dict(DOC["config"], caster_languages={"orga": "EN", "ghost": "FR"}))
    async with test_client as client:
        response = await client.post("/api/admin/events", json=_upsert(doc), headers=ADMIN)
    assert response.status_code == 422
    assert "caster_languages" in response.text
    assert "ghost" in response.text


@pytest.mark.asyncio
async def test_upsert_takes_withdrawn_names_whatever_their_case(test_client, users):
    doc = dict(DOC, config=dict(DOC["config"], withdrawn=[" ORGA "]))
    async with test_client as client:
        response = await client.post("/api/admin/events", json=_upsert(doc), headers=ADMIN)
    assert response.status_code == 200, response.text


def _locked_doc(lock: datetime, **config: object) -> dict[str, Any]:
    """DOC with its cut a day ago, its first evening in ten days and a lock in between."""
    now = datetime.now(UTC)
    raw = bracketed(DOC["config"])
    dated = [s for b in raw["brackets"] for s in b["stages"] if s.get("date")]
    for i, stage in enumerate(dated):
        stage["date"] = (now + timedelta(days=10 + i)).isoformat()
    raw.update({"draw_locks_at": lock.isoformat(), **config})
    return {
        **DOC,
        "starts_at": (now - timedelta(days=8)).isoformat(),
        "qualifier_ends_at": (now - timedelta(days=1)).isoformat(),
        "ends_at": (now + timedelta(days=30)).isoformat(),
        "config": raw,
    }


@pytest.mark.asyncio
async def test_upsert_refuses_a_lock_outside_the_cut_and_the_first_evening(test_client, users):
    early = _locked_doc(datetime.now(UTC) - timedelta(days=2))
    async with test_client as client:
        response = await client.post("/api/admin/events", json=early, headers=ADMIN)
    assert response.status_code == 422
    assert "draw_locks_at" in response.text


@pytest.mark.asyncio
async def test_upsert_refuses_forfeits_before_the_lock(test_client, users):
    doc = _locked_doc(datetime.now(UTC) + timedelta(days=2), forfeits=["orga"])
    async with test_client as client:
        response = await client.post("/api/admin/events", json=doc, headers=ADMIN)
    assert response.status_code == 422
    assert "forfeits" in response.text


@pytest.mark.asyncio
async def test_upsert_freezes_withdrawn_once_the_lock_has_passed(test_client, users):
    lock = datetime.now(UTC) - timedelta(hours=1)
    async with test_client as client:
        # Created after its own lock: nothing stored to compare, accepted.
        created = await client.post(
            "/api/admin/events", json=_locked_doc(lock, withdrawn=["orga"]), headers=ADMIN
        )
        assert created.status_code == 200, created.text
        same = await client.post(
            "/api/admin/events", json=_locked_doc(lock, withdrawn=[" ORGA "]), headers=ADMIN
        )
        assert same.status_code == 200, same.text
        changed = await client.post(
            "/api/admin/events", json=_locked_doc(lock, withdrawn=[]), headers=ADMIN
        )
        assert changed.status_code == 422
        assert "withdrawn" in changed.text
        late = await client.post(
            "/api/admin/events",
            json=_locked_doc(lock, withdrawn=["orga"], forfeits=["root"]),
            headers=ADMIN,
        )
        assert late.status_code == 200, late.text


@pytest.mark.asyncio
async def test_upsert_refuses_a_forfeits_name_that_matches_no_user(test_client, users):
    doc = _locked_doc(datetime.now(UTC) - timedelta(hours=1), forfeits=["ghost"])
    async with test_client as client:
        response = await client.post("/api/admin/events", json=doc, headers=ADMIN)
    assert response.status_code == 422
    assert "ghost" in response.text


def _with_rewards(rewards: dict[str, Any]) -> dict[str, Any]:
    doc = _upsert(DOC)
    doc["config"]["brackets"][0]["rewards"] = rewards
    return doc


@pytest.mark.asyncio
async def test_upsert_keeps_a_brackets_rewards(test_client, users):
    rewards = {
        "seated": {"name_templates": ["season_one_qualifier"]},
        "champion": {"badges": ["season_one_champion"], "phantom_skins": ["violet-aura"]},
    }
    async with test_client as client:
        response = await client.post(
            "/api/admin/events", json=_with_rewards(rewards), headers=ADMIN
        )
        assert response.status_code == 200, response.text
        listed = await client.get("/api/admin/events", headers=ADMIN)
    stored = listed.json()[0]["config"]["brackets"][0]["rewards"]
    assert stored["champion"]["phantom_skins"] == ["violet-aura"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field, reward_id",
    [
        ("badges", "nope"),
        ("badges", "weekly_daily_champion"),
        ("name_templates", "default"),
        ("phantom_skins", "random"),
        ("phantom_skins", "none"),
    ],
)
async def test_upsert_refuses_rewards_the_catalog_cannot_grant(
    test_client, users, field, reward_id
):
    doc = _with_rewards({"seated": {field: [reward_id]}})
    async with test_client as client:
        response = await client.post("/api/admin/events", json=doc, headers=ADMIN)
    assert response.status_code == 422
    assert reward_id in response.text
    assert "brackets.0.rewards.seated" in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("ids", [[""], ["  "], ["violet-aura", "violet-aura"]])
async def test_upsert_refuses_a_blank_or_repeated_reward_id(test_client, users, ids):
    doc = _with_rewards({"champion": {"phantom_skins": ids}})
    async with test_client as client:
        response = await client.post("/api/admin/events", json=doc, headers=ADMIN)
    assert response.status_code == 422


@pytest.fixture
async def reward_admin(async_session):
    """An admin and the pools the ranked-season helpers seed races from.

    Not ``users``: the helpers create their own ``orga`` organizer.
    """
    async with async_session() as db:
        db.add_all(
            [
                User(
                    twitch_id="a", twitch_username="root", api_token="tok-root", role=UserRole.ADMIN
                ),
                Pool(name="boss_rush", config={}),
            ]
        )
        await db.commit()


KINDLED_REF = "name_template:season_one_qualifier"


async def _ranked_event_with_rewards(async_session, config: dict[str, Any] | None = None) -> str:
    """A season with 7 finished-ladder runners, runner1 already owning Kindled; its id."""
    async with async_session() as db:
        event = await _ranked_event(db, config=config or rewarded(RANKED_CONFIG))
        await _ranked_runners(db, event, 7, RaceStatus.FINISHED)
        runner1 = (
            await db.execute(select(User).where(User.twitch_username == "runner1"))
        ).scalar_one()
        db.add(NameTemplateUnlock(user_id=runner1.id, template_id="season_one_qualifier"))
        await db.commit()
        return str(event.id)


def _block(data: dict[str, Any], key: str, role: str) -> dict[str, Any]:
    return next(b for b in data["blocks"] if (b["bracket_key"], b["role"]) == (key, role))


@pytest.mark.asyncio
async def test_rewards_preview_lists_each_block_with_what_is_new(
    test_client, reward_admin, async_session
):
    event_id = await _ranked_event_with_rewards(async_session)
    async with test_client as client:
        response = await client.get(f"/api/admin/events/{event_id}/rewards", headers=ADMIN)
    assert response.status_code == 200, response.text
    data = response.json()
    seated = _block(data, "main", "seated")
    assert seated["waiting"] is None
    assert seated["rewards"] == [
        {"kind": "name_template", "id": "season_one_qualifier", "name": "Kindled"}
    ]
    assert len(seated["recipients"]) == 4
    owned = {r["user"]["twitch_username"]: r["owned"] for r in seated["recipients"]}
    assert owned["runner1"] == [KINDLED_REF]
    assert owned["runner2"] == []
    assert seated["new_grants"] == 3
    champion = _block(data, "main", "champion")
    assert champion["waiting"] == "stage_incomplete"
    assert champion["recipients"] == []


@pytest.mark.asyncio
async def test_granting_a_block_grants_it_alone(test_client, reward_admin, async_session):
    event_id = await _ranked_event_with_rewards(async_session)
    url = f"/api/admin/events/{event_id}/rewards"
    async with test_client as client:
        granted = await client.post(f"{url}/main/seated", headers=ADMIN)
        assert granted.status_code == 200, granted.text
        assert granted.json()["granted"] == 3
        assert granted.json()["block"]["new_grants"] == 0
        again = await client.post(f"{url}/main/seated", headers=ADMIN)
        assert again.json()["granted"] == 0
        preview = (await client.get(url, headers=ADMIN)).json()
    # The newcomers block is its own grant: still waiting on its click.
    assert _block(preview, "newcomers", "seated")["new_grants"] == 2


@pytest.mark.asyncio
async def test_granting_a_waiting_block_is_a_conflict(test_client, reward_admin, async_session):
    event_id = await _ranked_event_with_rewards(async_session)
    async with test_client as client:
        response = await client.post(
            f"/api/admin/events/{event_id}/rewards/main/champion", headers=ADMIN
        )
    assert response.status_code == 409
    assert response.json()["detail"] == "stage_incomplete"
    async with async_session() as db:
        count = (await db.execute(select(NameTemplateUnlock))).scalars().all()
    assert len(count) == 1  # runner1's pre-existing unlock only


@pytest.mark.asyncio
async def test_granting_a_block_without_rewards_is_not_found(
    test_client, reward_admin, async_session
):
    config = rewarded(RANKED_CONFIG)
    config["brackets"][1]["rewards"] = {"champion": {"phantom_skins": ["violet-aura"]}}
    event_id = await _ranked_event_with_rewards(async_session, config)
    url = f"/api/admin/events/{event_id}/rewards"
    async with test_client as client:
        preview = (await client.get(url, headers=ADMIN)).json()
        assert [b["role"] for b in preview["blocks"] if b["bracket_key"] == "newcomers"] == [
            "champion"
        ]
        assert (await client.post(f"{url}/newcomers/seated", headers=ADMIN)).status_code == 404
        assert (await client.post(f"{url}/nope/seated", headers=ADMIN)).status_code == 404
        assert (await client.post(f"{url}/main/finalists", headers=ADMIN)).status_code == 422
        missing = await client.get(f"/api/admin/events/{uuid.uuid4()}/rewards", headers=ADMIN)
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_rewards_of_an_invalid_stored_config_answer_422(
    test_client, reward_admin, async_session
):
    event_id = await _ranked_event_with_rewards(async_session)
    async with async_session() as db:
        event = await db.get(Event, uuid.UUID(event_id))
        event.config = dict(event.config, brackets="broken")
        await db.commit()
    url = f"/api/admin/events/{event_id}/rewards"
    async with test_client as client:
        got = await client.get(url, headers=ADMIN)
        posted = await client.post(f"{url}/main/seated", headers=ADMIN)
    assert got.status_code == 422, got.text
    assert posted.status_code == 422, posted.text
