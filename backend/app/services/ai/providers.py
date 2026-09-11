from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import re
import socket
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
import uuid

from flask import current_app

from app.services.ai.types import (
    AIProviderCapabilities,
    AIProviderActionDefinition,
    AIProviderDraft,
    AIProviderPlanProposal,
    AIProviderPlanStepProposal,
    AIProviderRequest,
    AIProviderResponse,
    AIProviderToolCall,
    AIUsage,
)


class AIProviderError(RuntimeError):
    """Safe provider boundary error; never include credentials in its message."""

    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status = status


class AIProvider(ABC):
    name = "unknown"
    capabilities = AIProviderCapabilities()

    @abstractmethod
    def respond(self, request: AIProviderRequest) -> AIProviderResponse:
        """Return text, allowlisted tool requests, or structured drafts."""


def _normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def _last_user_text(request: AIProviderRequest) -> str:
    for message in reversed(request.messages):
        if message.role == "user":
            return message.content
    return ""


def _prior_topic(request: AIProviderRequest) -> str:
    user_messages = [
        _normalized(message.content)
        for message in request.messages
        if message.role == "user"
    ]
    for text in reversed(user_messages[:-1]):
        if "peso" in text:
            return "weight"
        if "proteina" in text or "nutric" in text or "comida" in text:
            return "nutrition"
        if "pasos" in text:
            return "steps"
        if "entren" in text or "sesion" in text:
            return "training"
        if "actividad" in text:
            return "activity"
        if "objetiv" in text or "meta" in text:
            return "goals"
    return "dashboard"


def _explicit_preset(text: str) -> str | None:
    if "hoy" in text or "today" in text:
        return "today"
    if "90" in text:
        return "90d"
    if "semana" in text:
        return "7d"
    if "mes pasado" in text or "mes anterior" in text:
        return "previous-month"
    if "este mes" in text or "mes" in text:
        return "this-month"
    return None


def _prior_preset(request: AIProviderRequest) -> str:
    user_messages = [
        _normalized(message.content)
        for message in request.messages
        if message.role == "user"
    ]
    for text in reversed(user_messages[:-1]):
        preset = _explicit_preset(text)
        if preset is not None:
            return preset
    return "30d"


def _number(value) -> str:
    if value is None:
        return "sin datos"
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


