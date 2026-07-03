from datetime import datetime, timezone

from app.extensions import db


class MedicalLabReport(db.Model):
    __tablename__ = "medical_lab_reports"
    __table_args__ = (
        db.UniqueConstraint(
            "source_file_id",
            name="uq_medical_lab_reports_source_file",
        ),
        db.Index("ix_medical_lab_reports_user_date", "user_id", "date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    date = db.Column(db.Date, nullable=False)
    laboratory_name = db.Column(db.String(200), nullable=True)
    doctor_name = db.Column(db.String(200), nullable=True)
    source = db.Column(db.String(32), nullable=False)
    source_file_id = db.Column(
        db.Integer,
        db.ForeignKey("uploaded_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes = db.Column(db.Text, nullable=True)
    raw_payload_json = db.Column(db.JSON, nullable=True)
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

    user = db.relationship("User", back_populates="medical_lab_reports")
    source_file = db.relationship("UploadedFile")
    results = db.relationship(
        "MedicalLabResult",
        back_populates="report",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MedicalLabResult.id",
    )


class MedicalLabResult(db.Model):
    __tablename__ = "medical_lab_results"
    __table_args__ = (
        db.CheckConstraint(
            "value IS NOT NULL OR value_text IS NOT NULL",
            name="ck_medical_lab_results_value",
        ),
        db.CheckConstraint(
            "reference_min IS NULL OR reference_max IS NULL "
            "OR reference_min <= reference_max",
            name="ck_medical_lab_results_reference_range",
        ),
        db.CheckConstraint(
            "status IN ('low', 'normal', 'high', 'unknown')",
            name="ck_medical_lab_results_status",
        ),
        db.Index(
            "ix_medical_lab_results_user_marker",
            "user_id",
            "marker_name",
        ),
        db.Index(
            "ix_medical_lab_results_user_report",
            "user_id",
            "report_id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    report_id = db.Column(
        db.Integer,
        db.ForeignKey("medical_lab_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    marker_name = db.Column(db.String(200), nullable=False)
    marker_code = db.Column(db.String(100), nullable=True)
    value = db.Column(db.Numeric(20, 6), nullable=True)
    value_text = db.Column(db.String(500), nullable=True)
    unit = db.Column(db.String(100), nullable=False)
    reference_min = db.Column(db.Numeric(20, 6), nullable=True)
    reference_max = db.Column(db.Numeric(20, 6), nullable=True)
    reference_text = db.Column(db.String(500), nullable=True)
    status = db.Column(
        db.String(20),
        nullable=False,
        default="unknown",
        server_default="unknown",
    )
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.current_timestamp(),
    )

    report = db.relationship("MedicalLabReport", back_populates="results")
