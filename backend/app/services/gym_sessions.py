"""Incremental confirmed-set capture using TrainingSession/TrainingSet."""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from flask import current_app
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import TrainingSession, TrainingSessionExercise, TrainingSet, TrainingPlanVersion
from app.services.gym_programs import GymError, catalog, lock_user, owned_plan
from app.services.exercise_identity import normalize_exercise_name
from app.services.training_plans import get_active_version
from app.services.workout_loads import calculate_workout_load, from_kg
from app.services.validation import validate_json_document


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def owned_session(user_id, public_id, lock=False):
    query = db.select(TrainingSession).where(TrainingSession.user_id == user_id, TrainingSession.public_id == public_id, TrainingSession.deleted_at.is_(None))
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    record = db.session.execute(query).scalar_one_or_none()
    if record is None:
        raise GymError("Sesión no encontrada.", 404)
    return record


def session_day(record, user_id):
    version = db.session.execute(db.select(TrainingPlanVersion).where(TrainingPlanVersion.id == record.training_plan_version_id, TrainingPlanVersion.user_id == user_id, TrainingPlanVersion.training_plan_id == record.training_plan_id)).scalar_one_or_none()
    if version is None:
        raise GymError("Versión no encontrada.", 404)
    for week in version.content["data"]["weeks"]:
        for day in week["days"]:
            if (week["week_number"], day["day_number"]) == (record.planned_week_number, record.planned_day_number):
                return day
    raise GymError("Día histórico no encontrado.", 404)


def start_session(user_id, plan_public_id, version_public_id, week_number, day_number, submission_id):
    user = lock_user(user_id)
    try:
        submission_id = str(uuid.UUID(submission_id))
    except (ValueError, TypeError, AttributeError) as error:
        raise GymError("Identificador de inicio inválido.") from error
    plan = owned_plan(user_id, plan_public_id, lock=True)
    version = get_active_version(plan, user_id)
    fingerprint = hashlib.sha256(json.dumps([plan_public_id, version_public_id, week_number, day_number]).encode()).hexdigest()
    duplicate = db.session.execute(db.select(TrainingSession).where(TrainingSession.user_id == user_id, TrainingSession.client_submission_id == submission_id)).scalar_one_or_none()
    if duplicate:
        if duplicate.client_payload_sha256 != fingerprint or duplicate.deleted_at:
            raise GymError("El inicio ya se usó para otra sesión.", 409)
        return duplicate
    if version.public_id != version_public_id:
        raise GymError("La rutina cambió; actualiza la pantalla.", 409)
    day = next((day for week in version.content["data"]["weeks"] if week["week_number"] == week_number for day in week["days"] if day["day_number"] == day_number), None)
    if day is None or not day["exercises"]:
        raise GymError("Día no disponible.", 404)
    ongoing = db.session.execute(db.select(TrainingSession).where(TrainingSession.user_id == user_id, TrainingSession.training_plan_version_id == version.id, TrainingSession.planned_week_number == week_number, TrainingSession.planned_day_number == day_number, TrainingSession.status == "in_progress", TrainingSession.deleted_at.is_(None))).scalar_one_or_none()
    if ongoing:
        return ongoing
    now = datetime.now(timezone.utc)
    record = TrainingSession(user_id=user_id, training_plan_id=plan.id, training_plan_version_id=version.id, planned_week_number=week_number, planned_day_number=day_number, status="in_progress", started_at=now, performed_at=now, timezone=user.timezone or current_app.config["APP_TIMEZONE"], client_submission_id=submission_id, client_payload_sha256=fingerprint)
    db.session.add(record)
    db.session.flush()
    return record


def _performance(training_set, unit):
    details = training_set.load_details_json or {}
    mode = details.get("load_mode", "direct_total")
    return {"load": format(from_kg(training_set.weight_kg, unit).quantize(Decimal("0.01")), "f") if mode == "direct_total" else None, "unit": unit, "reps": training_set.reps, "rir": str(training_set.rir) if training_set.rir is not None else None, "rpe": str(training_set.rpe) if training_set.rpe is not None else None, "mode": mode}


