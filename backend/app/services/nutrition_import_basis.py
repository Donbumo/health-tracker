"""Verified canonical source annotations, distinct from legacy decision state."""
import copy
import re
import unicodedata

from app.services.nutrition_math import NutritionError, decimal, validate_vector
from app.services.importers.nutrition_legacy_semantics import semantic_inputs, _number

ORIGIN = 'nutrition_import_2_1'


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
    if re.search(r'not consumed|no son aportes|bases? distintas|contradict',text):return True
    basis=entry['declaration']
    for match in re.finditer(r'(?:valores|macros|nutrientes|values|nutrients)\s+(?:son|declarados|expresados|are)\s+(?:por|per)\s+100\s*(g|ml)\b',text):
        if decimal(basis['basis_amount'])!=100 or basis['basis_unit']!=match[1]:return True
    return bool(re.search(r'(?:carbohidratos|carbohydrates|carbs).*?netos?\s*,?\s*no\s+totales?',text)
                and 'carbohydrate_total' in basis['nutrients'])


def prepare(row, review):
    """GET projects proposals only; the official draft POST records acceptance.

    Reverify the owner-bound original rather than trusting provenance supplied
    by a file. Current decisions, edited bases and bindings are never reset.
    """
    for item in review['rows']:item.pop('_shared_basis_verified',None)
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
            quality=(annotation['quality'] if is_editorial else item.get('source_quality') or 'file_declared_unverified'),
            measurement_verified=False,source_annotation=copy.deepcopy(annotation))
        item['basis_interpretation']['source_inputs']=semantic_inputs(item,'explicit_basis')
        item['_shared_basis_verified']=True


def grouped(item):
    basis=item.get('basis_interpretation') or {}
    return (item.get('_shared_basis_verified') is True and clean(item)
        and basis.get('origin')==ORIGIN and basis.get('kind')=='explicit_basis' and basis.get('status')=='proposed'
        and basis.get('source_inputs')==semantic_inputs(item,'explicit_basis'))
