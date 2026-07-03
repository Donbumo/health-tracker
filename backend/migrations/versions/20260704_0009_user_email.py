"""Add optional user email for admin-created accounts.

Revision ID: 20260704_0009
Revises: 20260704_0008
Create Date: 2026-07-04
"""

from alembic import op
import sqlalchemy as sa


revision = "20260704_0009"
down_revision = "20260704_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "username",
            existing_type=sa.String(length=80),
            type_=sa.String(length=254),
            existing_nullable=False,
        )
        batch_op.add_column(sa.Column("email", sa.String(length=254), nullable=True))
        batch_op.create_index("ix_users_email", ["email"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_email")
        batch_op.drop_column("email")
        batch_op.alter_column(
            "username",
            existing_type=sa.String(length=254),
            type_=sa.String(length=80),
            existing_nullable=False,
        )
