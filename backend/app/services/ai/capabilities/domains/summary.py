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
    ),
    comparisons=True,
)
