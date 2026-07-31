"""Add owner-scoped portable export and import jobs.

Revision ID: 20260730_0033
Revises: 20260726_0032
"""

from alembic import op
import sqlalchemy as sa


revision = "20260730_0033"
down_revision = "20260726_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portable_artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("relative_path", sa.String(length=512), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('export', 'import')", name="ck_portable_artifacts_kind"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_portable_artifacts_size"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_portable_artifacts_public"),
        sa.UniqueConstraint("relative_path", name="uq_portable_artifacts_path"),
    )
    op.create_index("ix_portable_artifacts_user_created", "portable_artifacts", ["user_id", "created_at"])
    op.create_index("ix_portable_artifacts_expiry", "portable_artifacts", ["expires_at"])

    op.create_table(
        "portable_export_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=24), server_default="requested", nullable=False),
        sa.Column("format_version", sa.String(length=20), server_default="1.0", nullable=False),
        sa.Column("sections_json", sa.JSON(), nullable=False),
        sa.Column("counts_json", sa.JSON(), nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=True),
        sa.Column("artifact_hash", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("include_attachments", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("include_identifiable_profile", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=True),
        sa.Column("date_to", sa.Date(), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint("revision >= 1", name="ck_portable_export_jobs_revision"),
        sa.CheckConstraint("state IN ('requested', 'preparing', 'ready', 'failed', 'expired', 'deleted')", name="ck_portable_export_jobs_state"),
        sa.ForeignKeyConstraint(["artifact_id"], ["portable_artifacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_portable_export_jobs_public"),
        sa.UniqueConstraint("user_id", "idempotency_key_hash", name="uq_portable_export_jobs_idempotency"),
    )
    op.create_index("ix_portable_export_jobs_user_created", "portable_export_jobs", ["user_id", "created_at"])
    op.create_index("ix_portable_export_jobs_expiry", "portable_export_jobs", ["expires_at"])

    op.create_table(
        "portable_import_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), server_default="uploaded", nullable=False),
        sa.Column("format_version", sa.String(length=20), nullable=True),
        sa.Column("sections_json", sa.JSON(), nullable=False),
        sa.Column("counts_json", sa.JSON(), nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=True),
        sa.Column("artifact_hash", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("inspection_json", sa.JSON(), nullable=True),
        sa.Column("plan_json", sa.JSON(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("apply_idempotency_key_hash", sa.String(length=64), nullable=True),
        sa.Column("apply_request_hash", sa.String(length=64), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint("revision >= 1", name="ck_portable_import_jobs_revision"),
        sa.CheckConstraint("state IN ('uploaded', 'inspecting', 'inspection_ready', 'invalid', 'awaiting_confirmation', 'importing', 'completed', 'completed_with_skips', 'failed', 'rolled_back', 'expired')", name="ck_portable_import_jobs_state"),
        sa.ForeignKeyConstraint(["artifact_id"], ["portable_artifacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_portable_import_jobs_public"),
    )
    op.create_index("ix_portable_import_jobs_user_created", "portable_import_jobs", ["user_id", "created_at"])
    op.create_index("ix_portable_import_jobs_expiry", "portable_import_jobs", ["expires_at"])

    op.create_table(
        "portable_import_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("import_job_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=64), nullable=False),
        sa.Column("source_public_id", sa.String(length=36), nullable=False),
        sa.Column("strategy", sa.String(length=48), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_portable_import_decisions_revision"),
        sa.CheckConstraint("strategy IN ('skip_existing', 'import_as_new', 'use_destination', 'update_when_identical_lineage', 'require_manual_resolution')", name="ck_portable_import_decisions_strategy"),
        sa.ForeignKeyConstraint(["import_job_id"], ["portable_import_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_job_id", "section", "source_public_id", name="uq_portable_import_decision_record"),
    )

    op.create_table(
        "portable_import_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("import_job_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=64), nullable=False),
        sa.Column("source_public_id", sa.String(length=36), nullable=False),
        sa.Column("destination_public_id", sa.String(length=36), nullable=False),
        sa.Column("collision_type", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["import_job_id"], ["portable_import_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_job_id", "section", "source_public_id", name="uq_portable_import_mapping_record"),
    )
    op.create_index("ix_portable_import_mappings_user_job", "portable_import_mappings", ["user_id", "import_job_id"])


def downgrade() -> None:
    op.drop_table("portable_import_mappings")
    op.drop_table("portable_import_decisions")
    op.drop_table("portable_import_jobs")
    op.drop_table("portable_export_jobs")
    op.drop_table("portable_artifacts")
