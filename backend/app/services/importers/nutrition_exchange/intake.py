"""Bounded JSON detection and the strict HTNX 1.0 adapter."""

import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from itertools import islice
from pathlib import Path

from app.services.nutrition_math import NutritionError, decimal
from app.services.validation import _load_validator

from .source import (
    Declaration,
    Diagnostic,
    Evidence,
    JsonValue,
    Observation,
    Profile,
    Quantity,
    SourceBatch,
    SourceFood,
    SourceMeal,
    issue,
    pointer,
)

MAX_BYTES = 10 * 1024 * 1024
MAX_DEPTH = 32
MAX_MEMBERS = 200_000
MAX_TEXT_LENGTH = 10_000
MAX_NUMBER_LENGTH = 80
MAX_NUMBER_EXPONENT = 1_000
MAX_FOODS = 250
MAX_DIAGNOSTICS = 50

_STRUCTURE = re.compile(r'["{}\[\],]')
_SURROGATE = re.compile(r"[\ud800-\udfff]")
_FORMAT = "health-tracker-nutrition"


class IntakeError(NutritionError):
    def __init__(self, diagnostics: tuple[Diagnostic, ...], status: int = 422):
        super().__init__(diagnostics[0].code, status=status)
        self.diagnostics = diagnostics


@dataclass(frozen=True, slots=True)
class ParsedSource:
    profile: Profile
    document: dict[str, JsonValue] = field(repr=False)
    batch: SourceBatch | None = None


def _invalid(code: str, path: str = "", status: int = 422) -> IntakeError:
    scope = "field" if path else "file"
    return IntakeError((issue(code, path=path, scope=scope, severity="invalid"),), status=status)


def _guard_structure(text: str) -> None:
    # Count structural tokens before the JSON decoder allocates the document.
    # A quoted string can contain arbitrary braces and commas.
    offset = depth = members = 0
    while token := _STRUCTURE.search(text, offset):
        offset = token.end()
        character = token[0]
        if character == '"':
            value, offset = json.decoder.scanstring(text, offset, True)
            if len(value) > MAX_TEXT_LENGTH:
                raise _invalid("limit_exceeded", status=413)
            if _SURROGATE.search(value):
                raise _invalid("invalid_json")
        elif character in "[{":
            depth += 1
            members += 1
            if depth > MAX_DEPTH:
                raise _invalid("limit_exceeded", status=413)
        elif character in "]}":
            depth -= 1
        else:
            members += 1
        if members > MAX_MEMBERS:
            raise _invalid("limit_exceeded", status=413)


class _InvalidNumber(Enum):
    NON_FINITE = "invalid_json"
    OUTSIDE_BUDGET = "numeric_limit"


def _parse_int(token: str) -> int | _InvalidNumber:
    if len(token) > MAX_NUMBER_LENGTH:
        return _InvalidNumber.OUTSIDE_BUDGET
    return int(token)


def _parse_decimal(token: str) -> Decimal | _InvalidNumber:
    if len(token) > MAX_NUMBER_LENGTH:
        return _InvalidNumber.OUTSIDE_BUDGET
    try:
        value = Decimal(token)
    except InvalidOperation:
        return _InvalidNumber.OUTSIDE_BUDGET
    if abs(value.as_tuple().exponent) > MAX_NUMBER_EXPONENT:
        return _InvalidNumber.OUTSIDE_BUDGET
    return value


def _non_finite(_token: str) -> _InvalidNumber:
    return _InvalidNumber.NON_FINITE


class _ObjectPairs(list[tuple[str, JsonValue]]):
    """An undecoded object, distinct from a JSON array."""


def _unique_keys(value, path: str = "") -> JsonValue:
    if isinstance(value, _InvalidNumber):
        raise _invalid(value.value, path)
    if isinstance(value, _ObjectPairs):
        result = {}
        for key, item in value:
            child = pointer(path, key)
            if key in result:
                raise _invalid("duplicate_key", child)
            result[key] = _unique_keys(item, child)
        return result
    if isinstance(value, list):
        return [_unique_keys(item, pointer(path, index)) for index, item in enumerate(value)]
    return value


