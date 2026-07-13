"""Add API device sessions and refresh tokens.

Revision ID: 20260713_0021
Revises: 20260712_0020
"""
from alembic import op
import sqlalchemy as sa

revision = "20260713_0021"
down_revision = "20260712_0020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "api_devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("public_device_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("platform", sa.String(20), server_default="unknown", nullable=False),
        sa.Column("app_version", sa.String(40)),
        sa.Column("os_version", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("platform IN ('android', 'ios', 'watch', 'unknown')", name="ck_api_devices_platform"),
        sa.UniqueConstraint("user_id", "public_device_id", name="uq_api_device_user_public"),
    )
    op.create_index("ix_api_devices_user_last_seen", "api_devices", ["user_id", "last_seen_at"])
    op.create_table(
        "api_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("api_devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("public_session_id", sa.String(36), nullable=False),
        sa.Column("token_family_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoke_reason", sa.String(64)),
        sa.UniqueConstraint("public_session_id", name="uq_api_sessions_public"),
        sa.UniqueConstraint("token_family_id", name="uq_api_sessions_family"),
    )
    op.create_index("ix_api_sessions_user_active", "api_sessions", ["user_id", "revoked_at", "expires_at"])
    op.create_index("ix_api_sessions_device", "api_sessions", ["device_id", "created_at"])
    op.create_table(
        "api_refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("api_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("public_token_id", sa.String(36), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("replaced_by_id", sa.Integer(), sa.ForeignKey("api_refresh_tokens.id", ondelete="SET NULL")),
        sa.Column("reuse_detected_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("public_token_id", name="uq_api_refresh_public"),
        sa.UniqueConstraint("token_hash", name="uq_api_refresh_hash"),
    )
    op.create_index("ix_api_refresh_session_created", "api_refresh_tokens", ["session_id", "created_at"])
    op.create_index("ix_api_refresh_expiry", "api_refresh_tokens", ["expires_at"])


def downgrade():
    op.drop_table("api_refresh_tokens")
    op.drop_table("api_sessions")
    op.drop_table("api_devices")
