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


def test_playing_ghost_behind_t_stays_at_its_own_igt() -> None:
    # Started after the viewer: nothing is known of it at the viewer's IGT, so
    # it stands where its run has got to, not at its last zone change.
    graph = _graph({"start": 0, "fog_a": 1})
    p = _participant(
        status=ParticipantStatus.PLAYING,
        igt_ms=130_000,
        zone_history=[
            {"node_id": "start", "igt_ms": 0, "type": "spawn"},
            {"node_id": "fog_a", "igt_ms": 120_000},
        ],
    )

    projected = project_participant_at(p, viewer_igt_ms=999_000, graph_json=graph)

    assert projected is not None
    assert projected.status == ParticipantStatus.PLAYING
    assert projected.igt_ms == 130_000
    assert projected.current_zone == "fog_a"


def test_playing_ghost_still_in_its_zone_at_t_reads_t() -> None:
    # Started before the viewer and stuck on a boss since 18:00 of its run,
    # now at 30:00: at the viewer's 20:00 it was still there.
    graph = _graph({"start": 0, "fog_a": 1, "boss": 1})
    p = _participant(
        status=ParticipantStatus.PLAYING,
        igt_ms=1_800_000,
        zone_history=[
            {"node_id": "start", "igt_ms": 0, "type": "spawn"},
            {"node_id": "fog_a", "igt_ms": 840_000},
            {"node_id": "boss", "igt_ms": 1_080_000},
        ],
    )

    projected = project_participant_at(p, viewer_igt_ms=1_200_000, graph_json=graph)

    assert projected is not None
    assert projected.status == ParticipantStatus.PLAYING
    assert projected.igt_ms == 1_200_000
    assert projected.current_zone == "boss"


def test_finished_ghost_in_its_last_zone_at_t_reads_t() -> None:
    # Finishing adds no history entry: between its arrival in the last zone
    # and its finish, the ghost is still racing at the viewer's IGT.
    graph = _graph({"start": 0, "fog_a": 1, "end": 2})
    p = _participant(
        status=ParticipantStatus.FINISHED,
        igt_ms=600_000,
        zone_history=[
            {"node_id": "start", "igt_ms": 0, "type": "spawn"},
            {"node_id": "fog_a", "igt_ms": 100_000},
            {"node_id": "end", "igt_ms": 480_000},
        ],
    )

    projected = project_participant_at(p, viewer_igt_ms=540_000, graph_json=graph)

    assert projected is not None
    assert projected.status == ParticipantStatus.PLAYING
    assert projected.igt_ms == 540_000
    assert projected.current_zone == "end"


def test_abandoned_ghost_drops_out_at_the_igt_it_quit() -> None:
    # Quit at 30:00 of its run, last zone change at 18:00.
    graph = _graph({"start": 0, "fog_a": 1})
    p = _participant(
        status=ParticipantStatus.ABANDONED,
        igt_ms=1_800_000,
        zone_history=[
            {"node_id": "start", "igt_ms": 0, "type": "spawn"},
            {"node_id": "fog_a", "igt_ms": 1_080_000},
        ],
    )

    before = project_participant_at(p, viewer_igt_ms=1_200_000, graph_json=graph)
    assert before is not None
    assert before.status == ParticipantStatus.PLAYING
    assert before.igt_ms == 1_200_000

    after = project_participant_at(p, viewer_igt_ms=2_400_000, graph_json=graph)
    assert after is not None
    assert after.status == ParticipantStatus.ABANDONED
    assert after.igt_ms == 1_800_000


def test_igt_behind_the_last_zone_entry_keeps_the_entry() -> None:
    # A row whose recorded IGT trails its last zone entry (written before every
    # entry raised it): the ghost has still reached that entry.
    graph = _graph({"start": 0, "fog_a": 1})
    p = _participant(
        status=ParticipantStatus.ABANDONED,
        igt_ms=119_500,
        zone_history=[
            {"node_id": "start", "igt_ms": 0, "type": "spawn"},
            {"node_id": "fog_a", "igt_ms": 120_000},
        ],
    )

    projected = project_participant_at(p, viewer_igt_ms=999_000, graph_json=graph)

    assert projected is not None
    assert projected.status == ParticipantStatus.ABANDONED
    assert projected.igt_ms == 120_000


