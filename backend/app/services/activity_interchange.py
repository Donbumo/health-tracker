from __future__ import annotations

from copy import deepcopy
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import gzip
import hashlib
from io import BytesIO, StringIO
import json
import math
import os
from pathlib import Path
import re
from typing import Any
import uuid
from xml.etree import ElementTree as ET

from flask import current_app
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models import (
    Activity,
    ActivityDuplicateCandidate,
    ActivityImportJob,
    ActivityLap,
    ActivityRouteMetadata,
    ActivitySeriesArtifact,
    PlanActivityLink,
    PlanActualComparisonSnapshot,
    PlannedWorkout,
    UploadedFile,
)
from app.services.activity_parsers import (
    ACTIVITY_FORMAT,
    MAX_REAL_FILE_BYTES,
    SERIES_FORMAT,
    ActivityParseError,
    ActivityParserRegistry,
    ParsedActivityFile,
)
from app.services.files import UploadError, store_uploaded_file
from app.services.validation import validate_json_document


LOCATION_WARNING = "Las actividades pueden contener ubicación, horarios y métricas personales."
IMPORT_TTL_HOURS = 24
MAX_USER_ACTIVITY_BYTES = 250 * 1024 * 1024
ROUTE_POLICIES = {"keep", "drop", "redact"}
DISCIPLINES = {"cycling", "running", "walking", "hiking", "strength", "indoor_cycling", "other", "unknown"}
LINK_STATES = {"strong_auto_link", "user_confirmed", "user_rejected", "detached"}
GPX_NS = "http://www.topografix.com/GPX/1/1"
ET.register_namespace("", GPX_NS)


class ActivityInterchangeError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400, details: dict[str, Any] | None = None):
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}
        super().__init__(message)


# Keep service call sites compact while avoiding a dependency on the API package.
ApiError = ActivityInterchangeError


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_import_job(
    *, user_id: int, content: bytes, filename: str, mime_type: str | None,
    idempotency_key: str, route_policy: str, redact_start_meters: int,
    redact_end_meters: int, strong_plan_public_id: str | None,
) -> tuple[ActivityImportJob, bool]:
    policy, start_m, end_m = _route_policy(route_policy, redact_start_meters, redact_end_meters)
    strong_plan_id = _optional_uuid(strong_plan_public_id, "strong_plan_public_id")
    registry = ActivityParserRegistry()
    detected, mismatch = registry.detect(filename, content)
    if len(content) > current_app.config.get("ACTIVITY_FILE_MAX_BYTES", MAX_REAL_FILE_BYTES):
        raise ApiError("file_too_large", "El archivo supera el límite permitido.", 413)
    total = db.session.execute(
        db.select(db.func.coalesce(db.func.sum(UploadedFile.size_bytes), 0)).where(UploadedFile.user_id == user_id)
    ).scalar_one()
    if int(total) + len(content) > current_app.config.get("ACTIVITY_USER_MAX_BYTES", MAX_USER_ACTIVITY_BYTES):
        raise ApiError("user_storage_limit", "Los archivos de actividad superan el límite de la cuenta.", 413)
    key_hash = _key_hash(idempotency_key)
    request_payload = {
        "sha256": hashlib.sha256(content).hexdigest(), "route_policy": policy,
        "redact_start_meters": start_m, "redact_end_meters": end_m,
        "strong_plan_public_id": strong_plan_id,
    }
    request_hash = _sha(request_payload)
    existing_job = db.session.execute(
        db.select(ActivityImportJob).where(
            ActivityImportJob.user_id == user_id,
            ActivityImportJob.idempotency_key_hash == key_hash,
        )
    ).scalar_one_or_none()
    if existing_job:
        if existing_job.request_hash != request_hash:
            raise ApiError("idempotency_conflict", "La clave de idempotencia ya se usó con otro archivo.", 409)
        return existing_job, True
    storage = FileStorage(stream=BytesIO(content), filename=filename, content_type=mime_type)
    try:
        uploaded, file_duplicate = store_uploaded_file(storage, user_id)
    except UploadError as error:
        raise ApiError("invalid_upload", "No fue posible almacenar el archivo de actividad.", 400) from error
    previous = db.session.execute(
        db.select(ActivityImportJob).where(
            ActivityImportJob.user_id == user_id,
            ActivityImportJob.uploaded_file_id == uploaded.id,
            ActivityImportJob.activity_id.is_not(None),
        ).order_by(ActivityImportJob.id.desc())
    ).scalars().first()
    job = ActivityImportJob(
        user_id=user_id,
        uploaded_file_id=uploaded.id,
        activity_id=previous.activity_id if previous else None,
        state="duplicate" if file_duplicate and previous else "uploaded",
        detected_format=detected,
        extension_format=mismatch,
        route_policy=policy,
        redact_start_meters=start_m,
        redact_end_meters=end_m,
        strong_plan_public_id=strong_plan_id,
        duplicate_classification="exact_file_duplicate" if file_duplicate else None,
        warnings_json=[LOCATION_WARNING],
        idempotency_key_hash=key_hash,
        request_hash=request_hash,
        expires_at=utcnow() + timedelta(hours=IMPORT_TTL_HOURS),
    )
    db.session.add(job)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raced = db.session.execute(
            db.select(ActivityImportJob).where(
                ActivityImportJob.user_id == user_id,
                ActivityImportJob.idempotency_key_hash == key_hash,
            )
        ).scalar_one_or_none()
        if raced and raced.request_hash == request_hash:
            return raced, True
        raise
    return job, False


def inspect_import_job(job: ActivityImportJob, user_id: int) -> dict[str, Any]:
    _ensure_owner(job, user_id)
    if job.state == "duplicate" and job.activity:
        return serialize_import_job(job)
    _ensure_job_active(job)
    content = _read_uploaded(job.uploaded_file, user_id)
    proposed = (job.inspection_json or {}).get("proposed_public_id") or str(uuid.uuid4())
    try:
        parsed = ActivityParserRegistry().parse(job.uploaded_file.original_filename, content, public_id=proposed)
    except ActivityParseError as error:
        job.state = "invalid"
        job.error_code = error.code
        job.warnings_json = [str(error)[:300]]
        job.revision += 1
        db.session.commit()
        raise ApiError(error.code, str(error), 422) from error
    duplicate = db.session.execute(
        db.select(Activity).where(
            Activity.user_id == user_id,
            Activity.fingerprint_sha256 == parsed.content_fingerprint,
        )
    ).scalar_one_or_none()
    classification = "exact_activity_duplicate" if duplicate else "distinct"
    inspection = {
        "proposed_public_id": proposed,
        "format": parsed.source_format,
        "size_bytes": job.uploaded_file.size_bytes,
        "discipline": parsed.document["activity"]["discipline"],
        "start_time": _truncate_instant(parsed.document["activity"]["startTime"]),
        "end_time": _truncate_instant(parsed.document["activity"].get("endTime")),
        "lap_count": len(parsed.laps),
        "sample_count": len(parsed.samples),
        "metrics": sorted(parsed.document.get("summary", {})),
        "route_present": bool(parsed.route_points),
        "route_point_count": len(parsed.route_points),
        "warnings": parsed.warnings,
        "duplicate_classification": classification,
        "duplicate_activity_public_id": duplicate.public_id if duplicate else None,
        "content_fingerprint_short": parsed.content_fingerprint[:12],
        "privacy_warning": LOCATION_WARNING,
    }
    job.state = "duplicate" if duplicate else "ready_to_import"
    job.activity_id = duplicate.id if duplicate else None
    job.detected_format = parsed.source_format
    job.inspection_json = inspection
    job.parsed_document_json = parsed.document
    job.warnings_json = parsed.warnings
    job.duplicate_classification = classification
    job.error_code = None
    job.revision += 1
    db.session.commit()
    return serialize_import_job(job)


