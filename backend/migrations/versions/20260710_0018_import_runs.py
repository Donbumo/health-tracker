"""Add persistent audit records for confirmed standard imports.

Revision ID: 20260710_0018
Revises: 20260705_0017
Create Date: 2026-07-10
"""

from alembic import op
import sqlalchemy as sa


revision = "20260710_0018"
down_revision = "20260705_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("insert_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("update_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skip_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("conflict_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("invalid_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("plan_sha256", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'blocked')",
            name="ck_import_runs_status",
        ),
        sa.CheckConstraint("target_type <> ''", name="ck_import_runs_target_type"),
        sa.CheckConstraint("total_count >= 0", name="ck_import_runs_total_count"),
        sa.CheckConstraint("insert_count >= 0", name="ck_import_runs_insert_count"),
        sa.CheckConstraint("update_count >= 0", name="ck_import_runs_update_count"),
        sa.CheckConstraint("skip_count >= 0", name="ck_import_runs_skip_count"),
        sa.CheckConstraint("conflict_count >= 0", name="ck_import_runs_conflict_count"),
        sa.CheckConstraint("invalid_count >= 0", name="ck_import_runs_invalid_count"),
        sa.CheckConstraint("LENGTH(payload_sha256) = 64", name="ck_import_runs_payload_sha"),
        sa.CheckConstraint("LENGTH(plan_sha256) = 64", name="ck_import_runs_plan_sha"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_runs_user_id", "import_runs", ["user_id"])
    op.create_index(
        "ix_import_runs_user_started",
        "import_runs",
        ["user_id", "started_at"],
    )
    op.create_index(
        "ix_import_runs_user_status",
        "import_runs",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_import_runs_user_target",
        "import_runs",
        ["user_id", "target_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_import_runs_user_target", table_name="import_runs")
    op.drop_index("ix_import_runs_user_status", table_name="import_runs")
    op.drop_index("ix_import_runs_user_started", table_name="import_runs")
    op.drop_index("ix_import_runs_user_id", table_name="import_runs")
    op.drop_table("import_runs")
