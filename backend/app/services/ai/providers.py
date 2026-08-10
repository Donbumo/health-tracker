from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
import re
import unicodedata
import uuid

from flask import current_app

from app.services.ai.types import (
    AIProviderDraft,
    AIProviderRequest,
    AIProviderResponse,
    AIProviderToolCall,
    AIUsage,
)


class AIProviderError(RuntimeError):
    """Safe provider boundary error; never include credentials in its message."""


class AIProvider(ABC):
    name = "unknown"

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


def _number(value) -> str:
    if value is None:
        return "sin datos"
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


class FakeAIProvider(AIProvider):
    """Deterministic QA/demo provider. It performs no network calls."""

    name = "fake"

    def respond(self, request: AIProviderRequest) -> AIProviderResponse:
        if request.tool_results:
            return self._summarize(request)

        original = _last_user_text(request)
        text = _normalized(original)
        draft = self._body_measurement_draft(original)
        if draft is not None:
            return AIProviderResponse(
                content=(
                    "Preparé un borrador de medición corporal. Revísalo: todavía "
                    "no se guardó ningún dato. La confirmación desde el chat no está "
                    "habilitada en esta versión."
                ),
                drafts=(draft,),
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

        comparison = any(term in text for term in ("comparado", "anterior", "mas o menos"))
        if comparison and len([m for m in request.messages if m.role == "user"]) > 1:
            topic = _prior_topic(request)
        elif "pasos" in text and any(term in text for term in ("de donde", "fuente", "origen")):
            topic = "sources"
        elif "peso" in text:
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
        name, arguments = self._tool_for(topic, preset, comparison)
        return AIProviderResponse(
            tool_calls=(
                AIProviderToolCall(
                    call_id=str(uuid.uuid4()), name=name, arguments=arguments
                ),
            ),
            usage=self._usage(request, original),
        )

    @staticmethod
    def _preset(text: str) -> str:
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
        return "30d"

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

    @staticmethod
    def _body_measurement_draft(text: str) -> AIProviderDraft | None:
        match = re.fullmatch(
            r"\s*(?:peso|weight)\s*(?:es|:)?\s*(\d{1,3}(?:[.,]\d{1,3})?)\s*(kg|lb|lbs)?\s*[.!]?\s*",
            text,
            flags=re.IGNORECASE,
        )
        if match is None:
            return None
        value = Decimal(match.group(1).replace(",", "."))
        unit = (match.group(2) or "kg").casefold()
        if unit == "lbs":
            unit = "lb"
        if value <= 0 or value > 700:
            return None
        return AIProviderDraft(
            draft_type="body_measurement",
            payload={"weight": format(value, "f"), "unit": unit},
            provenance={
                "value_origin": "reported",
                "interpretation": "estimated_by_ai",
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


def provider_status() -> dict:
    enabled = bool(current_app.config.get("AI_ENABLED"))
    provider_name = str(current_app.config.get("AI_PROVIDER") or "").strip().casefold()
    model = str(current_app.config.get("AI_MODEL") or "").strip()
    injected = current_app.config.get("AI_PROVIDER_INSTANCE") is not None or callable(
        current_app.config.get("AI_PROVIDER_FACTORY")
    )
    if not enabled:
        state = "disabled"
        reason = "La función AI está desactivada."
    elif not provider_name or not model:
        state = "unconfigured"
        reason = "Falta configurar AI_PROVIDER o AI_MODEL."
    elif provider_name != "fake" and not injected:
        state = "unconfigured"
        reason = "El proveedor configurado no está instalado."
    else:
        state = "available"
        reason = None
    return {
        "enabled": enabled,
        "state": state,
        "provider": provider_name or None,
        "model": model or None,
        "reason": reason,
        "write_actions_enabled": False,
        "attachments_enabled": False,
    }


def get_provider() -> AIProvider:
    status = provider_status()
    if status["state"] != "available":
        raise AIProviderError(status["reason"] or "AI no disponible.")
    factory = current_app.config.get("AI_PROVIDER_FACTORY")
    if callable(factory):
        provider = factory()
    else:
        provider = current_app.config.get("AI_PROVIDER_INSTANCE")
    if provider is None and status["provider"] == "fake":
        provider = FakeAIProvider()
    if not isinstance(provider, AIProvider):
        raise AIProviderError("El proveedor AI configurado no implementa la interfaz requerida.")
    return provider
