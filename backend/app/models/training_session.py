from datetime import datetime, timezone
import uuid

from app.extensions import db


class TrainingSession(db.Model):
    __tablename__ = "training_sessions"
    __table_args__ = (
        db.CheckConstraint(
            "planned_week_number >= 1",
            name="ck_training_sessions_week_number",
        ),
        db.CheckConstraint(
            "planned_day_number BETWEEN 1 AND 7",
            name="ck_training_sessions_day_number",
        ),
        db.CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds BETWEEN 1 AND 604800",
            name="ck_training_sessions_duration",
        ),
        db.CheckConstraint(
            "average_heart_rate_bpm IS NULL OR "
            "average_heart_rate_bpm BETWEEN 20 AND 250",
            name="ck_training_sessions_average_heart_rate",
        ),
        db.CheckConstraint(
            "calories_burned IS NULL OR calories_burned >= 0",
            name="ck_training_sessions_calories",
        ),
        db.UniqueConstraint(
            "source_file_id",
            name="uq_training_sessions_source_file",
        ),
        db.Index(
            "ix_training_sessions_user_performed",
            "user_id",
            "performed_at",
        ),
        db.UniqueConstraint("public_id", name="uq_training_sessions_public_id"),
        db.UniqueConstraint(
            "user_id",
            "source_device_id",
            "client_event_id",
            name="uq_training_sessions_device_event",
        ),
        db.UniqueConstraint(
            "planned_workout_id", name="uq_training_sessions_planned_workout"
        ),
        db.CheckConstraint("revision >= 1", name="ck_training_sessions_revision"),
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
        nullable=False,
    )
    training_plan_version_id = db.Column(
        db.Integer,
        db.ForeignKey("training_plan_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_file_id = db.Column(
        db.Integer,
        db.ForeignKey("uploaded_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    planned_workout_id = db.Column(
        db.Integer,
        db.ForeignKey("planned_workouts.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_device_id = db.Column(
        db.Integer, db.ForeignKey("api_devices.id", ondelete="SET NULL"), nullable=True
    )
    client_event_id = db.Column(db.String(36), nullable=True)
    client_payload_sha256 = db.Column(db.String(64), nullable=True)
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    timezone = db.Column(db.String(64), nullable=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=db.func.current_timestamp(),
    )
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    performed_at = db.Column(db.DateTime(timezone=True), nullable=False)
    planned_week_number = db.Column(db.Integer, nullable=False)
    planned_day_number = db.Column(db.Integer, nullable=False)
    duration_seconds = db.Column(db.Integer, nullable=True)
    average_heart_rate_bpm = db.Column(db.Integer, nullable=True)
    calories_burned = db.Column(db.Numeric(10, 2), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.current_timestamp(),
    )

    user = db.relationship("User", back_populates="training_sessions")
    training_plan = db.relationship("TrainingPlan", back_populates="sessions")
    training_plan_version = db.relationship(
        "TrainingPlanVersion",
        back_populates="sessions",
    )
    source_file = db.relationship("UploadedFile")
    planned_workout = db.relationship(
        "PlannedWorkout", back_populates="completed_session"
    )
    source_device = db.relationship("ApiDevice")
    exercises = db.relationship(
        "TrainingSessionExercise",
        back_populates="training_session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TrainingSessionExercise.exercise_order",
    )


class TrainingSessionExercise(db.Model):
    __tablename__ = "training_session_exercises"
    __table_args__ = (
        db.CheckConstraint(
            "exercise_order >= 1",
            name="ck_training_session_exercises_order",
        ),
        db.CheckConstraint(
            "planned_exercise_order >= 1",
            name="ck_training_session_exercises_planned_order",
        ),
        db.UniqueConstraint(
            "training_session_id",
            "exercise_order",
            name="uq_training_session_exercises_session_order",
        ),
        db.Index(
            "ix_training_session_exercises_user_session",
            "user_id",
            "training_session_id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    training_session_id = db.Column(
        db.Integer,
        db.ForeignKey("training_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    exercise_order = db.Column(db.Integer, nullable=False)
    planned_exercise_order = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    notes = db.Column(db.Text, nullable=True)

    training_session = db.relationship("TrainingSession", back_populates="exercises")
    sets = db.relationship(
        "TrainingSet",
        back_populates="session_exercise",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TrainingSet.set_number",
    )


class TrainingSet(db.Model):
    __tablename__ = "training_sets"
    __table_args__ = (
        db.CheckConstraint("set_number >= 1", name="ck_training_sets_number"),
        db.CheckConstraint(
            "planned_set_number >= 1",
            name="ck_training_sets_planned_number",
        ),
        db.CheckConstraint("weight_kg >= 0", name="ck_training_sets_weight"),
        db.CheckConstraint("reps >= 1", name="ck_training_sets_reps"),
        db.CheckConstraint(
            "rir IS NULL OR (rir >= 0 AND rir <= 10)",
            name="ck_training_sets_rir",
        ),
        db.CheckConstraint(
            "rpe IS NULL OR (rpe >= 1 AND rpe <= 10)",
            name="ck_training_sets_rpe",
        ),
        db.CheckConstraint(
            "rest_seconds IS NULL OR rest_seconds BETWEEN 0 AND 86400",
            name="ck_training_sets_rest_seconds",
        ),
        db.UniqueConstraint(
            "training_session_exercise_id",
            "set_number",
            name="uq_training_sets_exercise_number",
        ),
        db.Index(
            "ix_training_sets_user_exercise",
            "user_id",
            "training_session_exercise_id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    training_session_exercise_id = db.Column(
        db.Integer,
        db.ForeignKey("training_session_exercises.id", ondelete="CASCADE"),
        nullable=False,
    )
    set_number = db.Column(db.Integer, nullable=False)
    planned_set_number = db.Column(db.Integer, nullable=False)
    weight_kg = db.Column(db.Numeric(8, 2), nullable=False)
    reps = db.Column(db.Integer, nullable=False)
    rir = db.Column(db.Numeric(4, 1), nullable=True)
    rpe = db.Column(db.Numeric(4, 1), nullable=True)
    rest_seconds = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    session_exercise = db.relationship(
        "TrainingSessionExercise",
        back_populates="sets",
    )
