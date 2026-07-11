"""Read-only prompt helpers for preparing standard import JSON with AI.

The catalog is static on purpose: it mirrors the current public schemas without
calling external AI services, storing copied prompts, or reading user data.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import current_app, has_app_context


TARGET_ORDER = (
    "weigh_in_batch",
    "food_products",
    "daily_energy",
    "daily_nutrition",
    "completed_workout",
    "medical_lab",
    "training_plan",
    "recipe",
    "recipe_bundle",
)

PRIVACY_NOTICE = (
    "Health Tracker no envía tus datos a ninguna IA. Este prompt se copia "
    "localmente para que tú decidas dónde usarlo. Evita compartir información "
    "personal que no sea necesaria."
)

GENERAL_RULES = (
    "Devuelve únicamente JSON válido.",
    "No uses Markdown ni bloques de código.",
    "No añadas explicaciones antes o después.",
    "No inventes valores.",
    "Si un dato opcional no existe, omítelo.",
    "Si falta un campo obligatorio, no lo inventes; deja una estructura incompleta claramente detectable o usa un campo de notas permitido para describir el problema.",
    "Respeta fechas ISO 8601, kilogramos, centímetros, kcal, gramos, bpm y segundos cuando apliquen.",
    "Conserva nombres, cantidades y valores originales.",
    "No conviertas unidades sin explicar la conversión exacta en notes cuando el target lo permita.",
    "No adivines user_id; Health Tracker debe derivarlo del usuario autenticado o tú debes reemplazar el marcador explícito si el schema lo exige.",
    "No inventes IDs de rutinas, versiones, alimentos o recetas; usa marcadores REEMPLAZAR_* solo como plantilla.",
)


@dataclass(frozen=True)
class PromptTargetSpec:
    target_type: str
    schema_name: str
    friendly_name: str
    purpose: str
    structure: str
    required_notes: tuple[str, ...]
    optional_notes: tuple[str, ...]
    common_errors: tuple[str, ...]
    template: dict[str, Any]
    references: tuple[str, ...] = ()
    batch_mode: str = "single"


class ImportPromptCatalog:
    """Return safe prompt text and JSON templates for supported import targets."""

    def __init__(self, schema_root: Path | None = None) -> None:
        configured_root = current_app.config.get("SCHEMA_ROOT") if has_app_context() else None
        self.schema_root = Path(schema_root or configured_root or "schemas")

    def targets(self) -> list[dict[str, Any]]:
        return [self.get(target_type) for target_type in TARGET_ORDER]

    def target_types(self) -> tuple[str, ...]:
        return TARGET_ORDER

    def get(self, target_type: str) -> dict[str, Any]:
        if target_type not in _SPECS:
            raise KeyError(target_type)
        spec = _SPECS[target_type]
        schema = self._load_schema(spec.schema_name)
        required_paths = _required_paths(schema)
        source_types = _source_types(schema)
        template = copy.deepcopy(spec.template)
        prompt = self._build_prompt(
            spec=spec,
            required_paths=required_paths,
            source_types=source_types,
            template=template,
        )
        return {
            "target_type": spec.target_type,
            "schema_name": spec.schema_name,
            "friendly_name": spec.friendly_name,
            "purpose": spec.purpose,
            "structure": spec.structure,
            "required": required_paths,
            "optional": list(spec.optional_notes),
            "source_types": source_types,
            "references": list(spec.references),
            "batch_mode": spec.batch_mode,
            "common_errors": list(spec.common_errors),
            "privacy_notice": PRIVACY_NOTICE,
            "prompt": prompt,
            "template": template,
            "template_json": _pretty_json(template),
        }

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {target["target_type"]: target for target in self.targets()}

    def _load_schema(self, schema_name: str) -> dict[str, Any]:
        schema_path = self.schema_root / f"{schema_name}.schema.json"
        with schema_path.open(encoding="utf-8") as schema_file:
            return json.load(schema_file)

    def _build_prompt(
        self,
        *,
        spec: PromptTargetSpec,
        required_paths: list[str],
        source_types: list[str],
        template: dict[str, Any],
    ) -> str:
        sections = [
            "Actúa como preparador de datos para Health Tracker.",
            f"Objetivo: crear un JSON estándar para {spec.friendly_name}.",
            "",
            "Reglas estrictas:",
            *[f"- {rule}" for rule in GENERAL_RULES],
            "",
            f"Target: {spec.target_type}",
            f"Schema: {spec.schema_name}.schema.json",
            f"Propósito: {spec.purpose}",
            f"Estructura esperada: {spec.structure}",
            f"source_type permitido: {', '.join(source_types) if source_types else 'no requerido por schema'}",
            "",
            "Campos obligatorios:",
            *[f"- {path}" for path in required_paths],
            "",
            "Campos opcionales relevantes:",
            *[f"- {field}" for field in spec.optional_notes],
        ]
        if spec.references:
            sections.extend(
                [
                    "",
                    "Referencias por ID:",
                    *[f"- {reference}" for reference in spec.references],
                ]
            )
        sections.extend(
            [
                "",
                "Errores comunes a evitar:",
                *[f"- {error}" for error in spec.common_errors],
                "",
                "Ejemplo ficticio mínimo. Úsalo como forma, no como datos reales:",
                _pretty_json(template),
                "",
                PRIVACY_NOTICE,
                "",
                "Ahora convierte los datos que te pegaré a continuación. Devuelve solo JSON.",
            ]
        )
        return "\n".join(sections)


def _pretty_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _source_types(schema: dict[str, Any]) -> list[str]:
    properties = schema.get("properties", {})
    source_type = properties.get("source_type", {})
    enum = source_type.get("enum")
    return list(enum) if isinstance(enum, list) else []


def _required_paths(schema: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    _collect_required_paths(schema, "$", paths)
    return paths


def _collect_required_paths(schema: dict[str, Any], prefix: str, paths: list[str]) -> None:
    required = schema.get("required") or []
    properties = schema.get("properties") or {}
    for field in required:
        path = f"{prefix}.{field}" if prefix != "$" else field
        paths.append(path)
        child = properties.get(field)
        if isinstance(child, dict):
            if child.get("type") == "array" and isinstance(child.get("items"), dict):
                _collect_required_paths(child["items"], f"{path}[]", paths)
            else:
                _collect_required_paths(child, path, paths)


_SPECS: dict[str, PromptTargetSpec] = {
    "weigh_in_batch": PromptTargetSpec(
        target_type="weigh_in_batch",
        schema_name="weigh_in",
        friendly_name="pesajes y composición corporal",
        purpose="Registrar uno o varios pesajes con composición corporal opcional.",
        structure="Un documento weigh_in por registro; el asistente estándar puede generar varios documentos desde un lote.",
        batch_mode="batch",
        required_notes=("schema_version", "record_type", "user_id", "source_type", "data.recorded_at", "data.weight_kg"),
        optional_notes=("body_fat_percent", "muscle_mass_kg", "water_percent", "visceral_fat", "bmr_kcal", "bmi", "source", "notes"),
        common_errors=("No inventar peso si solo existe una nota.", "Usar recorded_at ISO 8601 con fecha y hora.", "No usar aliases como body_water_percent en el JSON final."),
        template={
            "schema_version": "1.0",
            "record_type": "weigh_in",
            "user_id": "REEMPLAZAR_USER_ID",
            "source_type": "uploaded",
            "data": {
                "recorded_at": "2026-07-10T07:30:00+00:00",
                "weight_kg": 82.4,
                "body_fat_percent": 24.5,
                "notes": "Ejemplo ficticio; reemplazar con datos revisados.",
            },
        },
    ),
    "food_products": PromptTargetSpec(
        target_type="food_products",
        schema_name="food_product",
        friendly_name="productos de alacena",
        purpose="Crear productos reutilizables con macros por 100 g cuando existan.",
        structure="Un documento food_product por producto.",
        batch_mode="batch",
        required_notes=("schema_version", "type", "name o data.name"),
        optional_notes=("brand", "serving_size_g", "serving_label", "calories_per_100g", "protein_g_per_100g", "fat_g_per_100g", "carbs_g_per_100g", "net_carbs_g_per_100g", "fiber_g_per_100g", "sodium_mg_per_100g", "notes"),
        common_errors=("No inventar macros faltantes.", "No mezclar macros por porción con macros por 100 g sin explicar conversión.", "No incluir código de barras si no existe en el schema."),
        template={
            "schema_version": "1.0",
            "type": "food_product",
            "source_type": "uploaded",
            "name": "Yogur griego ficticio",
            "brand": "Marca QA",
            "serving_size_g": 170,
            "calories_per_100g": 59,
            "protein_g_per_100g": 10,
            "fat_g_per_100g": 0.4,
            "carbs_g_per_100g": 3.6,
            "notes": "Ejemplo ficticio.",
        },
    ),
    "daily_energy": PromptTargetSpec(
        target_type="daily_energy",
        schema_name="daily_energy",
        friendly_name="gasto energético diario",
        purpose="Registrar gasto energético, pasos y distancia por día.",
        structure="Documento con data.date y métricas opcionales del día.",
        batch_mode="single_or_batch",
        required_notes=("schema_version", "record_type", "user_id", "source_type", "data.date"),
        optional_notes=("total_expenditure_kcal", "resting_expenditure_kcal", "active_expenditure_kcal", "steps", "distance_meters", "source", "notes"),
        common_errors=("No inventar calorías totales si solo hay pasos.", "distance_meters debe estar en metros.", "date debe ser YYYY-MM-DD."),
        template={
            "schema_version": "1.0",
            "record_type": "daily_energy",
            "user_id": "REEMPLAZAR_USER_ID",
            "source_type": "uploaded",
            "data": {
                "date": "2026-07-10",
                "total_expenditure_kcal": 2400,
                "active_expenditure_kcal": 520,
                "steps": 8200,
                "distance_meters": 6100,
                "notes": "Ejemplo ficticio.",
            },
        },
    ),
    "daily_nutrition": PromptTargetSpec(
        target_type="daily_nutrition",
        schema_name="daily_nutrition",
        friendly_name="nutrición diaria",
        purpose="Registrar comidas, alimentos y macros de un día.",
        structure="Documento con data.date, totales opcionales y meals/items si existen.",
        batch_mode="single_or_batch",
        required_notes=("schema_version", "record_type", "user_id", "source_type", "data.date"),
        optional_notes=("data.calories_kcal", "protein_g", "fat_g", "net_carbs_g", "total_carbs_g", "fiber_g", "sugar_g", "sodium_mg", "meals[].items[]"),
        common_errors=("No inventar macros faltantes.", "meal_type debe ser breakfast, lunch, dinner, snack, extra u other.", "No inventar food_product_id ni recipe_id."),
        references=("food_product_id y recipe_id solo si Health Tracker ya mostró esos IDs.",),
        template={
            "schema_version": "1.0",
            "record_type": "daily_nutrition",
            "user_id": "REEMPLAZAR_USER_ID",
            "source_type": "uploaded",
            "data": {
                "date": "2026-07-10",
                "calories_kcal": 450,
                "protein_g": 32,
                "fat_g": 12,
                "net_carbs_g": 38,
                "meals": [
                    {
                        "meal_type": "breakfast",
                        "name": "Desayuno ficticio",
                        "items": [
                            {
                                "name": "Avena ficticia",
                                "quantity": 60,
                                "unit": "g",
                                "calories_kcal": 230,
                                "protein_g": 8,
                            }
                        ],
                    }
                ],
            },
        },
    ),
    "completed_workout": PromptTargetSpec(
        target_type="completed_workout",
        schema_name="completed_workout",
        friendly_name="sesión de entrenamiento completada",
        purpose="Registrar una sesión realizada ligada a una rutina y versión existentes.",
        structure="Documento con IDs de rutina/version, fecha, día planeado, ejercicios y sets.",
        batch_mode="single_or_batch",
        required_notes=("schema_version", "record_type", "user_id", "source_type", "data.training_plan_id", "data.training_plan_version_id", "data.performed_at", "data.planned_week_number", "data.planned_day_number", "data.exercises[]"),
        optional_notes=("duration_seconds", "average_heart_rate_bpm", "calories_burned", "rir", "rpe", "rest_seconds", "notes"),
        references=("training_plan_id y training_plan_version_id deben copiarse desde Health Tracker.", "planned_exercise_order y planned_set_number deben corresponder al plan usado."),
        common_errors=("No inventar IDs de plan o versión.", "No inventar planned_* si no se conoce la rutina.", "performed_at debe ser date-time ISO 8601."),
        template={
            "schema_version": "1.0",
            "record_type": "completed_workout",
            "user_id": "REEMPLAZAR_USER_ID",
            "source_type": "uploaded",
            "data": {
                "training_plan_id": "REEMPLAZAR_PLAN_ID",
                "training_plan_version_id": "REEMPLAZAR_PLAN_VERSION_ID",
                "performed_at": "2026-07-10T18:00:00+00:00",
                "planned_week_number": 1,
                "planned_day_number": 1,
                "duration_seconds": 2700,
                "exercises": [
                    {
                        "exercise_order": 1,
                        "planned_exercise_order": 1,
                        "name": "Press ficticio",
                        "sets": [
                            {
                                "set_number": 1,
                                "planned_set_number": 1,
                                "weight_kg": 50,
                                "reps": 8,
                                "rir": 2,
                                "rpe": 8,
                                "rest_seconds": 90,
                            }
                        ],
                    }
                ],
            },
        },
    ),
    "medical_lab": PromptTargetSpec(
        target_type="medical_lab",
        schema_name="medical_lab",
        friendly_name="reporte de laboratorio médico",
        purpose="Registrar reporte de laboratorio y marcadores clínicos.",
        structure="Documento con fecha de reporte y lista markers.",
        batch_mode="single_or_batch",
        required_notes=("schema_version", "type", "user_id", "source_type", "date", "markers[].name", "markers[].value", "markers[].unit"),
        optional_notes=("laboratory_name", "doctor_name", "source", "notes", "code", "reference_min", "reference_max", "reference_text", "status"),
        common_errors=("No interpretar resultados ni diagnosticar.", "No inventar rangos de referencia.", "Usar status solo low, normal, high o unknown si existe en el reporte."),
        template={
            "schema_version": "1.0",
            "type": "medical_lab",
            "user_id": "REEMPLAZAR_USER_ID",
            "source_type": "uploaded",
            "date": "2026-07-10",
            "laboratory_name": "Laboratorio QA ficticio",
            "markers": [
                {
                    "name": "Glucosa ficticia",
                    "value": 92,
                    "unit": "mg/dL",
                    "reference_min": 70,
                    "reference_max": 99,
                    "status": "normal",
                }
            ],
            "notes": "Ejemplo ficticio; no sustituye evaluación médica.",
        },
    ),
    "training_plan": PromptTargetSpec(
        target_type="training_plan",
        schema_name="training_plan",
        friendly_name="rutina versionable",
        purpose="Crear o actualizar una rutina planificada versionable.",
        structure="Documento con data.name y data.weeks[].days[].exercises[].sets[].",
        batch_mode="single_or_batch",
        required_notes=("schema_version", "record_type", "user_id", "source_type", "data.name", "data.weeks[]"),
        optional_notes=("description", "week.name", "exercise.notes", "set.reps", "set.reps_min/reps_max", "duration_seconds", "distance_m", "target", "rest_seconds"),
        common_errors=("No inventar semanas, días o ejercicios no presentes.", "Cada set debe tener reps, reps_min/reps_max, duration_seconds o distance_m.", "No usar aliases históricos como rir_objetivo si el schema no los define."),
        template={
            "schema_version": "1.0",
            "record_type": "training_plan",
            "user_id": "REEMPLAZAR_USER_ID",
            "source_type": "uploaded",
            "data": {
                "name": "Rutina QA ficticia",
                "description": "Ejemplo ficticio.",
                "weeks": [
                    {
                        "week_number": 1,
                        "days": [
                            {
                                "day_number": 1,
                                "name": "Día ficticio",
                                "exercises": [
                                    {
                                        "exercise_order": 1,
                                        "name": "Remo ficticio",
                                        "sets": [
                                            {
                                                "set_number": 1,
                                                "reps_min": 8,
                                                "reps_max": 12,
                                                "rest_seconds": 90,
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        },
    ),
    "recipe": PromptTargetSpec(
        target_type="recipe",
        schema_name="recipe",
        friendly_name="receta",
        purpose="Registrar una receta con ingredientes por gramos.",
        structure="Documento recipe con ingredientes que apuntan a producto existente o nombre de producto.",
        batch_mode="single_or_batch",
        required_notes=("schema_version", "type", "name", "ingredients[].quantity_g", "ingredients[].food_product_id o food_product_name"),
        optional_notes=("servings", "yield_weight_g", "description", "source", "notes", "food_product_brand", "sort_order"),
        references=("food_product_id solo si Health Tracker ya mostró ese ID; si no, usar food_product_name.",),
        common_errors=("No inventar ingredientes.", "quantity_g debe estar en gramos.", "No usar food_product_id si no se conoce."),
        template={
            "schema_version": "1.0",
            "type": "recipe",
            "source_type": "uploaded",
            "name": "Receta QA ficticia",
            "servings": 2,
            "ingredients": [
                {
                    "food_product_name": "Ingrediente ficticio",
                    "quantity_g": 100,
                    "sort_order": 1,
                }
            ],
            "notes": "Ejemplo ficticio.",
        },
    ),
    "recipe_bundle": PromptTargetSpec(
        target_type="recipe_bundle",
        schema_name="recipe_bundle",
        friendly_name="bundle de recetas",
        purpose="Importar varias recetas en un solo archivo.",
        structure="Documento recipe_bundle con recipes[], cada receta sigue el schema recipe embebido.",
        batch_mode="batch",
        required_notes=("schema_version", "type", "recipes[]", "recipes[].name", "recipes[].ingredients[]"),
        optional_notes=("name", "source_type", "recipe.description", "recipe.servings", "recipe.notes"),
        references=("food_product_id dentro de ingredientes solo si Health Tracker ya mostró ese ID.",),
        common_errors=("No crear recetas vacías.", "No inventar cantidades.", "No mezclar productos y recetas diarias."),
        template={
            "schema_version": "1.0",
            "type": "recipe_bundle",
            "name": "Bundle QA ficticio",
            "source_type": "uploaded",
            "recipes": [
                {
                    "schema_version": "1.0",
                    "type": "recipe",
                    "name": "Receta de bundle ficticia",
                    "ingredients": [
                        {
                            "food_product_name": "Ingrediente ficticio",
                            "quantity_g": 100,
                        }
                    ],
                }
            ],
        },
    ),
}
