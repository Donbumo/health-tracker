"""Versioned complete nutrition section in official account export/restore.

Historical values are self-contained; importing never needs a live catalog.
Ownership and DB IDs are remapped from account restore's verified dictionaries.
"""
import copy
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from uuid import uuid5, NAMESPACE_URL
from sqlalchemy.orm import selectinload
from app.extensions import db
from app.models import FoodProduct, Recipe, DailyNutrition, NutritionMeal, NutritionItem
from app.models.nutrition_intelligence import MealLog
from app.services.nutrition_math import NutritionError, ingredient, summarize, LEGACY, validate_vector
from app.services.nutrition_intelligence import hash_document, lock_owner, recalculate
from app.services.validation import validate_json_document


def export_bundle(user_id):
    logs=db.session.execute(db.select(MealLog).where(MealLog.user_id==user_id).order_by(MealLog.id)).scalars().all()
    foods=db.session.execute(db.select(FoodProduct).where(FoodProduct.user_id==user_id)).scalars().all()
    recipes=db.session.execute(db.select(Recipe).where(Recipe.user_id==user_id,Recipe.nutrition_snapshot_json.is_not(None))).scalars().all()
    days=db.session.execute(db.select(DailyNutrition).where(DailyNutrition.user_id==user_id,DailyNutrition.authority.is_not(None))).scalars().all()
    if not (logs or any(p.nutrition_json is not None for p in foods) or recipes or days):
        return None
    log_rows=[]
    owned_items=db.session.execute(db.select(NutritionItem).where(NutritionItem.user_id==user_id)
        .options(selectinload(NutritionItem.meal))).scalars().all()
    items_by_id={item.id:item for item in owned_items}
    for log in logs:
        item=items_by_id[log.projection_item_id]
        log_rows.append({'identity':log.public_id,'client_event_id':log.client_event_id,'revision':log.revision,
            'local_date':log.local_date.isoformat(),'consumed_at':consumed_timestamp(log.consumed_at),
            'timezone':log.timezone,'recipe_id':log.recipe_id,'meal_order':item.meal.sort_order,
            'item_order':item.sort_order,'snapshot':copy.deepcopy(log.snapshot_json)})
    authority=[]
    for day in days:
        baseline=copy.deepcopy(day.authority_baseline_json)
        if baseline:
            coords=[]
            for key in baseline.pop('included_item_ids',[]):
                item=items_by_id.get(key)
                if item:
                    coords.append({'meal_order':item.meal.sort_order,'item_order':item.sort_order})
            baseline['included_items']=coords
        authority.append({'date':day.date.isoformat(),'authority':day.authority,'baseline':baseline})
    bundle={'schema_version':'2.0','type':'nutrition_intelligence','foods':[
        {'source_id':p.id,'identity':p.public_id,'revision':p.revision,'name':p.name,'brand':p.brand,'nutrition':p.nutrition_json or {'nutrients':{},'servings':[],'density_g_ml':None}} for p in foods],
        'templates':[{'source_id':r.id,'identity':r.public_id,'revision':r.revision,'name':r.name,'snapshot':copy.deepcopy(r.nutrition_snapshot_json)} for r in recipes],
        'logs':log_rows,'authorities':authority}
    validate_bundle(bundle)
    return bundle


def validate_snapshot(snapshot):
    try:
        date.fromisoformat(snapshot['local_date'])
        ZoneInfo(snapshot['timezone'])
    except (ValueError, TypeError, ZoneInfoNotFoundError) as error:
        raise NutritionError('Fecha o zona horaria del snapshot inválida.') from error
    entries=snapshot['ingredients']
    if not entries or len(entries)>100:
        raise NutritionError('Snapshot requiere ingredientes válidos.')
    calculated=[ingredient(e['food'],e['amount'],e['unit'],e.get('serving_id')) for e in entries]
    if hash_document(calculated)!=hash_document(entries) or hash_document(summarize(calculated))!=hash_document(snapshot['summary']):
        raise NutritionError('Snapshot y cálculo no coinciden; no se importan totales del cliente.')


