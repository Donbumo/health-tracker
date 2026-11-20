"""Observations from an import document, before resolving review decisions."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal, TypeAlias


JsonValue: TypeAlias = str | int | Decimal | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
Profile: TypeAlias = Literal["htnx_1_0", "standard_2_1", "daily_1_0", "common"]
Scope: TypeAlias = Literal["file", "meal", "food", "field"]
Severity: TypeAlias = Literal["warning", "decision", "invalid"]


@dataclass(frozen=True, slots=True)
class Evidence:
    path: str
    raw: JsonValue = field(repr=False)
    rule: str | None = None
    conversion: str | None = None
    source: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    path: str
    scope: Scope
    severity: Severity
    message_key: str
    action_key: str


def issue(
    code: str, path: str = "", scope: Scope = "file", severity: Severity = "decision"
) -> Diagnostic:
    return Diagnostic(code, path, scope, severity, f"nutrition_exchange.{code}", f"nutrition_exchange.{code}.action")


def pointer(path: str, *parts: str | int) -> str:
    return path + "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


@dataclass(frozen=True, slots=True)
class Quantity:
    amount: Decimal
    unit: str
    label: str | None
    evidence: Evidence


@dataclass(frozen=True, slots=True)
class Observation:
    state: Literal["known", "unknown", "trace", "below_limit"]
    value: Decimal | None
    unit: str | None
    limit: Decimal | None
    quality: str
    evidence: Evidence
    name: str | None = None


@dataclass(frozen=True, slots=True)
class Declaration:
    basis_kind: Literal["reference", "consumed", "absent"]
    basis: Quantity | None
    values: dict[str, Observation]
    additional: tuple[Observation, ...]
    evidence: Evidence


@dataclass(frozen=True, slots=True)
class SourceFood:
    path: str
    name: str | None
    quantity: Quantity | None
    nutrition: Declaration | None
    ingredients: tuple["SourceFood", ...] = ()
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceMeal:
    path: str
    date: date | None
    date_path: str | None
    type: str | None
    name: str | None
    foods: tuple[SourceFood, ...]
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceBatch:
    profile: Profile
    adapter_version: str
    destination_hint: str | None
    default_date: date | None
    meals: tuple[SourceMeal, ...]
    diagnostics: tuple[Diagnostic, ...] = ()
    evidence: tuple[Evidence, ...] = ()
