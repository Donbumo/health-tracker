"""Add food_product_id FK to nutrition_items table.

Revision ID: 20260705_0015
Revises: 20260704_0014
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa


revision = "20260705_0015"
down_revision = "20260705_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nutrition_items",
        sa.Column("food_product_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_nutrition_items_food_product",
        "nutrition_items",
        "food_products",
        ["food_product_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_nutrition_items_food_product", "nutrition_items", type_="foreignkey")
    op.drop_column("nutrition_items", "food_product_id")
