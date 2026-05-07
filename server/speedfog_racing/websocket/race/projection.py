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


@dataclass
class ProjectedParticipant:
    """Read-only Participant-shaped wrapper used by sort/serialization layers.

    Mirrors the attributes read by ``sort_leaderboard`` and
    ``participant_to_info``. Static fields (``id``, ``user``,
    ``color_index``) passthrough to the real ``Participant``; dynamic
    fields (``status``, ``current_zone``, ``current_layer``, ``igt_ms``,
    ``death_count``, ``zone_history``, ``layer_entry_igts``) hold the
    projected values.
    """

    _real: Participant
    status: ParticipantStatus
    current_zone: str | None
    current_layer: int
    igt_ms: int
    death_count: int
    zone_history: list[dict[str, Any]] | None
    layer_entry_igts: dict[str, int]

    @property
    def id(self) -> uuid.UUID:
        return self._real.id

    @property
    def user(self) -> User:
        return self._real.user

    @property
    def color_index(self) -> int:
        return self._real.color_index


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

    past = [e for e in history if int(e.get("igt_ms", 0)) <= viewer_igt_ms]
    if not past:
        return None

    last_event = past[-1]
    last_event_igt = int(last_event.get("igt_ms", 0))

    real_status = participant.status
    real_final_igt = int(participant.igt_ms or 0)

    if real_status == ParticipantStatus.FINISHED and real_final_igt <= viewer_igt_ms:
        proj_status = ParticipantStatus.FINISHED
        proj_igt = real_final_igt
    elif real_status == ParticipantStatus.ABANDONED and last_event_igt <= viewer_igt_ms:
        proj_status = ParticipantStatus.ABANDONED
        proj_igt = last_event_igt
    else:
        proj_status = ParticipantStatus.PLAYING
        proj_igt = viewer_igt_ms

    proj_zone = last_event.get("node_id") if isinstance(last_event.get("node_id"), str) else None

    proj_layer = 0
    if graph_json:
        for e in past:
            node_id = e.get("node_id")
            if isinstance(node_id, str):
                layer = get_layer_for_node(node_id, graph_json)
                if layer > proj_layer:
                    proj_layer = layer

    proj_deaths = sum(int(e.get("deaths", 0)) for e in past)

    return ProjectedParticipant(
        _real=participant,
        status=proj_status,
        current_zone=proj_zone,
        current_layer=proj_layer,
        igt_ms=proj_igt,
        death_count=proj_deaths,
        zone_history=past,
        layer_entry_igts={},
    )
