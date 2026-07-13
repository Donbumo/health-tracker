from datetime import datetime, timezone

from app.extensions import db


class ExportRecord(db.Model):
    __tablename__ = "export_records"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('ready', 'deleted', 'expired')",
            name="ck_export_records_status",
        ),
        db.CheckConstraint("size_bytes >= 0", name="ck_export_records_size"),
        db.Index("ix_export_records_user_created", "user_id", "created_at"),
        db.Index("ix_export_records_user_domain", "user_id", "domain"),
        db.Index("ix_export_records_user_status", "user_id", "status"),
        db.UniqueConstraint("relative_path", name="uq_export_records_relative_path"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    domain = db.Column(db.String(64), nullable=False)
    source_type = db.Column(db.String(64), nullable=False)
    source_id = db.Column(db.Integer, nullable=True)
    format = db.Column(db.String(32), nullable=False)
    exporter_version = db.Column(db.String(20), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    relative_path = db.Column(db.String(512), nullable=False)
    media_type = db.Column(db.String(255), nullable=False)
    size_bytes = db.Column(db.BigInteger, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    status = db.Column(
        db.String(20),
        nullable=False,
        default="ready",
        server_default="ready",
    )
    warnings_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.current_timestamp(),
    )
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship("User", back_populates="export_records")
