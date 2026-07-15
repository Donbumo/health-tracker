"""Add companion capability profiles, deliveries and progress checkpoints.

Revision ID: 20260714_0024
Revises: 20260714_0023
"""
from alembic import op
import sqlalchemy as sa


revision = "20260714_0024"
down_revision = "20260714_0023"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "companion_device_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_device_id", sa.Integer(), sa.ForeignKey("api_devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("protocol_version", sa.String(10), server_default="1.0", nullable=False),
        sa.Column("workout_schema_version", sa.String(10), server_default="1.0", nullable=False),
        sa.Column("result_schema_version", sa.String(10), server_default="1.0", nullable=False),
        sa.Column("supported_metrics_json", sa.JSON(), nullable=False),
        sa.Column("supported_features_json", sa.JSON(), nullable=False),
        sa.Column("max_payload_bytes", sa.Integer(), server_default="65536", nullable=False),
        sa.Column("max_progress_events_per_workout", sa.Integer(), server_default="500", nullable=False),
        sa.Column("supports_offline", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("supports_rest_timer", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("supports_haptics", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("supports_rpe", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("supports_rir", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("supports_weight", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("supports_heart_rate_summary", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("supports_calories_summary", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("last_negotiated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("public_id", name="uq_companion_profiles_public"),
        sa.UniqueConstraint("api_device_id", name="uq_companion_profiles_device"),
        sa.CheckConstraint("revision >= 1", name="ck_companion_profiles_revision"),
        sa.CheckConstraint("max_payload_bytes BETWEEN 1024 AND 1048576", name="ck_companion_profiles_payload_limit"),
        sa.CheckConstraint("max_progress_events_per_workout BETWEEN 1 AND 10000", name="ck_companion_profiles_event_limit"),
    )
    op.create_index("ix_companion_profiles_user_updated", "companion_device_profiles", ["user_id", "updated_at"])

    op.create_table(
        "companion_workout_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_device_id", sa.Integer(), sa.ForeignKey("api_devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("companion_device_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("planned_workout_id", sa.Integer(), sa.ForeignKey("planned_workouts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("planned_workout_revision", sa.Integer(), nullable=False),
        sa.Column("package_schema_version", sa.String(10), nullable=False),
        sa.Column("package_hash", sa.String(64), nullable=False),
        sa.Column("payload_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), server_default="prepared", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last_client_sequence", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completion_event_id", sa.String(36)),
        sa.Column("completion_payload_hash", sa.String(64)),
        sa.Column("training_session_id", sa.Integer(), sa.ForeignKey("training_sessions.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("aborted_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String(64)),
        sa.UniqueConstraint("public_id", name="uq_companion_deliveries_public"),
        sa.UniqueConstraint("api_device_id", "profile_id", "planned_workout_id", "planned_workout_revision", name="uq_companion_delivery_snapshot"),
        sa.UniqueConstraint("training_session_id", name="uq_companion_delivery_session"),
        sa.CheckConstraint("status IN ('prepared','delivered','acknowledged','started','completed','aborted','failed','expired','cancelled')", name="ck_companion_deliveries_status"),
        sa.CheckConstraint("revision >= 1", name="ck_companion_deliveries_revision"),
        sa.CheckConstraint("last_client_sequence >= 0", name="ck_companion_deliveries_sequence"),
    )
    op.create_index("ix_companion_deliveries_user_status", "companion_workout_deliveries", ["user_id", "status", "updated_at"])
    op.create_index("ix_companion_deliveries_device_created", "companion_workout_deliveries", ["api_device_id", "created_at"])

    op.create_table(
        "companion_progress_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("delivery_id", sa.Integer(), sa.ForeignKey("companion_workout_deliveries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_device_id", sa.Integer(), sa.ForeignKey("api_devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_event_id", sa.String(36), nullable=False),
        sa.Column("client_sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.UniqueConstraint("public_id", name="uq_companion_progress_public"),
        sa.UniqueConstraint("delivery_id", "client_event_id", name="uq_companion_progress_event"),
        sa.UniqueConstraint("delivery_id", "client_sequence", name="uq_companion_progress_sequence"),
        sa.CheckConstraint("client_sequence >= 1", name="ck_companion_progress_sequence"),
        sa.CheckConstraint("event_type IN ('heartbeat','exercise_started','set_completed','exercise_completed','paused','resumed','checkpoint')", name="ck_companion_progress_type"),
    )
    op.create_index("ix_companion_progress_user_created", "companion_progress_events", ["user_id", "created_at"])


def downgrade():
    op.drop_table("companion_progress_events")
    op.drop_table("companion_workout_deliveries")
    op.drop_table("companion_device_profiles")
