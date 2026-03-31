"""Tests for ELO algorithm."""

import pytest

from speedfog_racing.services.stats_service import (
    DIFFICULTY_INJECTION,
    K_FACTOR,
    K_FACTOR_PROVISIONAL,
    REFERENCE_ELO,
    apply_difficulty_bonus,
    apply_field_strength_weight,
    compute_elo_deltas,
)


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


class TestProvisionalConfidence:
    """Test ELO confidence weighting for provisional players."""

    def test_fully_provisional_opponent_zero_delta(self):
        """Established player vs fully provisional: no delta for established player."""
        players = [
            {"user_id": "a", "elo": 1600.0, "igt_ms": 2_500_000, "finished": True, "elo_races": 10},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 2_600_000, "finished": True, "elo_races": 0},
        ]
        deltas = compute_elo_deltas(players)
        assert deltas["a"] == 0.0
        # Provisional player still gets full delta (opponent is established)
        assert deltas["b"] != 0.0

    def test_both_provisional_still_move(self):
        """Two fully provisional players: both get delta (bootstrapping)."""
        players = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 2_500_000, "finished": True, "elo_races": 0},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 3_000_000, "finished": True, "elo_races": 0},
        ]
        deltas = compute_elo_deltas(players)
        assert deltas["a"] > 0
        assert deltas["b"] < 0

    def test_established_players_full_confidence(self):
        """Both established: confidence = 1.0, behaves like classic ELO."""
        players_with = [
            {"user_id": "a", "elo": 1800.0, "igt_ms": 2_000_000, "finished": True, "elo_races": 10},
            {"user_id": "b", "elo": 1200.0, "igt_ms": 3_500_000, "finished": True, "elo_races": 10},
        ]
        players_without = [
            {"user_id": "a", "elo": 1800.0, "igt_ms": 2_000_000, "finished": True},
            {"user_id": "b", "elo": 1200.0, "igt_ms": 3_500_000, "finished": True},
        ]
        deltas_with = compute_elo_deltas(players_with)
        deltas_without = compute_elo_deltas(players_without)
        assert deltas_with["a"] == pytest.approx(deltas_without["a"])

    def test_partial_confidence_scales_established_delta(self):
        """Partially provisional opponent: established player's delta is reduced."""
        players_half = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 2_000_000, "finished": True, "elo_races": 10},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 3_000_000, "finished": True, "elo_races": 5},
        ]
        players_full = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 2_000_000, "finished": True, "elo_races": 10},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 3_000_000, "finished": True, "elo_races": 10},
        ]
        delta_half = compute_elo_deltas(players_half)
        delta_full = compute_elo_deltas(players_full)
        # Established player gets less delta from partially provisional opponent
        assert 0 < delta_half["a"] < delta_full["a"]
        # Provisional player uses higher K factor, so loses more than established
        assert delta_half["b"] < delta_full["b"]
        k_ratio = K_FACTOR_PROVISIONAL / K_FACTOR
        assert delta_half["b"] == pytest.approx(delta_full["b"] * k_ratio)

    def test_asymmetric_confidence(self):
        """Provisional player gets full delta, established gets reduced delta."""
        players = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 2_000_000, "finished": True, "elo_races": 10},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 3_000_000, "finished": True, "elo_races": 0},
        ]
        deltas = compute_elo_deltas(players)
        # a's delta is 0 (opponent is provisional)
        assert deltas["a"] == 0.0
        # b's delta is full (opponent is established)
        assert deltas["b"] < 0

    def test_mixed_race_no_dilution(self):
        """Established player in mixed race: provisionals don't dilute established matchups."""
        # 4-player race: 1 established opponent + 2 provisionals
        players_mixed = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 2_000_000, "finished": True, "elo_races": 10},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 3_000_000, "finished": True, "elo_races": 10},
            {"user_id": "c", "elo": 1500.0, "igt_ms": 2_500_000, "finished": True, "elo_races": 0},
            {"user_id": "d", "elo": 1500.0, "igt_ms": 3_500_000, "finished": True, "elo_races": 0},
        ]
        # Same matchup as a 1v1 between the two established players
        players_1v1 = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 2_000_000, "finished": True, "elo_races": 10},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 3_000_000, "finished": True, "elo_races": 10},
        ]
        delta_mixed = compute_elo_deltas(players_mixed)
        delta_1v1 = compute_elo_deltas(players_1v1)
        # Established player's delta should be the same regardless of provisionals
        assert delta_mixed["a"] == pytest.approx(delta_1v1["a"])
        assert delta_mixed["b"] == pytest.approx(delta_1v1["b"])
        # Provisionals still get deltas (bootstrapping)
        assert delta_mixed["c"] != 0.0
        assert delta_mixed["d"] != 0.0


