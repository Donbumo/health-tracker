import hashlib
import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from flask import current_app
from sqlalchemy import func, or_

from app.extensions import db
from app.models import (
    DailyEnergy,
    DailyNutrition,
    MedicalLabReport,
    MedicalLabResult,
    NutritionItem,
    NutritionMeal,
    TrainingPlan,
    TrainingPlanVersion,
    TrainingSession,
    TrainingSessionExercise,
    TrainingSet,
    User,
    WeighIn,
)
from app.services.validation import validate_json_document


DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo12345"
DEMO_SOURCE = "demo_seed"
DEMO_PLAN_NAME = "Rutina ficticia QA"
DEMO_SESSION_NOTE = "QA_DEMO_SEED: sesión completamente ficticia."
DEMO_LAB_NAME = "Laboratorio ficticio QA"
DEMO_LAB_NOTE = "QA_DEMO_MEDICAL_SEED: reporte completamente ficticio y no clínico."


class DemoSeedError(ValueError):
    pass


def _local_date(value: datetime, app_timezone: ZoneInfo):
    if value.tzinfo is None or value.utcoffset() is None:
        return value.date()
    return value.astimezone(app_timezone).date()


def _demo_user(created: dict[str, int]) -> User:
    user = db.session.execute(
        db.select(User).where(
            or_(
                func.lower(User.email) == DEMO_EMAIL,
                func.lower(User.username) == DEMO_EMAIL,
            )
        )
    ).scalar_one_or_none()
    if user is None:
        user = User(username=DEMO_EMAIL, email=DEMO_EMAIL, role="user")
        user.set_password(DEMO_PASSWORD)
        db.session.add(user)
        db.session.flush()
        created["users"] += 1
    elif user.role != "user":
        raise DemoSeedError("demo@example.com already belongs to a non-user account")

    user.email = DEMO_EMAIL
    user.set_password(DEMO_PASSWORD)
    return user


def _seed_weigh_ins(
    user: User,
    days: tuple,
    app_timezone: ZoneInfo,
    created: dict[str, int],
) -> None:
    existing_dates = {
        _local_date(record.recorded_at, app_timezone)
        for record in db.session.execute(
            db.select(WeighIn).where(
                WeighIn.user_id == user.id,
                WeighIn.source == DEMO_SOURCE,
            )
        ).scalars()
    }
    values = (
        (days[0], "74.800", "18.400", "58.200"),
        (days[1], "74.500", "18.100", "58.400"),
    )
    for record_date, weight, body_fat, muscle_mass in values:
        if record_date in existing_dates:
            continue
        db.session.add(
            WeighIn(
                user_id=user.id,
                recorded_at=datetime.combine(
                    record_date,
                    time(hour=7),
                    tzinfo=app_timezone,
                ),
                weight_kg=Decimal(weight),
                body_fat_percentage=Decimal(body_fat),
                muscle_mass_kg=Decimal(muscle_mass),
                water_percentage=Decimal("56.000"),
                visceral_fat=Decimal("7.000"),
                bmr_kcal=Decimal("1720.00"),
                bmi=Decimal("23.500"),
                source=DEMO_SOURCE,
                notes="Dato completamente ficticio para QA manual.",
            )
        )
        created["weigh_ins"] += 1


