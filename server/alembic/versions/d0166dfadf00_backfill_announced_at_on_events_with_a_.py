"""backfill announced_at on events with a newcomers stage

Revision ID: d0166dfadf00
Revises: a3e5c7d9b1f2
Create Date: 2026-09-16 11:04:49.680473

The announcement (``config.announced_at``) is now the newcomer cut, and a
config with a ``newcomers`` stage must set it explicitly: the timeline's
display default (``starts_at`` minus 7 days) must never decide a final's
field. The public event page validates the stored config on every request,
so a document saved before that rule would read as "Event not found" for
every viewer.

This migration writes the default the timeline was already showing into any
stored config that has a newcomers stage and no ``announced_at``: those
events keep the same announce stop and validate again, and the admin editor
can then correct the date.
"""

from collections.abc import Sequence
from datetime import UTC, timedelta

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d0166dfadf00"
down_revision: str | None = "a3e5c7d9b1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

events = sa.table(
    "events",
    sa.column("id", sa.Uuid),
    sa.column("starts_at", sa.DateTime(timezone=True)),
    sa.column("config", sa.JSON),
)


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.select(events.c.id, events.c.starts_at, events.c.config)).all()
    for event_id, starts_at, config in rows:
        if config.get("announced_at") is not None:
            continue
        if not any(s.get("kind") == "newcomers" for s in config.get("stages") or []):
            continue
        # SQLite hands the column back naive; the app reads it as UTC.
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=UTC)
        announced = (starts_at - timedelta(days=7)).isoformat().replace("+00:00", "Z")
        bind.execute(
            sa.update(events)
            .where(events.c.id == event_id)
            .values(config={**config, "announced_at": announced})
        )


def downgrade() -> None:
    # A no-op on purpose: ``announced_at`` was optional before this rule, so
    # an explicit date stays valid on the way back, and the value written is
    # the one the timeline already displayed.
    pass
