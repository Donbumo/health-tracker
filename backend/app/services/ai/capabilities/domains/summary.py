from app.services.ai.capabilities.types import (
    AICapabilityManifest,
    AIIntent,
    ReadCapability,
)


MANIFEST = AICapabilityManifest(
    domain_id="all",
    label="Resumen general",
    description="Vista combinada de los dominios disponibles de Health Tracker.",
    entities=("dashboard_summary",),
    metrics=(),
    read_capabilities=(
        ReadCapability(
            AIIntent.SUMMARY,
            ("get_dashboard_summary",),
            description="Resumen longitudinal combinado.",
        ),
        ReadCapability(
            AIIntent.COMPARE,
            ("get_dashboard_summary",),
            periods=("7d", "30d", "90d"),
            description="Comparación contra el periodo anterior equivalente.",
        ),
        ReadCapability(AIIntent.DAILY_COACH, ("get_coach_brief",), periods=("today",),
                       description="Señales y evidencia del día, calculadas por Health Tracker."),
        ReadCapability(AIIntent.WEEKLY_COACH, ("get_coach_brief",), periods=("7d",),
                       description="Prioridades semanales y cobertura verificable."),
        ReadCapability(AIIntent.EXPLAIN_SIGNAL, ("get_coach_brief",), periods=("today", "7d"),
                       description="Explicación de una señal calculada."),
        ReadCapability(AIIntent.EXPLAIN_PROGRESSION, ("get_coach_brief",), periods=("today", "7d"),
                       description="Explicación de la evaluación Gym existente."),
        ReadCapability(AIIntent.WHAT_CHANGED, ("get_coach_brief",), periods=("7d",),
                       description="Cambios comparables del resumen semanal."),
        ReadCapability(AIIntent.WHAT_SHOULD_I_REVIEW, ("get_coach_brief",), periods=("today", "7d"),
                       description="Prioridades determinadas por el motor de señales."),
    ),
    comparisons=True,
)
