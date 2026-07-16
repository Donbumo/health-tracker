"""Read-only assisted import preview for non-standard JSON documents.

This module does not write to the database.

It detects possible import domains, suggests canonical mappings, and returns a
preview payload that can later be connected to UI, ImportJob, standard JSON
generation, and official importers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import unicodedata

from app.services.importers.schema_detector import SchemaDetector


@dataclass(frozen=True)
class DomainRule:
    target_type: str
    path_hints: tuple[str, ...]
    aliases: dict[str, str]
    signal_fields: tuple[str, ...]
    minimum_confidence: float = 0.35


def _normalize_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_text.strip().lower().replace("-", "_").replace(" ", "_")


WEIGH_IN_ALIASES = {
    "fecha": "recorded_at",
    "hora": "recorded_time",
    "recorded_at": "recorded_at",
    "measured_at": "recorded_at",
    "peso": "weight_kg",
    "peso_kg": "weight_kg",
    "weight": "weight_kg",
    "weight_kg": "weight_kg",
    "imc": "bmi",
    "bmi": "bmi",
    "grasa_corporal_pct": "body_fat_percent",
    "body_fat_percent": "body_fat_percent",
    "body_fat_pct": "body_fat_percent",
    "agua_pct": "water_percent",
    "agua_corporal_pct": "water_percent",
    "body_water_percent": "water_percent",
    "water_percentage": "water_percent",
    "water_pct": "water_percent",
    "water_percent": "water_percent",
    "proteinas_pct": "protein_percent",
    "protein_percent": "protein_percent",
    "metabolismo_basal_kcal": "bmr_kcal",
    "bmr": "bmr_kcal",
    "bmr_kcal": "bmr_kcal",
    "grasa_visceral": "visceral_fat",
    "visceral_fat": "visceral_fat",
    "musculo_kg": "muscle_mass_kg",
    "muscle_mass_kg": "muscle_mass_kg",
    "masa_osea_kg": "bone_mass_kg",
    "bone_mass_kg": "bone_mass_kg",
    "puntuacion_corporal": "body_score",
    "body_score": "body_score",
    "nota": "notes",
    "notas": "notes",
    "notes": "notes",
}

DAILY_NUTRITION_ALIASES = {
    "fecha": "date",
    "date": "date",
    "desayuno": "breakfast",
    "comida": "lunch",
    "cena": "dinner",
    "snacks": "snacks",
    "extras": "extras",
    "kcal": "calories",
    "calorias": "calories",
    "calories": "calories",
    "proteina_g": "protein_g",
    "protein_g": "protein_g",
    "grasa_g": "fat_g",
    "fat_g": "fat_g",
    "carbos_netos_g": "net_carbs_g",
    "net_carbs_g": "net_carbs_g",
    "carbohidratos": "carbs_g",
    "carbs_g": "carbs_g",
    "fibra_g": "fiber_g",
    "fiber_g": "fiber_g",
    "azucares_g": "sugars_g",
    "sugars_g": "sugars_g",
    "sodio_mg": "sodium_mg",
    "sodium_mg": "sodium_mg",
    "micronutrientes": "micronutrients",
    "micronutrients": "micronutrients",
    "totales": "totals",
    "totals": "totals",
    "meals": "meals",
    "items": "items",
}

FOOD_PRODUCT_ALIASES = {
    "alacena": "products",
    "pantry": "products",
    "productos": "products",
    "foods": "products",
    "ingredientes": "ingredients",
    "nombre": "name",
    "name": "name",
    "marca": "brand",
    "brand": "brand",
    "porcion_g": "serving_size_g",
    "serving_size": "serving_size_g",
    "serving_size_g": "serving_size_g",
    "kcal": "calories_per_100g",
    "calorias": "calories_per_100g",
    "calories": "calories_per_100g",
    "calories_per_100g": "calories_per_100g",
    "proteina": "protein_g_per_100g",
    "proteina_g": "protein_g_per_100g",
    "protein_g": "protein_g_per_100g",
    "protein_g_per_100g": "protein_g_per_100g",
    "grasa": "fat_g_per_100g",
    "grasa_g": "fat_g_per_100g",
    "fat_g": "fat_g_per_100g",
    "fat_g_per_100g": "fat_g_per_100g",
    "carbohidratos": "carbs_g_per_100g",
    "carbs_g": "carbs_g_per_100g",
    "carbs_g_per_100g": "carbs_g_per_100g",
    "carbos_netos_g": "net_carbs_g_per_100g",
    "net_carbs_g": "net_carbs_g_per_100g",
    "net_carbs_g_per_100g": "net_carbs_g_per_100g",
    "fibra": "fiber_g_per_100g",
    "fibra_g": "fiber_g_per_100g",
    "fiber_g": "fiber_g_per_100g",
    "fiber_g_per_100g": "fiber_g_per_100g",
    "sodio": "sodium_mg_per_100g",
    "sodio_mg": "sodium_mg_per_100g",
    "sodium_mg": "sodium_mg_per_100g",
    "sodium_mg_per_100g": "sodium_mg_per_100g",
}

RECIPE_ALIASES = {
    "receta": "name",
    "recipe": "name",
    "nombre": "name",
    "name": "name",
    "descripcion": "description",
    "description": "description",
    "ingredientes": "ingredients",
    "ingredients": "ingredients",
    "producto": "food_product_name",
    "producto_nombre": "food_product_name",
    "food_product_name": "food_product_name",
    "alimento": "food_product_name",
    "marca": "food_product_brand",
    "brand": "food_product_brand",
    "cantidad_g": "quantity_g",
    "quantity_g": "quantity_g",
    "preparacion": "instructions",
    "pasos": "instructions",
    "instructions": "instructions",
    "rendimiento": "yield_weight_g",
    "porciones": "servings",
    "servings": "servings",
    "peso_final": "yield_weight_g",
    "yield_weight_g": "yield_weight_g",
    "macros_por_receta": "total_macros",
    "macros_por_porcion": "per_serving_macros",
}

DAILY_ENERGY_ALIASES = {
    "fecha": "date",
    "date": "date",
    "calorias_totales": "total_calories",
    "total_calories": "total_calories",
    "calorias_activas": "active_calories",
    "active_calories": "active_calories",
    "calorias_reposo": "resting_calories",
    "resting_calories": "resting_calories",
    "pasos": "steps",
    "steps": "steps",
    "distancia": "distance_km",
    "distancia_km": "distance_km",
    "distance": "distance_km",
    "distance_km": "distance_km",
    "reloj": "source",
    "watch": "source",
    "gasto": "energy",
    "energy": "energy",
    "active_energy": "active_calories",
    "resting_energy": "resting_calories",
}

COMPLETED_WORKOUT_ALIASES = {
    "fecha": "performed_at",
    "performed_at": "performed_at",
    "rutina": "session_name",
    "sesion": "session_name",
    "session": "session_name",
    "session_name": "session_name",
    "ejercicios": "exercises",
    "exercises": "exercises",
    "sets": "sets",
    "series": "sets",
    "reps": "reps",
    "peso": "weight",
    "weight": "weight",
    "rir": "rir",
    "rpe": "rpe",
    "descanso": "rest_seconds",
    "rest_seconds": "rest_seconds",
    "duracion": "duration_seconds",
    "duration_seconds": "duration_seconds",
    "frecuencia_cardiaca": "average_heart_rate_bpm",
    "average_heart_rate_bpm": "average_heart_rate_bpm",
    "calorias": "calories_burned",
    "calories_burned": "calories_burned",
    "detalle_carga": "load_details",
    "load_details": "load_details",
}

TRAINING_PLAN_ALIASES = {
    "plan": "name",
    "rutina": "name",
    "programa": "name",
    "nombre": "name",
    "name": "name",
    "descripcion": "description",
    "description": "description",
    "semanas": "weeks",
    "weeks": "weeks",
    "semana": "week_number",
    "week_number": "week_number",
    "dias": "days",
    "days": "days",
    "dia": "day_number",
    "day_number": "day_number",
    "ejercicios": "exercises",
    "exercises": "exercises",
    "orden": "exercise_order",
    "exercise_order": "exercise_order",
    "series": "sets",
    "series_objetivo": "sets",
    "sets": "sets",
    "serie": "set_number",
    "set_number": "set_number",
    "reps": "reps",
    "repeticiones": "reps",
    "reps_objetivo": "reps",
    "reps_min": "reps_min",
    "reps_max": "reps_max",
    "rir_objetivo": "rir",
    "rpe_objetivo": "rpe",
    "duracion_segundos": "duration_seconds",
    "duration_seconds": "duration_seconds",
    "distancia_m": "distance_m",
    "distance_m": "distance_m",
    "objetivo": "target",
    "target": "target",
    "descanso": "rest_seconds",
    "descanso_objetivo": "rest_seconds",
    "rest_seconds": "rest_seconds",
    "notas": "notes",
    "notes": "notes",
    "version": "version",
    "bloques": "blocks",
}

MEDICAL_LAB_ALIASES = {
    "laboratorio": "lab_name",
    "lab_name": "lab_name",
    "fecha": "lab_date",
    "lab_date": "lab_date",
    "marcadores": "markers",
    "analitos": "markers",
    "markers": "markers",
    "valor": "value",
    "value": "value",
    "unidad": "unit",
    "unit": "unit",
    "rango_referencia": "reference_range",
    "reference_range": "reference_range",
    "estado": "status",
    "status": "status",
    "glucosa": "glucose",
    "insulina": "insulin",
    "hba1c": "hba1c",
    "colesterol": "total_cholesterol",
    "hdl": "hdl",
    "ldl": "ldl",
    "trigliceridos": "triglycerides",
    "tsh": "tsh",
    "vitamina_d": "vitamin_d",
    "b12": "b12",
    "ferritina": "ferritin",
}


DOMAIN_RULES: tuple[DomainRule, ...] = (
    DomainRule(
        target_type="weigh_in_batch",
        path_hints=("registros", "pesajes", "weigh_ins", "body_composition"),
        aliases=WEIGH_IN_ALIASES,
        signal_fields=("weight_kg", "body_fat_percent", "water_percent", "bmr_kcal"),
    ),
    DomainRule(
        target_type="daily_nutrition",
        path_hints=("nutrition", "nutricion", "meals", "comidas", "dias"),
        aliases=DAILY_NUTRITION_ALIASES,
        signal_fields=("calories", "protein_g", "net_carbs_g", "meals"),
    ),
    DomainRule(
        target_type="food_products",
        path_hints=("alacena", "pantry", "productos", "foods"),
        aliases=FOOD_PRODUCT_ALIASES,
        signal_fields=("name", "brand", "calories_per_100g", "protein_g_per_100g"),
    ),
    DomainRule(
        target_type="recipe",
        path_hints=("receta", "recipe"),
        aliases=RECIPE_ALIASES,
        signal_fields=("name", "ingredients", "quantity_g", "food_product_name"),
    ),
    DomainRule(
        target_type="recipe_bundle",
        path_hints=("recetas", "recipes", "recipe_bundle"),
        aliases=RECIPE_ALIASES,
        signal_fields=("name", "ingredients", "servings", "yield_weight_g"),
    ),
    DomainRule(
        target_type="daily_energy",
        path_hints=("energy", "energia", "gasto", "watch"),
        aliases=DAILY_ENERGY_ALIASES,
        signal_fields=("total_calories", "active_calories", "steps", "distance_km"),
    ),
    DomainRule(
        target_type="completed_workout",
        path_hints=("workouts", "entrenamientos", "sesiones", "sessions"),
        aliases=COMPLETED_WORKOUT_ALIASES,
        signal_fields=("exercises", "sets", "reps", "weight"),
    ),
    DomainRule(
        target_type="training_plan",
        path_hints=("plan", "rutina", "training_plan", "programa", "semanas"),
        aliases=TRAINING_PLAN_ALIASES,
        signal_fields=("weeks", "days", "exercises", "sets", "reps"),
    ),
    DomainRule(
        target_type="medical_lab",
        path_hints=("labs", "laboratorio", "medical", "marcadores"),
        aliases=MEDICAL_LAB_ALIASES,
        signal_fields=("markers", "value", "unit", "lab_date"),
    ),
)


class UniversalJsonImportAssistant:
    """Analyze JSON and produce a read-only assisted import preview."""

    def __init__(self, schema_detector: SchemaDetector | None = None) -> None:
        self.schema_detector = schema_detector or SchemaDetector()

    def analyze(
        self,
        payload: dict[str, Any],
        requested_type: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {
                "mode": "invalid",
                "requested_type": requested_type,
                "source_shape": "non_object_json",
                "candidate_domains": [],
                "preview": {
                    "candidate_count": 0,
                    "warnings": ["The uploaded JSON must be an object."],
                    "actions_available": ["cancel"],
                },
            }

        schema_detection = self.schema_detector.detect(payload, requested_type=requested_type)
        if schema_detection["mode"] == "standard":
            return {
                "mode": "standard",
                "detected_type": schema_detection["detected_type"],
                "schema_name": schema_detection["schema_name"],
                "confidence": 1.0,
                "requested_type": requested_type,
                "source_shape": "standard_internal_json",
                "candidate_domains": [],
                "preview": {
                    "candidate_count": 0,
                    "warnings": [
                        "This file already matches an official internal schema."
                    ],
                    "actions_available": ["import_with_standard_importer"],
                },
            }

        candidate_domains = self._candidate_domains(payload)

        return {
            "mode": "assistant_required",
            "detected_type": schema_detection["detected_type"],
            "requested_type": requested_type,
            "source_shape": self._source_shape(payload, candidate_domains),
            "schema_detection": schema_detection,
            "candidate_domains": candidate_domains,
            "preview": self._preview(payload, candidate_domains),
        }

    def _candidate_domains(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []

        for path, node in self._iter_nodes(payload):
            fields = self._field_names(node)
            if not fields:
                continue

            count = self._record_count(node)

            for rule in DOMAIN_RULES:
                candidate = self._score_candidate(
                    rule=rule,
                    path=path,
                    fields=fields,
                    count=count,
                )
                if candidate and candidate["confidence"] >= rule.minimum_confidence:
                    candidates.append(candidate)

        candidates.sort(
            key=lambda item: (
                item["confidence"],
                item["count"],
                item["target_type"],
            ),
            reverse=True,
        )
        return candidates[:12]

    def _score_candidate(
        self,
        *,
        rule: DomainRule,
        path: str,
        fields: list[str],
        count: int,
    ) -> dict[str, Any] | None:
        normalized_to_original = {
            _normalize_key(field): field
            for field in fields
        }

        suggested_mapping: dict[str, str] = {}
        aliases_used: list[dict[str, str]] = []
        canonical_hits: set[str] = set()

        for normalized, original in normalized_to_original.items():
            canonical = rule.aliases.get(normalized)
            if canonical is None:
                continue

            suggested_mapping[original] = canonical
            canonical_hits.add(canonical)

            if normalized != canonical:
                aliases_used.append(
                    {
                        "source_field": original,
                        "canonical_field": canonical,
                    }
                )

        signal_hits = {
            field for field in rule.signal_fields
            if field in canonical_hits
        }

        path_normalized = _normalize_key(path)
        path_hit = any(hint in path_normalized for hint in rule.path_hints)

        if not canonical_hits and not path_hit:
            return None

        field_score = min(0.78, len(canonical_hits) * 0.13)
        signal_score = min(0.12, len(signal_hits) * 0.04)
        path_score = 0.18 if path_hit else 0.0
        count_score = 0.04 if count > 1 else 0.0
        confidence = min(0.99, field_score + signal_score + path_score + count_score)

        ignored_fields = [
            field for field in fields
            if field not in suggested_mapping
        ]

        return {
            "target_type": rule.target_type,
            "path": path,
            "count": count,
            "confidence": round(confidence, 2),
            "detected_fields": fields,
            "suggested_mapping": suggested_mapping,
            "aliases_used": aliases_used,
            "ignored_fields": ignored_fields,
            "action_suggestion": "preview_required",
        }

    def _preview(
        self,
        payload: dict[str, Any],
        candidate_domains: list[dict[str, Any]],
    ) -> dict[str, Any]:
        warnings = []
        if not candidate_domains:
            warnings.append(
                "No importable domain was detected with enough confidence."
            )
        else:
            warnings.append(
                "Preview only. No database writes have been performed."
            )

        top_level_keys = list(payload.keys())
        candidate_paths = {candidate["path"] for candidate in candidate_domains}
        ignored_top_level_keys = [
            key for key in top_level_keys
            if key not in candidate_paths
        ]

        return {
            "candidate_count": len(candidate_domains),
            "top_level_keys": top_level_keys,
            "primary_candidate": candidate_domains[0] if candidate_domains else None,
            "ignored_top_level_keys": ignored_top_level_keys,
            "warnings": warnings,
            "actions_available": [
                "review_mapping",
                "generate_standard_json",
                "cancel",
            ] if candidate_domains else ["cancel"],
        }

    @staticmethod
    def _source_shape(
        payload: dict[str, Any],
        candidate_domains: list[dict[str, Any]],
    ) -> str:
        top_keys = {_normalize_key(key) for key in payload.keys()}

        if {
            "metadata",
            "perfil",
            "metas",
            "reglas_macros_actuales",
            "entrenamiento",
            "registros",
        } & top_keys and candidate_domains:
            return "consolidated_health_source"

        if len(candidate_domains) > 1:
            return "multi_domain_json_source"

        if candidate_domains:
            return f"{candidate_domains[0]['target_type']}_source"

        return "generic_json_object"

    def _iter_nodes(self, value: Any, path: str = "$") -> list[tuple[str, Any]]:
        nodes: list[tuple[str, Any]] = []

        if isinstance(value, dict):
            nodes.append((path, value))
            for key, child in value.items():
                child_path = key if path == "$" else f"{path}.{key}"
                if isinstance(child, (dict, list)):
                    nodes.extend(self._iter_nodes(child, child_path))

        elif isinstance(value, list):
            nodes.append((path, value))
            for index, child in enumerate(value[:5]):
                if isinstance(child, dict):
                    child_path = f"{path}[{index}]"
                    nodes.extend(self._iter_nodes(child, child_path))

        return nodes

    @staticmethod
    def _field_names(node: Any) -> list[str]:
        fields: set[str] = set()

        if isinstance(node, dict):
            fields.update(str(key) for key in node.keys())

        elif isinstance(node, list):
            for item in node[:10]:
                if isinstance(item, dict):
                    fields.update(str(key) for key in item.keys())

        return sorted(fields)

    @staticmethod
    def _record_count(node: Any) -> int:
        if isinstance(node, list):
            return len(node)
        return 1
