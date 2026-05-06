"""Unit tests for api/helpers.py utilities."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest
from fastapi import HTTPException

from speedfog_racing.api.helpers import parse_enum_csv
from speedfog_racing.models import RaceStatus


def test_parse_enum_csv_returns_none_when_missing_or_blank():
    """``None``, empty string, and whitespace-only mean "no filter"."""
    assert parse_enum_csv(None, RaceStatus) is None
    assert parse_enum_csv("", RaceStatus) is None
    assert parse_enum_csv("   ", RaceStatus) is None


def test_parse_enum_csv_parses_single_and_multi_values():
    assert parse_enum_csv("setup", RaceStatus) == [RaceStatus.SETUP]
    assert parse_enum_csv("setup,running", RaceStatus) == [
        RaceStatus.SETUP,
        RaceStatus.RUNNING,
    ]


def test_parse_enum_csv_strips_and_skips_empty_tokens():
    """Trailing or duplicated commas don't produce phantom entries."""
    assert parse_enum_csv(" setup , running ", RaceStatus) == [
        RaceStatus.SETUP,
        RaceStatus.RUNNING,
    ]
    assert parse_enum_csv("setup,,running,", RaceStatus) == [
        RaceStatus.SETUP,
        RaceStatus.RUNNING,
    ]


def test_parse_enum_csv_raises_400_on_invalid_token():
    """Any unknown token aborts with HTTP 400 and names the offender."""
    with pytest.raises(HTTPException) as excinfo:
        parse_enum_csv("setup,bogus", RaceStatus)
    assert excinfo.value.status_code == 400
    assert "bogus" in excinfo.value.detail
