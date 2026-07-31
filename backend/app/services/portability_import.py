from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import uuid

from flask import current_app
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models import (
    DailyEnergy, DailyNutrition, Exercise, ExerciseAlias, ExerciseLoadProfile,
    FoodProduct, NutritionItem, NutritionMeal, PlannedWorkout, PortableArtifact,
    PortableImportDecision, PortableImportJob, PortableImportMapping,
    TrainingPlan, TrainingPlanVersion, TrainingPlanWorkout, TrainingSession,
    TrainingSessionExercise, TrainingSet, UploadedFile, User, WeighIn,
)
from app.services.exercise_identity import normalize_exercise_name
from app.services.portable_archive import (
    ALL_SECTIONS, MEDIA_TYPE, PortableArchiveError, PortableArchiveReader,
    PortableLimits, canonical_json_bytes, safe_filename, scrub_portable,
    sha256_bytes, sha256_path,
)


STRATEGIES = {
    "skip_existing", "import_as_new", "use_destination",
    "update_when_identical_lineage", "require_manual_resolution",
}
DEPENDENCY_ORDER = (
    "profile", "settings", "custom_foods", "exercises", "plans", "workouts",
    "schedules", "sessions", "session_exercises", "sets", "body_stats",
    "nutrition_entries", "steps", "attachments", "external_sources",
)
PUBLIC_MODELS = {
    "exercises": Exercise, "plans": TrainingPlan, "workouts": TrainingPlanWorkout,
    "schedules": PlannedWorkout, "sessions": TrainingSession,
    "session_exercises": TrainingSessionExercise, "body_stats": WeighIn,
    "custom_foods": FoodProduct, "steps": DailyEnergy,
}


class PortabilityImportError(ValueError):
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


def _reader() -> PortableArchiveReader:
    return PortableArchiveReader(Path(current_app.config["SCHEMA_ROOT"]), PortableLimits(
        max_compressed_bytes=current_app.config["PORTABILITY_MAX_COMPRESSED_BYTES"],
        max_uncompressed_bytes=current_app.config["PORTABILITY_MAX_UNCOMPRESSED_BYTES"],
        max_files=current_app.config["PORTABILITY_MAX_FILES"],
        max_file_bytes=current_app.config["PORTABILITY_MAX_FILE_BYTES"],
        max_records_per_section=current_app.config["PORTABILITY_MAX_RECORDS_PER_SECTION"],
        max_json_depth=current_app.config["PORTABILITY_MAX_JSON_DEPTH"],
        max_string_length=current_app.config["PORTABILITY_MAX_STRING_LENGTH"],
        max_json_line_bytes=current_app.config["PORTABILITY_MAX_JSON_LINE_BYTES"],
        max_attachments_bytes=current_app.config["PORTABILITY_MAX_ATTACHMENTS_BYTES"],
    ))


def _artifact_path(artifact: PortableArtifact) -> Path:
    root = _root().resolve(); path = (root / artifact.relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise PortabilityImportError("artifact_invalid", "El artefacto temporal no es seguro.", 409) from error
    if path.is_symlink() or not path.is_file():
        raise PortabilityImportError("artifact_missing", "El paquete temporal ya no está disponible.", 410)
    return path


def _store_upload(storage: FileStorage, user_id: int) -> tuple[Path, str, int]:
    if storage is None or not storage.filename:
        raise PortabilityImportError("file_required", "Selecciona un paquete .htpack.")
    directory = _root() / f"user_{user_id}" / "imports"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{uuid.uuid4()}.htpack"
    temporary = destination.with_name(f".{destination.name}.uploading")
    digest = hashlib.sha256(); size = 0
    try:
        with temporary.open("xb") as target:
            while chunk := storage.stream.read(1024 * 1024):
                size += len(chunk)
                if size > current_app.config["PORTABILITY_MAX_COMPRESSED_BYTES"]:
                    raise PortabilityImportError("package_too_large", "El paquete supera el límite permitido.", 413)
                digest.update(chunk); target.write(chunk)
        if size == 0:
            raise PortabilityImportError("invalid_archive", "El paquete está vacío.")
        temporary.replace(destination)
        return destination, digest.hexdigest(), size
    except Exception:
        temporary.unlink(missing_ok=True); destination.unlink(missing_ok=True)
        raise


def _selected(value, available: list[str]) -> list[str]:
    if value is None or value == "":
        return list(available)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise PortabilityImportError("invalid_sections", "La selección de secciones no es JSON válido.") from error
    if not isinstance(value, list) or not value:
        raise PortabilityImportError("invalid_sections", "Selecciona al menos una sección.")
    selected = []
    for section in value:
        if section not in available:
            raise PortabilityImportError("invalid_sections", "La selección contiene una sección no disponible.")
        if section not in selected:
            selected.append(section)
    return selected


def _clean(value):
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items() if item is not None and key not in {"revision"}}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, Decimal):
        return format(value, "f").rstrip("0").rstrip(".")
    if isinstance(value, (date, datetime)):
        return scrub_portable(value)
    return value


def _same_data(left: dict, right: dict) -> bool:
    return canonical_json_bytes(_clean(left)) == canonical_json_bytes(_clean(right))


def _owned_public(section: str, source_id: str, user_id: int):
    model = PUBLIC_MODELS.get(section)
    if model is None:
        return None, False
    row = db.session.execute(db.select(model).where(model.public_id == source_id)).scalar_one_or_none()
    return row, bool(row is not None and row.user_id != user_id)


