"""Add persistent daily energy records.

Revision ID: 20260704_0010
Revises: 20260704_0009
Create Date: 2026-07-04
"""

from alembic import op
import sqlalchemy as sa


revision = "20260704_0010"
down_revision = "20260704_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_energy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("total_calories", sa.Numeric(10, 2), nullable=True),
        sa.Column("active_calories", sa.Numeric(10, 2), nullable=True),
        sa.Column("resting_calories", sa.Numeric(10, 2), nullable=True),
        sa.Column("steps", sa.BigInteger(), nullable=True),
        sa.Column("distance_meters", sa.Numeric(12, 2), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_file_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("raw_payload_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "active_calories IS NULL OR active_calories >= 0",
            name="ck_daily_energy_active_calories",
        ),
        sa.CheckConstraint(
            "distance_meters IS NULL OR distance_meters >= 0",
            name="ck_daily_energy_distance",
        ),
        sa.CheckConstraint(
            "resting_calories IS NULL OR resting_calories >= 0",
            name="ck_daily_energy_resting_calories",
        ),
        sa.CheckConstraint(
            "steps IS NULL OR steps >= 0",
            name="ck_daily_energy_steps",
        ),
        sa.CheckConstraint(
            "total_calories IS NULL OR total_calories >= 0",
            name="ck_daily_energy_total_calories",
        ),
        sa.ForeignKeyConstraint(
            ["source_file_id"],
            ["uploaded_files.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_file_id",
            name="uq_daily_energy_source_file",
        ),
        sa.UniqueConstraint("user_id", "date", name="uq_daily_energy_user_date"),
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_daily_energy_user_date",
        "daily_energy",
        ["user_id", "date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_daily_energy_user_date", table_name="daily_energy")
    op.drop_table("daily_energy")
