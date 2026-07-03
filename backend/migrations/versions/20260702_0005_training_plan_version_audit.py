"""Add training plan version author and change reason.

Revision ID: 20260702_0005
Revises: 20260701_0004
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260702_0005"
down_revision = "20260701_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("training_plan_versions") as batch_op:
        batch_op.add_column(
            sa.Column("created_by_user_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(sa.Column("change_reason", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            "fk_training_plan_versions_created_by_user_id_users",
            "users",
            ["created_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("training_plan_versions") as batch_op:
        batch_op.drop_constraint(
            "fk_training_plan_versions_created_by_user_id_users",
            type_="foreignkey",
        )
        batch_op.drop_column("change_reason")
        batch_op.drop_column("created_by_user_id")
