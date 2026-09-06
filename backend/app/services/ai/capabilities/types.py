from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping


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


@dataclass(frozen=True)
class ActionCapability:
    action_id: str
    domain: str
    entity: str
    supported_fields: tuple[str, ...]
    draft_type: str
    confirmation_required: bool
    service: str
    read_tools: tuple[str, ...] = ()
    available: bool = True
    blocker: str | None = None


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
