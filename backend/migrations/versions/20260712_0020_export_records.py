"""Add persisted export artifact records.

Revision ID: 20260712_0020
Revises: 20260711_0019
Create Date: 2026-07-12
"""

from alembic import op
import sqlalchemy as sa


revision = "20260712_0020"
down_revision = "20260711_0019"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "export_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("exporter_version", sa.String(length=20), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("relative_path", sa.String(length=512), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="ready", nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('ready', 'deleted', 'expired')",
            name="ck_export_records_status",
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_export_records_size"),
        sa.UniqueConstraint("relative_path", name="uq_export_records_relative_path"),
    )
    op.create_index(
        "ix_export_records_user_created",
        "export_records",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_export_records_user_domain",
        "export_records",
        ["user_id", "domain"],
    )
    op.create_index(
        "ix_export_records_user_status",
        "export_records",
        ["user_id", "status"],
    )


def downgrade():
    op.drop_index("ix_export_records_user_status", table_name="export_records")
    op.drop_index("ix_export_records_user_domain", table_name="export_records")
    op.drop_index("ix_export_records_user_created", table_name="export_records")
    op.drop_table("export_records")
