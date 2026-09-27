"""Shared reference metadata; personal exercise identity remains owner-scoped."""
import uuid

from app.extensions import db


class ExerciseCatalogSource(db.Model):
    __tablename__ = "exercise_catalog_sources"
    source_id = db.Column(db.String(64), primary_key=True)
    active_snapshot = db.Column(db.String(64))
    previous_snapshot = db.Column(db.String(64))
    manifest = db.Column(db.JSON, nullable=False, default=dict)


class ExternalExercise(db.Model):
    __tablename__ = "external_exercises"
    __table_args__ = (
        db.UniqueConstraint("source", "external_id", name="uq_external_exercise_source_id"),
    )
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    source = db.Column(db.String(64), db.ForeignKey("exercise_catalog_sources.source_id"), nullable=False)
    # Binary collation on MariaDB preserves the exact case-sensitive upstream ID.
    external_id = db.Column(db.String(200, collation="utf8mb4_bin").with_variant(db.String(200), "sqlite"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    normalized_name = db.Column(db.String(255), nullable=False, index=True)
    available = db.Column(db.Boolean, nullable=False, default=True)
    details = db.Column(db.JSON, nullable=False)
    media = db.Column(db.JSON, nullable=False, default=list)
