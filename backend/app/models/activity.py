from datetime import datetime, timezone

from app.extensions import db


class Activity(db.Model):
    __tablename__ = "activities"
    __table_args__ = (
        db.CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="ck_activities_duration"),
        db.CheckConstraint("moving_time_seconds IS NULL OR moving_time_seconds >= 0", name="ck_activities_moving_time"),
        db.CheckConstraint("distance_meters IS NULL OR distance_meters >= 0", name="ck_activities_distance"),
        db.CheckConstraint("calories_kcal IS NULL OR calories_kcal >= 0", name="ck_activities_calories"),
        db.CheckConstraint("point_count >= 0", name="ck_activities_point_count"),
        db.UniqueConstraint("user_id", "fingerprint_sha256", name="uq_activities_user_fingerprint"),
        db.Index("ix_activities_user_started", "user_id", "started_at"),
        db.Index("ix_activities_user_type", "user_id", "activity_type"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    activity_type = db.Column(db.String(64), nullable=False)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False)
    ended_at = db.Column(db.DateTime(timezone=True), nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)
    moving_time_seconds = db.Column(db.Integer, nullable=True)
    distance_meters = db.Column(db.Numeric(12, 2), nullable=True)
    calories_kcal = db.Column(db.Numeric(10, 2), nullable=True)
    avg_heart_rate_bpm = db.Column(db.Integer, nullable=True)
    max_heart_rate_bpm = db.Column(db.Integer, nullable=True)
    avg_cadence_rpm = db.Column(db.Numeric(8, 2), nullable=True)
    max_cadence_rpm = db.Column(db.Numeric(8, 2), nullable=True)
    avg_speed_mps = db.Column(db.Numeric(10, 4), nullable=True)
    max_speed_mps = db.Column(db.Numeric(10, 4), nullable=True)
    elevation_gain_meters = db.Column(db.Numeric(10, 2), nullable=True)
    elevation_loss_meters = db.Column(db.Numeric(10, 2), nullable=True)
    avg_power_watts = db.Column(db.Integer, nullable=True)
    max_power_watts = db.Column(db.Integer, nullable=True)
    sport_profile = db.Column(db.String(128), nullable=True)
    manufacturer = db.Column(db.String(128), nullable=True)
    product = db.Column(db.String(128), nullable=True)
    source_app = db.Column(db.String(128), nullable=True)
    source_type = db.Column(db.String(32), nullable=False, default="uploaded", server_default="uploaded")
    source_file_id = db.Column(db.Integer, db.ForeignKey("uploaded_files.id", ondelete="SET NULL"), nullable=True)
    fingerprint_sha256 = db.Column(db.String(64), nullable=False)
    canonical_json = db.Column(db.JSON, nullable=False)
    laps_json = db.Column(db.JSON, nullable=True)
    track_json = db.Column(db.JSON, nullable=True)
    bounds_json = db.Column(db.JSON, nullable=True)
    point_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    warnings_json = db.Column(db.JSON, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=db.func.current_timestamp())

    user = db.relationship("User", back_populates="activities")
    source_file = db.relationship("UploadedFile")


class Route(db.Model):
    __tablename__ = "routes"
    __table_args__ = (
        db.CheckConstraint("distance_meters IS NULL OR distance_meters >= 0", name="ck_routes_distance"),
        db.CheckConstraint("point_count >= 0", name="ck_routes_point_count"),
        db.UniqueConstraint("user_id", "fingerprint_sha256", name="uq_routes_user_fingerprint"),
        db.Index("ix_routes_user_created", "user_id", "created_at"),
        db.Index("ix_routes_user_type", "user_id", "route_type"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    route_type = db.Column(db.String(64), nullable=False)
    distance_meters = db.Column(db.Numeric(12, 2), nullable=True)
    elevation_gain_meters = db.Column(db.Numeric(10, 2), nullable=True)
    elevation_loss_meters = db.Column(db.Numeric(10, 2), nullable=True)
    bounds_json = db.Column(db.JSON, nullable=True)
    points_json = db.Column(db.JSON, nullable=True)
    point_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    source_app = db.Column(db.String(128), nullable=True)
    source_type = db.Column(db.String(32), nullable=False, default="uploaded", server_default="uploaded")
    source_file_id = db.Column(db.Integer, db.ForeignKey("uploaded_files.id", ondelete="SET NULL"), nullable=True)
    fingerprint_sha256 = db.Column(db.String(64), nullable=False)
    canonical_json = db.Column(db.JSON, nullable=False)
    warnings_json = db.Column(db.JSON, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=db.func.current_timestamp())

    user = db.relationship("User", back_populates="routes")
    source_file = db.relationship("UploadedFile")