def workout_context(record, user_id, unit):
    """Batch prefetch by exercise names; never query for individual rendered sets."""
    day = session_day(record, user_id)
    identities = catalog(user_id)
    name_key = {name: item.public_id for item in identities for name in [item.normalized_name, *(alias.normalized_name for alias in item.aliases)]}
    def key(name):
        normalized = normalize_exercise_name(name)
        return name_key.get(normalized, normalized)
    wanted = {key(exercise["name"]) for exercise in day["exercises"]}
    # Restrict in SQL to known canonical/alias spellings, including legacy names.
    spellings = {exercise["name"] for exercise in day["exercises"]}
    for item in identities:
        if item.public_id in wanted:
            spellings.update([item.canonical_name, *(alias.alias_name for alias in item.aliases)])
    occurrences = db.session.execute(db.select(TrainingSessionExercise).join(TrainingSession).where(
        TrainingSessionExercise.user_id == user_id, TrainingSession.user_id == user_id,
        TrainingSession.id != record.id, TrainingSession.status.in_(["completed", "abandoned"]),
        TrainingSession.deleted_at.is_(None), TrainingSession.performed_at <= record.performed_at,
        db.func.lower(TrainingSessionExercise.name).in_([name.lower() for name in spellings]),
    ).options(selectinload(TrainingSessionExercise.sets), selectinload(TrainingSessionExercise.training_session)).order_by(
        (TrainingSession.training_plan_id == record.training_plan_id).desc(), TrainingSession.performed_at.desc(), TrainingSessionExercise.id.desc()
    ).limit(2000)).scalars().all()
    previous = {}
    for occurrence in occurrences:
        identity = key(occurrence.name)
        comparable = [item for item in occurrence.sets if item.user_id == user_id and (item.load_details_json or {}).get("load_mode", "direct_total") == "direct_total"]
        if comparable and identity not in previous:
            previous[identity] = {"date": utc(occurrence.training_session.performed_at).isoformat(), "sets": [_performance(item, unit) for item in comparable]}
    current = db.session.execute(db.select(TrainingSessionExercise).where(TrainingSessionExercise.user_id == user_id, TrainingSessionExercise.training_session_id == record.id).options(selectinload(TrainingSessionExercise.sets))).scalars().all()
    completed = {(exercise.planned_exercise_order, item.planned_set_number): item for exercise in current for item in exercise.sets if item.user_id == user_id}
    exercises = []
    for exercise in day["exercises"]:
        last = previous.get(key(exercise["name"]))
        sets = []
        for index, target in enumerate(exercise["sets"]):
            recent = last["sets"][index] if last and index < len(last["sets"]) else {}
            target_load = target.get("weight_kg")
            if target_load is not None:
                target_load = format(from_kg(Decimal(str(target_load)), unit).quantize(Decimal("0.01")), "f")
            elif target.get("load_value") is not None and target.get("load_unit") in {"kg", "lb"}:
                value = Decimal(str(target["load_value"]))
                if target["load_unit"] == "lb":
                    value *= Decimal("0.45359237")
                target_load = format(from_kg(value, unit).quantize(Decimal("0.01")), "f")
            actual = completed.get((exercise["exercise_order"], target["set_number"]))
            sets.append({"number": target["set_number"], "target": target, "previous": recent,
                "suggestion": {"load": recent.get("load") if recent.get("load") is not None else target_load,
                    "reps": target.get("reps", recent.get("reps", target.get("reps_min"))), "rir": target.get("rir"), "rpe": target.get("rpe")},
                "actual": _performance(actual, unit) if actual else None})
        exercises.append({"name": exercise["name"], "order": exercise["exercise_order"], "notes": exercise.get("notes"), "identity": name_key.get(normalize_exercise_name(exercise["name"])), "previous": last, "sets": sets})
    return {"day": day["name"], "exercises": exercises, "completed_sets": len(completed), "total_sets": sum(len(item["sets"]) for item in exercises), "unit": unit}


