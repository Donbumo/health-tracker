"""Add activity and route import tables.

Revision ID: 20260711_0019
Revises: 20260710_0018
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa


revision = "20260711_0019"
down_revision = "20260710_0018"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "activities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("activity_type", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("moving_time_seconds", sa.Integer(), nullable=True),
        sa.Column("distance_meters", sa.Numeric(12, 2), nullable=True),
        sa.Column("calories_kcal", sa.Numeric(10, 2), nullable=True),
        sa.Column("avg_heart_rate_bpm", sa.Integer(), nullable=True),
        sa.Column("max_heart_rate_bpm", sa.Integer(), nullable=True),
        sa.Column("avg_cadence_rpm", sa.Numeric(8, 2), nullable=True),
        sa.Column("max_cadence_rpm", sa.Numeric(8, 2), nullable=True),
        sa.Column("avg_speed_mps", sa.Numeric(10, 4), nullable=True),
        sa.Column("max_speed_mps", sa.Numeric(10, 4), nullable=True),
        sa.Column("elevation_gain_meters", sa.Numeric(10, 2), nullable=True),
        sa.Column("elevation_loss_meters", sa.Numeric(10, 2), nullable=True),
        sa.Column("avg_power_watts", sa.Integer(), nullable=True),
        sa.Column("max_power_watts", sa.Integer(), nullable=True),
        sa.Column("sport_profile", sa.String(length=128), nullable=True),
        sa.Column("manufacturer", sa.String(length=128), nullable=True),
        sa.Column("product", sa.String(length=128), nullable=True),
        sa.Column("source_app", sa.String(length=128), nullable=True),
        sa.Column("source_type", sa.String(length=32), server_default="uploaded", nullable=False),
        sa.Column("source_file_id", sa.Integer(), sa.ForeignKey("uploaded_files.id", ondelete="SET NULL"), nullable=True),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("canonical_json", sa.JSON(), nullable=False),
        sa.Column("laps_json", sa.JSON(), nullable=True),
        sa.Column("track_json", sa.JSON(), nullable=True),
        sa.Column("bounds_json", sa.JSON(), nullable=True),
        sa.Column("point_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="ck_activities_duration"),
        sa.CheckConstraint("moving_time_seconds IS NULL OR moving_time_seconds >= 0", name="ck_activities_moving_time"),
        sa.CheckConstraint("distance_meters IS NULL OR distance_meters >= 0", name="ck_activities_distance"),
        sa.CheckConstraint("calories_kcal IS NULL OR calories_kcal >= 0", name="ck_activities_calories"),
        sa.CheckConstraint("point_count >= 0", name="ck_activities_point_count"),
        sa.UniqueConstraint("user_id", "fingerprint_sha256", name="uq_activities_user_fingerprint"),
    )
    op.create_index("ix_activities_user_started", "activities", ["user_id", "started_at"])
    op.create_index("ix_activities_user_type", "activities", ["user_id", "activity_type"])

    op.create_table(
        "routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("route_type", sa.String(length=64), nullable=False),
        sa.Column("distance_meters", sa.Numeric(12, 2), nullable=True),
        sa.Column("elevation_gain_meters", sa.Numeric(10, 2), nullable=True),
        sa.Column("elevation_loss_meters", sa.Numeric(10, 2), nullable=True),
        sa.Column("bounds_json", sa.JSON(), nullable=True),
        sa.Column("points_json", sa.JSON(), nullable=True),
        sa.Column("point_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source_app", sa.String(length=128), nullable=True),
        sa.Column("source_type", sa.String(length=32), server_default="uploaded", nullable=False),
        sa.Column("source_file_id", sa.Integer(), sa.ForeignKey("uploaded_files.id", ondelete="SET NULL"), nullable=True),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("canonical_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.CheckConstraint("distance_meters IS NULL OR distance_meters >= 0", name="ck_routes_distance"),
        sa.CheckConstraint("point_count >= 0", name="ck_routes_point_count"),
        sa.UniqueConstraint("user_id", "fingerprint_sha256", name="uq_routes_user_fingerprint"),
    )
    op.create_index("ix_routes_user_created", "routes", ["user_id", "created_at"])
    op.create_index("ix_routes_user_type", "routes", ["user_id", "route_type"])


def downgrade():
    op.drop_index("ix_routes_user_type", table_name="routes")
    op.drop_index("ix_routes_user_created", table_name="routes")
    op.drop_table("routes")
    op.drop_index("ix_activities_user_type", table_name="activities")
    op.drop_index("ix_activities_user_started", table_name="activities")
    op.drop_table("activities")