def _existing_data(section: str, row) -> dict:
    if section == "exercises":
        return {"canonical_name": row.canonical_name, "aliases": [item.alias_name for item in row.aliases],
            "load_profile": None if row.load_profile is None else {"public_id": row.load_profile.public_id, "load_mode": row.load_profile.load_mode,
            "preferred_unit": row.load_profile.preferred_unit, "configuration": row.load_profile.configuration_json or {},
            "quick_increments": row.load_profile.quick_increments_json or []}}
    if section == "plans":
        return {"name": row.name, "description": row.description, "status": row.status,
            "active_version_number": row.active_version_number, "archived_at": row.archived_at,
            "versions": [{"public_id": item.public_id, "version_number": item.version_number,
                "schema_version": item.schema_version, "content": item.content,
                "change_reason": item.change_reason, "created_at": item.created_at} for item in row.versions]}
    if section == "workouts":
        return {"plan_public_id": row.training_plan.public_id, "name": row.name, "notes": row.notes,
            "position": row.position, "exercises": row.exercises_json or []}
    if section == "schedules":
        return {"plan_public_id": row.training_plan.public_id, "plan_version_public_id": row.training_plan_version.public_id,
            "scheduled_for_date": row.scheduled_for_date, "timezone": row.timezone, "status": row.status,
            "title": row.title_snapshot, "payload_snapshot": row.payload_snapshot_json, "source_version": row.source_version,
            "completed_at": row.completed_at, "cancelled_at": row.cancelled_at, "deleted_at": row.deleted_at}
    if section == "sessions":
        return {"plan_public_id": row.training_plan.public_id, "plan_version_public_id": row.training_plan_version.public_id,
            "schedule_public_id": row.planned_workout.public_id if row.planned_workout else None,
            "timezone": row.timezone, "started_at": row.started_at, "completed_at": row.completed_at,
            "performed_at": row.performed_at, "planned_week_number": row.planned_week_number,
            "planned_day_number": row.planned_day_number, "duration_seconds": row.duration_seconds,
            "average_heart_rate_bpm": row.average_heart_rate_bpm, "calories_burned": row.calories_burned, "notes": row.notes}
    if section == "session_exercises":
        return {"session_public_id": row.training_session.public_id, "exercise_order": row.exercise_order,
            "planned_exercise_order": row.planned_exercise_order, "name": row.name, "notes": row.notes}
    if section == "body_stats":
        return {"recorded_at": row.recorded_at, "weight_kg": row.weight_kg,
            "body_fat_percent": row.body_fat_percentage, "muscle_mass_kg": row.muscle_mass_kg,
            "water_percent": row.water_percentage, "visceral_fat": row.visceral_fat,
            "bmr_kcal": row.bmr_kcal, "bmi": row.bmi, "source": _portable_source(row.source), "notes": row.notes}
    if section == "custom_foods":
        result = {"name": row.name, "brand": row.brand, "serving_size_g": row.serving_size_g,
            "serving_label": row.serving_label, "source": _portable_source(row.source), "notes": row.notes,
            "is_active": row.is_active}
        for field in ("calories_per_100g", "protein_g_per_100g", "fat_g_per_100g", "carbs_g_per_100g", "net_carbs_g_per_100g", "fiber_g_per_100g", "sodium_mg_per_100g"):
            result[field] = getattr(row, field)
        return result
    if section == "steps":
        return {"date": row.date, "steps": row.steps, "distance_meters": row.distance_meters,
            "source": _portable_source(row.source), "notes": row.notes}
    return {}


def _portable_source(value: str | None) -> str:
    value = (value or "").casefold()
    if "health_connect" in value: return "health_connect"
    if value == "manual": return "manual"
    if "ble" in value: return "external_measurement"
    if "import" in value or value == "uploaded": return "imported"
    return "external"


def _natural_existing(section: str, record: dict, user_id: int):
    data = record["data"]
    if section == "exercises":
        return db.session.execute(db.select(Exercise).where(Exercise.user_id == user_id,
            Exercise.normalized_name == normalize_exercise_name(data["canonical_name"]))).scalar_one_or_none()
    if section == "custom_foods":
        return db.session.execute(db.select(FoodProduct).where(FoodProduct.user_id == user_id,
            FoodProduct.name == data["name"], FoodProduct.brand == data.get("brand"))).scalar_one_or_none()
    if section == "nutrition_entries":
        return db.session.execute(db.select(DailyNutrition).where(DailyNutrition.user_id == user_id,
            DailyNutrition.date == _date(data["date"]))).scalar_one_or_none()
    if section == "attachments":
        return db.session.execute(db.select(UploadedFile).where(UploadedFile.user_id == user_id,
            UploadedFile.sha256 == data["sha256"])).scalar_one_or_none()
    return None


