"""Verified canonical source annotations, distinct from legacy decision state."""
import copy
import re
import unicodedata

from app.services.nutrition_math import NutritionError, decimal, validate_vector

ORIGIN = 'nutrition_import_2_1'


def source_interpretation(value, quality=None, _depth=0):
    """Validate editorial metadata before any reader treats it as controls."""
    path='data.entries[] / declaration / provenance / basis_interpretation'
    def invalid():raise NutritionError(path+': se esperaba texto no vacío u objeto con metadatos válidos.')
    if _depth>8:invalid()
    if isinstance(value,str):
        if not value.strip():invalid()
        return dict(kind='explicit_basis',status='proposed',origin=ORIGIN,
            quality=quality if isinstance(quality,str) else 'file_declared_unverified',
            measurement_verified=False,source_annotation=value)
    if not isinstance(value,dict):invalid()
    for key in ('kind','status','origin','choice','quality','stale_reason','confirmed_by','basis_unit','consumed_quantity'):
        if key in value and not isinstance(value[key],str):invalid()
    for key in ('measurement_verified','file_conflict'):
        if key in value and not isinstance(value[key],bool):invalid()
    for key in ('source_basis','source_inputs','accepted_inputs','explicit_inputs'):
        if key not in value:continue
        part=value[key]
        if not isinstance(part,dict):invalid()
        for field in ('unit','basis_unit','unit_label','basis_label','choice','kind'):
            if field in part and part[field] is not None and not isinstance(part[field],str):invalid()
        for field in ('amount','basis_amount'):
            if field in part and part[field] is not None:
                try:decimal(part[field],positive=True)
                except NutritionError:invalid()
        if 'equivalence' in part and part['equivalence'] is not None and not isinstance(part['equivalence'],dict):invalid()
    if 'source_annotation' in value:
        source_interpretation(value['source_annotation'],_depth=_depth+1)
    return copy.deepcopy(value)


def interpretation(item):
    if 'basis_interpretation' not in item:return {}
    return source_interpretation(item['basis_interpretation'],item.get('source_quality'))


def editorial(annotation):
    return (isinstance(annotation, dict) and set(annotation) == {'consumed_quantity','basis_unit','quality'}
            and all(isinstance(v,str) for v in annotation.values()))


def textual_consumed_basis(annotation):
    """Only familiar affirmative text may become an owner-reviewable proposal.

    Text is never an accepted decision or proof of measurement. Unknown text
    remains visible in the original and requires an individual basis decision.
    """
    if not isinstance(annotation,str) or not 0<len(annotation)<=500:
        return False
    normalized=''.join(char for char in unicodedata.normalize('NFKD',annotation.casefold())
                       if not unicodedata.combining(char))
    normalized=' '.join(normalized.strip().rstrip('.').split())
    return normalized in {
        'los nutrientes corresponden a la porcion consumida',
        'los nutrientes corresponden a la cantidad consumida',
        'los valores declarados corresponden a la porcion consumida',
        'los valores declarados corresponden a la cantidad consumida',
        'nutrients correspond to the consumed portion',
        'nutrients correspond to the consumed quantity',
        'nutrientes expresados por la porcion total declarada, sin escalar en la importacion',
    }


def clean(item):
    return (not item.get('ingredients') and not item.get('summary_bindings')
        and item.get('resolution') in {None,'declared'}
        and not any(p.get('decision_binding') for p in item.get('ingredient_proposals',[]))
        and not item.get('basis_conflict') and not item.get('portion_conflict')
        and not item.get('portion_note_pending') and not item.get('unsupported_vector')
        and not (item.get('carbohydrate_proposal') and not item.get('carbohydrate_reviewed'))
        and not (set(item.get('quality_problems',[]))-set(item.get('resolved_nutrients',[])))
        and not any(w.startswith('Valor declarado ambiguo: ') and w.split(': ',1)[1] not in item.get('resolved_nutrients',[]) for w in item.get('warnings',[])))


