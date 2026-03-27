"""Tests for seed difficulty computation."""

import pytest

from speedfog_racing.services.seed_difficulty import compute_seed_difficulty


class TestComputeSeedDifficulty:
    def test_empty_graph(self):
        """Empty nodes dict returns 0."""
        assert compute_seed_difficulty({"nodes": {}}) == 0.0

    def test_start_node_excluded(self):
        """Start nodes do not contribute to difficulty."""
        graph = {
            "nodes": {
                "chapel_start": {"type": "start", "tier": 3},
            }
        }
        assert compute_seed_difficulty(graph) == 0.0

    def test_single_legacy_dungeon(self):
        """Single legacy dungeon: weight 1.0 * tier^1.3."""
        graph = {
            "nodes": {
                "start": {"type": "start", "tier": 3},
                "stormveil": {"type": "legacy_dungeon", "tier": 5},
            }
        }
        expected = 1.0 * (5**1.3)
        assert compute_seed_difficulty(graph) == pytest.approx(expected, rel=1e-6)

    def test_boss_types_weighted_higher(self):
        """Boss nodes have higher weight than dungeons at the same tier."""
        graph_dungeon = {
            "nodes": {
                "s": {"type": "start", "tier": 1},
                "a": {"type": "legacy_dungeon", "tier": 10},
            }
        }
        graph_boss = {
            "nodes": {
                "s": {"type": "start", "tier": 1},
                "a": {"type": "major_boss", "tier": 10},
            }
        }
        assert compute_seed_difficulty(graph_boss) > compute_seed_difficulty(graph_dungeon)

    def test_higher_tier_increases_difficulty(self):
        """Higher tier nodes produce higher difficulty score."""
        graph_low = {
            "nodes": {
                "s": {"type": "start", "tier": 1},
                "a": {"type": "legacy_dungeon", "tier": 3},
            }
        }
        graph_high = {
            "nodes": {
                "s": {"type": "start", "tier": 1},
                "a": {"type": "legacy_dungeon", "tier": 15},
            }
        }
        assert compute_seed_difficulty(graph_high) > compute_seed_difficulty(graph_low)

    def test_more_nodes_increases_difficulty(self):
        """More non-start nodes produce higher total difficulty."""
        graph_small = {
            "nodes": {
                "s": {"type": "start", "tier": 1},
                "a": {"type": "mini_dungeon", "tier": 5},
            }
        }
        graph_large = {
            "nodes": {
                "s": {"type": "start", "tier": 1},
                "a": {"type": "mini_dungeon", "tier": 5},
                "b": {"type": "mini_dungeon", "tier": 5},
                "c": {"type": "mini_dungeon", "tier": 5},
            }
        }
        assert compute_seed_difficulty(graph_large) > compute_seed_difficulty(graph_small)

    def test_final_boss_highest_weight(self):
        """Final boss has the highest type weight."""
        graph = {
            "nodes": {
                "s": {"type": "start", "tier": 1},
                "a": {"type": "final_boss", "tier": 10},
            }
        }
        graph_major = {
            "nodes": {
                "s": {"type": "start", "tier": 1},
                "a": {"type": "major_boss", "tier": 10},
            }
        }
        assert compute_seed_difficulty(graph) > compute_seed_difficulty(graph_major)

    def test_realistic_seed(self):
        """Realistic seed with mixed types produces a positive score."""
        graph = {
            "nodes": {
                "start": {"type": "start", "tier": 3},
                "ld1": {"type": "legacy_dungeon", "tier": 5},
                "md1": {"type": "mini_dungeon", "tier": 4},
                "md2": {"type": "mini_dungeon", "tier": 7},
                "ba1": {"type": "boss_arena", "tier": 6},
                "mb1": {"type": "major_boss", "tier": 10},
                "mb2": {"type": "major_boss", "tier": 14},
                "fb": {"type": "final_boss", "tier": 18},
            }
        }
        score = compute_seed_difficulty(graph)
        assert score > 0
        # Sanity: a realistic seed should produce a score in the hundreds
        assert score > 50