def apply_import_job(
    job: ActivityImportJob, user_id: int, *, commit: bool = True,
    rollback_cleanup: list[Path] | None = None,
) -> tuple[Activity, bool]:
    _ensure_owner(job, user_id)
    if job.activity and job.state in {"duplicate", "imported"}:
        return job.activity, True
    _ensure_job_active(job)
    if job.state != "ready_to_import":
        raise ApiError("import_not_ready", "Inspecciona el archivo antes de importarlo.", 409)
    content = _read_uploaded(job.uploaded_file, user_id)
    public_id = (job.inspection_json or {}).get("proposed_public_id")
    parsed = ActivityParserRegistry().parse(job.uploaded_file.original_filename, content, public_id=public_id)
    existing = db.session.execute(
        db.select(Activity).where(Activity.user_id == user_id, Activity.fingerprint_sha256 == parsed.content_fingerprint)
    ).scalar_one_or_none()
    if existing:
        job.activity = existing
        job.state = "duplicate"
        job.duplicate_classification = "exact_activity_duplicate"
        job.revision += 1
        job.uploaded_file.import_status = "duplicate"
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return existing, True
    paths: list[Path] = []
    try:
        activity = _create_activity(job, parsed, user_id)
        db.session.flush()
        _create_laps(activity, parsed.laps, user_id)
        series = _write_series(activity, parsed.samples, user_id)
        if series:
            paths.append(_generated_path(series.storage_path))
        route = _write_route(activity, parsed.route_points, job, user_id)
        if route:
            for relative in (route.original_storage_path, route.visible_storage_path):
                if relative:
                    paths.append(_generated_path(relative))
        if rollback_cleanup is not None:
            rollback_cleanup.extend(path for path in paths if path not in rollback_cleanup)
        _create_duplicates(activity, user_id)
        if job.strong_plan_public_id:
            _strong_link(activity, job.strong_plan_public_id, user_id)
        job.activity = activity
        job.state = "imported"
        job.duplicate_classification = "distinct"
        job.revision += 1
        job.uploaded_file.import_status = "imported"
        job.uploaded_file.detected_type = parsed.source_format
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return activity, False
    except Exception:
        db.session.rollback()
        for path in paths:
            path.unlink(missing_ok=True)
        raise


def list_import_jobs(user_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
    limit = _limit(limit, maximum=100)
    rows = db.session.execute(
        db.select(ActivityImportJob).options(
            selectinload(ActivityImportJob.uploaded_file),
            selectinload(ActivityImportJob.activity),
        )
        .where(ActivityImportJob.user_id == user_id)
        .order_by(ActivityImportJob.created_at.desc(), ActivityImportJob.id.desc())
        .limit(limit)
    ).scalars().all()
    return [serialize_import_job(row) for row in rows]


def owned_import_job(user_id: int, public_id: str) -> ActivityImportJob:
    public_id = _uuid(public_id, "import_id")
    row = db.session.execute(
        db.select(ActivityImportJob).where(ActivityImportJob.user_id == user_id, ActivityImportJob.public_id == public_id)
    ).scalar_one_or_none()
    if row is None:
        raise ApiError("not_found", "Import no encontrado.", 404)
    return row


def delete_import_job(
    job: ActivityImportJob, user_id: int, *, commit: bool = True,
    commit_cleanup: list[Path] | None = None,
) -> None:
    _ensure_owner(job, user_id)
    uploaded = job.uploaded_file
    can_delete_file = job.activity_id is None and db.session.execute(
        db.select(db.func.count(ActivityImportJob.id)).where(
            ActivityImportJob.uploaded_file_id == uploaded.id,
            ActivityImportJob.id != job.id,
        )
    ).scalar_one() == 0
    path = _uploaded_path(uploaded) if can_delete_file else None
    db.session.delete(job)
    if can_delete_file:
        db.session.delete(uploaded)
    if commit:
        db.session.commit()
        if path:
            path.unlink(missing_ok=True)
    else:
        db.session.flush()
        if path and commit_cleanup is not None:
            commit_cleanup.append(path)


def cleanup_expired_import_jobs(now: datetime | None = None) -> int:
    now = now or utcnow()
    rows = db.session.execute(
        db.select(ActivityImportJob).where(
            ActivityImportJob.expires_at < now,
            ActivityImportJob.state.in_({"uploaded", "ready_to_import", "invalid"}),
        )
    ).scalars().all()
    count = 0
    for row in rows:
        delete_import_job(row, row.user_id)
        count += 1
    return count


def list_activities(
    user_id: int, *, limit: int = 50, cursor: str | None = None,
    discipline: str | None = None, status: str | None = None,
    date_from: date | None = None, date_to: date | None = None,
) -> dict[str, Any]:
    limit = _limit(limit, maximum=100)
    filters = [Activity.user_id == user_id, Activity.public_id.is_not(None)]
    if discipline:
        if discipline not in DISCIPLINES:
            raise ApiError("invalid_filter", "La disciplina no es válida.", 400)
        filters.append(Activity.discipline == discipline)
    if status:
        if status not in {"imported", "archived"}:
            raise ApiError("invalid_filter", "El estado no es válido.", 400)
        filters.append(Activity.status == status)
    if date_from:
        filters.append(Activity.started_at >= datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc))
    if date_to:
        filters.append(Activity.started_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc))
    if date_from and date_to and (date_to < date_from or (date_to - date_from).days > 366):
        raise ApiError("invalid_range", "El rango de fechas debe ser de hasta 366 días.", 400)
    if cursor:
        try:
            cursor_id = int(cursor)
        except ValueError as error:
            raise ApiError("invalid_cursor", "El cursor no es válido.", 400) from error
        filters.append(Activity.id < cursor_id)
    rows = db.session.execute(
        db.select(Activity).options(
            selectinload(Activity.laps),
            selectinload(Activity.series_artifact),
            selectinload(Activity.route_metadata),
            selectinload(Activity.duplicate_candidates),
        ).where(*filters).order_by(Activity.id.desc()).limit(limit + 1)
    ).scalars().all()
    return {"items": [serialize_activity(row, include_detail=False) for row in rows[:limit]], "next_cursor": str(rows[limit - 1].id) if len(rows) > limit else None}


def owned_activity(user_id: int, public_id: str) -> Activity:
    public_id = _uuid(public_id, "activity_id")
    row = db.session.execute(
        db.select(Activity).where(Activity.user_id == user_id, Activity.public_id == public_id)
    ).scalar_one_or_none()
    if row is None:
        raise ApiError("not_found", "Actividad no encontrada.", 404)
    return row