def _classify(section: str, record: dict, user: User, package_ids: dict[str, set[str]]) -> dict:
    source_id = record["public_id"]; data = record["data"]
    if section == "profile":
        existing = {"display_name": user.display_name, "email": user.email, "identifiable": data.get("identifiable", False)}
        classification = "same_record" if _same_data(data, existing) else "compatible_update"
        return _plan_row(section, source_id, classification, "skip_existing" if classification == "same_record" else "update_when_identical_lineage", source_id)
    if section == "settings":
        existing = {"preferred_load_unit": user.preferred_load_unit, "timezone": user.timezone}
        classification = "same_record" if _same_data(data, existing) else "compatible_update"
        return _plan_row(section, source_id, classification, "skip_existing" if classification == "same_record" else "update_when_identical_lineage", source_id)
    if section == "external_sources":
        return _plan_row(section, source_id, "same_record", "skip_existing", source_id)
    row, foreign = _owned_public(section, source_id, user.id)
    if foreign:
        return _plan_row(section, source_id, "foreign_collision", "import_as_new", None)
    if row is not None:
        same = _same_data(data, _existing_data(section, row))
        return _plan_row(section, source_id, "same_record" if same else "conflict",
            "skip_existing" if same else "require_manual_resolution", row.public_id)
    natural = _natural_existing(section, record, user.id)
    if natural is not None:
        same = section in PUBLIC_MODELS and _same_data(data, _existing_data(section, natural))
        return _plan_row(section, source_id, "same_record" if same else "duplicate_candidate",
            "skip_existing" if same else "require_manual_resolution", getattr(natural, "public_id", source_id))
    reference = None
    reference_section = None
    for key, parent in (("plan_public_id", "plans"), ("session_public_id", "sessions"),
                        ("session_exercise_public_id", "session_exercises")):
        if data.get(key): reference, reference_section = data[key], parent; break
    if reference and reference not in package_ids.get(reference_section, set()):
        model = PUBLIC_MODELS.get(reference_section)
        found = model and db.session.execute(db.select(model).where(model.user_id == user.id, model.public_id == reference)).scalar_one_or_none()
        if found is None:
            return _plan_row(section, source_id, "broken_reference", "require_manual_resolution", None,
                ["La referencia padre no existe en el paquete ni en la cuenta destino."])
    return _plan_row(section, source_id, "new", "import_as_new", source_id)


def _plan_row(section: str, source_id: str, classification: str, strategy: str,
              destination_id: str | None, warnings: list[str] | None = None) -> dict:
    return {"section": section, "source_public_id": source_id, "classification": classification,
        "default_strategy": strategy, "destination_public_id": destination_id,
        "warnings": warnings or []}


def _build_plan(inspection, user: User, sections: list[str], expires_at: datetime) -> dict:
    package_ids = {section: {record["public_id"] for record in records}
        for section, records in inspection.records.items()}
    rows = []
    previously_applied = db.session.execute(
        db.select(PortableImportJob.id).where(
            PortableImportJob.user_id == user.id,
            PortableImportJob.artifact_hash == inspection.package_sha256,
            PortableImportJob.state.in_(("completed", "completed_with_skips")),
        ).limit(1)
    ).scalar_one_or_none()
    for section in DEPENDENCY_ORDER:
        if section in sections:
            if previously_applied is not None:
                rows.extend(
                    _plan_row(section, record["public_id"], "same_record", "skip_existing", record["public_id"])
                    for record in inspection.records[section]
                )
            else:
                rows.extend(_classify(section, record, user, package_ids) for record in inspection.records[section])
    summary = {key: 0 for key in ("new", "same_record", "compatible_update", "conflict", "foreign_collision", "duplicate_candidate", "broken_reference")}
    for row in rows: summary[row["classification"]] += 1
    return {"schema_version": "1.0", "plan_id": str(uuid.uuid4()), "revision": 1,
        "package_sha256": inspection.package_sha256, "selected_sections": sections,
        "summary": summary, "records": rows, "warnings": list(inspection.warnings),
        "expires_at": scrub_portable(expires_at)}


def inspect_import(user: User, storage: FileStorage, selected_sections=None) -> PortableImportJob:
    path, digest, size = _store_upload(storage, user.id); now = _now()
    try:
        inspection = _reader().inspect(path)
        sections = _selected(selected_sections, inspection.manifest["included_sections"])
        expires = now + timedelta(hours=current_app.config["PORTABILITY_TTL_HOURS"])
        artifact = PortableArtifact(user_id=user.id, kind="import",
            relative_path=path.relative_to(_root()).as_posix(), filename=f"import-{uuid.uuid4()}.htpack",
            media_type=MEDIA_TYPE, sha256=digest, size_bytes=size, created_at=now, expires_at=expires)
        db.session.add(artifact); db.session.flush()
        job = PortableImportJob(user_id=user.id, state="inspecting", format_version="1.0",
            sections_json=sections, counts_json={section: inspection.manifest["counts"][section] for section in sections},
            artifact_id=artifact.id, artifact_hash=digest, size_bytes=size,
            created_at=now, expires_at=expires)
        db.session.add(job); db.session.flush()
        job.inspection_json = inspection.report(); job.plan_json = _build_plan(inspection, user, sections, expires)
        job.state = "inspection_ready"; job.revision += 1; db.session.commit()
        return job
    except PortableArchiveError as error:
        path.unlink(missing_ok=True)
        job = PortableImportJob(user_id=user.id, state="invalid", sections_json=[], counts_json={},
            artifact_hash=digest, size_bytes=size, created_at=now,
            expires_at=now + timedelta(hours=current_app.config["PORTABILITY_TTL_HOURS"]), error_code=error.code)
        db.session.add(job); db.session.commit()
        raise PortabilityImportError(error.code, str(error), 400) from error
    except Exception:
        path.unlink(missing_ok=True); db.session.rollback(); raise


