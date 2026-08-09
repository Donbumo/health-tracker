"""Add public UUIDs to exercise identities and historical occurrences.

Revision ID: 20260724_0029
Revises: 20260717_0028
"""
import uuid

from alembic import op
import sqlalchemy as sa


revision = "20260724_0029"
down_revision = "20260717_0028"
branch_labels = None
depends_on = None


def _add_public_id(table: str, constraint: str) -> None:
    connection = op.get_bind()
    op.add_column(table, sa.Column("public_id", sa.String(length=36), nullable=True))
    rows = connection.execute(sa.text(f"SELECT id FROM {table}")).fetchall()
    for row in rows:
        connection.execute(
            sa.text(f"UPDATE {table} SET public_id=:public_id WHERE id=:id"),
            {"public_id": str(uuid.uuid4()), "id": row.id},
        )
    with op.batch_alter_table(table) as batch_op:
        batch_op.alter_column(
            "public_id", existing_type=sa.String(length=36), nullable=False
        )
        batch_op.create_unique_constraint(constraint, ["public_id"])


def upgrade() -> None:
    _add_public_id("exercises", "uq_exercises_public_id")
    _add_public_id(
        "training_session_exercises", "uq_training_session_exercises_public_id"
    )


def downgrade() -> None:
    with op.batch_alter_table("training_session_exercises") as batch_op:
        batch_op.drop_constraint(
            "uq_training_session_exercises_public_id", type_="unique"
        )
        batch_op.drop_column("public_id")
    with op.batch_alter_table("exercises") as batch_op:
        batch_op.drop_constraint("uq_exercises_public_id", type_="unique")
        batch_op.drop_column("public_id")
