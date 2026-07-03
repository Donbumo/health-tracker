"""Add import status metadata to uploaded files.

Revision ID: 20260704_0008
Revises: 20260704_0007
Create Date: 2026-07-04
"""

from alembic import op
import sqlalchemy as sa


revision = "20260704_0008"
down_revision = "20260704_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("uploaded_files") as batch_op:
        batch_op.add_column(
            sa.Column(
                "detected_type",
                sa.String(length=32),
                server_default="unknown",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "import_status",
                sa.String(length=20),
                server_default="pending",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("error_message", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "ck_uploaded_files_import_status",
            "import_status IN ('pending', 'imported', 'duplicate', 'error')",
        )


def downgrade() -> None:
    with op.batch_alter_table("uploaded_files") as batch_op:
        batch_op.drop_constraint(
            "ck_uploaded_files_import_status",
            type_="check",
        )
        batch_op.drop_column("error_message")
        batch_op.drop_column("import_status")
        batch_op.drop_column("detected_type")
