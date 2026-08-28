from datetime import datetime, timezone
import uuid

from app.extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExternalAccount(db.Model):
    __tablename__ = "external_accounts"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('connected','disconnected','auth_error','sync_error')",
            name="ck_external_accounts_status",
        ),
        db.UniqueConstraint(
            "user_id",
            "provider",
            "provider_account_id",
            name="uq_external_accounts_user_provider_account",
        ),
        db.Index("ix_external_accounts_user_provider", "user_id", "provider"),
        db.Index("ix_external_accounts_provider_identity", "provider", "provider_account_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(
        db.String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4())
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider = db.Column(db.String(32), nullable=False)
    provider_account_id = db.Column(db.String(128), nullable=False)
    display_name = db.Column(db.String(160), nullable=True)
    display_metadata_json = db.Column(db.JSON, nullable=False, default=dict)
    scopes_json = db.Column(db.JSON, nullable=False, default=list)
    status = db.Column(
        db.String(24), nullable=False, default="connected", server_default="connected"
    )
    access_token_ciphertext = db.Column(db.Text, nullable=True)
    refresh_token_ciphertext = db.Column(db.Text, nullable=True)
    pending_revoke_token_ciphertext = db.Column(db.Text, nullable=True)
    token_expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    token_updated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    connected_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow, server_default=db.func.current_timestamp()
    )
    disconnected_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_sync_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_success_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_sync_summary_json = db.Column(db.JSON, nullable=False, default=dict)
    last_rate_limit_json = db.Column(db.JSON, nullable=False, default=dict)
    last_error_code = db.Column(db.String(64), nullable=True)
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow, server_default=db.func.current_timestamp()
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow,
        onupdate=_utcnow, server_default=db.func.current_timestamp()
    )

    user = db.relationship("User", back_populates="external_accounts")
    sync_cursors = db.relationship(
        "ExternalSyncCursor", back_populates="account", cascade="all, delete-orphan",
    )
    resources = db.relationship(
        "ExternalResource", back_populates="account", cascade="all, delete-orphan",
    )
    import_events = db.relationship(
        "ExternalImportEvent", back_populates="account", cascade="all, delete-orphan",
    )


class ExternalSyncCursor(db.Model):
    __tablename__ = "external_sync_cursors"
    __table_args__ = (
        db.UniqueConstraint(
            "external_account_id", "resource_type", name="uq_external_sync_cursor_resource"
        ),
        db.Index("ix_external_sync_cursors_user_account", "user_id", "external_account_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    external_account_id = db.Column(
        db.Integer, db.ForeignKey("external_accounts.id", ondelete="CASCADE"), nullable=False
    )
    resource_type = db.Column(db.String(32), nullable=False)
    cursor_at = db.Column(db.DateTime(timezone=True), nullable=True)
    checkpoint_json = db.Column(db.JSON, nullable=False, default=dict)
    last_checkpoint_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow, server_default=db.func.current_timestamp()
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow,
        onupdate=_utcnow, server_default=db.func.current_timestamp()
    )

    account = db.relationship("ExternalAccount", back_populates="sync_cursors")


class ExternalResource(db.Model):
    __tablename__ = "external_resources"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('active','deleted')", name="ck_external_resources_status"
        ),
        db.UniqueConstraint(
            "provider",
            "external_account_id",
            "resource_type",
            "external_resource_id",
            name="uq_external_resources_provider_account_resource",
        ),
        db.Index(
            "ix_external_resources_user_provider_type",
            "user_id",
            "provider",
            "resource_type",
        ),
        db.Index("ix_external_resources_activity", "user_id", "activity_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(
        db.String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4())
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    external_account_id = db.Column(
        db.Integer, db.ForeignKey("external_accounts.id", ondelete="CASCADE"), nullable=False
    )
    provider = db.Column(db.String(32), nullable=False)
    resource_type = db.Column(db.String(32), nullable=False)
    external_resource_id = db.Column(db.String(128), nullable=False)
    activity_id = db.Column(
        db.Integer, db.ForeignKey("activities.id", ondelete="SET NULL"), nullable=True
    )
    status = db.Column(
        db.String(16), nullable=False, default="active", server_default="active"
    )
    payload_fingerprint_sha256 = db.Column(db.String(64), nullable=False)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)
    provider_updated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    imported_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow, server_default=db.func.current_timestamp()
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow,
        onupdate=_utcnow, server_default=db.func.current_timestamp()
    )

    account = db.relationship("ExternalAccount", back_populates="resources")
    activity = db.relationship("Activity")


class ExternalImportEvent(db.Model):
    __tablename__ = "external_import_events"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('pending','processing','completed','failed','ignored')",
            name="ck_external_import_events_status",
        ),
        db.UniqueConstraint(
            "provider", "external_account_id", "event_key_sha256",
            name="uq_external_import_events_provider_account_key",
        ),
        db.Index("ix_external_import_events_pending", "status", "created_at"),
        db.Index("ix_external_import_events_user_account", "user_id", "external_account_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(
        db.String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4())
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    external_account_id = db.Column(
        db.Integer, db.ForeignKey("external_accounts.id", ondelete="CASCADE"), nullable=False
    )
    provider = db.Column(db.String(32), nullable=False)
    event_key_sha256 = db.Column(db.String(64), nullable=False)
    event_type = db.Column(db.String(64), nullable=False)
    resource_type = db.Column(db.String(32), nullable=True)
    external_resource_id = db.Column(db.String(128), nullable=True)
    payload_json = db.Column(db.JSON, nullable=False, default=dict)
    status = db.Column(
        db.String(16), nullable=False, default="pending", server_default="pending"
    )
    attempts = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    error_code = db.Column(db.String(64), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_utcnow, server_default=db.func.current_timestamp()
    )
    processing_started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    processed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    account = db.relationship("ExternalAccount", back_populates="import_events")
