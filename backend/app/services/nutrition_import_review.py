"""Compact review over the existing atomic file receipt; no partial import.

Read helpers copy draft JSON. Only save_decisions mutates a pending review;
canonical domain writes still belong to StandardImportExecutor.
"""
import copy
from datetime import date

from app.extensions import db
from app.models.nutrition_intelligence import CatalogFood, FoodCatalogRevision
from app.services import food_catalog as catalog, nutrition_import as imports
from app.services.nutrition_math import NUTRIENTS, NutritionError, decimal, ingredient


def exact_binding(user_id, proposal, cache):
    """An explicit identity AND preparation AND revision, never a fuzzy match."""
    raw = proposal['original']
    if any(not isinstance(raw.get(key), (str, int, type(None))) or isinstance(raw.get(key), bool)
           for key in ('ref', 'source', 'source_food_id', 'revision', 'preparation')):
        return None
    identity = (raw.get('ref'), raw.get('source'), raw.get('source_food_id'),
                raw.get('revision'), raw.get('preparation'))
    if identity not in cache:
        food = None
        if raw.get('revision') is not None and raw.get('preparation'):
            ref = raw.get('ref')
            if not ref and raw.get('source') and raw.get('source_food_id') is not None:
                row = db.session.execute(catalog.catalog_query().where(
                    FoodCatalogRevision.source_id == str(raw['source']),
                    CatalogFood.source_food_id == str(raw['source_food_id']))).scalar_one_or_none()
                ref = 'catalog:' + row.public_id if row else None
            if ref:
                try:
                    candidate = catalog.detail(user_id, ref)
                    if (str(candidate['revision']) == str(raw['revision']) and
                            candidate['preparation'].strip().casefold() == str(raw['preparation']).strip().casefold()):
                        food = candidate
                except NutritionError:
                    pass
        cache[identity] = food
    food = cache[identity]
    if not food:
        return None
    return {'ref': food['ref'], 'food_revision': str(food['revision']),
            'amount': proposal.get('amount'), 'unit': proposal.get('unit')}


def prepared(row):
    """Resolve exact file identities without changing persistent review state."""
    review = copy.deepcopy(row.review_json)
    cache = {}
    for item in review['rows']:
        proposals = item.get('ingredient_proposals')
        # Preserve compositions already reviewed through the legacy endpoint.
        if proposals and (item.get('summary_bindings') or not item.get('ingredients')):
            item['summary_bindings'] = True
            item['ingredients'] = []
            for proposal in proposals:
                binding = proposal.get('decision_binding') or exact_binding(row.user_id, proposal, cache)
                if binding:
                    item['ingredients'].append(copy.deepcopy(binding))
        if review['destination']=='products' and not item.get('ingredients'):
            try:
                item['ingredients']=[private_proposal(item)]
            except NutritionError:
                pass
    return review


def private_proposal(item):
    from app.services.nutrition_math import validate_vector
    nutrition=dict(basis_amount=str(decimal(item.get('basis_amount'),positive=True)),
        basis_unit=item.get('basis_unit'),nutrients=validate_vector(item['declaration']),
        servings=[],density_g_ml=None,barcode=item.get('barcode'),
        metadata={'brand':item.get('brand'),'quality':'file_declared',
                  'net_content_text':item.get('net_content_text','')},
        provenance={'method':'file_declared','evidence':item['evidence']})
    if not item.get('name') or not nutrition['nutrients'] or nutrition['basis_unit'] not in {'g','ml'}:
        raise NutritionError('Falta una definición explícita con nombre, base y nutrientes.')
    amount=item.get('amount') or nutrition['basis_amount']
    unit=item.get('unit') or nutrition['basis_unit']
    if unit not in {'g','ml'}:raise NutritionError('Unidad de cantidad no verificada.')
    return dict(new_food=dict(name=item['name'],brand=item.get('brand'),nutrition=nutrition),
                amount=str(decimal(amount,positive=True)),unit=unit)


def issue(code, message, **values):
    return dict(code=code, message=message, **values)