def list_imports(user_id: int) -> list[PortableImportJob]:
    expire_imports(user_id=user_id)
    return db.session.execute(db.select(PortableImportJob).where(PortableImportJob.user_id == user_id).order_by(PortableImportJob.created_at.desc())).scalars().all()


def get_import(user_id: int, public_id: str) -> PortableImportJob | None:
    try: public_id = str(uuid.UUID(public_id))
    except ValueError: return None
    job = db.session.execute(db.select(PortableImportJob).where(PortableImportJob.user_id == user_id,
        PortableImportJob.public_id == public_id)).scalar_one_or_none()
    if job and _expired(job.expires_at) and job.state not in {"completed", "completed_with_skips", "expired"}:
        _expire(job); db.session.commit()
    return job


def _date(value) -> date:
    try: return date.fromisoformat(str(value))
    except ValueError as error: raise PortabilityImportError("invalid_date", "El paquete contiene una fecha inválida.") from error


def _datetime(value, required=False):
    if value in (None, ""):
        if required: raise PortabilityImportError("invalid_datetime", "Falta una fecha requerida.")
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except ValueError as error: raise PortabilityImportError("invalid_datetime", "El paquete contiene una fecha inválida.") from error


def _decimal(value):
    if value in (None, ""): return None
    try: return Decimal(str(value))
    except Exception as error: raise PortabilityImportError("invalid_number", "El paquete contiene un decimal inválido.") from error


def _destination_uuid(model, source_id: str, user_id: int, force_new: bool) -> tuple[str, str | None]:
    row = db.session.execute(db.select(model).where(model.public_id == source_id)).scalar_one_or_none()
    if force_new or (row is not None and row.user_id != user_id):
        return str(uuid.uuid4()), "foreign_collision" if row is not None and row.user_id != user_id else "import_as_new"
    return source_id, None


def _resolve(model, user_id: int, source_id: str, maps: dict[tuple[str, str], str], section: str):
    destination = maps.get((section, source_id), source_id)
    return db.session.execute(db.select(model).where(model.user_id == user_id, model.public_id == destination)).scalar_one_or_none()


def _add_mapping(job, section, source_id, destination_id, collision, maps):
    maps[(section, source_id)] = destination_id
    existing = next((item for item in job.mappings if item.section == section and item.source_public_id == source_id), None)
    if existing is None:
        job.mappings.append(PortableImportMapping(user_id=job.user_id, section=section,
            source_public_id=source_id, destination_public_id=destination_id, collision_type=collision))


