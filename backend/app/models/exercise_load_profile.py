from datetime import datetime, timezone
import uuid

from app.extensions import db


class ExerciseLoadProfile(db.Model):
    __tablename__ = "exercise_load_profiles"
    __table_args__ = (
        db.UniqueConstraint("public_id", name="uq_exercise_load_profiles_public_id"),
        db.UniqueConstraint("user_id", "exercise_id", name="uq_exercise_load_profiles_user_exercise"),
        db.CheckConstraint("preferred_unit IN ('kg', 'lb')", name="ck_exercise_load_profiles_unit"),
        db.CheckConstraint(
            "load_mode IN ('direct_total','per_side','bar_plus_per_side','machine_initial_total','machine_initial_per_side','machine_external_per_side_initial_total','selector_stack','dumbbell_each','bodyweight','bodyweight_plus','assistance','duration_distance')",
            name="ck_exercise_load_profiles_mode",
        ),
        db.CheckConstraint("revision >= 1", name="ck_exercise_load_profiles_revision"),
        db.Index("ix_exercise_load_profiles_user_exercise", "user_id", "exercise_id"),
    )
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    exercise_id = db.Column(db.Integer, db.ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False)
    load_mode = db.Column(db.String(64), nullable=False, default="direct_total", server_default="direct_total")
    preferred_unit = db.Column(db.String(2), nullable=False, default="kg", server_default="kg")
    configuration_json = db.Column(db.JSON, nullable=False, default=dict)
    quick_increments_json = db.Column(db.JSON, nullable=False, default=lambda: ["2.5", "5"])
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=db.func.current_timestamp())
    user = db.relationship("User", back_populates="exercise_load_profiles")
    exercise = db.relationship("Exercise", back_populates="load_profile")
