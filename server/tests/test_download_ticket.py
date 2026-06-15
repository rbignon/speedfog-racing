"""Unit tests for signed, short-lived download tickets."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from speedfog_racing.download_ticket import sign_download_ticket, verify_download_ticket

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_round_trip_returns_user_id():
    user_id = uuid4()
    resource_id = uuid4()
    token = sign_download_ticket("race", user_id, resource_id, _NOW)
    assert verify_download_ticket(token, "race", resource_id, _NOW) == user_id


def test_expired_ticket_rejected():
    user_id = uuid4()
    resource_id = uuid4()
    token = sign_download_ticket("race", user_id, resource_id, _NOW)
    later = _NOW + timedelta(minutes=11)
    assert verify_download_ticket(token, "race", resource_id, later) is None


def test_tampered_signature_rejected():
    user_id = uuid4()
    resource_id = uuid4()
    token = sign_download_ticket("race", user_id, resource_id, _NOW)
    payload, sig = token.split(".")
    flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
    assert verify_download_ticket(f"{payload}.{flipped}", "race", resource_id, _NOW) is None


def test_wrong_scope_rejected():
    resource_id = uuid4()
    token = sign_download_ticket("race", uuid4(), resource_id, _NOW)
    assert verify_download_ticket(token, "training", resource_id, _NOW) is None


def test_wrong_resource_rejected():
    token = sign_download_ticket("race", uuid4(), uuid4(), _NOW)
    assert verify_download_ticket(token, "race", uuid4(), _NOW) is None


def test_malformed_token_rejected():
    assert verify_download_ticket("garbage", "race", uuid4(), _NOW) is None
    assert verify_download_ticket("a.b.c", "race", uuid4(), _NOW) is None


def test_expiry_boundary():
    user_id = uuid4()
    resource_id = uuid4()
    token = sign_download_ticket("race", user_id, resource_id, _NOW)
    # Exactly at expiry (now + TTL) is rejected.
    at_exp = _NOW + timedelta(minutes=10)
    assert verify_download_ticket(token, "race", resource_id, at_exp) is None
    # One second before expiry is still valid.
    before_exp = _NOW + timedelta(minutes=9, seconds=59)
    assert verify_download_ticket(token, "race", resource_id, before_exp) == user_id
