"""Neutral reads and reserved Coach action contracts; no AI provider dependency."""
from app.extensions import db
from app.models import TrainingPlan
from app.services.gym_programs import GymError, owned_plan
from app.services.gym_sessions import owned_session, session_day
from app.services.training_plans import get_active_version

READ_MODELS = {
    "training.program": "get_training_program",
    "training.program_day": "get_training_program",
    "training.session": "get_training_session",
    "training.exercise_progress": "get_exercise_progress",
}
FUTURE_ACTIONS = {
    "training.program.adjust": ("program_id", "base_revision", "days"),
    "training.exercise.replace": ("program_id", "base_revision", "exercise_id", "replacement_exercise_id"),
    "training.prescription.update": ("program_id", "base_revision", "exercise_id", "prescription"),
    "training.load.propose": ("program_id", "base_revision", "exercise_id", "load_value", "load_unit"),
}


def read_program(user_id, public_id=None, week=None, day=None):
    if public_id:
        plan = owned_plan(user_id, public_id)
    else:
        plan = db.session.execute(db.select(TrainingPlan).where(TrainingPlan.deleted_at.is_(None), TrainingPlan.user_id == user_id, TrainingPlan.gym_active.is_(True))).scalar_one_or_none()
    if plan is None:
        return {"status": "no_active_program", "days": []}
    version = get_active_version(plan, user_id)
    days = [{"week": w["week_number"], "day": d["day_number"], "name": d["name"], "prescriptions": d["exercises"]}
        for w in version.content["data"]["weeks"] for d in w["days"]
        if (week is None or week == w["week_number"]) and (day is None or day == d["day_number"])]
    if (day is not None or week is not None) and not days:
        raise GymError("Día no encontrado.", 404)
    return {"program_id": plan.public_id, "name": plan.name, "revision_id": version.public_id, "revision": version.version_number, "active": plan.gym_active, "days": days, "semantics": "prescriptions_are_targets_not_completed_sets"}


def read_session(user_id, public_id):
    record = owned_session(user_id, public_id)
    day = session_day(record, user_id)
    return {"session_id": record.public_id, "status": record.status, "day": day["name"], "program_id": record.training_plan.public_id,
        "revision_id": record.training_plan_version.public_id, "duration_seconds": record.duration_seconds,
        "exercises": [{"name": exercise.name, "sets": [{"reps": item.reps, "weight_kg": str(item.weight_kg), "rir": str(item.rir) if item.rir is not None else None, "rpe": str(item.rpe) if item.rpe is not None else None, "load_mode": (item.load_details_json or {}).get("load_mode", "direct_total")} for item in exercise.sets if item.user_id == user_id]} for exercise in record.exercises if exercise.user_id == user_id]}