class FakeAIProvider(AIProvider):
    """Deterministic QA/demo provider. It performs no network calls."""

    name = "fake"
    capabilities = AIProviderCapabilities(
        supports_tools=True,
        supports_structured_output=True,
        supports_usage=True,
        remote=False,
    )

    def respond(self, request: AIProviderRequest) -> AIProviderResponse:
        if request.tool_results:
            summary = self._summarize(request)
            action_plan = self._proposal_after_goal_read(request) or self._action_plan(
                request
            ) or self._single_selected_action_plan(request)
            if action_plan is not None:
                return AIProviderResponse(
                    content=summary.content,
                    plans=(action_plan,),
                    usage=summary.usage,
                )
            return summary

        original = _last_user_text(request)
        text = _normalized(original)
        action_plan = self._action_plan(request)
        if action_plan is not None:
            return AIProviderResponse(
                content=(
                    "Preparé un plan editable. No se guardó ningún cambio; revisa y "
                    "confirma cada paso o usa Confirmar todo."
                ),
                plans=(action_plan,),
                usage=self._usage(request, original),
            )
        selected_plan = self._single_selected_action_plan(request)
        if selected_plan is not None:
            return AIProviderResponse(
                content=(
                    "Preparé un plan editable con la información disponible. "
                    "Completa cualquier dato faltante antes de confirmarlo."
                ),
                plans=(selected_plan,),
                usage=self._usage(request, original),
            )
        allowed_drafts = request.draft_types
        draft = (
            self._body_measurement_draft(request)
            if allowed_drafts is None or "body_measurement" in allowed_drafts
            else None
        )
        if draft is not None:
            return AIProviderResponse(
                content=(
                    "Preparé un borrador de medición corporal. Revísalo: todavía "
                    "no se guardó ningún dato. Confírmalo explícitamente para aplicar "
                    "la medición."
                ),
                drafts=(draft,),
                usage=self._usage(request, original),
            )

        food_draft = (
            self._food_entry_draft(request)
            if allowed_drafts is None or "food_entry" in allowed_drafts
            else None
        )
        if food_draft is not None:
            return AIProviderResponse(
                content=(
                    "Preparé un borrador de comida a partir de tu texto. Revisa "
                    "cantidades y unidades antes de confirmarlo; no estimé nutrientes "
                    "que no estaban disponibles."
                ),
                drafts=(food_draft,),
                usage=self._usage(request, original),
            )
        if self._food_nutrient_fields(original):
            return AIProviderResponse(
                content=(
                    "Conservé los nutrientes que indicaste. ¿De qué fecha y comida "
                    "(desayuno, comida, cena o snack) fue?"
                ),
                usage=self._usage(request, original),
            )

        if any(
            term in text
            for term in (
                " sql",
                "base de datos",
                "filesystem",
                "archivo del servidor",
                "shell",
                "powershell",
                "curl ",
                "http://",
                "https://",
            )
        ):
            return AIProviderResponse(
                content=(
                    "No tengo acceso a SQL, archivos, shell ni URLs arbitrarias. "
                    "Solo puedo consultar las herramientas de salud de solo lectura "
                    "autorizadas por Health Tracker."
                ),
                usage=self._usage(request, original),
            )

        allowed_tool_names = tuple(item.name for item in request.tools)
        if len(allowed_tool_names) == 1:
            name = allowed_tool_names[0]
            comparison = any(
                term in text
                for term in ("comparado", "compara", "anterior", "mas o menos")
            )
            arguments = self._arguments_for_allowed_tool(
                name,
                self._preset(text),
                comparison,
                original,
            )
            return AIProviderResponse(
                tool_calls=(
                    AIProviderToolCall(
                        call_id=str(uuid.uuid4()), name=name, arguments=arguments
                    ),
                ),
                usage=self._usage(request, original),
            )

        comparison = any(
            term in text
            for term in ("comparado", "compara", "anterior", "mas o menos")
        )
        has_prior_user_message = len(
            [message for message in request.messages if message.role == "user"]
        ) > 1
        if comparison and has_prior_user_message:
            topic = _prior_topic(request)
        elif "pasos" in text and any(term in text for term in ("de donde", "fuente", "origen")):
            topic = "sources"
        elif "peso" in text or "pesaj" in text:
            topic = "weight"
        elif "proteina" in text or "nutric" in text:
            topic = "nutrition"
        elif "pasos" in text:
            topic = "steps"
        elif "entren" in text or "sesion" in text:
            topic = "training"
        elif "actividad" in text:
            topic = "activity"
        elif "objetiv" in text or "meta" in text:
            topic = "goals"
        else:
            topic = "dashboard"

        preset = self._preset(text)
        if comparison and has_prior_user_message and _explicit_preset(text) is None:
            preset = _prior_preset(request)
        elif "mas o menos" in text and preset == "previous-month":
            # This asks for the current month against the previous period.
            preset = "this-month"
        if topic == "weight" and self._is_point_body_question(text):
            name = "get_latest_body_measurement"
            arguments = self._point_body_arguments(text)
        else:
            name, arguments = self._tool_for(topic, preset, comparison)
        if name not in allowed_tool_names:
            if not allowed_tool_names:
                return AIProviderResponse(
                    content="No hace falta consultar datos adicionales para preparar esta respuesta.",
                    usage=self._usage(request, original),
                )
            name = allowed_tool_names[0]
            arguments = self._arguments_for_allowed_tool(
                name, preset, comparison, original
            )
        return AIProviderResponse(
            tool_calls=(
                AIProviderToolCall(
                    call_id=str(uuid.uuid4()), name=name, arguments=arguments
                ),
            ),
            usage=self._usage(request, original),
        )

    @classmethod
    def _action_plan(cls, request: AIProviderRequest) -> AIProviderPlanProposal | None:
        allowed = {item.action_capability_id for item in request.actions}
        if not allowed:
            return None
        original = _last_user_text(request)
        text = _normalized(original)
        steps = []

        body = cls._body_measurement_draft(request)
        if body is not None:
            candidates = [
                item
                for item in ("body.measurement.create", "body.measurement.correct")
                if item in allowed
            ]
            if candidates:
                action_id = (
                    "body.measurement.correct"
                    if "body.measurement.correct" in candidates
                    and any(term in text for term in ("corrige", "correccion", "era ", "quise decir"))
                    else candidates[0]
                )
                steps.append(
                    AIProviderPlanStepProposal(
                        f"step_{len(steps) + 1}", action_id, body.payload
                    )
                )

        food = cls._food_entry_draft(request)
        if food is not None and "nutrition.food.create" in allowed:
            steps.append(
                AIProviderPlanStepProposal(
                    f"step_{len(steps) + 1}", "nutrition.food.create", food.payload
                )
            )

        goal_match = re.search(
            r"(?:meta|objetivo)(?:\s+de)?\s+(pasos|prote[ií]na|calor[ií]as|entrenamientos?)"
            r"[^0-9]{0,40}(\d+(?:[.,]\d+)?)",
            original,
            flags=re.IGNORECASE,
        )
        if goal_match and any(
            term in text
            for term in ("cambia", "cambiar", "ajusta", "ajustar", "sera", "establece", "crea", "crear", "nueva")
        ):
            goal_types = {
                "pasos": "daily_steps",
                "proteina": "nutrition_protein",
                "calorias": "nutrition_calories",
                "entrenamiento": "training_sessions_per_week",
                "entrenamientos": "training_sessions_per_week",
            }
            action_id = (
                "goal.create"
                if any(term in text for term in ("crea", "crear", "nueva"))
                else "goal.update"
            )
            if action_id in allowed:
                steps.append(
                    AIProviderPlanStepProposal(
                        f"step_{len(steps) + 1}",
                        action_id,
                        {
                            "goal_type": goal_types[_normalized(goal_match.group(1))],
                            "target_value": goal_match.group(2).replace(",", "."),
                        },
                    )
                )

        if (
            "training.session.create" in allowed
            and any(term in text for term in ("registra este entrenamiento", "registrar entrenamiento", "registre entrenamiento"))
        ):
            performed = re.search(r"\b(20\d{2}-\d{2}-\d{2}T[^\s,;]+)", original)
            arguments = {"performed_at": performed.group(1)} if performed else {}
            steps.append(
                AIProviderPlanStepProposal(
                    f"step_{len(steps) + 1}", "training.session.create", arguments
                )
            )

        if not steps:
            return None
        intent = "hybrid" if len({item.action_capability_id.split(".", 1)[0] for item in steps}) > 1 else "record"
        if all(item.action_capability_id.endswith((".correct", ".update")) for item in steps):
            intent = "correct"
        return AIProviderPlanProposal(
            intent=intent,
            summary=f"{len(steps)} cambio{'s' if len(steps) != 1 else ''} preparado{'s' if len(steps) != 1 else ''}",
            steps=tuple(steps),
        )

    @staticmethod
    def _single_selected_action_plan(
        request: AIProviderRequest,
    ) -> AIProviderPlanProposal | None:
        if len(request.actions) != 1 or not (request.require_tool or request.tool_results):
            return None
        action = request.actions[0]
        intent = "correct" if action.operation in {"correct", "update"} else "record"
        return AIProviderPlanProposal(
            intent=intent,
            summary="1 cambio preparado",
            steps=(
                AIProviderPlanStepProposal(
                    "step_1", action.action_capability_id, {}
                ),
            ),
        )

    @staticmethod
    def _proposal_after_goal_read(
        request: AIProviderRequest,
    ) -> AIProviderPlanProposal | None:
        if not request.tool_results or request.tool_results[-1].name != "get_goals_summary":
            return None
        text = _normalized(_last_user_text(request))
        if not (
            any(term in text for term in ("ajusta", "ajustar", "ajustes", "propon", "cambios"))
            and any(term in text for term in ("meta", "objetivo"))
        ):
            return None
        explicit = FakeAIProvider._action_plan(request)
        if explicit is not None and all(
            step.action_capability_id.startswith("goal.") for step in explicit.steps
        ):
            return AIProviderPlanProposal(
                intent="propose_changes",
                summary=explicit.summary,
                steps=explicit.steps,
            )
        allowed = {item.action_capability_id for item in request.actions}
        result = request.tool_results[-1]
        items = (result.data or {}).get("items") if result.ok else None
        arguments = {}
        action_id = "goal.create" if "goal.create" in allowed else None
        if isinstance(items, list) and "goal.update" in allowed:
            for item in items:
                goal = item.get("goal") if isinstance(item, dict) else None
                if not isinstance(goal, dict):
                    continue
                goal_type = goal.get("goal_type")
                target_value = goal.get("target_value")
                if goal_type and target_value not in (None, ""):
                    action_id = "goal.update"
                    arguments = {
                        "goal_type": goal_type,
                        "target_value": target_value,
                    }
                    break
        if action_id is None and "goal.update" in allowed:
            action_id = "goal.update"
        if action_id is None:
            return None
        return AIProviderPlanProposal(
            intent="propose_changes",
            summary="1 cambio de meta preparado para revisión",
            steps=(AIProviderPlanStepProposal("step_1", action_id, arguments),),
        )

    @staticmethod
    def _preset(text: str) -> str:
        return _explicit_preset(text) or "30d"

    @staticmethod
    def _tool_for(topic: str, preset: str, comparison: bool) -> tuple[str, dict]:
        if topic == "weight":
            return "get_weight_trend", {"preset": preset}
        if topic == "nutrition":
            return "get_nutrition_summary", {"preset": preset}
        if topic == "steps":
            return "get_steps_summary", {"preset": preset}
        if topic == "training":
            return "get_training_summary", {
                "preset": preset,
                "compare_previous": comparison,
            }
        if topic == "activity":
            return "get_activity_summary", {"limit": 10}
        if topic == "goals":
            days = 7 if preset == "7d" else 90 if preset == "90d" else 30
            return "get_goals_summary", {"days": days}
        if topic == "sources":
            return "get_data_sources_summary", {"domain": "steps", "preset": "90d"}
        return "get_dashboard_summary", {
            "preset": preset,
            "compare_previous": comparison,
        }

    @classmethod
    def _arguments_for_allowed_tool(
        cls,
        name: str,
        preset: str,
        comparison: bool,
        original: str,
    ) -> dict:
        if name == "get_latest_body_measurement":
            return cls._point_body_arguments(_normalized(original))
        if name in {"get_training_history", "get_activity_summary"}:
            return {"limit": 10}
        if name == "get_goals_summary":
            return {"days": 7 if preset == "7d" else 90 if preset == "90d" else 30}
        if name == "get_data_sources_summary":
            return {"domain": "all", "preset": preset}
        if name == "get_exercise_progress":
            return {"preset": preset if preset in {"7d", "30d", "90d"} else "30d"}
        if name == "get_food_patterns":
            return {"preset": preset}
        if name in {"get_dashboard_summary", "get_training_summary"}:
            return {"preset": preset, "compare_previous": comparison}
        if name in {"get_weight_trend", "get_nutrition_summary"}:
            return {"preset": preset, "compare_previous": comparison}
        if name == "get_steps_summary":
            return {"preset": preset}
        return {}

    @staticmethod
    def _is_point_body_question(text: str) -> bool:
        trend_terms = (
            "tendencia",
            "cambio",
            "cambio mi",
            "evolucion",
            "promedio",
            "subi",
            "baje",
            "ultimos ",
            "esta semana",
            "este mes",
        )
        return not any(term in text for term in trend_terms)

    @staticmethod
    def _point_body_arguments(text: str) -> dict:
        match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
        if match is not None:
            return {
                "date": match.group(1),
                "match": "on_or_before" if "antes" in text else "exact",
            }
        if "hoy" in text:
            override = current_app.config.get("AI_TODAY_OVERRIDE")
            today = override if isinstance(override, date) else datetime.now(timezone.utc).date()
            return {"date": today.isoformat(), "match": "exact"}
        return {}

    @classmethod
    def _body_measurement_draft(
        cls, request: AIProviderRequest
    ) -> AIProviderDraft | None:
        text = _last_user_text(request)
        match = re.search(
            r"(?:\bpeso\b|\bpes[eé]\b|\bweight\b)\s*(?:es|fue|:)?\s*(\d{1,3}(?:[.,]\d{1,3})?)\s*(kg|lb|lbs)?\b",
            text,
            flags=re.IGNORECASE,
        )
        body_fat = re.search(
            r"(\d{1,3}(?:[.,]\d{1,3})?)\s*%\s*(?:de\s*)?(?:grasa(?:\s+corporal)?|body\s+fat)",
            text,
            flags=re.IGNORECASE,
        )
        if match is None and body_fat is not None:
            prior_users = [item.content for item in request.messages if item.role == "user"]
            for prior in reversed(prior_users[:-1]):
                match = re.search(
                    r"(?:\bpeso\b|\bpes[eé]\b|\bweight\b)\s*(?:es|fue|:)?\s*(\d{1,3}(?:[.,]\d{1,3})?)\s*(kg|lb|lbs)?\b",
                    prior,
                    flags=re.IGNORECASE,
                )
                if match is not None:
                    break
        if match is None:
            return None
        value = Decimal(match.group(1).replace(",", "."))
        unit = (match.group(2) or "kg").casefold()
        if unit == "lbs":
            unit = "lb"
        if value <= 0 or value > 700:
            return None
        payload = {"weight": format(value, "f"), "unit": unit}
        if body_fat is not None:
            payload["body_fat_percent"] = body_fat.group(1).replace(",", ".")
        return AIProviderDraft(
            draft_type="body_measurement",
            payload=payload,
            provenance={
                "value_origin": "reported_by_user",
                "interpretation": "parsed_by_ai",
            },
        )

    @staticmethod
    def _food_nutrient_fields(text: str) -> dict[str, str]:
        number = r"(\d{1,7}(?:[.,]\d{1,3})?)"
        patterns = {
            "calories_kcal": rf"{number}\s*(?:kcal|calor[ií]as?)\b",
            "protein_g": rf"{number}\s*g(?:ramos?)?\s*(?:de\s*)?prote[ií]na\b",
            "fat_g": rf"{number}\s*g(?:ramos?)?\s*(?:de\s*)?grasas?\b",
            "net_carbs_g": rf"{number}\s*g(?:ramos?)?\s*(?:de\s*)?(?:carbos?|carbohidratos?)\s+netos?\b",
            "total_carbs_g": rf"{number}\s*g(?:ramos?)?\s*(?:de\s*)?(?:carbos?|carbohidratos?)\b(?!\s+netos?)",
            "fiber_g": rf"{number}\s*g(?:ramos?)?\s*(?:de\s*)?fibra\b",
            "sugar_g": rf"{number}\s*g(?:ramos?)?\s*(?:de\s*)?az[uú]car(?:es)?\b",
            "sodium_mg": rf"{number}\s*mg\s*(?:de\s*)?sodio\b",
        }
        result = {}
        for field_name, pattern in patterns.items():
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match is not None:
                result[field_name] = match.group(1).replace(",", ".")
        return result

    @classmethod
    def _food_entry_draft(cls, request: AIProviderRequest) -> AIProviderDraft | None:
        text = _last_user_text(request)
        normalized = _normalized(text).strip(" .!")
        source_text = text
        nutrient_fields = cls._food_nutrient_fields(text)
        meal_type = None
        meal_map = {
            "desayuno": "breakfast",
            "comida": "lunch",
            "almuerzo": "lunch",
            "cena": "dinner",
            "snack": "snack",
            "colacion": "snack",
        }
        for label, value in meal_map.items():
            if label in normalized:
                meal_type = value
                break
        has_today = "hoy" in normalized
        if (meal_type is not None or has_today) and not nutrient_fields:
            prior_users = [item.content for item in request.messages if item.role == "user"]
            for prior in reversed(prior_users[:-1]):
                nutrient_fields = cls._food_nutrient_fields(prior)
                if nutrient_fields:
                    source_text = prior
                    break
        items = []
        egg = re.fullmatch(r"comi\s+(\d+)\s+huevos?", normalized)
        if egg:
            items.append(
                {"name": "huevos", "quantity": egg.group(1), "unit": "unidad"}
            )
        else:
            for match in re.finditer(
                r"(\d+(?:[.,]\d+)?)\s*g(?:\s+de)?\s+([a-záéíóúñ ]+?)(?=\s+y\s+\d|$)",
                text.strip(" .!"),
                flags=re.IGNORECASE,
            ):
                items.append(
                    {
                        "name": match.group(2).strip(),
                        "quantity": match.group(1).replace(",", "."),
                        "unit": "g",
                    }
                )
        if nutrient_fields:
            name = source_text.split(",", 1)[0].strip(" .!")
            name = re.sub(r"^(?:com[ií]|registr[eé])\s+", "", name, flags=re.IGNORECASE)
            items = [{"name": name[:200] or "alimento reportado", **nutrient_fields}]
        if not items:
            return None
        if nutrient_fields and meal_type is None:
            return None
        target_date = None
        if has_today:
            override = current_app.config.get("AI_TODAY_OVERRIDE")
            today = override if isinstance(override, date) else datetime.now(timezone.utc).date()
            target_date = today.isoformat()
        date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
        if date_match is not None:
            target_date = date_match.group(1)
        payload = {
            "meal_type": meal_type or "other",
            "items": items,
        }
        if target_date is not None:
            payload["date"] = target_date
        if not nutrient_fields:
            payload.update(
                {
                    "warnings": [
                        "Faltan valores nutricionales; se guardarán como datos no disponibles."
                    ],
                    "missing_fields": [
                        "calories_kcal",
                        "protein_g",
                        "fat_g",
                        "total_carbs_g_or_net_carbs_g",
                    ],
                }
            )
        return AIProviderDraft(
            draft_type="food_entry",
            payload=payload,
            provenance={
                "value_origin": "reported_by_user",
                "interpretation": "parsed_by_ai",
            },
        )

    def _summarize(self, request: AIProviderRequest) -> AIProviderResponse:
        result = request.tool_results[-1]
        if not result.ok or result.data is None:
            return AIProviderResponse(
                content=(
                    "No pude completar esa consulta con las herramientas autorizadas. "
                    "No se modificó ningún dato; puedes intentarlo de nuevo."
                ),
                usage=self._usage(request, result.name),
            )
        data = result.data
        metrics = data.get("metrics") or {}
        period = data.get("period") or {}
        label = period.get("label") or (
            f"{period.get('from')} a {period.get('to')}"
            if period.get("from") and period.get("to")
            else "el periodo consultado"
        )

        if result.name == "get_dashboard_summary":
            energy = metrics.get("energy") or {}
            protein = metrics.get("protein") or {}
            weight = metrics.get("weight") or {}
            training = metrics.get("training") or {}
            content = (
                f"Para {label}: energía ingerida {_number(energy.get('consumed_total'))} kcal; "
                f"proteína {_number(protein.get('total'))} g; peso más reciente "
                f"{_number(weight.get('latest'))} {weight.get('unit') or 'kg'}; "
                f"entrenamientos {training.get('sessions', 0)}. "
                "Los valores ausentes se mantienen como ausencia, no como cero."
            )
        elif result.name == "get_weight_trend":
            content = (
                f"En {label} hay {metrics.get('entries', 0)} mediciones. "
                f"El peso más reciente es {_number(metrics.get('latest'))} "
                f"{metrics.get('unit') or 'kg'} y el cambio disponible es "
                f"{_number(metrics.get('change'))}."
            )
        elif result.name == "get_latest_body_measurement":
            if metrics.get("recorded_at") is None:
                content = "No encontré una medición corporal para la fecha solicitada."
            else:
                details = [f"peso {_number(metrics.get('weight_kg'))} kg"]
                if metrics.get("body_fat_percent") is not None:
                    details.append(
                        f"grasa corporal {_number(metrics.get('body_fat_percent'))}%"
                    )
                content = (
                    f"Tu medición del {metrics.get('local_date')} registra "
                    + " y ".join(details)
                    + "."
                )
        elif result.name == "get_nutrition_summary":
            protein = metrics.get("protein") or {}
            energy = metrics.get("energy") or {}
            content = (
                f"En {label}, la proteína registrada suma {_number(protein.get('total'))} g "
                f"en {protein.get('protein_days', 0)} días con datos. La energía ingerida "
                f"suma {_number(energy.get('consumed_total'))} kcal."
            )
        elif result.name == "get_training_summary":
            content = (
                f"En {label} registraste {metrics.get('sessions', 0)} sesiones en "
                f"{metrics.get('active_days', 0)} días activos. La comparación, cuando "
                "está disponible, usa un periodo anterior de la misma duración."
            )
        elif result.name == "get_training_history":
            content = f"Encontré {metrics.get('count', 0)} entrenamientos recientes."
        elif result.name == "get_activity_summary":
            content = f"Encontré {metrics.get('count', 0)} actividades recientes."
        elif result.name == "get_steps_summary":
            content = (
                f"En {label} hay {metrics.get('days_with_data', 0)} días con pasos y "
                f"un total de {_number(metrics.get('total'))} pasos."
            )
        elif result.name == "get_goals_summary":
            content = data.get("summary") or "Consulté tus objetivos configurados."
        elif result.name == "get_data_sources_summary":
            sources = [item.get("source") for item in data.get("sources", [])]
            content = (
                "Las fuentes registradas para esos datos son: "
                + (", ".join(source for source in sources if source) or "ninguna en el periodo")
                + "."
            )
        else:
            content = "Completé la consulta con una herramienta de solo lectura."
        return AIProviderResponse(content=content, usage=self._usage(request, content))

    @staticmethod
    def _usage(request: AIProviderRequest, output: str) -> AIUsage:
        input_chars = sum(len(message.content) for message in request.messages)
        return AIUsage(
            input_tokens=max(1, input_chars // 4) if input_chars else 0,
            output_tokens=max(1, len(output) // 4) if output else 0,
        )


OPENAI_BASE_URL = "https://api.openai.com/v1"
_DRAFT_TOOL_NAMES = {
    "prepare_body_measurement_draft": "body_measurement",
    "prepare_food_entry_draft": "food_entry",
}
_ACTION_PLAN_TOOL_NAME = "propose_action_plan"


def _action_plan_tools(actions: tuple[AIProviderActionDefinition, ...]) -> list[dict]:
    if not actions:
        return []
    step_variants = []
    for action in actions:
        schema = dict(action.input_schema)
        # Missing required fields are allowed in proposals and become needs_input.
        schema["required"] = []
        step_variants.append(
            {
                "type": "object",
                "properties": {
                    "step_id": {"type": "string", "pattern": "^[a-z][a-z0-9_-]{0,63}$"},
                    "action_capability_id": {"const": action.action_capability_id},
                    "arguments": schema,
                    "dependencies": {
                        "type": "array",
                        "maxItems": 10,
                        "items": {"type": "string"},
                    },
                },
                "required": ["step_id", "action_capability_id", "arguments", "dependencies"],
                "additionalProperties": False,
            }
        )
    return [
        {
            "type": "function",
            "name": _ACTION_PLAN_TOOL_NAME,
            "description": (
                "Propose one editable multi-step Health Tracker action plan. Never claim it was applied. "
                "Use only the listed capability IDs and fields; omit unknown values."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "enum": ["record", "correct", "propose_changes", "hybrid"],
                    },
                    "summary": {"type": "string", "minLength": 1, "maxLength": 500},
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 10,
                        "items": {"oneOf": step_variants},
                    },
                },
                "required": ["intent", "summary", "steps"],
                "additionalProperties": False,
            },
            "strict": False,
        }
    ]


