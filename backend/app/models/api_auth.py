from datetime import datetime, timezone

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class ApiDevice(db.Model):
    __tablename__ = "api_devices"
    __table_args__ = (
        db.CheckConstraint(
            "platform IN ('android', 'ios', 'watch', 'unknown')",
            name="ck_api_devices_platform",
        ),
        db.UniqueConstraint("user_id", "public_device_id", name="uq_api_device_user_public"),
        db.Index("ix_api_devices_user_last_seen", "user_id", "last_seen_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    public_device_id = db.Column(db.String(36), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    platform = db.Column(db.String(20), nullable=False, default="unknown", server_default="unknown")
    app_version = db.Column(db.String(40), nullable=True)
    os_version = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, server_default=db.func.current_timestamp())
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, server_default=db.func.current_timestamp())
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship("User", back_populates="api_devices")
    sessions = db.relationship("ApiSession", back_populates="device", cascade="all, delete-orphan", passive_deletes=True)
    companion_profile = db.relationship(
        "CompanionDeviceProfile", back_populates="api_device", uselist=False,
        cascade="all, delete-orphan", passive_deletes=True,
    )
    companion_deliveries = db.relationship(
        "CompanionWorkoutDelivery", back_populates="api_device", passive_deletes=True
    )


class ApiSession(db.Model):
    __tablename__ = "api_sessions"
    __table_args__ = (
        db.UniqueConstraint("public_session_id", name="uq_api_sessions_public"),
        db.UniqueConstraint("token_family_id", name="uq_api_sessions_family"),
        db.Index("ix_api_sessions_user_active", "user_id", "revoked_at", "expires_at"),
        db.Index("ix_api_sessions_device", "device_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    device_id = db.Column(db.Integer, db.ForeignKey("api_devices.id", ondelete="CASCADE"), nullable=False)
    public_session_id = db.Column(db.String(36), nullable=False)
    token_family_id = db.Column(db.String(36), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, server_default=db.func.current_timestamp())
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, server_default=db.func.current_timestamp())
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    revoke_reason = db.Column(db.String(64), nullable=True)

    user = db.relationship("User", back_populates="api_sessions")
    device = db.relationship("ApiDevice", back_populates="sessions")
    refresh_tokens = db.relationship("ApiRefreshToken", back_populates="session", cascade="all, delete-orphan", passive_deletes=True, foreign_keys="ApiRefreshToken.session_id")


class ApiRefreshToken(db.Model):
    __tablename__ = "api_refresh_tokens"
    __table_args__ = (
        db.UniqueConstraint("public_token_id", name="uq_api_refresh_public"),
        db.UniqueConstraint("token_hash", name="uq_api_refresh_hash"),
        db.Index("ix_api_refresh_session_created", "session_id", "created_at"),
        db.Index("ix_api_refresh_expiry", "expires_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("api_sessions.id", ondelete="CASCADE"), nullable=False)
    public_token_id = db.Column(db.String(36), nullable=False)
    token_hash = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, server_default=db.func.current_timestamp())
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    replaced_by_id = db.Column(db.Integer, db.ForeignKey("api_refresh_tokens.id", ondelete="SET NULL"), nullable=True)
    reuse_detected_at = db.Column(db.DateTime(timezone=True), nullable=True)

    session = db.relationship("ApiSession", back_populates="refresh_tokens", foreign_keys=[session_id])
    replaced_by = db.relationship("ApiRefreshToken", remote_side=[id], foreign_keys=[replaced_by_id])
