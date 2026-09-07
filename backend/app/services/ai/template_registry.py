from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
from typing import Callable, Mapping

from app.services.ai.capabilities.composer import AdaptivePromptComposer
from app.services.ai.capabilities.presets import PRESETS_BY_ID
from app.services.ai.capabilities.registry import AICapabilityRegistry
from app.services.ai.capabilities.types import AIIntentSpec, CapabilityError
from app.services.ai.tools import AIToolRegistry


PERIOD_LABELS = {
    "today": "hoy",
    "7d": "los últimos 7 días",
    "30d": "los últimos 30 días",
    "90d": "los últimos 90 días",
}
PERIOD_ORDER = tuple(PERIOD_LABELS)
MODES = {"analysis", "comparison", "action"}


class AITemplateError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status = status


@dataclass(frozen=True)
class AITemplateCategory:
    id: str
    label: str
    token: str
    sort_order: int


@dataclass(frozen=True)
class AITemplatePromptContext:
    period: str

    @property
    def period_label(self) -> str:
        return PERIOD_LABELS[self.period]


PromptBuilder = Callable[[AITemplatePromptContext], str]


@dataclass(frozen=True)
class AITemplate:
    id: str
    category: str
    title: str
    short_description: str
    mode: str
    token: str
    default_period: str
    allowed_periods: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    suggested_followups: tuple[str, ...]
    prompt_builder: PromptBuilder
    input_schema: Mapping | None
    sort_order: int

    def build_prompt(self, period: str | None = None) -> str:
        selected_period = period or self.default_period
        if selected_period not in self.allowed_periods:
            raise AITemplateError(
                "invalid_template_period",
                "El periodo no está disponible para esta plantilla.",
            )
        context = AITemplatePromptContext(selected_period)
        legacy_prompt = self.prompt_builder(context).strip()
        if self.mode == "action":
            objective = legacy_prompt.split(".", 1)[0]
        else:
            objective = legacy_prompt.split(f" para {context.period_label}", 1)[0]
        prompt = AdaptivePromptComposer(_default_capability_registry()).compose(
            self.intent_spec(selected_period),
            objective=objective,
        ).strip()
        if not prompt:
            raise AITemplateError(
                "invalid_template_prompt",
                "La plantilla no pudo preparar un mensaje.",
                500,
            )
        return prompt

    def intent_spec(self, period: str | None = None) -> AIIntentSpec:
        selected_period = period or self.default_period
        preset = PRESETS_BY_ID.get(self.id)
        if preset is None:
            raise AITemplateError(
                "template_without_preset",
                "La plantilla AI no tiene un preset adaptativo.",
                500,
            )
        spec = preset.spec(selected_period)
        try:
            _default_capability_registry().resolve(spec)
        except CapabilityError as error:
            raise AITemplateError(error.code, error.safe_message, error.status) from error
        return spec


@dataclass(frozen=True)
class AITemplateAvailability:
    template: AITemplate
    available: bool
    missing_capabilities: tuple[str, ...]

    @property
    def unavailable_reason(self) -> str | None:
        if not self.missing_capabilities:
            return None
        return "Esta vista necesita una lectura que Health Tracker aún no expone a AI."


CATEGORIES = (
    AITemplateCategory("summary", "Resumen", "RE", 10),
    AITemplateCategory("energy", "Energía", "EN", 20),
    AITemplateCategory("nutrition", "Nutrición", "NU", 30),
    AITemplateCategory("body", "Cuerpo", "CU", 40),
    AITemplateCategory("activity", "Actividad", "AC", 50),
    AITemplateCategory("training", "Entrenamiento", "TR", 60),
    AITemplateCategory("goals", "Metas", "ME", 70),
    AITemplateCategory("data", "Datos", "DA", 80),
    AITemplateCategory("log", "Registrar", "RG", 90),
)


