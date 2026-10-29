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
    if item.get('portion_text'):evidence['source_text']=item['portion_text']
    if item.get('portion_text_reviewed'):evidence['text_reviewed']=True
    if item.get('portion_conflict') and not item.get('portion_text_reviewed'):
        raise NutritionError(item['portion_conflict'])
    interpretation=item.get('basis_interpretation') or {}
    nominal_total=(interpretation.get('status')=='accepted' and interpretation.get('choice') in {'source_total','consumed_total'}
        and unit==basis=='portion' and amount==decimal(item.get('basis_amount'),positive=True))
    if item.get('portion_note_pending') and not (nominal_total or item.get('portion_text_reviewed') or item.get('equivalence_confirmed')):
        raise NutritionError('Revisa la nota de porción y corrige sus cantidades o equivalencias antes de aceptarla.')
    if unit == basis:
        if unit == 'portion' and item.get('basis_label', 'portion') != item.get('unit_label', 'portion') and not item.get('portion_label_confirmed'):
            raise NutritionError('La porción consumida y la base tienen nombres distintos; confirma su equivalencia.')
        if unit=='portion':
            evidence['basis_portion_label']=item.get('basis_label') or 'portion'
            evidence['same_portion_confirmed']=bool(item.get('portion_label_confirmed'))
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
    interpretation=item.get('basis_interpretation') or {}
    from app.services.importers.nutrition_legacy_semantics import current
    if interpretation and not current(item):
        raise NutritionError('Confirma a qué cantidad corresponden los valores del archivo legacy; no hace falta un producto.')
    return consumption(item)