def upsert_external_activity(
    user_id: int,
    *,
    provider: str,
    external_account_public_id: str,
    external_resource_id: str,
    normalized: dict[str, Any],
) -> tuple[Activity, bool, bool]:
    """Create or update a provider activity through the canonical Activity service."""
    provider = str(provider).strip().casefold()
    resource_id = str(external_resource_id).strip()
    if not provider or len(provider) > 32 or not resource_id or len(resource_id) > 128:
        raise ApiError("invalid_external_resource", "La identidad externa no es válida.", 400)
    if normalized.get("external_resource_id") != resource_id:
        raise ApiError("invalid_external_resource", "La actividad externa no coincide con el recurso.", 400)
    if normalized.get("discipline") not in DISCIPLINES:
        raise ApiError("invalid_external_resource", "La disciplina externa no es válida.", 400)
    started_at = normalized.get("started_at")
    if not isinstance(started_at, datetime) or started_at.tzinfo is None:
        raise ApiError("invalid_external_resource", "La fecha externa no es válida.", 400)
    started_at = started_at.astimezone(timezone.utc)
    ended_at = normalized.get("ended_at")
    if ended_at is not None:
        if not isinstance(ended_at, datetime) or ended_at.tzinfo is None:
            raise ApiError("invalid_external_resource", "La fecha final externa no es válida.", 400)
        ended_at = ended_at.astimezone(timezone.utc)

    provenance = {
        "source": "external_provider",
        "provider": provider,
        "external_account_id": str(external_account_public_id),
        "resource_type": "activity",
        "external_resource_id": resource_id,
    }
    data = {
        "activity_type": str(normalized["activity_type"])[:64],
        "started_at": _rfc3339(started_at),
        "source_app": provider,
    }
    if ended_at is not None:
        data["ended_at"] = _rfc3339(ended_at)
    for key in (
        "title", "original_type", "discipline", "local_started_at", "timezone",
        "utc_offset_minutes", "elapsed_time_seconds", "moving_time_seconds",
        "distance_meters", "calories_kcal", "avg_heart_rate_bpm",
        "max_heart_rate_bpm", "avg_speed_mps", "max_speed_mps",
        "elevation_gain_meters", "source_device", "trainer", "commute",
        "manual", "visibility",
    ):
        if normalized.get(key) is not None:
            data[key] = normalized[key]
    document = {
        "schema_version": "1.0",
        "record_type": "activity",
        "user_id": user_id,
        "source_type": "external_provider",
        "provenance": provenance,
        "data": data,
    }
    validate_json_document(document, "activity")
    fingerprint = hashlib.sha256(
        f"external:{provider}:{external_account_public_id}:activity:{resource_id}".encode("utf-8")
    ).hexdigest()
    activity = db.session.execute(
        db.select(Activity).where(
            Activity.user_id == user_id,
            Activity.fingerprint_sha256 == fingerprint,
        )
    ).scalar_one_or_none()
    created = activity is None
    if created:
        activity = Activity(user_id=user_id, fingerprint_sha256=fingerprint, canonical_json=document)
        db.session.add(activity)
    previous = deepcopy(activity.canonical_json) if not created else None
    activity.activity_type = data["activity_type"]
    activity.discipline = normalized["discipline"]
    activity.original_type = normalized.get("original_type") or data["activity_type"]
    activity.title = normalized.get("title")
    activity.started_at = started_at
    activity.ended_at = ended_at
    activity.timezone_name = normalized.get("timezone")
    activity.utc_offset_minutes = normalized.get("utc_offset_minutes")
    local_started_at = normalized.get("local_started_at")
    try:
        activity.local_date = date.fromisoformat(str(local_started_at)[:10]) if local_started_at else started_at.date()
    except ValueError:
        activity.local_date = started_at.date()
    activity.duration_seconds = normalized.get("elapsed_time_seconds")
    activity.elapsed_time_seconds = normalized.get("elapsed_time_seconds")
    activity.moving_time_seconds = normalized.get("moving_time_seconds")
    activity.distance_meters = normalized.get("distance_meters")
    activity.calories_kcal = normalized.get("calories_kcal")
    activity.elevation_gain_meters = normalized.get("elevation_gain_meters")
    activity.avg_heart_rate_bpm = normalized.get("avg_heart_rate_bpm")
    activity.max_heart_rate_bpm = normalized.get("max_heart_rate_bpm")
    activity.avg_speed_mps = normalized.get("avg_speed_mps")
    activity.max_speed_mps = normalized.get("max_speed_mps")
    activity.source_app = provider
    activity.source_type = "external_provider"
    activity.source_format = "json"
    activity.source_device = normalized.get("source_device")
    activity.source_activity_id = resource_id
    activity.canonical_json = document
    activity.laps_json = []
    activity.track_json = None
    activity.bounds_json = None
    activity.point_count = 0
    activity.warnings_json = []
    metric_keys = {
        "elapsed_time_seconds": "elapsed_time",
        "moving_time_seconds": "moving_time",
        "distance_meters": "distance",
        "calories_kcal": "calories",
        "elevation_gain_meters": "ascent",
        "avg_heart_rate_bpm": "heart_rate_average",
        "max_heart_rate_bpm": "heart_rate_maximum",
        "avg_speed_mps": "speed_average",
        "max_speed_mps": "speed_maximum",
    }
    activity.metrics_provenance_json = {
        target: "source_provided" for source, target in metric_keys.items()
        if normalized.get(source) is not None
    }
    activity.environment = "indoor" if normalized.get("trainer") else "unknown"
    activity.status = "imported"
    changed = created or previous != document
    if not created and changed:
        activity.revision += 1
    db.session.flush()
    return activity, created, changed


def archive_external_activity(activity: Activity, user_id: int) -> bool:
    _ensure_owner(activity, user_id)
    if activity.source_type != "external_provider":
        raise ApiError("invalid_external_resource", "La actividad no pertenece a un proveedor externo.", 409)
    if activity.status == "archived":
        return False
    activity.status = "archived"
    activity.archived_at = utcnow()
    activity.revision += 1
    db.session.flush()
    return True


def patch_activity(activity: Activity, user_id: int, payload: dict[str, Any], *, commit: bool = True) -> Activity:
    _ensure_owner(activity, user_id)
    allowed = {"base_revision", "title", "subtype", "environment"}
    if set(payload) - allowed or type(payload.get("base_revision")) is not int:
        raise ApiError("invalid_request", "La actualización contiene campos no admitidos.", 400)
    if payload["base_revision"] != activity.revision:
        raise ApiError("revision_conflict", "La actividad cambió en el servidor.", 409, {"current_revision": activity.revision})
    if "title" in payload:
        activity.title = _optional_text(payload["title"], 200)
    if "subtype" in payload:
        activity.subtype = _optional_text(payload["subtype"], 64)
    if "environment" in payload:
        if payload["environment"] not in {"indoor", "outdoor", "unknown"}:
            raise ApiError("invalid_environment", "El entorno no es válido.", 400)
        activity.environment = payload["environment"]
    activity.revision += 1
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return activity


def archive_activity(activity: Activity, user_id: int, base_revision: int, *, commit: bool = True) -> Activity:
    _ensure_revision(activity, user_id, base_revision)
    activity.status = "archived"
    activity.archived_at = utcnow()
    activity.revision += 1
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return activity


def delete_activity(
    activity: Activity, user_id: int, base_revision: int, *, commit: bool = True,
    commit_cleanup: list[Path] | None = None,
) -> None:
    _ensure_revision(activity, user_id, base_revision)
    paths = _activity_paths(activity)
    db.session.delete(activity)
    if commit:
        db.session.commit()
        for path in paths:
            path.unlink(missing_ok=True)
    else:
        db.session.flush()
        if commit_cleanup is not None:
            commit_cleanup.extend(paths)


def activity_laps(activity: Activity, user_id: int) -> list[dict[str, Any]]:
    _ensure_owner(activity, user_id)
    rows = db.session.execute(
        db.select(ActivityLap).where(ActivityLap.user_id == user_id, ActivityLap.activity_id == activity.id).order_by(ActivityLap.lap_index)
    ).scalars().all()
    return [serialize_lap(row) for row in rows]


def activity_series(activity: Activity, user_id: int, *, offset: int, limit: int, downsample: int | None) -> dict[str, Any]:
    _ensure_owner(activity, user_id)
    artifact = activity.series_artifact
    if not artifact:
        return {"format": SERIES_FORMAT, "items": [], "offset": 0, "next_offset": None, "sample_count": 0}
    samples = _read_json_gzip(artifact.storage_path).get("samples") or []
    offset = max(0, int(offset))
    limit = _limit(limit, maximum=2_000)
    selected = samples[offset:offset + limit]
    if downsample is not None:
        target = max(2, min(int(downsample), 1_000))
        selected = deterministic_downsample(selected, target)
    next_offset = offset + limit if offset + limit < len(samples) else None
    return {
        "format": SERIES_FORMAT, "items": selected, "offset": offset,
        "next_offset": next_offset, "sample_count": len(samples),
        "fields": artifact.fields_json, "sha256": artifact.sha256,
    }