class TestAdaptiveK:
    """Test adaptive K factor: provisional players move faster."""

    def test_provisional_uses_higher_k(self):
        """Provisional player (< 10 races) gets K=48 instead of K=32."""
        players_prov = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 2_000_000, "finished": True, "elo_races": 3},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 3_000_000, "finished": True, "elo_races": 3},
        ]
        players_est = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 2_000_000, "finished": True, "elo_races": 10},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 3_000_000, "finished": True, "elo_races": 10},
        ]
        delta_prov = compute_elo_deltas(players_prov)
        delta_est = compute_elo_deltas(players_est)
        # Provisional players move more than established
        assert abs(delta_prov["a"]) > abs(delta_est["a"])
        assert abs(delta_prov["a"]) == pytest.approx(
            abs(delta_est["a"]) * K_FACTOR_PROVISIONAL / K_FACTOR
        )

    def test_established_uses_standard_k(self):
        """Established player (>= 10 races) uses K=32."""
        players = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 2_000_000, "finished": True, "elo_races": 10},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 3_000_000, "finished": True, "elo_races": 10},
        ]
        # Without elo_races, defaults to PROVISIONAL_THRESHOLD (= established)
        players_default = [
            {"user_id": "a", "elo": 1500.0, "igt_ms": 2_000_000, "finished": True},
            {"user_id": "b", "elo": 1500.0, "igt_ms": 3_000_000, "finished": True},
        ]
        deltas = compute_elo_deltas(players)
        deltas_default = compute_elo_deltas(players_default)
        assert deltas["a"] == pytest.approx(deltas_default["a"])

    def test_mixed_k_provisional_vs_established(self):
        """Provisional player uses K=48, established player uses K=32 in same race."""
        players = [
            {
                "user_id": "prov",
                "elo": 1500.0,
                "igt_ms": 2_000_000,
                "finished": True,
                "elo_races": 2,
            },
            {
                "user_id": "est",
                "elo": 1500.0,
                "igt_ms": 3_000_000,
                "finished": True,
                "elo_races": 15,
            },
        ]
        deltas = compute_elo_deltas(players)
        # Both gain/lose, but provisional moves more per unit of actual-expected
        # Note: established player's delta is also affected by confidence weighting
        assert deltas["prov"] > 0
        assert deltas["est"] < 0


class TestDifficultyBonus:
    """Test the difficulty injection that breaks zero-sum."""

    def test_average_difficulty_no_bonus(self):
        """Difficulty factor 1.0 (average) gives zero bonus."""
        deltas = {"a": 10.0, "b": -10.0}
        result = apply_difficulty_bonus(deltas, difficulty_factor=1.0)
        assert result["a"] == pytest.approx(10.0)
        assert result["b"] == pytest.approx(-10.0)

    def test_hard_seed_positive_bonus(self):
        """Difficulty factor > 1.0 adds positive bonus to all players."""
        deltas = {"a": 10.0, "b": -10.0}
        result = apply_difficulty_bonus(deltas, difficulty_factor=1.3)
        bonus = DIFFICULTY_INJECTION * 0.3
        assert result["a"] == pytest.approx(10.0 + bonus)
        assert result["b"] == pytest.approx(-10.0 + bonus)

    def test_easy_seed_negative_bonus(self):
        """Difficulty factor < 1.0 subtracts from all players."""
        deltas = {"a": 10.0, "b": -10.0}
        result = apply_difficulty_bonus(deltas, difficulty_factor=0.7)
        bonus = DIFFICULTY_INJECTION * -0.3
        assert result["a"] == pytest.approx(10.0 + bonus)
        assert result["b"] == pytest.approx(-10.0 + bonus)


class TestFieldStrengthWeight:
    """Test K-factor weighting by field strength."""

    def test_average_field_no_change(self):
        """Field at REFERENCE_ELO gives weight=1.0, no change."""
        deltas = {"a": 10.0, "b": -10.0}
        elos = {"a": 1500.0, "b": 1500.0}
        result = apply_field_strength_weight(deltas, elos)
        assert result["a"] == pytest.approx(10.0)
        assert result["b"] == pytest.approx(-10.0)

    def test_strong_field_amplifies(self):
        """Field above REFERENCE_ELO amplifies deltas."""
        deltas = {"a": 10.0, "b": -10.0}
        elos = {"a": 1700.0, "b": 1700.0}
        result = apply_field_strength_weight(deltas, elos)
        weight = 1700.0 / REFERENCE_ELO
        assert result["a"] == pytest.approx(10.0 * weight)
        assert result["b"] == pytest.approx(-10.0 * weight)

    def test_weak_field_dampens(self):
        """Field below REFERENCE_ELO dampens deltas."""
        deltas = {"a": 10.0, "b": -10.0}
        elos = {"a": 1300.0, "b": 1300.0}
        result = apply_field_strength_weight(deltas, elos)
        weight = 1300.0 / REFERENCE_ELO
        assert result["a"] == pytest.approx(10.0 * weight)
        assert result["b"] == pytest.approx(-10.0 * weight)