def _apply_record(job, section, record, strategy, maps, created_paths):
    data = record["data"]; source_id = record["public_id"]; user_id = job.user_id
    if strategy in {"skip_existing", "use_destination"}:
        entry = next(item for item in job.plan_json["records"] if item["section"] == section and item["source_public_id"] == source_id)
        destination = entry.get("destination_public_id") or source_id
        _add_mapping(job, section, source_id, destination, entry["classification"], maps)
        return "skipped"
    if strategy == "require_manual_resolution":
        raise PortabilityImportError("unresolved_conflict", "El plan contiene conflictos sin resolver.", 409)
    if section == "profile":
        user = db.session.get(User, user_id)
        if strategy == "update_when_identical_lineage":
            user.display_name = data.get("display_name"); user.timezone = data.get("timezone", user.timezone)
        _add_mapping(job, section, source_id, source_id, None, maps); return "updated"
    if section == "settings":
        user = db.session.get(User, user_id)
        if data.get("preferred_load_unit") in {"kg", "lb"}: user.preferred_load_unit = data["preferred_load_unit"]
        if data.get("timezone") is not None: user.timezone = str(data["timezone"])[:64]
        _add_mapping(job, section, source_id, source_id, None, maps); return "updated"
    if section == "external_sources":
        _add_mapping(job, section, source_id, source_id, None, maps); return "skipped"
    force_new = strategy == "import_as_new" and next(item for item in job.plan_json["records"] if item["section"] == section and item["source_public_id"] == source_id)["classification"] not in {"new"}
    if section == "custom_foods":
        destination, collision = _destination_uuid(FoodProduct, source_id, user_id, force_new)
        name = str(data["name"])[:200]
        if force_new and db.session.execute(db.select(FoodProduct).where(FoodProduct.user_id == user_id, FoodProduct.name == name, FoodProduct.brand == data.get("brand"))).scalar_one_or_none():
            name = f"{name[:170]} (importado {source_id[:8]})"
        row = FoodProduct(public_id=destination, user_id=user_id, name=name, brand=data.get("brand"),
            serving_size_g=_decimal(data.get("serving_size_g")), serving_label=data.get("serving_label"),
            source="portable_import", notes=data.get("notes"), is_active=bool(data.get("is_active", True)), revision=max(1, int(record.get("revision", 1))))
        for field in ("calories_per_100g", "protein_g_per_100g", "fat_g_per_100g", "carbs_g_per_100g", "net_carbs_g_per_100g", "fiber_g_per_100g", "sodium_mg_per_100g"):
            setattr(row, field, _decimal(data.get(field)))
        db.session.add(row); _add_mapping(job, section, source_id, destination, collision, maps); return "inserted"
    if section == "exercises":
        destination, collision = _destination_uuid(Exercise, source_id, user_id, force_new)
        name = str(data["canonical_name"])[:200]
        normalized = normalize_exercise_name(name)
        if db.session.execute(db.select(Exercise).where(Exercise.user_id == user_id, Exercise.normalized_name == normalized)).scalar_one_or_none():
            name = f"{name[:170]} (importado {source_id[:8]})"; normalized = normalize_exercise_name(name)
        row = Exercise(public_id=destination, user_id=user_id, canonical_name=name, normalized_name=normalized); db.session.add(row); db.session.flush()
        for alias in data.get("aliases", []):
            alias_name = str(alias)[:200]; alias_normalized = normalize_exercise_name(alias_name)
            if not db.session.execute(db.select(Exercise).where(Exercise.user_id == user_id, Exercise.normalized_name == alias_normalized)).scalar_one_or_none():
                if not db.session.execute(db.select(ExerciseAlias).where(ExerciseAlias.user_id == user_id, ExerciseAlias.normalized_name == alias_normalized)).scalar_one_or_none():
                    db.session.add(ExerciseAlias(user_id=user_id, exercise_id=row.id, alias_name=alias_name, normalized_name=alias_normalized))
        profile = data.get("load_profile")
        if isinstance(profile, dict):
            profile_id, _ = _destination_uuid(ExerciseLoadProfile, profile.get("public_id", str(uuid.uuid4())), user_id, False)
            db.session.add(ExerciseLoadProfile(public_id=profile_id, user_id=user_id, exercise_id=row.id,
                load_mode=profile.get("load_mode", "direct_total"), preferred_unit=profile.get("preferred_unit", "kg"),
                configuration_json=profile.get("configuration") or {}, quick_increments_json=profile.get("quick_increments") or [],
                revision=max(1, int(profile.get("revision", 1)))))
        _add_mapping(job, section, source_id, destination, collision, maps); return "inserted"
    if section == "plans":
        destination, collision = _destination_uuid(TrainingPlan, source_id, user_id, force_new)
        row = TrainingPlan(public_id=destination, user_id=user_id, name=str(data["name"])[:200],
            description=data.get("description"), status=data.get("status", "active"),
            active_version_number=max(1, int(data.get("active_version_number", 1))),
            archived_at=_datetime(data.get("archived_at")), revision=max(1, int(record.get("revision", 1))))
        db.session.add(row); db.session.flush(); _add_mapping(job, section, source_id, destination, collision, maps)
        for version in data.get("versions", []):
            version_source = str(uuid.UUID(version["public_id"])); version_dest, version_collision = _destination_uuid(TrainingPlanVersion, version_source, user_id, False)
            content = version.get("content") or {}
            db.session.add(TrainingPlanVersion(public_id=version_dest, user_id=user_id, training_plan_id=row.id,
                version_number=max(1, int(version["version_number"])), schema_version=str(version.get("schema_version", "1.0"))[:20],
                sha256=sha256_bytes(canonical_json_bytes(content)), content=content,
                change_reason=version.get("change_reason"), created_at=_datetime(version.get("created_at")) or _now()))
            _add_mapping(job, "plan_versions", version_source, version_dest, version_collision, maps)
        return "inserted"
    if section == "workouts":
        plan = _resolve(TrainingPlan, user_id, data["plan_public_id"], maps, "plans")
        if plan is None: raise PortabilityImportError("broken_reference", "No se pudo remapear el plan de un workout.", 409)
        destination, collision = _destination_uuid(TrainingPlanWorkout, source_id, user_id, force_new)
        position = max(1, int(data["position"])); existing = db.session.execute(db.select(TrainingPlanWorkout).where(TrainingPlanWorkout.training_plan_id == plan.id, TrainingPlanWorkout.position == position)).scalar_one_or_none()
        if existing: position = max([item.position for item in plan.workouts] + [0]) + 1
        db.session.add(TrainingPlanWorkout(public_id=destination, user_id=user_id, training_plan_id=plan.id,
            name=str(data["name"])[:200], notes=data.get("notes"), position=position,
            exercises_json=data.get("exercises") or [], revision=max(1, int(record.get("revision", 1)))))
        _add_mapping(job, section, source_id, destination, collision, maps); return "inserted"
    if section == "schedules":
        plan = _resolve(TrainingPlan, user_id, data["plan_public_id"], maps, "plans")
        version = _resolve(TrainingPlanVersion, user_id, data["plan_version_public_id"], maps, "plan_versions")
        if plan is None or version is None: raise PortabilityImportError("broken_reference", "No se pudo remapear una programación.", 409)
        destination, collision = _destination_uuid(PlannedWorkout, source_id, user_id, force_new)
        db.session.add(PlannedWorkout(public_id=destination, user_id=user_id, training_plan_id=plan.id,
            training_plan_version_id=version.id, scheduled_for_date=_date(data["scheduled_for_date"]),
            timezone=str(data.get("timezone") or "UTC")[:64], status=data.get("status", "planned"),
            title_snapshot=str(data.get("title") or plan.name)[:200], payload_snapshot_json=data.get("payload_snapshot") or {},
            source_version=max(1, int(data.get("source_version", version.version_number))), revision=max(1, int(record.get("revision", 1))),
            completed_at=_datetime(data.get("completed_at")), cancelled_at=_datetime(data.get("cancelled_at")), deleted_at=_datetime(data.get("deleted_at"))))
        _add_mapping(job, section, source_id, destination, collision, maps); return "inserted"
    if section == "sessions":
        plan = _resolve(TrainingPlan, user_id, data["plan_public_id"], maps, "plans")
        version = _resolve(TrainingPlanVersion, user_id, data["plan_version_public_id"], maps, "plan_versions")
        schedule = _resolve(PlannedWorkout, user_id, data.get("schedule_public_id"), maps, "schedules") if data.get("schedule_public_id") else None
        if plan is None or version is None: raise PortabilityImportError("broken_reference", "No se pudo remapear una sesión.", 409)
        destination, collision = _destination_uuid(TrainingSession, source_id, user_id, force_new)
        db.session.add(TrainingSession(public_id=destination, user_id=user_id, training_plan_id=plan.id,
            training_plan_version_id=version.id, planned_workout_id=schedule.id if schedule else None,
            timezone=data.get("timezone"), started_at=_datetime(data.get("started_at")), completed_at=_datetime(data.get("completed_at")),
            performed_at=_datetime(data.get("performed_at"), required=True), planned_week_number=max(1, int(data.get("planned_week_number", 1))),
            planned_day_number=min(7, max(1, int(data.get("planned_day_number", 1)))), duration_seconds=data.get("duration_seconds"),
            average_heart_rate_bpm=data.get("average_heart_rate_bpm"), calories_burned=_decimal(data.get("calories_burned")),
            notes=data.get("notes"), revision=max(1, int(record.get("revision", 1)))))
        _add_mapping(job, section, source_id, destination, collision, maps); return "inserted"
    if section == "session_exercises":
        session = _resolve(TrainingSession, user_id, data["session_public_id"], maps, "sessions")
        if session is None: raise PortabilityImportError("broken_reference", "No se pudo remapear un ejercicio realizado.", 409)
        destination, collision = _destination_uuid(TrainingSessionExercise, source_id, user_id, force_new)
        db.session.add(TrainingSessionExercise(public_id=destination, user_id=user_id, training_session_id=session.id,
            exercise_order=max(1, int(data["exercise_order"])), planned_exercise_order=max(1, int(data["planned_exercise_order"])),
            name=str(data["name"])[:200], notes=data.get("notes")))
        _add_mapping(job, section, source_id, destination, collision, maps); return "inserted"
    if section == "sets":
        parent = _resolve(TrainingSessionExercise, user_id, data["session_exercise_public_id"], maps, "session_exercises")
        if parent is None: raise PortabilityImportError("broken_reference", "No se pudo remapear una serie.", 409)
        existing = db.session.execute(db.select(TrainingSet).where(TrainingSet.training_session_exercise_id == parent.id,
            TrainingSet.set_number == int(data["set_number"]))).scalar_one_or_none()
        if existing:
            _add_mapping(job, section, source_id, source_id, "duplicate_candidate", maps); return "skipped"
        db.session.add(TrainingSet(user_id=user_id, training_session_exercise_id=parent.id,
            set_number=max(1, int(data["set_number"])), planned_set_number=max(1, int(data["planned_set_number"])),
            weight_kg=_decimal(data["weight_kg"]), load_details_json=data.get("load_details"), reps=max(1, int(data["reps"])),
            rir=_decimal(data.get("rir")), rpe=_decimal(data.get("rpe")), rest_seconds=data.get("rest_seconds"), notes=data.get("notes")))
        _add_mapping(job, section, source_id, source_id, None, maps); return "inserted"
    if section == "body_stats":
        destination, collision = _destination_uuid(WeighIn, source_id, user_id, force_new)
        source = "portable_import" if force_new else data.get("source", "portable_import")
        db.session.add(WeighIn(public_id=destination, user_id=user_id, recorded_at=_datetime(data["recorded_at"], required=True),
            weight_kg=_decimal(data["weight_kg"]), body_fat_percentage=_decimal(data.get("body_fat_percent")),
            muscle_mass_kg=_decimal(data.get("muscle_mass_kg")), water_percentage=_decimal(data.get("water_percent")),
            visceral_fat=_decimal(data.get("visceral_fat")), bmr_kcal=_decimal(data.get("bmr_kcal")), bmi=_decimal(data.get("bmi")),
            source=source, notes=data.get("notes"), revision=max(1, int(record.get("revision", 1)))))
        _add_mapping(job, section, source_id, destination, collision, maps); return "inserted"
    if section == "nutrition_entries":
        existing = _natural_existing(section, record, user_id)
        if existing: _add_mapping(job, section, source_id, source_id, "duplicate_candidate", maps); return "skipped"
        totals = data.get("totals") or {}
        day = DailyNutrition(user_id=user_id, date=_date(data["date"]), source="portable_import", notes=data.get("notes"))
        for field in ("calories", "protein_g", "fat_g", "net_carbs_g", "total_carbs_g", "fiber_g", "sugar_g", "sodium_mg"):
            setattr(day, field, _decimal(totals.get(field)))
        db.session.add(day); db.session.flush()
        for meal_data in data.get("meals", []):
            meal = NutritionMeal(user_id=user_id, daily_nutrition_id=day.id, meal_type=meal_data["meal_type"],
                name=meal_data.get("name"), sort_order=max(1, int(meal_data["sort_order"])))
            db.session.add(meal); db.session.flush()
            for item_data in meal_data.get("items", []):
                item_id, _ = _destination_uuid(NutritionItem, item_data["public_id"], user_id, False)
                food = _resolve(FoodProduct, user_id, item_data.get("food_public_id"), maps, "custom_foods") if item_data.get("food_public_id") else None
                item = NutritionItem(public_id=item_id, user_id=user_id, nutrition_meal_id=meal.id, name=item_data["name"],
                    quantity=_decimal(item_data.get("quantity")), unit=item_data.get("unit"), sort_order=max(1, int(item_data["sort_order"])),
                    notes=item_data.get("notes"), source="portable_import", revision=max(1, int(item_data.get("revision", 1))),
                    food_product_id=food.id if food else None)
                for field in ("calories", "protein_g", "fat_g", "net_carbs_g", "total_carbs_g", "fiber_g", "sugar_g", "sodium_mg"):
                    setattr(item, field, _decimal(item_data.get(field)))
                db.session.add(item)
        _add_mapping(job, section, source_id, source_id, None, maps); return "inserted"
    if section == "steps":
        destination, collision = _destination_uuid(DailyEnergy, source_id, user_id, force_new)
        source = "portable_import" if force_new else data.get("source", "portable_import")
        db.session.add(DailyEnergy(public_id=destination, user_id=user_id, date=_date(data["date"]), steps=int(data["steps"]),
            distance_meters=_decimal(data.get("distance_meters")), source=source, notes=data.get("notes"),
            revision=max(1, int(record.get("revision", 1)))))
        _add_mapping(job, section, source_id, destination, collision, maps); return "inserted"
    if section == "attachments":
        existing = _natural_existing(section, record, user_id)
        if existing: _add_mapping(job, section, source_id, source_id, "same_record", maps); return "skipped"
        package_path = _artifact_path(job.artifact); content = _reader().read_member(package_path, data["archive_path"])
        if sha256_bytes(content) != data["sha256"] or len(content) != int(data["size_bytes"]):
            raise PortabilityImportError("checksum_mismatch", "El attachment cambió después de la inspección.", 409)
        directory = Path(current_app.config["UPLOAD_ROOT"]) / f"user_{user_id}"; directory.mkdir(parents=True, exist_ok=True)
        final = directory / data["sha256"]
        if not final.exists():
            partial = directory / f".{uuid.uuid4().hex}.portability"; partial.write_bytes(content); partial.replace(final); created_paths.append(final)
        relative = (Path("uploads") / "raw" / f"user_{user_id}" / data["sha256"]).as_posix()
        db.session.add(UploadedFile(user_id=user_id, original_filename=safe_filename(data.get("filename")), stored_filename=data["sha256"],
            storage_path=relative, source_type="portable_import", detected_type="unknown", import_status="imported",
            sha256=data["sha256"], size_bytes=int(data["size_bytes"]), mime_type=data.get("media_type")))
        _add_mapping(job, section, source_id, source_id, None, maps); return "inserted"
    raise PortabilityImportError("unsupported_section", "La sección no puede importarse en esta versión.")


