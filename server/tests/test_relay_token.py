"""Relay save binding: the token a member's validation draws, and the mod's ``relay_bound``."""

from typing import Any

import pytest

from . import test_integration as _integration
from .relay_fixtures import (
    RelayModClient,
    barrier,
    load_member,
    load_members,
    make_receiver,
    member_view,
    setup_relay_race,
    started_mods,
    validate,
)
from .test_relay_baton import _hand_off, _started_before_any_report, _taken

integration_db = _integration.integration_db
integration_client = _integration.integration_client

# The token's width is the seed's ``token_bits`` (24); 0 is never drawn.
TOKEN_MAX = 2**24 - 1


@pytest.fixture
def relay_race(integration_db, integration_client):
    return setup_relay_race(integration_db)


@pytest.fixture
def mods(integration_client, relay_race):
    yield from started_mods(integration_client, relay_race)


def _pid(relay_race: dict[str, Any], team: int, member: int) -> str:
    pid: str = relay_race["teams"][team]["members"][member]["participant_id"]
    return pid


def _own(update: dict[str, Any]) -> tuple[Any, Any]:
    """The receiving member's own token and binding."""
    return update["relay"]["token"], update["relay"]["bound"]


def _playing(update: dict[str, Any]) -> bool:
    return bool(update["relay"]["team_status"] == "playing")


def _bound(update: dict[str, Any]) -> bool:
    return bool(update["relay"]["bound"])


def _token(relay_race: dict[str, Any], mod: RelayModClient) -> int:
    token = load_member(relay_race, mod.participant_id).relay_token
    assert token is not None
    return token


def _updates_until_barrier(mod: RelayModClient) -> int:
    """How many ``relay_update`` the mod received until the server handled
    what it sent so far."""
    barrier(mod)
    return sum(1 for m in mod.skipped if m["type"] == "relay_update")


# --- The draw ---


def test_a_member_has_no_token_before_its_save_is_validated(relay_race, mods):
    # Connected since before the start, the teammate has not reported yet;
    # the holder's first report made the team play.
    mate = mods[_pid(relay_race, 0, 1)]
    assert _own(mate.receive_until("relay_update", _playing)) == (None, False)
    assert load_member(relay_race, mate.participant_id).relay_token is None


def test_validation_draws_a_token_only_its_owner_reads(relay_race, mods):
    holder, mate = mods[_pid(relay_race, 0, 0)], mods[_pid(relay_race, 0, 1)]
    mate.send_status_update(igt_ms=2_000, death_count=0)
    validated = mate.receive_until(
        "relay_update", lambda m: member_view(m, mate.participant_id)["validated"]
    )
    token, bound = _own(validated)
    assert isinstance(token, int) and 1 <= token <= TOKEN_MAX and bound is False
    assert _token(relay_race, mate) == token

    # The teammate's entry carries no token; the holder reads its own.
    seen = holder.receive_until(
        "relay_update", lambda m: member_view(m, mate.participant_id)["validated"]
    )
    assert "token" not in member_view(seen, mate.participant_id)
    assert seen["relay"]["token"] == _token(relay_race, holder)


def test_a_later_report_keeps_the_token(relay_race, mods):
    mate = mods[_pid(relay_race, 0, 1)]
    validate(mate)
    token = _token(relay_race, mate)

    mate.send_status_update(igt_ms=3_000, death_count=0)
    barrier(mate)

    assert _token(relay_race, mate) == token


def test_the_first_holder_gets_its_token_at_its_first_report(integration_client, relay_race):
    mods = _started_before_any_report(integration_client, relay_race)
    try:
        holder = mods[_pid(relay_race, 0, 0)]
        start = holder.receive_until("relay_update", lambda m: m["relay"]["team_status"] == "ready")
        assert _own(start) == (None, False)

        holder.send_status_update(igt_ms=1_000, death_count=0)
        token, bound = _own(holder.receive_until("relay_update", _playing))

        assert isinstance(token, int) and 1 <= token <= TOKEN_MAX and bound is False
        assert _token(relay_race, holder) == token
    finally:
        for mod in mods.values():
            mod.close()


def test_a_receiver_validated_before_the_teams_first_report_keeps_its_token(
    integration_client, relay_race
):
    mods = _started_before_any_report(integration_client, relay_race)
    try:
        holder, target = mods[_pid(relay_race, 0, 0)], mods[_pid(relay_race, 0, 1)]
        make_receiver(target)
        token = _token(relay_race, target)
        # The first runner hands off before its first report: the receiver's
        # first report is the team's, which validates the holder's save.
        take = _hand_off(holder, target)
        _taken(target, take)

        target.send_status_update(igt_ms=2_000, death_count=0)

        assert _own(target.receive_until("relay_update", _playing)) == (token, False)
        assert _token(relay_race, target) == token
    finally:
        for mod in mods.values():
            mod.close()


# --- relay_bound ---


def test_relay_bound_with_the_members_token_binds_and_is_answered(relay_race, mods):
    mate = mods[_pid(relay_race, 0, 1)]
    validate(mate)
    token = _token(relay_race, mate)

    mate.send({"type": "relay_bound", "token": token})

    assert _own(mate.receive_until("relay_update", _bound)) == (token, True)
    assert load_member(relay_race, mate.participant_id).relay_bound is True


def test_relay_bound_with_another_token_or_before_validation_changes_nothing(relay_race, mods):
    mate = mods[_pid(relay_race, 0, 1)]
    mate.receive_until("relay_update", _playing)

    # Not validated yet.
    mate.send({"type": "relay_bound", "token": 1})
    assert _updates_until_barrier(mate) == 0
    assert load_member(relay_race, mate.participant_id).relay_bound is False

    validate(mate)
    token = _token(relay_race, mate)
    mate.send({"type": "relay_bound", "token": token % TOKEN_MAX + 1})

    assert _updates_until_barrier(mate) == 0
    member = load_member(relay_race, mate.participant_id)
    assert (member.relay_token, member.relay_bound) == (token, False)


def test_a_second_relay_bound_is_not_answered(relay_race, mods):
    mate = mods[_pid(relay_race, 0, 1)]
    validate(mate)
    token = _token(relay_race, mate)
    mate.send({"type": "relay_bound", "token": token})
    mate.receive_until("relay_update", _bound)

    mate.send({"type": "relay_bound", "token": token})

    assert _updates_until_barrier(mate) == 0
    assert load_member(relay_race, mate.participant_id).relay_bound is True


# --- Reset ---


def test_a_reset_clears_token_and_binding(integration_client, relay_race, mods):
    # Each holder drew a token at its first report; the teammate binds its own.
    mate = mods[_pid(relay_race, 0, 1)]
    validate(mate)
    mate.send({"type": "relay_bound", "token": _token(relay_race, mate)})
    mate.receive_until("relay_update", _bound)

    response = integration_client.post(
        f"/api/races/{relay_race['race_id']}/reset",
        headers={"Authorization": f"Bearer {relay_race['organizer'].api_token}"},
    )

    assert response.status_code == 200, response.json()
    for team in range(2):
        for member in load_members(relay_race, team):
            assert (member.relay_validated, member.relay_token, member.relay_bound) == (
                False,
                None,
                False,
            )
