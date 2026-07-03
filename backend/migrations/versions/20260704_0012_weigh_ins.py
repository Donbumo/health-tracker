"""Add persistent weigh-ins and body composition.

Revision ID: 20260704_0012
Revises: 20260704_0011
Create Date: 2026-07-04
"""

from alembic import op
import sqlalchemy as sa


revision = "20260704_0012"
down_revision = "20260704_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weigh_ins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("weight_kg", sa.Numeric(8, 3), nullable=False),
        sa.Column("body_fat_percentage", sa.Numeric(6, 3), nullable=True),
        sa.Column("muscle_mass_kg", sa.Numeric(8, 3), nullable=True),
        sa.Column("water_percentage", sa.Numeric(6, 3), nullable=True),
        sa.Column("visceral_fat", sa.Numeric(8, 3), nullable=True),
        sa.Column("bmr_kcal", sa.Numeric(10, 2), nullable=True),
        sa.Column("bmi", sa.Numeric(6, 3), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_file_id", sa.Integer(), nullable=True),
        sa.Column("raw_payload_json", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.CheckConstraint("weight_kg > 0", name="ck_weigh_ins_weight"),
        sa.CheckConstraint(
            "body_fat_percentage IS NULL OR "
            "(body_fat_percentage >= 0 AND body_fat_percentage <= 100)",
            name="ck_weigh_ins_body_fat_percentage",
        ),
        sa.CheckConstraint(
            "muscle_mass_kg IS NULL OR muscle_mass_kg >= 0",
            name="ck_weigh_ins_muscle_mass",
        ),
        sa.CheckConstraint(
            "water_percentage IS NULL OR "
            "(water_percentage >= 0 AND water_percentage <= 100)",
            name="ck_weigh_ins_water_percentage",
        ),
        sa.CheckConstraint(
            "visceral_fat IS NULL OR visceral_fat >= 0",
            name="ck_weigh_ins_visceral_fat",
        ),
        sa.CheckConstraint(
            "bmr_kcal IS NULL OR bmr_kcal >= 0",
            name="ck_weigh_ins_bmr",
        ),
        sa.CheckConstraint("bmi IS NULL OR bmi >= 0", name="ck_weigh_ins_bmi"),
        sa.ForeignKeyConstraint(
            ["source_file_id"],
            ["uploaded_files.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_file_id",
            name="uq_weigh_ins_source_file",
        ),
        sa.UniqueConstraint(
            "user_id",
            "recorded_at",
            name="uq_weigh_ins_user_recorded_at",
        ),
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_weigh_ins_user_recorded",
        "weigh_ins",
        ["user_id", "recorded_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_weigh_ins_user_recorded", table_name="weigh_ins")
    op.drop_table("weigh_ins")
