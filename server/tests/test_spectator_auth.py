"""Tests for spectator DAG access logic and auth."""

import uuid
from unittest.mock import MagicMock

from speedfog_racing.models import (
    Caster,
    Participant,
    Race,
    RaceStatus,
    Seed,
    User,
)
from speedfog_racing.websocket.spectator import build_seed_info, compute_dag_access


def _make_user(user_id: uuid.UUID | None = None) -> User:
    u = MagicMock(spec=User)
    u.id = user_id or uuid.uuid4()
    return u


def _make_participant(user_id: uuid.UUID, race_id: uuid.UUID) -> Participant:
    p = MagicMock(spec=Participant)
    p.user_id = user_id
    p.race_id = race_id
    p.id = uuid.uuid4()
    return p


def _make_caster(user_id: uuid.UUID, race_id: uuid.UUID) -> Caster:
    c = MagicMock(spec=Caster)
    c.user_id = user_id
    c.race_id = race_id
    c.id = uuid.uuid4()
    return c


def _make_race(
    status: RaceStatus,
    organizer_id: uuid.UUID,
    participants: list[Participant] | None = None,
    casters: list[Caster] | None = None,
    seed: Seed | None = None,
) -> Race:
    r = MagicMock(spec=Race)
    r.id = uuid.uuid4()
    r.name = "Test Race"
    r.status = status
    r.organizer_id = organizer_id
    r.participants = participants or []
    r.casters = casters or []
    r.seed = seed
    return r


def _make_seed(graph_json: dict, total_layers: int) -> Seed:
    s = MagicMock(spec=Seed)
    s.total_layers = total_layers
    s.graph_json = graph_json
    return s


# =============================================================================
# compute_dag_access Tests
# =============================================================================


class TestComputeDagAccess:
    """Test DAG access rules."""

    def test_finished_always_true(self):
        """FINISHED race: everyone sees the DAG."""
        org_id = uuid.uuid4()
        race = _make_race(RaceStatus.FINISHED, org_id)
        assert compute_dag_access(None, race) is True
        assert compute_dag_access(uuid.uuid4(), race) is True

    def test_running_anonymous_sees_dag(self):
        """RUNNING race: anonymous spectator sees the DAG."""
        org_id = uuid.uuid4()
        race = _make_race(RaceStatus.RUNNING, org_id)
        assert compute_dag_access(None, race) is True

    def test_running_non_participant_sees_dag(self):
        """RUNNING race: non-participant user sees the DAG."""
        org_id = uuid.uuid4()
        race = _make_race(RaceStatus.RUNNING, org_id)
        assert compute_dag_access(uuid.uuid4(), race) is True

    def test_running_participant_no_dag(self):
        """RUNNING race: participant does NOT see the DAG."""
        org_id = uuid.uuid4()
        player_id = uuid.uuid4()
        race_id = uuid.uuid4()
        race = _make_race(
            RaceStatus.RUNNING,
            org_id,
            participants=[_make_participant(player_id, race_id)],
        )
        assert compute_dag_access(player_id, race) is False

    def test_draft_anonymous_no_dag(self):
        """DRAFT race: anonymous spectator does NOT see the DAG."""
        race = _make_race(RaceStatus.DRAFT, uuid.uuid4())
        assert compute_dag_access(None, race) is False

    def test_draft_random_user_no_dag(self):
        """DRAFT race: random user does NOT see the DAG."""
        race = _make_race(RaceStatus.DRAFT, uuid.uuid4())
        assert compute_dag_access(uuid.uuid4(), race) is False

    def test_draft_non_participating_organizer_sees_dag(self):
        """DRAFT race: organizer who is NOT a participant sees the DAG."""
        org_id = uuid.uuid4()
        race = _make_race(RaceStatus.DRAFT, org_id)
        assert compute_dag_access(org_id, race) is True

    def test_draft_participating_organizer_no_dag(self):
        """DRAFT race: organizer who IS a participant does NOT see the DAG."""
        org_id = uuid.uuid4()
        race_id = uuid.uuid4()
        race = _make_race(
            RaceStatus.DRAFT,
            org_id,
            participants=[_make_participant(org_id, race_id)],
        )
        assert compute_dag_access(org_id, race) is False

    def test_draft_caster_sees_dag(self):
        """DRAFT race: caster sees the DAG."""
        org_id = uuid.uuid4()
        caster_id = uuid.uuid4()
        race_id = uuid.uuid4()
        race = _make_race(
            RaceStatus.DRAFT,
            org_id,
            casters=[_make_caster(caster_id, race_id)],
        )
        assert compute_dag_access(caster_id, race) is True

    def test_open_same_rules_as_draft(self):
        """OPEN race follows same rules as DRAFT."""
        org_id = uuid.uuid4()
        race = _make_race(RaceStatus.OPEN, org_id)
        # Non-participating organizer sees DAG
        assert compute_dag_access(org_id, race) is True
        # Anonymous does not
        assert compute_dag_access(None, race) is False


# =============================================================================
# build_seed_info Tests
# =============================================================================


class TestBuildSeedInfo:
    """Test SeedInfo construction with DAG access using real v3 graph.json."""

    def test_no_seed(self):
        """No seed returns minimal SeedInfo."""
        race = _make_race(RaceStatus.DRAFT, uuid.uuid4())
        race.seed = None
        info = build_seed_info(race, dag_access=True)
        assert info.total_layers == 0
        assert info.graph_json is None

    def test_with_access_includes_graph(self, sample_graph_json: dict):
        """With DAG access, graph_json is included with correct v3 stats."""
        graph = sample_graph_json
        seed = _make_seed(graph, total_layers=graph["total_layers"])
        race = _make_race(RaceStatus.RUNNING, uuid.uuid4(), seed=seed)
        info = build_seed_info(race, dag_access=True)
        assert info.graph_json is not None
        assert info.total_layers == graph["total_layers"]
        assert info.total_nodes == graph["total_nodes"]
        assert info.total_paths == graph["total_paths"]

    def test_without_access_no_graph(self, sample_graph_json: dict):
        """Without DAG access, graph_json is None but meta-stats present."""
        graph = sample_graph_json
        seed = _make_seed(graph, total_layers=graph["total_layers"])
        race = _make_race(RaceStatus.RUNNING, uuid.uuid4(), seed=seed)
        info = build_seed_info(race, dag_access=False)
        assert info.graph_json is None
        assert info.total_layers == graph["total_layers"]
        assert info.total_nodes == graph["total_nodes"]
        assert info.total_paths == graph["total_paths"]
