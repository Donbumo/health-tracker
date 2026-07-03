"""Add persistent daily nutrition, meals, and items.

Revision ID: 20260704_0011
Revises: 20260704_0010
Create Date: 2026-07-04
"""

from alembic import op
import sqlalchemy as sa


revision = "20260704_0011"
down_revision = "20260704_0010"
branch_labels = None
depends_on = None


METRICS = (
    "calories",
    "protein_g",
    "fat_g",
    "net_carbs_g",
    "total_carbs_g",
    "fiber_g",
    "sugar_g",
    "sodium_mg",
)


def _metric_columns() -> list[sa.Column]:
    return [sa.Column(name, sa.Numeric(12, 3), nullable=True) for name in METRICS]


def _metric_constraints(prefix: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint(
            f"{name} IS NULL OR {name} >= 0",
            name=f"ck_{prefix}_{name}",
        )
        for name in METRICS
    ]


def upgrade() -> None:
    op.create_table(
        "daily_nutrition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_file_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_metric_columns(),
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
        *_metric_constraints("daily_nutrition"),
        sa.ForeignKeyConstraint(
            ["source_file_id"],
            ["uploaded_files.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_file_id",
            name="uq_daily_nutrition_source_file",
        ),
        sa.UniqueConstraint(
            "user_id",
            "date",
            name="uq_daily_nutrition_user_date",
        ),
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_daily_nutrition_user_date",
        "daily_nutrition",
        ["user_id", "date"],
        unique=False,
    )

    op.create_table(
        "nutrition_meals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("daily_nutrition_id", sa.Integer(), nullable=False),
        sa.Column("meal_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "sort_order >= 1",
            name="ck_nutrition_meals_sort_order",
        ),
        sa.ForeignKeyConstraint(
            ["daily_nutrition_id"],
            ["daily_nutrition.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "daily_nutrition_id",
            "sort_order",
            name="uq_nutrition_meals_day_order",
        ),
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_nutrition_meals_user_day",
        "nutrition_meals",
        ["user_id", "daily_nutrition_id"],
        unique=False,
    )

    op.create_table(
        "nutrition_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("nutrition_meal_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        *_metric_columns(),
        sa.Column("notes", sa.Text(), nullable=True),
        *_metric_constraints("nutrition_items"),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity >= 0",
            name="ck_nutrition_items_quantity",
        ),
        sa.CheckConstraint(
            "sort_order >= 1",
            name="ck_nutrition_items_sort_order",
        ),
        sa.ForeignKeyConstraint(
            ["nutrition_meal_id"],
            ["nutrition_meals.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "nutrition_meal_id",
            "sort_order",
            name="uq_nutrition_items_meal_order",
        ),
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_nutrition_items_user_meal",
        "nutrition_items",
        ["user_id", "nutrition_meal_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_nutrition_items_user_meal", table_name="nutrition_items")
    op.drop_table("nutrition_items")
    op.drop_index("ix_nutrition_meals_user_day", table_name="nutrition_meals")
    op.drop_table("nutrition_meals")
    op.drop_index("ix_daily_nutrition_user_date", table_name="daily_nutrition")
    op.drop_table("daily_nutrition")
