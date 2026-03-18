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
        igts = [100, 200, 300]
        deaths = [20, 10, 5]
        score = compute_rusher_score(igts, deaths, player_index=0)
        assert score > 0.8

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
        igts = [300, 200, 100]
        deaths = [2, 10, 15]
        score = compute_cautious_score(igts, deaths, player_index=0)
        assert score > 0.8

    def test_fast_with_many_deaths(self):
        igts = [100, 200, 300]
        deaths = [20, 10, 5]
        score = compute_cautious_score(igts, deaths, player_index=0)
        assert score == 0.0


class TestExplorerScore:
    def test_high_coverage_high_backtrack(self):
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
        assert 0.5 < score < 0.7

    def test_no_backtrack(self):
        visited = {"a", "b"}
        history = [{"node_id": "a"}, {"node_id": "b"}]
        score = compute_explorer_score(visited, 10, history)
        assert 0.1 < score < 0.15


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
        gap_ratios = [0.5, 0.6, 0.4, 0.7, 0.5, 0.3, 0.6, 0.5, 0.4, 0.5]
        score = compute_resilient_score(10, 10, gap_ratios)
        assert score > 60

    def test_leader_always(self):
        score = compute_resilient_score(10, 10, [0.0] * 10)
        assert score < 10

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