FOOD_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "date": {"type": "string", "format": "date"},
        "meal_type": {
            "type": "string",
            "enum": ["breakfast", "lunch", "dinner", "snack", "extra", "other"],
        },
        "meal_name": {"type": "string"},
        "items": {"type": "array"},
    },
    "additionalProperties": False,
}

BODY_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "weight": {"type": ["string", "number"]},
        "unit": {"type": "string", "enum": ["kg", "lb"]},
        "recorded_at": {"type": "string", "format": "date-time"},
        "body_fat_percent": {"type": ["string", "number"]},
        "muscle_mass_kg": {"type": ["string", "number"]},
        "water_percent": {"type": ["string", "number"]},
        "visceral_fat": {"type": ["string", "number"]},
        "bmr_kcal": {"type": ["string", "number"]},
        "bmi": {"type": ["string", "number"]},
        "notes": {"type": "string"},
    },
    "additionalProperties": False,
}


def _analysis_prompt(
    objective: str,
    tools: tuple[str, ...],
    *,
    comparison: bool = False,
    constraints: tuple[str, ...] = (),
) -> PromptBuilder:
    tool_text = ", ".join(tools)

    def build(context: AITemplatePromptContext) -> str:
        comparison_text = (
            " Compara con el periodo inmediatamente anterior de la misma duración."
            if comparison
            else ""
        )
        constraint_text = "".join(f"\n- {item}" for item in constraints)
        return (
            f"{objective} para {context.period_label}.{comparison_text}\n"
            f"Usa únicamente las herramientas autorizadas de Health Tracker; las "
            f"capacidades relevantes son: {tool_text}. No inventes valores ni conviertas "
            "ausencias en cero.\n"
            "Responde en español con: resumen, hallazgos, cobertura de datos y fuentes "
            "cuando corresponda. Distingue datos registrados, cálculos de Health Tracker "
            "e interpretación AI. Si no hay datos suficientes, explícalo de forma útil. "
            "No diagnostiques ni muestres razonamiento interno."
            f"{constraint_text}"
        )

    return build


def _action_prompt(
    objective: str,
    draft_type: str,
    fields: str,
    *,
    meal_type: str | None = None,
    correction: bool = False,
) -> PromptBuilder:
    def build(context: AITemplatePromptContext) -> str:
        meal_text = f" La comida prevista es {meal_type}." if meal_type else ""
        correction_text = (
            " Consulta primero la última medición corporal owner-only y prepara una "
            "corrección de ese registro mediante el flujo oficial de patch."
            if correction
            else ""
        )
        return (
            f"{objective}.{meal_text}{correction_text}\n"
            f"Pídeme solo los datos que falten entre estos campos soportados: {fields}. "
            f"Cuando haya información suficiente, prepara un borrador {draft_type} "
            "editable. No estimes nutrientes ni métricas corporales ausentes. Nunca "
            "guardes nada automáticamente: muestra el preview y espera mi confirmación "
            "explícita. Indica la procedencia y cualquier campo faltante, ambiguo o no "
            "soportado. No diagnostiques ni muestres razonamiento interno."
        )

    return build


def _template(
    template_id: str,
    category: str,
    title: str,
    description: str,
    mode: str,
    token: str,
    default_period: str,
    allowed_periods: tuple[str, ...],
    capabilities: tuple[str, ...],
    followups: tuple[str, ...],
    builder: PromptBuilder,
    order: int,
    input_schema: Mapping | None = None,
) -> AITemplate:
    return AITemplate(
        template_id,
        category,
        title,
        description,
        mode,
        token,
        default_period,
        allowed_periods,
        capabilities,
        followups,
        builder,
        input_schema,
        order,
    )


_P = ("7d", "30d", "90d")
_PT = ("today", "7d", "30d", "90d")
_FOOD_FIELDS = (
    "calorías, proteína, grasa, carbohidratos netos y totales, fibra, azúcar, "
    "sodio, cantidad, unidad, fecha, tipo y nombre de comida y notas"
)
_BODY_FIELDS = (
    "peso y unidad, grasa corporal, masa muscular, agua corporal, grasa visceral, "
    "BMR, IMC, fecha, hora y notas"
)


