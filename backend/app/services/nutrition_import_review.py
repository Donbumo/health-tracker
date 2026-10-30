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
from app.services.importers.nutrition_legacy_semantics import current as interpretation_current


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


def prepared(row,destination=None):
    """Resolve exact file identities without changing persistent review state."""
    review = copy.deepcopy(row.review_json)
    if destination is not None:review['destination']=destination
    cache = {}
    for index,item in enumerate(review['rows']):
        proposals = item.get('ingredient_proposals')
        # Preserve compositions already reviewed through the legacy endpoint.
        if proposals and (item.get('summary_bindings') or not item.get('ingredients')):
            item['summary_bindings'] = True
            item['ingredients'] = []
            for proposal in proposals:
                binding = proposal.get('decision_binding') or exact_binding(row.user_id, proposal, cache)
                if binding:
                    item['ingredients'].append(copy.deepcopy(binding))
        if not proposals and not item.get('ingredients') and not item.get('resolution'):
            binding=exact_binding(row.user_id,item,cache)
            if binding:item['ingredients']=[binding]
        if item.get('resolution') == 'declared' and review['destination']=='consumed':
            item['ingredients']=[];item['summary_bindings']=False;item['composition_complete']=False
        elif item.get('resolution') == 'private':
            try:item['ingredients']=[private_proposal(item)];item['summary_bindings']=False
            except NutritionError:pass
        if review['destination']=='products' and not item.get('ingredients'):
            try:
                item['ingredients']=[private_proposal(item)]
            except NutritionError:
                pass
        # Derive a sufficient declaration without a technical acceptance POST.
        # prepared() copies JSON: GET never persists this choice.
        if (row.source_json.get('extractor_version')==imports.EXTRACTOR_VERSION and
                review['destination']=='consumed' and not item.get('resolution') and
                not row.review_json['rows'][index].get('ingredients') and
                not any(p.get('decision_binding') for p in item.get('ingredient_proposals',[]))):
            try:
                from app.services.nutrition_import_portions import sufficient
                sufficient(item)
            except NutritionError:
                pass
            else:
                item.update(resolution='declared', ingredients=[], summary_bindings=False, composition_complete=False)
    return review


def private_proposal(item):
    from app.services.nutrition_math import validate_vector
    nutrition=dict(basis_amount=str(decimal(item.get('basis_amount'),positive=True)),
        basis_unit=item.get('basis_unit'),nutrients=validate_vector(item['declaration']),
        servings=[],density_g_ml=None,barcode=item.get('barcode'),
        metadata={'brand':item.get('brand'),'quality':'file_declared',
                  'net_content_text':item.get('net_content_text','')},
        provenance={'method':'user_confirmed_file',**{'evidence_'+k:v for k,v in item['evidence'].items() if isinstance(v,(str,int,float,bool,type(None)))}})
    if not item.get('name') or not nutrition['nutrients'] or nutrition['basis_unit'] not in {'g','ml'}:
        raise NutritionError('Falta una definición explícita con nombre, base y nutrientes.')
    amount=item.get('amount') or nutrition['basis_amount']
    unit=item.get('unit') or nutrition['basis_unit']
    if unit=='portion':
        from app.services.nutrition_import_portions import consumption
        amount,unit,quantity=consumption(item)
        nutrition['provenance'].update(consumed_amount=quantity['amount'],consumed_unit=quantity['unit'],
            equivalence_amount=quantity.get('equivalence_per_unit',{}).get('amount'),
            equivalence_unit=quantity.get('equivalence_per_unit',{}).get('unit'),
            equivalence_verified=quantity.get('equivalence_confirmed',False))
    if unit not in {'g','ml'}:raise NutritionError('Unidad de cantidad no verificada.')
    return dict(new_food=dict(name=item['name'],brand=item.get('brand'),nutrition=nutrition),
                amount=str(decimal(amount,positive=True)),unit=unit)


def issue(code, message, **values):
    return dict(code=code, message=message, **values)


