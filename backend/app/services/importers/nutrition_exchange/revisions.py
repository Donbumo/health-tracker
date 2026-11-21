"""Validated changes to a source review, reapplied to the retained original."""

import copy
from dataclasses import replace
from datetime import date
from hashlib import sha256
import json

from app.extensions import db
from app.services.nutrition_math import NutritionError, decimal

from . import normalize
from .projection import EXCHANGE_PROFILES, _food
from .source import Evidence, Quantity

MEAL_TYPES = ("breakfast", "lunch", "dinner", "snack", "other")
UNITS = ("g", "ml", "piece", "portion")
UNIT_NAMES = {"g": "g", "ml": "ml", "piece": "pieza", "portion": "porción"}


def _number(raw):
    return format(decimal(raw, positive=True), "f")


def _date(raw):
    try:
        value = date.fromisoformat(raw)
    except (ValueError, TypeError) as error:
        raise NutritionError("Elige una fecha de calendario válida.") from error
    if value.year < 1000 or value.isoformat() != raw:
        raise NutritionError("Elige una fecha de calendario válida.")
    return value


def _quantity(form, prefix):
    unit = form.get(prefix + "_unit")
    label = normalize.label(form.get(prefix + "_label"))
    if unit not in UNITS or (unit in normalize.NOMINAL and not label) or len(label) > 200:
        raise NutritionError("Selecciona la unidad y describe la pieza o porción cuando corresponda.")
    return {"amount": _number(form.get(prefix + "_amount")), "unit": unit,
            "label": label if unit in normalize.NOMINAL else None}


def adjusted(batch, options):
    """Apply owner-provided facts while retaining the separate source IR."""
    meals = []
    decisions = {}
    for meal in batch.meals:
        meal_edit = options.get("meals", {}).get(meal.path, {})
        foods = []
        for food in meal.foods:
            edit = options.get("foods", {}).get(food.path, {})
            current = food
            if "quantity" in edit:
                current = replace(current, quantity=_edited_quantity(food, edit["quantity"]))
            if current.nutrition:
                declaration = current.nutrition
                kind = edit.get("basis_kind", declaration.basis_kind)
                basis = declaration.basis if kind == "reference" else None
                if "basis" in edit:
                    basis = _edited_quantity(food, edit["basis"])
                if "quantity" in edit and "basis_kind" not in edit and kind == "consumed":
                    kind = "absent"
                current = replace(current, nutrition=replace(declaration, basis_kind=kind, basis=basis))
            foods.append(current)
            equivalence = edit.get("equivalence")
            if edit.get("authority") or equivalence:
                decisions[food.path] = normalize.FoodDecision(
                    current, authority=edit.get("authority"),
                    equivalence=normalize.Equivalence(decimal(equivalence["factor"], positive=True), equivalence["source"])
                    if equivalence else None,
                )
        meals.append(replace(
            meal, foods=tuple(foods),
            date=_date(meal_edit["date"]) if "date" in meal_edit else meal.date,
            type=meal_edit.get("type", meal.type),
        ))
    return replace(batch, meals=tuple(meals), destination_hint=options.get("destination", batch.destination_hint)), decisions


def _edited_quantity(food, value):
    return Quantity(decimal(value["amount"], positive=True), value["unit"], value["label"],
                    Evidence(food.path, value, rule="owner_review"))


def _stamp(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str).encode()).hexdigest()