def _seed_energy(user: User, days: tuple, created: dict[str, int]) -> None:
    values = (
        (days[0], "2250.00", "500.00", "1750.00", 7200),
        (days[1], "2380.00", "620.00", "1760.00", 9100),
    )
    for record_date, total, active, resting, steps in values:
        existing = db.session.execute(
            db.select(DailyEnergy).where(
                DailyEnergy.user_id == user.id,
                DailyEnergy.date == record_date,
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        db.session.add(
            DailyEnergy(
                user_id=user.id,
                date=record_date,
                total_calories=Decimal(total),
                active_calories=Decimal(active),
                resting_calories=Decimal(resting),
                steps=steps,
                distance_meters=Decimal("6500.00"),
                source=DEMO_SOURCE,
                notes="Dato completamente ficticio para QA manual.",
            )
        )
        created["energy_days"] += 1


def _seed_nutrition(user: User, days: tuple, created: dict[str, int]) -> None:
    values = (
        (days[0], "1950.000", "135.000", "65.000", "185.000", "28.000"),
        (days[1], "2100.000", "145.000", "70.000", "200.000", "30.000"),
    )
    for record_date, calories, protein, fat, net_carbs, fiber in values:
        existing = db.session.execute(
            db.select(DailyNutrition).where(
                DailyNutrition.user_id == user.id,
                DailyNutrition.date == record_date,
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        nutrition = DailyNutrition(
            user_id=user.id,
            date=record_date,
            source=DEMO_SOURCE,
            notes="Día nutricional completamente ficticio para QA manual.",
            calories=Decimal(calories),
            protein_g=Decimal(protein),
            fat_g=Decimal(fat),
            net_carbs_g=Decimal(net_carbs),
            total_carbs_g=Decimal(net_carbs) + Decimal(fiber),
            fiber_g=Decimal(fiber),
            sugar_g=Decimal("24.000"),
            sodium_mg=Decimal("1800.000"),
        )
        db.session.add(nutrition)
        db.session.flush()
        meal = NutritionMeal(
            user_id=user.id,
            daily_nutrition_id=nutrition.id,
            meal_type="lunch",
            name="Comida ficticia QA",
            sort_order=1,
        )
        db.session.add(meal)
        db.session.flush()
        db.session.add(
            NutritionItem(
                user_id=user.id,
                nutrition_meal_id=meal.id,
                name="Alimento ficticio QA",
                quantity=Decimal("1.000"),
                unit="porción",
                sort_order=1,
                calories=Decimal(calories),
                protein_g=Decimal(protein),
                fat_g=Decimal(fat),
                net_carbs_g=Decimal(net_carbs),
                total_carbs_g=Decimal(net_carbs) + Decimal(fiber),
                fiber_g=Decimal(fiber),
                sugar_g=Decimal("24.000"),
                sodium_mg=Decimal("1800.000"),
                notes="No representa un alimento real.",
            )
        )
        created["nutrition_days"] += 1


def _plan_document(user_id: int) -> dict:
    return {
        "schema_version": "1.0",
        "record_type": "training_plan",
        "user_id": user_id,
        "source_type": "manual_generated",
        "data": {
            "name": DEMO_PLAN_NAME,
            "description": "Rutina completamente ficticia para QA manual.",
            "weeks": [
                {
                    "week_number": 1,
                    "days": [
                        {
                            "day_number": 1,
                            "name": "Día ficticio QA",
                            "exercises": [
                                {
                                    "exercise_order": 1,
                                    "name": "Sentadilla ficticia QA",
                                    "sets": [
                                        {"set_number": 1, "reps": 8, "rest_seconds": 90},
                                        {"set_number": 2, "reps": 8, "rest_seconds": 90},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    }


def _seed_plan(user: User, created: dict[str, int]) -> tuple[TrainingPlan, TrainingPlanVersion]:
    plan = db.session.execute(
        db.select(TrainingPlan).where(
            TrainingPlan.user_id == user.id,
            TrainingPlan.name == DEMO_PLAN_NAME,
        )
    ).scalar_one_or_none()
    if plan is None:
        plan = TrainingPlan(
            user_id=user.id,
            name=DEMO_PLAN_NAME,
            description="Rutina completamente ficticia para QA manual.",
            active_version_number=1,
        )
        db.session.add(plan)
        db.session.flush()
        created["training_plans"] += 1

    version = db.session.execute(
        db.select(TrainingPlanVersion).where(
            TrainingPlanVersion.user_id == user.id,
            TrainingPlanVersion.training_plan_id == plan.id,
            TrainingPlanVersion.version_number == 1,
        )
    ).scalar_one_or_none()
    if version is None:
        document = _plan_document(user.id)
        validate_json_document(document, "training_plan")
        serialized = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        version = TrainingPlanVersion(
            user_id=user.id,
            training_plan_id=plan.id,
            version_number=1,
            created_by_user_id=user.id,
            change_reason="Datos ficticios iniciales para QA manual.",
            schema_version="1.0",
            sha256=hashlib.sha256(serialized).hexdigest(),
            content=document,
        )
        db.session.add(version)
        db.session.flush()
        created["training_plan_versions"] += 1
    return plan, version


def _seed_session(
    user: User,
    plan: TrainingPlan,
    version: TrainingPlanVersion,
    target_date,
    app_timezone: ZoneInfo,
    created: dict[str, int],
) -> None:
    existing = [
        session
        for session in db.session.execute(
            db.select(TrainingSession).where(
                TrainingSession.user_id == user.id,
                TrainingSession.training_plan_id == plan.id,
                TrainingSession.notes == DEMO_SESSION_NOTE,
            )
        ).scalars()
        if _local_date(session.performed_at, app_timezone) == target_date
    ]
    if existing:
        return

    session = TrainingSession(
        user_id=user.id,
        training_plan_id=plan.id,
        training_plan_version_id=version.id,
        performed_at=datetime.combine(
            target_date,
            time(hour=18),
            tzinfo=app_timezone,
        ),
        planned_week_number=1,
        planned_day_number=1,
        duration_seconds=2700,
        average_heart_rate_bpm=118,
        calories_burned=Decimal("260.00"),
        notes=DEMO_SESSION_NOTE,
    )
    db.session.add(session)
    db.session.flush()
    exercise = TrainingSessionExercise(
        user_id=user.id,
        training_session_id=session.id,
        exercise_order=1,
        planned_exercise_order=1,
        name="Sentadilla ficticia QA",
        notes="Ejercicio ficticio para validar la vista de progreso.",
    )
    db.session.add(exercise)
    db.session.flush()
    for set_number, weight, reps in ((1, "40.00", 8), (2, "42.50", 8)):
        db.session.add(
            TrainingSet(
                user_id=user.id,
                training_session_exercise_id=exercise.id,
                set_number=set_number,
                planned_set_number=set_number,
                weight_kg=Decimal(weight),
                reps=reps,
                rir=Decimal("2.0"),
                rpe=Decimal("8.0"),
                rest_seconds=90,
                notes="Serie ficticia QA.",
            )
        )
    created["training_sessions"] += 1


def _seed_medical_lab(user: User, target_date, created: dict[str, int]) -> None:
    existing = db.session.execute(
        db.select(MedicalLabReport).where(
            MedicalLabReport.user_id == user.id,
            MedicalLabReport.date == target_date,
            MedicalLabReport.source == DEMO_SOURCE,
            MedicalLabReport.notes == DEMO_LAB_NOTE,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return

    report = MedicalLabReport(
        user_id=user.id,
        date=target_date,
        laboratory_name=DEMO_LAB_NAME,
        source=DEMO_SOURCE,
        notes=DEMO_LAB_NOTE,
    )
    db.session.add(report)
    db.session.flush()

    markers = (
        ("Glucosa", "GLU", "92.0", "mg/dL"),
        ("HbA1c", "HBA1C", "5.3", "%"),
        ("Colesterol total", "CHOL", "178.0", "mg/dL"),
        ("LDL", "LDL", "105.0", "mg/dL"),
        ("HDL", "HDL", "52.0", "mg/dL"),
        ("Triglicéridos", "TG", "110.0", "mg/dL"),
        ("Vitamina D", "VITD", "32.0", "ng/mL"),
    )
    for marker_name, marker_code, value, unit in markers:
        db.session.add(
            MedicalLabResult(
                user_id=user.id,
                report_id=report.id,
                marker_name=marker_name,
                marker_code=marker_code,
                value=Decimal(value),
                unit=unit,
                status="unknown",
                notes="Valor ficticio para QA; no representa un resultado clínico.",
            )
        )
    created["medical_lab_reports"] += 1


def seed_demo_data() -> tuple[User, dict[str, int]]:
    """Create idempotent, obviously fictional records for browser QA."""
    created = {
        "users": 0,
        "weigh_ins": 0,
        "energy_days": 0,
        "nutrition_days": 0,
        "training_plans": 0,
        "training_plan_versions": 0,
        "training_sessions": 0,
        "medical_lab_reports": 0,
    }
    app_timezone = ZoneInfo(current_app.config["APP_TIMEZONE"])
    today = datetime.now(app_timezone).date()
    days = (today - timedelta(days=1), today)

    try:
        user = _demo_user(created)
        _seed_weigh_ins(user, days, app_timezone, created)
        _seed_energy(user, days, created)
        _seed_nutrition(user, days, created)
        plan, version = _seed_plan(user, created)
        _seed_session(user, plan, version, today, app_timezone, created)
        _seed_medical_lab(user, today, created)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return user, created
