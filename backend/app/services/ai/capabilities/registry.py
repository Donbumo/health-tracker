from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping

from app.services.ai.capabilities.domains import load_manifests
from app.services.ai.capabilities.types import (
    AICapabilityManifest,
    ActionCapability,
    AIIntent,
    AIIntentPlan,
    AIPlanSpec,
    AIPlanStep,
    AIIntentSpec,
    CapabilityError,
    MetricDefinition,
)
from app.services.ai.types import (
    AIProviderActionDefinition,
    AIProviderPlanProposal,
    AIProviderPlanStepProposal,
)


_ID = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*\Z")
_ACTION_ID = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+\Z")
_STEP_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_ACTION_ALIASES = {
    "record_food": "nutrition.food.create",
    "record_measurement": "body.measurement.create",
    "correct_measurement": "body.measurement.correct",
    "record_training_session": "training.session.create",
    "propose_goal_change": "goal.update",
}
_OPTION_VALUES = {
    "focus": {"deficit", "surplus", "goals", "history"},
    "meal_type": {"breakfast", "lunch", "dinner", "snack", "extra", "other"},
}


class AICapabilityRegistry:
    def __init__(self, manifests: Iterable[AICapabilityManifest] | None = None, *, tool_registry=None):
        if tool_registry is None:
            from app.services.ai.tools import AIToolRegistry

            tool_registry = AIToolRegistry()
        self.tool_registry = tool_registry
        self._manifests = tuple(manifests or load_manifests())
        self._by_domain = {item.domain_id: item for item in self._manifests}
        self._tools = {item.name: item for item in tool_registry.definitions}
        self._validate()

    @property
    def manifests(self) -> tuple[AICapabilityManifest, ...]:
        return self._manifests

    @property
    def metric_catalog(self) -> dict[str, MetricDefinition]:
        return {
            f"{manifest.domain_id}.{metric.id}": metric
            for manifest in self._manifests
            for metric in manifest.metrics
        }

    @property
    def action_capabilities(self) -> tuple[ActionCapability, ...]:
        return tuple(
            action
            for manifest in self._manifests
            for action in manifest.action_capabilities
            if action.available
        )

    @property
    def actions_by_id(self) -> dict[str, ActionCapability]:
        return {item.action_id: item for item in self.action_capabilities}

    def action(self, action_id: str) -> ActionCapability:
        capability = self.actions_by_id.get(str(action_id or "").strip())
        if capability is None:
            raise CapabilityError(
                "unsupported_action", "La acción AI solicitada no está disponible.", 409
            )
        return capability

    def provider_action_definitions(
        self, allowed_action_ids: Iterable[str] | None = None
    ) -> tuple[AIProviderActionDefinition, ...]:
        allowed = None if allowed_action_ids is None else set(allowed_action_ids)
        return tuple(
            AIProviderActionDefinition(
                action_capability_id=item.action_id,
                domain=item.domain,
                entity=item.entity,
                operation=item.operation,
                label=item.label,
                description=item.description,
                input_schema=dict(item.input_schema),
            )
            for item in self.action_capabilities
            if allowed is None or item.action_id in allowed
        )

    def resolve_action_proposal(
        self,
        user,
        proposal: AIProviderPlanProposal,
        *,
        allowed_action_ids: Iterable[str] | None = None,
        resource_context: Mapping[str, str] | None = None,
    ) -> AIPlanSpec:
        if not isinstance(proposal, AIProviderPlanProposal):
            raise CapabilityError("invalid_plan", "La propuesta AI no tiene un formato válido.", 502)
        if proposal.intent not in {"record", "correct", "propose_changes", "hybrid"}:
            raise CapabilityError("invalid_plan_intent", "La intención del plan no está permitida.", 502)
        if not isinstance(proposal.summary, str):
            raise CapabilityError("invalid_plan", "La propuesta AI no tiene un formato válido.", 502)
        summary = proposal.summary.strip()
        if not summary or len(summary) > 500 or not 1 <= len(proposal.steps) <= 10:
            raise CapabilityError("invalid_plan", "La propuesta AI no tiene un formato válido.", 502)
        if not isinstance(proposal.steps, tuple) or any(
            not isinstance(item, AIProviderPlanStepProposal) for item in proposal.steps
        ):
            raise CapabilityError("invalid_plan", "La propuesta AI no tiene un formato válido.", 502)
        allowed = None if allowed_action_ids is None else set(allowed_action_ids)
        step_ids = [item.step_id for item in proposal.steps]
        if (
            len(step_ids) != len(set(step_ids))
            or any(not _STEP_ID.fullmatch(item) for item in step_ids)
        ):
            raise CapabilityError("invalid_plan_steps", "Los pasos del plan no son válidos.", 502)
        known_steps = set(step_ids)
        graph = {}
        resolved_steps = []
        for item in proposal.steps:
            if not isinstance(item.dependencies, tuple) or any(
                dependency not in known_steps or dependency == item.step_id
                for dependency in item.dependencies
            ):
                raise CapabilityError("invalid_plan_dependencies", "Las dependencias del plan no son válidas.", 502)
            if len(item.dependencies) != len(set(item.dependencies)):
                raise CapabilityError("invalid_plan_dependencies", "Las dependencias del plan no son válidas.", 502)
            graph[item.step_id] = item.dependencies
            try:
                capability = self.action(item.action_capability_id)
            except CapabilityError as error:
                raise CapabilityError(
                    "unknown_action", "La propuesta contiene una acción no permitida.", 502
                ) from error
            if allowed is not None and capability.action_id not in allowed:
                raise CapabilityError(
                    "action_not_allowed_for_intent",
                    "La propuesta contiene una acción fuera del plan autorizado.",
                    502,
                )
            if proposal.intent == "record" and capability.operation != "create":
                raise CapabilityError(
                    "invalid_plan_operation",
                    "La operación propuesta no corresponde a la intención del plan.",
                    502,
                )
            if proposal.intent == "correct" and capability.operation not in {"correct", "update"}:
                raise CapabilityError(
                    "invalid_plan_operation",
                    "La operación propuesta no corresponde a la intención del plan.",
                    502,
                )
            step_context = None
            if resource_context is not None:
                if (
                    resource_context.get("action_capability_id")
                    == capability.action_id
                    and resource_context.get("domain") == capability.domain
                ):
                    step_context = resource_context
                elif len(proposal.steps) == 1:
                    raise CapabilityError(
                        "invalid_action_context",
                        "El contexto no corresponde a la acción propuesta.",
                        403,
                    )
            draft = capability.create_draft(
                user, item.arguments, resource_context=step_context
            )
            resolved_steps.append(
                AIPlanStep(
                    step_id=item.step_id,
                    action_capability_id=capability.action_id,
                    domain=capability.domain,
                    entity=capability.entity,
                    operation=capability.operation,
                    arguments=draft.arguments,
                    dependencies=item.dependencies,
                    status=draft.status,
                    preview=draft.preview,
                    context=draft.context,
                )
            )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise CapabilityError("invalid_plan_dependencies", "El plan contiene dependencias cíclicas.", 502)
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in graph[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in step_ids:
            visit(step_id)
        return AIPlanSpec(
            plan_id=str(uuid.uuid4()),
            intent=proposal.intent,
            summary=summary,
            steps=tuple(resolved_steps),
        )

    @property
    def capability_tokens(self) -> frozenset[str]:
        values = {f"tool:{name}" for name in self._tools}
        for action in self.action_capabilities:
            values.add(f"draft:{action.draft_type}")
            values.add(f"action:{action.action_id}")
        return frozenset(values)

    def manifest(self, domain: str) -> AICapabilityManifest:
        item = self._by_domain.get(str(domain or "").strip())
        if item is None:
            raise CapabilityError(
                "unsupported_domain",
                "El dominio AI solicitado no está soportado.",
                409,
            )
        return item

    def parse(self, values: Mapping) -> AIIntentSpec | None:
        raw_intent = str(values.get("intent") or "").strip()
        if not raw_intent:
            return None
        try:
            intent = AIIntent(raw_intent)
        except ValueError as error:
            raise CapabilityError(
                "unsupported_intent", "La intención AI solicitada no está soportada.", 409
            ) from error
        if hasattr(values, "getlist"):
            metrics = tuple(str(value).strip() for value in values.getlist("metric") if str(value).strip())
        else:
            raw_metrics = values.get("metric") or values.get("metrics") or ()
            if isinstance(raw_metrics, str):
                raw_metrics = raw_metrics.split(",")
            metrics = tuple(str(value).strip() for value in raw_metrics if str(value).strip())
        options = tuple(
            (key, str(values.get(key)).strip())
            for key in _OPTION_VALUES
            if values.get(key) not in (None, "")
        )
        spec = AIIntentSpec(
            intent=intent,
            domain=str(values.get("domain") or "").strip(),
            metrics=metrics,
            period=str(values.get("period") or "30d").strip(),
            comparison=str(values.get("comparison") or "").strip() == "previous",
            action=str(values.get("action") or "").strip() or None,
            options=options,
        )
        self.resolve(spec)
        return spec

    def resolve(self, spec: AIIntentSpec) -> AIIntentPlan:
        manifest = self.manifest(spec.domain)
        self._validate_spec(spec, manifest)
        if spec.intent == AIIntent.PROPOSE_CHANGES:
            if manifest.domain_id != "goals":
                raise CapabilityError(
                    "unsupported_combination",
                    "La propuesta de cambios sólo está habilitada para metas.",
                    409,
                )
            actions = tuple(
                item
                for item in manifest.action_capabilities
                if item.available and item.operation in {"create", "update"}
            )
            if not actions:
                raise CapabilityError(
                    "capability_not_implemented",
                    "No hay acciones de metas disponibles.",
                    409,
                )
            return AIIntentPlan(spec, ("get_goals_summary",), actions=actions)
        if spec.intent in {AIIntent.RECORD, AIIntent.CORRECT}:
            requested_action = _ACTION_ALIASES.get(spec.action, spec.action)
            action = next(
                (
                    item
                    for item in manifest.action_capabilities
                    if item.action_id == requested_action and item.available
                ),
                None,
            )
            if action is None:
                raise CapabilityError(
                    "unsupported_action",
                    "La acción AI solicitada no está disponible.",
                    409,
                )
            expected_intent = (
                AIIntent.CORRECT
                if action.operation in {"correct", "update"}
                else AIIntent.RECORD
            )
            if spec.intent != expected_intent:
                raise CapabilityError(
                    "invalid_action_operation",
                    "La intención no corresponde a la operación de la acción.",
                    409,
                )
            if any(name not in self._tools for name in action.read_tools):
                raise CapabilityError(
                    "capability_not_implemented",
                    "La acción AI todavía no tiene todas sus lecturas seguras.",
                    409,
                )
            return AIIntentPlan(spec, tuple(action.read_tools), action)

        requested = set(spec.metrics)
        capability = next(
            (
                item
                for item in manifest.read_capabilities
                if item.intent == spec.intent
                and spec.period in item.periods
                and (not requested or requested <= set(item.metrics))
            ),
            None,
        )
        if capability is None:
            raise CapabilityError(
                "unsupported_combination",
                "La combinación de dominio, intención, métricas y periodo no está soportada.",
                409,
            )
        unknown_tools = tuple(name for name in capability.tools if name not in self._tools)
        if unknown_tools:
            raise CapabilityError(
                "capability_not_implemented",
                "La capacidad AI todavía no tiene una implementación disponible.",
                409,
            )
        return AIIntentPlan(spec, tuple(dict.fromkeys(capability.tools)))

    def definitions_for(self, plan: AIIntentPlan) -> tuple:
        allowed = set(plan.tools)
        return tuple(item for item in self.tool_registry.definitions if item.name in allowed)

    def minimum_records(self, spec: AIIntentSpec) -> int:
        if spec.intent == AIIntent.PROPOSE_CHANGES:
            return 0
        if spec.intent in {AIIntent.RECORD, AIIntent.CORRECT}:
            return 0 if spec.intent == AIIntent.RECORD else 1
        plan = self.resolve(spec)
        manifest = self.manifest(spec.domain)
        requested = set(spec.metrics)
        capability = next(
            item
            for item in manifest.read_capabilities
            if item.intent == spec.intent
            and spec.period in item.periods
            and (not requested or requested <= set(item.metrics))
            and set(plan.tools) == set(item.tools)
        )
        return capability.minimum_records

    def _validate_spec(self, spec: AIIntentSpec, manifest: AICapabilityManifest) -> None:
        if spec.period not in manifest.periods:
            raise CapabilityError(
                "invalid_intent_period", "El periodo no está disponible para esta capacidad."
            )
        metric_ids = {item.id for item in manifest.metrics}
        if spec.domain == "all" and spec.metrics:
            raise CapabilityError(
                "invalid_intent_metrics", "El resumen general no acepta métricas arbitrarias."
            )
        if any(metric not in metric_ids for metric in spec.metrics):
            raise CapabilityError(
                "unsupported_metric", "Una métrica solicitada no pertenece al catálogo permitido.", 409
            )
        if len(set(spec.metrics)) != len(spec.metrics):
            raise CapabilityError("duplicate_metric", "Las métricas no pueden repetirse.")
        if spec.comparison and spec.intent != AIIntent.COMPARE:
            raise CapabilityError(
                "invalid_comparison", "La comparación solo se admite con la intención compare."
            )
        if spec.intent == AIIntent.COMPARE and not manifest.comparisons:
            raise CapabilityError(
                "comparison_not_supported", "El dominio no soporta comparaciones.", 409
            )
        if spec.intent in {AIIntent.RECORD, AIIntent.CORRECT}:
            if spec.period != "today" or not spec.action:
                raise CapabilityError(
                    "invalid_action_intent", "La acción requiere action y el periodo today."
                )
        elif spec.action is not None:
            raise CapabilityError(
                "invalid_action_intent", "Una consulta de lectura no puede declarar acciones."
            )
        for key, value in spec.options:
            if value not in _OPTION_VALUES.get(key, set()):
                raise CapabilityError(
                    "invalid_intent_option", "Una opción de intención no está permitida."
                )
        metrics = {item.id: item for item in manifest.metrics}
        if spec.intent == AIIntent.TREND and any(
            not metrics[item].trend_supported for item in spec.metrics
        ):
            raise CapabilityError("trend_not_supported", "La métrica no soporta tendencia.", 409)
        if spec.intent == AIIntent.COMPARE and any(
            not metrics[item].comparison_supported for item in spec.metrics
        ):
            raise CapabilityError(
                "comparison_not_supported", "La métrica no soporta comparación.", 409
            )

    def _validate(self) -> None:
        if len(self._by_domain) != len(self._manifests):
            raise RuntimeError("AI capability domain ids must be unique.")
        all_action_ids = [
            action.action_id
            for manifest in self._manifests
            for action in manifest.action_capabilities
        ]
        if len(all_action_ids) != len(set(all_action_ids)):
            raise RuntimeError("AI action ids must be globally unique.")
        for manifest in self._manifests:
            if not _ID.fullmatch(manifest.domain_id):
                raise RuntimeError(f"Invalid AI capability domain: {manifest.domain_id}")
            if not manifest.entities:
                raise RuntimeError(f"AI capability domain has no entities: {manifest.domain_id}")
            if not manifest.read_capabilities and not manifest.action_capabilities:
                raise RuntimeError(f"AI capability domain has no capabilities: {manifest.domain_id}")
            if not manifest.periods or any(item not in ("today", "7d", "30d", "90d") for item in manifest.periods):
                raise RuntimeError(f"Invalid periods for AI capability domain: {manifest.domain_id}")
            metric_ids = [item.id for item in manifest.metrics]
            if len(metric_ids) != len(set(metric_ids)):
                raise RuntimeError(f"Duplicate metric in AI capability domain: {manifest.domain_id}")
            for metric in manifest.metrics:
                if not _ID.fullmatch(metric.id) or not metric.aggregations:
                    raise RuntimeError(f"Invalid AI metric: {manifest.domain_id}.{metric.id}")
                if not 0 <= metric.display_precision <= 6:
                    raise RuntimeError(f"Invalid metric precision: {manifest.domain_id}.{metric.id}")
            for capability in manifest.read_capabilities:
                if not capability.tools:
                    raise RuntimeError(f"Read capability has no tool: {manifest.domain_id}.{capability.intent}")
                if any(item not in metric_ids for item in capability.metrics):
                    raise RuntimeError(f"Read capability has unknown metric: {manifest.domain_id}.{capability.intent}")
                if any(item not in manifest.periods for item in capability.periods):
                    raise RuntimeError(f"Read capability has invalid period: {manifest.domain_id}.{capability.intent}")
                for tool_name in capability.tools:
                    definition = self._tools.get(tool_name)
                    if definition is None:
                        continue
                    metadata = definition.capability
                    if metadata is None:
                        raise RuntimeError(f"AI tool has no capability metadata: {tool_name}")
                    if manifest.domain_id not in metadata.domains:
                        raise RuntimeError(
                            f"AI tool/domain mismatch: {tool_name}/{manifest.domain_id}"
                        )
                    if (
                        capability.intent != AIIntent.PROPOSE_CHANGES
                        and capability.intent.value not in metadata.operations
                    ):
                        raise RuntimeError(
                            f"AI tool/intent mismatch: {tool_name}/{capability.intent.value}"
                        )
            action_ids = [item.action_id for item in manifest.action_capabilities]
            if len(action_ids) != len(set(action_ids)):
                raise RuntimeError(f"Duplicate action in AI capability domain: {manifest.domain_id}")
            for action in manifest.action_capabilities:
                if not _ACTION_ID.fullmatch(action.action_id):
                    raise RuntimeError(f"Invalid AI action id: {action.action_id}")
                if action.domain != manifest.domain_id or action.entity not in manifest.entities:
                    raise RuntimeError(f"AI action/domain mismatch: {action.action_id}")
                if action.operation not in {"create", "correct", "update"}:
                    raise RuntimeError(f"Invalid AI action operation: {action.action_id}")
                if not action.confirmation_required:
                    raise RuntimeError(f"AI write action must require confirmation: {action.action_id}")
                if set(action.required_fields) - set(action.supported_fields):
                    raise RuntimeError(f"AI action has unknown required fields: {action.action_id}")
                if set(action.optional_fields) - set(action.supported_fields):
                    raise RuntimeError(f"AI action has unknown optional fields: {action.action_id}")
                if set(action.required_fields) & set(action.optional_fields):
                    raise RuntimeError(f"AI action fields overlap: {action.action_id}")
                if set(action.required_fields) | set(action.optional_fields) != set(action.supported_fields):
                    raise RuntimeError(f"AI action fields are not fully classified: {action.action_id}")
                if set(action.input_schema.get("properties", {})) != set(action.supported_fields):
                    raise RuntimeError(f"AI action schema/fields mismatch: {action.action_id}")
                if any(name not in self._tools for name in action.required_read_capabilities):
                    raise RuntimeError(f"AI action has unknown read capability: {action.action_id}")