def _decode(payload: bytes) -> dict[str, JsonValue]:
    if len(payload) > MAX_BYTES:
        raise _invalid("limit_exceeded", status=413)
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _invalid("invalid_utf8") from None

    try:
        _guard_structure(text)
        value = json.loads(
            text,
            object_pairs_hook=_ObjectPairs,
            parse_float=_parse_decimal,
            parse_int=_parse_int,
            parse_constant=_non_finite,
        )
    except json.JSONDecodeError:
        raise _invalid("invalid_json") from None
    except RecursionError:
        raise _invalid("limit_exceeded", status=413) from None
    document = _unique_keys(value)
    if not isinstance(document, dict):
        raise _invalid("unsupported_format")
    return document


def _profile(document: dict[str, JsonValue]) -> Profile:
    htnx = document.get("format") == _FORMAT
    standard = document.get("type") == "nutrition_import"
    daily = document.get("record_type") == "daily_nutrition"
    if sum((htnx, standard, daily)) > 1:
        raise _invalid("format_conflict")

    if htnx:
        if "version" in document and document["version"] != "1.0":
            raise _invalid("unsupported_version", "/version")
        return "htnx_1_0"
    if standard or daily:
        expected = "2.1" if standard else "1.0"
        if document.get("schema_version") != expected:
            raise _invalid("unsupported_version", "/schema_version")
        return "standard_2_1" if standard else "daily_1_0"

    if {"format", "record_type", "schema_version"} & document.keys():
        raise _invalid("unsupported_format")
    if any(isinstance(document.get(key), list) for key in ("meals", "comidas", "foods", "alimentos")):
        return "common"
    raise _invalid("unsupported_format")


def _arrays(document, names: tuple[str, ...]):
    if isinstance(document, dict):
        for name in names:
            value = document.get(name)
            if isinstance(value, list):
                yield name, value


def _check_food_budget(document: dict[str, JsonValue]) -> None:
    food_arrays = [(pointer("", key), array) for key, array in _arrays(document, ("foods", "alimentos"))]
    for meal_key, meals in _arrays(document, ("meals", "comidas")):
        if len(meals) > MAX_FOODS:
            raise _invalid("limit_exceeded", pointer("", meal_key), status=413)
        for index, meal in enumerate(meals):
            for key, foods in _arrays(meal, ("foods", "alimentos")):
                food_arrays.append((pointer("", meal_key, index, key), foods))

    count = 0
    for path, foods in food_arrays:
        count += len(foods)
        if count > MAX_FOODS:
            raise _invalid("limit_exceeded", path, status=413)
        for index, food in enumerate(foods):
            for key, ingredients in _arrays(food, ("ingredients", "ingredientes")):
                count += len(ingredients)
                if count > MAX_FOODS:
                    raise _invalid("limit_exceeded", pointer(path, index, key), status=413)


def _schema_root() -> Path:
    backend_root = Path(__file__).resolve().parents[4]
    candidates = (backend_root.parent / "schemas", backend_root / "schemas")
    return next(path for path in candidates if (path / "nutrition_exchange_1_0.schema.json").is_file())


def _validate_htnx(document: dict[str, JsonValue], schema_root: Path | None) -> None:
    root = schema_root if schema_root is not None else _schema_root()
    validator = _load_validator(str(root), "nutrition_exchange_1_0")
    diagnostics = []
    for error in islice(validator.iter_errors(document), MAX_DIAGNOSTICS):
        path = pointer("", *error.absolute_path)
        if error.validator == "maxItems":
            raise _invalid("limit_exceeded", path, status=413)
        diagnostics.append(issue("schema_error", path, "field" if path else "file", "invalid"))
    if diagnostics:
        raise IntakeError(tuple(dict.fromkeys(diagnostics)))


def _read_decimal(value: str | int | Decimal, path: str, *, positive: bool = False) -> Decimal:
    number = Decimal(value)
    # Trim only trailing fractional zeroes. Decimal.normalize can also round
    # the coefficient when it exceeds the ambient context's precision.
    sign, digits, exponent = number.as_tuple()
    if number.is_zero():
        number = Decimal(0)
    elif exponent < 0:
        end = len(digits)
        while digits[end - 1] == 0 and exponent < 0:
            exponent += 1
            end -= 1
        number = Decimal((sign, digits[:end], exponent))
    try:
        return decimal(number, positive=positive)
    except NutritionError:
        raise _invalid("numeric_limit", path) from None


