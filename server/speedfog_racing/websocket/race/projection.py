"""Per-viewer projection of a participant's state at a given IGT.

Used by daily-race leaderboard broadcasts to render finished and
concurrent ghosts as if they were racing in parallel with the viewer.
See docs/specs/2026-05-06-daily-replay-leaderboard-design.md.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from speedfog_racing.models import Participant, ParticipantStatus, User
from speedfog_racing.services.layer_service import get_layer_for_node


@dataclass(frozen=True)
class ProjectedParticipant:
    """Participant-shaped wrapper exposing projected dynamic fields.

    Static fields (``id``, ``user``, ``color_index``) passthrough to the
    real ``Participant``; dynamic fields hold the projected values.
    """

    real: Participant
    status: ParticipantStatus
    current_zone: str | None
    current_layer: int
    igt_ms: int
    death_count: int
    zone_history: list[dict[str, Any]] | None
    # Always empty: sort_leaderboard falls back to scanning the projected
    # zone_history slice, which is the right behaviour for ghosts.
    layer_entry_igts: dict[str, int]

    @property
    def id(self) -> uuid.UUID:
        return self.real.id

    @property
    def user(self) -> User:
        return self.real.user

    @property
    def color_index(self) -> int:
        return self.real.color_index


def project_participant_at(
    participant: Participant,
    viewer_igt_ms: int,
    graph_json: dict[str, Any] | None,
) -> ProjectedParticipant | None:
    """Project ``participant`` to the viewer's IGT.

    Returns ``None`` for participants with no usable history at this IGT
    (empty ``zone_history`` or first entry past ``viewer_igt_ms``); these
    are excluded from the projected leaderboard.
    """
    history = participant.zone_history or []
    if not history:
        return None

    # zone_history is append-ordered by igt_ms; last entry has the max.
    full_last_igt = int(history[-1].get("igt_ms", 0))

    past: list[dict[str, Any]] = []
    proj_layer = 0
    proj_deaths = 0
    for e in history:
        igt = int(e.get("igt_ms", 0))
        if igt > viewer_igt_ms:
            break
        past.append(e)
        proj_deaths += int(e.get("deaths", 0))
        if graph_json:
            node_id = e.get("node_id")
            if isinstance(node_id, str):
                layer = get_layer_for_node(node_id, graph_json)
                if layer > proj_layer:
                    proj_layer = layer

    if not past:
        return None

    last_event = past[-1]
    proj_zone = last_event.get("node_id") if isinstance(last_event.get("node_id"), str) else None

    real_status = participant.status
    real_final_igt = int(participant.igt_ms or 0)

    if real_status == ParticipantStatus.FINISHED and real_final_igt <= viewer_igt_ms:
        proj_status = ParticipantStatus.FINISHED
        proj_igt = real_final_igt
    elif real_status == ParticipantStatus.ABANDONED and full_last_igt <= viewer_igt_ms:
        proj_status = ParticipantStatus.ABANDONED
        proj_igt = full_last_igt
    else:
        proj_status = ParticipantStatus.PLAYING
        proj_igt = min(viewer_igt_ms, full_last_igt)

    return ProjectedParticipant(
        real=participant,
        status=proj_status,
        current_zone=proj_zone,
        current_layer=proj_layer,
        igt_ms=proj_igt,
        death_count=proj_deaths,
        zone_history=past,
        layer_entry_igts={},
    )
