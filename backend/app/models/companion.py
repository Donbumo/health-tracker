from datetime import datetime, timezone
import uuid

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class CompanionDeviceProfile(db.Model):
    __tablename__ = "companion_device_profiles"
    __table_args__ = (
        db.UniqueConstraint("public_id", name="uq_companion_profiles_public"),
        db.UniqueConstraint("api_device_id", name="uq_companion_profiles_device"),
        db.CheckConstraint("revision >= 1", name="ck_companion_profiles_revision"),
        db.CheckConstraint("max_payload_bytes BETWEEN 1024 AND 1048576", name="ck_companion_profiles_payload_limit"),
        db.CheckConstraint("max_progress_events_per_workout BETWEEN 1 AND 10000", name="ck_companion_profiles_event_limit"),
        db.Index("ix_companion_profiles_user_updated", "user_id", "updated_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    api_device_id = db.Column(db.Integer, db.ForeignKey("api_devices.id", ondelete="CASCADE"), nullable=False)
    protocol_version = db.Column(db.String(10), nullable=False, default="1.0", server_default="1.0")
    workout_schema_version = db.Column(db.String(10), nullable=False, default="1.0", server_default="1.0")
    result_schema_version = db.Column(db.String(10), nullable=False, default="1.0", server_default="1.0")
    supported_metrics_json = db.Column(db.JSON, nullable=False)
    supported_features_json = db.Column(db.JSON, nullable=False)
    max_payload_bytes = db.Column(db.Integer, nullable=False, default=65536, server_default="65536")
    max_progress_events_per_workout = db.Column(db.Integer, nullable=False, default=500, server_default="500")
    supports_offline = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    supports_rest_timer = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    supports_haptics = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    supports_rpe = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    supports_rir = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    supports_weight = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    supports_heart_rate_summary = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    supports_calories_summary = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow, server_default=db.func.current_timestamp())
    last_negotiated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, server_default=db.func.current_timestamp())
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship("User")
    api_device = db.relationship("ApiDevice", back_populates="companion_profile")
    deliveries = db.relationship("CompanionWorkoutDelivery", back_populates="profile", passive_deletes=True)


class CompanionWorkoutDelivery(db.Model):
    __tablename__ = "companion_workout_deliveries"
    __table_args__ = (
        db.UniqueConstraint("public_id", name="uq_companion_deliveries_public"),
        db.UniqueConstraint(
            "api_device_id", "profile_id", "planned_workout_id", "planned_workout_revision",
            name="uq_companion_delivery_snapshot",
        ),
        db.UniqueConstraint("training_session_id", name="uq_companion_delivery_session"),
        db.CheckConstraint(
            "status IN ('prepared','delivered','acknowledged','started','completed','aborted','failed','expired','cancelled')",
            name="ck_companion_deliveries_status",
        ),
        db.CheckConstraint("revision >= 1", name="ck_companion_deliveries_revision"),
        db.CheckConstraint("last_client_sequence >= 0", name="ck_companion_deliveries_sequence"),
        db.Index("ix_companion_deliveries_user_status", "user_id", "status", "updated_at"),
        db.Index("ix_companion_deliveries_device_created", "api_device_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    api_device_id = db.Column(db.Integer, db.ForeignKey("api_devices.id", ondelete="CASCADE"), nullable=False)
    profile_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "companion_device_profiles.id",
            ondelete="CASCADE",
            name="fk_companion_deliveries_profile",
        ),
        nullable=False,
    )
    planned_workout_id = db.Column(db.Integer, db.ForeignKey("planned_workouts.id", ondelete="CASCADE"), nullable=False)
    planned_workout_revision = db.Column(db.Integer, nullable=False)
    package_schema_version = db.Column(db.String(10), nullable=False)
    package_hash = db.Column(db.String(64), nullable=False)
    payload_snapshot_json = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="prepared", server_default="prepared")
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    last_client_sequence = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    completion_event_id = db.Column(db.String(36), nullable=True)
    completion_payload_hash = db.Column(db.String(64), nullable=True)
    training_session_id = db.Column(db.Integer, db.ForeignKey("training_sessions.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow, server_default=db.func.current_timestamp())
    delivered_at = db.Column(db.DateTime(timezone=True), nullable=True)
    acknowledged_at = db.Column(db.DateTime(timezone=True), nullable=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    aborted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    failed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    failure_code = db.Column(db.String(64), nullable=True)

    api_device = db.relationship("ApiDevice", back_populates="companion_deliveries")
    profile = db.relationship("CompanionDeviceProfile", back_populates="deliveries")
    planned_workout = db.relationship("PlannedWorkout")
    training_session = db.relationship("TrainingSession")
    progress_events = db.relationship("CompanionProgressEvent", back_populates="delivery", cascade="all, delete-orphan", passive_deletes=True)


class CompanionProgressEvent(db.Model):
    __tablename__ = "companion_progress_events"
    __table_args__ = (
        db.UniqueConstraint("public_id", name="uq_companion_progress_public"),
        db.UniqueConstraint("delivery_id", "client_event_id", name="uq_companion_progress_event"),
        db.UniqueConstraint("delivery_id", "client_sequence", name="uq_companion_progress_sequence"),
        db.CheckConstraint("client_sequence >= 1", name="ck_companion_progress_sequence"),
        db.CheckConstraint(
            "event_type IN ('heartbeat','exercise_started','set_completed','exercise_completed','paused','resumed','checkpoint')",
            name="ck_companion_progress_type",
        ),
        db.Index("ix_companion_progress_user_created", "user_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    delivery_id = db.Column(db.Integer, db.ForeignKey("companion_workout_deliveries.id", ondelete="CASCADE"), nullable=False)
    api_device_id = db.Column(db.Integer, db.ForeignKey("api_devices.id", ondelete="CASCADE"), nullable=False)
    client_event_id = db.Column(db.String(36), nullable=False)
    client_sequence = db.Column(db.Integer, nullable=False)
    event_type = db.Column(db.String(32), nullable=False)
    occurred_at = db.Column(db.DateTime(timezone=True), nullable=False)
    payload_json = db.Column(db.JSON, nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, server_default=db.func.current_timestamp())

    delivery = db.relationship("CompanionWorkoutDelivery", back_populates="progress_events")
    api_device = db.relationship("ApiDevice")