def row_issues(row, review, index):
    item = review['rows'][index]
    errors = []
    if item.get('unsupported_vector'):
        errors.append(issue('unsupported','El vector de nutrientes no cumple el vocabulario o las unidades: corrige el archivo y vuelve a subirlo.'))
    if not item.get('name') and review['destination'] != 'daily_aggregate':
        errors.append(issue('name', 'Indica el nombre de este registro.'))
    if review['destination'] in {'consumed', 'recipes', 'daily_aggregate'}:
        try:
            date.fromisoformat(item.get('date', ''))
        except (ValueError, TypeError):
            errors.append(issue('date', 'Falta una fecha de calendario válida.'))
    if review['destination'] in {'plan', 'consumed', 'recipes'} and item.get('meal_type') not in {'breakfast', 'lunch', 'dinner', 'snack', 'other'}:
        errors.append(issue('meal_type', 'Selecciona el momento de esta comida.'))
    if item.get('carbohydrate_proposal') and not item.get('carbohydrate_reviewed'):
        errors.append(issue('carbohydrate', 'El archivo no distingue carbohidratos totales y netos.'))
    if 'Cantidad ilegible o ambigua.' in item.get('warnings', []):
        try: decimal(item.get('amount'), positive=True)
        except NutritionError: errors.append(issue('amount', 'La cantidad del registro es ambigua; introduce la cantidad verificada.'))
    for key, value in item.get('declaration', {}).items():
        if key not in NUTRIENTS or value.get('unit') != NUTRIENTS[key][1]:
            errors.append(issue('nutrient', 'Revisa la cantidad absoluta y unidad de ' + key + '.', nutrient=key))
    # Failed numbers/percentages cannot silently disappear from a ready row.
    for warning in item.get('warnings', []):
        if warning.startswith('Valor declarado ambiguo: '):
            key = warning.split(': ', 1)[1]
            if key not in item.get('resolved_nutrients', []):
                errors.append(issue('nutrient', 'Valor ilegible o porcentual: ' + key + '; no es una cantidad verificada.', nutrient=key))
    if item.get('summary_bindings'):
        for part, proposal in enumerate(item['ingredient_proposals']):
            binding = proposal.get('decision_binding') or exact_binding(row.user_id, proposal, {})
            messages = []
            if not binding:
                messages.append('Identidad, preparación o revisión sin vínculo inequívoco.')
            try:
                amount = (binding or proposal).get('amount')
                decimal(amount, positive=True)
            except NutritionError:
                messages.append('Falta una cantidad positiva verificable.')
            if (binding or proposal).get('unit') not in {'g', 'ml'}:
                messages.append('Unidad ambigua; indica g o ml verificados.')
            if proposal.get('ingredient_proposals'):
                messages.append('Componentes anidados: separa la composición en el archivo; no se aplana automáticamente.')
            if messages:
                errors.append(issue('ingredient', ' '.join(messages), part=part, proposal=proposal, identity_bound=bool(binding)))
    if not item.get('ingredients') and review['destination'] in {'plan', 'consumed', 'recipes'} and not item.get('summary_bindings'):
        # A single explicit food can be resolved by the same strict identity rule.
        binding = exact_binding(row.user_id, item, {})
        if binding:
            item['ingredients'] = [binding]
        else:
            errors.append(issue('ingredient', 'Vincula la identidad y cantidad; buscar por nombre no confirma equivalencia.', part=-1, proposal=item))
    if item.get('declaration'):
        try:
            decimal(item.get('basis_amount') or item.get('amount'), positive=True)
            if (item.get('basis_unit') or item.get('unit')) not in {'g', 'ml', 'portion'}:
                raise NutritionError('Base no verificada.')
        except NutritionError:
            errors.append(issue('basis', 'Indica la base exacta de los valores declarados.'))
    if errors:
        return errors
    try:
        document = imports.canonical(row, review, only_index=index)
        imports.validate_document(document, row.user_id)
    except (NutritionError, ValueError) as error:
        errors.append(issue('domain', str(error)))
    return errors


def overview(row):
    review = prepared(row)
    records = []
    foods = {}
    counts = dict(ready=0, decision=0, invalid=0, omitted=0)
    for index, item in enumerate(review['rows']):
        errors = [] if item.get('skip') else row_issues(row, review, index)
        empty = not item.get('name') and not item.get('declaration') and not item.get('ingredients') and not item.get('ingredient_proposals')
        state = 'omitted' if item.get('skip') else 'invalid' if empty or item.get('unsupported_vector') else 'decision' if errors else 'ready'
        counts[state] += 1
        bindings = []
        for binding in item.get('ingredients', []):
            food = binding.get('new_food')
            if not food:
                key = (binding['ref'], binding.get('food_revision'))
                if key not in foods:
                    try: foods[key] = catalog.detail(row.user_id, *key)
                    except NutritionError: foods[key] = None
                food = foods[key]
            bindings.append(dict(binding=binding, food=food))
        records.append(dict(index=index, item=item, state=state, issues=errors, bindings=bindings))
    return dict(review=review, records=records, counts=counts)


