"""Add owner-scoped medical studies, documents, panels and lab results.

Revision ID: 20260731_0035
Revises: 20260731_0034
"""

from alembic import op
import sqlalchemy as sa


revision = "20260731_0035"
down_revision = "20260731_0034"
branch_labels = None
depends_on = None


def _values(values):
    return ",".join(f"'{value}'" for value in values)


STUDY_TYPES = (
    "laboratory", "imaging", "clinical_document", "prescription_document",
    "vaccination_document", "other",
)
VALUE_TYPES = (
    "numeric", "text", "categorical", "positive_negative",
    "detected_not_detected", "unknown",
)
COMPARATORS = (
    "equal", "less_than", "less_or_equal", "greater_than",
    "greater_or_equal", "approximate", "none",
)
SOURCE_STATUSES = (
    "low", "within_range", "high", "abnormal", "critical_as_reported",
    "indeterminate", "not_provided",
)
DERIVED_STATUSES = (
    "below_reported_range", "within_reported_range", "above_reported_range",
    "not_computable",
)
DUPLICATE_STATUSES = (
    "exact_document_duplicate", "exact_structured_duplicate",
    "probable_duplicate", "possible_duplicate", "distinct",
)


def upgrade() -> None:
    op.create_table(
        "medical_studies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("study_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("laboratory_name", sa.String(length=200), nullable=True),
        sa.Column("professional_name", sa.String(length=200), nullable=True),
        sa.Column("study_date", sa.Date(), nullable=False),
        sa.Column("issued_date", sa.Date(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("source", sa.String(length=32), server_default="manual", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("structured_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(f"study_type IN ({_values(STUDY_TYPES)})", name="ck_medical_studies_type"),
        sa.CheckConstraint("state IN ('draft','complete','archived')", name="ck_medical_studies_state"),
        sa.CheckConstraint("revision >= 1", name="ck_medical_studies_revision"),
        sa.CheckConstraint("issued_date IS NULL OR issued_date >= study_date", name="ck_medical_studies_dates"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_medical_studies_public_id"),
    )
    op.create_index("ix_medical_studies_user_date_state", "medical_studies", ["user_id", "study_date", "state"])
    op.create_index("ix_medical_studies_user_fingerprint", "medical_studies", ["user_id", "structured_fingerprint"])

    op.create_table(
        "medical_study_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("study_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_reference", sa.String(length=120), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["medical_studies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_medical_study_sources_public_id"),
    )
    op.create_index("ix_medical_study_sources_user_study", "medical_study_sources", ["user_id", "study_id"])

    op.create_table(
        "lab_panels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("study_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source", sa.String(length=32), server_default="manual", nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("display_order >= 0", name="ck_lab_panels_order"),
        sa.CheckConstraint("revision >= 1", name="ck_lab_panels_revision"),
        sa.ForeignKeyConstraint(["study_id"], ["medical_studies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_lab_panels_public_id"),
        sa.UniqueConstraint("study_id", "display_order", name="uq_lab_panels_study_order"),
    )
    op.create_index("ix_lab_panels_user_study", "lab_panels", ["user_id", "study_id"])

    op.create_table(
        "lab_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("panel_id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("canonical_key", sa.String(length=100), nullable=True),
        sa.Column("value_type", sa.String(length=32), nullable=False),
        sa.Column("original_value", sa.String(length=500), nullable=False),
        sa.Column("numeric_value", sa.Numeric(precision=30, scale=10), nullable=True),
        sa.Column("comparator", sa.String(length=24), server_default="none", nullable=False),
        sa.Column("original_unit", sa.String(length=100), nullable=True),
        sa.Column("canonical_unit", sa.String(length=100), nullable=True),
        sa.Column("reference_lower", sa.Numeric(precision=30, scale=10), nullable=True),
        sa.Column("reference_upper", sa.Numeric(precision=30, scale=10), nullable=True),
        sa.Column("reference_text", sa.String(length=500), nullable=True),
        sa.Column("source_status", sa.String(length=32), server_default="not_provided", nullable=False),
        sa.Column("derived_range_status", sa.String(length=32), server_default="not_computable", nullable=False),
        sa.Column("method", sa.String(length=200), nullable=True),
        sa.Column("specimen", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("source", sa.String(length=32), server_default="manual", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(f"value_type IN ({_values(VALUE_TYPES)})", name="ck_lab_results_value_type"),
        sa.CheckConstraint(f"comparator IN ({_values(COMPARATORS)})", name="ck_lab_results_comparator"),
        sa.CheckConstraint(f"source_status IN ({_values(SOURCE_STATUSES)})", name="ck_lab_results_source_status"),
        sa.CheckConstraint(f"derived_range_status IN ({_values(DERIVED_STATUSES)})", name="ck_lab_results_derived_status"),
        sa.CheckConstraint("revision >= 1", name="ck_lab_results_revision"),
        sa.CheckConstraint("display_order >= 0", name="ck_lab_results_order"),
        sa.CheckConstraint("reference_lower IS NULL OR reference_upper IS NULL OR reference_lower <= reference_upper", name="ck_lab_results_reference_range"),
        sa.CheckConstraint("value_type != 'numeric' OR numeric_value IS NOT NULL", name="ck_lab_results_numeric_value"),
        sa.ForeignKeyConstraint(["panel_id"], ["lab_panels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_lab_results_public_id"),
        sa.UniqueConstraint("panel_id", "display_order", name="uq_lab_results_panel_order"),
    )
    op.create_index("ix_lab_results_user_panel", "lab_results", ["user_id", "panel_id"])
    op.create_index("ix_lab_results_user_canonical", "lab_results", ["user_id", "canonical_key"])

    op.create_table(
        "lab_result_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("result_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("correction_reason", sa.String(length=500), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_lab_result_revisions_revision"),
        sa.ForeignKeyConstraint(["result_id"], ["lab_results.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_lab_result_revisions_public_id"),
        sa.UniqueConstraint("result_id", "revision", name="uq_lab_result_revisions_result_revision"),
    )
    op.create_index("ix_lab_result_revisions_user_result", "lab_result_revisions", ["user_id", "result_id"])

    op.create_table(
        "medical_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("study_id", sa.Integer(), nullable=False),
        sa.Column("uploaded_file_id", sa.Integer(), nullable=True),
        sa.Column("document_type", sa.String(length=32), server_default="original", nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("availability", sa.String(length=20), server_default="available", nullable=False),
        sa.Column("source", sa.String(length=32), server_default="manual", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_medical_documents_revision"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_medical_documents_size"),
        sa.ForeignKeyConstraint(["study_id"], ["medical_studies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_file_id"], ["uploaded_files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_medical_documents_public_id"),
        sa.UniqueConstraint("user_id", "study_id", "sha256", name="uq_medical_documents_study_hash"),
    )
    op.create_index("ix_medical_documents_user_study", "medical_documents", ["user_id", "study_id"])
    op.create_index("ix_medical_documents_user_hash", "medical_documents", ["user_id", "sha256"])

    op.create_table(
        "medical_duplicate_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("left_study_id", sa.Integer(), nullable=False),
        sa.Column("right_study_id", sa.Integer(), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("resolution", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"classification IN ({_values(DUPLICATE_STATUSES)})", name="ck_medical_duplicates_classification"),
        sa.ForeignKeyConstraint(["left_study_id"], ["medical_studies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["right_study_id"], ["medical_studies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_medical_duplicates_public_id"),
        sa.UniqueConstraint("user_id", "left_study_id", "right_study_id", name="uq_medical_duplicates_pair"),
    )
    op.create_index("ix_medical_duplicates_user_state", "medical_duplicate_candidates", ["user_id", "resolution"])

    op.create_table(
        "medical_audit_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("study_public_id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_public_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=48), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_medical_audit_events_public_id"),
    )
    op.create_index("ix_medical_audit_user_created", "medical_audit_events", ["user_id", "created_at"])
    op.create_index("ix_medical_audit_user_study", "medical_audit_events", ["user_id", "study_public_id"])


def downgrade() -> None:
    op.drop_table("medical_audit_events")
    op.drop_table("medical_duplicate_candidates")
    op.drop_table("medical_documents")
    op.drop_table("lab_result_revisions")
    op.drop_table("lab_results")
    op.drop_table("lab_panels")
    op.drop_table("medical_study_sources")
    op.drop_table("medical_studies")
