"""Format-independent, read-only presentation and scoped pending-row edits.

Nutrient amounts use the same Decimal snapshot calculation as the final writer.
Neither this module nor a contextual edit can persist a food or consumption.
"""
import copy
from collections import OrderedDict
from datetime import datetime, timezone
from decimal import Decimal

from app.services.nutrition_math import (
    NUTRIENTS, NutritionError, decimal, precise, summarize, summarize_parts,
    validate_vector,
)

MACROS = ('energy', 'protein', 'carbohydrate_total', 'fat')
MEALS = {'breakfast': 'Desayuno', 'lunch': 'Comida', 'dinner': 'Cena',
         'snack': 'Colación', 'other': 'Otro'}


def nutritional_preview(item, destination, user_id):
    """Compute known contributions even when an unrelated date/identity blocks.

    Ambiguous bases/units never contribute a plausible-looking subtotal.
    Products without a serving display their definition's explicit base.
    """
    from app.services import nutrition_import as imports
    from app.services.importers.nutrition_legacy_semantics import current
    from app.services.nutrition_import_portions import sufficient
    try:
        if not current(item) or (item.get('basis_conflict') and not item.get('basis_conflict_resolved')):
            return None
        if item.get('unsupported_vector') or any(
                warning.startswith('Valor declarado ambiguo: ') and
                warning.split(': ', 1)[1] not in item.get('resolved_nutrients', [])
                for warning in item.get('warnings', [])):
            return None
        if any(key not in item.get('resolved_nutrients', []) for key in item.get('quality_problems', [])):
            return None
        vector = validate_vector(item.get('declaration', {}))
        entry = dict(name=item.get('name', ''), bindings=copy.deepcopy(item.get('ingredients', [])),
                     composition={'complete': item.get('composition_complete', False),
                                  'total_mass_g': item.get('total_mass_g') or (item.get('amount') if item.get('unit') == 'g' else None)},
                     declaration=None)
        if vector:
            entry['declaration'] = dict(basis_amount=str(decimal(item.get('basis_amount') or item.get('amount'), positive=True)),
                basis_unit=item.get('basis_unit') or item.get('unit'), nutrients=vector, confirmed=True,
                provenance={'basis_interpretation': copy.deepcopy(item.get('basis_interpretation') or {}),
                            'quality':item.get('source_quality')})
            if destination == 'products':
                # These are product definitions, not recorded intake.
                entry['composition'] = {'complete': False, 'total_mass_g': None}
            elif destination == 'consumed' and item.get('resolution') in {'declared', 'private'}:
                amount, unit, _ = sufficient(item)
                entry.update(portion_amount=amount, portion_unit=unit)
                entry['composition'] = {'complete': False, 'total_mass_g': amount if unit == 'g' else None}
                if item.get('resolution') == 'declared':entry['bindings'] = []
            elif item.get('amount') and item.get('unit'):
                entry.update(portion_amount=item['amount'], portion_unit=item['unit'])
        elif not entry['bindings']:
            return None
        if item.get('yield_factor'):entry['composition']['yield_factor']=item['yield_factor']
        return imports.meal_snapshot(entry, imports.resolved_entries(entry, user_id), 'UTC')['summary']
    except (NutritionError, ValueError):
        return None


def aggregate(records):
    empty = summarize([])
    parts = [record['preview'] or empty for record in records if record['state'] != 'omitted']
    return summarize_parts(parts)


