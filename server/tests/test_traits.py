"""Tests for behavioral trait scoring."""

import pytest

from speedfog_racing.services.stats_service import (
    compute_boss_slayer_score,
    compute_cautious_score,
    compute_explorer_score,
    compute_pathfinder_score,
    compute_rage_quitter_score,
    compute_resilient_score,
    compute_rusher_score,
)


class TestRusherScore:
    def test_fastest_with_most_deaths(self):
        """Rank 1 IGT, rank 3 deaths in 3-player race: raw=1.0, adjusted=1.0."""
        igts = [100, 200, 300]
        deaths = [20, 10, 5]
        score = compute_rusher_score(igts, deaths, player_index=0)
        assert score == pytest.approx(1.0)

    def test_moderate_rush(self):
        """Rank 1 IGT, rank 2 deaths in 3-player race: raw=0.5, adjusted=0.5^0.6=0.66."""
        igts = [100, 200, 300]
        deaths = [10, 20, 5]
        score = compute_rusher_score(igts, deaths, player_index=0)
        assert 0.6 < score < 0.7

    def test_slowest_with_fewest_deaths(self):
        igts = [300, 200, 100]
        deaths = [5, 10, 20]
        score = compute_rusher_score(igts, deaths, player_index=0)
        assert score == 0.0

    def test_single_player(self):
        score = compute_rusher_score([100], [5], player_index=0)
        assert score == 0.0


class TestCautiousScore:
    def test_few_deaths_but_slow(self):
        """Rank 3 IGT, rank 1 deaths in 3-player race: raw=1.0, adjusted=1.0."""
        igts = [300, 200, 100]
        deaths = [2, 10, 15]
        score = compute_cautious_score(igts, deaths, player_index=0)
        assert score == pytest.approx(1.0)

    def test_moderate_caution(self):
        """Rank 2 IGT, rank 1 deaths in 3-player race: raw=0.5, adjusted=0.5^0.6=0.66."""
        igts = [200, 100, 300]
        deaths = [2, 10, 15]
        score = compute_cautious_score(igts, deaths, player_index=0)
        assert 0.6 < score < 0.7

    def test_fast_with_many_deaths(self):
        igts = [100, 200, 300]
        deaths = [20, 10, 5]
        score = compute_cautious_score(igts, deaths, player_index=0)
        assert score == 0.0


class TestExplorerScore:
    def test_high_coverage_high_backtrack(self):
        """5/6 coverage (83%), sqrt(0.83)=0.91. 1/6 backtrack rate. 0.6*0.91 + 0.4*0.17 = 0.61."""
        visited = {"a", "b", "c", "d", "e"}
        total_nodes = 6
        history = [
            {"node_id": "a"},
            {"node_id": "b"},
            {"node_id": "c"},
            {"node_id": "b"},  # backtrack
            {"node_id": "d"},
            {"node_id": "e"},
        ]
        score = compute_explorer_score(visited, total_nodes, history)
        assert 0.55 < score < 0.70

    def test_low_coverage_no_backtrack(self):
        """2/10 coverage (20%), sqrt(0.2)=0.45. No backtrack. 0.6*0.45 = 0.27."""
        visited = {"a", "b"}
        history = [{"node_id": "a"}, {"node_id": "b"}]
        score = compute_explorer_score(visited, 10, history)
        assert 0.25 < score < 0.30

    def test_empty_history(self):
        score = compute_explorer_score(set(), 10, [])
        assert score == 0.0

    def test_zero_total_nodes(self):
        score = compute_explorer_score({"a"}, 0, [{"node_id": "a"}])
        assert score == 0.0


class TestPathfinderScore:
    def test_unique_path(self):
        player_nodes = {"a", "b", "c", "d"}
        others_nodes = {"a", "b"}
        score = compute_pathfinder_score(player_nodes, others_nodes)
        assert score == pytest.approx(0.5)

    def test_identical_paths(self):
        player_nodes = {"a", "b", "c"}
        others_nodes = {"a", "b", "c", "d"}
        score = compute_pathfinder_score(player_nodes, others_nodes)
        assert score == 0.0

    def test_empty_others(self):
        score = compute_pathfinder_score({"a", "b"}, set())
        assert score == 0.0


class TestBossSlayerScore:
    def test_zero_deaths_on_hard_boss(self):
        score = compute_boss_slayer_score({"boss_a": 0}, {"boss_a": 10.0}, {"boss_a": 1.0})
        assert score == pytest.approx(1.0)

    def test_average_deaths(self):
        score = compute_boss_slayer_score({"boss_a": 10}, {"boss_a": 10.0}, {"boss_a": 1.0})
        assert score == pytest.approx(0.0)

    def test_no_bosses(self):
        score = compute_boss_slayer_score({}, {}, {})
        assert score == 0.0


class TestResilientScore:
    def test_always_finishes_far_behind(self):
        """Player finishes all races but is always 30%+ behind: high score."""
        gap_ratios = [0.5, 0.6, 0.4, 0.7, 0.5, 0.35, 0.6, 0.5, 0.4, 0.5]
        score = compute_resilient_score(10, 10, gap_ratios)
        assert score == 100.0  # All 10 races are far-behind, frequency = 100%

    def test_leader_always(self):
        """Player always wins (gap=0): score 0 (never far behind)."""
        score = compute_resilient_score(10, 10, [0.0] * 10)
        assert score == 0.0

    def test_slightly_behind_not_resilient(self):
        """Player is only 10-15% behind: not counted as far behind."""
        gap_ratios = [0.1, 0.15, 0.12, 0.08, 0.1]
        score = compute_resilient_score(5, 5, gap_ratios)
        assert score == 0.0

    def test_mix_of_close_and_far(self):
        """Some races close, some far behind: partial score."""
        # 3 out of 6 races are >= 30% behind
        gap_ratios = [0.05, 0.5, 0.1, 0.4, 0.02, 0.35]
        score = compute_resilient_score(6, 6, gap_ratios)
        assert score == pytest.approx(50.0)  # 3/6 = 50%

    def test_never_finishes(self):
        score = compute_resilient_score(0, 10, [])
        assert score == 0


class TestRageQuitterScore:
    def test_half_abandoned(self):
        score = compute_rage_quitter_score(abandoned=5, total=10)
        assert score == pytest.approx(50.0)

    def test_no_abandons(self):
        score = compute_rage_quitter_score(abandoned=0, total=10)
        assert score == 0.0

    def test_no_races(self):
        score = compute_rage_quitter_score(abandoned=0, total=0)
        assert score == 0.0
