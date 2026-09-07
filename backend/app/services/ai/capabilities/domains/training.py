from app.services.ai.capabilities.types import (
    AICapabilityManifest,
    AIIntent,
    MetricDefinition,
    ReadCapability,
)
from app.services.ai.capabilities.domains.training_actions import TRAINING_CORRECT, TRAINING_CREATE


METRICS = (
    MetricDefinition("sessions", "Sesiones", "sessions", ("count",), True, True, True, 0, "missing_is_no_record"),
    MetricDefinition("duration", "Duración", "minutes", ("sum", "average"), True, True, False, 0, "unknown_not_zero"),
    MetricDefinition("volume", "Volumen comparable", "user_load_unit", ("sum", "max"), True, True, False, 1, "only_compatible_load_modes"),
    MetricDefinition("exercise_load", "Carga por ejercicio", "kg", ("latest", "max"), True, True, False, 1, "only_compatible_load_modes"),
    MetricDefinition("reps", "Repeticiones", "reps", ("sum", "max"), True, True, False, 0, "compare_with_context"),
)

TRAINING_ACTION_FOUNDATION = TRAINING_CREATE

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
    action_capabilities=(TRAINING_CREATE, TRAINING_CORRECT),
    comparisons=True,
)