def decorate(found, result, original, options, existing, days):
    source_rows = {food.path: (meal, food) for meal in original.meals for food in meal.foods}
    candidates = [normalize._duplicate_candidate(record) for record in result.records]
    for index, (row, record) in enumerate(zip(found["rows"], result.records, strict=True)):
        path = record.food.path
        source_meal, source_food = source_rows[path]
        provenance = row["source_provenance"]
        edits = options.get("foods", {}).get(path)
        if edits or record.meal != source_meal:
            provenance["food"] = _food(source_food)
            provenance["original_meal"] = {"date": source_meal.date.isoformat() if source_meal.date else None,
                                          "type": source_meal.type}
        provenance["owner_corrections"] = edits or {}
        row["exchange_input"] = {
            "quantity": _input_quantity(record.food.quantity), "basis": _input_quantity(normalize._basis(record.food)),
            "basis_kind": record.food.nutrition.basis_kind if record.food.nutrition else "absent",
        }
        key = candidates[index]
        if key is not None and any(item["code"] == "possible_duplicate" for item in row["exchange_diagnostics"]):
            matches = list(existing.get(key, ()))
            for peer, candidate in enumerate(candidates):
                if peer != index and candidate == key:
                    compared = result.records[peer]
                    matches.append((compared.food.path, compared.food.name, "En este archivo",
                                    compared.contributions.get("energy", {}).get("value") if compared.contributions else None))
            witness = _stamp((key, record.contributions, matches))
            row["exchange_duplicate"] = {"witness": witness, "matches": [item[1:] for item in matches[:10]],
                                         "count": len(matches)}
            action = options.get("duplicates", {}).get(path)
            if action and action["witness"] == witness:
                row["skip"] = action["choice"] == "omit"
                provenance["duplicate_resolution"] = action["choice"]
                _remove_issue(row, "possible_duplicate")
        if row["date"] and row["date"] in days:
            witness, legacy, kcal = days[row["date"]]
            row["exchange_day"] = {"witness": witness, "legacy": legacy, "energy": kcal}
            if options.get("days", {}).get(row["date"]) == witness:
                row["conflict_action"] = "keep_and_add"
                if legacy:
                    row["authority"] = "disjoint_aggregate"
                _remove_issue(row, "day_overlap")


def _input_quantity(quantity):
    return {"amount": format(quantity.amount, "f"), "unit": quantity.unit, "label": quantity.label,
            "unit_name": quantity.label or UNIT_NAMES[quantity.unit]} if quantity else {}


def _remove_issue(row, code):
    row["exchange_diagnostics"] = [item for item in row["exchange_diagnostics"] if item["code"] != code]


def groups(rows):
    """Only offer a joint form for the same unresolved fact with matching units."""
    by_unit = {}
    for row in rows:
        quantity = row.get("exchange_input", {}).get("quantity") or {}
        codes = {d["code"] for d in row["exchange_diagnostics"] if d["severity"] != "warning"}
        if not row["skip"] and codes == {"missing_basis"} and quantity.get("unit") in {"g", "ml"}:
            by_unit.setdefault(quantity["unit"], []).append(row["evidence"]["path"])
    return {unit: {"paths": paths, "witness": _stamp(paths)}
            for unit, paths in by_unit.items() if len(paths) > 1}


def refresh(row, *, options=None, lock=False):
    from app.services.nutrition_import import verified_original

    source, found = verified_original(row, lock=lock, exchange_options=(
        row.source_json.get("exchange_options", {}) if options is None else options))
    if found["profile"] != row.source_json["profile"]:
        raise NutritionError("El formato del original cambió. Vuelve a subirlo para revisarlo.", 409)
    for item in found["rows"]:
        item["evidence"]["file"] = source.original_filename
    review = dict(row.review_json, destination=found["classification_hint"], rows=found["rows"])
    return review, found["exchange_diagnostics"]


def _row(rows, raw):
    try:
        index = int(raw)
        if index < 0:
            raise ValueError
        return rows[index]
    except (TypeError, ValueError, IndexError) as error:
        raise NutritionError("Selecciona un alimento de esta revisión.") from error


def _edit_food(item, form, options, action):
    path = item["evidence"]["path"]
    edit = options.setdefault("foods", {}).setdefault(path, {})
    codes = {diagnostic["code"] for diagnostic in item["exchange_diagnostics"]}
    if action == "quantity":
        quantity = _quantity(form, "quantity")
        edit.update(quantity=quantity)
        edit.pop("basis_kind", None)
        edit.pop("basis", None)
    elif action == "basis":
        kind = form.get("basis_kind")
        if not item["declaration"] or kind not in {"reference", "consumed"}:
            raise NutritionError("Indica qué cantidad representa la declaración original.")
        edit["basis_kind"] = kind
        edit.pop("basis", None)
        if kind == "reference":
            edit["basis"] = _quantity(form, "basis")
    elif action == "authority":
        choice = form.get("choice")
        if "conflicting_authority" not in codes or choice not in {"dish", "ingredients"}:
            raise NutritionError("Comprueba qué fuente aporta los nutrientes de este plato.")
        edit["authority"] = choice
    elif action == "equivalence":
        source = (form.get("source") or "").strip()
        if not codes & {"missing_equivalence", "incompatible_units"} or not 0 < len(source) <= 500 or form.get("verified") != "yes":
            raise NutritionError("Confirma y describe cómo verificaste esta equivalencia.")
        edit["equivalence"] = {"factor": _number(form.get("factor")), "source": source}
        edit.pop("authority", None)
    if action in {"quantity", "basis"}:
        for key in ("authority", "equivalence"):
            edit.pop(key, None)
    options.get("duplicates", {}).pop(path, None)
    options.get("days", {}).pop(item["date"], None)


