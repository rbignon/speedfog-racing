"""backfill relay first runners

Revision ID: a4898d1850a8
Revises: c6e1a8d3f205
Create Date: 2026-11-21 20:00:00.000000

A relay team has a first runner exactly when it has a member: joining a team
without one makes the runner it, and a first runner who leaves hands it to the
next member by join time. Before that rule, joining an existing team (a
placeholder) left the column null, and a first runner leaving cleared it. This
gives every team with members and no first runner its earliest member, the
runner the start used to fall back on.

The downgrade does nothing: which teams were filled is not recorded, and a
first runner set is valid under the old rule too.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4898d1850a8"
down_revision: str | None = "c6e1a8d3f205"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Plain SQL that PostgreSQL and SQLite (the tests) both run.
BACKFILL = """
UPDATE relay_teams
SET first_runner_id = (
    SELECT participants.id
    FROM participants
    WHERE participants.relay_team_id = relay_teams.id
    ORDER BY participants.created_at, participants.id
    LIMIT 1
)
WHERE first_runner_id IS NULL
"""


def upgrade() -> None:
    op.execute(BACKFILL)


def downgrade() -> None:
    pass
