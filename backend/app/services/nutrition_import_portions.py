"""Explicit file portions, without inferred weights or catalog identities."""
import copy

from app.services.nutrition_math import NutritionError, decimal, precise


@precise
def consumption(item):
    """Return the quantity in declaration units; retain the original evidence."""
    amount = decimal(item.get('amount'), positive=True)
    unit = item.get('unit')
    basis = item.get('basis_unit')
    decimal(item.get('basis_amount'), positive=True)
    if unit not in {'g', 'ml', 'portion'} or basis not in {'g', 'ml', 'portion'}:
        raise NutritionError('Confirma cantidad, unidad y base de los nutrientes.')
    evidence = {'amount': str(amount), 'unit': item.get('unit_label') or unit}
    if unit == basis:
        if unit == 'portion' and item.get('basis_label', 'portion') != item.get('unit_label', 'portion'):
            raise NutritionError('La porción consumida y la base tienen nombres distintos; confirma su equivalencia.')
        return str(amount), unit, evidence
    equivalent = item.get('equivalence') or {}
    if unit != 'portion' or equivalent.get('unit') != basis or not item.get('equivalence_confirmed'):
        raise NutritionError('Confirma la equivalencia explícita de esta porción con la base; no se inventa masa o volumen.')
    factor = decimal(equivalent.get('amount'), positive=True)
    evidence['equivalence_per_unit'] = copy.deepcopy(equivalent)
    evidence['equivalence_confirmed'] = True
    return str(amount * factor), basis, evidence


def sufficient(item):
    from app.services.nutrition_math import validate_vector
    vector = validate_vector(item.get('declaration', {}))
    if not any(value['state'] == 'known' for value in vector.values()):
        raise NutritionError('Se necesita al menos un nutriente absoluto declarado; los ausentes siguen desconocidos.')
    return consumption(item)
