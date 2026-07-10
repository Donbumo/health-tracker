from datetime import datetime, timezone

from app.extensions import db


class ImportRun(db.Model):
    __tablename__ = "import_runs"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'blocked')",
            name="ck_import_runs_status",
        ),
        db.CheckConstraint("target_type <> ''", name="ck_import_runs_target_type"),
        db.CheckConstraint("total_count >= 0", name="ck_import_runs_total_count"),
        db.CheckConstraint("insert_count >= 0", name="ck_import_runs_insert_count"),
        db.CheckConstraint("update_count >= 0", name="ck_import_runs_update_count"),
        db.CheckConstraint("skip_count >= 0", name="ck_import_runs_skip_count"),
        db.CheckConstraint("conflict_count >= 0", name="ck_import_runs_conflict_count"),
        db.CheckConstraint("invalid_count >= 0", name="ck_import_runs_invalid_count"),
        db.CheckConstraint("LENGTH(payload_sha256) = 64", name="ck_import_runs_payload_sha"),
        db.CheckConstraint("LENGTH(plan_sha256) = 64", name="ck_import_runs_plan_sha"),
        db.Index("ix_import_runs_user_started", "user_id", "started_at"),
        db.Index("ix_import_runs_user_status", "user_id", "status"),
        db.Index("ix_import_runs_user_target", "user_id", "target_type"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_type = db.Column(db.String(64), nullable=False)
    source_type = db.Column(db.String(32), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending", server_default="pending")
    started_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.current_timestamp(),
    )
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    total_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    insert_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    update_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    skip_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    conflict_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    invalid_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    payload_sha256 = db.Column(db.String(64), nullable=False)
    plan_sha256 = db.Column(db.String(64), nullable=False)
    error_code = db.Column(db.String(64), nullable=True)
    error_message = db.Column(db.String(500), nullable=True)
    metadata_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.current_timestamp(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=db.func.current_timestamp(),
    )

    user = db.relationship("User", back_populates="import_runs")