def validate_bundle(bundle):
    validate_json_document(bundle,'nutrition_intelligence_2')
    for food in bundle['foods']:
        validate_vector(food['nutrition'].get('nutrients',{}))
    for row in bundle['templates']+bundle['logs']:
        validate_snapshot(row['snapshot'])
    for section, key in [('foods','identity'),('templates','identity'),('logs','identity'),('authorities','date')]:
        values=[r[key] for r in bundle[section]]
        if len(values)!=len(set(values)):
            raise NutritionError('Identidades duplicadas en export.')
    authority_dates={r['date'] for r in bundle['authorities']}
    for row in bundle['logs']:
        if row['local_date']!=row['snapshot']['local_date'] or row['timezone']!=row['snapshot']['timezone'] or row['local_date'] not in authority_dates:
            raise NutritionError('Evento, snapshot y autoridad del día no coinciden.')
    for row in bundle['authorities']:
        baseline=row['baseline']
        expected='disjoint_aggregate' if row['authority']=='disjoint_aggregate' else 'derive_items'
        if (baseline and baseline['choice']!=expected) or (row['authority']=='disjoint_aggregate' and baseline is None):
            raise NutritionError('Autoridad y baseline no coinciden.')
    identities=[r['client_event_id'] for r in bundle['logs']]
    if len(identities)!=len(set(identities)):
        raise NutritionError('Eventos duplicados en export.')


def consumed_timestamp(value):
    if value is None:
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)).isoformat()


def same_event(existing,row):
    incoming=datetime.fromisoformat(row['consumed_at']) if row['consumed_at'] else None
    return existing.revision==row['revision'] and consumed_timestamp(existing.consumed_at)==consumed_timestamp(incoming) and semantic_snapshot(existing.snapshot_json)==semantic_snapshot(row['snapshot'])


def semantic_snapshot(snapshot):
    value=copy.deepcopy(snapshot)
    for k in ['recipe_id','save_target','save_base_revision']:
        value.pop(k,None)
    for e in value['ingredients']:
        if e['food'].get('scope')=='user':
            e['food']['ref']=None
            e['food']['source_food_id']=None
    return hash_document(value)


def plan_bundle(bundle,user_id):
    validate_bundle(bundle)
    all_existing=True
    for row in bundle['logs']:
        existing=db.session.execute(db.select(MealLog).where(MealLog.user_id==user_id,MealLog.client_event_id==row['client_event_id'])).scalar_one_or_none()
        if existing and not same_event(existing,row):
            raise NutritionError('El evento existente difiere. No se sobrescribe historia.',409)
        if not existing: all_existing=False
    for row in bundle['foods']:
        product=db.session.execute(db.select(FoodProduct).where(FoodProduct.user_id==user_id,FoodProduct.name==row['name'],
            FoodProduct.brand==row['brand'] if row['brand'] is not None else FoodProduct.brand.is_(None))).scalar_one_or_none()
        if not product or product.nutrition_json!=row['nutrition']: all_existing=False
    for row in bundle['templates']:
        recipe=db.session.execute(db.select(Recipe).where(Recipe.user_id==user_id,Recipe.name==row['name'])).scalar_one_or_none()
        if not recipe or not recipe.nutrition_snapshot_json or semantic_snapshot(recipe.nutrition_snapshot_json)!=semantic_snapshot(row['snapshot']): all_existing=False
    for row in bundle['authorities']:
        day=db.session.execute(db.select(DailyNutrition).where(DailyNutrition.user_id==user_id,DailyNutrition.date==date.fromisoformat(row['date']))).scalar_one_or_none()
        if not day or day.authority!=row['authority']: all_existing=False
    return 'skip' if all_existing else 'insert'