def apply_import(job: PortableImportJob, user_id: int, payload: dict, raw_idempotency_key: str) -> dict:
    if job.user_id != user_id: raise PortabilityImportError("not_found", "Importación no encontrada.", 404)
    if not isinstance(raw_idempotency_key, str) or not raw_idempotency_key.strip() or len(raw_idempotency_key) > 200:
        raise PortabilityImportError("idempotency_required", "Se requiere Idempotency-Key.")
    key_hash = hashlib.sha256(raw_idempotency_key.strip().encode()).hexdigest()
    job = db.session.execute(db.select(PortableImportJob).where(
        PortableImportJob.id == job.id,
        PortableImportJob.user_id == user_id,
    ).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if job is None:
        raise PortabilityImportError("not_found", "Importacion no encontrada.", 404)
    if payload.get("confirmed") is not True:
        raise PortabilityImportError("confirmation_required", "La importación requiere confirmación explícita.")
    if job.state in {"completed", "completed_with_skips"}:
        if job.apply_idempotency_key_hash == key_hash: return job.result_json
        raise PortabilityImportError("already_applied", "Este plan ya fue aplicado.", 409)
    if job.state not in {"inspection_ready", "awaiting_confirmation", "rolled_back", "failed"}:
        raise PortabilityImportError("invalid_state", "La importación no está lista para aplicar.", 409)
    if _expired(job.expires_at):
        _expire(job); db.session.commit(); raise PortabilityImportError("plan_expired", "El plan de importación venció.", 410)
    try: plan_revision = int(payload.get("plan_revision"))
    except (TypeError, ValueError) as error: raise PortabilityImportError("plan_revision_required", "Se requiere la revisión del plan.") from error
    if plan_revision != int(job.plan_json["revision"]):
        raise PortabilityImportError("stale_plan", "El plan cambió y debe revisarse de nuevo.", 409)
    decisions = payload.get("decisions", [])
    if not isinstance(decisions, list): raise PortabilityImportError("invalid_decisions", "Las decisiones no son válidas.")
    overrides = {}
    plan_keys = {(row["section"], row["source_public_id"]) for row in job.plan_json["records"]}
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != {"section", "source_public_id", "strategy"}:
            raise PortabilityImportError("invalid_decisions", "Una decisión no tiene el contrato esperado.")
        key = (decision["section"], decision["source_public_id"]); strategy = decision["strategy"]
        if key not in plan_keys or strategy not in STRATEGIES: raise PortabilityImportError("invalid_decisions", "Una decisión no pertenece al plan.")
        overrides[key] = strategy
    strategies = {(row["section"], row["source_public_id"]): overrides.get((row["section"], row["source_public_id"]), row["default_strategy"]) for row in job.plan_json["records"]}
    if "require_manual_resolution" in strategies.values():
        raise PortabilityImportError("unresolved_conflict", "Resuelve o descarta todos los conflictos antes de importar.", 409)
    normalized = {"plan_revision": plan_revision, "decisions": sorted(decisions, key=lambda item: (item["section"], item["source_public_id"])), "confirmed": True}
    request_hash = hashlib.sha256(canonical_json_bytes(normalized)).hexdigest()
    path = _artifact_path(job.artifact); digest, size = sha256_path(path, maximum=current_app.config["PORTABILITY_MAX_COMPRESSED_BYTES"])
    if digest != job.artifact_hash or size != job.size_bytes: raise PortabilityImportError("package_changed", "El paquete cambió tras la inspección.", 409)
    inspection = _reader().inspect(path)
    if inspection.package_sha256 != job.plan_json["package_sha256"]: raise PortabilityImportError("package_changed", "El paquete ya no coincide con el plan.", 409)
    created_paths = []; maps = {(item.section, item.source_public_id): item.destination_public_id for item in job.mappings}
    counts = {"inserted": 0, "updated": 0, "skipped": 0, "remapped": 0}; sections_result = {}
    try:
        job.state = "importing"; job.apply_idempotency_key_hash = key_hash; job.apply_request_hash = request_hash; job.revision += 1
        for existing in list(job.decisions): db.session.delete(existing)
        for (section, source_id), strategy in strategies.items():
            db.session.add(PortableImportDecision(import_job_id=job.id, user_id=user_id, section=section,
                source_public_id=source_id, strategy=strategy, revision=plan_revision))
        for section in DEPENDENCY_ORDER:
            if section not in job.sections_json: continue
            section_counts = {"inserted": 0, "updated": 0, "skipped": 0}
            for record in inspection.records[section]:
                action = _apply_record(job, section, record, strategies[(section, record["public_id"])], maps, created_paths)
                counts[action] += 1; section_counts[action] += 1
            sections_result[section] = section_counts
        db.session.flush()
        counts["remapped"] = sum(1 for item in job.mappings if item.source_public_id != item.destination_public_id)
        state = "completed_with_skips" if counts["skipped"] else "completed"; completed = _now()
        result = {"schema_version": "1.0", "import_id": job.public_id, "state": state,
            "package_sha256": inspection.package_sha256, "counts": counts, "sections": sections_result,
            "warnings": list(inspection.warnings), "completed_at": scrub_portable(completed)}
        job.result_json = result; job.state = state; job.completed_at = completed; job.revision += 1
        db.session.commit(); return result
    except Exception as error:
        db.session.rollback()
        for path in created_paths: path.unlink(missing_ok=True)
        failed = db.session.execute(db.select(PortableImportJob).where(PortableImportJob.id == job.id,
            PortableImportJob.user_id == user_id)).scalar_one()
        failed.state = "rolled_back"; failed.error_code = getattr(error, "code", "import_failed"); failed.revision += 1
        db.session.commit()
        if isinstance(error, PortabilityImportError): raise
        raise


def delete_import(job: PortableImportJob, user_id: int) -> None:
    if job.user_id != user_id: raise PortabilityImportError("not_found", "Importación no encontrada.", 404)
    if job.state == "importing": raise PortabilityImportError("invalid_state", "No se puede borrar una importación en curso.", 409)
    if job.artifact:
        path = _artifact_path(job.artifact); path.unlink(missing_ok=True); db.session.delete(job.artifact)
    db.session.delete(job); db.session.commit()


def _expire(job: PortableImportJob) -> None:
    if job.artifact:
        try: path = _artifact_path(job.artifact)
        except PortabilityImportError: path = None
        if path is not None: path.unlink(missing_ok=True)
        db.session.delete(job.artifact); job.artifact = None; job.artifact_id = None
    job.state = "expired"; job.revision += 1


def expire_imports(user_id: int | None = None) -> int:
    statement = db.select(PortableImportJob).where(PortableImportJob.expires_at <= _now(),
        PortableImportJob.state.notin_(("completed", "completed_with_skips", "expired")))
    if user_id is not None: statement = statement.where(PortableImportJob.user_id == user_id)
    rows = db.session.execute(statement).scalars().all()
    for row in rows: _expire(row)
    if rows: db.session.commit()
    return len(rows)


def import_job_document(job: PortableImportJob) -> dict:
    return {"import_id": job.public_id, "state": job.state, "format_version": job.format_version,
        "sections": job.sections_json or [], "counts": job.counts_json or {}, "size_bytes": job.size_bytes,
        "sha256": job.artifact_hash, "inspection": job.inspection_json, "plan": job.plan_json,
        "result": job.result_json, "created_at": scrub_portable(job.created_at),
        "expires_at": scrub_portable(job.expires_at), "completed_at": scrub_portable(job.completed_at),
        "revision": job.revision, "error_code": job.error_code}
