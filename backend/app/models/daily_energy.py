from datetime import datetime, timezone

from app.extensions import db


class DailyEnergy(db.Model):
    __tablename__ = "daily_energy"
    __table_args__ = (
        db.CheckConstraint(
            "total_calories IS NULL OR total_calories >= 0",
            name="ck_daily_energy_total_calories",
        ),
        db.CheckConstraint(
            "active_calories IS NULL OR active_calories >= 0",
            name="ck_daily_energy_active_calories",
        ),
        db.CheckConstraint(
            "resting_calories IS NULL OR resting_calories >= 0",
            name="ck_daily_energy_resting_calories",
        ),
        db.CheckConstraint(
            "steps IS NULL OR steps >= 0",
            name="ck_daily_energy_steps",
        ),
        db.CheckConstraint(
            "distance_meters IS NULL OR distance_meters >= 0",
            name="ck_daily_energy_distance",
        ),
        db.UniqueConstraint(
            "user_id",
            "date",
            name="uq_daily_energy_user_date",
        ),
        db.UniqueConstraint(
            "source_file_id",
            name="uq_daily_energy_source_file",
        ),
        db.Index("ix_daily_energy_user_date", "user_id", "date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    date = db.Column(db.Date, nullable=False)
    total_calories = db.Column(db.Numeric(10, 2), nullable=True)
    active_calories = db.Column(db.Numeric(10, 2), nullable=True)
    resting_calories = db.Column(db.Numeric(10, 2), nullable=True)
    steps = db.Column(db.BigInteger, nullable=True)
    distance_meters = db.Column(db.Numeric(12, 2), nullable=True)
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

    user = db.relationship("User", back_populates="daily_energy_records")
    source_file = db.relationship("UploadedFile")
