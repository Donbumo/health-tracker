from datetime import datetime, timezone
import uuid

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
        db.Index("ix_activities_user_public", "user_id", "public_id"),
        db.Index("ix_activities_user_status_started", "user_id", "status", "started_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=True, unique=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    activity_type = db.Column(db.String(64), nullable=False)
    discipline = db.Column(db.String(32), nullable=False, default="unknown", server_default="unknown")
    subtype = db.Column(db.String(64), nullable=True)
    original_type = db.Column(db.String(128), nullable=True)
    title = db.Column(db.String(200), nullable=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False)
    ended_at = db.Column(db.DateTime(timezone=True), nullable=True)
    timezone_name = db.Column(db.String(64), nullable=True)
    utc_offset_minutes = db.Column(db.Integer, nullable=True)
    local_date = db.Column(db.Date, nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)
    moving_time_seconds = db.Column(db.Integer, nullable=True)
    elapsed_time_seconds = db.Column(db.Integer, nullable=True)
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
    source_format = db.Column(db.String(32), nullable=False, default="unknown", server_default="unknown")
    source_device = db.Column(db.String(128), nullable=True)
    source_activity_id = db.Column(db.String(128), nullable=True)
    original_file_public_id = db.Column(db.String(36), nullable=True)
    source_file_id = db.Column(db.Integer, db.ForeignKey("uploaded_files.id", ondelete="SET NULL"), nullable=True)
    fingerprint_sha256 = db.Column(db.String(64), nullable=False)
    canonical_json = db.Column(db.JSON, nullable=False)
    laps_json = db.Column(db.JSON, nullable=True)
    track_json = db.Column(db.JSON, nullable=True)
    bounds_json = db.Column(db.JSON, nullable=True)
    point_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    warnings_json = db.Column(db.JSON, nullable=True)
    metrics_provenance_json = db.Column(db.JSON, nullable=False, default=dict)
    environment = db.Column(db.String(16), nullable=False, default="unknown", server_default="unknown")
    status = db.Column(db.String(24), nullable=False, default="imported", server_default="imported")
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    notes = db.Column(db.Text, nullable=True)
    archived_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=db.func.current_timestamp())

    user = db.relationship("User", back_populates="activities")
    source_file = db.relationship("UploadedFile")
    laps = db.relationship("ActivityLap", back_populates="activity", cascade="all, delete-orphan", passive_deletes=True)
    series_artifact = db.relationship("ActivitySeriesArtifact", back_populates="activity", cascade="all, delete-orphan", uselist=False, passive_deletes=True)
    route_metadata = db.relationship("ActivityRouteMetadata", back_populates="activity", cascade="all, delete-orphan", uselist=False, passive_deletes=True)
    duplicate_candidates = db.relationship("ActivityDuplicateCandidate", foreign_keys="ActivityDuplicateCandidate.activity_id", back_populates="activity", cascade="all, delete-orphan", passive_deletes=True)
    plan_link = db.relationship("PlanActivityLink", back_populates="activity", cascade="all, delete-orphan", uselist=False, passive_deletes=True)


class ActivityImportJob(db.Model):
    __tablename__ = "activity_import_jobs"
    __table_args__ = (
        db.CheckConstraint("revision >= 1", name="ck_activity_import_jobs_revision"),
        db.UniqueConstraint("public_id", name="uq_activity_import_jobs_public"),
        db.UniqueConstraint("user_id", "idempotency_key_hash", name="uq_activity_import_jobs_idempotency"),
        db.Index("ix_activity_import_jobs_user_state_created", "user_id", "state", "created_at"),
        db.Index("ix_activity_import_jobs_expires", "expires_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    uploaded_file_id = db.Column(db.Integer, db.ForeignKey("uploaded_files.id", ondelete="CASCADE"), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey("activities.id", ondelete="SET NULL"), nullable=True)
    state = db.Column(db.String(24), nullable=False, default="uploaded", server_default="uploaded")
    detected_format = db.Column(db.String(32), nullable=True)
    extension_format = db.Column(db.String(32), nullable=True)
    route_policy = db.Column(db.String(16), nullable=False, default="keep", server_default="keep")
    redact_start_meters = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    redact_end_meters = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    strong_plan_public_id = db.Column(db.String(36), nullable=True)
    inspection_json = db.Column(db.JSON, nullable=True)
    parsed_document_json = db.Column(db.JSON, nullable=True)
    warnings_json = db.Column(db.JSON, nullable=True)
    duplicate_classification = db.Column(db.String(32), nullable=True)
    error_code = db.Column(db.String(64), nullable=True)
    idempotency_key_hash = db.Column(db.String(64), nullable=False)
    request_hash = db.Column(db.String(64), nullable=False)
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=db.func.current_timestamp())
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)

    uploaded_file = db.relationship("UploadedFile")
    activity = db.relationship("Activity")


