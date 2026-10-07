"""Event test configs written as a flat stage list, wrapped into brackets.

The wrapping is the data migration's own (``wrap_stages_in_brackets``), so the
older tests keep their flat fixtures and run on the shape the migration
produces. New tests write brackets directly.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "b8e2f4a6c1d3_wrap_event_stages_in_brackets.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("event_fixtures_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_migration = _load()


def bracketed(config: dict[str, Any]) -> dict[str, Any]:
    """``config`` with its flat ``stages`` wrapped into brackets; unchanged without them."""
    wrapped = _migration.wrap_stages_in_brackets(config)
    return wrapped if wrapped is not None else config


def stages_of(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Every stage dict of a dumped bracketed config, bracket order then stage order."""
    return [stage for bracket in raw["brackets"] for stage in bracket["stages"]]
