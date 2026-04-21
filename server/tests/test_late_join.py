"""Tests for late-join and private_dag features."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from speedfog_racing.schemas import CreateRaceRequest


def _base_kwargs(**overrides):
    scheduled_at = datetime.now(UTC) + timedelta(hours=1)
    defaults = dict(name="Test", scheduled_at=scheduled_at)
    defaults.update(overrides)
    return defaults


class TestCreateRaceRequestLateJoin:
    def test_both_null_is_valid(self):
        req = CreateRaceRequest(**_base_kwargs())
        assert req.registration_closes_at is None
        assert req.race_ends_at is None

    def test_registration_after_scheduled_requires_race_ends_at(self):
        scheduled = datetime.now(UTC) + timedelta(hours=1)
        with pytest.raises(ValidationError, match="race_ends_at"):
            CreateRaceRequest(
                **_base_kwargs(
                    scheduled_at=scheduled,
                    registration_closes_at=scheduled + timedelta(minutes=30),
                )
            )

    def test_registration_closes_at_must_be_before_race_ends_at(self):
        scheduled = datetime.now(UTC) + timedelta(hours=1)
        with pytest.raises(ValidationError, match="registration_closes_at"):
            CreateRaceRequest(
                **_base_kwargs(
                    scheduled_at=scheduled,
                    registration_closes_at=scheduled + timedelta(hours=5),
                    race_ends_at=scheduled + timedelta(hours=2),
                )
            )

    def test_race_ends_at_must_be_after_scheduled(self):
        scheduled = datetime.now(UTC) + timedelta(hours=1)
        with pytest.raises(ValidationError, match="race_ends_at"):
            CreateRaceRequest(
                **_base_kwargs(
                    scheduled_at=scheduled,
                    race_ends_at=scheduled - timedelta(minutes=1),
                )
            )

    def test_late_join_race_valid(self):
        scheduled = datetime.now(UTC) + timedelta(hours=1)
        req = CreateRaceRequest(
            **_base_kwargs(
                scheduled_at=scheduled,
                registration_closes_at=scheduled + timedelta(minutes=30),
                race_ends_at=scheduled + timedelta(hours=4),
            )
        )
        assert req.registration_closes_at == scheduled + timedelta(minutes=30)
        assert req.race_ends_at == scheduled + timedelta(hours=4)