def _quantity(raw: dict, path: str) -> Quantity:
    return Quantity(
        _read_decimal(raw["amount"], pointer(path, "amount"), positive=True),
        raw["unit"],
        raw.get("label"),
        Evidence(path, raw),
    )


def _observation(raw: dict, path: str, block: dict, name: str) -> Observation:
    value = _read_decimal(raw["value"], pointer(path, "value")) if "value" in raw else None
    limit = _read_decimal(raw["limit"], pointer(path, "limit"), positive=True) if "limit" in raw else None
    return Observation(
        state=raw.get("state", "known"),
        value=value,
        unit=raw.get("unit"),
        limit=limit,
        quality=raw.get("quality", block.get("quality", "declared")),
        evidence=Evidence(path, raw, source=raw.get("source", block.get("source")), note=raw.get("note")),
        name=name,
    )


def _declaration(raw: dict, path: str) -> Declaration:
    raw_basis = raw.get("basis")
    if raw_basis is None:
        basis_kind, basis = "absent", None
    elif raw_basis.get("kind") == "consumed":
        basis_kind, basis = "consumed", None
    else:
        basis_kind, basis = "reference", _quantity(raw_basis, pointer(path, "basis"))

    values = {
        key: _observation(observation, pointer(path, "values", key), raw, key)
        for key, observation in raw.get("values", {}).items()
    }
    additional = tuple(
        _observation(item["observation"], pointer(path, "additional_nutrients", index, "observation"), raw, item["name"])
        for index, item in enumerate(raw.get("additional_nutrients", ()))
    )
    metadata = {key: value for key, value in raw.items() if key not in {"values", "additional_nutrients"}}
    return Declaration(basis_kind, basis, values, additional, Evidence(path, metadata, source=raw.get("source"), note=raw.get("note")))


def _food(raw: dict, path: str) -> SourceFood:
    children = tuple(
        _food(item, pointer(path, "ingredients", index))
        for index, item in enumerate(raw.get("ingredients", ()))
    )
    metadata = {key: value for key, value in raw.items() if key not in {"quantity", "nutrition", "ingredients"}}
    return SourceFood(
        path=path,
        name=raw["name"],
        quantity=_quantity(raw["quantity"], pointer(path, "quantity")) if "quantity" in raw else None,
        nutrition=_declaration(raw["nutrition"], pointer(path, "nutrition")) if "nutrition" in raw else None,
        ingredients=children,
        evidence=(Evidence(path, metadata, note=raw.get("note")),),
    )


def _meal(raw: dict, path: str, default_date: date | None) -> SourceMeal:
    if "date" in raw:
        effective_date, date_path = date.fromisoformat(raw["date"]), pointer(path, "date")
    else:
        effective_date, date_path = default_date, "/date" if default_date is not None else None
    metadata = {key: value for key, value in raw.items() if key != "foods"}
    return SourceMeal(
        path=path,
        date=effective_date,
        date_path=date_path,
        type=raw.get("type"),
        name=raw.get("name"),
        foods=tuple(_food(food, pointer(path, "foods", index)) for index, food in enumerate(raw["foods"])),
        evidence=(Evidence(path, metadata, note=raw.get("note")),),
    )


def _adapt_htnx(document: dict[str, JsonValue]) -> SourceBatch:
    default_date = date.fromisoformat(document["date"]) if "date" in document else None
    metadata = {key: value for key, value in document.items() if key != "meals"}
    return SourceBatch(
        profile="htnx_1_0",
        adapter_version="htnx-1.0",
        destination_hint=document.get("destination"),
        default_date=default_date,
        meals=tuple(_meal(meal, pointer("", "meals", index), default_date) for index, meal in enumerate(document["meals"])),
        evidence=(Evidence("", metadata, note=document.get("note")),),
    )


def parse(payload: bytes, *, schema_root: Path | None = None) -> ParsedSource:
    """Decode once, identify the format, and adapt a valid explicit HTNX document."""
    document = _decode(payload)
    profile = _profile(document)
    if profile in {"htnx_1_0", "common"}:
        _check_food_budget(document)
    if profile == "htnx_1_0":
        _validate_htnx(document, schema_root)
        return ParsedSource(profile, document, _adapt_htnx(document))
    return ParsedSource(profile, document)
