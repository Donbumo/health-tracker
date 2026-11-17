"""Adapters for explicitly supported grouped and flat Spanish/English JSON."""

from datetime import date
from decimal import Decimal
import re

from app.services.nutrition_math import NUTRIENTS, NutritionError, decimal

from .source import Declaration, Evidence, Observation, Quantity, SourceBatch, SourceFood, SourceMeal, issue, pointer


UNIT_ALIASES = {
    "g": "g", "kg": "kg", "ml": "ml", "l": "l", "mg": "mg", "ug": "ug", "µg": "ug", "mcg": "ug",
    "kcal": "kcal", "piece": "piece", "pieza": "piece", "portion": "portion", "porción": "portion", "porcion": "portion",
}
QUANTITY_UNITS = {"g": ("g", 0), "kg": ("g", 3), "ml": ("ml", 0), "l": ("ml", 3), "piece": ("piece", 0), "portion": ("portion", 0)}
MASS = {"g": 0, "mg": -3, "ug": -6}
MEALS = {
    "breakfast": "breakfast", "desayuno": "breakfast", "lunch": "lunch", "comida": "lunch",
    "almuerzo": "lunch", "dinner": "dinner", "cena": "dinner", "snack": "snack",
    "colación": "snack", "colacion": "snack", "other": "other", "otro": "other",
}
DESTINATIONS = {
    "consumed": "consumed", "consumido": "consumed", "plan": "plan",
    "recipe": "recipe", "receta": "recipe", "product": "product", "producto": "product",
}
QUALITY = {
    "declared": "declared", "declarado": "declared", "estimated": "estimated", "estimado": "estimated",
    "label": "label", "etiqueta": "label", "unknown": "unknown", "desconocido": "unknown",
}
STATES = {
    "known": "known", "conocido": "known", "unknown": "unknown", "desconocido": "unknown",
    "trace": "trace", "traza": "trace", "below_limit": "below_limit", "bajo_limite": "below_limit",
}
NUTRIENT_ALIASES = {
    "kcal": "energy", "energía": "energy", "energia": "energy", "calorías": "energy", "calorias": "energy",
    "proteína": "protein", "proteina": "protein", "proteínas": "protein", "proteinas": "protein",
    "grasa": "fat", "grasas": "fat", "fibra": "fiber", "azúcar": "sugar", "azucar": "sugar",
    "carbohidratos_totales": "carbohydrate_total", "carbohidratos_netos": "net_carbs",
    "sodio": "sodium", "potasio": "potassium", "calcio": "calcium", "hierro": "iron",
    "magnesio": "magnesium", "fósforo": "phosphorus", "fosforo": "phosphorus", "cinc": "zinc",
}
AMBIGUOUS_CARBS = {"carbohydrates", "carbs", "carbohidratos"}
STRING_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?\Z")
ABSENT = object()


def _term(value):
    return value.strip().casefold() if isinstance(value, str) else None


def _same_source(left, right):
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_same_source(value, right[key]) for key, value in left.items())
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_same_source(a, b) for a, b in zip(left, right))
    return left == right


def _number(value, *, shift=0, positive=False):
    if isinstance(value, str) and not STRING_NUMBER.fullmatch(value):
        raise NutritionError("Se esperaba un decimal explícito.")
    source = Decimal(str(value))
    if not source.is_finite():
        raise NutritionError("Se esperaba un decimal finito.")
    sign, digits, exponent = source.as_tuple()
    digits = list(digits)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exponent += 1
    decimal_value = Decimal((sign, digits, exponent + shift)) if source else Decimal(0)
    return decimal(decimal_value, positive=positive)


