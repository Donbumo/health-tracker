from datetime import datetime, timezone
import uuid

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class PlannedWorkout(db.Model):
    __tablename__ = "planned_workouts"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('planned', 'in_progress', 'completed', 'skipped', 'cancelled')",
            name="ck_planned_workouts_status",
        ),
        db.CheckConstraint("revision >= 1", name="ck_planned_workouts_revision"),
        db.UniqueConstraint("public_id", name="uq_planned_workouts_public_id"),
        db.Index(
            "ix_planned_workouts_user_schedule",
            "user_id",
            "scheduled_for_date",
            "status",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(
        db.String(36), nullable=False, default=lambda: str(uuid.uuid4())
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    training_plan_id = db.Column(
        db.Integer,
        db.ForeignKey("training_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    training_plan_version_id = db.Column(
        db.Integer,
        db.ForeignKey("training_plan_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    scheduled_for_date = db.Column(db.Date, nullable=False)
    timezone = db.Column(db.String(64), nullable=False)
    status = db.Column(
        db.String(20), nullable=False, default="planned", server_default="planned"
    )
    title_snapshot = db.Column(db.String(200), nullable=False)
    payload_snapshot_json = db.Column(db.JSON, nullable=False)
    source_version = db.Column(db.Integer, nullable=False)
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow,
        server_default=db.func.current_timestamp(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow,
        server_default=db.func.current_timestamp(),
    )
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    cancelled_at = db.Column(db.DateTime(timezone=True), nullable=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_modified_by_device_id = db.Column(
        db.Integer, db.ForeignKey("api_devices.id", ondelete="SET NULL"), nullable=True
    )

    user = db.relationship("User", back_populates="planned_workouts")
    training_plan = db.relationship("TrainingPlan")
    training_plan_version = db.relationship("TrainingPlanVersion")
    last_modified_by_device = db.relationship("ApiDevice")
    completed_session = db.relationship(
        "TrainingSession", back_populates="planned_workout", uselist=False
    )


class SyncChange(db.Model):
    __tablename__ = "sync_changes"
    __table_args__ = (
        db.CheckConstraint(
            "operation IN ('upsert', 'delete')", name="ck_sync_changes_operation"
        ),
        db.CheckConstraint("revision >= 1", name="ck_sync_changes_revision"),
        db.Index("ix_sync_changes_user_sequence", "user_id", "sequence"),
        db.Index(
            "ix_sync_changes_user_entity",
            "user_id",
            "entity_type",
            "entity_public_id",
        ),
    )

    sequence = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    entity_type = db.Column(db.String(40), nullable=False)
    entity_public_id = db.Column(db.String(36), nullable=False)
    operation = db.Column(db.String(10), nullable=False)
    revision = db.Column(db.Integer, nullable=False)
    changed_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow,
        server_default=db.func.current_timestamp(),
    )
    changed_by_device_id = db.Column(
        db.Integer, db.ForeignKey("api_devices.id", ondelete="SET NULL"), nullable=True
    )
    payload_hash = db.Column(db.String(64), nullable=False)
    payload_json = db.Column(db.JSON, nullable=True)


class DeviceSyncState(db.Model):
    __tablename__ = "device_sync_states"
    __table_args__ = (
        db.UniqueConstraint("user_id", "device_id", name="uq_device_sync_user_device"),
        db.CheckConstraint(
            "last_pull_sequence >= 0", name="ck_device_sync_last_pull_sequence"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    device_id = db.Column(
        db.Integer, db.ForeignKey("api_devices.id", ondelete="CASCADE"), nullable=False
    )
    last_pull_sequence = db.Column(
        db.Integer, nullable=False, default=0, server_default="0"
    )
    last_push_at = db.Column(db.DateTime(timezone=True), nullable=True)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow,
        server_default=db.func.current_timestamp(),
    )


class IdempotencyRecord(db.Model):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "device_id", "key_hash", name="uq_idempotency_user_device_key"
        ),
        db.Index("ix_idempotency_expires", "expires_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    device_id = db.Column(
        db.Integer, db.ForeignKey("api_devices.id", ondelete="CASCADE"), nullable=False
    )
    key_hash = db.Column(db.String(64), nullable=False)
    operation = db.Column(db.String(80), nullable=False)
    request_hash = db.Column(db.String(64), nullable=False)
    response_status = db.Column(db.Integer, nullable=True)
    response_body_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow,
        server_default=db.func.current_timestamp(),
    )
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
