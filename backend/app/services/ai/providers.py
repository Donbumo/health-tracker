from __future__ import annotations

from abc import ABC, abstractmethod
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
    AIProviderDraft,
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
            return self._summarize(request)

        original = _last_user_text(request)
        text = _normalized(original)
        draft = self._body_measurement_draft(original)
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

        food_draft = self._food_entry_draft(original)
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
        if comparison and has_prior_user_message and _explicit_preset(text) is None:
            preset = _prior_preset(request)
        elif "mas o menos" in text and preset == "previous-month":
            # This asks for the current month against the previous period.
            preset = "this-month"
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
                "value_origin": "reported_by_user",
                "interpretation": "parsed_by_ai",
            },
        )

    @staticmethod
    def _food_entry_draft(text: str) -> AIProviderDraft | None:
        normalized = _normalized(text).strip(" .!")
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
        if not items:
            return None
        return AIProviderDraft(
            draft_type="food_entry",
            payload={
                "meal_type": "other",
                "items": items,
                "warnings": [
                    "Faltan valores nutricionales; se guardarán como datos no disponibles."
                ],
                "missing_fields": ["calories_kcal", "protein_g"],
            },
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


def _draft_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "name": "prepare_body_measurement_draft",
            "description": "Prepare, but never apply, a user-reported body weight draft.",
            "parameters": {
                "type": "object",
                "properties": {
                    "weight": {"type": ["string", "number"]},
                    "unit": {"type": "string", "enum": ["kg", "lb"]},
                },
                "required": ["weight", "unit"],
                "additionalProperties": False,
            },
            "strict": False,
        },
        {
            "type": "function",
            "name": "prepare_food_entry_draft",
            "description": "Prepare, but never apply, editable food items reported by the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "format": "date"},
                    "meal_type": {
                        "type": "string",
                        "enum": ["breakfast", "lunch", "dinner", "snack", "extra", "other"],
                    },
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
                            },
                            "required": ["name"],
                            "additionalProperties": False,
                        },
                    },
                    "warnings": {"type": "array", "items": {"type": "string"}},
                    "missing_fields": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["meal_type", "items"],
                "additionalProperties": False,
            },
            "strict": False,
        },
    ]


def _post_openai_json(url: str, headers: dict, body: bytes, timeout: int) -> dict:
    request = Request(url, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


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
        tools.extend(_draft_tools())
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
        try:
            document = self._transport(
                self._responses_url,
                {
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                request.timeout_seconds,
            )
        except HTTPError as error:
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
            raise AIProviderError(
                "provider_malformed_response",
                "El proveedor AI devolvió una respuesta no válida.",
                502,
            ) from error
        return self._parse(document)

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
    def _parse(document) -> AIProviderResponse:
        if not isinstance(document, dict) or not isinstance(document.get("output"), list):
            raise AIProviderError(
                "provider_malformed_response",
                "El proveedor AI devolvió una respuesta no válida.",
                502,
            )
        text_parts: list[str] = []
        calls = []
        drafts = []
        for item in document["output"]:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message":
                for content in item.get("content") or []:
                    if isinstance(content, dict) and content.get("type") == "output_text":
                        if isinstance(content.get("text"), str):
                            text_parts.append(content["text"])
            elif item.get("type") == "function_call":
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
                if not isinstance(name, str) or not isinstance(call_id, str) or not isinstance(arguments, dict):
                    raise AIProviderError(
                        "provider_malformed_tool_call",
                        "El proveedor AI devolvió una llamada de herramienta no válida.",
                        502,
                    )
                draft_type = _DRAFT_TOOL_NAMES.get(name)
                if draft_type:
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
        if calls and drafts:
            raise AIProviderError(
                "provider_malformed_response",
                "El proveedor AI devolvió una respuesta ambigua.",
                502,
            )
        content = "\n".join(part.strip() for part in text_parts if part.strip()) or None
        if drafts and content is None:
            content = "Preparé un borrador editable. Revísalo antes de confirmarlo."
        usage = document.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}
        return AIProviderResponse(
            content=content,
            tool_calls=tuple(calls),
            drafts=tuple(drafts),
            usage=AIUsage(
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
            ),
        )


def provider_status(user=None) -> dict:
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
        "write_actions_enabled": ["body_measurement", "food_entry"],
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