class _Adapter:
    def __init__(self):
        self.diagnostics = []

    def pick(self, raw, path, scope, *names):
        present = [name for name in names if name in raw]
        if not present:
            return ABSENT, pointer(path, names[0])
        first = present[0]
        if any(not _same_source(raw[name], raw[first]) for name in present[1:]):
            self.diagnostics.extend(issue("alias_conflict", pointer(path, name), scope) for name in present)
            return ABSENT, pointer(path, first)
        return raw[first], pointer(path, first)

    def text(self, raw, path, scope, *names, maximum=200):
        value, location = self.pick(raw, path, scope, *names)
        if value is ABSENT:
            return None, None
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            self.diagnostics.append(issue("invalid_field", location, scope))
            return None, None
        return value.strip(), Evidence(location, value, rule=names[0])

    def term(self, vocabulary, raw, path, scope, *names):
        value, evidence = self.text(raw, path, scope, *names)
        matched = vocabulary.get(_term(value))
        if evidence is not None and matched is None:
            self.diagnostics.append(issue("invalid_field", evidence.path, scope))
        return matched, evidence

    def local_date(self, raw, path, scope):
        value, location = self.pick(raw, path, scope, "date", "fecha")
        if value is ABSENT:
            return None, None, location if any(key in raw for key in ("date", "fecha")) else None
        try:
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                raise ValueError
            return date.fromisoformat(value), Evidence(location, value, rule="date"), location
        except ValueError:
            self.diagnostics.append(issue("invalid_date", location, scope))
            return None, None, location

    def quantity(self, raw, path):
        if not isinstance(raw, dict):
            self.diagnostics.append(issue("invalid_quantity", path, "field"))
            return None
        amount, amount_path = self.pick(raw, path, "field", "amount", "cantidad", "valor")
        unit, unit_path = self.pick(raw, path, "field", "unit", "unidad")
        source_unit = UNIT_ALIASES.get(_term(unit))
        mapped = QUANTITY_UNITS.get(source_unit)
        if mapped is None:
            self.diagnostics.append(issue("invalid_unit", unit_path, "field"))
            return None
        try:
            normalized = _number(amount, shift=mapped[1], positive=True)
        except (ArithmeticError, TypeError, ValueError):
            self.diagnostics.append(issue("invalid_quantity", amount_path, "field"))
            return None
        quantity_label, label_evidence = self.text(raw, path, "field", "label", "etiqueta")
        if mapped[0] in {"piece", "portion"} and not quantity_label:
            self.diagnostics.append(issue("missing_label", pointer(path, "label"), "field"))
            return None
        details = {amount_path.rsplit("/", 1)[-1]: amount, unit_path.rsplit("/", 1)[-1]: unit}
        if label_evidence:
            details[label_evidence.path.rsplit("/", 1)[-1]] = label_evidence.raw
        return Quantity(normalized, mapped[0], quantity_label, Evidence(
            path, details, "quantity", f"{source_unit}->{mapped[0]}" if mapped[1] else None))

    def observation(self, raw, path, key, quality, source):
        if not isinstance(raw, dict):
            self.diagnostics.append(issue("invalid_observation", path, "field"))
            return None
        stated, state_path = self.pick(raw, path, "field", "state", "estado")
        amount, value_path = self.pick(raw, path, "field", "value", "valor")
        limit, limit_path = self.pick(raw, path, "field", "limit", "limite", "límite")
        unit, unit_path = self.pick(raw, path, "field", "unit", "unidad")
        item_quality, quality_evidence = self.term(QUALITY, raw, path, "field", "quality", "calidad")
        item_source, _ = self.text(raw, path, "field", "source", "fuente", maximum=500)
        note, _ = self.text(raw, path, "field", "note", "nota", maximum=10000)
        state = ("known" if amount is not ABSENT else None) if stated is ABSENT else STATES.get(_term(stated))
        if state is None:
            self.diagnostics.append(issue("invalid_observation", state_path, "field"))
            return None

        original_unit = UNIT_ALIASES.get(_term(unit))
        canonical = NUTRIENTS[key][1] if key else None
        shift = 0
        if unit is ABSENT and state == "unknown":
            output_unit = None
        elif isinstance(unit, str) and unit.strip() and len(unit) <= 32:
            output_unit = canonical or unit
            if key and original_unit != canonical:
                if original_unit not in MASS or canonical not in MASS:
                    self.diagnostics.append(issue("invalid_unit", unit_path, "field"))
                    return None
                shift = MASS[original_unit] - MASS[canonical]
        else:
            self.diagnostics.append(issue("invalid_unit", unit_path, "field"))
            return None

        def read(field, location, required, positive=False):
            if not required and field is ABSENT:
                return None
            try:
                if not required:
                    raise ValueError
                return _number(field, shift=shift, positive=positive)
            except (ArithmeticError, TypeError, ValueError):
                self.diagnostics.append(issue("invalid_observation", location, "field"))
                return None

        result = read(amount, value_path, state == "known")
        threshold = read(limit, limit_path, state == "below_limit", positive=True)
        if (state == "known" and result is None) or (state == "below_limit" and threshold is None):
            return None
        original = {part.rsplit("/", 1)[-1]: val
                    for part, val in ((state_path, stated), (value_path, amount), (unit_path, unit), (limit_path, limit))
                    if val is not ABSENT and isinstance(val, (str, int, Decimal, type(None)))}
        if quality_evidence:
            original[quality_evidence.path.rsplit("/", 1)[-1]] = quality_evidence.raw
        evidence = Evidence(path, original, key, f"{original_unit}->{canonical}" if shift else None, item_source or source, note)
        return Observation(state, result, output_unit, threshold, item_quality or quality or "declared", evidence)

    def declaration(self, raw, path):
        if not isinstance(raw, dict):
            self.diagnostics.append(issue("invalid_nutrition", path, "field"))
            return None
        basis, basis_path = self.pick(raw, path, "field", "basis", "base")
        values, values_path = self.pick(raw, path, "field", "values", "valores", "nutrients", "nutrientes")
        quality, qe = self.term(QUALITY, raw, path, "field", "quality", "calidad")
        source, _ = self.text(raw, path, "field", "source", "fuente", maximum=500)
        note, _ = self.text(raw, path, "field", "note", "nota", maximum=10000)
        basis_kind, reference = "absent", None
        if basis is not ABSENT:
            kind, kind_path = self.pick(basis, basis_path, "field", "kind", "tipo") if isinstance(basis, dict) else (ABSENT, basis_path)
            if kind is ABSENT or _term(kind) in {"reference", "referencia"}:
                reference = self.quantity(basis, basis_path)
                basis_kind = "reference" if reference else "absent"
            elif _term(kind) not in {"consumed", "consumido"} or set(basis) - {"kind", "tipo"}:
                self.diagnostics.append(issue("basis_conflict", kind_path, "field"))
            else:
                basis_kind = "consumed"

        parsed = {}
        extras = []
        if values is not ABSENT and not isinstance(values, dict):
            self.diagnostics.append(issue("invalid_nutrition", values_path, "field"))
            values = ABSENT
        if values is not ABSENT:
            grouped = {}
            for name, entry in values.items():
                current = pointer(values_path, name)
                mapped = _term(name)
                key = mapped if mapped in NUTRIENTS else NUTRIENT_ALIASES.get(mapped)
                item = self.observation(entry, current, key, quality, source)
                if item is None:
                    continue
                if key is None:
                    extras.append(Observation(item.state, item.value, item.unit, item.limit, item.quality, item.evidence, name))
                    if mapped in AMBIGUOUS_CARBS:
                        self.diagnostics.append(issue("ambiguous_nutrient", current, "field"))
                else:
                    grouped.setdefault(key, []).append(item)
            for key, items in grouped.items():
                first = items[0]
                semantic = lambda item: (item.state, item.value, item.unit, item.limit, item.quality)
                if any(semantic(item) != semantic(first) for item in items[1:]):
                    self.diagnostics.extend(issue("alias_conflict", item.evidence.path, "field") for item in items)
                # Preserve duplicate aliases as evidence even when they agree.
                # Do not decide which attribution to prefer for conflicting input.
                chosen = min(items, key=lambda item: (item.evidence.path != pointer(values_path, key), item.evidence.path))
                parsed[key] = chosen
                extras.extend(Observation(item.state, item.value, item.unit, item.limit, item.quality, item.evidence, key)
                              for item in items if item is not chosen)
        return Declaration(basis_kind, reference, parsed, tuple(extras),
                           Evidence(path, qe.raw if qe else None, "nutrition", source=source, note=note))

    def food(self, raw, path, *, ingredient=False):
        if not isinstance(raw, dict):
            self.diagnostics.append(issue("invalid_food", path, "food", "invalid"))
            return SourceFood(path, None, None, None)
        food_name, name = self.text(raw, path, "food", "name", "nombre")
        _, note = self.text(raw, path, "food", "note", "nota", maximum=10000)
        amount, amount_path = self.pick(raw, path, "field", "quantity", "cantidad")
        nutrition, nutrition_path = self.pick(raw, path, "field", "nutrition", "nutricion", "nutrición")
        children, child_path = self.pick(raw, path, "field", "ingredients", "ingredientes")
        if children is not ABSENT and (ingredient or not isinstance(children, list)):
            self.diagnostics.append(issue("invalid_composition", child_path, "field"))
            children = ABSENT
        return SourceFood(
            path, food_name, self.quantity(amount, amount_path) if amount is not ABSENT else None,
            self.declaration(nutrition, nutrition_path) if nutrition is not ABSENT else None,
            tuple(self.food(child, pointer(child_path, index), ingredient=True) for index, child in enumerate(children))
            if children is not ABSENT else (),
            tuple(value for value in (name, note) if value is not None),
        )

    def meal(self, raw, path, default_date, default_path):
        if not isinstance(raw, dict):
            self.diagnostics.append(issue("invalid_meal", path, "meal", "invalid"))
            return SourceMeal(path, None, None, None, None, ())
        day, day_evidence, date_path = self.local_date(raw, path, "meal")
        meal_type, type_evidence = self.term(MEALS, raw, path, "meal", "type", "tipo", "meal_type")
        name, name_evidence = self.text(raw, path, "meal", "name", "nombre")
        _, note = self.text(raw, path, "meal", "note", "nota", maximum=10000)
        foods, food_path = self.pick(raw, path, "meal", "foods", "alimentos")
        if not isinstance(foods, list) or not foods:
            self.diagnostics.append(issue("missing_foods", food_path, "meal", "invalid"))
            foods = []
        return SourceMeal(
            path, day if date_path is not None else default_date, date_path or default_path, meal_type, name,
            tuple(self.food(food, pointer(food_path, index)) for index, food in enumerate(foods)),
            tuple(value for value in (day_evidence, type_evidence, name_evidence, note) if value is not None),
        )


