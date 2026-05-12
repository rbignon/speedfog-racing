"""add daily streak

Revision ID: b28f8a846049
Revises: e19ed46884b0
Create Date: 2026-05-12 16:37:56.005321

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b28f8a846049"
down_revision: str | None = "e19ed46884b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "daily_current_streak",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "daily_best_streak",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "daily_freeze_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("daily_last_qualifying_date", sa.Date(), nullable=True),
    )

    op.create_check_constraint(
        "ck_users_daily_freeze_count_range",
        "users",
        "daily_freeze_count >= 0 AND daily_freeze_count <= 2",
    )
    op.create_check_constraint(
        "ck_users_daily_current_streak_nonneg",
        "users",
        "daily_current_streak >= 0",
    )
    op.create_check_constraint(
        "ck_users_daily_best_ge_current",
        "users",
        "daily_best_streak >= daily_current_streak",
    )

    op.create_table(
        "daily_streak_freezes",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("daily_date", sa.Date(), nullable=False),
        sa.Column(
            "consumed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "daily_date"),
    )

    connection = op.get_bind()
    _backfill_streaks(connection)


def downgrade() -> None:
    op.drop_table("daily_streak_freezes")

    op.drop_constraint("ck_users_daily_best_ge_current", "users", type_="check")
    op.drop_constraint("ck_users_daily_current_streak_nonneg", "users", type_="check")
    op.drop_constraint("ck_users_daily_freeze_count_range", "users", type_="check")

    op.drop_column("users", "daily_last_qualifying_date")
    op.drop_column("users", "daily_freeze_count")
    op.drop_column("users", "daily_best_streak")
    op.drop_column("users", "daily_current_streak")


def _backfill_streaks(connection) -> None:
    """Synchronous backfill mirroring services.daily_streak_service.backfill_user.

    Duplicated rather than imported because Alembic migrations must remain
    pinned to the schema at this revision; the live service is allowed to
    evolve.
    """
    import json as _json
    from datetime import UTC as _UTC
    from datetime import date as _date
    from datetime import datetime as _datetime
    from datetime import timedelta as _timedelta

    from sqlalchemy import text

    FREEZE_CAP = 2
    FREEZE_PERIOD = 7
    DAILY_ROTATION_HOUR = 8

    def _today_rotation() -> _date:
        now = _datetime.now(_UTC)
        return (now - _timedelta(hours=DAILY_ROTATION_HOUR)).date()

    today = _today_rotation()

    user_ids = [
        row[0]
        for row in connection.execute(
            text(
                "SELECT DISTINCT p.user_id "
                "FROM participants p "
                "JOIN races r ON r.id = p.race_id "
                "WHERE r.daily_date IS NOT NULL"
            )
        )
    ]

    for user_id in user_ids:
        rows = list(
            connection.execute(
                text(
                    "SELECT r.daily_date, p.zone_history "
                    "FROM participants p "
                    "JOIN races r ON r.id = p.race_id "
                    "WHERE p.user_id = :uid AND r.daily_date IS NOT NULL "
                    "ORDER BY r.daily_date"
                ),
                {"uid": user_id},
            )
        )

        qualified: dict[_date, bool] = {}
        for daily_date_value, zone_history in rows:
            # SQLite returns JSON columns as strings; Postgres returns
            # the deserialized list. Normalize both shapes.
            if isinstance(zone_history, str):
                try:
                    zone_history = _json.loads(zone_history)
                except (ValueError, TypeError):
                    zone_history = None
            is_q = bool(zone_history) and len(zone_history) >= 2
            qualified[daily_date_value] = qualified.get(daily_date_value, False) or is_q

        if not qualified:
            continue

        earliest = min(qualified)
        latest_touched = max(qualified)
        end = max(latest_touched, today) if qualified.get(today, False) else latest_touched
        cursor = earliest
        current_streak = 0
        best_streak = 0
        freeze_count = 0
        last_qualifying: _date | None = None
        freeze_rows: list[_date] = []

        while cursor <= end:
            if qualified.get(cursor, False):
                current_streak += 1
                if current_streak > best_streak:
                    best_streak = current_streak
                if current_streak % FREEZE_PERIOD == 0 and freeze_count < FREEZE_CAP:
                    freeze_count += 1
                last_qualifying = cursor
            elif current_streak > 0:
                if freeze_count > 0:
                    freeze_count -= 1
                    freeze_rows.append(cursor)
                else:
                    current_streak = 0
            cursor = _date.fromordinal(cursor.toordinal() + 1)

        connection.execute(
            text(
                "UPDATE users SET "
                "daily_current_streak = :cs, "
                "daily_best_streak = :bs, "
                "daily_freeze_count = :fc, "
                "daily_last_qualifying_date = :ld "
                "WHERE id = :uid"
            ),
            {
                "cs": current_streak,
                "bs": best_streak,
                "fc": freeze_count,
                "ld": last_qualifying,
                "uid": user_id,
            },
        )
        for d in freeze_rows:
            connection.execute(
                text("INSERT INTO daily_streak_freezes (user_id, daily_date) VALUES (:uid, :d)"),
                {"uid": user_id, "d": d},
            )
