"""wrap event stages in brackets

Revision ID: b8e2f4a6c1d3
Revises: c9e5a1b3f4d6
Create Date: 2026-10-07 18:00:00.000000

An event's playoff stages now live in named brackets, each with an entry
rule (``all`` or ``newcomers``) and its own chain of stages, instead of one
flat list where a ``newcomers`` kind drew its own field. The public event
page validates the stored config on every request, so a document in the old
shape would read as "Event not found" once the new schema ships.

The upgrade moves every stage but the newcomers one into a ``main`` bracket
(entry ``all``), in its order, and turns a ``newcomers`` stage into a
``newcomers`` bracket holding one final seeded 1 to ``size``, under the same
key so an attached race keeps its slot. A document already in brackets, or
without a stage list, is left alone, so a second run changes nothing. The
downgrade does the reverse where the old model can express the document.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8e2f4a6c1d3"
down_revision: str | None = "c9e5a1b3f4d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

events = sa.table(
    "events",
    sa.column("id", sa.Uuid),
    sa.column("config", sa.JSON),
)

MAIN = {"key": "main", "label": "Playoffs", "entry": "all"}
NEWCOMERS = {"key": "newcomers", "label": "Newcomers", "entry": "newcomers"}


def _without_size(stage: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in stage.items() if k != "size"}


def wrap_stages_in_brackets(config: dict[str, Any]) -> dict[str, Any] | None:
    """The config with its flat ``stages`` moved into brackets, None if unchanged."""
    if "brackets" in config or "stages" not in config:
        return None
    stages = [dict(s) for s in config.get("stages") or []]
    brackets: list[dict[str, Any]] = []
    main = [_without_size(s) for s in stages if s.get("kind") != "newcomers"]
    if main:
        brackets.append({**MAIN, "stages": main})
    for stage in stages:
        if stage.get("kind") != "newcomers":
            continue
        size = stage.get("size") or 0
        final = {
            **_without_size(stage),
            "kind": "final",
            "seeds": list(range(1, size + 1)),
            "from": None,
            "advance": None,
        }
        brackets.append({**NEWCOMERS, "stages": [final]})
    rest = {k: v for k, v in config.items() if k != "stages"}
    return {**rest, "brackets": brackets}


def unwrap_brackets(config: dict[str, Any]) -> dict[str, Any] | None:
    """The reverse, where the flat model can express the document; None otherwise.

    It can when the first bracket draws from everyone and any other is a
    single newcomers bracket holding one final seeded 1 to N (N at most 8),
    which goes back to a ``newcomers`` stage listed first.
    """
    brackets = config.get("brackets")
    if brackets is None:
        return None
    rest = {k: v for k, v in config.items() if k != "brackets"}
    if not brackets:
        return {**rest, "stages": []}
    first, *others = brackets
    if first.get("entry") != "all" or len(others) > 1:
        return None
    newcomers: list[dict[str, Any]] = []
    for bracket in others:
        inner = bracket.get("stages") or []
        if bracket.get("entry") != "newcomers" or len(inner) != 1:
            return None
        stage = dict(inner[0])
        seeds = stage.get("seeds") or []
        if stage.get("from") or not 2 <= len(seeds) <= 8:
            return None
        if seeds != list(range(1, len(seeds) + 1)):
            return None
        newcomers.append(
            {
                **stage,
                "kind": "newcomers",
                "size": len(seeds),
                "seeds": None,
                "from": None,
                "advance": None,
            }
        )
    stages = [dict(s) for s in first.get("stages") or []]
    return {**rest, "stages": newcomers + stages}


def _rewrite(transform: Any) -> None:
    bind = op.get_bind()
    for event_id, config in bind.execute(sa.select(events.c.id, events.c.config)).all():
        rewritten = transform(config or {})
        if rewritten is not None:
            bind.execute(sa.update(events).where(events.c.id == event_id).values(config=rewritten))


def upgrade() -> None:
    _rewrite(wrap_stages_in_brackets)


def downgrade() -> None:
    _rewrite(unwrap_brackets)
