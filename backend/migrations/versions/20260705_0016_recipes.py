"""Add recipes and recipe ingredients.

Revision ID: 20260705_0016
Revises: 20260705_0015
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa


revision = "20260705_0016"
down_revision = "20260705_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recipes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("servings", sa.Numeric(10, 3), server_default="1", nullable=False),
        sa.Column("yield_weight_g", sa.Numeric(12, 3), nullable=True),
        sa.Column("source", sa.String(length=32), server_default="manual", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("raw_payload_json", sa.JSON(), nullable=True),
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
        sa.CheckConstraint("servings > 0", name="ck_recipes_servings_positive"),
        sa.CheckConstraint(
            "yield_weight_g IS NULL OR yield_weight_g > 0",
            name="ck_recipes_yield_weight_positive",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_recipes_user_name"),
    )
    op.create_index("ix_recipes_user_active", "recipes", ["user_id", "is_active"])

    op.create_table(
        "recipe_ingredients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("food_product_id", sa.Integer(), nullable=True),
        sa.Column("name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("brand_snapshot", sa.String(length=200), nullable=True),
        sa.Column("quantity_g", sa.Numeric(12, 3), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("calories_per_100g", sa.Numeric(10, 3), nullable=True),
        sa.Column("protein_g_per_100g", sa.Numeric(10, 3), nullable=True),
        sa.Column("fat_g_per_100g", sa.Numeric(10, 3), nullable=True),
        sa.Column("carbs_g_per_100g", sa.Numeric(10, 3), nullable=True),
        sa.Column("net_carbs_g_per_100g", sa.Numeric(10, 3), nullable=True),
        sa.Column("fiber_g_per_100g", sa.Numeric(10, 3), nullable=True),
        sa.Column("sodium_mg_per_100g", sa.Numeric(10, 3), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "calories_per_100g IS NULL OR calories_per_100g >= 0",
            name="ck_recipe_ingredients_calories_per_100g",
        ),
        sa.CheckConstraint(
            "protein_g_per_100g IS NULL OR protein_g_per_100g >= 0",
            name="ck_recipe_ingredients_protein_g_per_100g",
        ),
        sa.CheckConstraint(
            "fat_g_per_100g IS NULL OR fat_g_per_100g >= 0",
            name="ck_recipe_ingredients_fat_g_per_100g",
        ),
        sa.CheckConstraint(
            "carbs_g_per_100g IS NULL OR carbs_g_per_100g >= 0",
            name="ck_recipe_ingredients_carbs_g_per_100g",
        ),
        sa.CheckConstraint(
            "net_carbs_g_per_100g IS NULL OR net_carbs_g_per_100g >= 0",
            name="ck_recipe_ingredients_net_carbs_g_per_100g",
        ),
        sa.CheckConstraint(
            "fiber_g_per_100g IS NULL OR fiber_g_per_100g >= 0",
            name="ck_recipe_ingredients_fiber_g_per_100g",
        ),
        sa.CheckConstraint(
            "sodium_mg_per_100g IS NULL OR sodium_mg_per_100g >= 0",
            name="ck_recipe_ingredients_sodium_mg_per_100g",
        ),
        sa.CheckConstraint(
            "quantity_g > 0",
            name="ck_recipe_ingredients_quantity",
        ),
        sa.CheckConstraint(
            "sort_order >= 1",
            name="ck_recipe_ingredients_sort_order",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["food_product_id"],
            ["food_products.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recipe_id",
            "sort_order",
            name="uq_recipe_ingredients_recipe_order",
        ),
    )
    op.create_index(
        "ix_recipe_ingredients_user_recipe",
        "recipe_ingredients",
        ["user_id", "recipe_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_recipe_ingredients_user_recipe", table_name="recipe_ingredients")
    op.drop_table("recipe_ingredients")
    op.drop_index("ix_recipes_user_active", table_name="recipes")
    op.drop_table("recipes")