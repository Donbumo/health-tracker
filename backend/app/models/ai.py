from datetime import datetime, timezone
import uuid

from app.extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AIConversation(db.Model):
    __tablename__ = "ai_conversations"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('active','archived')", name="ck_ai_conversations_status"
        ),
        db.UniqueConstraint("public_id", name="uq_ai_conversations_public_id"),
        db.Index(
            "ix_ai_conversations_user_updated", "user_id", "updated_at", "id"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(
        db.String(36), nullable=False, default=lambda: str(uuid.uuid4())
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title = db.Column(db.String(160), nullable=False, default="Nueva conversación")
    status = db.Column(
        db.String(16), nullable=False, default="active", server_default="active"
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=db.func.current_timestamp(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=db.func.current_timestamp(),
    )

    user = db.relationship("User", back_populates="ai_conversations")
    messages = db.relationship(
        "AIMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AIMessage.id",
    )
    tool_calls = db.relationship(
        "AIToolCall",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AIToolCall.id",
    )
    drafts = db.relationship(
        "AIActionDraft",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AIActionDraft.id",
    )


class AIMessage(db.Model):
    __tablename__ = "ai_messages"
    __table_args__ = (
        db.CheckConstraint(
            "role IN ('user','assistant')", name="ck_ai_messages_role"
        ),
        db.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_ai_messages_input_tokens",
        ),
        db.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_ai_messages_output_tokens",
        ),
        db.UniqueConstraint("public_id", name="uq_ai_messages_public_id"),
        db.Index(
            "ix_ai_messages_conversation_created",
            "conversation_id",
            "created_at",
            "id",
        ),
        db.Index("ix_ai_messages_user_created", "user_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(
        db.String(36), nullable=False, default=lambda: str(uuid.uuid4())
    )
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role = db.Column(db.String(16), nullable=False)
    content = db.Column(db.Text, nullable=False)
    attachments_json = db.Column(db.JSON, nullable=False, default=list)
    evidence_json = db.Column(db.JSON, nullable=False, default=list)
    provider = db.Column(db.String(64), nullable=True)
    model = db.Column(db.String(128), nullable=True)
    input_tokens = db.Column(db.Integer, nullable=True)
    output_tokens = db.Column(db.Integer, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=db.func.current_timestamp(),
    )

    conversation = db.relationship("AIConversation", back_populates="messages")
    requested_tool_calls = db.relationship(
        "AIToolCall",
        back_populates="request_message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AIToolCall.id",
    )
    drafts = db.relationship(
        "AIActionDraft",
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AIActionDraft.id",
    )


class AIToolCall(db.Model):
    __tablename__ = "ai_tool_calls"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('completed','failed','rejected')",
            name="ck_ai_tool_calls_status",
        ),
        db.UniqueConstraint("public_id", name="uq_ai_tool_calls_public_id"),
        db.Index(
            "ix_ai_tool_calls_conversation_created",
            "conversation_id",
            "created_at",
            "id",
        ),
        db.Index("ix_ai_tool_calls_user_created", "user_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(
        db.String(36), nullable=False, default=lambda: str(uuid.uuid4())
    )
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    request_message_id = db.Column(
        db.Integer,
        db.ForeignKey("ai_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider_call_id = db.Column(db.String(128), nullable=True)
    tool_name = db.Column(db.String(96), nullable=False)
    sanitized_arguments_json = db.Column(db.JSON, nullable=False, default=dict)
    result_summary_json = db.Column(db.JSON, nullable=True)
    evidence_json = db.Column(db.JSON, nullable=False, default=list)
    status = db.Column(db.String(16), nullable=False)
    error_code = db.Column(db.String(64), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=db.func.current_timestamp(),
    )
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    conversation = db.relationship("AIConversation", back_populates="tool_calls")
    request_message = db.relationship(
        "AIMessage", back_populates="requested_tool_calls"
    )


class AIActionDraft(db.Model):
    __tablename__ = "ai_action_drafts"
    __table_args__ = (
        db.CheckConstraint(
            "draft_type IN ('food_entry','body_measurement','workout_entry','steps_entry','capability_action')",
            name="ck_ai_action_drafts_type",
        ),
        db.CheckConstraint(
            "status IN ('pending_confirmation','applied','rejected','expired','failed')",
            name="ck_ai_action_drafts_status",
        ),
        db.UniqueConstraint("public_id", name="uq_ai_action_drafts_public_id"),
        db.Index(
            "ix_ai_action_drafts_user_status",
            "user_id",
            "status",
            "created_at",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(
        db.String(36), nullable=False, default=lambda: str(uuid.uuid4())
    )
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey("ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_id = db.Column(
        db.Integer,
        db.ForeignKey("ai_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    draft_type = db.Column(db.String(32), nullable=False)
    payload_json = db.Column(db.JSON, nullable=False)
    status = db.Column(
        db.String(24),
        nullable=False,
        default="pending_confirmation",
        server_default="pending_confirmation",
    )
    provenance_json = db.Column(db.JSON, nullable=False, default=dict)
    applied_resource_type = db.Column(db.String(32), nullable=True)
    applied_resource_public_ids_json = db.Column(db.JSON, nullable=False, default=list)
    error_code = db.Column(db.String(64), nullable=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    applied_at = db.Column(db.DateTime(timezone=True), nullable=True)
    rejected_at = db.Column(db.DateTime(timezone=True), nullable=True)
    failed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=db.func.current_timestamp(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=db.func.current_timestamp(),
    )

    conversation = db.relationship("AIConversation", back_populates="drafts")
    message = db.relationship("AIMessage", back_populates="drafts")
