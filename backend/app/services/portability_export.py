from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import uuid

from flask import current_app
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import (
    DailyEnergy, DailyNutrition, Exercise, FoodProduct, NutritionItem, NutritionMeal, PlannedWorkout,
    PortableArtifact, PortableExportJob, TrainingPlan, TrainingPlanWorkout,
    TrainingSession, TrainingSessionExercise, TrainingSet, UploadedFile, User,
    UserGoal, ReminderRule, WeighIn,
    LabPanel, LabResult, MedicalDocument, MedicalStudy,
)
from app.services.portable_archive import (
    ALL_SECTIONS, MEDIA_TYPE, PortableArchiveError, PortableArchiveWriter,
    canonical_json_bytes, safe_filename, scrub_portable, sha256_path,
)


PORTABLE_NAMESPACE = uuid.UUID("9b1de0a5-73e7-4eb7-a2ac-e9dd6cfed24a")
DEFAULT_SECTIONS = tuple(section for section in ALL_SECTIONS if section not in {"profile", "attachments", "external_sources"})


class PortabilityExportError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expired(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= _now()


def _root() -> Path:
    return Path(current_app.config["PORTABILITY_ROOT"])


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stable_uuid(kind: str, value: str) -> str:
    return str(uuid.uuid5(PORTABLE_NAMESPACE, f"{kind}:{value}"))


def _record(section: str, public_id: str, data: dict, revision: int | None = None) -> dict:
    value = {
        "schema_version": "1.0",
        "record_type": section,
        "public_id": str(uuid.UUID(str(public_id))),
        "data": scrub_portable(data),
    }
    if revision is not None:
        value["revision"] = max(1, int(revision))
    return value


def _safe_source(value: str | None) -> str:
    normalized = (value or "unknown").strip().casefold().replace("-", "_")
    if "health_connect" in normalized:
        return "health_connect"
    if "ble" in normalized or "bluetooth" in normalized:
        return "external_measurement"
    if normalized == "manual":
        return "manual"
    if normalized in {"uploaded", "imported", "portable_import"} or "import" in normalized:
        return "imported"
    return "external"


def _in_range(value: date | datetime | None, start: date | None, end: date | None) -> bool:
    if value is None:
        return True
    target = value.date() if isinstance(value, datetime) else value
    return (start is None or target >= start) and (end is None or target <= end)


def _parse_date(value, field: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise PortabilityExportError("invalid_date", f"{field} debe usar YYYY-MM-DD.") from error


def _request(payload: dict) -> tuple[list[str], date | None, date | None, bool, bool, bool]:
    allowed = {"sections", "date_from", "date_to", "include_attachments", "include_medical_attachments", "include_identifiable_profile", "format"}
    if set(payload) - allowed:
        raise PortabilityExportError("invalid_request", "La solicitud contiene campos no reconocidos.")
    if payload.get("format", "health-tracker-portable-v1") != "health-tracker-portable-v1":
        raise PortabilityExportError("unsupported_format", "El formato solicitado no está soportado.")
    raw_sections = payload.get("sections", list(DEFAULT_SECTIONS))
    if not isinstance(raw_sections, list) or not raw_sections or len(raw_sections) > len(ALL_SECTIONS):
        raise PortabilityExportError("invalid_sections", "Selecciona al menos una sección válida.")
    sections = []
    for section in raw_sections:
        if not isinstance(section, str) or section not in ALL_SECTIONS:
            raise PortabilityExportError("invalid_sections", "La solicitud contiene una sección desconocida.")
        if section not in sections:
            sections.append(section)
    include_attachments = payload.get("include_attachments", False)
    include_medical_attachments = payload.get("include_medical_attachments", False)
    identifiable = payload.get("include_identifiable_profile", False)
    if type(include_attachments) is not bool or type(include_medical_attachments) is not bool or type(identifiable) is not bool:
        raise PortabilityExportError("invalid_request", "Las opciones de privacidad deben ser booleanas.")
    if "attachments" in sections and not (include_attachments or include_medical_attachments):
        raise PortabilityExportError("attachments_not_confirmed", "Los attachments requieren selección explícita.")
    if (include_attachments or include_medical_attachments) and "attachments" not in sections:
        sections.append("attachments")
    if include_medical_attachments:
        for required in ("medical_studies", "lab_panels", "lab_results", "medical_documents_metadata"):
            if required not in sections:
                sections.append(required)
    if "profile" in sections and not identifiable:
        raise PortabilityExportError("profile_not_confirmed", "El perfil identificable requiere selección explícita.")
    start, end = _parse_date(payload.get("date_from"), "date_from"), _parse_date(payload.get("date_to"), "date_to")
    if start and end and start > end:
        raise PortabilityExportError("invalid_date_range", "date_from no puede ser posterior a date_to.")
    return sections, start, end, include_attachments, include_medical_attachments, identifiable


def _query(model, user_id: int, *order, loaders=()):
    statement = db.select(model).where(model.user_id == user_id)
    if loaders:
        statement = statement.options(*loaders)
    if order:
        statement = statement.order_by(*order)
    return db.session.execute(statement).scalars().all()


def _serialize_records(
    user: User,
    sections: list[str],
    start: date | None,
    end: date | None,
    identifiable: bool,
    include_attachments: bool,
    include_medical_attachments: bool,
) -> tuple[dict[str, list[dict]], dict[str, Path]]:
    output: dict[str, list[dict]] = {}
    attachment_files: dict[str, Path] = {}
    sources: dict[str, set[str]] = {}
    medical_upload_ids: set[int] = set()
    medical_attachment_ids: dict[int, str] = {}

    if "profile" in sections:
        output["profile"] = [_record("profile", _stable_uuid("profile", user.public_id), {
            "display_name": user.display_name,
            "email": user.email if identifiable else None,
            "identifiable": identifiable,
        })]
    if "settings" in sections:
        output["settings"] = [_record("settings", _stable_uuid("settings", user.public_id), {
            "preferred_load_unit": user.preferred_load_unit,
            "timezone": user.timezone,
        })]
    if "goals" in sections:
        rows = _query(UserGoal, user.id, UserGoal.created_at, UserGoal.public_id)
        output["goals"] = [_record("goals", row.public_id, {
            "goal_type": row.goal_type,
            "target_value": row.target_value,
            "unit": row.unit,
            "period": row.period,
            "applicable_days": row.applicable_days_json or [],
            "timezone": row.timezone,
            "start_date": row.start_date,
            "end_date": row.end_date,
            "state": row.state,
            "source": "manual" if row.source == "manual" else "portable_import",
            "related_public_id": row.related_public_id,
        }, row.revision) for row in rows]
    if "reminder_rules" in sections:
        rows = _query(ReminderRule, user.id, ReminderRule.created_at, ReminderRule.public_id,
            loaders=(selectinload(ReminderRule.goal),))
        output["reminder_rules"] = [_record("reminder_rules", row.public_id, {
            "reminder_type": row.reminder_type,
            "goal_public_id": row.goal.public_id if row.goal else None,
            "local_time": row.local_time.strftime("%H:%M"),
            "applicable_days": row.applicable_days_json or [],
            "lead_minutes": row.lead_minutes,
            "quiet_start": row.quiet_start.strftime("%H:%M") if row.quiet_start else None,
            "quiet_end": row.quiet_end.strftime("%H:%M") if row.quiet_end else None,
            "quiet_timezone": row.quiet_timezone,
            "snooze_options": row.snooze_options_json or [],
            "max_per_day": row.max_per_day,
            "cooldown_minutes": row.cooldown_minutes,
            "enabled": row.enabled,
            "timezone": row.timezone,
            "related_public_id": row.related_public_id,
        }, row.revision) for row in rows]
    medical_studies = [
        row for row in _query(
            MedicalStudy,
            user.id,
            MedicalStudy.study_date,
            MedicalStudy.public_id,
            loaders=(
                selectinload(MedicalStudy.panels).selectinload(LabPanel.results),
                selectinload(MedicalStudy.documents).selectinload(MedicalDocument.uploaded_file),
            ),
        )
        if _in_range(row.study_date, start, end)
    ]
    if "medical_studies" in sections:
        output["medical_studies"] = [_record("medical_studies", row.public_id, {
            "study_type": row.study_type,
            "title": row.title,
            "laboratory_name": row.laboratory_name,
            "professional_name": row.professional_name,
            "study_date": row.study_date,
            "issued_date": row.issued_date,
            "timezone": row.timezone,
            "notes": row.notes,
            "state": row.state,
            "source": "manual" if row.source in {"manual", "mobile"} else "imported",
        }, row.revision) for row in medical_studies]
    panels = [panel for study in medical_studies for panel in study.panels]
    if "lab_panels" in sections:
        output["lab_panels"] = [_record("lab_panels", row.public_id, {
            "study_public_id": row.study.public_id,
            "name": row.name,
            "display_order": row.display_order,
            "source": "manual" if row.source in {"manual", "mobile"} else "imported",
        }, row.revision) for row in panels]
    results = [result for panel in panels for result in panel.results]
    if "lab_results" in sections:
        output["lab_results"] = [_record("lab_results", row.public_id, {
            "panel_public_id": row.panel.public_id,
            "display_name": row.display_name,
            "canonical_key": row.canonical_key,
            "value_type": row.value_type,
            "original_value": row.original_value,
            "numeric_value": row.numeric_value,
            "comparator": row.comparator,
            "original_unit": row.original_unit,
            "reference_lower": row.reference_lower,
            "reference_upper": row.reference_upper,
            "reference_text": row.reference_text,
            "source_status": row.source_status,
            "method": row.method,
            "specimen": row.specimen,
            "notes": row.notes,
            "display_order": row.display_order,
            "source": "manual" if row.source in {"manual", "mobile"} else "imported",
        }, row.revision) for row in results]
    medical_documents = [document for study in medical_studies for document in study.documents]
    for document in medical_documents:
        if document.uploaded_file_id:
            medical_upload_ids.add(document.uploaded_file_id)
            medical_attachment_ids[document.uploaded_file_id] = _stable_uuid("medical_attachment", document.sha256)
    if "medical_documents_metadata" in sections:
        output["medical_documents_metadata"] = [_record("medical_documents_metadata", row.public_id, {
            "study_public_id": row.study.public_id,
            "document_type": row.document_type,
            "filename": safe_filename(row.original_filename),
            "mime_type": row.mime_type,
            "size_bytes": row.size_bytes,
            "sha256": row.sha256,
            "availability": row.availability,
            "attachment_public_id": medical_attachment_ids.get(row.uploaded_file_id) if include_medical_attachments else None,
            "source": "manual" if row.source in {"manual", "mobile"} else "imported",
        }, row.revision) for row in medical_documents]
    if "exercises" in sections:
        rows = _query(Exercise, user.id, Exercise.normalized_name, Exercise.public_id,
            loaders=(selectinload(Exercise.aliases), selectinload(Exercise.load_profile)))
        output["exercises"] = [_record("exercises", row.public_id, {
            "canonical_name": row.canonical_name,
            "aliases": [alias.alias_name for alias in row.aliases],
            "load_profile": None if row.load_profile is None else {
                "public_id": row.load_profile.public_id,
                "load_mode": row.load_profile.load_mode,
                "preferred_unit": row.load_profile.preferred_unit,
                "configuration": row.load_profile.configuration_json or {},
                "quick_increments": row.load_profile.quick_increments_json or [],
                "revision": row.load_profile.revision,
            },
        }, getattr(row.load_profile, "revision", 1)) for row in rows]
    if "plans" in sections:
        rows = _query(TrainingPlan, user.id, TrainingPlan.created_at, TrainingPlan.public_id,
            loaders=(selectinload(TrainingPlan.versions),))
        output["plans"] = [_record("plans", row.public_id, {
            "name": row.name, "description": row.description, "status": row.status,
            "active_version_number": row.active_version_number, "archived_at": row.archived_at,
            "versions": [{
                "public_id": version.public_id, "version_number": version.version_number,
                "schema_version": version.schema_version, "content": version.content,
                "change_reason": version.change_reason, "created_at": version.created_at,
            } for version in row.versions],
        }, row.revision) for row in rows]
    if "workouts" in sections:
        rows = _query(TrainingPlanWorkout, user.id, TrainingPlanWorkout.training_plan_id, TrainingPlanWorkout.position,
            loaders=(selectinload(TrainingPlanWorkout.training_plan),))
        output["workouts"] = [_record("workouts", row.public_id, {
            "plan_public_id": row.training_plan.public_id, "name": row.name, "notes": row.notes,
            "position": row.position, "exercises": row.exercises_json or [],
        }, row.revision) for row in rows]
    if "schedules" in sections:
        rows = [row for row in _query(PlannedWorkout, user.id, PlannedWorkout.scheduled_for_date, PlannedWorkout.public_id,
            loaders=(selectinload(PlannedWorkout.training_plan), selectinload(PlannedWorkout.training_plan_version))) if _in_range(row.scheduled_for_date, start, end)]
        output["schedules"] = [_record("schedules", row.public_id, {
            "plan_public_id": row.training_plan.public_id,
            "plan_version_public_id": row.training_plan_version.public_id,
            "scheduled_for_date": row.scheduled_for_date, "timezone": row.timezone,
            "status": row.status, "title": row.title_snapshot,
            "payload_snapshot": row.payload_snapshot_json, "source_version": row.source_version,
            "completed_at": row.completed_at, "cancelled_at": row.cancelled_at,
            "deleted_at": row.deleted_at,
        }, row.revision) for row in rows]
    if "sessions" in sections or "session_exercises" in sections or "sets" in sections:
        sessions = [row for row in _query(TrainingSession, user.id, TrainingSession.performed_at, TrainingSession.public_id,
            loaders=(
                selectinload(TrainingSession.training_plan),
                selectinload(TrainingSession.training_plan_version),
                selectinload(TrainingSession.planned_workout),
                selectinload(TrainingSession.exercises).selectinload(TrainingSessionExercise.sets),
            )) if _in_range(row.performed_at, start, end)]
        if "sessions" in sections:
            output["sessions"] = [_record("sessions", row.public_id, {
                "plan_public_id": row.training_plan.public_id,
                "plan_version_public_id": row.training_plan_version.public_id,
                "schedule_public_id": row.planned_workout.public_id if row.planned_workout else None,
                "timezone": row.timezone, "started_at": row.started_at, "completed_at": row.completed_at,
                "performed_at": row.performed_at, "planned_week_number": row.planned_week_number,
                "planned_day_number": row.planned_day_number, "duration_seconds": row.duration_seconds,
                "average_heart_rate_bpm": row.average_heart_rate_bpm,
                "calories_burned": row.calories_burned, "notes": row.notes,
            }, row.revision) for row in sessions]
        exercises = [exercise for session in sessions for exercise in session.exercises]
        if "session_exercises" in sections:
            output["session_exercises"] = [_record("session_exercises", row.public_id, {
                "session_public_id": row.training_session.public_id, "exercise_order": row.exercise_order,
                "planned_exercise_order": row.planned_exercise_order, "name": row.name, "notes": row.notes,
            }) for row in exercises]
        if "sets" in sections:
            output["sets"] = [_record("sets", _stable_uuid("set", f"{exercise.public_id}:{row.set_number}"), {
                "session_exercise_public_id": exercise.public_id, "set_number": row.set_number,
                "planned_set_number": row.planned_set_number, "weight_kg": row.weight_kg,
                "load_details": row.load_details_json, "reps": row.reps, "rir": row.rir,
                "rpe": row.rpe, "rest_seconds": row.rest_seconds, "notes": row.notes,
            }) for exercise in exercises for row in exercise.sets]
    if "body_stats" in sections:
        rows = [row for row in _query(WeighIn, user.id, WeighIn.recorded_at, WeighIn.public_id) if _in_range(row.recorded_at, start, end)]
        output["body_stats"] = []
        for row in rows:
            source = _safe_source(row.source); sources.setdefault(source, set()).add("body_stats")
            output["body_stats"].append(_record("body_stats", row.public_id, {
                "recorded_at": row.recorded_at, "weight_kg": row.weight_kg,
                "body_fat_percent": row.body_fat_percentage, "muscle_mass_kg": row.muscle_mass_kg,
                "water_percent": row.water_percentage, "visceral_fat": row.visceral_fat,
                "bmr_kcal": row.bmr_kcal, "bmi": row.bmi, "source": source, "notes": row.notes,
            }, row.revision))
    if "nutrition_entries" in sections:
        rows = [row for row in _query(DailyNutrition, user.id, DailyNutrition.date, DailyNutrition.id,
            loaders=(selectinload(DailyNutrition.meals).selectinload(NutritionMeal.items).selectinload(NutritionItem.food_product),)) if _in_range(row.date, start, end)]
        output["nutrition_entries"] = []
        for row in rows:
            source = _safe_source(row.source); sources.setdefault(source, set()).add("nutrition_entries")
            output["nutrition_entries"].append(_record("nutrition_entries", _stable_uuid("nutrition_day", row.date.isoformat()), {
                "date": row.date, "source": source, "notes": row.notes,
                "totals": {field: getattr(row, field) for field in ("calories", "protein_g", "fat_g", "net_carbs_g", "total_carbs_g", "fiber_g", "sugar_g", "sodium_mg")},
                "meals": [{"meal_type": meal.meal_type, "name": meal.name, "sort_order": meal.sort_order,
                    "items": [{
                        "public_id": item.public_id, "name": item.name, "quantity": item.quantity,
                        "unit": item.unit, "sort_order": item.sort_order, "source": _safe_source(item.source),
                        "calories": item.calories, "protein_g": item.protein_g, "fat_g": item.fat_g,
                        "net_carbs_g": item.net_carbs_g, "total_carbs_g": item.total_carbs_g,
                        "fiber_g": item.fiber_g, "sugar_g": item.sugar_g, "sodium_mg": item.sodium_mg,
                        "notes": item.notes, "revision": item.revision,
                        "food_public_id": item.food_product.public_id if item.food_product else None,
                    } for item in meal.items]} for meal in row.meals],
            }))
    if "custom_foods" in sections:
        rows = _query(FoodProduct, user.id, FoodProduct.name, FoodProduct.public_id)
        output["custom_foods"] = []
        for row in rows:
            source = _safe_source(row.source); sources.setdefault(source, set()).add("custom_foods")
            data = {"name": row.name, "brand": row.brand, "serving_size_g": row.serving_size_g,
                "serving_label": row.serving_label, "source": source, "notes": row.notes,
                "is_active": row.is_active}
            for field in ("calories_per_100g", "protein_g_per_100g", "fat_g_per_100g", "carbs_g_per_100g", "net_carbs_g_per_100g", "fiber_g_per_100g", "sodium_mg_per_100g"):
                data[field] = getattr(row, field)
            output["custom_foods"].append(_record("custom_foods", row.public_id, data, row.revision))
    if "steps" in sections:
        rows = [row for row in _query(DailyEnergy, user.id, DailyEnergy.date, DailyEnergy.public_id) if row.steps is not None and _in_range(row.date, start, end)]
        output["steps"] = []
        for row in rows:
            source = _safe_source(row.source); sources.setdefault(source, set()).add("steps")
            output["steps"].append(_record("steps", row.public_id, {
                "date": row.date, "steps": row.steps, "distance_meters": row.distance_meters,
                "source": source, "notes": row.notes,
            }, row.revision))
    if "external_sources" in sections:
        output["external_sources"] = [_record("external_sources", _stable_uuid("source", source), {
            "source": source, "domains": sorted(domains), "reference_only": True,
        }) for source, domains in sorted(sources.items()) if source != "manual"]
    if "attachments" in sections:
        output["attachments"] = []
        maximum_total = current_app.config["PORTABILITY_MAX_ATTACHMENTS_BYTES"]
        total = 0
        upload_root = Path(current_app.config["UPLOAD_ROOT"]).resolve()
        data_root = Path(current_app.config["DATA_ROOT"]).resolve()
        for row in _query(UploadedFile, user.id, UploadedFile.created_at, UploadedFile.id):
            is_medical = row.id in medical_upload_ids
            if (is_medical and not include_medical_attachments) or (not is_medical and not include_attachments):
                continue
            source = (data_root / row.storage_path).resolve()
            try:
                source.relative_to(upload_root)
            except ValueError:
                continue
            if source.is_symlink() or not source.is_file():
                continue
            digest, size = sha256_path(source, maximum=current_app.config["PORTABILITY_MAX_FILE_BYTES"])
            if digest != row.sha256 or size != row.size_bytes:
                continue
            total += size
            if total > maximum_total:
                raise PortabilityExportError("attachments_too_large", "Los attachments seleccionados superan el límite.", 413)
            public_id = medical_attachment_ids.get(row.id) if is_medical else _stable_uuid("attachment", row.sha256)
            archive_path = f"attachments/{public_id}/{safe_filename(row.original_filename)}"
            attachment_files[archive_path] = source
            output["attachments"].append(_record("attachments", public_id, {
                "archive_path": archive_path, "filename": safe_filename(row.original_filename),
                "sha256": row.sha256, "size_bytes": row.size_bytes,
                "media_type": (row.mime_type or "application/octet-stream")[:100],
                "source_type": "medical_document" if is_medical else "user_upload",
            }))
        included_attachment_ids = {row["public_id"] for row in output["attachments"]}
        for record in output.get("medical_documents_metadata", []):
            attachment_id = record["data"].get("attachment_public_id")
            if attachment_id and attachment_id not in included_attachment_ids:
                record["data"]["attachment_public_id"] = None
                if record["data"]["availability"] == "available":
                    record["data"]["availability"] = "missing"
    return output, attachment_files


def create_export(user: User, payload: dict, raw_idempotency_key: str) -> tuple[PortableExportJob, bool]:
    if not isinstance(raw_idempotency_key, str) or not raw_idempotency_key.strip() or len(raw_idempotency_key) > 200:
        raise PortabilityExportError("idempotency_required", "Se requiere Idempotency-Key.")
    sections, start, end, include_attachments, include_medical_attachments, identifiable = _request(payload)
    normalized = {"sections": sections, "date_from": start.isoformat() if start else None, "date_to": end.isoformat() if end else None,
        "include_attachments": include_attachments, "include_medical_attachments": include_medical_attachments,
        "include_identifiable_profile": identifiable, "format": "health-tracker-portable-v1"}
    request_hash = _hash(canonical_json_bytes(normalized))
    key_hash = _hash(raw_idempotency_key.strip().encode("utf-8"))
    existing = db.session.execute(db.select(PortableExportJob).where(
        PortableExportJob.user_id == user.id, PortableExportJob.idempotency_key_hash == key_hash
    )).scalar_one_or_none()
    if existing:
        if existing.request_hash != request_hash:
            raise PortabilityExportError("idempotency_conflict", "Idempotency-Key ya se usó con otra solicitud.", 409)
        return existing, True
    now = _now()
    job = PortableExportJob(user_id=user.id, state="preparing", sections_json=sections, counts_json={},
        include_attachments=(include_attachments or include_medical_attachments), include_identifiable_profile=identifiable,
        date_from=start, date_to=end, request_hash=request_hash, idempotency_key_hash=key_hash,
        created_at=now, expires_at=now + timedelta(hours=current_app.config["PORTABILITY_TTL_HOURS"]))
    try:
        with db.session.begin_nested():
            db.session.add(job)
            db.session.flush()
    except IntegrityError:
        existing = db.session.execute(db.select(PortableExportJob).where(
            PortableExportJob.user_id == user.id,
            PortableExportJob.idempotency_key_hash == key_hash,
        )).scalar_one_or_none()
        if existing is None:
            raise PortabilityExportError("idempotency_conflict", "No fue posible reclamar la solicitud.", 409)
        if existing.request_hash != request_hash:
            raise PortabilityExportError("idempotency_conflict", "Idempotency-Key ya se usó con otra solicitud.", 409)
        return existing, True
    destination_dir = _root() / f"user_{user.id}" / "exports"
    destination = destination_dir / f"{job.public_id}.htpack"
    try:
        records, attachments = _serialize_records(
            user, sections, start, end, identifiable,
            include_attachments, include_medical_attachments,
        )
        omitted = [section for section in ALL_SECTIONS if section not in records]
        manifest = PortableArchiveWriter(Path(current_app.config["SCHEMA_ROOT"])).write(
            destination, export_id=job.public_id, created_at=now,
            application_version=current_app.config.get("APP_VERSION", "unknown"), timezone_name=user.timezone,
            records=records, omitted_sections=omitted, identifiable_profile=identifiable,
            attachment_files=attachments,
        )
        digest, size = sha256_path(destination, maximum=current_app.config["PORTABILITY_MAX_COMPRESSED_BYTES"])
        artifact = PortableArtifact(user_id=user.id, kind="export",
            relative_path=destination.relative_to(_root()).as_posix(), filename=f"health-tracker-{job.public_id}.htpack",
            media_type=MEDIA_TYPE, sha256=digest, size_bytes=size, created_at=now, expires_at=job.expires_at)
        db.session.add(artifact); db.session.flush()
        job.artifact_id = artifact.id; job.artifact_hash = digest; job.size_bytes = size
        job.counts_json = manifest["counts"]; job.state = "ready"; job.completed_at = _now(); job.revision += 1
        db.session.commit()
    except Exception as error:
        db.session.rollback(); destination.unlink(missing_ok=True)
        failed = PortableExportJob(user_id=user.id, state="failed", sections_json=sections, counts_json={},
            include_attachments=(include_attachments or include_medical_attachments), include_identifiable_profile=identifiable,
            date_from=start, date_to=end, request_hash=request_hash, idempotency_key_hash=key_hash,
            created_at=now, expires_at=now + timedelta(hours=current_app.config["PORTABILITY_TTL_HOURS"]),
            completed_at=_now(), error_code=getattr(error, "code", "generation_failed"))
        db.session.add(failed); db.session.commit()
        if isinstance(error, (PortabilityExportError, PortableArchiveError)):
            raise PortabilityExportError(error.code, str(error), getattr(error, "status", 400)) from error
        raise
    return job, False


def list_exports(user_id: int) -> list[PortableExportJob]:
    expire_jobs(user_id=user_id)
    return db.session.execute(db.select(PortableExportJob).where(PortableExportJob.user_id == user_id).order_by(PortableExportJob.created_at.desc())).scalars().all()


def get_export(user_id: int, public_id: str) -> PortableExportJob | None:
    try:
        public_id = str(uuid.UUID(public_id))
    except ValueError:
        return None
    job = db.session.execute(db.select(PortableExportJob).where(PortableExportJob.user_id == user_id, PortableExportJob.public_id == public_id)).scalar_one_or_none()
    if job and _expired(job.expires_at) and job.state == "ready":
        _expire(job); db.session.commit()
    return job


def resolve_export_download(job: PortableExportJob, user_id: int) -> Path:
    if job.user_id != user_id or job.state != "ready" or job.artifact is None:
        raise PortabilityExportError("not_found", "Exportación no disponible.", 404)
    root = _root().resolve(); path = (root / job.artifact.relative_path).resolve()
    try: path.relative_to(root)
    except ValueError as error: raise PortabilityExportError("artifact_invalid", "El artefacto no es seguro.", 409) from error
    if path.is_symlink() or not path.is_file():
        raise PortabilityExportError("artifact_missing", "El artefacto ya no está disponible.", 410)
    digest, size = sha256_path(path, maximum=current_app.config["PORTABILITY_MAX_COMPRESSED_BYTES"])
    if digest != job.artifact.sha256 or size != job.artifact.size_bytes:
        raise PortabilityExportError("artifact_integrity", "La integridad del artefacto no coincide.", 409)
    return path


def delete_export(job: PortableExportJob, user_id: int) -> None:
    if job.user_id != user_id:
        raise PortabilityExportError("not_found", "Exportación no encontrada.", 404)
    if job.artifact:
        path = (_root() / job.artifact.relative_path).resolve(); root = _root().resolve()
        try: path.relative_to(root)
        except ValueError: path = None
        if path is not None and not path.is_symlink(): path.unlink(missing_ok=True)
        db.session.delete(job.artifact); job.artifact = None; job.artifact_id = None
    job.state = "deleted"; job.artifact_hash = None; job.size_bytes = None; job.revision += 1
    db.session.commit()


def _expire(job: PortableExportJob) -> None:
    if job.artifact:
        path = (_root() / job.artifact.relative_path).resolve(); root = _root().resolve()
        try: path.relative_to(root)
        except ValueError: path = None
        if path is not None and not path.is_symlink(): path.unlink(missing_ok=True)
        db.session.delete(job.artifact); job.artifact = None; job.artifact_id = None
    job.state = "expired"; job.artifact_hash = None; job.size_bytes = None; job.revision += 1


def expire_jobs(user_id: int | None = None) -> int:
    statement = db.select(PortableExportJob).where(PortableExportJob.state == "ready", PortableExportJob.expires_at <= _now())
    if user_id is not None: statement = statement.where(PortableExportJob.user_id == user_id)
    rows = db.session.execute(statement).scalars().all()
    for row in rows: _expire(row)
    if rows: db.session.commit()
    return len(rows)


def export_job_document(job: PortableExportJob) -> dict:
    return {"export_id": job.public_id, "state": job.state, "format": "health-tracker-portable-v1",
        "format_version": job.format_version, "sections": job.sections_json, "counts": job.counts_json or {},
        "size_bytes": job.size_bytes, "sha256": job.artifact_hash, "created_at": scrub_portable(job.created_at),
        "expires_at": scrub_portable(job.expires_at), "completed_at": scrub_portable(job.completed_at),
        "revision": job.revision, "error_code": job.error_code,
        "download_ready": job.state == "ready" and job.artifact_id is not None,
        "integrity": "sha256" if job.state == "ready" else None,
        "authenticity": "not_proven" if job.state == "ready" else None}
