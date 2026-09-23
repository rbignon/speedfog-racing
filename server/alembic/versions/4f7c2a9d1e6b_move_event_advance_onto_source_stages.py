"""move event advance onto source stages

Revision ID: 4f7c2a9d1e6b
Revises: d0166dfadf00
Create Date: 2026-09-23 12:00:00.000000

A stage's ``advance`` now sits on the stage that sends runners on, not on the
stage that takes them: once quarters feed semis that feed a final, the final
can no longer speak for every round. The public event page validates the
stored config on every request, so a document in the old shape would read as
"Event not found" once the new rules ship.

The upgrade copies each taking stage's ``advance`` onto the stages its
``from`` names and removes it from the taker. It only touches the old shape
(a stage with ``from`` and ``advance`` that nothing takes from in turn), so a
second run, or a document already in the new shape, changes nothing. The
downgrade does the reverse where the old model can express the document.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4f7c2a9d1e6b"
down_revision: str | None = "d0166dfadf00"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

events = sa.table(
    "events",
    sa.column("id", sa.Uuid),
    sa.column("config", sa.JSON),
)


def move_advance_to_sources(config: dict[str, Any]) -> dict[str, Any] | None:
    """The config with each taker's ``advance`` moved onto its sources, None if unchanged."""
    stages = [dict(s) for s in config.get("stages") or []]
    named = {key for s in stages for key in s.get("from") or []}
    changed = False
    for taker in stages:
        advance = taker.get("advance")
        sources = taker.get("from") or []
        # In the new shape a stage with ``from`` and ``advance`` always feeds
        # a later one, so only the old shape's final matches here.
        if advance is None or not sources or taker.get("key") in named:
            continue
        for stage in stages:
            if stage.get("key") in sources:
                stage["advance"] = advance
        taker["advance"] = None
        changed = True
    return {**config, "stages": stages} if changed else None


def move_advance_to_takers(config: dict[str, Any]) -> dict[str, Any] | None:
    """The reverse, for a final fed by seeded stages sharing one ``advance``; None otherwise."""
    stages = [dict(s) for s in config.get("stages") or []]
    named = {key for s in stages for key in s.get("from") or []}
    # The old model had two rounds at most: a fed stage feeding another one
    # (a semi fed by quarters) cannot be expressed, so the document stays.
    if any(s.get("from") and s.get("key") in named for s in stages):
        return None
    by_key = {s.get("key"): s for s in stages}
    changed = False
    for taker in stages:
        sources = [by_key.get(key) for key in taker.get("from") or []]
        if not sources or any(s is None or s.get("from") for s in sources):
            continue
        advances = {s.get("advance") for s in sources if s is not None}
        if len(advances) != 1 or None in advances:
            continue
        taker["advance"] = advances.pop()
        for source in sources:
            if source is not None:
                source["advance"] = None
        changed = True
    return {**config, "stages": stages} if changed else None


def _rewrite(transform: Any) -> None:
    bind = op.get_bind()
    for event_id, config in bind.execute(sa.select(events.c.id, events.c.config)).all():
        rewritten = transform(config or {})
        if rewritten is not None:
            bind.execute(sa.update(events).where(events.c.id == event_id).values(config=rewritten))


def upgrade() -> None:
    _rewrite(move_advance_to_sources)


def downgrade() -> None:
    _rewrite(move_advance_to_takers)
