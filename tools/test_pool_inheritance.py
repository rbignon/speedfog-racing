"""Tests for pool TOML inheritance (deep_merge + resolve_pool_config)."""

from __future__ import annotations

import pytest
from generate_pool import (
    POOLS_DIR,
    add_dll_to_config,
    deep_merge,
    resolve_pool_config,
    validate_pool_config,
)


class TestDeepMerge:
    def test_scalar_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3}
        assert deep_merge(base, override) == {"a": 1, "b": 3}

    def test_nested_table_merge(self):
        base = {"t": {"a": 1, "b": 2}}
        override = {"t": {"b": 3, "c": 4}}
        assert deep_merge(base, override) == {"t": {"a": 1, "b": 3, "c": 4}}

    def test_array_replacement(self):
        base = {"arr": [1, 2, 3]}
        override = {"arr": [4, 5]}
        assert deep_merge(base, override) == {"arr": [4, 5]}

    def test_new_key_in_override(self):
        base = {"a": 1}
        override = {"b": 2}
        assert deep_merge(base, override) == {"a": 1, "b": 2}

    def test_new_table_in_override(self):
        base = {"a": 1}
        override = {"t": {"x": 1}}
        assert deep_merge(base, override) == {"a": 1, "t": {"x": 1}}

    def test_override_table_with_scalar(self):
        base = {"t": {"a": 1}}
        override = {"t": "replaced"}
        assert deep_merge(base, override) == {"t": "replaced"}

    def test_override_scalar_with_table(self):
        base = {"t": "scalar"}
        override = {"t": {"a": 1}}
        assert deep_merge(base, override) == {"t": {"a": 1}}

    def test_does_not_mutate_base(self):
        base = {"t": {"a": 1}}
        override = {"t": {"b": 2}}
        deep_merge(base, override)
        assert base == {"t": {"a": 1}}


class TestResolvePoolConfig:
    def test_resolves_with_extends(self):
        """standard.toml extends _base, should resolve with all sections."""
        resolved = resolve_pool_config("standard")
        assert "extends" not in resolved
        assert "display" in resolved

    def test_cycle_detection(self, tmp_path):
        """Circular extends should raise ValueError."""
        (tmp_path / "a.toml").write_text('extends = "b"\n[display]\nx = 1\n')
        (tmp_path / "b.toml").write_text('extends = "a"\n[display]\ny = 2\n')
        with pytest.raises(ValueError, match="Circular extends"):
            resolve_pool_config("a", _pools_dir=tmp_path)

    def test_chain_depth_limit(self, tmp_path):
        """Chains deeper than 6 should raise ValueError."""
        for i, child in enumerate("abcdefg"):
            parent = "abcdefg"[i + 1] if i + 1 < 7 else None
            if parent:
                (tmp_path / f"{child}.toml").write_text(
                    f'extends = "{parent}"\n[x]\n{child} = 1\n'
                )
            else:
                (tmp_path / f"{child}.toml").write_text(f"[x]\n{child} = 1\n")
        with pytest.raises(ValueError, match="too deep"):
            resolve_pool_config("a", _pools_dir=tmp_path)

    def test_simple_chain(self, tmp_path):
        """Child extends parent, values merge correctly."""
        (tmp_path / "parent.toml").write_text(
            "[run]\nseed = 0\n[display]\nname = 'parent'\ncolor = 'red'\n"
        )
        (tmp_path / "child.toml").write_text(
            'extends = "parent"\n[display]\nname = "child"\n'
        )
        resolved = resolve_pool_config("child", _pools_dir=tmp_path)
        assert resolved["display"]["name"] == "child"
        assert resolved["display"]["color"] == "red"
        assert resolved["run"]["seed"] == 0
        assert "extends" not in resolved

    def test_missing_parent_raises(self, tmp_path):
        """Extending a nonexistent file should raise FileNotFoundError."""
        (tmp_path / "child.toml").write_text('extends = "nonexistent"\n[x]\na = 1\n')
        with pytest.raises(FileNotFoundError):
            resolve_pool_config("child", _pools_dir=tmp_path)

    def test_extends_list_later_parent_wins(self, tmp_path):
        """When extends is a list, later parents override earlier ones."""
        (tmp_path / "a.toml").write_text("[x]\nk = 'from_a'\nonly_a = 1\n")
        (tmp_path / "b.toml").write_text("[x]\nk = 'from_b'\nonly_b = 2\n")
        (tmp_path / "child.toml").write_text('extends = ["a", "b"]\n[display]\nn = 1\n')
        resolved = resolve_pool_config("child", _pools_dir=tmp_path)
        assert resolved["x"]["k"] == "from_b"
        assert resolved["x"]["only_a"] == 1
        assert resolved["x"]["only_b"] == 2

    def test_extends_list_own_values_win(self, tmp_path):
        """Pool's own values override all listed parents."""
        (tmp_path / "a.toml").write_text("[x]\nk = 'from_a'\n")
        (tmp_path / "b.toml").write_text("[x]\nk = 'from_b'\n")
        (tmp_path / "child.toml").write_text(
            'extends = ["a", "b"]\n[x]\nk = "from_child"\n'
        )
        resolved = resolve_pool_config("child", _pools_dir=tmp_path)
        assert resolved["x"]["k"] == "from_child"

    def test_extends_list_resolves_parent_chains(self, tmp_path):
        """Each parent in the list is resolved recursively."""
        (tmp_path / "grand.toml").write_text("[x]\ng = 1\n")
        (tmp_path / "a.toml").write_text('extends = "grand"\n[x]\na = 1\n')
        (tmp_path / "b.toml").write_text("[x]\nb = 1\n")
        (tmp_path / "child.toml").write_text('extends = ["a", "b"]\n[display]\nn = 1\n')
        resolved = resolve_pool_config("child", _pools_dir=tmp_path)
        assert resolved["x"] == {"g": 1, "a": 1, "b": 1}

    def test_extends_list_cycle_detection(self, tmp_path):
        """A cycle through a list branch must still raise."""
        (tmp_path / "a.toml").write_text('extends = ["b"]\n[x]\na = 1\n')
        (tmp_path / "b.toml").write_text('extends = ["a"]\n[x]\nb = 1\n')
        with pytest.raises(ValueError, match="Circular extends"):
            resolve_pool_config("a", _pools_dir=tmp_path)

    def test_extends_list_depth_limit(self, tmp_path):
        """Depth limit applies through a list branch too."""
        (tmp_path / "sibling.toml").write_text("[x]\ns = 1\n")
        for i, child in enumerate("abcdefg"):
            parent = "abcdefg"[i + 1] if i + 1 < 7 else None
            if parent:
                (tmp_path / f"{child}.toml").write_text(
                    f'extends = ["{parent}", "sibling"]\n[x]\n{child} = 1\n'
                )
            else:
                (tmp_path / f"{child}.toml").write_text(f"[x]\n{child} = 1\n")
        with pytest.raises(ValueError, match="too deep"):
            resolve_pool_config("a", _pools_dir=tmp_path)

    def test_all_pools_resolve(self):
        """Every non-underscore pool must resolve without error."""
        for toml_path in POOLS_DIR.glob("*.toml"):
            if toml_path.stem.startswith("_"):
                continue
            resolved = resolve_pool_config(toml_path.stem)
            assert "extends" not in resolved
            assert "display" in resolved


