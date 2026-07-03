from datetime import datetime, timezone

from app.extensions import db


class WeighIn(db.Model):
    __tablename__ = "weigh_ins"
    __table_args__ = (
        db.CheckConstraint("weight_kg > 0", name="ck_weigh_ins_weight"),
        db.CheckConstraint(
            "body_fat_percentage IS NULL OR "
            "(body_fat_percentage >= 0 AND body_fat_percentage <= 100)",
            name="ck_weigh_ins_body_fat_percentage",
        ),
        db.CheckConstraint(
            "muscle_mass_kg IS NULL OR muscle_mass_kg >= 0",
            name="ck_weigh_ins_muscle_mass",
        ),
        db.CheckConstraint(
            "water_percentage IS NULL OR "
            "(water_percentage >= 0 AND water_percentage <= 100)",
            name="ck_weigh_ins_water_percentage",
        ),
        db.CheckConstraint(
            "visceral_fat IS NULL OR visceral_fat >= 0",
            name="ck_weigh_ins_visceral_fat",
        ),
        db.CheckConstraint(
            "bmr_kcal IS NULL OR bmr_kcal >= 0",
            name="ck_weigh_ins_bmr",
        ),
        db.CheckConstraint(
            "bmi IS NULL OR bmi >= 0",
            name="ck_weigh_ins_bmi",
        ),
        db.UniqueConstraint(
            "user_id",
            "recorded_at",
            name="uq_weigh_ins_user_recorded_at",
        ),
        db.UniqueConstraint("source_file_id", name="uq_weigh_ins_source_file"),
        db.Index("ix_weigh_ins_user_recorded", "user_id", "recorded_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    recorded_at = db.Column(db.DateTime(timezone=True), nullable=False)
    weight_kg = db.Column(db.Numeric(8, 3), nullable=False)
    body_fat_percentage = db.Column(db.Numeric(6, 3), nullable=True)
    muscle_mass_kg = db.Column(db.Numeric(8, 3), nullable=True)
    water_percentage = db.Column(db.Numeric(6, 3), nullable=True)
    visceral_fat = db.Column(db.Numeric(8, 3), nullable=True)
    bmr_kcal = db.Column(db.Numeric(10, 2), nullable=True)
    bmi = db.Column(db.Numeric(6, 3), nullable=True)
    source = db.Column(db.String(32), nullable=False)
    source_file_id = db.Column(
        db.Integer,
        db.ForeignKey("uploaded_files.id", ondelete="SET NULL"),
        nullable=True,
    )
    raw_payload_json = db.Column(db.JSON, nullable=True)
    notes = db.Column(db.Text, nullable=True)
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

    user = db.relationship("User", back_populates="weigh_ins")
    source_file = db.relationship("UploadedFile")
