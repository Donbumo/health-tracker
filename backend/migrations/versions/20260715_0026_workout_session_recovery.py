"""Add recoverable workout drafts and web submission idempotency.

Revision ID: 20260715_0026
Revises: 20260714_0025
"""
from alembic import op
import sqlalchemy as sa


revision = "20260715_0026"
down_revision = "20260714_0025"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("training_sessions") as batch_op:
        batch_op.add_column(
            sa.Column("client_submission_id", sa.String(36), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uq_training_sessions_user_submission",
            ["user_id", "client_submission_id"],
        )

    op.create_table(
        "workout_session_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "training_plan_id",
            sa.Integer(),
            sa.ForeignKey("training_plans.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "training_plan_version_id",
            sa.Integer(),
            sa.ForeignKey("training_plan_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "planned_workout_id",
            sa.Integer(),
            sa.ForeignKey("planned_workouts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("planned_week_number", sa.Integer(), nullable=True),
        sa.Column("planned_day_number", sa.Integer(), nullable=True),
        sa.Column("client_submission_id", sa.String(36), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(20), server_default="1.0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_saved_from_device_id",
            sa.Integer(),
            sa.ForeignKey("api_devices.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "revision >= 1", name="ck_workout_session_drafts_revision"
        ),
        sa.CheckConstraint(
            "planned_week_number IS NULL OR planned_week_number >= 1",
            name="ck_workout_session_drafts_week",
        ),
        sa.CheckConstraint(
            "planned_day_number IS NULL OR planned_day_number BETWEEN 1 AND 7",
            name="ck_workout_session_drafts_day",
        ),
        sa.UniqueConstraint(
            "public_id", name="uq_workout_session_drafts_public_id"
        ),
        sa.UniqueConstraint(
            "user_id",
            "client_submission_id",
            name="uq_workout_session_drafts_user_submission",
        ),
    )
    op.create_index(
        "ix_workout_session_drafts_user_version",
        "workout_session_drafts",
        ["user_id", "training_plan_version_id", "updated_at"],
    )
    op.create_index(
        "ix_workout_session_drafts_user_planned",
        "workout_session_drafts",
        ["user_id", "planned_workout_id"],
    )
    op.create_index(
        "ix_workout_session_drafts_expires",
        "workout_session_drafts",
        ["expires_at"],
    )


def downgrade():
    op.drop_table("workout_session_drafts")
    with op.batch_alter_table("training_sessions") as batch_op:
        batch_op.drop_constraint(
            "uq_training_sessions_user_submission", type_="unique"
        )
        batch_op.drop_column("client_submission_id")
