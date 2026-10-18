"""Canonical day registry; DailyEnergy remains the source/mobile identity table."""
from datetime import datetime, timezone

from app.extensions import db


class EnergyDay(db.Model):
    __tablename__ = "energy_days"
    __table_args__ = (
        db.UniqueConstraint("user_id", "date", name="uq_energy_day_user_date"),
        db.CheckConstraint("revision >= 1", name="ck_energy_day_revision"),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    resolutions_json = db.Column(db.JSON, nullable=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)


class EnergyEvidenceEvent(db.Model):
    """Private audit of accepted, conflicting and explicitly removed source data.

    No filesystem paths or credentials; original uploads remain owner scoped.
    Events are append-only and are never interpreted as additive expenditure.
    """
    __tablename__ = "energy_evidence_events"
    __table_args__ = (
        db.UniqueConstraint("user_id", "event_key", name="uq_energy_event_owner_key"),
        db.Index("ix_energy_event_owner_date", "user_id", "date"),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    evidence_public_id = db.Column(db.String(36), nullable=False)
    event_key = db.Column(db.String(64), nullable=False)
    kind = db.Column(db.String(24), nullable=False)
    source_file_id = db.Column(db.Integer, db.ForeignKey("uploaded_files.id", ondelete="SET NULL"), nullable=True)
    source_file_sha256 = db.Column(db.String(64), nullable=True)
    payload_json = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=db.func.current_timestamp())
