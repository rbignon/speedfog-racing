"""Tests for pool TOML inheritance (deep_merge + resolve_pool_config)."""

from __future__ import annotations

import pytest

from generate_pool import (
    POOLS_DIR,
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

    def test_does_not_mutate_base(self):
        base = {"t": {"a": 1}}
        override = {"t": {"b": 2}}
        deep_merge(base, override)
        assert base == {"t": {"a": 1}}


class TestResolvePoolConfig:
    def test_no_extends_returns_self(self):
        """A file without extends should resolve to itself."""
        # standard.toml currently has no extends key
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
        """Chains deeper than 4 should raise ValueError."""
        (tmp_path / "a.toml").write_text('extends = "b"\n[x]\na = 1\n')
        (tmp_path / "b.toml").write_text('extends = "c"\n[x]\nb = 1\n')
        (tmp_path / "c.toml").write_text('extends = "d"\n[x]\nc = 1\n')
        (tmp_path / "d.toml").write_text('extends = "e"\n[x]\nd = 1\n')
        (tmp_path / "e.toml").write_text("[x]\ne = 1\n")
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

    def test_all_pools_validate(self):
        """Every pool must pass validation after resolution."""
        for toml_path in POOLS_DIR.glob("*.toml"):
            if toml_path.stem.startswith("_"):
                continue
            resolved = resolve_pool_config(toml_path.stem)
            errors = validate_pool_config(resolved, toml_path.stem)
            assert errors == [], f"{toml_path.stem}: {errors}"