TEMPLATES = (
    _template("today-summary", "summary", "Resumen de hoy", "Lectura breve del estado de hoy.", "analysis", "HOY", "today", ("today",), ("tool:get_dashboard_summary",), ("data-quality", "log-food", "log-weight"), _analysis_prompt("Resume mi estado de hoy", ("get_dashboard_summary",)), 10),
    _template("weekly-summary", "summary", "Resumen semanal", "Qué cambió durante la última semana.", "analysis", "7D", "7d", ("7d",), ("tool:get_dashboard_summary",), ("compare-periods", "energy-balance", "training-summary"), _analysis_prompt("Resume mi semana", ("get_dashboard_summary",)), 20),
    _template("monthly-summary", "summary", "Resumen mensual", "Panorama de los últimos treinta días.", "analysis", "30D", "30d", ("30d",), ("tool:get_dashboard_summary",), ("compare-periods", "weight-trend", "data-quality"), _analysis_prompt("Resume mi mes", ("get_dashboard_summary",)), 30),
    _template("period-summary", "summary", "Resumen por periodo", "Resumen combinado para 7, 30 o 90 días.", "analysis", "PER", "30d", _P, ("tool:get_dashboard_summary",), ("compare-periods", "energy-balance", "data-quality"), _analysis_prompt("Resume mi periodo", ("get_dashboard_summary",)), 40),
    _template("compare-periods", "summary", "Comparar con anterior", "Compara contra el periodo anterior equivalente.", "comparison", "VS", "30d", _P, ("tool:get_dashboard_summary",), ("data-quality", "energy-balance", "weight-trend"), _analysis_prompt("Compara mi evolución general", ("get_dashboard_summary",), comparison=True), 50),

    _template("energy-balance", "energy", "Ver solo balance", "Consumo, gasto, déficit y superávit.", "analysis", "BAL", "30d", _PT, ("tool:get_dashboard_summary",), ("deficit-focus", "intake-trend", "expenditure-trend"), _analysis_prompt("Analiza mi balance energético", ("get_dashboard_summary",), constraints=("Separa déficit, superávit y días incompletos.",)), 110),
    _template("deficit-focus", "energy", "Enfoque en déficit", "Identifica únicamente días con déficit comparable.", "analysis", "DEF", "30d", _P, ("tool:get_dashboard_summary",), ("energy-balance", "nutrition-overview", "data-quality"), _analysis_prompt("Analiza solo mis días con déficit energético", ("get_dashboard_summary",), constraints=("No trates días incompletos como déficit.",)), 120),
    _template("expenditure-trend", "energy", "Tendencia de gasto", "Revisa la evolución del gasto registrado.", "analysis", "GAS", "30d", _P, ("tool:get_dashboard_summary",), ("activity-overview", "training-summary", "data-quality"), _analysis_prompt("Analiza la tendencia de mi gasto energético", ("get_dashboard_summary",)), 130),
    _template("intake-trend", "energy", "Tendencia de consumo", "Revisa la evolución de la ingesta registrada.", "analysis", "CON", "30d", _P, ("tool:get_dashboard_summary", "tool:get_nutrition_summary"), ("nutrition-overview", "protein-consistency", "data-quality"), _analysis_prompt("Analiza la tendencia de mi consumo energético", ("get_dashboard_summary", "get_nutrition_summary")), 140),

    _template("nutrition-overview", "nutrition", "Panorama nutricional", "Macros, energía y cobertura nutricional.", "analysis", "NUT", "30d", _PT, ("tool:get_nutrition_summary",), ("protein-consistency", "macro-goals", "nutrition-data-quality"), _analysis_prompt("Analiza mi nutrición", ("get_nutrition_summary",)), 210),
    _template("protein-consistency", "nutrition", "Analizar proteína", "Frecuencia y cobertura del registro de proteína.", "analysis", "PRO", "30d", _P, ("tool:get_nutrition_summary",), ("nutrition-overview", "macro-goals", "nutrition-data-quality"), _analysis_prompt("Analiza la consistencia de mi proteína", ("get_nutrition_summary",)), 220),
    _template("macro-goals", "nutrition", "Macros frente a metas", "Contrasta macros con metas ya configuradas.", "comparison", "MAC", "30d", _P, ("tool:get_nutrition_summary", "tool:get_goals_summary"), ("goals-progress", "protein-consistency", "nutrition-data-quality"), _analysis_prompt("Compara mis macros con mis metas configuradas", ("get_nutrition_summary", "get_goals_summary"), constraints=("No propongas ni inventes metas nuevas.",)), 230),
    _template("nutrition-data-quality", "nutrition", "Calidad nutricional", "Días cubiertos y campos ausentes.", "analysis", "CAL", "30d", _P, ("tool:get_nutrition_summary", "tool:get_data_sources_summary"), ("nutrition-overview", "data-sources", "log-food"), _analysis_prompt("Evalúa la calidad y cobertura de mis datos de nutrición", ("get_nutrition_summary", "get_data_sources_summary")), 240),
    _template("food-patterns", "nutrition", "Patrones de alimentos", "Patrones sobre elementos de comida registrados.", "analysis", "PAT", "30d", _P, ("tool:get_food_patterns",), (), _analysis_prompt("Analiza patrones de los alimentos que registré", ("get_food_patterns",)), 250),

    _template("weight-trend", "body", "Ver tendencia de peso", "Cambios, promedios y cobertura del peso.", "analysis", "PES", "30d", _P, ("tool:get_weight_trend",), ("body-composition", "compare-body-period", "data-quality"), _analysis_prompt("Analiza mi tendencia de peso", ("get_weight_trend",)), 310),
    _template("body-composition", "body", "Composición corporal", "Evolución de las métricas corporales disponibles.", "analysis", "COM", "30d", _PT, ("tool:get_weight_trend", "tool:get_latest_body_measurement"), ("weight-trend", "latest-body-measurement", "correct-body-measurement"), _analysis_prompt("Analiza mi peso y composición corporal disponible", ("get_weight_trend", "get_latest_body_measurement")), 320),
    _template("compare-body-period", "body", "Comparar cuerpo por periodo", "Contrasta el periodo corporal con el anterior.", "comparison", "CVS", "30d", _P, ("tool:get_weight_trend",), ("weight-trend", "body-composition", "data-quality"), _analysis_prompt("Compara mi evolución corporal", ("get_weight_trend",), comparison=True), 330),
    _template("latest-body-measurement", "body", "Última medición corporal", "Muestra la última medición disponible y su fuente.", "analysis", "ULT", "today", ("today",), ("tool:get_latest_body_measurement",), ("body-composition", "weight-trend", "correct-body-measurement"), _analysis_prompt("Revisa mi última medición corporal disponible", ("get_latest_body_measurement",)), 340),

    _template("activity-overview", "activity", "Panorama de actividad", "Actividad reciente registrada o importada.", "analysis", "ACT", "30d", _P, ("tool:get_activity_summary",), ("steps-progress", "activity-consistency", "data-sources"), _analysis_prompt("Analiza mi actividad reciente", ("get_activity_summary",)), 410),
    _template("steps-progress", "activity", "Progreso de pasos", "Totales, promedios y cobertura de pasos.", "analysis", "PAS", "30d", _PT, ("tool:get_steps_summary",), ("activity-consistency", "active-days", "data-sources"), _analysis_prompt("Analiza mi progreso de pasos", ("get_steps_summary",)), 420),
    _template("activity-consistency", "activity", "Consistencia de actividad", "Regularidad de actividad y pasos.", "analysis", "REG", "30d", _P, ("tool:get_activity_summary", "tool:get_steps_summary"), ("active-days", "steps-progress", "data-quality"), _analysis_prompt("Analiza la consistencia de mi actividad", ("get_activity_summary", "get_steps_summary")), 430),
    _template("active-days", "activity", "Días activos", "Distingue días con datos de actividad.", "analysis", "DIA", "30d", _P, ("tool:get_steps_summary",), ("activity-overview", "steps-progress", "data-quality"), _analysis_prompt("Analiza mis días activos usando los datos disponibles", ("get_steps_summary",), constraints=("No clasifiques como inactivo un día sin datos.",)), 440),

    _template("training-summary", "training", "Resumen de entrenamiento", "Sesiones, duración y cargas comparables.", "analysis", "ENT", "30d", _PT, ("tool:get_training_summary",), ("training-consistency", "training-volume", "training-history"), _analysis_prompt("Resume mi entrenamiento", ("get_training_summary",)), 510),
    _template("training-consistency", "training", "Consistencia de entrenamiento", "Frecuencia y cobertura de sesiones.", "analysis", "CON", "30d", _P, ("tool:get_training_summary",), ("training-summary", "training-history", "data-quality"), _analysis_prompt("Analiza la consistencia de mi entrenamiento", ("get_training_summary",)), 520),
    _template("training-volume", "training", "Volumen de entrenamiento", "Volumen únicamente cuando las cargas sean comparables.", "comparison", "VOL", "30d", _P, ("tool:get_training_summary",), ("training-summary", "compare-periods", "training-history"), _analysis_prompt("Analiza mi volumen de entrenamiento", ("get_training_summary",), comparison=True, constraints=("Compara volumen solo entre cargas compatibles; declara lo no comparable.",)), 530),
    _template("training-history", "training", "Historial de entrenamiento", "Revisa sesiones recientes sin inventar progreso.", "analysis", "HIS", "30d", ("30d", "90d"), ("tool:get_training_history",), ("training-summary", "training-consistency", "data-sources"), _analysis_prompt("Resume mi historial reciente de entrenamiento", ("get_training_history",)), 540),
    _template("exercise-progress", "training", "Progreso por ejercicio", "Evolución específica de un ejercicio comparable.", "analysis", "EJE", "30d", _P, ("tool:get_exercise_progress",), (), _analysis_prompt("Analiza el progreso de un ejercicio específico", ("get_exercise_progress",)), 550),

    _template("goals-overview", "goals", "Panorama de metas", "Estado de metas ya configuradas.", "analysis", "MET", "30d", _P, ("tool:get_goals_summary",), ("goals-progress", "goal-gaps", "data-quality"), _analysis_prompt("Resume mis metas configuradas", ("get_goals_summary",)), 610),
    _template("goals-progress", "goals", "Progreso de metas", "Adherencia descriptiva por periodo.", "analysis", "PRO", "30d", _P, ("tool:get_goals_summary",), ("goals-overview", "goal-gaps", "compare-periods"), _analysis_prompt("Analiza el progreso de mis metas configuradas", ("get_goals_summary",)), 620),
    _template("goal-gaps", "goals", "Brechas de metas", "Dónde faltan datos o adherencia para metas existentes.", "analysis", "BRE", "30d", _P, ("tool:get_goals_summary",), ("goals-progress", "data-quality", "data-sources"), _analysis_prompt("Identifica brechas en mis metas configuradas", ("get_goals_summary",), constraints=("Usa únicamente metas existentes; no crees objetivos nuevos.",)), 630),

    _template("data-quality", "data", "Revisar días faltantes", "Cobertura, ausencias y comparabilidad.", "analysis", "CAL", "30d", _P, ("tool:get_dashboard_summary", "tool:get_data_sources_summary"), ("data-sources", "what-do-you-know", "period-summary"), _analysis_prompt("Evalúa la calidad de mis datos", ("get_dashboard_summary", "get_data_sources_summary")), 710),
    _template("data-sources", "data", "Explicar fuentes", "Procedencia por dominio sin payloads crudos.", "analysis", "FUE", "30d", _P, ("tool:get_data_sources_summary",), ("what-do-you-know", "data-quality", "steps-progress"), _analysis_prompt("Explica de dónde vienen mis datos, incluidos los pasos", ("get_data_sources_summary",)), 720),
    _template("what-do-you-know", "data", "Qué sabes de mis datos", "Alcance real de las lecturas disponibles.", "analysis", "SAB", "30d", _P, ("tool:get_data_sources_summary",), ("data-sources", "data-quality", "period-summary"), _analysis_prompt("Explica qué datos conoces y de qué fuentes provienen mis pasos y otros dominios", ("get_data_sources_summary",)), 730),

    _template("log-food", "log", "Registrar comida", "Prepara un borrador editable de comida.", "action", "COM", "today", ("today",), ("draft:food_entry",), ("nutrition-overview", "nutrition-data-quality"), _action_prompt("Quiero registrar una comida", "food_entry", _FOOD_FIELDS), 810, FOOD_INPUT_SCHEMA),
    _template("quick-breakfast", "log", "Desayuno rápido", "Inicia un borrador de desayuno.", "action", "DES", "today", ("today",), ("draft:food_entry",), ("nutrition-overview",), _action_prompt("Quiero registrar rápidamente lo que desayuné", "food_entry", _FOOD_FIELDS, meal_type="desayuno"), 820, FOOD_INPUT_SCHEMA),
    _template("quick-lunch", "log", "Comida rápida", "Inicia un borrador de comida o almuerzo.", "action", "ALM", "today", ("today",), ("draft:food_entry",), ("nutrition-overview",), _action_prompt("Quiero registrar rápidamente lo que comí", "food_entry", _FOOD_FIELDS, meal_type="comida"), 830, FOOD_INPUT_SCHEMA),
    _template("quick-dinner", "log", "Cena rápida", "Inicia un borrador de cena.", "action", "CEN", "today", ("today",), ("draft:food_entry",), ("nutrition-overview",), _action_prompt("Quiero registrar rápidamente lo que cené", "food_entry", _FOOD_FIELDS, meal_type="cena"), 840, FOOD_INPUT_SCHEMA),
    _template("quick-snack", "log", "Snack rápido", "Inicia un borrador de snack.", "action", "SNK", "today", ("today",), ("draft:food_entry",), ("nutrition-overview",), _action_prompt("Quiero registrar rápidamente un snack", "food_entry", _FOOD_FIELDS, meal_type="snack"), 850, FOOD_INPUT_SCHEMA),
    _template("log-weight", "log", "Registrar peso", "Prepara un borrador de peso y fecha.", "action", "PES", "today", ("today",), ("draft:body_measurement",), ("weight-trend", "body-composition"), _action_prompt("Quiero registrar mi peso", "body_measurement", _BODY_FIELDS), 860, BODY_INPUT_SCHEMA),
    _template("log-body-composition", "log", "Registrar composición", "Prepara peso y métricas corporales soportadas.", "action", "COR", "today", ("today",), ("draft:body_measurement",), ("body-composition", "latest-body-measurement"), _action_prompt("Quiero registrar una medición de composición corporal", "body_measurement", _BODY_FIELDS), 870, BODY_INPUT_SCHEMA),
    _template("correct-body-measurement", "log", "Corregir medición corporal", "Corrige la última medición mediante preview y patch oficial.", "action", "EDI", "today", ("today",), ("draft:body_measurement", "action:body.measurement.correct"), ("latest-body-measurement", "body-composition"), _action_prompt("Quiero corregir mi última medición corporal", "body_measurement", _BODY_FIELDS, correction=True), 880, BODY_INPUT_SCHEMA),
)


