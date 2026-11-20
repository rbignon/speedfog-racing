"""Relay races: the seed capability and the block a relay seed carries.

A relay seed is a seed whose ``graph.json`` has a top-level ``relay`` object
(the generator writes it when its relay plugin is enabled).
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import ColumnElement

from speedfog_racing.models import Seed

RELAY_PLUGIN = "relay"


def seed_has_relay(graph_json: Mapping[str, Any]) -> bool:
    """Whether a seed supports relay races: ``relay`` is a non-empty object."""
    block = graph_json.get(RELAY_PLUGIN)
    return isinstance(block, dict) and bool(block)


def relay_seed_clause() -> ColumnElement[bool]:
    """SQL twin of ``seed_has_relay``: reads ``Seed.relay``, which the pool scan
    sets when it adds the seed, so no query parses a graph."""
    clause: ColumnElement[bool] = Seed.relay.is_(True)
    return clause


def relay_flags(graph_json: Mapping[str, Any]) -> dict[str, int] | None:
    """The seed's relay block minus ``warp_flag_count``, or None for a plain seed."""
    if not seed_has_relay(graph_json):
        return None
    block: Mapping[str, Any] = graph_json[RELAY_PLUGIN]
    return {k: v for k, v in block.items() if k != "warp_flag_count"}
