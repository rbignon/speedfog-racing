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
        """Rank 1 IGT, rank 2 deaths in 3-player race: raw=0.5, adjusted=0.5^0.4=0.76."""
        igts = [100, 200, 300]
        deaths = [10, 20, 5]
        score = compute_rusher_score(igts, deaths, player_index=0)
        assert 0.7 < score < 0.8

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
        """Rank 2 IGT, rank 1 deaths in 3-player race: raw=0.5, adjusted=0.5^0.4=0.76."""
        igts = [200, 100, 300]
        deaths = [2, 10, 15]
        score = compute_cautious_score(igts, deaths, player_index=0)
        assert 0.7 < score < 0.8

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
    def test_completely_different_order(self):
        """Reversed path vs others: high divergence. raw~0.75, 0.75^0.6=0.83."""
        player = ["a", "b", "c", "d"]
        others = [["d", "c", "b", "a"]]
        score = compute_pathfinder_score(player, others)
        assert score > 0.6

    def test_identical_paths(self):
        player = ["a", "b", "c"]
        others = [["a", "b", "c"], ["a", "b", "c"]]
        score = compute_pathfinder_score(player, others)
        assert score == 0.0

    def test_partially_different(self):
        """Same nodes, some reordering. raw~0.2, 0.2^0.6=0.38."""
        player = ["a", "b", "c", "d", "e"]
        others = [["a", "c", "b", "d", "e"]]
        score = compute_pathfinder_score(player, others)
        assert 0.2 < score < 0.5

    def test_unique_nodes_in_path(self):
        """Player visits extra nodes others didn't. raw~0.25, 0.25^0.6=0.43."""
        player = ["a", "x", "y", "b", "c"]
        others = [["a", "b", "c"]]
        score = compute_pathfinder_score(player, others)
        assert score > 0.3

    def test_empty_others(self):
        score = compute_pathfinder_score(["a", "b"], [])
        assert score == 0.0

    def test_empty_player(self):
        score = compute_pathfinder_score([], [["a", "b"]])
        assert score == 0.0


class TestBossSlayerScore:
    def test_best_on_all_bosses(self):
        """Rank 1 deaths on every boss among 3 players: raw=1.0, 1.0^1.4=1.0."""
        player = {"boss_a": 0, "boss_b": 1}
        all_deaths = {"boss_a": [0, 5, 10], "boss_b": [1, 3, 8]}
        score = compute_boss_slayer_score(player, all_deaths)
        assert score == pytest.approx(1.0)

    def test_worst_on_all_bosses(self):
        """Rank last on every boss: raw=0.0, 0.0^1.4=0.0."""
        player = {"boss_a": 10, "boss_b": 8}
        all_deaths = {"boss_a": [0, 5, 10], "boss_b": [1, 3, 8]}
        score = compute_boss_slayer_score(player, all_deaths)
        assert score == pytest.approx(0.0)

    def test_average_player(self):
        """Rank 2/3 on every boss: raw=0.5, 0.5^1.4=0.38."""
        player = {"boss_a": 5, "boss_b": 3}
        all_deaths = {"boss_a": [0, 5, 10], "boss_b": [1, 3, 8]}
        score = compute_boss_slayer_score(player, all_deaths)
        assert 0.3 < score < 0.45

    def test_weighted_by_difficulty(self):
        """Hard boss (avg 10 deaths) weighted more than easy boss (avg 1 death)."""
        player = {"easy": 0, "hard": 0}
        all_deaths = {"easy": [0, 1, 2], "hard": [0, 5, 15]}
        score = compute_boss_slayer_score(player, all_deaths)
        assert score == pytest.approx(1.0)  # Best on both, raw=1.0

    def test_no_bosses(self):
        score = compute_boss_slayer_score({}, {})
        assert score == 0.0

    def test_single_player_on_boss(self):
        """Only 1 player fought the boss: N<2, skip that boss."""
        player = {"boss_a": 3}
        all_deaths = {"boss_a": [3]}
        score = compute_boss_slayer_score(player, all_deaths)
        assert score == 0.0


class TestResilientScore:
    def test_always_most_deaths_and_finishes(self):
        """Always has most deaths (percentile=1.0), finishes 100%: score = 100."""
        death_pcts = [1.0, 1.0, 1.0, 1.0, 1.0]
        score = compute_resilient_score(death_pcts, finished_races=5, total_races=5)
        assert score == pytest.approx(100.0)

    def test_fewest_deaths_always(self):
        """Always has fewest deaths (percentile=0.0): score = 0 (no adversity)."""
        death_pcts = [0.0, 0.0, 0.0, 0.0, 0.0]
        score = compute_resilient_score(death_pcts, finished_races=5, total_races=5)
        assert score == pytest.approx(0.0)

    def test_high_deaths_but_abandons_half(self):
        """High deaths when playing, but abandons half: score = ~50."""
        death_pcts = [1.0, 1.0, 1.0]  # Only 3 finished races
        score = compute_resilient_score(death_pcts, finished_races=3, total_races=6)
        assert 45 < score < 55

    def test_moderate_deaths(self):
        """Middle-of-the-pack deaths, 100% completion: moderate score."""
        death_pcts = [0.5, 0.5, 0.5]
        score = compute_resilient_score(death_pcts, finished_races=3, total_races=3)
        assert 45 < score < 55

    def test_never_finishes(self):
        score = compute_resilient_score([], finished_races=0, total_races=10)
        assert score == 0.0

    def test_no_races(self):
        score = compute_resilient_score([], finished_races=0, total_races=0)
        assert score == 0.0


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

    def test_below_minimum_races(self):
        """Only 2 races played: too few for a trait, returns 0."""
        score = compute_rage_quitter_score(abandoned=2, total=2)
        assert score == 0.0

    def test_at_minimum_races(self):
        """Exactly 3 races: threshold met."""
        score = compute_rage_quitter_score(abandoned=2, total=3)
        assert score == pytest.approx(200 / 3)