def row_issues(row, review, index):
    item = review['rows'][index]
    errors = []
    if item.get('basis_conflict') and not item.get('basis_conflict_resolved'):
        errors.append(issue('basis_conflict','El archivo declara bases nutricionales contradictorias. Revisa a qué cantidad pertenecen sus valores.'))
    interpretation=item.get('basis_interpretation') or {}
    if (review['destination']=='consumed' and interpretation and
            not interpretation_current(item)):
        errors.append(issue('interpretation',interpretation.get('stale_reason') or 'Confirma si los nutrientes pertenecen a la cantidad original, a la cantidad consumida o a una base distinta.'))
    for nutrient in item.get('quality_problems',[]):
        if nutrient not in item.get('resolved_nutrients',[]):
            errors.append(issue('nutrient','La nota de origen describe un marcador operativo, no un cero conocido. Conserva desconocido o introduce un valor verificado.',nutrient=nutrient))
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
    declared_only = review['destination']=='consumed' and item.get('resolution')=='declared'
    if declared_only:
        try:
            from app.services.nutrition_import_portions import sufficient
            sufficient(item)
        except NutritionError as error:errors.append(issue('portion',str(error)))
    if item.get('summary_bindings') and not declared_only:
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
    if not item.get('ingredients') and review['destination'] in {'plan', 'consumed', 'recipes'} and not item.get('summary_bindings') and not declared_only and not interpretation:
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
        code='date_conflict' if (getattr(error,'status',None)==409 and review['destination']=='consumed' and ('fecha' in str(error) or 'solapamiento' in str(error))) else 'domain'
        errors.append(issue(code,str(error)))
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
        from app.services.nutrition_import_preview import nutritional_preview
        preview=nutritional_preview(item,review['destination'],row.user_id)
        records.append(dict(index=index, item=item, state=state, issues=errors, bindings=bindings,preview=preview))
    from app.models import DailyNutrition
    conflicts=[]
    if review['destination']=='consumed':
        for target in sorted({item.get('date') for item in review['rows'] if item.get('date')}):
            try:parsed=date.fromisoformat(target)
            except ValueError:continue
            day=db.session.scalar(db.select(DailyNutrition).where(DailyNutrition.user_id==row.user_id,DailyNutrition.date==parsed))
            if day:conflicts.append(dict(date=target,legacy=day.authority is None,
                count=sum(item.get('date')==target for item in review['rows'])))
    eligible=0
    for record in records:
        try:
            from app.services.nutrition_import_portions import sufficient
            sufficient(record['item'])
            if not record['item'].get('ingredients') and record['item'].get('resolution') not in {'declared','private'}:eligible+=1
        except NutritionError:pass
    from app.services.importers.nutrition_legacy_semantics import grouped
    from app.services.nutrition_import_preview import presentation
    return dict(review=review, records=records, counts=counts, day_conflicts=conflicts, declaration_eligible=eligible,
        **presentation(records,review['destination']),
        legacy_total_count=sum(grouped(item) for item in review['rows'] if not item.get('skip')),
        newly_extracted_declarations=sum('new_source_declaration_requires_review' in detail['fields']
            for detail in row.source_json.get('retained_decisions',[])))


