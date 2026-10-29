"""Read-only interpretation of daily_nutrition 1.0 item totals.

The legacy importer/exporter store item nutrients without quantity scaling.
Only a schema-valid item in its original envelope establishes that contract.
Extensions, conflicting bases and free text never establish a new contract.
"""
import re

from app.services.nutrition_math import NutritionError, decimal
from app.services.validation import validate_json_document


def annotate(row, document, meal, original):
    candidate = dict(document,data=dict(document['data'],meals=[dict(meal,items=[original])]))
    supported = document.get('schema_version') == '1.0'
    try:
        validate_json_document(candidate, 'daily_nutrition')
    except ValueError:
        supported = False
    notes = str(original.get('notes', '')).casefold()
    estimated = bool(re.search(r'estimad|aprox|proxy|referencia gen', notes)) or original.get('quality') == 'estimated'
    interpretation = dict(kind='unresolved', status='proposed',
        origin='daily_nutrition_1_0' if supported else 'unrecognized_daily_nutrition',
        quality='estimated' if estimated else 'file_declared_unverified', measurement_verified=False)
    explicit = bool(row.get('basis_amount') and row.get('basis_unit'))
    if explicit:
        interpretation.update(kind='explicit_basis', status='explicit')
        row['resolution']='declared'
    elif supported:
        interpretation['kind'] = 'consumed_total'
        try:
            decimal(row.get('amount'), positive=True)
            if row.get('unit') not in {'g', 'ml', 'portion'}:
                raise NutritionError('Unidad no verificada.')
        except NutritionError:
            pass
        else:
            row.update(basis_amount=row['amount'], basis_unit=row['unit'])
            if row.get('unit_label'):
                row['basis_label'] = row['unit_label']
    if interpretation['kind'] == 'consumed_total' and row.get('basis_amount'):
        interpretation['source_basis'] = {key:row.get(key) for key in ('basis_amount','basis_unit','basis_label')}
    if row.get('basis_conflict'):
        interpretation.update(kind='contradictory_basis',status='proposed')
        row.pop('resolution',None)
    if not explicit and re.search(r'(?:valores|macros|nutrientes)\s+(?:expresados\s+|declarados\s+|son\s+)?por\s+(?:100\s*(?:g|ml)\b|porci[oó]n|unidad|pieza|envase)',notes):
        # Free text is evidence of ambiguity, never a conversion instruction.
        interpretation.update(kind='contradictory_basis',status='proposed')
        row.pop('resolution',None)
    scaled=[str(value.get('provenance',{}).get('source_field','')).endswith(('per_100g','per_100ml'))
        for value in row['declaration'].values()]
    if any(str(key).endswith(('per_100g','per_100ml')) for key in original) and not all(scaled) and not original.get('basis_amount'):
        interpretation.update(kind='contradictory_basis',status='proposed')
        row.pop('resolution',None)
    row['basis_interpretation'] = interpretation
    row['kind_hint'] = 'consumed'
    for nutrient, value in row['declaration'].items():
        value['provenance'] = dict(value.get('provenance') or {},
            quality=interpretation['quality'], measurement_verified=False,
            origin_contract=interpretation['origin'])
    # A source zero explicitly described as a placeholder is not a known zero.
    # Keep it unchanged in original/declaration until an explicit nutrient decision.
    if ('fibra' in notes and '0' in notes and
            re.search(r'no cuantificada|no declarada|no registrar fibra', notes) and
            re.search(r'marcador|compatibilidad', notes)):
        row['quality_problems'] = ['fiber'] if 'fiber' in row['declaration'] else []


def grouped(item):
    interpretation = item.get('basis_interpretation') or {}
    source = interpretation.get('source_basis') or {}
    return (interpretation.get('kind') == 'consumed_total' and interpretation.get('status') == 'proposed'
        and bool(source) and item.get('unit') == source.get('basis_unit')
        and str(item.get('amount')) == str(source.get('basis_amount'))
        and all(str(item.get(key) or '')==str(source.get(key) or '') for key in source)
        and not item.get('ingredients') and not item.get('resolution')
        and not item.get('portion_conflict'))


def accept(item, choice):
    interpretation = item.get('basis_interpretation') or {}
    if not interpretation:
        raise NutritionError('Este registro no tiene una interpretación legacy pendiente.')
    if choice == 'source_total':
        source = interpretation.get('source_basis')
        if interpretation.get('kind') != 'consumed_total' or not source:
            raise NutritionError('El contrato de origen no demuestra una base total.')
        item.update(source)
    elif choice == 'consumed_total':
        item.update(basis_amount=item.get('amount'), basis_unit=item.get('unit'), basis_label=item.get('unit_label'))
    elif choice in {'per_100g', 'per_100ml'}:
        item.update(basis_amount='100', basis_unit='g' if choice == 'per_100g' else 'ml', basis_label=None)
    elif choice != 'explicit_basis':
        raise NutritionError('Selecciona una interpretación explícita de los valores.')
    item['basis_interpretation'] = dict(interpretation, status='accepted',
        choice=choice, confirmed_by='user', measurement_verified=False)
    from app.services.nutrition_import_portions import sufficient
    sufficient(item)
    item.update(resolution='declared', ingredients=[], summary_bindings=False, composition_complete=False)
