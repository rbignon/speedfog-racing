"""Sanctions: disqualification and ban."""

import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Event,
    EventSignup,
    Invite,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    TrainingSession,
    TrainingSessionStatus,
    User,
    UserRole,
)
from speedfog_racing.services.chat_access import is_active_participant_status
from speedfog_racing.services.daily_points_service import daily_points_for_race
from speedfog_racing.services.event_service import score_race
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
    race id and participant ids by user key. A daily gets today's rotation
    date, which is still yesterday's calendar date before 08:00 UTC."""
    from speedfog_racing.services.daily_seed_loop import daily_date_for

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
            daily_date=daily_date_for(datetime.now(UTC)) if daily else None,
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


def _scored_race(statuses: list[ParticipantStatus], *, daily: bool = True) -> Race:
    race = Race(
        id=uuid.uuid4(),
        name="d",
        status=RaceStatus.FINISHED,
        daily_date=datetime.now(UTC).date() if daily else None,
    )
    race.participants = [
        Participant(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            status=s,
            igt_ms=1000 * (i + 1),
            current_layer=3,
            zone_history=[{"node_id": "a"}, {"node_id": "b"}],
        )
        for i, s in enumerate(statuses)
    ]
    return race


def test_disqualified_runner_leaves_the_daily_field() -> None:
    with_dq = _scored_race(
        [ParticipantStatus.DISQUALIFIED, ParticipantStatus.FINISHED, ParticipantStatus.FINISHED]
    )
    without = _scored_race([ParticipantStatus.FINISHED, ParticipantStatus.FINISHED])
    points = daily_points_for_race(with_dq)
    assert with_dq.participants[0].id not in points
    assert sorted(points.values()) == sorted(daily_points_for_race(without).values())


@pytest.mark.parametrize("settled_only", [False, True])
def test_disqualified_runner_leaves_the_qualifier_field(settled_only: bool) -> None:
    with_dq = _scored_race(
        [ParticipantStatus.DISQUALIFIED, ParticipantStatus.FINISHED, ParticipantStatus.FINISHED],
        daily=False,
    )
    without = _scored_race([ParticipantStatus.FINISHED, ParticipantStatus.FINISHED], daily=False)
    scores = score_race(with_dq, settled_only=settled_only)
    assert with_dq.participants[0].user_id not in scores
    assert sorted(s.points for s in scores.values()) == sorted(
        s.points for s in score_race(without, settled_only=settled_only).values()
    )


def test_disqualified_is_not_an_active_participant() -> None:
    assert not is_active_participant_status(ParticipantStatus.DISQUALIFIED)


async def test_new_winner_gets_the_race_win_after_a_disqualification(
    sx_client, sx_session, sx_users, monkeypatch
):
    import speedfog_racing.api.races as races_api
    from speedfog_racing.rewards.service import RewardsService

    monkeypatch.setattr(races_api, "fire_disqualification_notification", MagicMock())
    granted: list[uuid.UUID] = []

    async def fake_grant(self, user_id, skin_id, reason=None):  # noqa: ANN001
        granted.append(user_id)

    monkeypatch.setattr(RewardsService, "grant_phantom_skin", fake_grant)
    # Three finishers: once the cheater is out, two racers are left, enough
    # for the race-win reward.
    race_id, ids = await _race(
        sx_session,
        sx_users,
        status=RaceStatus.FINISHED,
        runners={
            "cheater": ParticipantStatus.FINISHED,
            "other": ParticipantStatus.FINISHED,
            "organizer": ParticipantStatus.FINISHED,
        },
    )
    async with sx_session() as db:
        other = await db.get(Participant, ids["other"])
        other.igt_ms = 90_000
        organizer = await db.get(Participant, ids["organizer"])
        organizer.igt_ms = 120_000
        race = await db.get(Race, race_id)
        race.is_public = True
        await db.commit()
    async with sx_client as client:
        await client.post(
            _dq_url(race_id, ids["cheater"]),
            json={"reason": REASON},
            headers=_auth(sx_users["admin"]),
        )
    assert granted == [sx_users["other"].id]