def complete_set(user_id, public_id, exercise_order, set_number, values):
    record = owned_session(user_id, public_id, lock=True)
    day = session_day(record, user_id)
    prescription = next((item for item in day["exercises"] if item["exercise_order"] == exercise_order), None)
    target = next((item for item in prescription["sets"] if item["set_number"] == set_number), None) if prescription else None
    if target is None:
        raise GymError("Serie no encontrada.", 404)
    if target.get("load_mode") in {"bodyweight", "bodyweight_plus", "assistance", "duration_distance"} or not any(field in target for field in ("reps", "reps_min")):
        raise GymError("Esta modalidad requiere la captura avanzada para conservar sus componentes reales.")
    if set(values) - {"load", "unit", "reps", "rir", "rpe"}:
        raise GymError("Campos de serie desconocidos.")
    try:
        load = calculate_workout_load("direct_total", values.get("unit"), {"direct_total": values.get("load")})
        reps = int(str(values.get("reps")))
        set_data = {"set_number": set_number, "planned_set_number": set_number, "weight_kg": float(load.weight_kg), "reps": reps, "load_details": load.details}
        for field in ("rir", "rpe"):
            if values.get(field) not in (None, ""):
                number = Decimal(str(values[field]))
                if not number.is_finite() or number * 10 != (number * 10).to_integral_value():
                    raise ValueError()
                set_data[field] = float(number)
    except (ValueError, TypeError, ArithmeticError) as error:
        raise GymError("Revisa carga, unidad, repeticiones y esfuerzo.") from error
    document = {"schema_version": "1.0", "record_type": "completed_workout", "user_id": user_id, "source_type": "manual_generated", "data": {
        "training_plan_id": record.training_plan_id, "training_plan_version_id": record.training_plan_version_id,
        "performed_at": utc(record.performed_at).isoformat(), "planned_week_number": record.planned_week_number,
        "planned_day_number": record.planned_day_number, "exercises": [{"exercise_order": exercise_order,
        "planned_exercise_order": exercise_order, "name": prescription["name"], "sets": [set_data]}]}}
    validate_json_document(document, "completed_workout")
    exercise = db.session.execute(db.select(TrainingSessionExercise).where(TrainingSessionExercise.user_id == user_id, TrainingSessionExercise.training_session_id == record.id, TrainingSessionExercise.exercise_order == exercise_order)).scalar_one_or_none()
    existing = db.session.execute(db.select(TrainingSet).where(TrainingSet.user_id == user_id, TrainingSet.training_session_exercise_id == exercise.id, TrainingSet.set_number == set_number)).scalar_one_or_none() if exercise else None
    if existing:
        same = existing.weight_kg == load.weight_kg and existing.load_details_json == load.details and existing.reps == reps and all(getattr(existing, field) == (Decimal(str(set_data[field])) if field in set_data else None) for field in ("rir", "rpe"))
        if same:
            return record, existing, True
        raise GymError("Esta serie ya está guardada con otros valores; recarga antes de editar.", 409)
    if record.status != "in_progress":
        raise GymError("La sesión ya está cerrada.", 409)
    if exercise is None:
        exercise = TrainingSessionExercise(user_id=user_id, training_session_id=record.id, exercise_order=exercise_order, planned_exercise_order=exercise_order, name=prescription["name"])
        db.session.add(exercise)
        db.session.flush()
    training_set = TrainingSet(user_id=user_id, training_session_exercise_id=exercise.id, set_number=set_number, planned_set_number=set_number, weight_kg=load.weight_kg, load_details_json=load.details, reps=reps, rir=set_data.get("rir"), rpe=set_data.get("rpe"), rest_seconds=target.get("rest_seconds"))
    db.session.add(training_set)
    record.revision += 1
    db.session.flush()
    return record, training_set, False


def finish_session(user_id, public_id, status):
    if status not in {"completed", "abandoned"}:
        raise GymError("Estado inválido.")
    record = owned_session(user_id, public_id, lock=True)
    if record.status != "in_progress":
        if record.status == status:
            return record
        raise GymError("La sesión ya está cerrada.", 409)
    count = db.session.execute(db.select(db.func.count(TrainingSet.id)).join(TrainingSessionExercise).where(TrainingSet.user_id == user_id, TrainingSessionExercise.user_id == user_id, TrainingSessionExercise.training_session_id == record.id)).scalar_one()
    if status == "completed" and not count:
        raise GymError("Completa al menos una serie o cierra como incompleta.")
    record.status = status
    record.completed_at = datetime.now(timezone.utc)
    record.duration_seconds = min(604800, max(1, int((record.completed_at - utc(record.started_at or record.performed_at)).total_seconds())))
    record.revision += 1
    if count and status == "completed":
        from app.services.mobile_sync import record_sync_change, serialize_completed_workout
        record_sync_change(user_id=user_id, entity_type="completed_workout", entity_public_id=record.public_id, operation="upsert", revision=record.revision, payload=serialize_completed_workout(record), device_id=None)
    return record
