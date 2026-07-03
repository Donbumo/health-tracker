from datetime import datetime, timezone

from app.extensions import db


class TrainingPlan(db.Model):
    __tablename__ = "training_plans"
    __table_args__ = (
        db.CheckConstraint(
            "active_version_number >= 1",
            name="ck_training_plans_active_version_number",
        ),
        db.Index("ix_training_plans_user_created", "user_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    active_version_number = db.Column(
        db.Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
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

    user = db.relationship("User", back_populates="training_plans")
    versions = db.relationship(
        "TrainingPlanVersion",
        back_populates="training_plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TrainingPlanVersion.version_number",
    )
    sessions = db.relationship(
        "TrainingSession",
        back_populates="training_plan",
        passive_deletes=True,
    )


class TrainingPlanVersion(db.Model):
    __tablename__ = "training_plan_versions"
    __table_args__ = (
        db.CheckConstraint(
            "version_number >= 1",
            name="ck_training_plan_versions_version_number",
        ),
        db.UniqueConstraint(
            "training_plan_id",
            "version_number",
            name="uq_training_plan_versions_plan_number",
        ),
        db.UniqueConstraint(
            "training_plan_id",
            "sha256",
            name="uq_training_plan_versions_plan_sha256",
        ),
        db.UniqueConstraint(
            "source_file_id",
            name="uq_training_plan_versions_source_file",
        ),
        db.Index(
            "ix_training_plan_versions_user_created",
            "user_id",
            "created_at",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    training_plan_id = db.Column(
        db.Integer,
        db.ForeignKey("training_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number = db.Column(db.Integer, nullable=False)
    source_file_id = db.Column(
        db.Integer,
        db.ForeignKey("uploaded_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    change_reason = db.Column(db.Text, nullable=True)
    schema_version = db.Column(db.String(20), nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    content = db.Column(db.JSON, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.current_timestamp(),
    )

    training_plan = db.relationship("TrainingPlan", back_populates="versions")
    source_file = db.relationship("UploadedFile")
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])
    sessions = db.relationship(
        "TrainingSession",
        back_populates="training_plan_version",
        passive_deletes=True,
    )