async def _closed_daily(sx_session, sx_users, *, weeks_back: int) -> tuple[uuid.UUID, uuid.UUID]:
    """A finished daily, ``weeks_back`` weeks before this one, won by "cheater"
    ahead of "other"; returns the race id and the cheater's participant id."""
    from speedfog_racing.services.daily_seed_loop import daily_date_for

    today = daily_date_for(datetime.now(UTC))
    day = today - timedelta(days=today.weekday() + 7 * weeks_back - 2)
    race_id, ids = await _race(
        sx_session,
        sx_users,
        status=RaceStatus.FINISHED,
        runners={"cheater": ParticipantStatus.FINISHED, "other": ParticipantStatus.FINISHED},
    )
    async with sx_session() as db:
        race = await db.get(Race, race_id)
        race.daily_date = day
        for key, igt in (("cheater", 60_000), ("other", 90_000)):
            p = await db.get(Participant, ids[key])
            p.igt_ms = igt
            p.zone_history = [{"node_id": "a", "igt_ms": 0}, {"node_id": "b", "igt_ms": igt}]
        await db.commit()
    return race_id, ids["cheater"]


async def _weekly_holders(sx_session, badge_id: str) -> set[uuid.UUID]:
    from speedfog_racing.models import BadgeGrant

    async with sx_session() as db:
        rows = await db.execute(
            select(BadgeGrant.user_id).where(
                BadgeGrant.badge_id == badge_id, BadgeGrant.revoked_at.is_(None)
            )
        )
        return set(rows.scalars().all())


async def test_disqualification_in_an_old_week_keeps_this_week_s_badge_holders(
    sx_client, sx_session, sx_users, monkeypatch
):
    # The weekly badges belong to last week's champions; an audit of a daily
    # weeks older must not hand them back to that old week's field.
    import speedfog_racing.api.races as races_api
    from speedfog_racing.models import PhantomSkinUnlock
    from speedfog_racing.rewards.service import RewardsService

    monkeypatch.setattr(races_api, "fire_disqualification_notification", MagicMock())
    holder = sx_users["organizer"].id
    async with sx_session() as db:
        svc = RewardsService(db)
        await svc.sync_transient_holders("weekly_daily_champion", {holder})
        await svc.sync_transient_holders("weekly_daily_winner", {holder})
        await db.commit()
    race_id, cheater = await _closed_daily(sx_session, sx_users, weeks_back=3)
    async with sx_client as client:
        resp = await client.post(
            _dq_url(race_id, cheater), json={"reason": REASON}, headers=_auth(sx_users["admin"])
        )
    assert resp.status_code == 200, resp.text
    assert await _weekly_holders(sx_session, "weekly_daily_champion") == {holder}
    assert await _weekly_holders(sx_session, "weekly_daily_winner") == {holder}
    # The old week's new champion still gets the permanent reward.
    async with sx_session() as db:
        skins = await db.execute(
            select(PhantomSkinUnlock.skin_id).where(
                PhantomSkinUnlock.user_id == sx_users["other"].id
            )
        )
        assert "gold-aura" in set(skins.scalars().all())


async def test_disqualification_in_last_week_moves_the_weekly_badges(
    sx_client, sx_session, sx_users, monkeypatch
):
    import speedfog_racing.api.races as races_api
    from speedfog_racing.rewards.service import RewardsService

    monkeypatch.setattr(races_api, "fire_disqualification_notification", MagicMock())
    race_id, cheater = await _closed_daily(sx_session, sx_users, weeks_back=1)
    async with sx_session() as db:
        await RewardsService(db).sync_transient_holders(
            "weekly_daily_champion", {sx_users["cheater"].id}
        )
        await db.commit()
    async with sx_client as client:
        await client.post(
            _dq_url(race_id, cheater), json={"reason": REASON}, headers=_auth(sx_users["admin"])
        )
    assert await _weekly_holders(sx_session, "weekly_daily_champion") == {sx_users["other"].id}


