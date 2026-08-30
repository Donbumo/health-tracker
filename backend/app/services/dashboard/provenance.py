from __future__ import annotations


SOURCE_ORDER = {
    "Manual": 0,
    "Health Connect": 1,
    "Dispositivo": 2,
    "Importación": 3,
    "Proveedor externo": 4,
    "Health Tracker": 5,
    "Otra fuente": 6,
}


def source_label(source: str | None, *, has_source_file: bool = False) -> str | None:
    """Return a compact, non-sensitive provenance label for dashboard views."""
    if has_source_file:
        return "Importación"
    normalized = (source or "").strip().casefold()
    if not normalized:
        return None
    if normalized == "manual" or normalized.startswith("manual_"):
        return "Manual"
    if "health_connect" in normalized or "health connect" in normalized:
        return "Health Connect"
    if any(token in normalized for token in ("device", "mobile", "companion", "ble")):
        return "Dispositivo"
    if any(token in normalized for token in ("import", "upload", "file", "fixture", "demo")):
        return "Importación"
    if any(token in normalized for token in ("external", "provider", "strava")):
        return "Proveedor externo"
    if any(token in normalized for token in ("system", "generated", "health_tracker")):
        return "Health Tracker"
    return "Otra fuente"


def source_labels(values) -> list[str]:
    labels = {value for value in values if value}
    return sorted(labels, key=lambda value: (SOURCE_ORDER.get(value, 99), value))
