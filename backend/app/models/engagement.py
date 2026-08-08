from datetime import datetime, timezone
import uuid

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


GOAL_TYPES = (
    "training_sessions_per_week",
    "active_days_per_week",
    "daily_steps",
    "nutrition_calories",
    "nutrition_protein",
    "nutrition_carbohydrates",
    "nutrition_fat",
    "weight_logging_frequency",
    "active_plan_tracking",
    "scheduled_workouts_completion",
)

REMINDER_TYPES = (
    "scheduled_workout_upcoming",
    "scheduled_workout_pending",
    "log_weight",
    "log_nutrition",
    "review_steps",
    "weekly_summary",
    "pending_sync_attention",
    "conflict_attention",
)


class UserGoal(db.Model):
    __tablename__ = "user_goals"
    __table_args__ = (
        db.CheckConstraint(
            "goal_type IN (" + ",".join(f"'{value}'" for value in GOAL_TYPES) + ")",
            name="ck_user_goals_type",
        ),
        db.CheckConstraint(
            "period IN ('daily','weekly','selected_days','active_plan','scheduled_workouts')",
            name="ck_user_goals_period",
        ),
        db.CheckConstraint(
            "state IN ('active','paused','completed','archived')",
            name="ck_user_goals_state",
        ),
        db.CheckConstraint("target_value > 0", name="ck_user_goals_target_value"),
        db.CheckConstraint("revision >= 1", name="ck_user_goals_revision"),
        db.CheckConstraint(
            "end_date IS NULL OR end_date >= start_date", name="ck_user_goals_dates"
        ),
        db.UniqueConstraint("public_id", name="uq_user_goals_public_id"),
        db.Index("ix_user_goals_user_state", "user_id", "state", "start_date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    goal_type = db.Column(db.String(48), nullable=False)
    target_value = db.Column(db.Numeric(14, 3), nullable=False)
    unit = db.Column(db.String(32), nullable=False)
    period = db.Column(db.String(24), nullable=False)
    applicable_days_json = db.Column(db.JSON, nullable=False, default=list)
    timezone = db.Column(db.String(64), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    state = db.Column(db.String(16), nullable=False, default="active", server_default="active")
    source = db.Column(db.String(32), nullable=False, default="manual", server_default="manual")
    related_public_id = db.Column(db.String(36), nullable=True)
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow,
        server_default=db.func.current_timestamp(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow,
        server_default=db.func.current_timestamp(),
    )


class ReminderRule(db.Model):
    __tablename__ = "reminder_rules"
    __table_args__ = (
        db.CheckConstraint(
            "reminder_type IN (" + ",".join(f"'{value}'" for value in REMINDER_TYPES) + ")",
            name="ck_reminder_rules_type",
        ),
        db.CheckConstraint("lead_minutes BETWEEN 0 AND 10080", name="ck_reminder_rules_lead"),
        db.CheckConstraint("max_per_day BETWEEN 1 AND 10", name="ck_reminder_rules_max_day"),
        db.CheckConstraint("cooldown_minutes BETWEEN 0 AND 1440", name="ck_reminder_rules_cooldown"),
        db.CheckConstraint("revision >= 1", name="ck_reminder_rules_revision"),
        db.CheckConstraint(
            "(quiet_start IS NULL AND quiet_end IS NULL) OR "
            "(quiet_start IS NOT NULL AND quiet_end IS NOT NULL)",
            name="ck_reminder_rules_quiet_pair",
        ),
        db.UniqueConstraint("public_id", name="uq_reminder_rules_public_id"),
        db.Index("ix_reminder_rules_user_enabled", "user_id", "enabled", "next_occurrence"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    goal_id = db.Column(
        db.Integer, db.ForeignKey("user_goals.id", ondelete="SET NULL"), nullable=True
    )
    reminder_type = db.Column(db.String(48), nullable=False)
    local_time = db.Column(db.Time, nullable=False)
    applicable_days_json = db.Column(db.JSON, nullable=False, default=list)
    lead_minutes = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    quiet_start = db.Column(db.Time, nullable=True)
    quiet_end = db.Column(db.Time, nullable=True)
    quiet_timezone = db.Column(db.String(64), nullable=True)
    snooze_options_json = db.Column(db.JSON, nullable=False, default=lambda: [15, 30, 60, "tomorrow"])
    max_per_day = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    cooldown_minutes = db.Column(db.Integer, nullable=False, default=60, server_default="60")
    enabled = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    timezone = db.Column(db.String(64), nullable=False)
    next_occurrence = db.Column(db.DateTime(timezone=True), nullable=True)
    last_triggered_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_acknowledged_at = db.Column(db.DateTime(timezone=True), nullable=True)
    related_public_id = db.Column(db.String(36), nullable=True)
    source = db.Column(db.String(32), nullable=False, default="manual", server_default="manual")
    requires_device_confirmation = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.false()
    )
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow,
        server_default=db.func.current_timestamp(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow,
        server_default=db.func.current_timestamp(),
    )

    goal = db.relationship("UserGoal")


class ReminderEvent(db.Model):
    __tablename__ = "reminder_events"
    __table_args__ = (
        db.CheckConstraint(
            "state IN ('scheduled','triggered','acknowledged','snoozed','dismissed',"
            "'suppressed','failed','cancelled')",
            name="ck_reminder_events_state",
        ),
        db.CheckConstraint("revision >= 1", name="ck_reminder_events_revision"),
        db.UniqueConstraint("public_id", name="uq_reminder_events_public_id"),
        db.UniqueConstraint("user_id", "deduplication_key", name="uq_reminder_events_dedupe"),
        db.Index("ix_reminder_events_user_scheduled", "user_id", "scheduled_for"),
        db.Index("ix_reminder_events_rule_state", "rule_id", "state"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    rule_id = db.Column(
        db.Integer, db.ForeignKey("reminder_rules.id", ondelete="CASCADE"), nullable=False
    )
    parent_event_id = db.Column(
        db.Integer, db.ForeignKey("reminder_events.id", ondelete="SET NULL"), nullable=True
    )
    scheduled_for = db.Column(db.DateTime(timezone=True), nullable=False)
    scheduled_local = db.Column(db.String(40), nullable=False)
    event_type = db.Column(db.String(48), nullable=False)
    related_public_id = db.Column(db.String(36), nullable=True)
    triggered_at = db.Column(db.DateTime(timezone=True), nullable=True)
    state = db.Column(db.String(20), nullable=False, default="scheduled", server_default="scheduled")
    acknowledged_at = db.Column(db.DateTime(timezone=True), nullable=True)
    snoozed_until = db.Column(db.DateTime(timezone=True), nullable=True)
    dismissed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    deduplication_key = db.Column(db.String(64), nullable=False)
    error_code = db.Column(db.String(64), nullable=True)
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow,
        server_default=db.func.current_timestamp(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow,
        server_default=db.func.current_timestamp(),
    )

    rule = db.relationship("ReminderRule")
    parent_event = db.relationship("ReminderEvent", remote_side=[id])


class AdherenceSnapshot(db.Model):
    __tablename__ = "adherence_snapshots"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('no_configured','insufficient_data','on_track','partially_complete',"
            "'completed','missed','paused')",
            name="ck_adherence_snapshots_status",
        ),
        db.CheckConstraint("completed_count >= 0", name="ck_adherence_snapshots_completed"),
        db.CheckConstraint("expected_count >= 0", name="ck_adherence_snapshots_expected"),
        db.CheckConstraint(
            "percentage IS NULL OR (percentage >= 0 AND percentage <= 100)",
            name="ck_adherence_snapshots_percentage",
        ),
        db.UniqueConstraint(
            "user_id", "goal_id", "period_start", "period_end",
            name="uq_adherence_snapshot_period",
        ),
        db.UniqueConstraint("public_id", name="uq_adherence_snapshots_public_id"),
        db.Index("ix_adherence_snapshots_user_period", "user_id", "period_start", "period_end"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    goal_id = db.Column(
        db.Integer, db.ForeignKey("user_goals.id", ondelete="CASCADE"), nullable=False
    )
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    timezone = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(24), nullable=False)
    completed_count = db.Column(db.Integer, nullable=False)
    expected_count = db.Column(db.Integer, nullable=False)
    percentage = db.Column(db.Numeric(6, 2), nullable=True)
    details_json = db.Column(db.JSON, nullable=False, default=dict)
    generated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow,
        server_default=db.func.current_timestamp(),
    )

    goal = db.relationship("UserGoal")