async def test_a_disqualified_daily_loses_its_streak_credit_until_cancelled(
    sx_client, sx_session, sx_users, monkeypatch
):
    import speedfog_racing.api.races as races_api

    monkeypatch.setattr(races_api, "fire_disqualification_notification", MagicMock())
    race_id, ids = await _race(
        sx_session,
        sx_users,
        daily=True,
        runners={"cheater": ParticipantStatus.FINISHED, "other": ParticipantStatus.PLAYING},
    )
    async with sx_session() as db:
        p = await db.get(Participant, ids["cheater"])
        p.zone_history = [{"node_id": "a", "igt_ms": 0}, {"node_id": "b", "igt_ms": 60_000}]
        race = await db.get(Race, race_id)
        # Credited live when the run reached its second zone.
        cheater = await db.get(User, sx_users["cheater"].id)
        cheater.daily_current_streak = 1
        cheater.daily_best_streak = 1
        cheater.daily_last_qualifying_date = race.daily_date
        await db.commit()

    async def streak() -> int:
        async with sx_session() as db:
            user = await db.get(User, sx_users["cheater"].id)
            return user.daily_current_streak

    async with sx_client as client:
        url = _dq_url(race_id, ids["cheater"])
        await client.post(url, json={"reason": REASON}, headers=_auth(sx_users["admin"]))
        assert await streak() == 0
        await client.delete(url, headers=_auth(sx_users["admin"]))
        assert await streak() == 1


async def test_a_daily_run_that_never_qualified_leaves_the_streak_alone(
    sx_client, sx_session, sx_users, monkeypatch
):
    # No streak credit at stake: the DQ and its cancel must not re-derive the
    # streak, which would wipe freeze rows an admin inserted by hand.
    import speedfog_racing.api.races as races_api
    from speedfog_racing.models import DailyStreakFreeze

    monkeypatch.setattr(races_api, "fire_disqualification_notification", MagicMock())
    race_id, ids = await _race(sx_session, sx_users, daily=True)
    vacation = date(2026, 1, 5)
    async with sx_session() as db:
        db.add(DailyStreakFreeze(user_id=sx_users["cheater"].id, daily_date=vacation))
        await db.commit()
    async with sx_client as client:
        url = _dq_url(race_id, ids["cheater"])
        await client.post(url, json={"reason": REASON}, headers=_auth(sx_users["admin"]))
        await client.delete(url, headers=_auth(sx_users["admin"]))
    async with sx_session() as db:
        rows = await db.execute(
            select(DailyStreakFreeze.daily_date).where(
                DailyStreakFreeze.user_id == sx_users["cheater"].id
            )
        )
        assert list(rows.scalars().all()) == [vacation]


async def test_a_cancel_that_restores_a_14_day_streak_grants_its_reward(
    sx_client, sx_session, sx_users, monkeypatch
):
    import speedfog_racing.api.races as races_api
    from speedfog_racing.models import PhantomSkinUnlock
    from speedfog_racing.services.daily_seed_loop import daily_date_for
    from speedfog_racing.services.daily_streak_service import backfill_user

    monkeypatch.setattr(races_api, "fire_disqualification_notification", MagicMock())
    push = AsyncMock()
    monkeypatch.setattr(races_api.manager, "send_daily_streak_update_to_user", push)
    qualified = [{"node_id": "a", "igt_ms": 0}, {"node_id": "b", "igt_ms": 60_000}]
    race_id, ids = await _race(
        sx_session,
        sx_users,
        daily=True,
        runners={"cheater": ParticipantStatus.FINISHED, "other": ParticipantStatus.PLAYING},
    )
    today = daily_date_for(datetime.now(UTC))
    async with sx_session() as db:
        # Thirteen qualified days before today's run: today makes fourteen.
        for back in range(1, 14):
            past = Race(
                name="Past daily",
                organizer_id=sx_users["organizer"].id,
                status=RaceStatus.FINISHED,
                daily_date=today - timedelta(days=back),
            )
            db.add(past)
            await db.flush()
            db.add(
                Participant(
                    race_id=past.id,
                    user_id=sx_users["cheater"].id,
                    status=ParticipantStatus.FINISHED,
                    zone_history=qualified,
                )
            )
        p = await db.get(Participant, ids["cheater"])
        p.zone_history = qualified
        await db.commit()
        await backfill_user(db, sx_users["cheater"].id)
        await db.commit()
    async with sx_client as client:
        url = _dq_url(race_id, ids["cheater"])
        await client.post(url, json={"reason": REASON}, headers=_auth(sx_users["admin"]))
        await client.delete(url, headers=_auth(sx_users["admin"]))
    async with sx_session() as db:
        skins = await db.execute(
            select(PhantomSkinUnlock.skin_id).where(
                PhantomSkinUnlock.user_id == sx_users["cheater"].id
            )
        )
        assert "molten-aura" in set(skins.scalars().all())
    # The runner's open pages hear of the streak both times.
    assert [c.kwargs["best"] for c in push.call_args_list] == [13, 14]


