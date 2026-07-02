"""Add uploaded file source type.

Revision ID: 20260701_0002
Revises: 20260701_0001
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260701_0002"
down_revision = "20260701_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("uploaded_files") as batch_op:
        batch_op.alter_column(
            "stored_filename",
            existing_type=sa.String(length=64),
            type_=sa.String(length=255),
            existing_nullable=False,
        )
        batch_op.add_column(
            sa.Column(
                "source_type",
                sa.String(length=32),
                server_default="uploaded",
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("uploaded_files") as batch_op:
        batch_op.drop_column("source_type")
        batch_op.alter_column(
            "stored_filename",
            existing_type=sa.String(length=255),
            type_=sa.String(length=64),
            existing_nullable=False,
        )