def deterministic_downsample(samples: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    if target >= len(samples) or target < 2:
        return list(samples)
    indexes = [round(index * (len(samples) - 1) / (target - 1)) for index in range(target)]
    return [samples[index] for index in dict.fromkeys(indexes)]


def activity_route(activity: Activity, user_id: int) -> dict[str, Any]:
    _ensure_owner(activity, user_id)
    metadata = activity.route_metadata
    if not metadata or metadata.state == "removed" or not metadata.visible_storage_path or metadata.visible_point_count == 0:
        return {"present": False, "state": metadata.state if metadata else "unavailable", "points": []}
    points = _read_json_gzip(metadata.visible_storage_path).get("points") or []
    return {
        "present": True, "state": metadata.state, "policy": metadata.policy,
        "point_count": len(points), "distance_meters": _number(metadata.visible_distance_meters),
        "redact_start_meters": metadata.redact_start_meters,
        "redact_end_meters": metadata.redact_end_meters, "points": points,
    }


def remove_activity_route(
    activity: Activity, user_id: int, base_revision: int, *, commit: bool = True,
    commit_cleanup: list[Path] | None = None,
) -> Activity:
    _ensure_revision(activity, user_id, base_revision)
    metadata = activity.route_metadata
    if metadata:
        paths = [_generated_path(value) for value in (metadata.original_storage_path, metadata.visible_storage_path) if value]
        metadata.state = "removed"
        metadata.original_storage_path = None
        metadata.visible_storage_path = None
        metadata.original_sha256 = None
        metadata.visible_sha256 = None
        metadata.visible_point_count = 0
        metadata.visible_distance_meters = None
        metadata.removed_at = utcnow()
    else:
        paths = []
    activity.revision += 1
    if commit:
        db.session.commit()
        for path in paths:
            path.unlink(missing_ok=True)
    else:
        db.session.flush()
        if commit_cleanup is not None:
            commit_cleanup.extend(paths)
    return activity


def plan_candidates(activity: Activity, user_id: int) -> list[dict[str, Any]]:
    _ensure_owner(activity, user_id)
    start_date = activity.started_at.date()
    rows = db.session.execute(
        db.select(PlannedWorkout).where(
            PlannedWorkout.user_id == user_id,
            PlannedWorkout.deleted_at.is_(None),
            PlannedWorkout.scheduled_for_date.between(start_date - timedelta(days=2), start_date + timedelta(days=2)),
        ).order_by(PlannedWorkout.scheduled_for_date, PlannedWorkout.id)
    ).scalars().all()
    output = []
    for row in rows:
        evidence = _candidate_evidence(activity, row)
        if evidence["score"] >= 0.25:
            output.append({
                "planned_workout_id": row.public_id, "title": _safe_title(row.title_snapshot),
                "scheduled_for_date": row.scheduled_for_date.isoformat(),
                "state": "suggested_link", "evidence": evidence,
            })
    return sorted(output, key=lambda item: (-item["evidence"]["score"], item["scheduled_for_date"]))[:20]


def set_plan_link(activity: Activity, user_id: int, payload: dict[str, Any], *, commit: bool = True) -> PlanActivityLink:
    _ensure_revision(activity, user_id, payload.get("base_revision"))
    plan_id = _uuid(payload.get("planned_workout_id"), "planned_workout_id")
    action = payload.get("action", "confirm")
    if action not in {"confirm", "reject"}:
        raise ApiError("invalid_link_action", "La acción de vínculo no es válida.", 400)
    plan = db.session.execute(
        db.select(PlannedWorkout).where(PlannedWorkout.user_id == user_id, PlannedWorkout.public_id == plan_id)
    ).scalar_one_or_none()
    if plan is None:
        raise ApiError("not_found", "Entrenamiento planeado no encontrado.", 404)
    state = "user_confirmed" if action == "confirm" else "user_rejected"
    link = activity.plan_link
    if link is None:
        link = PlanActivityLink(user_id=user_id, activity=activity, planned_workout=plan, state=state, evidence_json=_candidate_evidence(activity, plan))
        db.session.add(link)
    else:
        link.planned_workout = plan
        link.state = state
        link.evidence_json = _candidate_evidence(activity, plan)
        link.detached_at = None
        link.revision += 1
    activity.revision += 1
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return link


def detach_plan_link(activity: Activity, user_id: int, base_revision: int, *, commit: bool = True) -> None:
    _ensure_revision(activity, user_id, base_revision)
    if activity.plan_link:
        activity.plan_link.state = "detached"
        activity.plan_link.detached_at = utcnow()
        activity.plan_link.revision += 1
    activity.revision += 1
    if commit:
        db.session.commit()
    else:
        db.session.flush()


def plan_actual_comparison(activity: Activity, user_id: int) -> dict[str, Any]:
    _ensure_owner(activity, user_id)
    link = activity.plan_link
    if not link or link.state not in {"strong_auto_link", "user_confirmed"}:
        return {"status": "not_comparable", "message": "No existe un vínculo confirmado con un entrenamiento planeado."}
    latest = db.session.execute(
        db.select(PlanActualComparisonSnapshot).where(
            PlanActualComparisonSnapshot.user_id == user_id,
            PlanActualComparisonSnapshot.plan_activity_link_id == link.id,
            PlanActualComparisonSnapshot.activity_revision == activity.revision,
            PlanActualComparisonSnapshot.plan_revision == link.planned_workout.revision,
        ).order_by(PlanActualComparisonSnapshot.id.desc())
    ).scalars().first()
    if latest:
        return latest.comparison_json
    result = _compare(activity, link.planned_workout)
    db.session.add(PlanActualComparisonSnapshot(
        user_id=user_id, link=link, status=result["status"],
        activity_revision=activity.revision, plan_revision=link.planned_workout.revision,
        comparison_json=result,
    ))
    db.session.commit()
    return result


def export_activity(
    activity: Activity, user_id: int, *, format_name: str,
    include_series: bool = False, include_route: bool = False,
) -> tuple[bytes, str, str, str | None]:
    _ensure_owner(activity, user_id)
    if format_name == "json":
        document = normalized_activity_document(activity, user_id, include_series=include_series, include_route=include_route)
        return _canonical(document, pretty=True), "application/json", "json", None
    if format_name == "csv_summary":
        fields = ("public_id", "discipline", "original_type", "started_at", "ended_at", "duration_seconds", "moving_time_seconds", "distance_meters", "calories_kcal", "ascent_meters", "descent_meters")
        row = {
            "public_id": activity.public_id, "discipline": activity.discipline,
            "original_type": activity.original_type or activity.activity_type,
            "started_at": _rfc3339(activity.started_at), "ended_at": _rfc3339(activity.ended_at),
            "duration_seconds": activity.duration_seconds, "moving_time_seconds": activity.moving_time_seconds,
            "distance_meters": _number(activity.distance_meters), "calories_kcal": _number(activity.calories_kcal),
            "ascent_meters": _number(activity.elevation_gain_meters), "descent_meters": _number(activity.elevation_loss_meters),
        }
        return _csv(fields, [row]), "text/csv", "csv", None
    if format_name == "csv_laps":
        rows = activity_laps(activity, user_id)
        fields = ("index", "start_time", "end_time", "duration_seconds", "distance_meters", "metrics_json", "provenance")
        cooked = [{
            "index": row["index"], "start_time": row.get("startTime"), "end_time": row.get("endTime"),
            "duration_seconds": row.get("durationSeconds"), "distance_meters": row.get("distanceMeters"),
            "metrics_json": json.dumps(row["metrics"], ensure_ascii=False, sort_keys=True),
            "provenance": json.dumps(row.get("provenance", {}), ensure_ascii=False, sort_keys=True),
        } for row in rows]
        return _csv(fields, cooked), "text/csv", "csv", None
    if format_name == "csv_samples":
        if not include_series:
            raise ApiError("series_confirmation_required", "Confirma include_series para exportar muestras.", 400)
        rows = activity_series(activity, user_id, offset=0, limit=2_000, downsample=None)
        if rows["sample_count"] > 2_000:
            raise ApiError("series_export_too_large", "Usa la API paginada para una serie mayor a 2000 muestras.", 413)
        fields = tuple(["index", *sorted({key for item in rows["items"] for key in item})])
        return _csv(fields, [{"index": index, **row} for index, row in enumerate(rows["items"], 1)]), "text/csv", "csv", None
    if format_name == "gpx":
        if not include_route:
            raise ApiError("route_confirmation_required", "Confirma include_route para exportar la ruta.", 400)
        route = activity_route(activity, user_id)
        if not route["present"]:
            raise ApiError("route_unavailable", "La actividad no tiene una ruta exportable.", 409)
        return _gpx(route["points"], activity.started_at), "application/gpx+xml", "gpx", "GPX omite métricas no representables; se exporta únicamente la ruta visible."
    raise ApiError("unsupported_export", "El formato de exportación no está disponible.", 400)


def normalized_activity_document(activity: Activity, user_id: int, *, include_series: bool, include_route: bool) -> dict[str, Any]:
    _ensure_owner(activity, user_id)
    external = (activity.canonical_json or {}).get("provenance") or {}
    document = {
        "format": ACTIVITY_FORMAT, "formatVersion": "1.0",
        "activity": _activity_identity(activity),
        "summary": _summary(activity),
        "laps": activity_laps(activity, user_id),
        "intervals": [],
        "sampleSeries": _series_metadata(activity.series_artifact),
        "route": _route_summary(activity.route_metadata),
        "events": [],
        "sourceReference": {
            "format": activity.source_format, "application": activity.source_app,
            "originalFileId": activity.original_file_public_id,
            "sourceActivityId": activity.source_activity_id,
            "sourceType": activity.source_type,
            "provider": external.get("provider"),
            "externalAccountId": external.get("external_account_id"),
            "resourceType": external.get("resource_type"),
            "externalResourceId": external.get("external_resource_id"),
        },
        "warnings": list(activity.warnings_json or []),
    }
    if activity.plan_link and activity.plan_link.state != "detached":
        document["planLink"] = serialize_plan_link(activity.plan_link)
    if include_series:
        series_page = activity_series(activity, user_id, offset=0, limit=2_000, downsample=None)
        document["series"] = {"format": SERIES_FORMAT, "samples": series_page["items"]}
        if series_page["sample_count"] > len(series_page["items"]):
            document["series"].update({"truncated": True, "totalSampleCount": series_page["sample_count"]})
    if include_route:
        document["route"].update({"points": activity_route(activity, user_id)["points"]})
    return _without_none(document)


def serialize_import_job(job: ActivityImportJob) -> dict[str, Any]:
    return _without_none({
        "import_id": job.public_id, "state": job.state, "detected_format": job.detected_format,
        "extension_format": job.extension_format, "size_bytes": job.uploaded_file.size_bytes,
        "file_sha256_short": job.uploaded_file.sha256[:12], "route_policy": job.route_policy,
        "redact_start_meters": job.redact_start_meters, "redact_end_meters": job.redact_end_meters,
        "duplicate_classification": job.duplicate_classification,
        "activity_id": job.activity.public_id if job.activity else None,
        "inspection": job.inspection_json, "warnings": job.warnings_json or [],
        "error_code": job.error_code, "revision": job.revision,
        "created_at": _rfc3339(job.created_at), "updated_at": _rfc3339(job.updated_at),
        "expires_at": _rfc3339(job.expires_at), "privacy_warning": LOCATION_WARNING,
    })


def serialize_activity(activity: Activity, *, include_detail: bool = True) -> dict[str, Any]:
    result = {
        **_activity_identity(activity), "summary": _summary(activity),
        "lapCount": len(activity.laps), "sampleCount": activity.series_artifact.sample_count if activity.series_artifact else 0,
        "route": _route_summary(activity.route_metadata),
        "duplicateCount": len([row for row in activity.duplicate_candidates if row.resolution == "pending"]),
    }
    if include_detail:
        result.update({
            "sourceReference": {"format": activity.source_format, "application": activity.source_app, "device": activity.source_device, "originalFileId": activity.original_file_public_id},
            "metricsProvenance": activity.metrics_provenance_json or {},
            "warnings": activity.warnings_json or [],
            "planLink": serialize_plan_link(activity.plan_link) if activity.plan_link and activity.plan_link.state != "detached" else None,
            "duplicates": [serialize_duplicate(row) for row in activity.duplicate_candidates],
        })
    return _without_none(result)


def serialize_lap(row: ActivityLap) -> dict[str, Any]:
    return _without_none({
        "publicId": row.public_id, "index": row.lap_index,
        "startTime": _rfc3339(row.started_at), "endTime": _rfc3339(row.ended_at),
        "durationSeconds": row.duration_seconds, "distanceMeters": _number(row.distance_meters),
        "metrics": row.metrics_json or {}, "provenance": row.provenance_json or {},
    })


def serialize_plan_link(link: PlanActivityLink | None) -> dict[str, Any] | None:
    if link is None:
        return None
    return {
        "link_id": link.public_id, "planned_workout_id": link.planned_workout.public_id,
        "state": link.state, "evidence": link.evidence_json or {}, "revision": link.revision,
    }


def serialize_duplicate(row: ActivityDuplicateCandidate) -> dict[str, Any]:
    return {
        "candidate_id": row.public_id, "activity_id": row.candidate_activity.public_id,
        "classification": row.classification, "evidence": row.evidence_json,
        "resolution": row.resolution,
    }


def _create_activity(job: ActivityImportJob, parsed: ParsedActivityFile, user_id: int) -> Activity:
    identity = parsed.document["activity"]
    summary = parsed.document.get("summary") or {}
    start = _parse_instant(identity["startTime"])
    end = _parse_instant(identity.get("endTime"))
    canonical_data = {
        "activity_type": identity.get("originalType") or identity["discipline"],
        "started_at": _rfc3339(start), "source_app": identity.get("sourceApplication") or parsed.source_format,
        "laps": parsed.laps, "warnings": parsed.warnings,
    }
    if end:
        canonical_data["ended_at"] = _rfc3339(end)
    legacy_map = {
        "duration": "duration_seconds", "elapsed_time": "elapsed_time_seconds", "moving_time": "moving_time_seconds",
        "distance": "distance_meters", "calories": "calories_kcal", "ascent": "elevation_gain_meters",
        "descent": "elevation_loss_meters", "heart_rate_average": "avg_heart_rate_bpm",
        "heart_rate_maximum": "max_heart_rate_bpm", "cadence_average": "avg_cadence_rpm",
        "cadence_maximum": "max_cadence_rpm", "speed_average": "avg_speed_mps",
        "speed_maximum": "max_speed_mps", "power_average": "avg_power_watts", "power_maximum": "max_power_watts",
    }
    for metric, field in legacy_map.items():
        if metric in summary:
            canonical_data[field] = summary[metric]["value"]
    canonical = {"schema_version": "1.0", "record_type": "activity", "user_id": user_id, "source_type": "uploaded", "source_file_id": job.uploaded_file_id, "data": canonical_data}
    provenance = {key: value["provenance"] for key, value in summary.items()}
    return Activity(
        public_id=identity["publicId"], user_id=user_id,
        activity_type=identity.get("originalType") or identity["discipline"],
        discipline=identity["discipline"], subtype=identity.get("subtype"),
        original_type=identity.get("originalType"), title=identity.get("title"),
        started_at=start, ended_at=end, timezone_name=identity.get("timezone"),
        utc_offset_minutes=identity.get("utcOffsetMinutes"), local_date=date.fromisoformat(identity.get("localDate") or start.date().isoformat()),
        duration_seconds=_metric(summary, "duration"), elapsed_time_seconds=_metric(summary, "elapsed_time"),
        moving_time_seconds=_metric(summary, "moving_time"), distance_meters=_metric(summary, "distance"),
        calories_kcal=_metric(summary, "calories"), elevation_gain_meters=_metric(summary, "ascent"),
        elevation_loss_meters=_metric(summary, "descent"), avg_heart_rate_bpm=_metric(summary, "heart_rate_average"),
        max_heart_rate_bpm=_metric(summary, "heart_rate_maximum"), avg_cadence_rpm=_metric(summary, "cadence_average"),
        max_cadence_rpm=_metric(summary, "cadence_maximum"), avg_speed_mps=_metric(summary, "speed_average"),
        max_speed_mps=_metric(summary, "speed_maximum"), avg_power_watts=_metric(summary, "power_average"),
        max_power_watts=_metric(summary, "power_maximum"), source_app=identity.get("sourceApplication"),
        source_device=identity.get("sourceDevice"), source_type="uploaded", source_format=parsed.source_format,
        source_file_id=job.uploaded_file_id, original_file_public_id=job.public_id,
        fingerprint_sha256=parsed.content_fingerprint, canonical_json=canonical,
        laps_json=parsed.laps, track_json=None, bounds_json=None, point_count=len(parsed.samples),
        warnings_json=parsed.warnings, metrics_provenance_json=provenance,
        environment=identity.get("environment", "unknown"), status="imported", revision=1,
    )


def _create_laps(activity: Activity, laps: list[dict[str, Any]], user_id: int) -> None:
    for index, value in enumerate(laps, start=1):
        metrics = dict(value.get("metrics") or {})
        provenance = {key: value.get("provenance", "source_provided") for key in metrics}
        db.session.add(ActivityLap(
            public_id=value.get("publicId") or str(uuid.uuid4()), user_id=user_id, activity=activity,
            lap_index=int(value.get("index") or index), started_at=_parse_instant(value.get("startTime")),
            ended_at=_parse_instant(value.get("endTime")), duration_seconds=_integer(value.get("durationSeconds")),
            distance_meters=value.get("distanceMeters"), metrics_json=metrics,
            provenance_json=provenance, source_payload_json=None,
        ))


def _write_series(activity: Activity, samples: list[dict[str, Any]], user_id: int) -> ActivitySeriesArtifact | None:
    if not samples:
        return None
    fields = sorted({key for sample in samples for key in sample if key != "t"})
    relative, digest, size = _write_json_gzip(user_id, f"{activity.public_id}.series.json.gz", {"format": SERIES_FORMAT, "samples": samples})
    row = ActivitySeriesArtifact(
        user_id=user_id, activity=activity, storage_path=relative, sha256=digest,
        size_bytes=size, sample_count=len(samples), fields_json=fields,
        started_at=activity.started_at, ended_at=activity.ended_at,
    )
    db.session.add(row)
    return row


def _write_route(activity: Activity, points: list[dict[str, Any]], job: ActivityImportJob, user_id: int) -> ActivityRouteMetadata | None:
    if not points or job.route_policy == "drop":
        if points:
            row = ActivityRouteMetadata(
                user_id=user_id, activity=activity, state="removed", policy="drop",
                original_point_count=len(points), visible_point_count=0,
                redact_start_meters=0, redact_end_meters=0, removed_at=utcnow(),
            )
            db.session.add(row)
            return row
        return None
    visible = points if job.route_policy == "keep" else redact_route(points, job.redact_start_meters, job.redact_end_meters)
    original_path, original_sha, _original_size = _write_json_gzip(user_id, f"{activity.public_id}.route.original.json.gz", {"format": "activity-route-v1", "points": points})
    visible_path, visible_sha, _visible_size = _write_json_gzip(user_id, f"{activity.public_id}.route.visible.json.gz", {"format": "activity-route-v1", "points": visible})
    row = ActivityRouteMetadata(
        user_id=user_id, activity=activity, state="available", policy=job.route_policy,
        original_storage_path=original_path, visible_storage_path=visible_path,
        original_sha256=original_sha, visible_sha256=visible_sha,
        original_point_count=len(points), visible_point_count=len(visible),
        visible_distance_meters=_route_distance(visible), redact_start_meters=job.redact_start_meters,
        redact_end_meters=job.redact_end_meters,
    )
    db.session.add(row)
    return row


def redact_route(points: list[dict[str, Any]], start_meters: int, end_meters: int) -> list[dict[str, Any]]:
    if len(points) < 2:
        return []
    cumulative = [0.0]
    for previous, current in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + _haversine(previous, current))
    total = cumulative[-1]
    lower = max(0.0, float(start_meters))
    upper = max(lower, total - max(0.0, float(end_meters)))
    if lower >= upper:
        return []
    visible = [dict(point) for point, distance in zip(points, cumulative) if lower <= distance <= upper]
    if visible:
        baseline = next(distance for distance in cumulative if distance >= lower)
        for point in visible:
            if point.get("distance") is not None:
                point["distance"] = max(0, point["distance"] - baseline)
    return visible


