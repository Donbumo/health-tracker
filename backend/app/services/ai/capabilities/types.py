from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator, FormatChecker


PERIODS = ("today", "7d", "30d", "90d")


class AIIntent(StrEnum):
    SUMMARY = "summary"
    LATEST = "latest"
    TREND = "trend"
    COMPARE = "compare"
    CONSISTENCY = "consistency"
    PROGRESS = "progress"
    COVERAGE = "coverage"
    SOURCES = "sources"
    PATTERNS = "patterns"
    RECORD = "record"
    CORRECT = "correct"
    PROPOSE_CHANGES = "propose_changes"


class CapabilityError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status = status


@dataclass(frozen=True)
class MetricDefinition:
    id: str
    label: str
    unit: str
    aggregations: tuple[str, ...]
    comparison_supported: bool = False
    trend_supported: bool = False
    goal_supported: bool = False
    display_precision: int = 0
    missing_data_semantics: str = "unknown"


@dataclass(frozen=True)
class ReadCapability:
    intent: AIIntent
    tools: tuple[str, ...]
    metrics: tuple[str, ...] = ()
    periods: tuple[str, ...] = PERIODS
    minimum_records: int = 0
    description: str = ""


class AIPlanStepStatus(StrEnum):
    PROPOSED = "proposed"
    NEEDS_INPUT = "needs_input"
    READY = "ready"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    APPLIED = "applied"
    FAILED = "failed"


@dataclass(frozen=True)
class ActionApplyResult:
    resource_type: str
    resource_public_ids: tuple[str, ...]


@dataclass(frozen=True)
class ActionDraftSpec:
    arguments: dict[str, Any]
    status: AIPlanStepStatus
    preview: dict[str, Any]
    context: dict[str, Any] = field(default_factory=dict)


ActionNormalizer = Callable[[Any, dict[str, Any]], dict[str, Any]]
ActionOwnerResolver = Callable[
    [Any, dict[str, Any], Mapping[str, Any] | None], dict[str, Any]
]
ActionPreviewer = Callable[[Any, dict[str, Any], Mapping[str, Any]], dict[str, Any]]
ActionApplier = Callable[
    [Any, Any, dict[str, Any], Mapping[str, Any], datetime], ActionApplyResult
]


def _identity_normalizer(_user, arguments: dict[str, Any]) -> dict[str, Any]:
    return arguments


def _empty_owner_context(
    _user, _arguments: dict[str, Any], _resource_context: Mapping[str, Any] | None
) -> dict[str, Any]:
    return {}


def _default_preview(
    _user, arguments: dict[str, Any], _context: Mapping[str, Any]
) -> dict[str, Any]:
    return {"fields": [{"name": key, "value": value} for key, value in arguments.items()]}


@dataclass(frozen=True)
class ActionCapability:
    """Domain-owned, server-resolved contract for one confirmable write action."""

    action_id: str
    domain: str
    entity: str
    operation: str
    label: str
    description: str
    supported_fields: tuple[str, ...]
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    input_schema: Mapping[str, Any]
    apply_handler: ActionApplier
    draft_type: str = "capability_action"
    confirmation_required: bool = True
    ownership_policy: str = "effective_server_user"
    idempotency_policy: str = "draft_uuid"
    required_read_capabilities: tuple[str, ...] = ()
    normalizer: ActionNormalizer = _identity_normalizer
    owner_resolver: ActionOwnerResolver = _empty_owner_context
    previewer: ActionPreviewer = _default_preview
    available: bool = True
    blocker: str | None = None

    @property
    def service(self) -> str:
        """Human-readable audit metadata; never selected by the provider or browser."""
        return getattr(self.apply_handler, "__name__", "domain_handler")

    @property
    def read_tools(self) -> tuple[str, ...]:
        return self.required_read_capabilities

    def validate(
        self, user, arguments: Mapping[str, Any], *, allow_incomplete: bool
    ) -> dict[str, Any]:
        if not isinstance(arguments, Mapping):
            raise CapabilityError("invalid_action_arguments", "Los argumentos de la acción no son válidos.")
        raw = dict(arguments)
        unknown = set(raw) - set(self.supported_fields)
        if unknown:
            raise CapabilityError(
                "unsupported_action_field",
                "La propuesta contiene campos no permitidos para esta acción.",
                422,
            )
        normalized = self.normalizer(user, raw)
        if not isinstance(normalized, dict) or set(normalized) - set(self.supported_fields):
            raise CapabilityError(
                "invalid_action_arguments", "La acción no pudo normalizarse de forma segura.", 422
            )
        schema = dict(self.input_schema)
        schema["required"] = [] if allow_incomplete else list(self.required_fields)
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(normalized),
            key=lambda item: list(item.path),
        )
        if errors:
            raise CapabilityError(
                "invalid_action_arguments", "Los argumentos no cumplen el contrato de la acción.", 422
            )
        return normalized

    def create_draft(
        self,
        user,
        arguments: Mapping[str, Any],
        *,
        resource_context: Mapping[str, Any] | None = None,
    ) -> ActionDraftSpec:
        clean = self.validate(user, arguments, allow_incomplete=True)
        if resource_context is not None and not isinstance(resource_context, Mapping):
            raise CapabilityError(
                "invalid_action_context", "El contexto de la acción no es válido.", 403
            )
        context = self.owner_resolver(user, clean, resource_context)
        if not isinstance(context, dict):
            raise CapabilityError(
                "invalid_action_context", "La acción no pudo resolver un contexto seguro.", 422
            )
        argument_defaults = context.pop("argument_defaults", {})
        if argument_defaults:
            if (
                not isinstance(argument_defaults, Mapping)
                or set(argument_defaults) - set(self.supported_fields)
            ):
                raise CapabilityError(
                    "invalid_action_context", "La acción no pudo resolver un contexto seguro.", 422
                )
            clean = self.validate(
                user,
                {**dict(argument_defaults), **clean},
                allow_incomplete=True,
            )
        missing = tuple(field for field in self.required_fields if clean.get(field) in (None, "", []))
        retained_missing = [
            str(name)
            for name in (clean.get("missing_fields") or ())
            if name not in self.required_fields or name in missing
        ]
        if retained_missing or missing:
            clean["missing_fields"] = list(
                dict.fromkeys([*retained_missing, *missing])
            )
        else:
            clean.pop("missing_fields", None)
        ambiguous = tuple(clean.get("ambiguous_fields") or ())
        status = (
            AIPlanStepStatus.NEEDS_INPUT
            if missing or ambiguous or context.get("needs_input") is True
            else AIPlanStepStatus.READY
        )
        return ActionDraftSpec(
            arguments=clean,
            status=status,
            preview=self.previewer(user, clean, context),
            context=context,
        )

    def apply(
        self,
        user,
        draft,
        arguments: Mapping[str, Any],
        context: Mapping[str, Any],
        now: datetime,
    ) -> ActionApplyResult:
        if not self.confirmation_required:
            raise CapabilityError(
                "unsafe_action_contract", "La acción no exige confirmación explícita.", 409
            )
        clean = self.validate(user, arguments, allow_incomplete=False)
        if clean.get("ambiguous_fields"):
            raise CapabilityError(
                "action_needs_input", "Corrige los campos ambiguos antes de confirmar.", 422
            )
        if context.get("needs_input") is True:
            raise CapabilityError(
                "action_needs_input",
                "Completa o corrige el contexto requerido antes de confirmar.",
                422,
            )
        # The domain handler must re-check the persisted server-owned context through
        # its official owner-scoped service at confirmation time.
        return self.apply_handler(user, draft, clean, context, now)

    def cancel(self, _user, _draft) -> None:
        return None


