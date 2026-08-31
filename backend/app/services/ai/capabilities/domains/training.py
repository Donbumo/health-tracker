from app.services.ai.capabilities.types import (
    AICapabilityManifest,
    ActionCapability,
    AIIntent,
    MetricDefinition,
    ReadCapability,
)


METRICS = (
    MetricDefinition("sessions", "Sesiones", "sessions", ("count",), True, True, True, 0, "missing_is_no_record"),
    MetricDefinition("duration", "Duración", "minutes", ("sum", "average"), True, True, False, 0, "unknown_not_zero"),
    MetricDefinition("volume", "Volumen comparable", "user_load_unit", ("sum", "max"), True, True, False, 1, "only_compatible_load_modes"),
    MetricDefinition("exercise_load", "Carga por ejercicio", "kg", ("latest", "max"), True, True, False, 1, "only_compatible_load_modes"),
    MetricDefinition("reps", "Repeticiones", "reps", ("sum", "max"), True, True, False, 0, "compare_with_context"),
)

TRAINING_ACTION_FOUNDATION = ActionCapability(
    "record_training_session",
    "training",
    "training_session",
    ("performed_at", "plan", "exercises", "sets", "reps", "load", "notes"),
    "workout_entry",
    True,
    "create_manual_training_session",
    available=False,
    blocker="Requiere resolver plan/version y validación completa de ejercicios antes de confirmar.",
)

MANIFEST = AICapabilityManifest(
    domain_id="training",
    label="Entrenamiento",
    description="Sesiones, historial y progreso con cargas comparables.",
    entities=("training_session", "exercise", "training_set"),
    metrics=METRICS,
    read_capabilities=(
        ReadCapability(AIIntent.SUMMARY, ("get_training_summary",), tuple(item.id for item in METRICS)),
        ReadCapability(AIIntent.LATEST, ("get_training_history",), ("sessions",), ("30d", "90d")),
        ReadCapability(AIIntent.TREND, ("get_exercise_progress",), ("exercise_load", "volume", "reps"), ("7d", "30d", "90d"), 2),
        ReadCapability(AIIntent.COMPARE, ("get_training_summary",), ("sessions", "duration", "volume"), ("7d", "30d", "90d"), 2),
        ReadCapability(AIIntent.CONSISTENCY, ("get_training_summary",), ("sessions", "duration"), ("7d", "30d", "90d"), 2),
        ReadCapability(AIIntent.PROGRESS, ("get_exercise_progress",), ("exercise_load", "volume", "reps"), ("7d", "30d", "90d"), 2),
        ReadCapability(AIIntent.COVERAGE, ("get_training_summary",), tuple(item.id for item in METRICS)),
        ReadCapability(AIIntent.SOURCES, ("get_data_sources_summary",), tuple(item.id for item in METRICS)),
    ),
    comparisons=True,
)
