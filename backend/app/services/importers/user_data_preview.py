from typing import Any

from app.services.validation import JsonSchemaValidationError, validate_json_document


EXPECTED_SCHEMA_VERSION = "1.0"
EXPECTED_SECTIONS = (
    "uploads",
    "weigh_ins",
    "daily_nutrition",
    "daily_energy",
    "daily_balances",
    "training_plans",
    "training_sessions",
    "medical_lab_reports",
)
FORBIDDEN_NAMES = {"password_hash", "password", "secret", "token"}


def _safe_schema_errors(error: JsonSchemaValidationError) -> list[str]:
    errors = []
    for message in error.errors:
        location = message.partition(":")[0] or "$"
        if "required property" in message:
            reason = "falta un campo requerido"
        elif "Additional properties" in message or "does not match" in message:
            reason = "contiene un campo no permitido"
        elif "is not of type" in message:
            reason = "tiene un tipo inválido"
        elif "was expected" in message or "is not one of" in message:
            reason = "contiene un valor no permitido"
        else:
            reason = "no cumple el schema de exportación"
        errors.append(f"{location}: {reason}")
    return errors


def _safe_exported_user(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    user = payload.get("user")
    if not isinstance(user, dict):
        return None
    return {
        key: user.get(key)
        for key in ("id", "email", "role")
        if key in user
    }


def preview_user_data_import(
    payload: dict[str, Any],
    current_user_id: int | None = None,
) -> dict[str, Any]:
    """Validate and summarize an export without reading or writing the database."""
    try:
        validate_json_document(payload, "user_data_export")
    except JsonSchemaValidationError as error:
        errors = _safe_schema_errors(error)
    else:
        errors = []

    data = payload.get("data") if isinstance(payload, dict) else None
    data = data if isinstance(data, dict) else {}
    section_names = sorted(
        name
        for name in data
        if isinstance(name, str) and name not in FORBIDDEN_NAMES
    )
    counts = {
        name: len(data[name])
        for name in section_names
        if isinstance(data.get(name), list)
    }
    warnings = []

    schema_version = payload.get("schema_version") if isinstance(payload, dict) else None
    if schema_version != EXPECTED_SCHEMA_VERSION:
        warnings.append(
            f"Versión de schema no esperada; se requiere {EXPECTED_SCHEMA_VERSION}."
        )

    exported_user = _safe_exported_user(payload)
    exported_user_id = exported_user.get("id") if exported_user else None
    if (
        current_user_id is not None
        and isinstance(exported_user_id, int)
        and exported_user_id != current_user_id
    ):
        warnings.append("El export pertenece a otro identificador de usuario.")

    missing_sections = [name for name in EXPECTED_SECTIONS if name not in data]
    if missing_sections:
        warnings.append(
            "Faltan secciones esperadas: " + ", ".join(missing_sections) + "."
        )

    return {
        "valid": not errors,
        "errors": errors,
        "exported_user": exported_user,
        "schema_version": schema_version,
        "sections": section_names,
        "counts": counts,
        "warnings": warnings,
        "dry_run": True,
        "writes_performed": False,
    }
