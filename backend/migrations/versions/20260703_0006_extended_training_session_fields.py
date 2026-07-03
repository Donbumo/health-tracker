"""Add optional extended training session fields.

Revision ID: 20260703_0006
Revises: 20260702_0005
Create Date: 2026-07-03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260703_0006"
down_revision = "20260702_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("training_sessions") as batch_op:
        batch_op.add_column(sa.Column("duration_seconds", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("average_heart_rate_bpm", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("calories_burned", sa.Numeric(10, 2), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_training_sessions_duration",
            "duration_seconds IS NULL OR duration_seconds BETWEEN 1 AND 604800",
        )
        batch_op.create_check_constraint(
            "ck_training_sessions_average_heart_rate",
            "average_heart_rate_bpm IS NULL OR "
            "average_heart_rate_bpm BETWEEN 20 AND 250",
        )
        batch_op.create_check_constraint(
            "ck_training_sessions_calories",
            "calories_burned IS NULL OR calories_burned >= 0",
        )

    with op.batch_alter_table("training_sets") as batch_op:
        batch_op.add_column(sa.Column("rpe", sa.Numeric(4, 1), nullable=True))
        batch_op.add_column(sa.Column("rest_seconds", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            "ck_training_sets_rpe",
            "rpe IS NULL OR (rpe >= 1 AND rpe <= 10)",
        )
        batch_op.create_check_constraint(
            "ck_training_sets_rest_seconds",
            "rest_seconds IS NULL OR rest_seconds BETWEEN 0 AND 86400",
        )


def downgrade() -> None:
    with op.batch_alter_table("training_sets") as batch_op:
        batch_op.drop_constraint("ck_training_sets_rest_seconds", type_="check")
        batch_op.drop_constraint("ck_training_sets_rpe", type_="check")
        batch_op.drop_column("rest_seconds")
        batch_op.drop_column("rpe")

    with op.batch_alter_table("training_sessions") as batch_op:
        batch_op.drop_constraint("ck_training_sessions_calories", type_="check")
        batch_op.drop_constraint(
            "ck_training_sessions_average_heart_rate",
            type_="check",
        )
        batch_op.drop_constraint("ck_training_sessions_duration", type_="check")
        batch_op.drop_column("calories_burned")
        batch_op.drop_column("average_heart_rate_bpm")
        batch_op.drop_column("duration_seconds")
