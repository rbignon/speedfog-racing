"""Tests for spectator seed info construction."""

import uuid
from unittest.mock import MagicMock

from speedfog_racing.models import (
    Race,
    RaceStatus,
    Seed,
)
from speedfog_racing.websocket.spectator import build_seed_info


def _make_race(
    status: RaceStatus,
    organizer_id: uuid.UUID,
    seed: Seed | None = None,
) -> Race:
    r = MagicMock(spec=Race)
    r.id = uuid.uuid4()
    r.name = "Test Race"
    r.status = status
    r.organizer_id = organizer_id
    r.participants = []
    r.casters = []
    r.seed = seed
    return r


def _make_seed(graph_json: dict, total_layers: int) -> Seed:
    s = MagicMock(spec=Seed)
    s.total_layers = total_layers
    s.graph_json = graph_json
    return s


# =============================================================================
# build_seed_info Tests
# =============================================================================


class TestBuildSeedInfo:
    """Test SeedInfo construction with role-based graph visibility."""

    def test_no_seed(self):
        """No seed returns minimal SeedInfo."""
        race = _make_race(RaceStatus.DRAFT, uuid.uuid4())
        race.seed = None
        info = build_seed_info(race)
        assert info.total_layers == 0
        assert info.graph_json is None

    def test_running_includes_graph(self, sample_graph_json: dict):
        """RUNNING race always includes graph_json."""
        graph = sample_graph_json
        seed = _make_seed(graph, total_layers=graph["total_layers"])
        race = _make_race(RaceStatus.RUNNING, uuid.uuid4(), seed=seed)
        info = build_seed_info(race)
        assert info.graph_json is not None
        assert info.total_layers == graph["total_layers"]
        assert info.total_nodes == graph["total_nodes"]
        assert info.total_paths == graph["total_paths"]

    def test_finished_includes_graph(self, sample_graph_json: dict):
        """FINISHED race always includes graph_json."""
        seed = _make_seed(sample_graph_json, total_layers=3)
        race = _make_race(RaceStatus.FINISHED, uuid.uuid4(), seed=seed)
        info = build_seed_info(race)
        assert info.graph_json is not None

    def test_draft_hides_graph_for_anonymous(self, sample_graph_json: dict):
        """DRAFT race hides graph_json from anonymous spectators."""
        seed = _make_seed(sample_graph_json, total_layers=3)
        race = _make_race(RaceStatus.DRAFT, uuid.uuid4(), seed=seed)
        info = build_seed_info(race)
        assert info.graph_json is None
        # Stats are still visible (needed for MetroDagBlurred fallback)
        assert info.total_nodes is not None
        assert info.total_paths is not None

    def test_draft_hides_graph_for_random_user(self, sample_graph_json: dict):
        """DRAFT race hides graph_json from non-organizer users."""
        seed = _make_seed(sample_graph_json, total_layers=3)
        race = _make_race(RaceStatus.DRAFT, uuid.uuid4(), seed=seed)
        random_user = uuid.uuid4()
        info = build_seed_info(race, user_id=random_user)
        assert info.graph_json is None

    def test_draft_shows_graph_for_non_participating_organizer(self, sample_graph_json: dict):
        """DRAFT race shows graph_json to non-participating organizer."""
        seed = _make_seed(sample_graph_json, total_layers=3)
        organizer_id = uuid.uuid4()
        race = _make_race(RaceStatus.DRAFT, organizer_id, seed=seed)
        info = build_seed_info(race, user_id=organizer_id)
        assert info.graph_json is not None

    def test_draft_shows_graph_for_participating_organizer(self, sample_graph_json: dict):
        """DRAFT race shows graph_json to organizer who is also a participant."""
        seed = _make_seed(sample_graph_json, total_layers=3)
        organizer_id = uuid.uuid4()
        race = _make_race(RaceStatus.DRAFT, organizer_id, seed=seed)
        # Add organizer as participant
        participant = MagicMock()
        participant.user_id = organizer_id
        race.participants = [participant]
        info = build_seed_info(race, user_id=organizer_id)
        assert info.graph_json is not None

    def test_draft_shows_graph_for_participant(self, sample_graph_json: dict):
        """DRAFT race shows graph_json to a non-organizer participant."""
        seed = _make_seed(sample_graph_json, total_layers=3)
        organizer_id = uuid.uuid4()
        participant_id = uuid.uuid4()
        race = _make_race(RaceStatus.DRAFT, organizer_id, seed=seed)
        participant = MagicMock()
        participant.user_id = participant_id
        race.participants = [participant]
        info = build_seed_info(race, user_id=participant_id)
        assert info.graph_json is not None

    def test_draft_hides_graph_for_non_participant_non_organizer(self, sample_graph_json: dict):
        """DRAFT race hides graph_json from a user who is neither organizer nor participant."""
        seed = _make_seed(sample_graph_json, total_layers=3)
        organizer_id = uuid.uuid4()
        participant_id = uuid.uuid4()
        random_user = uuid.uuid4()
        race = _make_race(RaceStatus.DRAFT, organizer_id, seed=seed)
        participant = MagicMock()
        participant.user_id = participant_id
        race.participants = [participant]
        info = build_seed_info(race, user_id=random_user)
        assert info.graph_json is None

    def test_open_same_rules_as_draft(self, sample_graph_json: dict):
        """OPEN race follows same graph visibility rules as DRAFT."""
        seed = _make_seed(sample_graph_json, total_layers=3)
        organizer_id = uuid.uuid4()
        participant_id = uuid.uuid4()
        random_user = uuid.uuid4()
        race = _make_race(RaceStatus.OPEN, organizer_id, seed=seed)
        participant = MagicMock()
        participant.user_id = participant_id
        race.participants = [participant]
        # Anonymous: hidden
        assert build_seed_info(race).graph_json is None
        # Non-participating organizer: visible
        assert build_seed_info(race, user_id=organizer_id).graph_json is not None
        # Participant: visible
        assert build_seed_info(race, user_id=participant_id).graph_json is not None
        # Random user: hidden
        assert build_seed_info(race, user_id=random_user).graph_json is None

    def test_draft_hides_graph_for_caster(self, sample_graph_json: dict):
        """DRAFT race hides graph_json from a caster who is not a participant."""
        seed = _make_seed(sample_graph_json, total_layers=3)
        organizer_id = uuid.uuid4()
        caster_user_id = uuid.uuid4()
        race = _make_race(RaceStatus.DRAFT, organizer_id, seed=seed)
        caster = MagicMock()
        caster.user_id = caster_user_id
        race.casters = [caster]
        info = build_seed_info(race, user_id=caster_user_id)
        assert info.graph_json is None
