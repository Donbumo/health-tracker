"""Add owner-scoped goals, reminder rules, events and adherence snapshots.

Revision ID: 20260731_0034
Revises: 20260730_0033
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_0034"
down_revision = "20260730_0033"
branch_labels = None
depends_on = None


GOAL_TYPES = (
    "training_sessions_per_week", "active_days_per_week", "daily_steps",
    "nutrition_calories", "nutrition_protein", "nutrition_carbohydrates",
    "nutrition_fat", "weight_logging_frequency", "active_plan_tracking",
    "scheduled_workouts_completion",
)
REMINDER_TYPES = (
    "scheduled_workout_upcoming", "scheduled_workout_pending", "log_weight",
    "log_nutrition", "review_steps", "weekly_summary",
    "pending_sync_attention", "conflict_attention",
)


def _values(values):
    return ",".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "user_goals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("goal_type", sa.String(length=48), nullable=False),
        sa.Column("target_value", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("period", sa.String(length=24), nullable=False),
        sa.Column("applicable_days_json", sa.JSON(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("state", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("source", sa.String(length=32), server_default="manual", nullable=False),
        sa.Column("related_public_id", sa.String(length=36), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(f"goal_type IN ({_values(GOAL_TYPES)})", name="ck_user_goals_type"),
        sa.CheckConstraint("period IN ('daily','weekly','selected_days','active_plan','scheduled_workouts')", name="ck_user_goals_period"),
        sa.CheckConstraint("state IN ('active','paused','completed','archived')", name="ck_user_goals_state"),
        sa.CheckConstraint("target_value > 0", name="ck_user_goals_target_value"),
        sa.CheckConstraint("revision >= 1", name="ck_user_goals_revision"),
        sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_user_goals_dates"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_user_goals_public_id"),
    )
    op.create_index("ix_user_goals_user_state", "user_goals", ["user_id", "state", "start_date"])

    op.create_table(
        "reminder_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("goal_id", sa.Integer(), nullable=True),
        sa.Column("reminder_type", sa.String(length=48), nullable=False),
        sa.Column("local_time", sa.Time(), nullable=False),
        sa.Column("applicable_days_json", sa.JSON(), nullable=False),
        sa.Column("lead_minutes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("quiet_start", sa.Time(), nullable=True),
        sa.Column("quiet_end", sa.Time(), nullable=True),
        sa.Column("quiet_timezone", sa.String(length=64), nullable=True),
        sa.Column("snooze_options_json", sa.JSON(), nullable=False),
        sa.Column("max_per_day", sa.Integer(), server_default="1", nullable=False),
        sa.Column("cooldown_minutes", sa.Integer(), server_default="60", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("next_occurrence", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("related_public_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=32), server_default="manual", nullable=False),
        sa.Column("requires_device_confirmation", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(f"reminder_type IN ({_values(REMINDER_TYPES)})", name="ck_reminder_rules_type"),
        sa.CheckConstraint("lead_minutes BETWEEN 0 AND 10080", name="ck_reminder_rules_lead"),
        sa.CheckConstraint("max_per_day BETWEEN 1 AND 10", name="ck_reminder_rules_max_day"),
        sa.CheckConstraint("cooldown_minutes BETWEEN 0 AND 1440", name="ck_reminder_rules_cooldown"),
        sa.CheckConstraint("revision >= 1", name="ck_reminder_rules_revision"),
        sa.CheckConstraint("(quiet_start IS NULL AND quiet_end IS NULL) OR (quiet_start IS NOT NULL AND quiet_end IS NOT NULL)", name="ck_reminder_rules_quiet_pair"),
        sa.ForeignKeyConstraint(["goal_id"], ["user_goals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_reminder_rules_public_id"),
    )
    op.create_index("ix_reminder_rules_user_enabled", "reminder_rules", ["user_id", "enabled", "next_occurrence"])

    op.create_table(
        "reminder_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("parent_event_id", sa.Integer(), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_local", sa.String(length=40), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("related_public_id", sa.String(length=36), nullable=True),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(length=20), server_default="scheduled", nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deduplication_key", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("state IN ('scheduled','triggered','acknowledged','snoozed','dismissed','suppressed','failed','cancelled')", name="ck_reminder_events_state"),
        sa.CheckConstraint("revision >= 1", name="ck_reminder_events_revision"),
        sa.ForeignKeyConstraint(["parent_event_id"], ["reminder_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rule_id"], ["reminder_rules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_reminder_events_public_id"),
        sa.UniqueConstraint("user_id", "deduplication_key", name="uq_reminder_events_dedupe"),
    )
    op.create_index("ix_reminder_events_user_scheduled", "reminder_events", ["user_id", "scheduled_for"])
    op.create_index("ix_reminder_events_rule_state", "reminder_events", ["rule_id", "state"])

    op.create_table(
        "adherence_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("goal_id", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False),
        sa.Column("expected_count", sa.Integer(), nullable=False),
        sa.Column("percentage", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('no_configured','insufficient_data','on_track','partially_complete','completed','missed','paused')", name="ck_adherence_snapshots_status"),
        sa.CheckConstraint("completed_count >= 0", name="ck_adherence_snapshots_completed"),
        sa.CheckConstraint("expected_count >= 0", name="ck_adherence_snapshots_expected"),
        sa.CheckConstraint("percentage IS NULL OR (percentage >= 0 AND percentage <= 100)", name="ck_adherence_snapshots_percentage"),
        sa.ForeignKeyConstraint(["goal_id"], ["user_goals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_adherence_snapshots_public_id"),
        sa.UniqueConstraint("user_id", "goal_id", "period_start", "period_end", name="uq_adherence_snapshot_period"),
    )
    op.create_index("ix_adherence_snapshots_user_period", "adherence_snapshots", ["user_id", "period_start", "period_end"])


def downgrade() -> None:
    op.drop_table("adherence_snapshots")
    op.drop_table("reminder_events")
    op.drop_table("reminder_rules")
    op.drop_table("user_goals")