def evidence_conflict(entry):
    text=str((entry.get('declaration') or {}).get('provenance',{}))+' '+str(entry.get('evidence',{}))
    text=text.casefold()
    if re.search(r'not consumed|no son aportes|bases? distintas|contradict|\bno\s+(?:corresponden|representan|son)\b[^.;\n]{0,100}\b(?:consumid|aportes|ingesta)|\bnot\b[^.;\n]{0,100}\bconsumed\b',text):return True
    basis=entry['declaration']
    for match in re.finditer(r'(?:valores|macros|nutrientes|values|nutrients)\s+(?:nutricionales\s+)?(?:(?:son|declarados|expresados|are)\s+)?(?:por|per)\s+100\s*(g|ml)\b',text):
        if decimal(basis['basis_amount'])!=100 or basis['basis_unit']!=match[1]:return True
    return bool(re.search(r'(?:carbohidratos|carbohydrates|carbs).*?netos?\s*,?\s*no\s+totales?',text)
                and 'carbohydrate_total' in basis['nutrients'])


def prepare(row, review):
    """GET projects proposals only; the official draft POST records acceptance.

    Reverify the owner-bound original rather than trusting provenance supplied
    by a file. Current decisions, edited bases and bindings are never reset.
    """
    from app.services.importers.nutrition_legacy_semantics import semantic_inputs, _number
    for item in review['rows']:
        item.pop('_shared_basis_verified',None)
        if 'basis_interpretation' in item:item['basis_interpretation']=interpretation(item)
    if review['destination']!='consumed' or row.source_json.get('file_issues'):return
    def pending_annotation(item):
        basis=item.get('basis_interpretation') or {}
        if not isinstance(basis,dict):return False
        return (editorial(basis) or (basis.get('origin')==ORIGIN and basis.get('status')=='proposed'
                and (editorial(basis.get('source_annotation')) or
                     textual_consumed_basis(basis.get('source_annotation')))))
    candidates=[i for i,item in enumerate(review['rows']) if not item.get('skip') and pending_annotation(item) and clean(item)]
    if not candidates:return
    from app.services import nutrition_import as imports
    try:
        _,found=imports.verified_original(row,lock=False)
    except NutritionError:return  # Without an intact original there is no grouped authority.
    document=found.get('standard')
    if not document or document.get('type')!='nutrition_import' or document.get('schema_version')!='2.1':return
    entries=document['data']['entries']
    if document['data']['destination']!='consumed' or len(entries)!=len(review['rows']):return
    for index in candidates:
        item=review['rows'][index];entry=entries[index];basis=entry.get('declaration') or {}
        annotation=basis.get('provenance',{}).get('basis_interpretation')
        is_editorial=editorial(annotation)
        if (entry!=item.get('original') or not (is_editorial or textual_consumed_basis(annotation))
                or entry.get('bindings') or entry.get('composition',{}).get('complete')):continue
        try:
            if evidence_conflict(entry):continue
            amount=decimal(entry.get('portion_amount'),positive=True)
            if amount!=decimal(basis.get('basis_amount'),positive=True):continue
            if is_editorial and amount!=decimal(annotation['consumed_quantity'],positive=True):continue
            if not entry.get('portion_unit')==basis.get('basis_unit') or entry['portion_unit'] not in {'g','ml'}:continue
            if is_editorial and entry['portion_unit']!=annotation['basis_unit']:continue
            if any(_number(item.get(k))!=_number(v) for k,v in [('amount',entry['portion_amount']),('basis_amount',basis['basis_amount'])]):continue
            if item.get('unit')!=entry['portion_unit'] or item.get('basis_unit')!=basis['basis_unit']:continue
            if item.get('unit_label') or item.get('basis_label'):continue
            vector=validate_vector(item.get('declaration',{}))
            if not any(n['state']=='known' for n in vector.values()):continue
        except NutritionError:continue
        item['basis_interpretation']=dict(kind='explicit_basis',status='proposed',origin=ORIGIN,
            quality=(annotation['quality'] if is_editorial else item['basis_interpretation'].get('quality') or 'file_declared_unverified'),
            measurement_verified=False,source_annotation=copy.deepcopy(annotation))
        item['basis_interpretation']['source_inputs']=semantic_inputs(item,'explicit_basis')
        item['_shared_basis_verified']=True


def grouped(item):
    from app.services.importers.nutrition_legacy_semantics import semantic_inputs
    basis=interpretation(item)
    return (item.get('_shared_basis_verified') is True and clean(item)
        and basis.get('origin')==ORIGIN and basis.get('kind')=='explicit_basis' and basis.get('status')=='proposed'
        and basis.get('source_inputs')==semantic_inputs(item,'explicit_basis'))
