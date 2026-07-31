from datetime import datetime, timezone
import uuid

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class PortableArtifact(db.Model):
    __tablename__ = "portable_artifacts"
    __table_args__ = (
        db.CheckConstraint("kind IN ('export', 'import')", name="ck_portable_artifacts_kind"),
        db.CheckConstraint("size_bytes >= 0", name="ck_portable_artifacts_size"),
        db.UniqueConstraint("public_id", name="uq_portable_artifacts_public"),
        db.UniqueConstraint("relative_path", name="uq_portable_artifacts_path"),
        db.Index("ix_portable_artifacts_user_created", "user_id", "created_at"),
        db.Index("ix_portable_artifacts_expiry", "expires_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind = db.Column(db.String(16), nullable=False)
    relative_path = db.Column(db.String(512), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    media_type = db.Column(db.String(100), nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    size_bytes = db.Column(db.BigInteger, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, server_default=db.func.current_timestamp())
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)


class PortableExportJob(db.Model):
    __tablename__ = "portable_export_jobs"
    __table_args__ = (
        db.CheckConstraint(
            "state IN ('requested', 'preparing', 'ready', 'failed', 'expired', 'deleted')",
            name="ck_portable_export_jobs_state",
        ),
        db.CheckConstraint("revision >= 1", name="ck_portable_export_jobs_revision"),
        db.UniqueConstraint("public_id", name="uq_portable_export_jobs_public"),
        db.UniqueConstraint("user_id", "idempotency_key_hash", name="uq_portable_export_jobs_idempotency"),
        db.Index("ix_portable_export_jobs_user_created", "user_id", "created_at"),
        db.Index("ix_portable_export_jobs_expiry", "expires_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    state = db.Column(db.String(24), nullable=False, default="requested", server_default="requested")
    format_version = db.Column(db.String(20), nullable=False, default="1.0", server_default="1.0")
    sections_json = db.Column(db.JSON, nullable=False)
    counts_json = db.Column(db.JSON, nullable=False, default=dict)
    artifact_id = db.Column(db.Integer, db.ForeignKey("portable_artifacts.id", ondelete="SET NULL"), nullable=True)
    artifact_hash = db.Column(db.String(64), nullable=True)
    size_bytes = db.Column(db.BigInteger, nullable=True)
    include_attachments = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    include_identifiable_profile = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    date_from = db.Column(db.Date, nullable=True)
    date_to = db.Column(db.Date, nullable=True)
    request_hash = db.Column(db.String(64), nullable=False)
    idempotency_key_hash = db.Column(db.String(64), nullable=False)
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, server_default=db.func.current_timestamp())
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    error_code = db.Column(db.String(64), nullable=True)

    artifact = db.relationship("PortableArtifact", foreign_keys=[artifact_id])


class PortableImportJob(db.Model):
    __tablename__ = "portable_import_jobs"
    __table_args__ = (
        db.CheckConstraint(
            "state IN ('uploaded', 'inspecting', 'inspection_ready', 'invalid', "
            "'awaiting_confirmation', 'importing', 'completed', 'completed_with_skips', "
            "'failed', 'rolled_back', 'expired')",
            name="ck_portable_import_jobs_state",
        ),
        db.CheckConstraint("revision >= 1", name="ck_portable_import_jobs_revision"),
        db.UniqueConstraint("public_id", name="uq_portable_import_jobs_public"),
        db.Index("ix_portable_import_jobs_user_created", "user_id", "created_at"),
        db.Index("ix_portable_import_jobs_expiry", "expires_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    state = db.Column(db.String(32), nullable=False, default="uploaded", server_default="uploaded")
    format_version = db.Column(db.String(20), nullable=True)
    sections_json = db.Column(db.JSON, nullable=False, default=list)
    counts_json = db.Column(db.JSON, nullable=False, default=dict)
    artifact_id = db.Column(db.Integer, db.ForeignKey("portable_artifacts.id", ondelete="SET NULL"), nullable=True)
    artifact_hash = db.Column(db.String(64), nullable=False)
    size_bytes = db.Column(db.BigInteger, nullable=False)
    inspection_json = db.Column(db.JSON, nullable=True)
    plan_json = db.Column(db.JSON, nullable=True)
    result_json = db.Column(db.JSON, nullable=True)
    apply_idempotency_key_hash = db.Column(db.String(64), nullable=True)
    apply_request_hash = db.Column(db.String(64), nullable=True)
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, server_default=db.func.current_timestamp())
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    error_code = db.Column(db.String(64), nullable=True)

    artifact = db.relationship("PortableArtifact", foreign_keys=[artifact_id])
    decisions = db.relationship("PortableImportDecision", cascade="all, delete-orphan", passive_deletes=True)
    mappings = db.relationship("PortableImportMapping", cascade="all, delete-orphan", passive_deletes=True)


class PortableImportDecision(db.Model):
    __tablename__ = "portable_import_decisions"
    __table_args__ = (
        db.CheckConstraint(
            "strategy IN ('skip_existing', 'import_as_new', 'use_destination', "
            "'update_when_identical_lineage', 'require_manual_resolution')",
            name="ck_portable_import_decisions_strategy",
        ),
        db.CheckConstraint("revision >= 1", name="ck_portable_import_decisions_revision"),
        db.UniqueConstraint("import_job_id", "section", "source_public_id", name="uq_portable_import_decision_record"),
    )

    id = db.Column(db.Integer, primary_key=True)
    import_job_id = db.Column(db.Integer, db.ForeignKey("portable_import_jobs.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    section = db.Column(db.String(64), nullable=False)
    source_public_id = db.Column(db.String(36), nullable=False)
    strategy = db.Column(db.String(48), nullable=False)
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, server_default=db.func.current_timestamp())


class PortableImportMapping(db.Model):
    __tablename__ = "portable_import_mappings"
    __table_args__ = (
        db.UniqueConstraint("import_job_id", "section", "source_public_id", name="uq_portable_import_mapping_record"),
        db.Index("ix_portable_import_mappings_user_job", "user_id", "import_job_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    import_job_id = db.Column(db.Integer, db.ForeignKey("portable_import_jobs.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    section = db.Column(db.String(64), nullable=False)
    source_public_id = db.Column(db.String(36), nullable=False)
    destination_public_id = db.Column(db.String(36), nullable=False)
    collision_type = db.Column(db.String(32), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, server_default=db.func.current_timestamp())
