"""Sanctions: disqualification and ban."""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.websocket.race.manager import sort_leaderboard
from speedfog_racing.websocket.schemas import ParticipantInfo

REASON = "Cheat tool detected: One shot"


@pytest.fixture
async def sx_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def sx_client(sx_session):
    async def override_get_db():
        async with sx_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


@pytest.fixture
async def sx_users(sx_session) -> dict[str, User]:
    roles = {
        "organizer": UserRole.ORGANIZER,
        "admin": UserRole.ADMIN,
        "cheater": UserRole.USER,
        "other": UserRole.USER,
    }
    async with sx_session() as db:
        users = {
            key: User(
                twitch_id=f"sx_{key}",
                twitch_username=f"{key}_sx",
                api_token=f"sx_{key}_token",
                role=role,
            )
            for key, role in roles.items()
        }
        db.add_all(users.values())
        await db.commit()
        for user in users.values():
            await db.refresh(user)
        return users


def _auth(user: User | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {user.api_token}"} if user else {}


async def _race(
    sx_session,
    sx_users,
    *,
    status: RaceStatus = RaceStatus.RUNNING,
    runners: dict[str, ParticipantStatus] | None = None,
    daily: bool = False,
) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    """A race organized by "organizer" with the given runners; returns the
    race id and participant ids by user key."""
    runners = runners or {
        "cheater": ParticipantStatus.PLAYING,
        "other": ParticipantStatus.PLAYING,
    }
    async with sx_session() as db:
        seed = Seed(
            seed_number=f"sx_{uuid.uuid4().hex[:8]}",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": {}},
            total_layers=5,
            folder_path="/test/sx",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()
        race = Race(
            name="Sanction race",
            organizer_id=sx_users["organizer"].id,
            seed_id=seed.id,
            status=status,
            started_at=None if status == RaceStatus.SETUP else datetime.now(UTC),
            daily_date=datetime.now(UTC).date() if daily else None,
        )
        db.add(race)
        await db.flush()
        ids: dict[str, uuid.UUID] = {}
        for key, p_status in runners.items():
            p = Participant(
                race_id=race.id,
                user_id=sx_users[key].id,
                status=p_status,
                igt_ms=60_000 if p_status == ParticipantStatus.FINISHED else 30_000,
                current_layer=2,
            )
            db.add(p)
            await db.flush()
            ids[key] = p.id
        await db.commit()
        return race.id, ids


def _dq_url(race_id: uuid.UUID, participant_id: uuid.UUID) -> str:
    return f"/api/races/{race_id}/participants/{participant_id}/disqualify"


async def test_organizer_and_admin_can_disqualify(sx_client, sx_session, sx_users):
    races = {who: await _race(sx_session, sx_users) for who in ("organizer", "admin")}
    async with sx_client as client:
        for who, (race_id, ids) in races.items():
            resp = await client.post(
                _dq_url(race_id, ids["cheater"]),
                json={"reason": REASON},
                headers=_auth(sx_users[who]),
            )
            assert resp.status_code == 200, (who, resp.text)
            row = next(p for p in resp.json()["participants"] if p["id"] == str(ids["cheater"]))
            assert row["status"] == "disqualified"


async def test_others_cannot_disqualify(sx_client, sx_session, sx_users):
    race_id, ids = await _race(sx_session, sx_users)
    async with sx_client as client:
        for who, expected in (("cheater", 403), ("other", 403), (None, 401)):
            resp = await client.post(
                _dq_url(race_id, ids["cheater"]),
                json={"reason": REASON},
                headers=_auth(sx_users[who] if who else None),
            )
            assert resp.status_code == expected, who


async def test_disqualify_refused_before_the_start(sx_client, sx_session, sx_users):
    race_id, ids = await _race(
        sx_session,
        sx_users,
        status=RaceStatus.SETUP,
        runners={"cheater": ParticipantStatus.REGISTERED},
    )
    async with sx_client as client:
        resp = await client.post(
            _dq_url(race_id, ids["cheater"]),
            json={"reason": REASON},
            headers=_auth(sx_users["admin"]),
        )
    assert resp.status_code == 400


@pytest.mark.parametrize("reason", ["", "   ", "x" * 501])
async def test_disqualify_requires_a_bounded_reason(sx_client, sx_session, sx_users, reason):
    race_id, ids = await _race(sx_session, sx_users)
    async with sx_client as client:
        resp = await client.post(
            _dq_url(race_id, ids["cheater"]),
            json={"reason": reason},
            headers=_auth(sx_users["admin"]),
        )
    assert resp.status_code == 422


async def test_cancel_restores_the_previous_status(sx_client, sx_session, sx_users):
    race_id, ids = await _race(
        sx_session,
        sx_users,
        status=RaceStatus.FINISHED,
        runners={"cheater": ParticipantStatus.FINISHED, "other": ParticipantStatus.FINISHED},
    )
    async with sx_client as client:
        await client.post(
            _dq_url(race_id, ids["cheater"]),
            json={"reason": REASON},
            headers=_auth(sx_users["admin"]),
        )
        resp = await client.delete(
            _dq_url(race_id, ids["cheater"]), headers=_auth(sx_users["admin"])
        )
    assert resp.status_code == 200, resp.text
    row = next(p for p in resp.json()["participants"] if p["id"] == str(ids["cheater"]))
    assert row["status"] == "finished"
    assert row["igt_ms"] == 60_000, "run data untouched"
    assert row["disqualification_reason"] is None


async def test_double_disqualify_and_stray_cancel_are_refused(sx_client, sx_session, sx_users):
    race_id, ids = await _race(sx_session, sx_users)
    async with sx_client as client:
        url = _dq_url(race_id, ids["cheater"])
        assert (await client.delete(url, headers=_auth(sx_users["admin"]))).status_code == 400
        await client.post(url, json={"reason": REASON}, headers=_auth(sx_users["admin"]))
        again = await client.post(url, json={"reason": REASON}, headers=_auth(sx_users["admin"]))
    assert again.status_code == 400


async def test_reason_visible_to_the_runner_and_staff_only(sx_client, sx_session, sx_users):
    race_id, ids = await _race(sx_session, sx_users)
    async with sx_client as client:
        await client.post(
            _dq_url(race_id, ids["cheater"]),
            json={"reason": REASON},
            headers=_auth(sx_users["admin"]),
        )
        expected = {"organizer": True, "admin": True, "cheater": True, "other": False, None: False}
        for who, sees in expected.items():
            resp = await client.get(
                f"/api/races/{race_id}", headers=_auth(sx_users[who] if who else None)
            )
            row = next(p for p in resp.json()["participants"] if p["id"] == str(ids["cheater"]))
            assert row["status"] == "disqualified", who
            assert (row["disqualification_reason"] == REASON) == sees, who


def test_disqualified_rank_after_abandoned() -> None:
    def p(status: ParticipantStatus, layer: int) -> Participant:
        return Participant(
            id=uuid.uuid4(),
            status=status,
            current_layer=layer,
            igt_ms=1000,
            zone_history=None,
            layer_entry_igts={},
        )

    dq = p(ParticipantStatus.DISQUALIFIED, 5)
    dnf = p(ParticipantStatus.ABANDONED, 1)
    done = p(ParticipantStatus.FINISHED, 5)
    ordered, _ = sort_leaderboard([dq, dnf, done])
    assert ordered == [done, dnf, dq]


def test_participant_info_has_no_reason() -> None:
    # WebSocket participant data is public.
    assert not any("reason" in name for name in ParticipantInfo.model_fields)


async def test_disqualifying_the_last_runner_out_finishes_the_race(
    sx_client, sx_session, sx_users, monkeypatch
):
    import speedfog_racing.api.races as races_api

    monkeypatch.setattr(races_api, "fire_race_finished_notifications", MagicMock())
    monkeypatch.setattr(races_api, "fire_disqualification_notification", MagicMock(), raising=False)
    race_id, ids = await _race(
        sx_session,
        sx_users,
        runners={"cheater": ParticipantStatus.PLAYING, "other": ParticipantStatus.FINISHED},
    )
    async with sx_client as client:
        resp = await client.post(
            _dq_url(race_id, ids["cheater"]),
            json={"reason": REASON},
            headers=_auth(sx_users["admin"]),
        )
    assert resp.json()["status"] == "finished"


async def test_admin_discord_hears_of_disqualification_and_cancel(
    sx_client, sx_session, sx_users, monkeypatch
):
    import speedfog_racing.api.races as races_api

    fire = MagicMock()
    monkeypatch.setattr(races_api, "fire_disqualification_notification", fire, raising=False)
    race_id, ids = await _race(sx_session, sx_users)
    async with sx_client as client:
        url = _dq_url(race_id, ids["cheater"])
        await client.post(url, json={"reason": REASON}, headers=_auth(sx_users["admin"]))
        await client.delete(url, headers=_auth(sx_users["admin"]))
    assert [c.kwargs["cancelled"] for c in fire.call_args_list] == [False, True]
    assert fire.call_args_list[0].kwargs["reason"] == REASON
