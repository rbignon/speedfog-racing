"""normalize zone_history JSON null to SQL NULL

Revision ID: fffc83b0f2c4
Revises: b28f8a846049
Create Date: 2026-05-14 12:30:14.440156

Some legacy rows store the JSON value ``null`` in ``zone_history``
instead of SQL NULL: ``sqlalchemy.dialects.postgresql.JSON`` defaults to
``none_as_null=False``, so ``p.zone_history = None`` in Python was
serialized as JSON ``null``. PostgreSQL's ``json_array_length`` errors
on those values ("cannot get array length of a scalar"), which broke
``/api/users/{username}`` for any viewer of a profile whose history
contained one.

The model-side fix (``none_as_null=True`` on both ``zone_history``
columns) prevents new occurrences. This migration cleans up the
existing rows: rewrite JSON ``null`` to SQL NULL on both
``participants`` and ``training_sessions``.

The same normalization is applied on SQLite (test) where
``json_type(zone_history) = 'null'`` matches the same shape; in
practice tests don't seed JSON ``null`` so the UPDATE is a no-op there.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fffc83b0f2c4"
down_revision: str | None = "b28f8a846049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        # ``participants.zone_history`` is JSON, ``training_sessions.zone_history``
        # is JSONB; the function name differs between the two types.
        op.execute(
            "UPDATE participants SET zone_history = NULL "
            "WHERE zone_history IS NOT NULL "
            "AND json_typeof(zone_history) = 'null'"
        )
        op.execute(
            "UPDATE training_sessions SET zone_history = NULL "
            "WHERE zone_history IS NOT NULL "
            "AND jsonb_typeof(zone_history) = 'null'"
        )
    elif dialect == "sqlite":
        op.execute(
            "UPDATE participants SET zone_history = NULL "
            "WHERE zone_history IS NOT NULL "
            "AND json_type(zone_history) = 'null'"
        )
        op.execute(
            "UPDATE training_sessions SET zone_history = NULL "
            "WHERE zone_history IS NOT NULL "
            "AND json_type(zone_history) = 'null'"
        )


def downgrade() -> None:
    # Downgrade is intentionally a no-op: re-introducing JSON ``null``
    # values on the way back would re-create the production crash this
    # migration fixes. SQL NULL is the canonical "no history" shape;
    # rolling back the data isn't useful.
    pass
