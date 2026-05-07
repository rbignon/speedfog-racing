"""Unit tests for the daily-race per-viewer projector.

Tests construct lightweight stand-ins for ``Participant`` to keep the
projector exercised in isolation (no DB, no async). The projector reads
``status``, ``igt_ms``, ``zone_history``; we feed those directly via a
SimpleNamespace.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from speedfog_racing.models import ParticipantStatus
from speedfog_racing.websocket.race.projection import project_participant_at


def _graph(layers_by_node: dict[str, int]) -> dict[str, Any]:
    """Build a minimal graph_json that ``get_layer_for_node`` accepts."""
    return {
        "nodes": {node: {"layer": layer} for node, layer in layers_by_node.items()},
    }


def _participant(
    *,
    status: ParticipantStatus,
    igt_ms: int = 0,
    zone_history: list[dict[str, Any]] | None = None,
) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        igt_ms=igt_ms,
        zone_history=zone_history,
    )


def test_finished_at_t_before_final_appears_as_playing_at_projected_zone() -> None:
    graph = _graph({"start": 0, "fog_a": 1, "fog_b": 2, "end": 3})
    p = _participant(
        status=ParticipantStatus.FINISHED,
        igt_ms=600_000,
        zone_history=[
            {"node_id": "start", "igt_ms": 0, "type": "spawn"},
            {"node_id": "fog_a", "igt_ms": 100_000},
            {"node_id": "fog_b", "igt_ms": 250_000},
            {"node_id": "end", "igt_ms": 600_000},
        ],
    )

    projected = project_participant_at(p, viewer_igt_ms=200_000, graph_json=graph)

    assert projected is not None
    assert projected.status == ParticipantStatus.PLAYING
    assert projected.current_zone == "fog_a"
    assert projected.current_layer == 1
    assert projected.igt_ms == 200_000
    assert projected.death_count == 0


def test_playing_with_t_past_history_clamps_to_last_event_igt() -> None:
    graph = _graph({"start": 0, "fog_a": 1})
    p = _participant(
        status=ParticipantStatus.PLAYING,
        igt_ms=120_000,
        zone_history=[
            {"node_id": "start", "igt_ms": 0, "type": "spawn"},
            {"node_id": "fog_a", "igt_ms": 120_000},
        ],
    )

    projected = project_participant_at(p, viewer_igt_ms=999_000, graph_json=graph)

    assert projected is not None
    assert projected.status == ParticipantStatus.PLAYING
    assert projected.igt_ms == 120_000  # clamps to L_full, not viewer_igt_ms
    assert projected.current_zone == "fog_a"