def document(row, view=None):
    if row.source_json.get('reprocess_pending'):
        raise NutritionError('Revisa y acepta los campos conservados de la revisión anterior antes de confirmar.')
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
    edit_index = None
    if 'edit_index' in data:
        try:edit_index=int(data['edit_index'])
        except (TypeError,ValueError) as error:raise NutritionError('Registro inválido.') from error
        if not 0 <= edit_index < len(row.review_json['rows']):raise NutritionError('Registro inválido.')
        if any(data.get(k) for k in ('destination','accept_previous','accept_legacy_totals','use_declarations')) or any(k.startswith('day_') for k in data):
            raise NutritionError('La edición de una fila no cambia el destino ni otras fechas.')
    if data.get('destination'):
        if data['destination'] not in imports.DESTINATIONS:
            raise NutritionError('Selecciona un destino válido.')
    review = prepared(row,destination=data.get('destination') or None)
    persisted = copy.deepcopy(row.review_json)
    for index, item in enumerate(review['rows']):
        if edit_index is not None and index != edit_index:
            review['rows'][index]=persisted['rows'][index]
            continue
        before=copy.deepcopy(item)
        prefix = f'r{index}_'
        from app.services.importers.nutrition_legacy_semantics import grouped,accept,invalidate_changed,semantic_inputs,equivalence_inputs
        previous_semantics=semantic_inputs(item)
        day_prefix='day_'+str(item.get('date',''))+'_'
        for field in ('conflict_action','authority'):
            if data.get(day_prefix+field):item[field]=data[day_prefix+field]
        for nutrient,value in item.get('declaration',{}).items():
            raw=data.get(prefix+'declared_'+nutrient)
            if raw not in (None,'') and raw!=str(value.get('value') if value.get('value') is not None else ''):
                if value.get('state')!='known' or value.get('unit')!=NUTRIENTS[nutrient][1]:
                    raise NutritionError('Corrige explícitamente el estado y la unidad antes de introducir un valor absoluto.')
                item['declaration'][nutrient]=dict(state='known',value=str(decimal(raw)),unit=NUTRIENTS[nutrient][1],
                    provenance={'method':'user_confirmed','source_sha256':item['evidence'].get('sha256')})
        for field in ('name', 'date', 'planned_for', 'meal_type', 'basis_amount', 'basis_unit', 'amount', 'unit', 'conflict_action', 'authority', 'brand', 'barcode', 'unit_label', 'basis_label'):
            if prefix + field in data:
                item[field] = data[prefix + field].strip()[:200]
                if field in {'unit','basis_unit','unit_label','basis_label'}:
                    item[field]=' '.join(item[field].split()).casefold()
        for field in ('amount','basis_amount'):
            if prefix+field in data:decimal(item.get(field),positive=True)
        proposed_semantics=semantic_inputs(item)
        if previous_semantics != proposed_semantics and item.get('basis_conflict_resolved'):
            item['basis_conflict_resolved']=False
        if data.get(prefix+'basis_verified')=='yes':
            decimal(item.get('basis_amount'),positive=True)
            if item.get('basis_unit') not in {'g','ml','portion'}:raise NutritionError('Selecciona una unidad de base válida.')
            item['basis_conflict_resolved']=True
        proposed_semantics=semantic_inputs(item)
        labels_changed=any(previous_semantics[k]!=proposed_semantics[k] for k in ('unit','basis_unit','unit_label','basis_label'))
        if labels_changed:
            item['equivalence_confirmed']=False
            item['portion_label_confirmed']=False
        if labels_changed or previous_semantics['amount']!=proposed_semantics['amount']:
            item['portion_text_reviewed']=False
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
                    provenance={'method': 'user_confirmed', 'source_sha256': item['evidence'].get('sha256')})
            elif action:
                raise NutritionError('Decisión de nutriente inválida.')
            if action:
                item['resolved_nutrients'] = list(set(item.get('resolved_nutrients', [])) | {nutrient})
        old_equivalence=equivalence_inputs(item)
        if prefix+'equivalence_amount' in data and data[prefix+'equivalence_amount'].strip():
            item['equivalence']={'amount':str(decimal(data[prefix+'equivalence_amount'],positive=True)),
                                 'unit':data.get(prefix+'equivalence_unit')}
        if equivalence_inputs(item)!=old_equivalence:
            item['equivalence_confirmed']=False
        if data.get(prefix+'equivalence_confirmed')=='yes':
            item['equivalence_confirmed']=True
            item['equivalence']=dict(item.get('equivalence') or {},verification='user_verified_quantity')
        if data.get(prefix+'portion_text_reviewed')=='yes':item['portion_text_reviewed']=True
        if data.get(prefix+'portion_label_confirmed')=='yes':item['portion_label_confirmed']=True
        if edit_index is not None and interpretation_current(before):
            interpretation=item.get('basis_interpretation') or {}
            after_semantics=semantic_inputs(item)
            stable_basis=all(previous_semantics[k]==after_semantics[k] for k in previous_semantics if k!='amount')
            fixed_basis=(interpretation.get('status')=='explicit' or
                interpretation.get('choice') in {'source_total','explicit_basis','per_100g','per_100ml'})
            if stable_basis and fixed_basis:
                # A scoped quantity edit cannot change a verified concentration
                # or the original source-total basis. Keep that interpretation;
                # consumed-total, changed labels/bases/equivalences still expire.
                item['canonical_basis_inputs']=after_semantics
        invalidate_changed(item)
        semantic_choice=data.get(prefix+'interpretation')
        group_requested=data.get('accept_legacy_totals')=='yes' and grouped(item)
        if semantic_choice or group_requested:
            accept(item,semantic_choice or 'source_total')
        choice=data.get(prefix+'resolution')
        selected_identity=any(k.startswith(prefix) and k.endswith('_ref') and v for k,v in data.items())
        if selected_identity and not choice:choice='catalog'
        if data.get('use_declarations')=='yes' and not item.get('ingredients') and not choice and not selected_identity:
            try:
                from app.services.nutrition_import_portions import sufficient
                sufficient(item);choice='declared'
            except NutritionError:pass
        if choice:
            if choice not in {'declared','private','catalog'}:raise NutritionError('Resolución inválida.')
            if choice=='declared' and review['destination']!='consumed':raise NutritionError('La declaración sin producto sólo registra consumos.')
            item['resolution']=choice
            if choice=='declared' and interpretation_current(item):
                from app.services.nutrition_import_portions import sufficient
                sufficient(item)
                item['ingredients']=[];item['summary_bindings']=False;item['composition_complete']=False
        if (choice=='private' or data.get(prefix + 'private') == 'yes') and interpretation_current(item):
            item['ingredients'] = [private_proposal(item)]
            item['summary_bindings'] = False
            item['resolution']='private'
        proposals = item.get('ingredient_proposals') if item.get('summary_bindings') else [item]
        for part, proposal in enumerate(proposals or []):
            number = part if item.get('summary_bindings') else -1
            part_prefix = prefix + f'p{number}_'
            if part_prefix+'query' in data:proposal['search_query']=data[part_prefix+'query'].strip()[:100]
            ref = data.get(part_prefix + 'ref')
            # An amount correction may reuse only the already exact identity.
            binding = proposal.get('decision_binding') or exact_binding(user_id, proposal, {})
            current = binding or proposal
            changed = any(data.get(part_prefix + field) not in (None, '') and
                          data[part_prefix + field] != str(current.get(field) or '')
                          for field in ('amount', 'unit'))
            if (ref or (changed and binding)) and item.get('resolution') not in {'declared','private'}:
                if not ref and not binding:
                    raise NutritionError('Elige una identidad para este ingrediente.')
                item['resolution']='catalog'
                selected_ref,separator,selected_revision=(ref or binding['ref']).partition('|')
                food = catalog.detail(user_id,selected_ref,selected_revision if separator else (binding or {}).get('food_revision'))
                amount = data.get(part_prefix + 'amount', (binding or proposal).get('amount'))
                unit = data.get(part_prefix + 'unit', (binding or proposal).get('unit'))
                if unit=='portion' and proposal is item:
                    from app.services.nutrition_import_portions import consumption
                    amount,unit,_=consumption(item)
                ingredient(food, amount, unit)
                selected = dict(ref=food['ref'], food_revision=str(food['revision']), amount=str(decimal(amount, positive=True)), unit=unit)
                if item.get('summary_bindings'):
                    proposal['decision_binding'] = selected
                else:
                    item['ingredients'] = [selected]
        item['confirmed'] = False
        if edit_index is not None:
            from app.services.nutrition_import_preview import apply_inline_nutrients, audit_edit
            apply_inline_nutrients(item,before,review['destination'],data,prefix,user_id)
            audit_edit(item,before,row.revision,user_id,review['destination'])
    if row.source_json.get('reprocess_pending') and data.get('accept_previous')=='yes':
        row.source_json=dict(row.source_json,reprocess_pending=False)
    row.review_json = review
    row.revision += 1
    db.session.flush()
    return row