def _parse_action_plan(arguments: dict) -> AIProviderPlanProposal:
    if set(arguments) != {"intent", "summary", "steps"}:
        raise AIProviderError(
            "provider_malformed_action_plan", "El proveedor AI devolvió un plan no válido.", 502
        )
    intent = arguments.get("intent")
    summary = arguments.get("summary")
    raw_steps = arguments.get("steps")
    if (
        intent not in {"record", "correct", "propose_changes", "hybrid"}
        or not isinstance(summary, str)
        or not summary.strip()
        or not isinstance(raw_steps, list)
        or not 1 <= len(raw_steps) <= 10
    ):
        raise AIProviderError(
            "provider_malformed_action_plan", "El proveedor AI devolvió un plan no válido.", 502
        )
    steps = []
    for raw in raw_steps:
        if not isinstance(raw, dict) or set(raw) != {
            "step_id", "action_capability_id", "arguments", "dependencies"
        }:
            raise AIProviderError(
                "provider_malformed_action_plan", "El proveedor AI devolvió un plan no válido.", 502
            )
        if (
            not isinstance(raw["step_id"], str)
            or not isinstance(raw["action_capability_id"], str)
            or not isinstance(raw["arguments"], dict)
            or not isinstance(raw["dependencies"], list)
            or any(not isinstance(item, str) for item in raw["dependencies"])
        ):
            raise AIProviderError(
                "provider_malformed_action_plan", "El proveedor AI devolvió un plan no válido.", 502
            )
        steps.append(
            AIProviderPlanStepProposal(
                step_id=raw["step_id"],
                action_capability_id=raw["action_capability_id"],
                arguments=raw["arguments"],
                dependencies=tuple(raw["dependencies"]),
            )
        )
    return AIProviderPlanProposal(intent=intent, summary=summary.strip(), steps=tuple(steps))


