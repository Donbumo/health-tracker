"""Decimal calculations shared by previews, consumed snapshots and exports.

No database/network writes, reference targets or imputation. Chemical forms are
distinct IDs; trace and below-limit values never become exact zero.
"""
from decimal import Decimal, InvalidOperation, localcontext
from functools import wraps


def precise(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with localcontext() as context:
            context.prec = 40
            return function(*args, **kwargs)
    return wrapped


NUTRIENTS = {
    "energy": ("Energía", "kcal", "energy"),
    "protein": ("Proteína", "g", "macro"),
    "carbohydrate_total": ("Carbohidratos totales", "g", "macro"),
    "net_carbs": ("Carbohidratos netos", "g", "macro"),
    "fat": ("Grasa", "g", "macro"), "fiber": ("Fibra", "g", "macro"),
    "sugar": ("Azúcar", "g", "macro"),
    **{key: (label, "mg", "mineral") for key, label in (
        ("sodium", "Sodio"), ("potassium", "Potasio"), ("calcium", "Calcio"),
        ("iron", "Hierro"), ("magnesium", "Magnesio"),
        ("phosphorus", "Fósforo"), ("zinc", "Zinc"))},
    "vitamin_a_rae": ("Vitamina A (RAE)", "ug", "vitamin"),
    "retinol": ("Retinol", "ug", "vitamin"),
    "vitamin_a_re": ("Vitamina A (RE)", "ug", "vitamin"),
    "vitamin_c": ("Vitamina C", "mg", "vitamin"),
    "vitamin_d": ("Vitamina D", "ug", "vitamin"),
    "vitamin_e_alpha": ("Vitamina E (alfa-tocoferol)", "mg", "vitamin"),
    "vitamin_k1": ("Vitamina K1", "ug", "vitamin"),
    "vitamin_k2": ("Vitamina K2", "ug", "vitamin"),
    **{key: (label, "mg", "vitamin") for key, label in (
        ("thiamin", "B1"), ("riboflavin", "B2"), ("niacin", "B3"),
        ("vitamin_b6", "B6"))},
    "vitamin_b12": ("B12", "ug", "vitamin"),
    "folate_dfe": ("Folato (DFE)", "ug", "vitamin"),
    "folate_food": ("Folato alimentario", "ug", "vitamin"),
    "choline": ("Colina", "mg", "other"),
}
LEGACY = {"energy": "calories", "protein": "protein_g", "fat": "fat_g",
          "carbohydrate_total": "total_carbs_g", "net_carbs": "net_carbs_g",
          "fiber": "fiber_g", "sugar": "sugar_g", "sodium": "sodium_mg"}
PRODUCT = {"energy": "calories_per_100g", "protein": "protein_g_per_100g",
           "fat": "fat_g_per_100g", "carbohydrate_total": "carbs_g_per_100g",
           "net_carbs": "net_carbs_g_per_100g", "fiber": "fiber_g_per_100g",
           "sodium": "sodium_mg_per_100g"}
COVERAGE_EXPLANATION = ("La cobertura por masa mide disponibilidad de datos. "
    "No indica cumplimiento de referencia ni garantiza completitud nutricional.")


class NutritionError(ValueError):
    def __init__(self, message, status=422):
        self.status = status
        super().__init__(message)


def decimal(value, *, positive=False):
    if isinstance(value, bool):
        raise NutritionError("Cantidad numérica inválida.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise NutritionError("Cantidad numérica inválida.") from error
    if not result.is_finite() or result < 0 or (positive and result == 0) or result > Decimal("100000000"):
        raise NutritionError("Cantidad fuera de rango.")
    if result.as_tuple().exponent < -12:
        raise NutritionError("Precisión máxima: 12 decimales.")
    return result


def validate_vector(vector):
    if not isinstance(vector, dict) or set(vector) - NUTRIENTS.keys():
        raise NutritionError("Nutrientes o formas no reconocidos.")
    result = {}
    for key, entry in vector.items():
        if not isinstance(entry, dict) or set(entry) - {"state", "value", "unit", "limit", "provenance"}:
            raise NutritionError("Valor nutricional inválido.")
        state = entry.get("state")
        if state not in {"known", "unknown", "trace", "below_limit"} or entry.get("unit") != NUTRIENTS[key][1]:
            raise NutritionError("Estado o unidad incompatibles.")
        value = entry.get("value")
        if state == "known":
            value = str(decimal(value))
        elif value is not None:
            raise NutritionError("Un valor desconocido o calificado no es un valor exacto.")
        limit = entry.get("limit")
        if state == "below_limit":
            limit = str(decimal(limit, positive=True))
        elif limit is not None:
            raise NutritionError("Límite incompatible con estado.")
        result[key] = dict(entry, value=value, limit=limit)
    return result


@precise
def normalize(food, amount, unit, serving_id=None):
    amount = decimal(amount, positive=True)
    if serving_id:
        serving = next((s for s in food.get("servings", []) if s["id"] == serving_id), None)
        if not serving or unit != "serving":
            raise NutritionError("Porción inexistente para esta revisión.")
        amount *= decimal(serving["amount"], positive=True)
        unit = serving["unit"]
    elif unit not in {"g", "ml"}:
        raise NutritionError("Usa gramos, mililitros o una porción definida.")
    basis = food["basis_unit"]
    density = food.get("density_g_ml")
    mass = amount if unit == "g" else None
    if unit != basis:
        if density is None:
            raise NutritionError("Falta equivalencia de volumen/masa. Ingresa una cantidad compatible.")
        density = decimal(density, positive=True)
        amount = amount * density if basis == "g" else amount / density
        unit = basis
    if unit == "ml" and density is not None:
        mass = amount * decimal(density, positive=True)
    elif unit == "g":
        mass = amount
    return {"amount": str(amount), "unit": unit, "mass_g": str(mass) if mass is not None else None}


def ingredient(food, amount, unit, serving_id=None):
    normalized = normalize(food, amount, unit, serving_id)
    vector = validate_vector(food["nutrients"])
    with localcontext() as context:
        context.prec = 40
        factor = Decimal(normalized["amount"]) / decimal(food["basis_amount"], positive=True)
        contribution = {}
        for key in NUTRIENTS:
            entry = vector.get(key, {"state": "unknown", "value": None, "unit": NUTRIENTS[key][1]})
            contribution[key] = dict(entry)
            if entry["state"] == "known":
                contribution[key]["value"] = str(Decimal(entry["value"]) * factor)
            if entry.get("limit") is not None:
                contribution[key]["limit"] = str(Decimal(entry["limit"]) * factor)
    return {"food": food, "amount": str(decimal(amount, positive=True)), "unit": unit,
            "serving_id": serving_id, "normalized": normalized, "contribution": contribution}


@precise
def summarize(ingredients):
    output = {}
    masses = [entry["normalized"].get("mass_g") for entry in ingredients]
    denominator = sum((Decimal(m) for m in masses), Decimal(0)) if ingredients and all(m is not None for m in masses) else None
    for key, (_, unit, _) in NUTRIENTS.items():
        known = [i for i in ingredients if i["contribution"].get(key, {}).get("state") == "known"]
        subtotal = sum((Decimal(i["contribution"][key]["value"]) for i in known), Decimal(0)) if known else None
        known_mass = sum((Decimal(i["normalized"]["mass_g"]) for i in known), Decimal(0)) if all(i["normalized"].get("mass_g") is not None for i in known) else None
        coverage = known_mass * 100 / denominator if denominator and known_mass is not None else None
        sources = sorted({str(i["food"].get("source", "legacy")) for i in ingredients})
        state = "complete" if ingredients and len(known) == len(ingredients) else "partial" if known else "unknown"
        output[key] = {"value": str(subtotal) if subtotal is not None else None,
            "unit": unit, "state": state, "known_weight": str(known_mass) if known_mass is not None else None,
            "total_weight": str(denominator) if denominator is not None else None,
            "coverage": str(coverage) if coverage is not None else None,
            "coverage_method": "mass_weighted_v1", "known_items": len(known),
            "total_items": len(ingredients), "sources": sources}
    return output
