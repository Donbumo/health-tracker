from __future__ import annotations

from datetime import datetime, timezone
import uuid

from app.extensions import db


STUDY_TYPES = (
    "laboratory",
    "imaging",
    "clinical_document",
    "prescription_document",
    "vaccination_document",
    "other",
)
STUDY_STATES = ("draft", "complete", "archived")
VALUE_TYPES = (
    "numeric",
    "text",
    "categorical",
    "positive_negative",
    "detected_not_detected",
    "unknown",
)
COMPARATORS = (
    "equal",
    "less_than",
    "less_or_equal",
    "greater_than",
    "greater_or_equal",
    "approximate",
    "none",
)
SOURCE_STATUSES = (
    "low",
    "within_range",
    "high",
    "abnormal",
    "critical_as_reported",
    "indeterminate",
    "not_provided",
)
DERIVED_RANGE_STATUSES = (
    "below_reported_range",
    "within_reported_range",
    "above_reported_range",
    "not_computable",
)
DUPLICATE_STATUSES = (
    "exact_document_duplicate",
    "exact_structured_duplicate",
    "probable_duplicate",
    "possible_duplicate",
    "distinct",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def public_uuid() -> str:
    return str(uuid.uuid4())


def _values(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


class MedicalStudy(db.Model):
    __tablename__ = "medical_studies"
    __table_args__ = (
        db.CheckConstraint(
            f"study_type IN ({_values(STUDY_TYPES)})",
            name="ck_medical_studies_type",
        ),
        db.CheckConstraint(
            f"state IN ({_values(STUDY_STATES)})",
            name="ck_medical_studies_state",
        ),
        db.CheckConstraint("revision >= 1", name="ck_medical_studies_revision"),
        db.CheckConstraint(
            "issued_date IS NULL OR issued_date >= study_date",
            name="ck_medical_studies_dates",
        ),
        db.UniqueConstraint("public_id", name="uq_medical_studies_public_id"),
        db.Index(
            "ix_medical_studies_user_date_state",
            "user_id",
            "study_date",
            "state",
        ),
        db.Index(
            "ix_medical_studies_user_fingerprint",
            "user_id",
            "structured_fingerprint",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=public_uuid)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    study_type = db.Column(db.String(32), nullable=False)
    title = db.Column(db.String(240), nullable=False)
    laboratory_name = db.Column(db.String(200), nullable=True)
    professional_name = db.Column(db.String(200), nullable=True)
    study_date = db.Column(db.Date, nullable=False)
    issued_date = db.Column(db.Date, nullable=True)
    timezone = db.Column(db.String(64), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    state = db.Column(
        db.String(16), nullable=False, default="draft", server_default="draft"
    )
    source = db.Column(
        db.String(32), nullable=False, default="manual", server_default="manual"
    )
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    structured_fingerprint = db.Column(db.String(64), nullable=True)
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

    panels = db.relationship(
        "LabPanel",
        back_populates="study",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="LabPanel.display_order",
    )
    documents = db.relationship(
        "MedicalDocument",
        back_populates="study",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MedicalDocument.created_at",
    )
    sources = db.relationship(
        "MedicalStudySource",
        back_populates="study",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MedicalStudySource.created_at",
    )


class MedicalStudySource(db.Model):
    __tablename__ = "medical_study_sources"
    __table_args__ = (
        db.UniqueConstraint("public_id", name="uq_medical_study_sources_public_id"),
        db.Index("ix_medical_study_sources_user_study", "user_id", "study_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=public_uuid)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    study_id = db.Column(
        db.Integer,
        db.ForeignKey("medical_studies.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_type = db.Column(db.String(32), nullable=False)
    source_reference = db.Column(db.String(120), nullable=True)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=db.func.current_timestamp(),
    )

    study = db.relationship("MedicalStudy", back_populates="sources")


class LabPanel(db.Model):
    __tablename__ = "lab_panels"
    __table_args__ = (
        db.CheckConstraint("display_order >= 0", name="ck_lab_panels_order"),
        db.CheckConstraint("revision >= 1", name="ck_lab_panels_revision"),
        db.UniqueConstraint("public_id", name="uq_lab_panels_public_id"),
        db.UniqueConstraint(
            "study_id", "display_order", name="uq_lab_panels_study_order"
        ),
        db.Index("ix_lab_panels_user_study", "user_id", "study_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=public_uuid)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    study_id = db.Column(
        db.Integer,
        db.ForeignKey("medical_studies.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = db.Column(db.String(200), nullable=False)
    display_order = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    source = db.Column(
        db.String(32), nullable=False, default="manual", server_default="manual"
    )
    fingerprint = db.Column(db.String(64), nullable=True)
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow,
        server_default=db.func.current_timestamp(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow,
        server_default=db.func.current_timestamp(),
    )

    study = db.relationship("MedicalStudy", back_populates="panels")
    results = db.relationship(
        "LabResult",
        back_populates="panel",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="LabResult.display_order",
    )


class LabResult(db.Model):
    __tablename__ = "lab_results"
    __table_args__ = (
        db.CheckConstraint(
            f"value_type IN ({_values(VALUE_TYPES)})",
            name="ck_lab_results_value_type",
        ),
        db.CheckConstraint(
            f"comparator IN ({_values(COMPARATORS)})",
            name="ck_lab_results_comparator",
        ),
        db.CheckConstraint(
            f"source_status IN ({_values(SOURCE_STATUSES)})",
            name="ck_lab_results_source_status",
        ),
        db.CheckConstraint(
            f"derived_range_status IN ({_values(DERIVED_RANGE_STATUSES)})",
            name="ck_lab_results_derived_status",
        ),
        db.CheckConstraint("revision >= 1", name="ck_lab_results_revision"),
        db.CheckConstraint("display_order >= 0", name="ck_lab_results_order"),
        db.CheckConstraint(
            "reference_lower IS NULL OR reference_upper IS NULL "
            "OR reference_lower <= reference_upper",
            name="ck_lab_results_reference_range",
        ),
        db.CheckConstraint(
            "value_type != 'numeric' OR numeric_value IS NOT NULL",
            name="ck_lab_results_numeric_value",
        ),
        db.UniqueConstraint("public_id", name="uq_lab_results_public_id"),
        db.UniqueConstraint(
            "panel_id", "display_order", name="uq_lab_results_panel_order"
        ),
        db.Index("ix_lab_results_user_panel", "user_id", "panel_id"),
        db.Index(
            "ix_lab_results_user_canonical", "user_id", "canonical_key"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=public_uuid)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    panel_id = db.Column(
        db.Integer, db.ForeignKey("lab_panels.id", ondelete="CASCADE"), nullable=False
    )
    display_name = db.Column(db.String(200), nullable=False)
    canonical_key = db.Column(db.String(100), nullable=True)
    value_type = db.Column(db.String(32), nullable=False)
    original_value = db.Column(db.String(500), nullable=False)
    numeric_value = db.Column(db.Numeric(30, 10), nullable=True)
    comparator = db.Column(
        db.String(24), nullable=False, default="none", server_default="none"
    )
    original_unit = db.Column(db.String(100), nullable=True)
    canonical_unit = db.Column(db.String(100), nullable=True)
    reference_lower = db.Column(db.Numeric(30, 10), nullable=True)
    reference_upper = db.Column(db.Numeric(30, 10), nullable=True)
    reference_text = db.Column(db.String(500), nullable=True)
    source_status = db.Column(
        db.String(32),
        nullable=False,
        default="not_provided",
        server_default="not_provided",
    )
    derived_range_status = db.Column(
        db.String(32),
        nullable=False,
        default="not_computable",
        server_default="not_computable",
    )
    method = db.Column(db.String(200), nullable=True)
    specimen = db.Column(db.String(200), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    display_order = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    source = db.Column(
        db.String(32), nullable=False, default="manual", server_default="manual"
    )
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow,
        server_default=db.func.current_timestamp(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow,
        server_default=db.func.current_timestamp(),
    )

    panel = db.relationship("LabPanel", back_populates="results")
    revisions = db.relationship(
        "LabResultRevision",
        back_populates="result",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="LabResultRevision.revision",
    )


class LabResultRevision(db.Model):
    __tablename__ = "lab_result_revisions"
    __table_args__ = (
        db.CheckConstraint("revision >= 1", name="ck_lab_result_revisions_revision"),
        db.UniqueConstraint("public_id", name="uq_lab_result_revisions_public_id"),
        db.UniqueConstraint(
            "result_id", "revision", name="uq_lab_result_revisions_result_revision"
        ),
        db.Index("ix_lab_result_revisions_user_result", "user_id", "result_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=public_uuid)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    result_id = db.Column(
        db.Integer, db.ForeignKey("lab_results.id", ondelete="CASCADE"), nullable=False
    )
    revision = db.Column(db.Integer, nullable=False)
    snapshot_json = db.Column(db.JSON, nullable=False)
    correction_reason = db.Column(db.String(500), nullable=True)
    source = db.Column(db.String(32), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow,
        server_default=db.func.current_timestamp(),
    )

    result = db.relationship("LabResult", back_populates="revisions")


class MedicalDocument(db.Model):
    __tablename__ = "medical_documents"
    __table_args__ = (
        db.CheckConstraint("revision >= 1", name="ck_medical_documents_revision"),
        db.CheckConstraint("size_bytes >= 0", name="ck_medical_documents_size"),
        db.UniqueConstraint("public_id", name="uq_medical_documents_public_id"),
        db.UniqueConstraint(
            "user_id",
            "study_id",
            "sha256",
            name="uq_medical_documents_study_hash",
        ),
        db.Index("ix_medical_documents_user_study", "user_id", "study_id"),
        db.Index("ix_medical_documents_user_hash", "user_id", "sha256"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=public_uuid)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    study_id = db.Column(
        db.Integer,
        db.ForeignKey("medical_studies.id", ondelete="CASCADE"),
        nullable=False,
    )
    uploaded_file_id = db.Column(
        db.Integer,
        db.ForeignKey("uploaded_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    document_type = db.Column(
        db.String(32), nullable=False, default="original", server_default="original"
    )
    original_filename = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    size_bytes = db.Column(db.BigInteger, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    availability = db.Column(
        db.String(20), nullable=False, default="available", server_default="available"
    )
    source = db.Column(
        db.String(32), nullable=False, default="manual", server_default="manual"
    )
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow,
        server_default=db.func.current_timestamp(),
    )

    study = db.relationship("MedicalStudy", back_populates="documents")
    uploaded_file = db.relationship("UploadedFile")


class MedicalDuplicateCandidate(db.Model):
    __tablename__ = "medical_duplicate_candidates"
    __table_args__ = (
        db.CheckConstraint(
            f"classification IN ({_values(DUPLICATE_STATUSES)})",
            name="ck_medical_duplicates_classification",
        ),
        db.UniqueConstraint("public_id", name="uq_medical_duplicates_public_id"),
        db.UniqueConstraint(
            "user_id", "left_study_id", "right_study_id",
            name="uq_medical_duplicates_pair",
        ),
        db.Index("ix_medical_duplicates_user_state", "user_id", "resolution"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=public_uuid)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    left_study_id = db.Column(
        db.Integer, db.ForeignKey("medical_studies.id", ondelete="CASCADE"), nullable=False
    )
    right_study_id = db.Column(
        db.Integer, db.ForeignKey("medical_studies.id", ondelete="CASCADE"), nullable=False
    )
    classification = db.Column(db.String(32), nullable=False)
    evidence_json = db.Column(db.JSON, nullable=False, default=dict)
    resolution = db.Column(
        db.String(20), nullable=False, default="pending", server_default="pending"
    )
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow,
        server_default=db.func.current_timestamp(),
    )
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)


class MedicalAuditEvent(db.Model):
    __tablename__ = "medical_audit_events"
    __table_args__ = (
        db.UniqueConstraint("public_id", name="uq_medical_audit_events_public_id"),
        db.Index("ix_medical_audit_user_created", "user_id", "created_at"),
        db.Index("ix_medical_audit_user_study", "user_id", "study_public_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=public_uuid)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    study_public_id = db.Column(db.String(36), nullable=False)
    entity_type = db.Column(db.String(32), nullable=False)
    entity_public_id = db.Column(db.String(36), nullable=True)
    action = db.Column(db.String(48), nullable=False)
    details_json = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow,
        server_default=db.func.current_timestamp(),
    )
