from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AIUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class AIProviderCapabilities:
    supports_tools: bool = False
    supports_images: bool = False
    supports_structured_output: bool = False
    supports_usage: bool = False
    remote: bool = False


@dataclass(frozen=True)
class AIProviderMessage:
    role: str
    content: str


@dataclass(frozen=True)
class AIToolCapabilityMetadata:
    domains: tuple[str, ...]
    entities: tuple[str, ...]
    metrics: tuple[str, ...]
    operations: tuple[str, ...]


@dataclass(frozen=True)
class AIToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    capability: AIToolCapabilityMetadata | None = None


@dataclass(frozen=True)
class AIProviderToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class AIProviderDraft:
    draft_type: str
    payload: dict[str, Any]
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AIProviderToolResult:
    call_id: str
    name: str
    ok: bool
    data: dict[str, Any] | None = None
    evidence: tuple[dict[str, Any], ...] = ()
    error_code: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AIProviderRequest:
    model: str
    messages: tuple[AIProviderMessage, ...]
    tools: tuple[AIToolDefinition, ...]
    tool_results: tuple[AIProviderToolResult, ...] = ()
    safety_instructions: str = ""
    timeout_seconds: float = 20
    draft_types: tuple[str, ...] | None = None
    require_tool: bool = False


@dataclass(frozen=True)
class AIProviderResponse:
    content: str | None = None
    tool_calls: tuple[AIProviderToolCall, ...] = ()
    drafts: tuple[AIProviderDraft, ...] = ()
    usage: AIUsage = field(default_factory=AIUsage)


@dataclass(frozen=True)
class AIToolExecution:
    data: dict[str, Any]
    evidence: tuple[dict[str, Any], ...] = ()
