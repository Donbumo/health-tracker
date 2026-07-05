"""Add recipe_id FK to nutrition_items table.

Revision ID: 20260705_0017
Revises: 20260705_0016
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa


revision = "20260705_0017"
down_revision = "20260705_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nutrition_items",
        sa.Column("recipe_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_nutrition_items_recipe",
        "nutrition_items",
        "recipes",
        ["recipe_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_nutrition_items_recipe", "nutrition_items", type_="foreignkey")
    op.drop_column("nutrition_items", "recipe_id")