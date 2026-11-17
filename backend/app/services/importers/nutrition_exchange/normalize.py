"""Read-only nutrition semantics for the Phase B exchange review."""

from collections import Counter
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Literal
from unicodedata import normalize

from app.services.nutrition_math import NUTRIENTS, NutritionError, decimal, ingredient, precise, summarize, summarize_parts
from app.services.nutrition_sources import finite_source_number

from .source import Diagnostic, Evidence, Observation, Quantity, SourceBatch, SourceFood, SourceMeal, issue, pointer


NOMINAL = {"piece", "portion"}
Authority = Literal["dish", "ingredients"]


@dataclass(frozen=True)
class Equivalence:
    """Owner-verified basis units per unit of the consumed quantity.

    Scope and inputs are bound by FoodDecision, not provided by the document.
    """

    factor: Decimal
    source: str


@dataclass(frozen=True)
class FoodDecision:
    original: SourceFood
    authority: Authority | None = None
    equivalence: Equivalence | None = None


@dataclass(frozen=True)
class FoodReview:
    meal: SourceMeal
    food: SourceFood
    quantity: Quantity | None
    basis: Quantity | None
    values: dict[str, Observation]
    contributions: dict[str, dict] | None
    authority: Authority | None
    diagnostics: tuple[Diagnostic, ...] = ()
    equivalence: Equivalence | None = None


@dataclass(frozen=True)
class BatchReview:
    source: SourceBatch
    destination: str | None
    records: tuple[FoodReview, ...]
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class DuplicateCandidate:
    day: date
    meal_type: str | None
    name: str
    amount: Decimal
    unit: str
    label: str | None


@dataclass(frozen=True)
class _Calculated:
    quantity: Quantity
    basis: Quantity
    values: dict[str, Observation]
    contributions: dict[str, dict]
    summary: dict[str, dict]


def canonical_unit(unit):
    return "portion" if unit in NOMINAL else unit


def label(value):
    return normalize("NFC", value).strip() if isinstance(value, str) else ""


def vector(values):
    """Build a sparse, unscaled vector accepted by the existing Decimal engine."""
    result = {}
    for key, observation in values.items():
        item = {"state": observation.state, "unit": NUTRIENTS[key][1]}
        if observation.value is not None:
            item["value"] = format(observation.value, "f")
        if observation.limit is not None:
            item["limit"] = format(observation.limit, "f")
        result[key] = item
    return result


def _scaled(quantity, basis, values):
    from app.services.nutrition_import import meal_snapshot

    if not any(item.state == "known" for item in values.values()):
        return None
    quality = {key: item.quality for key, item in values.items()}
    entry = {
        "name": "",
        "portion_amount": format(quantity.amount, "f"),
        "portion_unit": canonical_unit(quantity.unit),
        "composition": {"complete": False, "total_mass_g": format(quantity.amount, "f") if quantity.unit == "g" else None},
        "declaration": {
            "basis_amount": format(basis.amount, "f"),
            "basis_unit": canonical_unit(basis.unit),
            "nutrients": vector(values),
            "confirmed": True,  # Internal snapshot calculation only, outside any writer or plan.
            "provenance": {"nutrient_quality": quality},
        },
    }
    snapshot = meal_snapshot(entry, [], "UTC")
    return _Calculated(quantity, basis, values, snapshot["declared_nutrition"]["nutrients"], snapshot["summary"])


def _basis(food):
    declaration = food.nutrition
    if declaration is None or declaration.basis_kind == "absent":
        return None
    return food.quantity if declaration.basis_kind == "consumed" else declaration.basis


def _direct(food, decision=None, calculate=_scaled):
    quantity = food.quantity
    declaration = food.nutrition
    if quantity is None or declaration is None or not declaration.values:
        return None, ()
    basis = _basis(food)
    if basis is None:
        return None, (issue("missing_basis", declaration.evidence.path, "field"),)
    same_nominal = quantity.unit not in NOMINAL or (
        bool(label(quantity.label)) and label(quantity.label) == label(basis.label)
    )
    if quantity.unit != basis.unit or not same_nominal:
        if decision is None or decision.equivalence is None:
            code = "missing_equivalence" if quantity.unit == basis.unit or NOMINAL.intersection({quantity.unit, basis.unit}) else "incompatible_units"
            return None, (issue(code, basis.evidence.path, "field"),)
        with_equivalence = decision.equivalence
        try:
            if not with_equivalence.source.strip() or len(with_equivalence.source) > 500:
                raise NutritionError("Falta la procedencia de esta equivalencia.")
            factor = decimal(with_equivalence.factor, positive=True)
            amount = decimal((quantity.amount * factor).normalize(), positive=True)
        except NutritionError:
            return None, (issue("invalid_equivalence", basis.evidence.path, "field"),)
        quantity = replace(quantity, amount=amount, unit=basis.unit, label=basis.label)
    try:
        return calculate(quantity, basis, declaration.values), ()
    except NutritionError:
        return None, (issue("unrepresentable_contribution", declaration.evidence.path, "field"),)


def _component(quantity, basis, values):
    if not any(item.state == "known" for item in values.values()):
        return None
    part = ingredient(
        {"basis_amount": basis.amount, "basis_unit": basis.unit, "nutrients": vector(values)},
        quantity.amount, quantity.unit,
    )
    return _Calculated(quantity, basis, values, part["contribution"], summarize([part]))


