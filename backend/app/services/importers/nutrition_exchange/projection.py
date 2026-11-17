"""Adapt exchange evidence to the existing review and canonical writer boundary."""
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from typing import TYPE_CHECKING

from app.services.nutrition_math import NutritionError

from .normalize import canonical_unit, label, vector
from .source import Declaration, Evidence, Observation, Quantity, SourceFood, pointer

if TYPE_CHECKING:
    from .normalize import BatchReview, FoodReview


EXCHANGE_PROFILES = frozenset({"htnx_1_0", "nutrition_exchange_common"})
DESTINATIONS = {"consumed": "consumed", "plan": "plan", "recipe": "recipes", "product": "products"}


def _number(amount: Decimal | None) -> str | None:
    return format(amount, "f") if amount is not None else None


def _evidence(evidence: Evidence) -> dict:
    # Preserve JSON number versus string without a float or a custom DB codec.
    # Paths are relative to this evidence's raw fragment.
    decimal_paths = []

    def encode(value, path):
        if isinstance(value, Decimal):
            decimal_paths.append(path)
            return str(value)
        if isinstance(value, dict):
            return {key: encode(child, pointer(path, key))
                    for key, child in value.items()}
        if isinstance(value, list):
            return [encode(child, pointer(path, index)) for index, child in enumerate(value)]
        return value

    raw = encode(evidence.raw, "")
    return {
        "path": evidence.path,
        "raw": raw,
        "decimal_paths": decimal_paths,
        **{name: value for name, value in {
            "rule": evidence.rule, "conversion": evidence.conversion,
            "source": evidence.source, "note": evidence.note,
        }.items() if value is not None},
    }


def _quantity(quantity: Quantity | None) -> dict | None:
    if quantity is None:
        return None
    return {"amount": _number(quantity.amount), "unit": quantity.unit, "label": quantity.label,
            "evidence": _evidence(quantity.evidence)}


def _observation(observation: Observation) -> dict:
    return {
        "state": observation.state,
        "value": _number(observation.value),
        "unit": observation.unit,
        "limit": _number(observation.limit),
        "quality": observation.quality,
        "evidence": _evidence(observation.evidence),
    }


def _declaration(declaration: Declaration | None) -> dict | None:
    if declaration is None:
        return None
    return {
        "basis_kind": declaration.basis_kind,
        "basis": _quantity(declaration.basis),
        "observations": {key: _observation(value) for key, value in declaration.values.items()},
        "additional_nutrients": [dict(_observation(value), name=value.name) for value in declaration.additional],
        "evidence": _evidence(declaration.evidence),
    }


def _food(food: SourceFood) -> dict:
    return {
        "path": food.path,
        "name": food.name,
        "quantity": _quantity(food.quantity),
        "nutrition": _declaration(food.nutrition),
        "ingredients": [_food(child) for child in food.ingredients],
        "evidence": [_evidence(value) for value in food.evidence],
    }


def review_row(record: FoodReview) -> dict:
    """Create the JSON row consumed by the current review service."""
    food, meal = record.food, record.meal
    quantity, basis = record.quantity, record.basis
    values = record.values
    if not values and food.nutrition:
        # Pending rows still expose the source declaration and its qualified states.
        values = food.nutrition.values
    quality = {key: value.quality for key, value in values.items()}
    quality_set = set(quality.values())
    source_quality = "mixed" if "estimated" in quality_set and len(quality_set) > 1 else (
        next(iter(quality_set)) if len(quality_set) == 1 else "declared")
    declaration = vector(values)
    for key, item in declaration.items():
        item["provenance"] = {"source_path": values[key].evidence.path, "quality": quality[key]}
    equivalence = record.equivalence
    date = meal.date.isoformat() if meal.date else None
    return {
        "name": food.name,
        "date": date,
        "meal_type": meal.type,
        "amount": _number(quantity.amount) if quantity else None,
        "unit": canonical_unit(quantity.unit) if quantity else None,
        "unit_label": label(quantity.label) if quantity and quantity.label else None,
        "basis_amount": _number(basis.amount) if basis else None,
        "basis_unit": canonical_unit(basis.unit) if basis else None,
        "basis_label": label(basis.label) if basis and basis.label else None,
        "composition_complete": False,
        "ingredients": [],
        "resolution": "declared",
        "confirmed": False,
        "skip": False,
        "warnings": [],
        "declaration": declaration,
        "nutrient_quality": quality,
        "source_quality": source_quality,
        "exchange_diagnostics": [asdict(item) for item in record.diagnostics],
        "exchange_preview_available": bool(record.contributions),
        "evidence": {"path": food.path},
        "original": {
            "name": food.name, "date": date, "meal_type": meal.type,
            "amount": _number(food.quantity.amount) if food.quantity else None,
            "unit": food.quantity.unit if food.quantity else None,
        },
        "source_provenance": {
            "meal": {"path": meal.path, "date_path": meal.date_path, "name": meal.name,
                     "evidence": [_evidence(value) for value in meal.evidence]},
            "food": _food(food),
            "authority": record.authority,
            "selected_observations": {key: _observation(value) for key, value in values.items()}
            if record.authority == "ingredients" else {},
            "reviewed_quantity": _quantity(quantity),
            "reviewed_basis": _quantity(basis),
            "equivalence": {"factor": _number(equivalence.factor), "source": equivalence.source}
            if equivalence else None,
        },
    }


def extracted(result: BatchReview, document: dict, sha: str) -> dict:
    """Build the extractor output for the existing technical draft transaction."""
    batch = result.source
    profile = "nutrition_exchange_common" if batch.profile == "common" else batch.profile
    rows = [review_row(record) for record in result.records]
    for row in rows:
        row["evidence"].update(sha256=sha, profile=profile, adapter_version=batch.adapter_version)
    return {
        "profile": profile,
        "classification_hint": DESTINATIONS.get(result.destination, ""),
        "rows": rows,
        "text": "",
        "warnings": [],
        "document_notes": [document["note"]] if isinstance(document.get("note"), str) else [],
        "source": {"sha256": sha, "adapter_version": batch.adapter_version,
                   "exchange": [_evidence(item) for item in batch.evidence]},
        "exchange_diagnostics": [asdict(item) for item in result.diagnostics],
    }


def project(row):
    """Run the canonical preview checks on a prepared exchange draft."""
    from app.services.nutrition_import import assert_pending
    from app.services.nutrition_import_review import document

    if row.source_json.get("profile") not in EXCHANGE_PROFILES:
        raise NutritionError("La revisión corresponde a otro formato nutricional.")
    assert_pending(row, row.revision)
    return document(row)
