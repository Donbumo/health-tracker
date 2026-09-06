from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from app.services.ai.capabilities.domains import load_manifests
from app.services.ai.capabilities.types import (
    AICapabilityManifest,
    ActionCapability,
    AIIntent,
    AIIntentPlan,
    AIIntentSpec,
    CapabilityError,
    MetricDefinition,
)


_ID = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*\Z")
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
        if spec.intent in {AIIntent.RECORD, AIIntent.CORRECT}:
            action = next(
                (
                    item
                    for item in manifest.action_capabilities
                    if item.action_id == spec.action and item.available
                ),
                None,
            )
            if action is None:
                raise CapabilityError(
                    "unsupported_action",
                    "La acción AI solicitada no está disponible.",
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
                    if capability.intent.value not in metadata.operations:
                        raise RuntimeError(
                            f"AI tool/intent mismatch: {tool_name}/{capability.intent.value}"
                        )
            action_ids = [item.action_id for item in manifest.action_capabilities]
            if len(action_ids) != len(set(action_ids)):
                raise RuntimeError(f"Duplicate action in AI capability domain: {manifest.domain_id}")
