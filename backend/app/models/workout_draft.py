from datetime import datetime, timezone
import uuid

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class WorkoutSessionDraft(db.Model):
    __tablename__ = "workout_session_drafts"
    __table_args__ = (
        db.UniqueConstraint(
            "public_id", name="uq_workout_session_drafts_public_id"
        ),
        db.UniqueConstraint(
            "user_id",
            "client_submission_id",
            name="uq_workout_session_drafts_user_submission",
        ),
        db.CheckConstraint(
            "revision >= 1", name="ck_workout_session_drafts_revision"
        ),
        db.CheckConstraint(
            "planned_week_number IS NULL OR planned_week_number >= 1",
            name="ck_workout_session_drafts_week",
        ),
        db.CheckConstraint(
            "planned_day_number IS NULL OR "
            "planned_day_number BETWEEN 1 AND 7",
            name="ck_workout_session_drafts_day",
        ),
        db.Index(
            "ix_workout_session_drafts_user_version",
            "user_id",
            "training_plan_version_id",
            "updated_at",
        ),
        db.Index(
            "ix_workout_session_drafts_user_planned",
            "user_id",
            "planned_workout_id",
        ),
        db.Index("ix_workout_session_drafts_expires", "expires_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(
        db.String(36), nullable=False, default=lambda: str(uuid.uuid4())
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    training_plan_id = db.Column(
        db.Integer,
        db.ForeignKey("training_plans.id", ondelete="CASCADE"),
        nullable=True,
    )
    training_plan_version_id = db.Column(
        db.Integer,
        db.ForeignKey("training_plan_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    planned_workout_id = db.Column(
        db.Integer,
        db.ForeignKey("planned_workouts.id", ondelete="SET NULL"),
        nullable=True,
    )
    planned_week_number = db.Column(db.Integer, nullable=True)
    planned_day_number = db.Column(db.Integer, nullable=True)
    client_submission_id = db.Column(db.String(36), nullable=False)
    payload_json = db.Column(db.JSON, nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)
    schema_version = db.Column(
        db.String(20), nullable=False, default="1.0", server_default="1.0"
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
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    last_saved_from_device_id = db.Column(
        db.Integer,
        db.ForeignKey("api_devices.id", ondelete="SET NULL"),
        nullable=True,
    )
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")

    user = db.relationship("User", back_populates="workout_session_drafts")
    training_plan = db.relationship("TrainingPlan")
    training_plan_version = db.relationship("TrainingPlanVersion")
    planned_workout = db.relationship("PlannedWorkout")
    last_saved_from_device = db.relationship("ApiDevice")