def presentation(records, destination):
    groups = OrderedDict()
    for record in records:
        item = record['item']
        record['original_fields']=original_fields(item)
        preview = record['preview']
        estimated = (item.get('source_quality')=='estimated' or (item.get('basis_interpretation') or {}).get('quality') == 'estimated' or
            any((value.get('provenance') or {}).get('quality') == 'estimated' for value in item.get('declaration', {}).values()))
        partial = not preview or any(preview[key]['state'] != 'complete' for key in MACROS)
        record['quality'] = 'Estimado' if estimated else 'Parcial' if preview and partial else 'Sin dato' if not preview else ''
        record['estimated'] = estimated
        record['partial'] = partial
        record['editor_panel'] = ('basis' if destination=='products' or any(
            problem['code'] in {'basis','basis_conflict'} for problem in record['issues']) else
            'correction' if record['issues'] else 'quantity')
        key = (item.get('date') or item.get('planned_for') or '', item.get('meal_type') or '')
        group = groups.setdefault(key, dict(date=key[0], meal=MEALS.get(key[1], ''), records=[]))
        group['records'].append(record)
        record['display_amount'] = (item.get('basis_amount') if destination == 'products' else item.get('amount'))
        record['display_unit'] = ((item.get('basis_label') or item.get('basis_unit')) if destination == 'products'
                                  else (item.get('unit_label') or item.get('unit')))
        if record['display_unit'] in {'portion','serving'}:record['display_unit']='porción'
    for group in groups.values():group['summary'] = aggregate(group['records'])
    active = [record for record in records if record['state'] != 'omitted']
    days = OrderedDict()
    for record in active:
        target = record['item'].get('date') or record['item'].get('planned_for')
        if target:days.setdefault(target, []).append(record)
    return dict(groups=list(groups.values()), batch_summary=aggregate(records),
        day_summaries=[dict(date=target, summary=aggregate(items)) for target,items in days.items()],
        quality_counts=dict(estimated=sum(r['estimated'] for r in active), partial=sum(r['partial'] for r in active),
                            unknown=sum(not r['preview'] for r in active)))


def original_fields(item):
    """Allowlisted nutrition evidence, never arbitrary source metadata/secrets."""
    from app.services.importers.nutrition_sources import ALIASES,fold
    original=item.get('original') or {}
    labels=dict(name='Nombre',brand='Marca',amount='Cantidad',unit='Unidad',date='Fecha',meal_type='Comida',
                basis_amount='Cantidad de referencia',basis_unit='Unidad de referencia')
    labels.update({key:definition[0] for key,definition in NUTRIENTS.items()})
    lookup={fold(alias):label for key,label in labels.items() for alias in ALIASES[key]}
    values=[dict(label=lookup[fold(key)],value=str(value)) for key,value in original.items()
            if fold(key) in lookup and isinstance(value,(str,int,float))]
    declaration=original.get('declaration') or {}
    if not isinstance(declaration,dict):declaration={}
    vector=declaration.get('nutrients',original.get('nutrients',{}))
    if isinstance(vector,dict):
        for key,nutrient in vector.items():
            if key in NUTRIENTS and isinstance(nutrient,dict):
                state=nutrient.get('state')
                text=(str(nutrient.get('value'))+' '+str(nutrient.get('unit') or '')) if state=='known' else {
                    'unknown':'Sin dato','trace':'Traza','below_limit':'Bajo el límite'}.get(state,'Sin dato')
                values.append(dict(label=NUTRIENTS[key][0],value=text))
    for key in ('basis_amount','basis_unit'):
        if declaration.get(key) is not None:values.append(dict(label=labels[key],value=str(declaration[key])))
    return values


