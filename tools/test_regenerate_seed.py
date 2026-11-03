"""Tests for regenerate_seed.py: the graph comparison and what main() writes."""

from __future__ import annotations

import json
import sys
import zipfile

import pytest
import regenerate_seed
from regenerate_seed import (
    SeedNotFoundError,
    StoredSeed,
    compare_graphs,
    json_differences,
)


def _graph(**overrides):
    graph = {
        "version": "4.10",
        "seed": 860847648,
        "total_layers": 3,
        "nodes": {"start": {"layer": 0, "zones": ["chapel"]}, "end": {"layer": 2}},
        "edges": [{"from": "start", "to": "end"}],
        "plugins": {},
    }
    graph.update(overrides)
    return graph


class TestJsonDifferences:
    def test_equal_values_have_no_difference(self):
        assert json_differences(_graph(), _graph()) == []

    def test_nested_value_names_its_path(self):
        regenerated = _graph()
        regenerated["nodes"]["start"]["zones"] = ["stormveil"]
        assert json_differences(_graph(), regenerated) == [
            "nodes.start.zones[0]: 'chapel' in the database, 'stormveil' regenerated"
        ]

    def test_key_on_one_side_only(self):
        regenerated = _graph()
        del regenerated["nodes"]["end"]
        regenerated["nodes"]["extra"] = {}
        assert json_differences(_graph(), regenerated) == [
            "nodes.end: missing from the regenerated graph",
            "nodes.extra: missing from the database graph",
        ]

    def test_list_length_mismatch_is_one_difference(self):
        regenerated = _graph(edges=[])
        assert json_differences(_graph(), regenerated) == [
            "edges: 1 items in the database, 0 regenerated"
        ]

    def test_type_change_is_a_difference(self):
        assert json_differences({"a": {"b": 1}}, {"a": [1]}) == [
            "a: {'b': 1} in the database, [1] regenerated"
        ]

    def test_long_values_are_shortened(self):
        (line,) = json_differences({"a": "x" * 200}, {"a": "y"})
        assert len(line) < 150
        assert line.endswith("'y' regenerated")


class TestCompareGraphs:
    def test_identical_graphs(self):
        assert compare_graphs(_graph(), _graph()) == ([], [])

    def test_plugin_change_is_only_a_warning(self):
        halloween = {"halloween": {"enabled": True, "jumpscares": 0}}
        errors, warnings = compare_graphs(_graph(plugins=halloween), _graph())
        assert errors == []
        assert warnings == ["plugins.halloween: missing from the regenerated graph"]

    def test_route_change_is_an_error_even_with_plugin_warnings(self):
        regenerated = _graph(plugins={"x": 1}, total_layers=4)
        errors, warnings = compare_graphs(_graph(), regenerated)
        assert errors == ["total_layers: 3 in the database, 4 regenerated"]
        assert warnings == ["plugins.x: missing from the database graph"]

    def test_plugins_block_missing_on_one_side(self):
        db_graph = _graph()
        del db_graph["plugins"]
        errors, warnings = compare_graphs(db_graph, _graph())
        assert errors == []
        assert warnings == ["plugins: missing from the database graph"]


@pytest.fixture
def restore(tmp_path, monkeypatch):
    """Runs main() on a stored standard seed (Halloween plugin on) whose
    regeneration writes the given graph, or fails with the given log when the
    graph is None, without database or speedfog."""
    stored = StoredSeed(
        "abc123def456",
        "standard",
        _graph(plugins={"halloween": {"enabled": True}}),
        "/srv/seeds/standard/seed_abc123def456.zip",
    )

    async def fake_load_seed(seed_number):
        assert seed_number == "abc123"
        return stored

    monkeypatch.setattr(regenerate_seed, "load_seed", fake_load_seed)

    def run(regenerated_graph, log=""):
        def fake_run_speedfog(
            speedfog_path, config_path, output_dir, game_dir, *, verbose, seed
        ):
            assert seed == stored.graph_json["seed"]
            (output_dir / "generation.log").write_text(log, encoding="utf-8")
            if regenerated_graph is None:
                return None
            seed_dir = output_dir / str(seed)
            (seed_dir / "modengine2").mkdir(parents=True)
            (seed_dir / "modengine2" / "config_speedfog.toml").write_text(
                "[modengine]\nexternal_dlls = []\n", encoding="utf-8"
            )
            (seed_dir / "graph.json").write_text(
                json.dumps(regenerated_graph), encoding="utf-8"
            )
            return seed_dir

        monkeypatch.setattr(regenerate_seed, "run_speedfog", fake_run_speedfog)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "regenerate_seed.py",
                "abc123",
                "--game-dir",
                str(tmp_path),
                "--speedfog-path",
                str(tmp_path),
                "--output",
                str(tmp_path / "out"),
            ],
        )
        return regenerate_seed.main()

    return run


class TestMain:
    def test_plugin_only_difference_writes_the_zip(self, restore, tmp_path):
        assert restore(_graph()) == 0
        zip_path = tmp_path / "out" / "standard" / "seed_abc123def456.zip"
        with zipfile.ZipFile(zip_path) as zf:
            assert "speedfog_abc123def456/graph.json" in zf.namelist()
        assert not (tmp_path / "out" / "standard_failed").exists()

    def test_graph_difference_writes_no_zip_and_keeps_the_run(self, restore, tmp_path):
        assert restore(_graph(total_layers=4)) == 1
        assert not (tmp_path / "out" / "standard" / "seed_abc123def456.zip").exists()
        kept = tmp_path / "out" / "standard_failed" / "seed_abc123def456"
        assert (kept / "860847648" / "graph.json").is_file()

    def test_unknown_seed_number_stops_before_generating(
        self, restore, monkeypatch, tmp_path
    ):
        async def no_seed(seed_number):
            raise SeedNotFoundError("no played seed 'abc123'")

        monkeypatch.setattr(regenerate_seed, "load_seed", no_seed)
        assert restore(_graph()) == 1
        assert not (tmp_path / "out").exists()

    def test_seed_that_no_longer_generates_explains_why(
        self, restore, tmp_path, capsys
    ):
        log = (
            "warning: `VIRTUAL_ENV=...` does not match the project environment\n"
            "Error: Generation failed: Validation failed: Layer 26: mixed types\n"
        )
        assert restore(None, log) == 1
        out = capsys.readouterr().out
        assert "speedfog: Error: Generation failed: Validation failed" in out
        assert "VIRTUAL_ENV" not in out
        assert "changed since the seed was generated" in out
        kept = tmp_path / "out" / "standard_failed" / "seed_abc123def456"
        assert (kept / "generation.log").read_text(encoding="utf-8") == log

    def test_other_speedfog_failures_are_not_blamed_on_the_generator(
        self, restore, capsys
    ):
        assert restore(None, "Error: Item Randomizer failed\n") == 1
        out = capsys.readouterr().out
        assert "speedfog: Error: Item Randomizer failed" in out
        assert "changed since the seed was generated" not in out

    def test_invalid_config_is_not_blamed_on_the_seed(self, restore, capsys):
        log = "Error: Generation failed: Invalid configuration: unknown zone\n"
        assert restore(None, log) == 1
        out = capsys.readouterr().out
        assert "no seed of this pool would generate" in out
        assert "changed since the seed was generated" not in out

    def test_log_without_error_lines_points_to_the_log(self, restore, capsys):
        assert restore(None, "Traceback (most recent call last):\nKeyError: 'x'\n") == 1
        assert "See generation.log" in capsys.readouterr().out