def save(user_id, key, form):
    from app.services import nutrition_import as imports
    from .preparation import web_enabled

    imports.ni.enabled()
    if not web_enabled():
        raise NutritionError("El intercambio de comidas está desactivado.", 404)
    imports.ni.lock_owner(user_id)
    row = imports.owned(user_id, key, True)
    imports.assert_pending(row, form.get("revision"), lock_original=True)
    if row.source_json.get("profile") not in EXCHANGE_PROFILES:
        raise NutritionError("Usa las opciones de este borrador.", 409)
    options = copy.deepcopy(row.source_json.get("exchange_options", {}))
    current, _ = refresh(row, options=options, lock=True)
    rows = current["rows"]
    action = form.get("action")
    if action == "destination":
        if form.get("destination") != "consumed":
            raise NutritionError("Selecciona consumos reales para estas comidas.")
        options["destination"] = "consumed"
    elif action == "group":
        group = groups(rows).get(form.get("unit"))
        if not group or group["witness"] != form.get("context") or form.get("verified") != "yes":
            raise NutritionError("Confirma la interpretación del grupo que aparece en pantalla.", 409)
        for item in rows:
            if item["evidence"]["path"] in group["paths"]:
                _edit_food(item, {"basis_kind": "consumed"}, options, "basis")
    elif action == "day":
        target = form.get("date")
        day = next((item.get("exchange_day") for item in rows if item["date"] == target and item.get("exchange_day")), None)
        if not day or form.get("verified") != "yes" or day["witness"] != form.get("context"):
            raise NutritionError("Vuelve a revisar el agregado existente e indica si es independiente.", 409)
        options.setdefault("days", {})[target] = day["witness"]
    elif action in {"meal", "quantity", "basis", "authority", "equivalence", "duplicate"}:
        item = _row(rows, form.get("index"))
        path = item["evidence"]["path"]
        if action == "duplicate":
            duplicate = item.get("exchange_duplicate")
            choice = form.get("choice")
            if not duplicate or choice not in {"distinct", "omit"} or duplicate["witness"] != form.get("context"):
                raise NutritionError("La coincidencia cambió. Compárala de nuevo antes de decidir.", 409)
            options.setdefault("duplicates", {})[path] = {"choice": choice, "witness": duplicate["witness"]}
        elif action == "meal":
            meal = item["source_provenance"]["meal"]["path"]
            day = _date(form.get("date")).isoformat()
            meal_type = form.get("meal_type")
            if meal_type not in MEAL_TYPES:
                raise NutritionError("Selecciona el tipo de comida.")
            options.setdefault("meals", {})[meal] = {"date": day, "type": meal_type}
            for candidate in rows:
                if candidate["source_provenance"]["meal"]["path"] == meal:
                    options.get("duplicates", {}).pop(candidate["evidence"]["path"], None)
                    options.get("days", {}).pop(candidate["date"], None)
            options.get("days", {}).pop(day, None)
        else:
            _edit_food(item, form, options, action)
    else:
        raise NutritionError("Selecciona una de las acciones de revisión.")

    review, diagnostics = refresh(row, options=options, lock=True)
    if action in {"authority", "equivalence"} and not _row(review["rows"], form.get("index"))["exchange_preview_available"]:
        raise NutritionError("La decisión no permite calcular el aporte. Verifica las cantidades o la fuente elegida.")
    row.review_json = review
    row.source_json = dict(row.source_json, exchange_options=options, exchange_diagnostics=diagnostics)
    row.revision += 1
    db.session.flush()
    return row