def restore_bundle(bundle,user_id,id_maps):
    validate_bundle(bundle)
    lock_owner(user_id)
    food_refs={}
    for row in bundle['foods']:
        key=id_maps.get('food_products',{}).get(row['source_id'])
        product=db.session.execute(db.select(FoodProduct).where(FoodProduct.user_id==user_id,FoodProduct.id==key)).scalar_one_or_none()
        if not product: raise NutritionError('Falta remapeo owner-only del alimento.')
        product.nutrition_json=copy.deepcopy(row['nutrition'])
        product.revision=max(product.revision,row['revision'])
        food_refs[row['identity']]=product.public_id
    def remap(doc):
        doc=copy.deepcopy(doc)
        for k in ['save_target','save_base_revision']: doc.pop(k,None)
        if doc.get('recipe_id'):
            doc['recipe_id']=id_maps.get('recipes',{}).get(doc['recipe_id'])
            if doc['recipe_id'] is None: raise NutritionError('Falta receta incluida en export.')
        for e in doc['ingredients']:
            old=e['food'].get('source_food_id')
            if e['food'].get('scope')=='user':
                if old not in food_refs:
                    raise NutritionError('Falta identidad personal incluida en export.')
                e['food']['source_food_id']=food_refs[old]
                e['food']['ref']='user:'+food_refs[old]
        return doc
    # Templates can include catalog ingredients that legacy recipe import cannot represent.
    for row in bundle['templates']:
        key=id_maps.get('recipes',{}).get(row['source_id'])
        recipe=db.session.execute(db.select(Recipe).where(Recipe.user_id==user_id,Recipe.id==key)).scalar_one_or_none() if key else None
        if not recipe:
            recipe=db.session.execute(db.select(Recipe).where(Recipe.user_id==user_id,Recipe.name==row['name'])).scalar_one_or_none()
        from app.services.nutrition_intelligence import restore_recipe_snapshot
        snapshot=copy.deepcopy(row['snapshot'])
        snapshot.pop('recipe_id',None)
        recipe=restore_recipe_snapshot(user_id,row['name'],snapshot,row['revision'],recipe)
        id_maps.setdefault('recipes',{})[row['source_id']]=recipe.id
    for row in bundle['templates']:
        recipe=db.session.execute(db.select(Recipe).where(Recipe.user_id==user_id,Recipe.id==id_maps['recipes'][row['source_id']])).scalar_one()
        recipe.nutrition_snapshot_json=remap(row['snapshot'])
        for part,entry in zip(sorted(recipe.ingredients,key=lambda part:part.sort_order),recipe.nutrition_snapshot_json['ingredients'],strict=True):
            part.nutrition_snapshot_json=copy.deepcopy(entry)
    days={}
    def day_record(target):
        if target not in days:
            row=db.session.execute(db.select(DailyNutrition).where(DailyNutrition.user_id==user_id,DailyNutrition.date==date.fromisoformat(target))).scalar_one_or_none()
            if not row: raise NutritionError('Falta día legacy/proyección incluida en export.')
            days[target]=row
        return days[target]
    def projection(day,meal_order,item_order):
        return db.session.execute(db.select(NutritionItem).join(NutritionMeal).where(
            NutritionItem.user_id==user_id,NutritionMeal.user_id==user_id,NutritionMeal.daily_nutrition_id==day.id,
            NutritionMeal.sort_order==meal_order,NutritionItem.sort_order==item_order)).scalar_one_or_none()
    for row in bundle['logs']:
        existing=db.session.execute(db.select(MealLog).where(MealLog.user_id==user_id,MealLog.client_event_id==row['client_event_id'])).scalar_one_or_none()
        if existing:
            if not same_event(existing,row): raise NutritionError('Historia en conflicto.',409)
            continue
        day=day_record(row['local_date'])
        item=projection(day,row['meal_order'],row['item_order'])
        if not item: raise NutritionError('Falta proyección legacy del evento.')
        doc=remap(row['snapshot'])
        for n,col in LEGACY.items():
            value=doc['summary'][n]['value']
            expected=Decimal(value).quantize(Decimal('0.001'),rounding=ROUND_HALF_UP) if value is not None else None
            if getattr(item,col)!=expected: raise NutritionError('Proyección y snapshot no coinciden.')
        destination=str(uuid5(NAMESPACE_URL,f'health-tracker/nutrition/{user_id}/{row["identity"]}'))
        db.session.add(MealLog(public_id=destination,user_id=user_id,client_event_id=row['client_event_id'],revision=row['revision'],
            local_date=date.fromisoformat(row['local_date']),consumed_at=datetime.fromisoformat(row['consumed_at']).astimezone(timezone.utc) if row['consumed_at'] else None,
            timezone=row['timezone'],projection_item_id=item.id,recipe_id=id_maps.get('recipes',{}).get(row['recipe_id']) if row['recipe_id'] else None,
            snapshot_json=doc))
    for row in bundle['authorities']:
        day=day_record(row['date'])
        baseline=copy.deepcopy(row['baseline'])
        if baseline:
            keys=[]
            for coord in baseline.pop('included_items',[]):
                item=projection(day,coord['meal_order'],coord['item_order'])
                if not item: raise NutritionError('Referencia baseline no encontrada.')
                keys.append(item.id)
            baseline['included_item_ids']=keys
        day.authority,day.authority_baseline_json=row['authority'],baseline
    db.session.flush()
    for day in days.values():
        recalculate(day)
    return len(bundle['logs'])
