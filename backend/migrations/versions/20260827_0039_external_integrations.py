"""Add the external integrations foundation.

Revision ID: 20260827_0039
Revises: 20260811_0038
Create Date: 2026-08-27
"""

from alembic import op
import sqlalchemy as sa


revision = "20260827_0039"
down_revision = "20260811_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_account_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=160)),
        sa.Column("display_metadata_json", sa.JSON(), nullable=False),
        sa.Column("scopes_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="connected", nullable=False),
        sa.Column("access_token_ciphertext", sa.Text()),
        sa.Column("refresh_token_ciphertext", sa.Text()),
        sa.Column("pending_revoke_token_ciphertext", sa.Text()),
        sa.Column("token_expires_at", sa.DateTime(timezone=True)),
        sa.Column("token_updated_at", sa.DateTime(timezone=True)),
        sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("disconnected_at", sa.DateTime(timezone=True)),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_sync_summary_json", sa.JSON(), nullable=False),
        sa.Column("last_rate_limit_json", sa.JSON(), nullable=False),
        sa.Column("last_error_code", sa.String(length=64)),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.CheckConstraint("status IN ('connected','disconnected','auth_error','sync_error')", name="ck_external_accounts_status"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("public_id", name="uq_external_accounts_public_id"),
        sa.UniqueConstraint("user_id", "provider", "provider_account_id", name="uq_external_accounts_user_provider_account"),
    )
    op.create_index("ix_external_accounts_user_provider", "external_accounts", ["user_id", "provider"])
    op.create_index("ix_external_accounts_provider_identity", "external_accounts", ["provider", "provider_account_id"])

    op.create_table(
        "external_sync_cursors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("external_account_id", sa.Integer(), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("cursor_at", sa.DateTime(timezone=True)),
        sa.Column("checkpoint_json", sa.JSON(), nullable=False),
        sa.Column("last_checkpoint_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["external_account_id"], ["external_accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("external_account_id", "resource_type", name="uq_external_sync_cursor_resource"),
    )
    op.create_index("ix_external_sync_cursors_user_account", "external_sync_cursors", ["user_id", "external_account_id"])

    op.create_table(
        "external_resources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("external_account_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("external_resource_id", sa.String(length=128), nullable=False),
        sa.Column("activity_id", sa.Integer()),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("payload_fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("provider_updated_at", sa.DateTime(timezone=True)),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.CheckConstraint("status IN ('active','deleted')", name="ck_external_resources_status"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["external_account_id"], ["external_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("public_id", name="uq_external_resources_public_id"),
        sa.UniqueConstraint("provider", "external_account_id", "resource_type", "external_resource_id", name="uq_external_resources_provider_account_resource"),
    )
    op.create_index("ix_external_resources_user_provider_type", "external_resources", ["user_id", "provider", "resource_type"])
    op.create_index("ix_external_resources_activity", "external_resources", ["user_id", "activity_id"])

    op.create_table(
        "external_import_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("external_account_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("event_key_sha256", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=32)),
        sa.Column("external_resource_id", sa.String(length=128)),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True)),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('pending','processing','completed','failed','ignored')", name="ck_external_import_events_status"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["external_account_id"], ["external_accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("public_id", name="uq_external_import_events_public_id"),
        sa.UniqueConstraint("provider", "external_account_id", "event_key_sha256", name="uq_external_import_events_provider_account_key"),
    )
    op.create_index("ix_external_import_events_pending", "external_import_events", ["status", "created_at"])
    op.create_index("ix_external_import_events_user_account", "external_import_events", ["user_id", "external_account_id"])


def downgrade() -> None:
    op.drop_table("external_import_events")
    op.drop_table("external_resources")
    op.drop_table("external_sync_cursors")
    op.drop_table("external_accounts")
