"""Add food_products table for reusable user-owned food catalog.

Revision ID: 20260705_0014
Revises: 20260705_0013
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa


revision = "20260705_0014"
down_revision = "20260705_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "food_products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("brand", sa.String(length=200), nullable=True),
        sa.Column("serving_size_g", sa.Numeric(10, 3), nullable=True),
        sa.Column("serving_label", sa.String(length=64), nullable=True),
        sa.Column("calories_per_100g", sa.Numeric(10, 3), nullable=True),
        sa.Column("protein_g_per_100g", sa.Numeric(10, 3), nullable=True),
        sa.Column("fat_g_per_100g", sa.Numeric(10, 3), nullable=True),
        sa.Column("carbs_g_per_100g", sa.Numeric(10, 3), nullable=True),
        sa.Column("net_carbs_g_per_100g", sa.Numeric(10, 3), nullable=True),
        sa.Column("fiber_g_per_100g", sa.Numeric(10, 3), nullable=True),
        sa.Column("sodium_mg_per_100g", sa.Numeric(10, 3), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("1"),
            nullable=False,
        ),
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
            "calories_per_100g IS NULL OR calories_per_100g >= 0",
            name="ck_food_products_calories_per_100g",
        ),
        sa.CheckConstraint(
            "protein_g_per_100g IS NULL OR protein_g_per_100g >= 0",
            name="ck_food_products_protein_g_per_100g",
        ),
        sa.CheckConstraint(
            "fat_g_per_100g IS NULL OR fat_g_per_100g >= 0",
            name="ck_food_products_fat_g_per_100g",
        ),
        sa.CheckConstraint(
            "carbs_g_per_100g IS NULL OR carbs_g_per_100g >= 0",
            name="ck_food_products_carbs_g_per_100g",
        ),
        sa.CheckConstraint(
            "net_carbs_g_per_100g IS NULL OR net_carbs_g_per_100g >= 0",
            name="ck_food_products_net_carbs_g_per_100g",
        ),
        sa.CheckConstraint(
            "fiber_g_per_100g IS NULL OR fiber_g_per_100g >= 0",
            name="ck_food_products_fiber_g_per_100g",
        ),
        sa.CheckConstraint(
            "sodium_mg_per_100g IS NULL OR sodium_mg_per_100g >= 0",
            name="ck_food_products_sodium_mg_per_100g",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "name",
            "brand",
            name="uq_food_product_user_name_brand",
        ),
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_food_products_user_active",
        "food_products",
        ["user_id", "is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_food_products_user_active", table_name="food_products")
    op.drop_table("food_products")