def _create_duplicates(activity: Activity, user_id: int) -> None:
    window_start = activity.started_at - timedelta(days=1)
    window_end = activity.started_at + timedelta(days=1)
    rows = db.session.execute(
        db.select(Activity).where(
            Activity.user_id == user_id, Activity.id != activity.id,
            Activity.started_at.between(window_start, window_end),
        ).limit(100)
    ).scalars().all()
    for candidate in rows:
        classification, evidence = _duplicate_evidence(activity, candidate)
        if classification in {"probable_duplicate", "possible_duplicate"}:
            db.session.add(ActivityDuplicateCandidate(
                user_id=user_id, activity=activity, candidate_activity=candidate,
                classification=classification, evidence_json=evidence,
            ))


def _duplicate_evidence(left: Activity, right: Activity) -> tuple[str, dict[str, Any]]:
    start_delta = abs((left.started_at - _aware(right.started_at)).total_seconds())
    duration_delta = _absolute_delta(left.duration_seconds, right.duration_seconds)
    distance_delta = _relative_delta(left.distance_meters, right.distance_meters)
    sport_match = left.discipline == right.discipline
    evidence = {
        "start_delta_seconds": round(start_delta), "duration_delta_seconds": duration_delta,
        "distance_relative_delta": distance_delta, "discipline_match": sport_match,
    }
    probable = start_delta <= 120 and sport_match and (duration_delta is None or duration_delta <= 60) and (distance_delta is None or distance_delta <= 0.05)
    possible = start_delta <= 86400 and sport_match
    return ("probable_duplicate" if probable else "possible_duplicate" if possible else "distinct"), evidence