@lru_cache(maxsize=1)
def _default_capability_registry() -> AICapabilityRegistry:
    return AICapabilityRegistry()


class AITemplateRegistry:
    def __init__(
        self,
        *,
        tool_registry: AIToolRegistry | None = None,
        extra_capabilities: set[str] | None = None,
    ):
        tools = tool_registry or AIToolRegistry()
        capability_registry = AICapabilityRegistry(tool_registry=tools)
        capabilities = set(capability_registry.capability_tokens)
        if extra_capabilities:
            capabilities.update(extra_capabilities)
        self._capabilities = frozenset(capabilities)
        self._templates = tuple(sorted(TEMPLATES, key=lambda item: item.sort_order))
        self._by_id = {item.id: item for item in self._templates}
        self.capability_registry = capability_registry
        self._validate()

    @property
    def categories(self) -> tuple[AITemplateCategory, ...]:
        return CATEGORIES

    @property
    def capabilities(self) -> frozenset[str]:
        return self._capabilities

    @property
    def templates(self) -> tuple[AITemplateAvailability, ...]:
        return tuple(self.availability(item) for item in self._templates)

    def availability(self, template: AITemplate) -> AITemplateAvailability:
        missing = tuple(
            capability
            for capability in template.required_capabilities
            if capability not in self._capabilities
        )
        return AITemplateAvailability(template, not missing, missing)

    def get(self, template_id: str) -> AITemplateAvailability:
        clean_id = str(template_id or "").strip()
        template = self._by_id.get(clean_id)
        if template is None:
            raise AITemplateError(
                "template_not_found", "La plantilla AI solicitada no existe.", 404
            )
        return self.availability(template)

    def prepare(self, template_id: str, period: str | None = None) -> tuple[AITemplate, str, str]:
        availability = self.get(template_id)
        if not availability.available:
            raise AITemplateError(
                "template_unavailable",
                availability.unavailable_reason or "La plantilla no está disponible.",
                409,
            )
        template = availability.template
        selected_period = str(period or template.default_period).strip()
        prompt = template.build_prompt(selected_period)
        return template, selected_period, prompt

    def intent_spec(self, template_id: str, period: str | None = None) -> AIIntentSpec:
        template, selected_period, _prompt = self.prepare(template_id, period)
        return template.intent_spec(selected_period)

    def _validate(self) -> None:
        category_ids = {item.id for item in CATEGORIES}
        if len(self._by_id) != len(self._templates):
            raise RuntimeError("AI template ids must be unique.")
        if set(self._by_id) != set(PRESETS_BY_ID):
            raise RuntimeError("Every legacy AI template must map to exactly one preset.")
        if tuple(item.sort_order for item in self._templates) != tuple(
            sorted(item.sort_order for item in self._templates)
        ):
            raise RuntimeError("AI templates must have stable sort order.")
        for item in self._templates:
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", item.id):
                raise RuntimeError(f"Invalid AI template id: {item.id}")
            if item.category not in category_ids:
                raise RuntimeError(f"Invalid AI template category: {item.category}")
            if item.mode not in MODES:
                raise RuntimeError(f"Invalid AI template mode: {item.mode}")
            if item.default_period not in item.allowed_periods:
                raise RuntimeError(f"Invalid default period for AI template: {item.id}")
            if not item.allowed_periods or any(
                period not in PERIOD_ORDER for period in item.allowed_periods
            ):
                raise RuntimeError(f"Invalid allowed periods for AI template: {item.id}")
            if any(value not in self._by_id for value in item.suggested_followups):
                raise RuntimeError(f"Invalid follow-up in AI template: {item.id}")


__all__ = [
    "AITemplate",
    "AITemplateAvailability",
    "AITemplateCategory",
    "AITemplateError",
    "AITemplateRegistry",
    "CATEGORIES",
    "PERIOD_LABELS",
    "TEMPLATES",
]