def _draft_tools(allowed_types: tuple[str, ...] | None = None) -> list[dict]:
    tools = [
        {
            "type": "function",
            "name": "prepare_body_measurement_draft",
            "description": (
                "Prepare, but never apply, a complete user-reported body measurement. "
                "Preserve every explicit supported metric; list unsupported or ambiguous "
                "fields visibly. For a pending-draft follow-up, return the complete merged draft."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "weight": {"type": ["string", "number"]},
                    "unit": {"type": "string", "enum": ["kg", "lb"]},
                    "recorded_at": {"type": "string", "format": "date-time"},
                    "body_fat_percent": {"type": ["string", "number", "null"]},
                    "muscle_mass_kg": {"type": ["string", "number", "null"]},
                    "water_percent": {"type": ["string", "number", "null"]},
                    "visceral_fat": {"type": ["string", "number", "null"]},
                    "bmr_kcal": {"type": ["string", "number", "null"]},
                    "bmi": {"type": ["string", "number", "null"]},
                    "notes": {"type": ["string", "null"]},
                    "warnings": {"type": "array", "items": {"type": "string"}},
                    "missing_fields": {"type": "array", "items": {"type": "string"}},
                    "unsupported_fields": {"type": "array", "items": {"type": "string"}},
                    "ambiguous_fields": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["weight", "unit"],
                "additionalProperties": False,
            },
            "strict": False,
        },
        {
            "type": "function",
            "name": "prepare_food_entry_draft",
            "description": (
                "Prepare, but never apply, complete editable food items. Preserve calories, "
                "protein, fat, net and total carbohydrates without treating them as equivalent, "
                "fiber, sugar and sodium when explicitly supplied. Preserve prior-turn nutrients "
                "when date or meal arrives in a follow-up; list unsupported/ambiguous fields."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "format": "date"},
                    "meal_type": {
                        "type": "string",
                        "enum": ["breakfast", "lunch", "dinner", "snack", "extra", "other"],
                    },
                    "meal_name": {"type": ["string", "null"]},
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 20,
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "quantity": {"type": ["string", "number", "null"]},
                                "unit": {"type": ["string", "null"]},
                                "calories_kcal": {"type": ["string", "number", "null"]},
                                "protein_g": {"type": ["string", "number", "null"]},
                                "fat_g": {"type": ["string", "number", "null"]},
                                "net_carbs_g": {"type": ["string", "number", "null"]},
                                "total_carbs_g": {"type": ["string", "number", "null"]},
                                "fiber_g": {"type": ["string", "number", "null"]},
                                "sugar_g": {"type": ["string", "number", "null"]},
                                "sodium_mg": {"type": ["string", "number", "null"]},
                                "notes": {"type": ["string", "null"]},
                            },
                            "required": ["name"],
                            "additionalProperties": False,
                        },
                    },
                    "warnings": {"type": "array", "items": {"type": "string"}},
                    "missing_fields": {"type": "array", "items": {"type": "string"}},
                    "unsupported_fields": {"type": "array", "items": {"type": "string"}},
                    "ambiguous_fields": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["meal_type", "items"],
                "additionalProperties": False,
            },
            "strict": False,
        },
    ]
    if allowed_types is None:
        return tools
    allowed_names = {
        name for name, draft_type in _DRAFT_TOOL_NAMES.items() if draft_type in allowed_types
    }
    return [item for item in tools if item["name"] in allowed_names]


