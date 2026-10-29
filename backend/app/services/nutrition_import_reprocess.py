"""Explicit, owner-locked fork from a verified original. No domain writes."""
import copy

from app.extensions import db
from app.models import NutritionImportDraft, NutritionImportReceipt
from app.services import nutrition_import as imports
from app.services.nutrition_math import NutritionError, decimal, validate_vector
from app.services.importers.nutrition_sources import EXTRACTOR_VERSION


def carry_decisions(previous, fresh):
    """Conservative same-position/source alignment; retained values need review."""
    review=copy.deepcopy(fresh.review_json)
    for key in ('name','destination'):
        if previous.review_json.get(key):review[key]=previous.review_json[key]
    retained=[]
    fields=('name','brand','barcode','date','planned_for','meal_type','notes','skip',
            'composition_complete','total_mass_g','yield_factor','conflict_action','authority',
            'carbohydrate_reviewed','carbohydrate_classification','resolved_nutrients','resolution','search_query')
    for index,old in enumerate(previous.review_json['rows']):
        if index>=len(review['rows']) or old.get('original')!=review['rows'][index].get('original'):
            retained.append({'row':index+1,'fields':[],'unapplied':True})
            continue
        item=review['rows'][index];copied=[]
        for key in fields:
            if key in old:item[key]=copy.deepcopy(old[key]);copied.append(key)
        for amount,unit in [('amount','unit'),('basis_amount','basis_unit')]:
            try:decimal(old.get(amount),positive=True)
            except NutritionError:continue
            if old.get(unit) not in {'g','ml','portion'}:continue
            item[amount]=old[amount];item[unit]=old[unit];copied.extend([amount,unit])
            if unit=='unit' and old[unit] in {'g','ml'}:item.pop('unit_label',None)
        try:vector=validate_vector(old.get('declaration',{}))
        except NutritionError:pass
        else:
            item['declaration']=copy.deepcopy(old.get('declaration',{}));copied.append('declaration')
        if old.get('ingredients'):
            item['ingredients']=copy.deepcopy(old['ingredients']);copied.append('ingredients')
        old_parts=old.get('ingredient_proposals',[]);parts=item.get('ingredient_proposals',[])
        for number,part in enumerate(old_parts):
            if number<len(parts) and part.get('original')==parts[number].get('original'):
                for key in ('decision_binding','search_query'):
                    if key in part:parts[number][key]=copy.deepcopy(part[key]);copied.append('ingredient_'+key)
        if old.get('summary_bindings'):item['summary_bindings']=True
        # A parsed equivalent is always a new unverified proposal, even if an
        # older draft had accepted another conversion or composition.
        item['confirmed']=False
        retained.append({'row':index+1,'fields':copied,'unapplied':False})
    fresh.review_json=review
    return retained


def reprocess(user_id,key,revision):
    imports.ni.enabled();imports.ni.lock_owner(user_id)
    previous=imports.owned(user_id,key,True)
    try:matches=int(revision)==previous.revision
    except (TypeError,ValueError):matches=False
    status=imports.review_status(previous)
    if not matches or not status['can_reprocess']:
        raise NutritionError('La revisión cambió o no admite reprocesado. Reabre el resumen.',409)
    if db.session.scalar(db.select(NutritionImportReceipt.id).where(
            NutritionImportReceipt.user_id==user_id,NutritionImportReceipt.source_sha256==previous.source_sha256)):
        raise NutritionError('El archivo ya tiene un recibo confirmado; no se crea otra revisión.',409)
    source,found=imports.verified_original(previous)
    existing=db.session.scalars(db.select(NutritionImportDraft).where(
        NutritionImportDraft.user_id==user_id,NutritionImportDraft.source_sha256==previous.source_sha256,
        NutritionImportDraft.source_json['reprocessed_from'].as_string()==previous.public_id,
        NutritionImportDraft.source_json['reprocessed_revision'].as_integer()==previous.revision,
        NutritionImportDraft.source_json['extractor_version'].as_string()==EXTRACTOR_VERSION,
        NutritionImportDraft.state=='pending').order_by(NutritionImportDraft.id.desc()).with_for_update()).all()
    for candidate in existing:
        if imports.review_status(candidate)['can_resume']:return candidate
    fresh=imports._review_from_source(user_id,found,source,reuse=False)
    retained=carry_decisions(previous,fresh)
    fresh.source_json=dict(fresh.source_json,reprocessed_from=previous.public_id,
        reprocessed_revision=previous.revision,reprocessed_expired=status['expired'],
        retained_decisions=retained,reprocess_pending=True)
    db.session.flush()
    return fresh