def _strong_link(activity: Activity, planned_public_id: str, user_id: int) -> None:
    plan = db.session.execute(
        db.select(PlannedWorkout).where(PlannedWorkout.user_id == user_id, PlannedWorkout.public_id == planned_public_id)
    ).scalar_one_or_none()
    if plan is None:
        raise ApiError("strong_reference_invalid", "La referencia fuerte no corresponde a un entrenamiento propio.", 422)
    db.session.add(PlanActivityLink(
        user_id=user_id, activity=activity, planned_workout=plan,
        state="strong_auto_link", evidence_json={"type": "verified_planned_workout_uuid"},
    ))


def _candidate_evidence(activity: Activity, plan: PlannedWorkout) -> dict[str, Any]:
    date_delta = abs((activity.started_at.date() - plan.scheduled_for_date).days)
    expected_duration, expected_distance, intervals = _planned_targets(plan.payload_snapshot_json or {})
    duration_delta = _relative_delta(activity.duration_seconds, expected_duration)
    distance_delta = _relative_delta(activity.distance_meters, expected_distance)
    score = max(0.0, 0.5 - 0.15 * date_delta)
    if duration_delta is not None:
        score += max(0.0, 0.3 * (1 - min(duration_delta, 1)))
    if distance_delta is not None:
        score += max(0.0, 0.2 * (1 - min(distance_delta, 1)))
    return {
        "score": round(min(score, 1.0), 3), "date_delta_days": date_delta,
        "duration_relative_delta": duration_delta, "distance_relative_delta": distance_delta,
        "planned_interval_count": intervals,
    }