def _ingredients(food):
    """Only derive a total when the parent's metric quantity is fully accounted for."""
    quantity = food.quantity
    components = [item.quantity for item in food.ingredients]
    if not components or quantity is None or quantity.unit not in {"g", "ml"}:
        return None
    if any(item is None or item.unit != quantity.unit for item in components):
        return None
    if sum((item.amount for item in components), Decimal(0)) != quantity.amount:
        return None
    calculated = [_direct(item, calculate=_component)[0] for item in food.ingredients]
    if any(part is None for part in calculated):
        return None

    total = summarize_parts([part.summary for part in calculated])
    keys = set.intersection(*(set(part.values) for part in calculated))
    values = {}
    for key in sorted(keys):
        parts = [part.contributions[key] for part in calculated]
        source_observations = [part.values[key] for part in calculated]
        state = parts[0]["state"]
        if any(part["state"] != state for part in parts):
            continue
        quality = "estimated" if any(item.quality == "estimated" for item in source_observations) else "declared"
        evidence = Evidence(food.path, [item.evidence.path for item in source_observations], rule="ingredient_sum")
        values[key] = Observation(
            state=state,
            value=Decimal(finite_source_number(total[key]["value"])) if state == "known" else None,
            unit=NUTRIENTS[key][1],
            limit=Decimal(finite_source_number(sum(Decimal(part["limit"]) for part in parts)))
            if state == "below_limit" else None,
            quality=quality,
            evidence=evidence,
        )
    return _scaled(quantity, quantity, values)


def _attached(diagnostic, path):
    return diagnostic.path == path or diagnostic.path.startswith(path + "/")


def _review_food(meal, food, diagnostics, decision):
    issues = list(diagnostics)
    stale = decision is not None and decision.original != food
    if stale:
        issues.append(issue("stale_revision", food.path, "food"))
        decision = None
    if not food.name:
        issues.append(issue("missing_name", food.path, "food"))
    if food.quantity is None:
        issues.append(issue("missing_quantity", pointer(food.path, "quantity"), "field"))
    if food.nutrition:
        issues.extend(issue("unsupported_nutrient", extra.evidence.path, "field", "warning")
                      for extra in food.nutrition.additional)
    source_blocked = stale or any(item.severity != "warning" for item in diagnostics)
    direct, basis_issues = (None, ()) if source_blocked else _direct(food, decision)
    try:
        derived = None if source_blocked else _ingredients(food)
    except NutritionError:
        derived = None

    choice = decision.authority if decision else None
    authority = None
    selected = None
    if direct and derived and choice not in {"dish", "ingredients"}:
        issues.append(issue("conflicting_authority", food.path, "food"))
    elif derived and choice == "ingredients":
        selected, authority = derived, "ingredients"
    elif direct and choice != "ingredients":
        selected, authority = direct, "dish"
    elif derived and not basis_issues and not (food.nutrition and food.nutrition.values) and choice is None:
        selected, authority = derived, "ingredients"
    else:
        issues.extend(basis_issues)
        if food.ingredients:
            code = "conflicting_authority" if derived or direct else "unverified_composition"
            issues.append(issue(code, pointer(food.path, "ingredients"), "field"))
        elif not basis_issues and not source_blocked and food.quantity is not None:
            issues.append(issue("missing_nutrition", pointer(food.path, "nutrition"), "field"))

    source_values = food.nutrition.values if food.nutrition else {}
    return FoodReview(
        meal=meal, food=food,
        quantity=selected.quantity if selected else food.quantity,
        basis=selected.basis if selected else _basis(food),
        values=selected.values if selected else source_values,
        contributions=selected.contributions if selected else None,
        authority=authority, diagnostics=tuple(issues),
        equivalence=decision.equivalence if decision and authority == "dish" and selected.quantity != food.quantity else None,
    )


def _duplicate_candidate(record):
    food, meal = record.food, record.meal
    quantity = food.quantity
    if meal.date is not None and food.name and quantity is not None:
        return DuplicateCandidate(meal.date, meal.type, label(food.name).casefold(), quantity.amount,
                                  quantity.unit, label(quantity.label) or None)
    return None


@precise
def evaluate(batch: SourceBatch, *, destination=None, decisions=None, aggregate_dates=frozenset(), existing=()):
    """Evaluate without storage or transport. Decisions come from trusted review code."""
    destination = destination or batch.destination_hint
    decisions = decisions or {}
    file_issues = [item for item in batch.diagnostics if item.scope == "file"]
    if destination is None:
        file_issues.append(issue("missing_destination"))
    elif destination != "consumed":
        # Current non-consumption destinations require reviewed product/catalog identities.
        file_issues.append(issue("destination_requires_review"))

    records = []
    for meal in batch.meals:
        meal_issues = [item for item in batch.diagnostics if item.scope != "file" and
                       not any(_attached(item, food.path) for food in meal.foods) and _attached(item, meal.path)]
        if not meal.foods:
            file_issues.extend(meal_issues)
            continue
        if destination == "consumed":
            if meal.date is None:
                meal_issues.append(issue("missing_date", meal.date_path or pointer(meal.path, "date"), "meal"))
            if meal.type is None:
                meal_issues.append(issue("missing_meal_type", pointer(meal.path, "type"), "meal"))
            if meal.date in aggregate_dates:
                meal_issues.append(issue("day_overlap", meal.date_path or meal.path, "meal"))
        for food in meal.foods:
            food_issues = [item for item in batch.diagnostics if item.scope != "file" and _attached(item, food.path)]
            record = _review_food(meal, food, food_issues, decisions.get(food.path))
            records.append(replace(record, diagnostics=tuple(meal_issues) + record.diagnostics))

    if destination == "consumed":
        keys = [_duplicate_candidate(record) for record in records]
        counts = Counter(key for key in keys if key is not None)
        previous = set(existing)
        records = [
            replace(record, diagnostics=record.diagnostics + (issue("possible_duplicate", record.food.path, "food"),))
            if key is not None and (counts[key] > 1 or key in previous) else record
            for record, key in zip(records, keys, strict=True)
        ]
    return BatchReview(batch, destination, tuple(records), tuple(file_issues))
