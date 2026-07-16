from app.extensions import db
from app.models import (
    Activity,
    ApiDevice,
    DailyEnergy,
    DailyNutrition,
    ExportRecord,
    MedicalLabReport,
    PlannedWorkout,
    TrainingPlan,
    TrainingSession,
    User,
    WeighIn,
)


def _exists(model, user_id: int, *conditions) -> bool:
    statement = db.select(model.id).where(model.user_id == user_id, *conditions).limit(1)
    return db.session.execute(statement).scalar_one_or_none() is not None


def getting_started_status(user_id: int) -> dict:
    """Return a derived onboarding state without creating checklist records."""
    user = db.session.get(User, user_id)
    if user is None:
        raise ValueError("User not found")

    has_plan = _exists(TrainingPlan, user_id)
    has_planned_workout = _exists(
        PlannedWorkout,
        user_id,
        PlannedWorkout.deleted_at.is_(None),
        PlannedWorkout.status.in_(("planned", "in_progress", "completed")),
    )
    has_session = _exists(TrainingSession, user_id)
    has_backup = _exists(
        ExportRecord,
        user_id,
        ExportRecord.domain == "account_backup",
        ExportRecord.status == "ready",
    )
    has_device = _exists(ApiDevice, user_id, ApiDevice.revoked_at.is_(None))
    preferences_complete = bool(user.timezone and user.preferred_load_unit)

    items = [
        {
            "key": "preferences",
            "label": "Configurar tus preferencias",
            "help": "Elige zona horaria y unidad de carga; el nombre visible es opcional.",
            "complete": preferences_complete,
            "endpoint": "main.account_preferences",
            "required": True,
        },
        {
            "key": "routine",
            "label": "Crear o importar una rutina",
            "help": "Empieza con una rutina propia o importa un archivo compatible.",
            "complete": has_plan,
            "endpoint": "training.list_plans",
            "required": True,
        },
        {
            "key": "planned_workout",
            "label": "Planear tu primer entrenamiento",
            "help": "Selecciona un día de la versión activa y asígnale una fecha.",
            "complete": has_planned_workout,
            "endpoint": "planned.create" if has_plan else "training.list_plans",
            "required": True,
        },
        {
            "key": "session",
            "label": "Registrar tu primera sesión",
            "help": "Puedes iniciar desde un entrenamiento planeado o desde una rutina.",
            "complete": has_session,
            "endpoint": "sessions.new_session" if has_plan else "training.list_plans",
            "required": True,
        },
        {
            "key": "backup",
            "label": "Crear tu primer backup",
            "help": "Un backup completo sirve para recuperación; no es lo mismo que importar datos.",
            "complete": has_backup,
            "endpoint": "main.new_account_backup",
            "required": True,
        },
        {
            "key": "device",
            "label": "Registrar un dispositivo API",
            "help": "Opcional: solo si usarás un cliente companion compatible.",
            "complete": has_device,
            "endpoint": "main.account_devices",
            "required": False,
        },
    ]
    required_items = [item for item in items if item["required"]]
    required_complete = all(item["complete"] for item in required_items)
    established = any(
        (
            has_plan,
            has_session,
            _exists(WeighIn, user_id),
            _exists(DailyEnergy, user_id),
            _exists(DailyNutrition, user_id),
            _exists(Activity, user_id),
            _exists(MedicalLabReport, user_id),
        )
    )
    return {
        "items": items,
        "completed_count": sum(item["complete"] for item in required_items),
        "total_count": len(required_items),
        "required_complete": required_complete,
        "established": established,
        "dismissed": user.onboarding_dismissed_at is not None,
        "show_dashboard_prompt": (
            not established
            and not required_complete
            and user.onboarding_dismissed_at is None
        ),
    }