def _compare(activity: Activity, plan: PlannedWorkout) -> dict[str, Any]:
    expected_duration, expected_distance, expected_intervals = _planned_targets(plan.payload_snapshot_json or {})
    actual_laps = len(activity.laps)
    comparisons = {
        "duration": _comparison_metric(expected_duration, activity.duration_seconds, "s"),
        "distance": _comparison_metric(expected_distance, _number(activity.distance_meters), "m"),
        "intervals": {"planned": expected_intervals, "detected": actual_laps, "difference": actual_laps - expected_intervals if expected_intervals is not None else None},
        "laps": {"count": actual_laps, "durations_seconds": [lap.duration_seconds for lap in activity.laps]},
        "power": _source_only_comparison(plan.payload_snapshot_json or {}, activity, "power"),
        "heart_rate": _source_only_comparison(plan.payload_snapshot_json or {}, activity, "heart_rate"),
        "cadence": _source_only_comparison(plan.payload_snapshot_json or {}, activity, "cadence"),
    }
    comparable = [value for key, value in comparisons.items() if key in {"duration", "distance"} and value.get("planned") is not None and value.get("actual") is not None]
    if activity.discipline == "strength" and not activity.plan_link.state == "strong_auto_link":
        status = "not_comparable"
    elif not comparable:
        status = "insufficient_data"
    else:
        ratios = [value["actual"] / value["planned"] for value in comparable if value["planned"] > 0]
        if ratios and any(ratio < 0.5 for ratio in ratios):
            status = "partially_completed"
        elif ratios and any(ratio < 0.8 or ratio > 1.2 for ratio in ratios):
            status = "deviated"
        else:
            status = "completed"
    messages = []
    if expected_duration and activity.duration_seconds is not None:
        messages.append(f"{round(activity.duration_seconds / 60)} de {round(expected_duration / 60)} minutos registrados")
    if comparisons["power"].get("status") == "insufficient_data":
        messages.append("Faltan datos para comparar potencia")
    if actual_laps:
        messages.append(f"La actividad contiene {actual_laps} laps")
    return {"format": "plan-actual-comparison-v1", "status": status, "comparisons": _without_none(comparisons), "messages": messages}


def _planned_targets(payload: Any) -> tuple[int | None, float | None, int | None]:
    durations: list[float] = []
    distances: list[float] = []
    intervals = 0
    def visit(value: Any) -> None:
        nonlocal intervals
        if isinstance(value, dict):
            if isinstance(value.get("duration_seconds"), (int, float)) and not isinstance(value["duration_seconds"], bool):
                durations.append(float(value["duration_seconds"]))
                intervals += 1
            if isinstance(value.get("distance_meters"), (int, float)) and not isinstance(value["distance_meters"], bool):
                distances.append(float(value["distance_meters"]))
            if isinstance(value.get("distance_m"), (int, float)) and not isinstance(value["distance_m"], bool):
                distances.append(float(value["distance_m"]))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(payload)
    explicit = payload.get("estimated_duration_seconds") if isinstance(payload, dict) else None
    duration = int(explicit) if isinstance(explicit, (int, float)) else int(sum(durations)) if durations else None
    return duration, sum(distances) if distances else None, intervals or None


def _source_only_comparison(payload: dict[str, Any], activity: Activity, metric: str) -> dict[str, Any]:
    payload_text = json.dumps(payload, ensure_ascii=False).casefold()
    target_declared = metric in payload_text or (metric == "heart_rate" and "bpm" in payload_text) or (metric == "power" and "watt" in payload_text)
    actual = {
        "power": _number(activity.avg_power_watts),
        "heart_rate": activity.avg_heart_rate_bpm,
        "cadence": _number(activity.avg_cadence_rpm),
    }[metric]
    if not target_declared or actual is None:
        return {"status": "insufficient_data"}
    return {"status": "descriptive_only", "actual": actual, "provenance": (activity.metrics_provenance_json or {}).get(f"{metric}_average", "source_provided")}


def _comparison_metric(planned: float | int | None, actual: float | int | None, unit: str) -> dict[str, Any]:
    result = {"planned": planned, "actual": actual, "unit": unit}
    if planned is not None and actual is not None:
        result["absolute_difference"] = actual - planned
        if planned > 0:
            result["percentage_difference"] = round((actual - planned) / planned * 100, 2)
    return result


def _write_json_gzip(user_id: int, filename: str, payload: dict[str, Any]) -> tuple[str, str, int]:
    root = Path(current_app.config["GENERATED_UPLOAD_ROOT"]).resolve()
    directory = (root / f"user_{user_id}" / "activities").resolve()
    _within(directory, root)
    directory.mkdir(parents=True, exist_ok=True)
    final = (directory / filename).resolve()
    _within(final, directory)
    temporary = (directory / f".{uuid.uuid4().hex}.tmp").resolve()
    data = _canonical(payload)
    try:
        with gzip.open(temporary, "xb", compresslevel=6) as handle:
            handle.write(data)
        os.replace(temporary, final)
        try:
            final.chmod(0o600)
        except OSError:
            pass
        compressed = final.read_bytes()
        relative = final.relative_to(root).as_posix()
        return relative, hashlib.sha256(compressed).hexdigest(), len(compressed)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json_gzip(relative: str) -> dict[str, Any]:
    path = _generated_path(relative)
    if path.stat().st_size > MAX_REAL_FILE_BYTES:
        raise ApiError("artifact_too_large", "El artefacto de actividad supera el límite.", 500)
    with gzip.open(path, "rb") as handle:
        data = handle.read(MAX_REAL_FILE_BYTES + 1)
    if len(data) > MAX_REAL_FILE_BYTES:
        raise ApiError("artifact_too_large", "El artefacto de actividad supera el límite.", 500)
    return json.loads(data)


def _read_uploaded(uploaded: UploadedFile, user_id: int) -> bytes:
    if uploaded.user_id != user_id:
        raise ApiError("not_found", "Archivo no encontrado.", 404)
    path = _uploaded_path(uploaded)
    if not path.is_file() or path.is_symlink():
        raise ApiError("source_unavailable", "El archivo original no está disponible.", 409)
    if path.stat().st_size != uploaded.size_bytes or uploaded.size_bytes > MAX_REAL_FILE_BYTES:
        raise ApiError("source_changed", "El archivo original no supera la verificación de integridad.", 409)
    content = path.read_bytes()
    if not hashlib.sha256(content).hexdigest() == uploaded.sha256:
        raise ApiError("source_changed", "El archivo original no supera la verificación de integridad.", 409)
    return content


def _uploaded_path(uploaded: UploadedFile) -> Path:
    root = Path(current_app.config["UPLOAD_ROOT"]).resolve()
    path = (root / f"user_{uploaded.user_id}" / uploaded.stored_filename).resolve()
    _within(path, root)
    return path


def _generated_path(relative: str) -> Path:
    root = Path(current_app.config["GENERATED_UPLOAD_ROOT"]).resolve()
    path = (root / relative).resolve()
    _within(path, root)
    return path


def _within(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ApiError("invalid_storage_path", "La ruta interna no es válida.", 500) from error


def _activity_paths(activity: Activity) -> list[Path]:
    values = []
    if activity.series_artifact:
        values.append(activity.series_artifact.storage_path)
    if activity.route_metadata:
        values.extend(filter(None, [activity.route_metadata.original_storage_path, activity.route_metadata.visible_storage_path]))
    return [_generated_path(value) for value in dict.fromkeys(values)]


def _route_distance(points: list[dict[str, Any]]) -> float:
    return round(sum(_haversine(a, b) for a, b in zip(points, points[1:])), 2)


def _haversine(left: dict[str, Any], right: dict[str, Any]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, [left["lat"], left["lon"], right["lat"], right["lon"]])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0, 1 - value)))


