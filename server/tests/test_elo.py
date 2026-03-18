"""Tests for ELO algorithm."""

from speedfog_racing.services.stats_service import compute_elo_deltas


class TestComputeEloDeltas:
    """Test the pure ELO delta computation function."""

    def test_two_players_equal_rating_close_finish(self):
        """Close finish between equal players: minimal change."""
        players = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 3_000_000, "finished": True},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 3_005_000, "finished": True},
        ]
        deltas = compute_elo_deltas(players)
        assert deltas["a"] > 0
        assert deltas["b"] < 0
        assert abs(deltas["a"]) < 5.0

    def test_two_players_equal_rating_large_gap(self):
        """Large gap between equal players: significant change."""
        players = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 2_000_000, "finished": True},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 3_500_000, "finished": True},
        ]
        deltas = compute_elo_deltas(players)
        assert deltas["a"] > 10.0
        assert deltas["b"] < -10.0

    def test_higher_rated_player_wins_small_change(self):
        """Favorite winning gives less ELO than an upset."""
        players = [
            {"user_id": "a", "elo": 1800.0, "igt_ms": 2_000_000, "finished": True},
            {"user_id": "b", "elo": 1200.0, "igt_ms": 3_500_000, "finished": True},
        ]
        deltas = compute_elo_deltas(players)
        assert deltas["a"] > 0
        assert deltas["a"] < 10.0

    def test_upset_large_change(self):
        """Lower-rated player winning gives more ELO."""
        players = [
            {"user_id": "a", "elo": 1200.0, "igt_ms": 2_000_000, "finished": True},
            {"user_id": "b", "elo": 1800.0, "igt_ms": 3_500_000, "finished": True},
        ]
        deltas = compute_elo_deltas(players)
        assert deltas["a"] > 20.0

    def test_three_players(self):
        """Three-player race: sum of deltas is zero."""
        players = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 2_000_000, "finished": True},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 2_500_000, "finished": True},
            {"user_id": "c", "elo": 1500.0, "igt_ms": 3_000_000, "finished": True},
        ]
        deltas = compute_elo_deltas(players)
        assert abs(sum(deltas.values())) < 0.01
        assert deltas["a"] > deltas["b"] > deltas["c"]

    def test_abandoned_player_loses_max(self):
        """Abandoned player (igt_ms > 0) loses to all finishers."""
        players = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 2_500_000, "finished": True},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 100_000, "finished": False},
        ]
        deltas = compute_elo_deltas(players)
        assert deltas["a"] > 0
        assert deltas["b"] < 0
        assert deltas["b"] < -10.0

    def test_single_player_no_change(self):
        """Single player: no pairwise comparisons, no change."""
        players = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 2_500_000, "finished": True},
        ]
        deltas = compute_elo_deltas(players)
        assert deltas == {"a": 0.0}

    def test_two_abandoned_players(self):
        """Two abandoned players: both get S=0.5 (draw), equal rating = zero change."""
        players = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 100_000, "finished": False},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 200_000, "finished": False},
        ]
        deltas = compute_elo_deltas(players)
        assert abs(deltas["a"]) < 0.01
        assert abs(deltas["b"]) < 0.01
