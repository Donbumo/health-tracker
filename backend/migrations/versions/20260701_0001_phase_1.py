"""Create Phase 1 user and uploaded file tables.

Revision ID: 20260701_0001
Revises:
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260701_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.String(length=20),
            server_default="user",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('admin', 'user')", name="ck_users_role"),
        sa.PrimaryKeyConstraint("id"),
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "uploaded_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "sha256",
            name="uq_uploaded_files_user_sha256",
        ),
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_uploaded_files_user_created",
        "uploaded_files",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_uploaded_files_user_created", table_name="uploaded_files")
    op.drop_table("uploaded_files")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