def _gpx(points: list[dict[str, Any]], started_at: datetime) -> bytes:
    root = ET.Element(f"{{{GPX_NS}}}gpx", {"version": "1.1", "creator": "Health Tracker"})
    track = ET.SubElement(root, f"{{{GPX_NS}}}trk")
    segment = ET.SubElement(track, f"{{{GPX_NS}}}trkseg")
    for point in points:
        node = ET.SubElement(segment, f"{{{GPX_NS}}}trkpt", {"lat": _xml_number(point["lat"]), "lon": _xml_number(point["lon"])})
        if point.get("elevation") is not None:
            ET.SubElement(node, f"{{{GPX_NS}}}ele").text = _xml_number(point["elevation"])
        if isinstance(point.get("t"), (int, float)) and math.isfinite(float(point["t"])):
            ET.SubElement(node, f"{{{GPX_NS}}}time").text = _rfc3339(started_at + timedelta(seconds=float(point["t"])))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _activity_identity(activity: Activity) -> dict[str, Any]:
    external = (activity.canonical_json or {}).get("provenance") or {}
    return _without_none({
        "publicId": activity.public_id, "discipline": activity.discipline,
        "subtype": activity.subtype, "originalType": activity.original_type or activity.activity_type,
        "title": activity.title, "startTime": _rfc3339(activity.started_at), "endTime": _rfc3339(activity.ended_at),
        "timezone": activity.timezone_name, "utcOffsetMinutes": activity.utc_offset_minutes,
        "localDate": activity.local_date.isoformat() if activity.local_date else None,
        "environment": activity.environment, "status": activity.status,
        "sourceFormat": activity.source_format, "sourceApplication": activity.source_app,
        "sourceDevice": activity.source_device, "originalFileId": activity.original_file_public_id,
        "sourceType": activity.source_type,
        "provider": external.get("provider"),
        "externalAccountId": external.get("external_account_id"),
        "resourceType": external.get("resource_type"),
        "externalResourceId": external.get("external_resource_id"),
        "contentFingerprint": activity.fingerprint_sha256, "revision": activity.revision,
        "createdAt": _rfc3339(activity.created_at), "updatedAt": _rfc3339(activity.updated_at),
    })


def _summary(activity: Activity) -> dict[str, Any]:
    fields = {
        "duration": (activity.duration_seconds, "s"), "elapsed_time": (activity.elapsed_time_seconds, "s"),
        "moving_time": (activity.moving_time_seconds, "s"), "distance": (_number(activity.distance_meters), "m"),
        "calories": (_number(activity.calories_kcal), "kcal"), "ascent": (_number(activity.elevation_gain_meters), "m"),
        "descent": (_number(activity.elevation_loss_meters), "m"), "heart_rate_average": (activity.avg_heart_rate_bpm, "bpm"),
        "heart_rate_maximum": (activity.max_heart_rate_bpm, "bpm"), "cadence_average": (_number(activity.avg_cadence_rpm), "rpm"),
        "cadence_maximum": (_number(activity.max_cadence_rpm), "rpm"), "speed_average": (_number(activity.avg_speed_mps), "m/s"),
        "speed_maximum": (_number(activity.max_speed_mps), "m/s"), "power_average": (activity.avg_power_watts, "W"),
        "power_maximum": (activity.max_power_watts, "W"),
    }
    provenance = activity.metrics_provenance_json or {}
    return {key: {"value": value, "unit": unit, "provenance": provenance.get(key, "unavailable")} for key, (value, unit) in fields.items() if value is not None}


def _series_metadata(row: ActivitySeriesArtifact | None) -> dict[str, Any]:
    if row is None:
        return {"format": SERIES_FORMAT, "sampleCount": 0, "fields": []}
    return {"format": SERIES_FORMAT, "sampleCount": row.sample_count, "fields": row.fields_json, "sha256": row.sha256, "compression": row.compression}


def _route_summary(row: ActivityRouteMetadata | None) -> dict[str, Any]:
    if row is None:
        return {"present": False, "state": "unavailable"}
    return _without_none({
        "present": row.state == "available" and bool(row.visible_storage_path) and row.visible_point_count > 0, "state": row.state,
        "policy": row.policy, "pointCount": row.visible_point_count,
        "distanceMeters": _number(row.visible_distance_meters),
        "redactStartMeters": row.redact_start_meters, "redactEndMeters": row.redact_end_meters,
    })


def _route_policy(policy: Any, start: Any, end: Any) -> tuple[str, int, int]:
    policy = str(policy or "keep").casefold()
    if policy not in ROUTE_POLICIES:
        raise ApiError("invalid_route_policy", "La política de ruta no es válida.", 400)
    start_i, end_i = _bounded_integer(start, 0, 50_000, "redact_start_meters"), _bounded_integer(end, 0, 50_000, "redact_end_meters")
    if policy != "redact" and (start_i or end_i):
        raise ApiError("invalid_route_policy", "El recorte requiere route_policy=redact.", 400)
    return policy, start_i, end_i


def _ensure_owner(row: Any, user_id: int) -> None:
    if row.user_id != user_id:
        raise ApiError("not_found", "Recurso no encontrado.", 404)


def _ensure_revision(activity: Activity, user_id: int, revision: Any) -> None:
    _ensure_owner(activity, user_id)
    if type(revision) is not int:
        raise ApiError("invalid_request", "Se requiere base_revision.", 400)
    if revision != activity.revision:
        raise ApiError("revision_conflict", "La actividad cambió en el servidor.", 409, {"current_revision": activity.revision})


def _ensure_job_active(job: ActivityImportJob) -> None:
    if _aware(job.expires_at) < utcnow():
        raise ApiError("import_expired", "El import expiró.", 410)


def _key_hash(value: Any) -> str:
    if not isinstance(value, str) or not 8 <= len(value) <= 200:
        raise ApiError("idempotency_key_required", "Se requiere Idempotency-Key de 8 a 200 caracteres.", 400)
    return hashlib.sha256(value.encode()).hexdigest()


def _uuid(value: Any, field: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as error:
        raise ApiError("invalid_uuid", f"{field} no es un UUID válido.", 400) from error


def _optional_uuid(value: Any, field: str) -> str | None:
    return None if value in {None, ""} else _uuid(value, field)


def _optional_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError("invalid_text", "El texto no es válido.", 400)
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", value).strip()
    if len(cleaned) > limit:
        raise ApiError("text_too_long", "El texto supera el límite.", 400)
    return cleaned or None


def _safe_title(value: Any) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", "", str(value or "")).strip()[:200]


def _bounded_integer(value: Any, lower: int, upper: int, field: str) -> int:
    try:
        result = int(value or 0)
    except (TypeError, ValueError) as error:
        raise ApiError("invalid_integer", f"{field} no es válido.", 400) from error
    if isinstance(value, bool) or not lower <= result <= upper:
        raise ApiError("invalid_integer", f"{field} está fuera de rango.", 400)
    return result


def _limit(value: Any, maximum: int) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError) as error:
        raise ApiError("invalid_limit", "El límite no es válido.", 400) from error
    if not 1 <= value <= maximum:
        raise ApiError("invalid_limit", "El límite está fuera de rango.", 400)
    return value


def _metric(summary: dict[str, Any], name: str) -> Any:
    return (summary.get(name) or {}).get("value")


def _integer(value: Any) -> int | None:
    return int(value) if value is not None else None


def _number(value: Any) -> float | int | None:
    if value is None:
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


def _absolute_delta(left: Any, right: Any) -> float | None:
    if left is None or right is None:
        return None
    return round(abs(float(left) - float(right)), 3)


def _relative_delta(left: Any, right: Any) -> float | None:
    if left is None or right is None or float(right) == 0:
        return None
    return round(abs(float(left) - float(right)) / abs(float(right)), 4)


def _parse_instant(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return _aware(parsed).astimezone(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _rfc3339(value: datetime | None) -> str | None:
    return _aware(value).astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def _truncate_instant(value: str | None) -> str | None:
    return value[:13] + ":00:00Z" if value else None


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _canonical(value: Any, *, pretty: bool = False) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2 if pretty else None, separators=None if pretty else (",", ":"), allow_nan=False) + "\n").encode()


def _without_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_without_none(item) for item in value]
    return value


def _csv(fields: tuple[str, ...], rows: list[dict[str, Any]]) -> bytes:
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_safe(row.get(key, "")) for key in fields})
    return output.getvalue().encode("utf-8-sig")


def _csv_safe(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _xml_number(value: Any) -> str:
    return format(float(value), ".10g")