@dataclass(frozen=True)
class AIPlanStep:
    step_id: str
    action_capability_id: str
    domain: str
    entity: str
    operation: str
    arguments: dict[str, Any]
    dependencies: tuple[str, ...]
    status: AIPlanStepStatus
    preview: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AIPlanSpec:
    plan_id: str
    intent: str
    summary: str
    steps: tuple[AIPlanStep, ...]


@dataclass(frozen=True)
class AICapabilityManifest:
    domain_id: str
    label: str
    description: str
    entities: tuple[str, ...]
    metrics: tuple[MetricDefinition, ...]
    read_capabilities: tuple[ReadCapability, ...]
    action_capabilities: tuple[ActionCapability, ...] = ()
    periods: tuple[str, ...] = PERIODS
    comparisons: bool = False
    provenance_support: bool = True
    coverage_support: bool = True


@dataclass(frozen=True)
class AIIntentSpec:
    intent: AIIntent
    domain: str
    metrics: tuple[str, ...] = ()
    period: str = "30d"
    comparison: bool = False
    action: str | None = None
    options: tuple[tuple[str, str], ...] = ()

    def option(self, name: str) -> str | None:
        return dict(self.options).get(name)

    def as_query(self) -> dict[str, str | list[str]]:
        query: dict[str, str | list[str]] = {
            "intent": self.intent.value,
            "domain": self.domain,
            "period": self.period,
        }
        if self.metrics:
            query["metric"] = list(self.metrics)
        if self.comparison:
            query["comparison"] = "previous"
        if self.action:
            query["action"] = self.action
        query.update(dict(self.options))
        return query


@dataclass(frozen=True)
class AIIntentPlan:
    spec: AIIntentSpec
    tools: tuple[str, ...]
    action: ActionCapability | None = None
    actions: tuple[ActionCapability, ...] = ()


@dataclass(frozen=True)
class AIPreset:
    template_id: str
    intent: AIIntent
    domain: str
    metrics: tuple[str, ...] = ()
    action: str | None = None
    options: tuple[tuple[str, str], ...] = ()

    def spec(self, period: str) -> AIIntentSpec:
        return AIIntentSpec(
            intent=self.intent,
            domain=self.domain,
            metrics=self.metrics,
            period=period,
            comparison=self.intent == AIIntent.COMPARE,
            action=self.action,
            options=self.options,
        )


@dataclass(frozen=True)
class DataAvailability:
    domain: str
    record_count: int
    status: str
    reason: str | None = None
    metric_counts: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class AIExperience:
    id: str
    title: str
    description: str
    domain_label: str
    intent_label: str
    metric_label: str | None
    spec: AIIntentSpec
    href: str
    allowed_periods: tuple[str, ...] = PERIODS
    availability: str = "available"
    availability_reason: str | None = None


@dataclass(frozen=True)
class AdaptiveCatalog:
    recommendations: tuple[AIExperience, ...]
    domains: tuple[AICapabilityManifest, ...]
    experiences: tuple[AIExperience, ...]
    availability: Mapping[str, DataAvailability]
    build_ms: int = 0
    availability_ms: int = 0
    recommendations_ms: int = 0