def test_finished_at_t_equal_to_final_appears_as_finished() -> None:
    graph = _graph({"start": 0, "end": 1})
    p = _participant(
        status=ParticipantStatus.FINISHED,
        igt_ms=300_000,
        zone_history=[
            {"node_id": "start", "igt_ms": 0, "type": "spawn"},
            {"node_id": "end", "igt_ms": 300_000},
        ],
    )

    projected = project_participant_at(p, viewer_igt_ms=300_000, graph_json=graph)

    assert projected is not None
    assert projected.status == ParticipantStatus.FINISHED
    assert projected.igt_ms == 300_000
    assert projected.current_zone == "end"
    assert projected.current_layer == 1


def test_finished_at_t_after_final_clamps_to_final() -> None:
    graph = _graph({"start": 0, "end": 1})
    p = _participant(
        status=ParticipantStatus.FINISHED,
        igt_ms=300_000,
        zone_history=[
            {"node_id": "start", "igt_ms": 0, "type": "spawn"},
            {"node_id": "end", "igt_ms": 300_000},
        ],
    )

    projected = project_participant_at(p, viewer_igt_ms=10_000_000, graph_json=graph)

    assert projected is not None
    assert projected.status == ParticipantStatus.FINISHED
    assert projected.igt_ms == 300_000


def test_playing_at_t_within_history_returns_t_as_igt() -> None:
    graph = _graph({"start": 0, "fog_a": 1, "fog_b": 2})
    p = _participant(
        status=ParticipantStatus.PLAYING,
        igt_ms=500_000,
        zone_history=[
            {"node_id": "start", "igt_ms": 0, "type": "spawn"},
            {"node_id": "fog_a", "igt_ms": 100_000},
            {"node_id": "fog_b", "igt_ms": 400_000},
        ],
    )

    projected = project_participant_at(p, viewer_igt_ms=250_000, graph_json=graph)

    assert projected is not None
    assert projected.status == ParticipantStatus.PLAYING
    assert projected.igt_ms == 250_000
    assert projected.current_zone == "fog_a"
    assert projected.current_layer == 1


def test_abandoned_before_t_keeps_abandoned_status() -> None:
    graph = _graph({"start": 0, "fog_a": 1})
    p = _participant(
        status=ParticipantStatus.ABANDONED,
        igt_ms=180_000,
        zone_history=[
            {"node_id": "start", "igt_ms": 0, "type": "spawn"},
            {"node_id": "fog_a", "igt_ms": 180_000},
        ],
    )

    projected = project_participant_at(p, viewer_igt_ms=500_000, graph_json=graph)

    assert projected is not None
    assert projected.status == ParticipantStatus.ABANDONED
    assert projected.igt_ms == 180_000
    assert projected.current_zone == "fog_a"
    assert projected.current_layer == 1


def test_abandoned_with_t_inside_history_appears_as_playing() -> None:
    graph = _graph({"start": 0, "fog_a": 1, "fog_b": 2})
    p = _participant(
        status=ParticipantStatus.ABANDONED,
        igt_ms=400_000,
        zone_history=[
            {"node_id": "start", "igt_ms": 0, "type": "spawn"},
            {"node_id": "fog_a", "igt_ms": 100_000},
            {"node_id": "fog_b", "igt_ms": 400_000},
        ],
    )

    projected = project_participant_at(p, viewer_igt_ms=200_000, graph_json=graph)

    assert projected is not None
    assert projected.status == ParticipantStatus.PLAYING
    assert projected.igt_ms == 200_000
    assert projected.current_zone == "fog_a"


def test_t_zero_renders_every_ghost_at_spawn() -> None:
    graph = _graph({"start": 0, "fog_a": 1})
    p = _participant(
        status=ParticipantStatus.FINISHED,
        igt_ms=400_000,
        zone_history=[
            {"node_id": "start", "igt_ms": 0, "type": "spawn"},
            {"node_id": "fog_a", "igt_ms": 100_000},
        ],
    )

    projected = project_participant_at(p, viewer_igt_ms=0, graph_json=graph)

    assert projected is not None
    assert projected.status == ParticipantStatus.PLAYING
    assert projected.igt_ms == 0
    assert projected.current_zone == "start"
    assert projected.current_layer == 0