def adapt(document):
    """Convert the bounded pre-parsed common family and keep unresolved fields visible."""
    adapter = _Adapter()
    day, date_evidence, default_path = adapter.local_date(document, "", "file")
    destination, destination_evidence = adapter.term(DESTINATIONS, document, "", "file", "destination", "destino")
    _, note = adapter.text(document, "", "file", "note", "nota", maximum=10000)
    meals, meal_path = adapter.pick(document, "", "file", "meals", "comidas")
    flat, flat_path = adapter.pick(document, "", "file", "foods", "alimentos")
    records = ()
    if meals is not ABSENT and flat is not ABSENT:
        adapter.diagnostics.append(issue("alias_conflict", flat_path, "file"))
    elif isinstance(meals, list) and meals:
        records = tuple(adapter.meal(meal, pointer(meal_path, index), day, default_path)
                        for index, meal in enumerate(meals))
    elif isinstance(flat, list) and flat:
        records = (adapter.meal(document, "", day, default_path),)
    else:
        adapter.diagnostics.append(issue("missing_foods", meal_path, "file", "invalid"))
    return SourceBatch("common", "nutrition-exchange-common-v1", destination, day, records,
                       tuple(adapter.diagnostics),
                       tuple(value for value in (date_evidence, destination_evidence, note) if value is not None))
