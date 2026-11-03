"""GET /api/speedrun/livesplit/{category} and the category of run details."""

import pytest
from sqlalchemy import select

from speedfog_racing.models import ParticipantStatus, Pool, RaceStatus, RunMode, Seed

from .test_speedrun_seed_endpoint import _auth, async_engine, async_session, pools, test_client
from .test_speedrun_service import _add_run, _add_session, _seed, _user

__all__ = ["async_engine", "async_session", "pools", "test_client"]


async def _get(client, category, viewer=None):
    headers = _auth(viewer) if viewer else {}
    return await client.get(f"/api/speedrun/livesplit/{category}", headers=headers)


async def test_wr_and_pb_come_from_the_random_seed_board(test_client, async_session, pools):
    async with async_session() as db:
        a, b = await _user(db, "a"), await _user(db, "b")
        await _add_run(db, user=a, igt_ms=900, minute=1)
        await _add_run(db, user=b, igt_ms=1000, minute=2)
        # A faster replay is no blind run: it stays off the Random Seed board.
        await _add_run(db, user=b, igt_ms=500, minute=3, mode=RunMode.SET_SEED)
        await db.commit()

    data = (await _get(test_client, "sprint", "b")).json()
    assert data["wr"]["igt_ms"] == 900
    assert data["wr"]["user"]["twitch_username"] == "a"
    assert data["pb"]["igt_ms"] == 1000
    assert data["category_name"] == "Sprint"
    assert data["total_layers"] == 15


async def test_pb_is_null_for_a_logged_out_viewer(test_client, async_session, pools):
    async with async_session() as db:
        await _add_run(db, user=await _user(db, "a"), igt_ms=900, minute=1)
        await db.commit()
    data = (await _get(test_client, "sprint")).json()
    assert data["wr"]["igt_ms"] == 900
    assert data["pb"] is None


async def test_pb_is_null_without_a_viewer_run(test_client, async_session, pools):
    async with async_session() as db:
        await _add_run(db, user=await _user(db, "a"), igt_ms=900, minute=1)
        await _user(db, "b")
        await db.commit()
    data = (await _get(test_client, "sprint", "b")).json()
    assert data["wr"]["igt_ms"] == 900
    assert data["pb"] is None


async def test_deathless_runs_count_like_any_run(test_client, async_session, pools):
    async with async_session() as db:
        a, b = await _user(db, "a"), await _user(db, "b")
        await _add_run(db, user=a, igt_ms=800, minute=1, deathless=True)
        await _add_run(db, user=b, igt_ms=900, minute=2)
        await db.commit()
    data = (await _get(test_client, "sprint")).json()
    assert data["wr"]["igt_ms"] == 800


async def test_reference_arrivals_are_first_arrivals_plus_the_finish(
    test_client, async_session, pools
):
    graph = {
        "nodes": {
            "n0": {"layer": 0},
            "n1": {"layer": 1},
            "n2": {"layer": 2},
        }
    }
    history = [
        {"node_id": "n0", "igt_ms": 0},
        {"node_id": "n1", "igt_ms": 5000},
        {"node_id": "n0", "igt_ms": 6000},
        {"node_id": "n1", "igt_ms": 7000},
        {"node_id": "n2", "igt_ms": 9000},
    ]
    async with async_session() as db:
        a = await _user(db, "a")
        await _add_run(db, user=a, igt_ms=12_000, minute=1, layers=3, zone_history=history)
        seed = (await db.execute(select(Seed))).scalar_one()
        seed.graph_json = graph
        pool = (await db.execute(select(Pool).where(Pool.name == "sprint"))).scalar_one()
        pool.config = {**pool.config, "layers_count": 3}
        await db.commit()

    data = (await _get(test_client, "sprint")).json()
    assert data["total_layers"] == 3
    assert data["wr"]["layer_entry_igts"] == {"0": 0, "1": 5000, "2": 9000, "3": 12000}


async def test_a_seed_number_shared_with_another_pool_is_no_error(
    test_client, async_session, pools
):
    # Seed numbers are unique per pool only.
    async with async_session() as db:
        await _seed(db, "123456789", pool="standard")
        seed = await _seed(db, "123456789")
        await _add_run(db, user=await _user(db, "a"), igt_ms=900, minute=1, seed=seed)
        await db.commit()
    response = await _get(test_client, "sprint")
    assert response.status_code == 200
    assert response.json()["wr"]["layer_entry_igts"] == {"15": 900}


async def test_a_seed_with_a_blind_run_in_progress_gives_no_reference(
    test_client, async_session, pools
):
    async with async_session() as db:
        a, b = await _user(db, "a"), await _user(db, "b")
        seed = await _seed(db, "123456789")
        await _add_run(db, user=a, igt_ms=900, minute=1, seed=seed)
        # A community race on the SEEN seed: its runners must not get its pacing.
        await _add_run(
            db,
            user=b,
            igt_ms=0,
            minute=2,
            seed=seed,
            race_status=RaceStatus.RUNNING,
            status=ParticipantStatus.PLAYING,
            finished=False,
        )
        await db.commit()
    data = (await _get(test_client, "sprint", "a")).json()
    assert (data["wr"], data["pb"]) == (None, None)
    assert data["total_layers"] == 15


async def test_a_training_category_answers_without_references(test_client, async_session, pools):
    async with async_session() as db:
        db.add(Pool(name="training_standard", config={"name": "Standard", "type": "training"}))
        await db.commit()
    response = await _get(test_client, "training_standard")
    assert response.status_code == 200
    data = response.json()
    assert (data["wr"], data["pb"]) == (None, None)
    assert data["category_name"] == "Standard"


async def test_an_unknown_category_is_404(test_client, async_session, pools):
    assert (await _get(test_client, "nowhere")).status_code == 404
    assert (await _get(test_client, "sprint@many")).status_code == 404


async def test_total_layers_comes_from_the_key_suffix(test_client, async_session, pools):
    async with async_session() as db:
        pool = (await db.execute(select(Pool).where(Pool.name == "sprint"))).scalar_one()
        pool.config = {**pool.config, "archived_layers": [12]}
        await _add_run(db, user=await _user(db, "a"), igt_ms=900, minute=1, layers=12)
        await db.commit()
    data = (await _get(test_client, "sprint@12")).json()
    assert data["total_layers"] == 12
    assert data["category_name"] == "Sprint (12 layers)"
    assert data["wr"]["igt_ms"] == 900


@pytest.mark.parametrize(("layers", "expected"), [(15, "sprint"), (12, "sprint@12")])
async def test_run_details_carry_the_seed_category(
    test_client, async_session, pools, layers, expected
):
    async with async_session() as db:
        a = await _user(db, "a")
        part = await _add_run(db, user=a, igt_ms=900, minute=1, layers=layers)
        session = await _add_session(db, a, "sprint", RunMode.SPEEDRUN, 900, layers=layers)
        await db.commit()
    race = (await test_client.get(f"/api/races/{part.race_id}")).json()
    solo = (await test_client.get(f"/api/training/{session.id}")).json()
    assert race["category"] == expected
    assert solo["category"] == expected
