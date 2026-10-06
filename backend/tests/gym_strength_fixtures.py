"""Synthetic strength history shared by isolated QA and domain tests."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from app.extensions import db
from app.models import Exercise, TrainingSession, TrainingSessionExercise, TrainingSet
from app.services.gym_programs import publish_program_document
from app.services.training_plans import get_active_version
from app.services.workout_loads import calculate_workout_load


def strength_fixture(owner, *, count=4, exercise_count=5, now=None):
    now = now or datetime.now(timezone.utc)
    identities = []
    names = ["QA Press banca", "QA Remo", "QA Curl", "QA Nuevo"]
    names += [f"QA Accesorio {n}" for n in range(max(0, exercise_count - 5))]
    for name in names:
        identity = Exercise(user_id=owner, canonical_name=name, normalized_name=name.lower())
        db.session.add(identity)
        identities.append(identity)
    db.session.flush()
    exercises = []
    for n, identity in enumerate(identities, 1):
        exercises.append({"exercise_order": n, "name": identity.canonical_name,
            "exercise_id": identity.public_id,
            "sets": [{"set_number": j, "reps_min": 6, "reps_max": 8,
                      "weight_kg": "80" if n == 1 else "60", "load_value": "80" if n == 1 else "60",
                      "load_unit": "kg", "load_mode": "direct_total", "rir": "2"} for j in (1, 2, 3)]})
    exercises.append({"exercise_order": len(exercises)+1, "name": "QA Sin vínculo",
                      "sets": [{"set_number": j, "reps_min": 6, "reps_max": 8} for j in (1, 2, 3)]})
    document = {"schema_version": "1.0", "record_type": "training_plan", "user_id": owner,
        "source_type": "manual_generated", "data": {"name": "QA · Fuerza D1/D2/D3",
        "weeks": [{"week_number": 1, "days": [
            {"day_number": 1, "name": "D1 · Empuje y tirón", "exercises": exercises},
            {"day_number": 2, "name": "D2 · Técnica", "exercises": exercises[:1]},
            {"day_number": 3, "name": "D3 · Repeticiones", "exercises": exercises[1:2]}]}]}}
    plan, _ = publish_program_document(document, owner)
    version = get_active_version(plan, owner)
    sessions = []
    for i in range(count):
        moment = now - timedelta(days=(count-1-i)*7+1)
        session = TrainingSession(user_id=owner, training_plan_id=plan.id, training_plan_version_id=version.id,
            status="completed", planned_week_number=1, planned_day_number=1, performed_at=moment,
            started_at=moment, completed_at=moment+timedelta(minutes=45), duration_seconds=2700,
            timezone="UTC", client_submission_id=str(uuid4()))
        db.session.add(session)
        for exercise in exercises:
            order = exercise["exercise_order"]
            if order == 4 and i != count-1:
                continue
            occurrence = TrainingSessionExercise(user_id=owner, training_session=session, exercise_order=order,
                                                 planned_exercise_order=order, name=exercise["name"])
            db.session.add(occurrence)
            weight = ("75" if i == 0 else "77.5" if i == 1 else "80") if order == 1 else "60"
            load = calculate_workout_load("direct_total", "kg", {"direct_total": weight})
            for j in (1, 2, 3):
                reps = (8 if j == 1 else 7) if order == 2 else 8
                db.session.add(TrainingSet(user_id=owner, session_exercise=occurrence,
                    set_number=j, planned_set_number=j, weight_kg=load.weight_kg, load_details_json=load.details,
                    reps=reps, rir=Decimal(1 if order == 3 else 2)))
        sessions.append(session)
    db.session.commit()
    return plan, identities, sessions