def test_empty_zone_history_returns_none() -> None:
    p = _participant(status=ParticipantStatus.READY, igt_ms=0, zone_history=None)
    assert project_participant_at(p, viewer_igt_ms=10_000, graph_json=_graph({"start": 0})) is None

    p2 = _participant(status=ParticipantStatus.READY, igt_ms=0, zone_history=[])
    assert project_participant_at(p2, viewer_igt_ms=10_000, graph_json=_graph({"start": 0})) is None


def test_death_count_sums_attributed_deaths_up_to_t() -> None:
    graph = _graph({"start": 0, "fog_a": 1, "fog_b": 2})
    p = _participant(
        status=ParticipantStatus.PLAYING,
        igt_ms=500_000,
        zone_history=[
            {"node_id": "start", "igt_ms": 0, "type": "spawn", "deaths": 1},
            {"node_id": "fog_a", "igt_ms": 100_000, "deaths": 2},
            {"node_id": "fog_b", "igt_ms": 400_000, "deaths": 5},
        ],
    )

    early = project_participant_at(p, viewer_igt_ms=50_000, graph_json=graph)
    assert early is not None and early.death_count == 1

    middle = project_participant_at(p, viewer_igt_ms=150_000, graph_json=graph)
    assert middle is not None and middle.death_count == 3

    late = project_participant_at(p, viewer_igt_ms=500_000, graph_json=graph)
    assert late is not None and late.death_count == 8


def test_layer_takes_max_over_visited_nodes_handles_backtracks() -> None:
    graph = _graph({"start": 0, "fog_a": 1, "fog_b": 2})
    p = _participant(
        status=ParticipantStatus.PLAYING,
        igt_ms=500_000,
        zone_history=[
            {"node_id": "start", "igt_ms": 0, "type": "spawn"},
            {"node_id": "fog_a", "igt_ms": 100_000},
            {"node_id": "fog_b", "igt_ms": 200_000},
            {"node_id": "fog_a", "igt_ms": 300_000},
        ],
    )

    projected = project_participant_at(p, viewer_igt_ms=400_000, graph_json=graph)

    assert projected is not None
    assert projected.current_zone == "fog_a"
    assert projected.current_layer == 2


def test_disqualified_never_projects_as_a_live_runner() -> None:
    # Whatever the viewer's IGT, a disqualified ghost reads DQ, never as a
    # runner still racing (nor as the leader whose gaps the others chase).
    graph = _graph({"start": 0, "fog_a": 1, "fog_b": 2})
    p = _participant(
        status=ParticipantStatus.DISQUALIFIED,
        igt_ms=400_000,
        zone_history=[
            {"node_id": "start", "igt_ms": 0, "type": "spawn"},
            {"node_id": "fog_a", "igt_ms": 100_000},
            {"node_id": "fog_b", "igt_ms": 400_000},
        ],
    )

    for viewer_igt in (200_000, 900_000):
        projected = project_participant_at(p, viewer_igt_ms=viewer_igt, graph_json=graph)
        assert projected is not None
        assert projected.status == ParticipantStatus.DISQUALIFIED


def test_projected_splits_stop_at_the_viewer_igt() -> None:
    """A ghost's splits hold only the arrivals reached by the viewer's IGT: a
    later one would leak its future progress and skew the mod's gaps."""
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
    assert projected.layer_entry_igts == {"0": 0, "1": 100_000}


def test_projected_splits_keep_the_first_arrival_on_a_backtrack() -> None:
    graph = _graph({"start": 0, "fog_a": 1, "fog_b": 2})
    p = _participant(
        status=ParticipantStatus.PLAYING,
        igt_ms=500_000,
        zone_history=[
            {"node_id": "start", "igt_ms": 0, "type": "spawn"},
            {"node_id": "fog_a", "igt_ms": 100_000},
            {"node_id": "fog_b", "igt_ms": 200_000},
            {"node_id": "fog_a", "igt_ms": 300_000},
        ],
    )

    projected = project_participant_at(p, viewer_igt_ms=400_000, graph_json=graph)

    assert projected is not None
    assert projected.layer_entry_igts == {"0": 0, "1": 100_000, "2": 200_000}
