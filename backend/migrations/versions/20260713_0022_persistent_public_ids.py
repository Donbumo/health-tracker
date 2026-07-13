"""Add persistent public UUIDs for API domain entities.

Revision ID: 20260713_0022
Revises: 20260713_0021
"""
import uuid

from alembic import op
import sqlalchemy as sa

revision = "20260713_0022"
down_revision = "20260713_0021"
branch_labels = None
depends_on = None


def _backfill(table_name: str) -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text(f"SELECT id FROM {table_name}")).fetchall()
    for row in rows:
        connection.execute(
            sa.text(f"UPDATE {table_name} SET public_id = :public_id WHERE id = :id"),
            {"public_id": str(uuid.uuid4()), "id": row.id},
        )


def _add_public_id(table_name: str, constraint_name: str) -> None:
    op.add_column(table_name, sa.Column("public_id", sa.String(length=36), nullable=True))
    _backfill(table_name)
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column("public_id", existing_type=sa.String(length=36), nullable=False)
        batch_op.create_unique_constraint(constraint_name, ["public_id"])


def upgrade():
    _add_public_id("users", "uq_users_public_id")
    _add_public_id("training_plans", "uq_training_plans_public_id")
    _add_public_id("training_plan_versions", "uq_training_plan_versions_public_id")


def _drop_public_id(table_name: str, constraint_name: str) -> None:
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.drop_constraint(constraint_name, type_="unique")
        batch_op.drop_column("public_id")


def downgrade():
    _drop_public_id("training_plan_versions", "uq_training_plan_versions_public_id")
    _drop_public_id("training_plans", "uq_training_plans_public_id")
    _drop_public_id("users", "uq_users_public_id")