def _post_openai_json(
    url: str, headers: dict, body: bytes, timeout: float
) -> _OpenAIHTTPResponse:
    request = Request(url, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
        status = getattr(response, "status", None)
        content_type = _response_content_type(getattr(response, "headers", None))
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        _log_openai_response_diagnostic(
            status=status,
            content_type=content_type,
            document=None,
        )
        raise
    return _OpenAIHTTPResponse(document, status, content_type)


@dataclass(frozen=True)
class _OpenAIHTTPResponse:
    document: object
    status: int | None
    content_type: str | None


def _response_content_type(headers) -> str | None:
    try:
        value = headers.get("Content-Type") if headers is not None else None
    except (AttributeError, TypeError, ValueError):
        return None
    if not isinstance(value, str):
        return None
    media_type = value.partition(";")[0].strip().casefold()
    if not re.fullmatch(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+", media_type):
        return None
    return media_type[:96]


def _diagnostic_token(value) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        clean = value.strip()
        if re.fullmatch(r"[A-Za-z0-9_.:/-]{1,96}", clean):
            return clean
        if clean:
            return "present"
    return "none"


def _log_openai_response_diagnostic(
    *,
    status: int | None,
    content_type: str | None,
    document,
    model: str | None = None,
    phase: str | None = None,
    intent: str | None = None,
) -> None:
    top_level_keys: list[str] = []
    output_item_types: list[str] = []
    error_code = "none"
    error_type = "none"
    if isinstance(document, dict):
        for key in list(document)[:32]:
            top_level_keys.append(_diagnostic_token(key))
        output = document.get("output")
        if isinstance(output, list):
            for item in output[:32]:
                if isinstance(item, dict):
                    output_item_types.append(_diagnostic_token(item.get("type")))
                else:
                    output_item_types.append("non_object")
        error = document.get("error")
        if isinstance(error, dict):
            error_code = _diagnostic_token(error.get("code"))
            error_type = _diagnostic_token(error.get("type"))
    current_app.logger.warning(
        "ai_provider_response_rejected http_status=%s content_type=%s "
        "top_level_keys=%s output_item_types=%s has_id=%s has_model=%s "
        "has_usage=%s error_code=%s error_type=%s model=%s phase=%s intent=%s",
        status if type(status) is int else "unknown",
        content_type or "unknown",
        ",".join(sorted(set(top_level_keys))) or "none",
        ",".join(output_item_types) or "none",
        "yes" if isinstance(document, dict) and "id" in document else "no",
        "yes" if isinstance(document, dict) and "model" in document else "no",
        "yes" if isinstance(document, dict) and "usage" in document else "no",
        error_code,
        error_type,
        _diagnostic_token(model),
        _diagnostic_token(phase),
        _diagnostic_token(intent),
    )


def _http_error_document(error: HTTPError):
    try:
        raw = error.read(65_537)
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    if not raw or len(raw) > 65_536:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _responses_url(base_url: str | None) -> str:
    raw = (base_url or OPENAI_BASE_URL).strip().rstrip("/")
    parts = urlsplit(raw)
    if (
        parts.scheme != "https"
        or not parts.netloc
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise AIProviderError(
            "invalid_ai_configuration", "La configuración AI no es válida.", 503
        )
    path = f"{parts.path.rstrip('/')}/responses"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


class OpenAIResponsesProvider(AIProvider):
    """Thin Responses API adapter with an injectable transport for offline tests."""

    name = "openai"
    capabilities = AIProviderCapabilities(
        supports_tools=True,
        supports_images=False,
        supports_structured_output=True,
        supports_usage=True,
        remote=True,
    )

    def __init__(
        self, api_key: str, *, base_url: str | None = None, transport=None
    ):
        self._api_key = api_key
        self._responses_url = _responses_url(base_url)
        self._transport = transport or _post_openai_json

    def respond(self, request: AIProviderRequest) -> AIProviderResponse:
        tools = [
            {
                "type": "function",
                "name": item.name,
                "description": item.description,
                "parameters": item.input_schema,
                "strict": False,
            }
            for item in request.tools
        ]
        tools.extend(_action_plan_tools(request.actions))
        if not request.actions:
            tools.extend(_draft_tools(request.draft_types))
        input_items: list[dict] = [
            {"role": item.role, "content": item.content} for item in request.messages
        ]
        for result in request.tool_results:
            input_items.extend(
                [
                    {
                        "type": "function_call",
                        "call_id": result.call_id,
                        "name": result.name,
                        "arguments": json.dumps(
                            result.arguments, ensure_ascii=False, separators=(",", ":")
                        ),
                    },
                    {
                        "type": "function_call_output",
                        "call_id": result.call_id,
                        "output": json.dumps(
                            {
                                "ok": result.ok,
                                "data": result.data,
                                "error_code": result.error_code,
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    },
                ]
            )
        maximum = current_app.config.get("AI_MAX_OUTPUT_TOKENS")
        if type(maximum) is not int or not 1 <= maximum <= 100_000:
            raise AIProviderError(
                "invalid_ai_configuration", "La configuración AI no es válida.", 503
            )
        payload = {
            "model": request.model,
            "instructions": request.safety_instructions,
            "input": input_items,
            "tools": tools,
            "store": False,
            "max_output_tokens": maximum,
        }
        if request.require_tool and tools:
            payload["tool_choice"] = "required"
        try:
            transport_response = self._transport(
                self._responses_url,
                {
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                request.timeout_seconds,
            )
        except HTTPError as error:
            document = _http_error_document(error)
            _log_openai_response_diagnostic(
                status=error.code,
                content_type=_response_content_type(error.headers),
                document=document,
                model=request.model,
                phase=request.phase,
                intent=request.intent,
            )
            self._raise_http(error.code)
        except (TimeoutError, socket.timeout) as error:
            raise AIProviderError(
                "provider_timeout", "El proveedor AI agotó el tiempo de espera.", 504
            ) from error
        except (URLError, OSError) as error:
            raise AIProviderError(
                "provider_offline", "El proveedor AI no está disponible temporalmente.", 503
            ) from error
        except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            _log_openai_response_diagnostic(
                status=None,
                content_type=None,
                document=None,
                model=request.model,
                phase=request.phase,
                intent=request.intent,
            )
            raise AIProviderError(
                "provider_malformed_response",
                "El proveedor AI devolvió una respuesta no válida.",
                502,
            ) from error
        if isinstance(transport_response, _OpenAIHTTPResponse):
            document = transport_response.document
            http_status = transport_response.status
            content_type = transport_response.content_type
            if type(http_status) is int and not 200 <= http_status < 300:
                _log_openai_response_diagnostic(
                    status=http_status,
                    content_type=content_type,
                    document=document,
                    model=request.model,
                    phase=request.phase,
                    intent=request.intent,
                )
                self._raise_http(http_status)
        else:
            document = transport_response
            http_status = None
            content_type = None
        return self._parse(
            document,
            http_status=http_status,
            content_type=content_type,
            model=request.model,
            phase=request.phase,
            intent=request.intent,
        )

    @staticmethod
    def _raise_http(status: int) -> None:
        if status in {401, 403}:
            raise AIProviderError(
                "provider_auth", "La autenticación del proveedor AI falló.", 502
            )
        if status == 429:
            raise AIProviderError(
                "provider_quota", "El proveedor AI alcanzó su límite temporal.", 429
            )
        if status in {408, 504}:
            raise AIProviderError(
                "provider_timeout", "El proveedor AI agotó el tiempo de espera.", 504
            )
        if status == 404:
            raise AIProviderError(
                "provider_model_unavailable",
                "El modelo AI configurado no está disponible.",
                502,
            )
        raise AIProviderError(
            "provider_offline", "El proveedor AI no está disponible temporalmente.", 503
        )

    @staticmethod
    def _parse(
        document,
        *,
        http_status: int | None = None,
        content_type: str | None = None,
        model: str | None = None,
        phase: str | None = None,
        intent: str | None = None,
    ) -> AIProviderResponse:
        try:
            return OpenAIResponsesProvider._parse_document(document)
        except AIProviderError:
            _log_openai_response_diagnostic(
                status=http_status,
                content_type=content_type,
                document=document,
                model=model,
                phase=phase,
                intent=intent,
            )
            raise

    @staticmethod
    def _parse_document(document) -> AIProviderResponse:
        if not isinstance(document, dict) or not isinstance(document.get("output"), list):
            raise AIProviderError(
                "provider_malformed_response",
                "El proveedor AI devolvió una respuesta no válida.",
                502,
            )
        text_parts: list[str] = []
        calls = []
        drafts = []
        plans = []
        for item in document["output"]:
            if not isinstance(item, dict):
                raise AIProviderError(
                    "provider_malformed_response",
                    "El proveedor AI devolvió una respuesta no válida.",
                    502,
                )
            item_type = item.get("type")
            if item_type == "message":
                contents = item.get("content")
                if not isinstance(contents, list):
                    raise AIProviderError(
                        "provider_malformed_response",
                        "El proveedor AI devolvió una respuesta no válida.",
                        502,
                    )
                for content in contents:
                    if not isinstance(content, dict):
                        raise AIProviderError(
                            "provider_malformed_response",
                            "El proveedor AI devolvió una respuesta no válida.",
                            502,
                        )
                    if content.get("type") == "output_text":
                        text = content.get("text")
                        if not isinstance(text, str):
                            raise AIProviderError(
                                "provider_malformed_response",
                                "El proveedor AI devolvió una respuesta no válida.",
                                502,
                            )
                        text_parts.append(text)
            elif item_type == "function_call":
                name = item.get("name")
                call_id = item.get("call_id")
                try:
                    arguments = json.loads(item.get("arguments"))
                except (TypeError, json.JSONDecodeError) as error:
                    raise AIProviderError(
                        "provider_malformed_tool_call",
                        "El proveedor AI devolvió una llamada de herramienta no válida.",
                        502,
                    ) from error
                if (
                    not isinstance(name, str)
                    or not name.strip()
                    or not isinstance(call_id, str)
                    or not call_id.strip()
                    or not isinstance(arguments, dict)
                ):
                    raise AIProviderError(
                        "provider_malformed_tool_call",
                        "El proveedor AI devolvió una llamada de herramienta no válida.",
                        502,
                    )
                draft_type = _DRAFT_TOOL_NAMES.get(name)
                if name == _ACTION_PLAN_TOOL_NAME:
                    plans.append(_parse_action_plan(arguments))
                elif draft_type:
                    drafts.append(
                        AIProviderDraft(
                            draft_type=draft_type,
                            payload=arguments,
                            provenance={
                                "value_origin": "reported_by_user",
                                "interpretation": "parsed_by_ai",
                            },
                        )
                    )
                else:
                    calls.append(AIProviderToolCall(call_id, name, arguments))
        if (calls and (drafts or plans)) or (drafts and plans):
            raise AIProviderError(
                "provider_malformed_response",
                "El proveedor AI devolvió una respuesta ambigua.",
                502,
            )
        content = "\n".join(part.strip() for part in text_parts if part.strip()) or None
        if (drafts or plans) and content is None:
            content = "Preparé un plan editable. Revísalo antes de confirmarlo."
        if content is None and not calls and not drafts and not plans:
            raise AIProviderError(
                "provider_malformed_response",
                "El proveedor AI no devolvió contenido utilizable.",
                502,
            )
        usage = document.get("usage")
        if usage is None:
            usage = {}
        if not isinstance(usage, dict):
            raise AIProviderError(
                "provider_malformed_response",
                "El proveedor AI devolvió una respuesta no válida.",
                502,
            )
        for field_name in ("input_tokens", "output_tokens"):
            value = usage.get(field_name)
            if value is not None and (type(value) is not int or value < 0):
                raise AIProviderError(
                    "provider_malformed_response",
                    "El proveedor AI devolvió una respuesta no válida.",
                    502,
                )
        return AIProviderResponse(
            content=content,
            tool_calls=tuple(calls),
            drafts=tuple(drafts),
            plans=tuple(plans),
            usage=AIUsage(
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
            ),
        )


def _enabled_action_ids() -> list[str]:
    from app.services.ai.capabilities.registry import AICapabilityRegistry

    return [item.action_id for item in AICapabilityRegistry().action_capabilities]


def provider_status(user=None) -> dict:
    enabled = bool(current_app.config.get("AI_ENABLED"))
    if not enabled:
        return {
            "enabled": False,
            "state": "disabled",
            "provider": None,
            "model": None,
            "reason": "La función AI está desactivada.",
            "capabilities": {
                "tools": False,
                "images": False,
                "structured_output": False,
                "usage": False,
            },
            "remote": False,
            "remote_consent_enabled": False,
            "write_actions_enabled": _enabled_action_ids(),
            "attachments_enabled": False,
        }

    provider_name = str(current_app.config.get("AI_PROVIDER") or "").strip().casefold()
    model = str(current_app.config.get("AI_MODEL") or "").strip()
    injected = current_app.config.get("AI_PROVIDER_INSTANCE") is not None or callable(
        current_app.config.get("AI_PROVIDER_FACTORY")
    )
    if not provider_name or not model:
        state = "unconfigured"
        reason = "Falta configurar AI_PROVIDER o AI_MODEL."
    elif provider_name not in {"fake", "openai"} and not injected:
        state = "unconfigured"
        reason = "El proveedor configurado no está instalado."
    elif provider_name == "openai" and not str(
        current_app.config.get("AI_API_KEY") or ""
    ).strip():
        state = "unconfigured"
        reason = "Falta configurar AI_API_KEY para el proveedor remoto."
    else:
        state = "available"
        reason = None
    instance = current_app.config.get("AI_PROVIDER_INSTANCE")
    if isinstance(instance, AIProvider):
        capabilities = instance.capabilities
    elif provider_name == "openai":
        capabilities = OpenAIResponsesProvider.capabilities
    elif provider_name == "fake":
        capabilities = FakeAIProvider.capabilities
    else:
        capabilities = AIProviderCapabilities()
    consent_enabled = bool(
        user is not None and getattr(user, "ai_remote_consent_enabled", False)
    )
    if (
        user is not None
        and state == "available"
        and capabilities.remote
        and not consent_enabled
    ):
        state = "consent_required"
        reason = "Activa el consentimiento de AI remota antes de enviar datos."
    return {
        "enabled": enabled,
        "state": state,
        "provider": provider_name or None,
        "model": model or None,
        "reason": reason,
        "capabilities": {
            "tools": capabilities.supports_tools,
            "images": capabilities.supports_images,
            "structured_output": capabilities.supports_structured_output,
            "usage": capabilities.supports_usage,
        },
        "remote": capabilities.remote,
        "remote_consent_enabled": consent_enabled,
        "write_actions_enabled": _enabled_action_ids(),
        "attachments_enabled": False,
    }


def get_provider() -> AIProvider:
    status = provider_status()
    if status["state"] != "available":
        raise AIProviderError(
            "ai_unavailable", status["reason"] or "AI no disponible.", 503
        )
    factory = current_app.config.get("AI_PROVIDER_FACTORY")
    if callable(factory):
        provider = factory()
    else:
        provider = current_app.config.get("AI_PROVIDER_INSTANCE")
    if provider is None and status["provider"] == "fake":
        provider = FakeAIProvider()
    if provider is None and status["provider"] == "openai":
        provider = OpenAIResponsesProvider(
            str(current_app.config.get("AI_API_KEY") or ""),
            base_url=str(current_app.config.get("AI_BASE_URL") or ""),
            transport=current_app.config.get("AI_HTTP_TRANSPORT"),
        )
    if not isinstance(provider, AIProvider):
        raise AIProviderError(
            "invalid_provider",
            "El proveedor AI configurado no implementa la interfaz requerida.",
            503,
        )
    return provider