class TestValidation:
    def test_complete_config_passes(self):
        resolved = resolve_pool_config("standard")
        errors = validate_pool_config(resolved, "standard")
        assert errors == []

    def test_missing_section_reports_error(self):
        config = {"display": {"sort_order": 1}}
        errors = validate_pool_config(config, "test")
        assert len(errors) > 0
        assert any("structure" in e for e in errors)

    def test_wrong_section_type_reports_error(self):
        config = {
            s: {}
            for s in (
                "display",
                "run",
                "structure",
                "starting_items",
                "care_package",
                "item_randomizer",
                "enemy",
                "requirements",
                "budget",
            )
        }
        config["structure"] = "oops"
        errors = validate_pool_config(config, "test")
        assert len(errors) == 1
        assert "table" in errors[0]

    def test_all_pools_validate(self):
        """Every pool must pass validation after resolution."""
        for toml_path in POOLS_DIR.glob("*.toml"):
            if toml_path.stem.startswith("_"):
                continue
            resolved = resolve_pool_config(toml_path.stem)
            errors = validate_pool_config(resolved, toml_path.stem)
            assert errors == [], f"{toml_path.stem}: {errors}"


class TestModConfig:
    def test_add_dll_appends_to_populated_list(self, tmp_path):
        modengine_dir = tmp_path / "modengine2"
        modengine_dir.mkdir()
        config = modengine_dir / "config_speedfog.toml"
        config.write_text(
            "[modengine]\n"
            "debug = false\n"
            "external_dlls = [\n"
            '    "..\\\\lib\\\\RandomizerHelper.dll",\n'
            "]\n",
            encoding="utf-8",
        )

        assert add_dll_to_config(tmp_path) is True

        content = config.read_text(encoding="utf-8")
        assert '    "..\\\\lib\\\\speedfog_racing.dll",' in content
        assert '    "..\\\\lib\\\\RandomizerHelper.dll",' in content

    def test_add_dll_to_empty_list(self, tmp_path):
        modengine_dir = tmp_path / "modengine2"
        modengine_dir.mkdir()
        config = modengine_dir / "config_speedfog.toml"
        config.write_text(
            "[modengine]\ndebug = false\nexternal_dlls = []\n",
            encoding="utf-8",
        )

        assert add_dll_to_config(tmp_path) is True

        assert '    "..\\\\lib\\\\speedfog_racing.dll",' in config.read_text(
            encoding="utf-8"
        )

    def test_add_dll_is_idempotent(self, tmp_path):
        modengine_dir = tmp_path / "modengine2"
        modengine_dir.mkdir()
        config = modengine_dir / "config_speedfog.toml"
        config.write_text(
            "[modengine]\n"
            "external_dlls = [\n"
            '    "..\\\\lib\\\\speedfog_racing.dll",\n'
            "]\n",
            encoding="utf-8",
        )

        assert add_dll_to_config(tmp_path) is True
        assert (
            config.read_text(encoding="utf-8").count(
                '"..\\\\lib\\\\speedfog_racing.dll"'
            )
            == 1
        )

    def test_add_dll_missing_config_fails(self, tmp_path):
        assert add_dll_to_config(tmp_path) is False
