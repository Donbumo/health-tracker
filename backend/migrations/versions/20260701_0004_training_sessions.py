"""Create completed training session tables.

Revision ID: 20260701_0004
Revises: 20260701_0003
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260701_0004"
down_revision = "20260701_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "training_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("training_plan_id", sa.Integer(), nullable=False),
        sa.Column("training_plan_version_id", sa.Integer(), nullable=False),
        sa.Column("source_file_id", sa.Integer(), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("planned_week_number", sa.Integer(), nullable=False),
        sa.Column("planned_day_number", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "planned_day_number BETWEEN 1 AND 7",
            name="ck_training_sessions_day_number",
        ),
        sa.CheckConstraint(
            "planned_week_number >= 1",
            name="ck_training_sessions_week_number",
        ),
        sa.ForeignKeyConstraint(
            ["source_file_id"],
            ["uploaded_files.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["training_plan_id"],
            ["training_plans.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["training_plan_version_id"],
            ["training_plan_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_file_id", name="uq_training_sessions_source_file"),
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_training_sessions_user_performed",
        "training_sessions",
        ["user_id", "performed_at"],
        unique=False,
    )

    op.create_table(
        "training_session_exercises",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("training_session_id", sa.Integer(), nullable=False),
        sa.Column("exercise_order", sa.Integer(), nullable=False),
        sa.Column("planned_exercise_order", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "exercise_order >= 1",
            name="ck_training_session_exercises_order",
        ),
        sa.CheckConstraint(
            "planned_exercise_order >= 1",
            name="ck_training_session_exercises_planned_order",
        ),
        sa.ForeignKeyConstraint(
            ["training_session_id"],
            ["training_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "training_session_id",
            "exercise_order",
            name="uq_training_session_exercises_session_order",
        ),
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_training_session_exercises_user_session",
        "training_session_exercises",
        ["user_id", "training_session_id"],
        unique=False,
    )

    op.create_table(
        "training_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("training_session_exercise_id", sa.Integer(), nullable=False),
        sa.Column("set_number", sa.Integer(), nullable=False),
        sa.Column("planned_set_number", sa.Integer(), nullable=False),
        sa.Column("weight_kg", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("rir", sa.Numeric(precision=4, scale=1), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint("reps >= 1", name="ck_training_sets_reps"),
        sa.CheckConstraint(
            "rir IS NULL OR (rir >= 0 AND rir <= 10)",
            name="ck_training_sets_rir",
        ),
        sa.CheckConstraint("set_number >= 1", name="ck_training_sets_number"),
        sa.CheckConstraint(
            "planned_set_number >= 1",
            name="ck_training_sets_planned_number",
        ),
        sa.CheckConstraint("weight_kg >= 0", name="ck_training_sets_weight"),
        sa.ForeignKeyConstraint(
            ["training_session_exercise_id"],
            ["training_session_exercises.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "training_session_exercise_id",
            "set_number",
            name="uq_training_sets_exercise_number",
        ),
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_training_sets_user_exercise",
        "training_sets",
        ["user_id", "training_session_exercise_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_training_sets_user_exercise", table_name="training_sets")
    op.drop_table("training_sets")
    op.drop_index(
        "ix_training_session_exercises_user_session",
        table_name="training_session_exercises",
    )
    op.drop_table("training_session_exercises")
    op.drop_index(
        "ix_training_sessions_user_performed",
        table_name="training_sessions",
    )
    op.drop_table("training_sessions")