async def test_reset_keeps_a_disqualification(sx_client, sx_session, sx_users, monkeypatch):
    import speedfog_racing.api.races as races_api

    monkeypatch.setattr(races_api, "fire_disqualification_notification", MagicMock())
    race_id, ids = await _race(sx_session, sx_users)
    async with sx_client as client:
        await client.post(
            _dq_url(race_id, ids["cheater"]),
            json={"reason": REASON},
            headers=_auth(sx_users["admin"]),
        )
        resp = await client.post(
            f"/api/races/{race_id}/reset", headers=_auth(sx_users["organizer"])
        )
        assert resp.status_code == 200, resp.text
        detail = (
            await client.get(f"/api/races/{race_id}", headers=_auth(sx_users["admin"]))
        ).json()
    statuses = {p["id"]: p["status"] for p in detail["participants"]}
    assert statuses[str(ids["cheater"])] == "disqualified"
    assert statuses[str(ids["other"])] == "registered"


async def test_cancel_after_a_reset_starts_the_runner_over(
    sx_client, sx_session, sx_users, monkeypatch
):
    import speedfog_racing.api.races as races_api

    monkeypatch.setattr(races_api, "fire_disqualification_notification", MagicMock())
    race_id, ids = await _race(
        sx_session,
        sx_users,
        runners={"cheater": ParticipantStatus.FINISHED, "other": ParticipantStatus.PLAYING},
    )
    async with sx_client as client:
        url = _dq_url(race_id, ids["cheater"])
        await client.post(url, json={"reason": REASON}, headers=_auth(sx_users["admin"]))
        await client.post(f"/api/races/{race_id}/reset", headers=_auth(sx_users["organizer"]))
        resp = await client.delete(url, headers=_auth(sx_users["admin"]))
    assert resp.status_code == 200, resp.text
    row = next(p for p in resp.json()["participants"] if p["id"] == str(ids["cheater"]))
    assert row["status"] == "registered"
    assert row["igt_ms"] == 0


async def test_cancel_after_a_daily_reroll_starts_the_runner_over(
    sx_client, sx_session, sx_users, monkeypatch
):
    # A reroll keeps the daily running and its start time: the saved FINISHED
    # belongs to the old seed and must not come back on the new one.
    import speedfog_racing.api.races as races_api

    monkeypatch.setattr(races_api, "fire_disqualification_notification", MagicMock())
    race_id, ids = await _race(
        sx_session,
        sx_users,
        daily=True,
        runners={"cheater": ParticipantStatus.FINISHED, "other": ParticipantStatus.PLAYING},
    )
    async with sx_session() as db:
        db.add(
            Seed(
                seed_number="sx_reroll",
                pool_name="standard",
                graph_json={"total_layers": 5, "nodes": {}},
                total_layers=5,
                folder_path="/test/sx_reroll",
                status=SeedStatus.AVAILABLE,
            )
        )
        await db.commit()
    async with sx_client as client:
        url = _dq_url(race_id, ids["cheater"])
        await client.post(url, json={"reason": REASON}, headers=_auth(sx_users["admin"]))
        reroll = await client.post(
            f"/api/races/{race_id}/reroll-seed", headers=_auth(sx_users["admin"])
        )
        assert reroll.status_code == 200, reroll.text
        resp = await client.delete(url, headers=_auth(sx_users["admin"]))
    assert resp.status_code == 200, resp.text
    row = next(p for p in resp.json()["participants"] if p["id"] == str(ids["cheater"]))
    assert (row["status"], row["igt_ms"]) == ("registered", 0)