class ActivityLap(db.Model):
    __tablename__ = "activity_laps"
    __table_args__ = (
        db.UniqueConstraint("activity_id", "lap_index", name="uq_activity_laps_index"),
        db.Index("ix_activity_laps_user_activity", "user_id", "activity_id", "lap_index"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey("activities.id", ondelete="CASCADE"), nullable=False)
    lap_index = db.Column(db.Integer, nullable=False)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    ended_at = db.Column(db.DateTime(timezone=True), nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)
    distance_meters = db.Column(db.Numeric(12, 2), nullable=True)
    metrics_json = db.Column(db.JSON, nullable=False, default=dict)
    provenance_json = db.Column(db.JSON, nullable=False, default=dict)
    source_payload_json = db.Column(db.JSON, nullable=True)

    activity = db.relationship("Activity", back_populates="laps")


class ActivitySeriesArtifact(db.Model):
    __tablename__ = "activity_series_artifacts"
    __table_args__ = (
        db.UniqueConstraint("activity_id", name="uq_activity_series_activity"),
        db.Index("ix_activity_series_user_activity", "user_id", "activity_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey("activities.id", ondelete="CASCADE"), nullable=False)
    format_version = db.Column(db.String(32), nullable=False, default="activity-series-v1", server_default="activity-series-v1")
    storage_path = db.Column(db.String(512), nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    compression = db.Column(db.String(16), nullable=False, default="gzip", server_default="gzip")
    size_bytes = db.Column(db.BigInteger, nullable=False)
    sample_count = db.Column(db.Integer, nullable=False)
    fields_json = db.Column(db.JSON, nullable=False)
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    ended_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=db.func.current_timestamp())

    activity = db.relationship("Activity", back_populates="series_artifact")


class ActivityRouteMetadata(db.Model):
    __tablename__ = "activity_route_metadata"
    __table_args__ = (
        db.UniqueConstraint("activity_id", name="uq_activity_route_activity"),
        db.Index("ix_activity_route_user_activity", "user_id", "activity_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey("activities.id", ondelete="CASCADE"), nullable=False)
    state = db.Column(db.String(16), nullable=False, default="available", server_default="available")
    policy = db.Column(db.String(16), nullable=False, default="keep", server_default="keep")
    original_storage_path = db.Column(db.String(512), nullable=True)
    visible_storage_path = db.Column(db.String(512), nullable=True)
    original_sha256 = db.Column(db.String(64), nullable=True)
    visible_sha256 = db.Column(db.String(64), nullable=True)
    original_point_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    visible_point_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    visible_distance_meters = db.Column(db.Numeric(12, 2), nullable=True)
    redact_start_meters = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    redact_end_meters = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    removed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    activity = db.relationship("Activity", back_populates="route_metadata")


class ActivityDuplicateCandidate(db.Model):
    __tablename__ = "activity_duplicate_candidates"
    __table_args__ = (
        db.UniqueConstraint("activity_id", "candidate_activity_id", name="uq_activity_duplicate_pair"),
        db.Index("ix_activity_duplicates_user_classification", "user_id", "classification", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey("activities.id", ondelete="CASCADE"), nullable=False)
    candidate_activity_id = db.Column(db.Integer, db.ForeignKey("activities.id", ondelete="CASCADE"), nullable=False)
    classification = db.Column(db.String(32), nullable=False)
    evidence_json = db.Column(db.JSON, nullable=False)
    resolution = db.Column(db.String(24), nullable=False, default="pending", server_default="pending")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=db.func.current_timestamp())
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)

    activity = db.relationship("Activity", foreign_keys=[activity_id], back_populates="duplicate_candidates")
    candidate_activity = db.relationship("Activity", foreign_keys=[candidate_activity_id])


class PlanActivityLink(db.Model):
    __tablename__ = "plan_activity_links"
    __table_args__ = (
        db.UniqueConstraint("activity_id", name="uq_plan_activity_links_activity"),
        db.Index("ix_plan_activity_links_user_plan", "user_id", "planned_workout_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey("activities.id", ondelete="CASCADE"), nullable=False)
    planned_workout_id = db.Column(db.Integer, db.ForeignKey("planned_workouts.id", ondelete="CASCADE"), nullable=False)
    state = db.Column(db.String(24), nullable=False)
    evidence_json = db.Column(db.JSON, nullable=False)
    revision = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), server_default=db.func.current_timestamp())
    detached_at = db.Column(db.DateTime(timezone=True), nullable=True)

    activity = db.relationship("Activity", back_populates="plan_link")
    planned_workout = db.relationship("PlannedWorkout")
    comparisons = db.relationship("PlanActualComparisonSnapshot", back_populates="link", cascade="all, delete-orphan", passive_deletes=True)


class PlanActualComparisonSnapshot(db.Model):
    __tablename__ = "plan_actual_comparison_snapshots"
    __table_args__ = (
        db.Index("ix_plan_actual_comparisons_user_link_created", "user_id", "plan_activity_link_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan_activity_link_id = db.Column(db.Integer, db.ForeignKey("plan_activity_links.id", ondelete="CASCADE"), nullable=False)
    status = db.Column(db.String(24), nullable=False)
    activity_revision = db.Column(db.Integer, nullable=False)
    plan_revision = db.Column(db.Integer, nullable=False)
    comparison_json = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=db.func.current_timestamp())

    link = db.relationship("PlanActivityLink", back_populates="comparisons")


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
