"""Add owner-scoped AI conversations, messages, tool audit and drafts.

Revision ID: 20260809_0037
Revises: 20260731_0036
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa


revision = "20260809_0037"
down_revision = "20260731_0036"
branch_labels = None
depends_on = None


def _timestamps():
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
    )


def upgrade() -> None:
    created_at, updated_at = _timestamps()
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        created_at,
        updated_at,
        sa.CheckConstraint(
            "status IN ('active','archived')", name="ck_ai_conversations_status"
        ),
        sa.UniqueConstraint("public_id", name="uq_ai_conversations_public_id"),
    )
    op.create_index(
        "ix_ai_conversations_user_updated",
        "ai_conversations",
        ["user_id", "updated_at", "id"],
    )

    op.create_table(
        "ai_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("ai_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("attachments_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('user','assistant')", name="ck_ai_messages_role"),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_ai_messages_input_tokens",
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_ai_messages_output_tokens",
        ),
        sa.UniqueConstraint("public_id", name="uq_ai_messages_public_id"),
    )
    op.create_index(
        "ix_ai_messages_conversation_created",
        "ai_messages",
        ["conversation_id", "created_at", "id"],
    )
    op.create_index(
        "ix_ai_messages_user_created", "ai_messages", ["user_id", "created_at"]
    )

    op.create_table(
        "ai_tool_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("ai_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "request_message_id",
            sa.Integer(),
            sa.ForeignKey("ai_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_call_id", sa.String(length=128), nullable=True),
        sa.Column("tool_name", sa.String(length=96), nullable=False),
        sa.Column("sanitized_arguments_json", sa.JSON(), nullable=False),
        sa.Column("result_summary_json", sa.JSON(), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('completed','failed','rejected')",
            name="ck_ai_tool_calls_status",
        ),
        sa.UniqueConstraint("public_id", name="uq_ai_tool_calls_public_id"),
    )
    op.create_index(
        "ix_ai_tool_calls_conversation_created",
        "ai_tool_calls",
        ["conversation_id", "created_at", "id"],
    )
    op.create_index(
        "ix_ai_tool_calls_user_created", "ai_tool_calls", ["user_id", "created_at"]
    )

    op.create_table(
        "ai_action_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("ai_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("ai_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("draft_type", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default="pending_confirmation",
            nullable=False,
        ),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "draft_type IN ('food_entry','body_measurement','workout_entry','steps_entry')",
            name="ck_ai_action_drafts_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending_confirmation','cancelled')",
            name="ck_ai_action_drafts_status",
        ),
        sa.UniqueConstraint("public_id", name="uq_ai_action_drafts_public_id"),
    )
    op.create_index(
        "ix_ai_action_drafts_user_status",
        "ai_action_drafts",
        ["user_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("ai_action_drafts")
    op.drop_table("ai_tool_calls")
    op.drop_table("ai_messages")
    op.drop_table("ai_conversations")
