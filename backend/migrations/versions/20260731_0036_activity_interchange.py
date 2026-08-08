"""Add normalized activity interchange, series, route privacy and plan linking.

Revision ID: 20260731_0036
Revises: 20260731_0035
Create Date: 2026-07-31
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_0036"
down_revision = "20260731_0035"
branch_labels = None
depends_on = None


def _timestamps():
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
    )


def upgrade():
    with op.batch_alter_table("activities") as batch_op:
        batch_op.add_column(sa.Column("public_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("discipline", sa.String(length=32), server_default="unknown", nullable=False))
        batch_op.add_column(sa.Column("subtype", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("original_type", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("title", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("timezone_name", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("utc_offset_minutes", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("local_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("elapsed_time_seconds", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source_format", sa.String(length=32), server_default="unknown", nullable=False))
        batch_op.add_column(sa.Column("source_device", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("source_activity_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("original_file_public_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("metrics_provenance_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False))
        batch_op.add_column(sa.Column("environment", sa.String(length=16), server_default="unknown", nullable=False))
        batch_op.add_column(sa.Column("status", sa.String(length=24), server_default="imported", nullable=False))
        batch_op.add_column(sa.Column("revision", sa.Integer(), server_default="1", nullable=False))
        batch_op.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_unique_constraint("uq_activities_public_id", ["public_id"])
        batch_op.create_index("ix_activities_user_public", ["user_id", "public_id"])
        batch_op.create_index("ix_activities_user_status_started", ["user_id", "status", "started_at"])

    created_at, updated_at = _timestamps()
    op.create_table(
        "activity_import_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploaded_file_id", sa.Integer(), sa.ForeignKey("uploaded_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("activity_id", sa.Integer(), sa.ForeignKey("activities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("state", sa.String(length=24), server_default="uploaded", nullable=False),
        sa.Column("detected_format", sa.String(length=32), nullable=True),
        sa.Column("extension_format", sa.String(length=32), nullable=True),
        sa.Column("route_policy", sa.String(length=16), server_default="keep", nullable=False),
        sa.Column("redact_start_meters", sa.Integer(), server_default="0", nullable=False),
        sa.Column("redact_end_meters", sa.Integer(), server_default="0", nullable=False),
        sa.Column("strong_plan_public_id", sa.String(length=36), nullable=True),
        sa.Column("inspection_json", sa.JSON(), nullable=True),
        sa.Column("parsed_document_json", sa.JSON(), nullable=True),
        sa.Column("warnings_json", sa.JSON(), nullable=True),
        sa.Column("duplicate_classification", sa.String(length=32), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        created_at,
        updated_at,
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_activity_import_jobs_revision"),
        sa.UniqueConstraint("public_id", name="uq_activity_import_jobs_public"),
        sa.UniqueConstraint("user_id", "idempotency_key_hash", name="uq_activity_import_jobs_idempotency"),
    )
    op.create_index("ix_activity_import_jobs_user_state_created", "activity_import_jobs", ["user_id", "state", "created_at"])
    op.create_index("ix_activity_import_jobs_expires", "activity_import_jobs", ["expires_at"])

    op.create_table(
        "activity_laps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("activity_id", sa.Integer(), sa.ForeignKey("activities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lap_index", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("distance_meters", sa.Numeric(12, 2), nullable=True),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("source_payload_json", sa.JSON(), nullable=True),
        sa.UniqueConstraint("activity_id", "lap_index", name="uq_activity_laps_index"),
    )
    op.create_index("ix_activity_laps_user_activity", "activity_laps", ["user_id", "activity_id", "lap_index"])

    op.create_table(
        "activity_series_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("activity_id", sa.Integer(), sa.ForeignKey("activities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("format_version", sa.String(length=32), server_default="activity-series-v1", nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("compression", sa.String(length=16), server_default="gzip", nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("fields_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.UniqueConstraint("activity_id", name="uq_activity_series_activity"),
    )
    op.create_index("ix_activity_series_user_activity", "activity_series_artifacts", ["user_id", "activity_id"])

    op.create_table(
        "activity_route_metadata",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("activity_id", sa.Integer(), sa.ForeignKey("activities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(length=16), server_default="available", nullable=False),
        sa.Column("policy", sa.String(length=16), server_default="keep", nullable=False),
        sa.Column("original_storage_path", sa.String(length=512), nullable=True),
        sa.Column("visible_storage_path", sa.String(length=512), nullable=True),
        sa.Column("original_sha256", sa.String(length=64), nullable=True),
        sa.Column("visible_sha256", sa.String(length=64), nullable=True),
        sa.Column("original_point_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("visible_point_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("visible_distance_meters", sa.Numeric(12, 2), nullable=True),
        sa.Column("redact_start_meters", sa.Integer(), server_default="0", nullable=False),
        sa.Column("redact_end_meters", sa.Integer(), server_default="0", nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("activity_id", name="uq_activity_route_activity"),
    )
    op.create_index("ix_activity_route_user_activity", "activity_route_metadata", ["user_id", "activity_id"])

    op.create_table(
        "activity_duplicate_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("activity_id", sa.Integer(), sa.ForeignKey("activities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_activity_id", sa.Integer(), sa.ForeignKey("activities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("resolution", sa.String(length=24), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("activity_id", "candidate_activity_id", name="uq_activity_duplicate_pair"),
    )
    op.create_index("ix_activity_duplicates_user_classification", "activity_duplicate_candidates", ["user_id", "classification", "created_at"])

    op.create_table(
        "plan_activity_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("activity_id", sa.Integer(), sa.ForeignKey("activities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("planned_workout_id", sa.Integer(), sa.ForeignKey("planned_workouts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
        sa.Column("detached_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("activity_id", name="uq_plan_activity_links_activity"),
    )
    op.create_index("ix_plan_activity_links_user_plan", "plan_activity_links", ["user_id", "planned_workout_id"])

    op.create_table(
        "plan_actual_comparison_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_activity_link_id", sa.Integer(), sa.ForeignKey("plan_activity_links.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("activity_revision", sa.Integer(), nullable=False),
        sa.Column("plan_revision", sa.Integer(), nullable=False),
        sa.Column("comparison_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp(), nullable=False),
    )
    op.create_index("ix_plan_actual_comparisons_user_link_created", "plan_actual_comparison_snapshots", ["user_id", "plan_activity_link_id", "created_at"])


def downgrade():
    # Dropping the table also drops its indexes.  On MariaDB some of these
    # composite indexes are selected to enforce foreign keys, so attempting
    # to remove them first fails with error 1553.
    op.drop_table("plan_actual_comparison_snapshots")
    op.drop_table("plan_activity_links")
    op.drop_table("activity_duplicate_candidates")
    op.drop_table("activity_route_metadata")
    op.drop_table("activity_series_artifacts")
    op.drop_table("activity_laps")
    op.drop_table("activity_import_jobs")
    with op.batch_alter_table("activities") as batch_op:
        batch_op.drop_index("ix_activities_user_status_started")
        batch_op.drop_index("ix_activities_user_public")
        batch_op.drop_constraint("uq_activities_public_id", type_="unique")
        for column in (
            "archived_at", "revision", "status", "environment", "metrics_provenance_json",
            "original_file_public_id", "source_activity_id", "source_device", "source_format",
            "elapsed_time_seconds", "local_date", "utc_offset_minutes", "timezone_name", "title",
            "original_type", "subtype", "discipline", "public_id",
        ):
            batch_op.drop_column(column)