@precise
def apply_inline_nutrients(item, before, destination, data, prefix, user_id):
    """Inputs are contributions for the displayed amount, not a second base.

    A macro edit rebases the declaration once at the displayed quantity while
    preserving other contributions. Quantity edits preserve concentrations and
    ingredient ratios.
    """
    from app.services.nutrition_import_portions import consumption
    from app.services.importers.nutrition_legacy_semantics import current, semantic_inputs
    from app.services.nutrition_sources import finite_source_number
    if item.get('ingredients') and item.get('unit') != before.get('unit'):
        if len(item['ingredients']) != 1 or item.get('summary_bindings'):
            raise NutritionError('La unidad cambió: revisa las cantidades de los ingredientes; no se convierte una composición implícitamente.')
        item['ingredients'][0].update(amount=str(decimal(item.get('amount'),positive=True)),unit=item.get('unit'))
    if (item.get('amount') != before.get('amount') and item.get('ingredients') and
            item.get('unit') == before.get('unit')):
        ratio = decimal(item['amount'], positive=True) / decimal(before.get('amount'), positive=True)
        for binding in item['ingredients']:binding['amount'] = str(decimal(binding['amount'], positive=True) * ratio)
        for proposal in item.get('ingredient_proposals', []):
            binding = proposal.get('decision_binding')
            if binding:binding['amount'] = str(decimal(binding['amount'], positive=True) * ratio)
            if proposal.get('amount'):proposal['amount']=str(decimal(proposal['amount'],positive=True)*ratio)
        if item.get('total_mass_g'):item['total_mass_g'] = str(decimal(item['total_mass_g'], positive=True) * ratio)
    changed = [(key,data[prefix+'contribution_'+key]) for key in NUTRIENTS if prefix+'contribution_'+key in data]
    if not changed:return
    # Unchanged displayed values are not rounded back into the source vector.
    old_summary = nutritional_preview(before, destination, user_id)
    changed = [(key,raw) for key,raw in changed if
        (raw.strip() != '' or (old_summary and old_summary[key]['value'] is not None)) and
        (not old_summary or (None if raw.strip()=='' else decimal(raw)) !=
            (None if old_summary[key]['value'] is None else Decimal(old_summary[key]['value'])))]
    if not changed:return
    if not item.get('basis_amount') or not item.get('basis_unit'):
        # The user explicitly declares the contribution to the shown quantity.
        decimal(item.get('amount'),positive=True)
        if item.get('unit') not in {'g','ml','portion'}:raise NutritionError('Completa primero la cantidad y su unidad.')
        item.update(basis_amount=item['amount'],basis_unit=item['unit'],basis_label=item.get('unit_label'))
    interpretation_was_current=current(item)
    if destination == 'products':factor=Decimal(1);amount=item['basis_amount'];unit=item['basis_unit']
    elif destination == 'consumed' and item.get('resolution') in {'declared','private'}:
        amount,unit,_=consumption(item)
        factor=decimal(amount,positive=True)/decimal(item['basis_amount'],positive=True)
    else:
        if item['basis_unit'] != item.get('unit'):raise NutritionError('Revisa primero la base y la unidad de estos valores.')
        amount,unit=item.get('amount'),item.get('unit')
        factor=decimal(item.get('amount'),positive=True)/decimal(item['basis_amount'],positive=True)
    # Store an edited contribution at its explicit displayed quantity. This
    # avoids dividing a user-entered value into a repeating concentration and
    # then scaling it back with rounding drift on final persistence.
    for nutrient in item['declaration'].values():
        if nutrient.get('state')=='known':nutrient['value']=finite_source_number(decimal(nutrient['value'])*factor)
        if nutrient.get('limit') is not None:nutrient['limit']=finite_source_number(decimal(nutrient['limit'])*factor)
    item.update(basis_amount=str(decimal(amount,positive=True)),basis_unit=unit)
    if item.get('basis_interpretation') and interpretation_was_current:
        item['canonical_basis_inputs']=semantic_inputs(item)
    for key, raw in changed:
        item['declaration'][key] = dict(state='unknown',value=None,unit=NUTRIENTS[key][1]) if raw.strip()=='' else dict(
            state='known', value=finite_source_number(decimal(raw)), unit=NUTRIENTS[key][1],
            provenance={'method':'user_corrected_contribution','source_sha256':item['evidence'].get('sha256')})
        item['resolved_nutrients'] = sorted(set(item.get('resolved_nutrients', [])) | {key})


def audit_edit(item, before, revision, user_id, destination):
    fields = ('name','brand','barcode','date','planned_for','meal_type','amount','unit','unit_label',
              'basis_amount','basis_unit','basis_label','declaration','ingredients','equivalence',
              'basis_interpretation','basis_conflict_resolved','equivalence_confirmed','resolution')
    changes = {key:dict(before=copy.deepcopy(before.get(key)),after=copy.deepcopy(item.get(key)))
               for key in fields if before.get(key) != item.get(key)}
    if changes:
        item['corrections'] = copy.deepcopy(before.get('corrections', [])) + [dict(
            method='user_inline_edit', revision=revision,
            at=datetime.now(timezone.utc).isoformat(), fields=changes)]
    previous=nutritional_preview(before,destination,user_id)
    following=nutritional_preview(item,destination,user_id)
    item['preview_change'] = dict(before=previous,after=following) if changes and previous and following and any(
        previous[key]['value']!=following[key]['value'] for key in MACROS) else None
