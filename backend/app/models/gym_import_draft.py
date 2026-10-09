"""Owner-private interactive imports, independent of upload storage."""
import uuid
from datetime import datetime, timezone

from app.extensions import db


class GymImportDraft(db.Model):
    __tablename__ = "gym_import_drafts"
    __table_args__ = (
        db.CheckConstraint("state IN ('pending', 'completed', 'cancelled')", name="ck_gym_import_drafts_state"),
        db.CheckConstraint("revision >= 1", name="ck_gym_import_drafts_revision"),
        db.Index("ix_gym_import_drafts_user_state", "user_id", "state", "updated_at"),
    )
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    target_plan_id = db.Column(db.Integer, db.ForeignKey("training_plans.id", ondelete="SET NULL"))
    target_public_id = db.Column(db.String(36))
    base_revision = db.Column(db.Integer)
    result_plan_id = db.Column(db.Integer, db.ForeignKey("training_plans.id", ondelete="SET NULL"))
    source_type = db.Column(db.String(32), nullable=False)
    payload_json = db.Column(db.JSON, nullable=False)
    state = db.Column(db.String(16), nullable=False, default="pending", server_default="pending")
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=db.func.current_timestamp())