def document(row, view=None):
    view = view or overview(row)
    if view['counts']['decision'] or view['counts']['invalid']:
        raise NutritionError('Resuelve las excepciones agrupadas antes de confirmar el lote.')
    review = copy.deepcopy(view['review'])
    for item in review['rows']:
        item['confirmed'] = True  # One global preview/consent, not per-row POSTs.
    result = imports.canonical(row, review)
    imports.validate_document(result, row.user_id)
    return result


def save_decisions(user_id, key, revision, data):
    """One draft POST for all contextual exceptions; no domain writes."""
    imports.ni.enabled(); imports.ni.lock_owner(user_id)
    row = imports.owned(user_id, key, True)
    imports.assert_pending(row, revision)
    review = prepared(row)
    if data.get('destination'):
        if data['destination'] not in imports.DESTINATIONS:
            raise NutritionError('Selecciona un destino válido.')
        review['destination'] = data['destination']
    for index, item in enumerate(review['rows']):
        prefix = f'r{index}_'
        for field in ('name', 'date', 'planned_for', 'meal_type', 'basis_amount', 'basis_unit', 'amount', 'unit', 'conflict_action', 'authority'):
            if prefix + field in data:
                item[field] = data[prefix + field].strip()[:200]
        choice = data.get(prefix + 'carbohydrate')
        if choice:
            if choice not in {'total', 'net', 'unknown'}:
                raise NutritionError('Clasificación de carbohidratos inválida.')
            proposal = item.get('carbohydrate_proposal')
            if not proposal:
                raise NutritionError('No hay carbohidratos pendientes en esta fila.')
            if choice != 'unknown':
                if proposal.get('unit') != 'g':
                    raise NutritionError('No se convierten porcentajes ni unidades ambiguas a gramos.')
                item['declaration']['carbohydrate_total' if choice == 'total' else 'net_carbs'] = copy.deepcopy(proposal)
            item['carbohydrate_reviewed'] = True
            item['carbohydrate_classification'] = choice
        for nutrient, (_, unit, _) in NUTRIENTS.items():
            action = data.get(prefix + 'nutrient_' + nutrient + '_action')
            if action == 'unknown':
                item['declaration'].pop(nutrient, None)
            elif action == 'value':
                item['declaration'][nutrient] = dict(state='known', value=str(decimal(data.get(prefix + 'nutrient_' + nutrient))), unit=unit,
                    provenance={'method': 'user_confirmed', 'evidence': item['evidence']})
            elif action:
                raise NutritionError('Decisión de nutriente inválida.')
            if action:
                item['resolved_nutrients'] = list(set(item.get('resolved_nutrients', [])) | {nutrient})
        if data.get(prefix + 'private') == 'yes':
            item['ingredients'] = [private_proposal(item)]
            item['summary_bindings'] = False
        proposals = item.get('ingredient_proposals') if item.get('summary_bindings') else [item]
        for part, proposal in enumerate(proposals or []):
            number = part if item.get('summary_bindings') else -1
            part_prefix = prefix + f'p{number}_'
            ref = data.get(part_prefix + 'ref')
            # An amount correction may reuse only the already exact identity.
            binding = proposal.get('decision_binding') or exact_binding(user_id, proposal, {})
            current = binding or proposal
            changed = any(data.get(part_prefix + field) not in (None, '') and
                          data[part_prefix + field] != str(current.get(field) or '')
                          for field in ('amount', 'unit'))
            if ref or changed:
                if not ref and not binding:
                    raise NutritionError('Elige una identidad para este ingrediente.')
                food = catalog.detail(user_id, ref or binding['ref'])
                amount = data.get(part_prefix + 'amount', (binding or proposal).get('amount'))
                unit = data.get(part_prefix + 'unit', (binding or proposal).get('unit'))
                ingredient(food, amount, unit)
                selected = dict(ref=food['ref'], food_revision=str(food['revision']), amount=str(decimal(amount, positive=True)), unit=unit)
                if item.get('summary_bindings'):
                    proposal['decision_binding'] = selected
                else:
                    item['ingredients'] = [selected]
        item['confirmed'] = False
    row.review_json = review
    row.revision += 1
    db.session.flush()
    return row