async def test_cancel_in_a_finished_race_never_leaves_a_runner_playing(
    sx_client, sx_session, sx_users, monkeypatch
):
    # Disqualifying the last runner still out finished the race: the run they
    # were on is over, so the cancel gives them back an abandon, not a live run.
    import speedfog_racing.api.races as races_api

    monkeypatch.setattr(races_api, "fire_race_finished_notifications", MagicMock())
    monkeypatch.setattr(races_api, "fire_disqualification_notification", MagicMock())
    race_id, ids = await _race(
        sx_session,
        sx_users,
        runners={"cheater": ParticipantStatus.PLAYING, "other": ParticipantStatus.FINISHED},
    )
    async with sx_client as client:
        url = _dq_url(race_id, ids["cheater"])
        await client.post(url, json={"reason": REASON}, headers=_auth(sx_users["admin"]))
        resp = await client.delete(url, headers=_auth(sx_users["admin"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "finished"
    row = next(p for p in resp.json()["participants"] if p["id"] == str(ids["cheater"]))
    assert (row["status"], row["igt_ms"]) == ("abandoned", 30_000)


async def test_under_review_participation_cannot_leave_or_be_removed(
    sx_client, sx_session, sx_users
):
    race_id, ids = await _race(
        sx_session,
        sx_users,
        status=RaceStatus.SETUP,
        runners={"cheater": ParticipantStatus.REGISTERED, "other": ParticipantStatus.REGISTERED},
    )
    async with sx_session() as db:
        p = await db.get(Participant, ids["cheater"])
        p.debug_flags = {"one_shot": {"igt_ms": 1, "node_id": None, "detected_at": "x"}}
        await db.commit()
    async with sx_client as client:
        leave = await client.post(f"/api/races/{race_id}/leave", headers=_auth(sx_users["cheater"]))
        remove = await client.delete(
            f"/api/races/{race_id}/participants/{ids['cheater']}",
            headers=_auth(sx_users["organizer"]),
        )
    assert leave.status_code == 400, leave.text
    assert leave.json()["detail"] == "This participation is under review"
    assert remove.status_code == 400, remove.text


async def _ban(sx_session, user: User, by: User, reason: str = "Repeat cheating") -> None:
    async with sx_session() as db:
        target = await db.get(User, user.id)
        target.banned_at = datetime.now(UTC)
        target.banned_by_id = by.id
        target.ban_reason = reason
        await db.commit()


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/races", {"name": "x"}),
        ("/api/races/{race_id}/join", None),
        ("/api/races/{race_id}/cast-join", None),
        ("/api/invite/not-a-token/accept", None),
        ("/api/training", {"pool_name": "standard"}),
        ("/api/events/no-such-event/signup", None),
    ],
)
async def test_banned_user_is_refused_at_every_entry_point(
    sx_client, sx_session, sx_users, path, body
):
    race_id, _ = await _race(sx_session, sx_users, status=RaceStatus.SETUP, runners={})
    await _ban(sx_session, sx_users["cheater"], sx_users["admin"])
    async with sx_client as client:
        resp = await client.post(
            path.format(race_id=race_id),
            headers=_auth(sx_users["cheater"]),
            **({"json": body} if body is not None else {}),
        )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Your account is banned"


async def test_organizer_cannot_add_a_banned_user(sx_client, sx_session, sx_users):
    race_id, _ = await _race(sx_session, sx_users, status=RaceStatus.SETUP, runners={})
    await _ban(sx_session, sx_users["cheater"], sx_users["admin"])
    async with sx_client as client:
        resp = await client.post(
            f"/api/races/{race_id}/participants",
            json={"twitch_username": "cheater_sx"},
            headers=_auth(sx_users["organizer"]),
        )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "This user is banned"


async def test_ban_endpoints_are_admin_only_and_spare_admins(sx_client, sx_users):
    async with sx_client as client:
        url = f"/api/admin/users/{sx_users['cheater'].id}/ban"
        by_org = await client.post(url, json={"reason": "x"}, headers=_auth(sx_users["organizer"]))
        on_admin = await client.post(
            f"/api/admin/users/{sx_users['admin'].id}/ban",
            json={"reason": "x"},
            headers=_auth(sx_users["admin"]),
        )
        ok = await client.post(
            url, json={"reason": "Repeat cheating"}, headers=_auth(sx_users["admin"])
        )
        me = await client.get("/api/auth/me", headers=_auth(sx_users["cheater"]))
        unban = await client.delete(url, headers=_auth(sx_users["admin"]))
        me_after = await client.get("/api/auth/me", headers=_auth(sx_users["cheater"]))
    assert by_org.status_code == 403
    assert on_admin.status_code == 400
    assert ok.status_code == 200, ok.text
    assert ok.json()["ban_reason"] == "Repeat cheating"
    assert me.json()["ban_reason"] == "Repeat cheating" and me.json()["banned_at"]
    assert unban.status_code == 200
    assert me_after.json()["banned_at"] is None


async def test_ban_side_effects(sx_client, sx_session, sx_users, monkeypatch):
    import speedfog_racing.api.admin as admin_api
    import speedfog_racing.api.races as races_api
    from tests.test_events_api import CONFIG

    monkeypatch.setattr(races_api, "fire_disqualification_notification", MagicMock())
    monkeypatch.setattr(admin_api, "fire_ban_notification", MagicMock(), raising=False)
    setup_id, setup_ids = await _race(
        sx_session,
        sx_users,
        status=RaceStatus.SETUP,
        runners={"cheater": ParticipantStatus.REGISTERED},
    )
    _review_id, review_ids = await _race(
        sx_session,
        sx_users,
        status=RaceStatus.SETUP,
        runners={"cheater": ParticipantStatus.REGISTERED},
    )
    _running_id, running_ids = await _race(sx_session, sx_users)
    now = datetime.now(UTC)
    async with sx_session() as db:
        p = await db.get(Participant, review_ids["cheater"])
        p.debug_flags = {"one_shot": {"igt_ms": 1, "node_id": None, "detected_at": "x"}}
        db.add(Invite(race_id=setup_id, twitch_username="Cheater_SX"))
        event = Event(
            slug="open-event",
            name="Open",
            partner_name="P",
            starts_at=now - timedelta(days=1),
            qualifier_ends_at=now + timedelta(days=6),
            ends_at=now + timedelta(days=20),
            newcomer_threshold=5,
            config=CONFIG,
        )
        db.add(event)
        await db.flush()
        db.add(EventSignup(event_id=event.id, user_id=sx_users["cheater"].id))
        seed = (await db.execute(select(Seed))).scalars().first()
        session = TrainingSession(
            user_id=sx_users["cheater"].id,
            seed_id=seed.id,
            status=TrainingSessionStatus.ACTIVE,
        )
        db.add(session)
        await db.commit()
        session_id = session.id
    async with sx_client as client:
        resp = await client.post(
            f"/api/admin/users/{sx_users['cheater'].id}/ban",
            json={"reason": "Repeat cheating"},
            headers=_auth(sx_users["admin"]),
        )
    assert resp.status_code == 200, resp.text
    async with sx_session() as db:
        assert await db.get(Participant, setup_ids["cheater"]) is None
        kept = await db.get(Participant, review_ids["cheater"])
        assert kept is not None and kept.status == ParticipantStatus.REGISTERED
        dq = await db.get(Participant, running_ids["cheater"])
        assert dq.status == ParticipantStatus.DISQUALIFIED
        assert dq.disqualification_reason == "Account banned"
        assert (await db.execute(select(Invite))).scalars().all() == []
        assert (await db.execute(select(EventSignup))).scalars().all() == []
        training = await db.get(TrainingSession, session_id)
        assert training.status == TrainingSessionStatus.CANCELLED
        assert training.finished_at is not None


def test_banned_spectator_stops_chatting_at_once() -> None:
    from unittest.mock import AsyncMock

    from speedfog_racing.websocket.race.manager import (
        ConnectionManager,
        RaceRoom,
        SpectatorConnection,
    )

    mgr = ConnectionManager()
    race_id, user_id = uuid.uuid4(), uuid.uuid4()
    conn = SpectatorConnection(websocket=AsyncMock(), user_id=user_id)
    other = SpectatorConnection(websocket=AsyncMock(), user_id=uuid.uuid4())
    mgr.rooms[race_id] = RaceRoom(race_id=race_id)
    mgr.rooms[race_id].spectators = {conn.connection_id: conn, other.connection_id: other}
    mgr.mark_user_banned(user_id)
    assert conn.banned and not other.banned
