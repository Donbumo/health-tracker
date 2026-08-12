"""Add remote AI consent and idempotent draft application metadata.

Revision ID: 20260811_0038
Revises: 20260809_0037
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa


revision = "20260811_0038"
down_revision = "20260809_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "ai_remote_consent_enabled",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column("ai_remote_consent_updated_at", sa.DateTime(timezone=True))
        )

    with op.batch_alter_table("ai_action_drafts") as batch:
        batch.drop_constraint("ck_ai_action_drafts_status", type_="check")
        batch.add_column(sa.Column("applied_resource_type", sa.String(length=32)))
        batch.add_column(
            sa.Column(
                "applied_resource_public_ids_json",
                sa.JSON(),
                server_default="[]",
                nullable=False,
            )
        )
        batch.add_column(sa.Column("error_code", sa.String(length=64)))
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("applied_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("rejected_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("failed_at", sa.DateTime(timezone=True)))
    op.execute(
        sa.text(
            "UPDATE ai_action_drafts SET status = 'rejected' "
            "WHERE status = 'cancelled'"
        )
    )
    with op.batch_alter_table("ai_action_drafts") as batch:
        batch.create_check_constraint(
            "ck_ai_action_drafts_status",
            "status IN ('pending_confirmation','applied','rejected','expired','failed')",
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_action_drafts") as batch:
        batch.drop_constraint("ck_ai_action_drafts_status", type_="check")
    op.execute(
        sa.text(
            "UPDATE ai_action_drafts SET status = 'cancelled' "
            "WHERE status <> 'pending_confirmation'"
        )
    )
    with op.batch_alter_table("ai_action_drafts") as batch:
        batch.drop_column("failed_at")
        batch.drop_column("rejected_at")
        batch.drop_column("applied_at")
        batch.drop_column("expires_at")
        batch.drop_column("error_code")
        batch.drop_column("applied_resource_public_ids_json")
        batch.drop_column("applied_resource_type")
        batch.create_check_constraint(
            "ck_ai_action_drafts_status",
            "status IN ('pending_confirmation','cancelled')",
        )

    with op.batch_alter_table("users") as batch:
        batch.drop_column("ai_remote_consent_updated_at")
        batch.drop_column("ai_remote_consent_enabled")
