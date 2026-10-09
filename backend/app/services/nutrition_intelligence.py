"""Official owner-scoped preview/confirmation service, without internal commits."""
import copy
import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
from zoneinfo import ZoneInfo
from flask import current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature
from sqlalchemy.orm import selectinload
from app.extensions import db
from app.models import User, DailyNutrition, NutritionMeal, NutritionItem, Recipe, RecipeIngredient, FoodProduct
from app.models.nutrition_intelligence import MealDraft, MealLog
from app.services.food_catalog import detail, details
from app.services.nutrition_math import NutritionError, NUTRIENTS, LEGACY, PRODUCT, ingredient, summarize, decimal


def enabled():
    if not current_app.config.get("NUTRITION_INTELLIGENCE_ENABLED"):
        raise NutritionError("Nutrition Intelligence todavía no está habilitado.", 404)


def lock_owner(user_id):
    owner = db.session.execute(db.select(User).where(User.id==user_id).with_for_update()
        .execution_options(populate_existing=True)).scalar_one_or_none()
    if owner is None:
        raise NutritionError("Usuario no encontrado.",404)
    return owner


def owned_draft(user_id, key, lock=False):
    query = db.select(MealDraft).where(MealDraft.user_id==user_id, MealDraft.public_id==key)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = db.session.execute(query).scalar_one_or_none()
    if row is None:
        raise NutritionError("Borrador no encontrado.",404)
    return row


def owned_log(user_id, key):
    row = db.session.execute(db.select(MealLog).where(MealLog.user_id==user_id, MealLog.public_id==key)).scalar_one_or_none()
    if row is None:
        raise NutritionError("Comida no encontrada.",404)
    return row


def hash_document(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":"),ensure_ascii=False).encode()).hexdigest()


def make_snapshot(entries, name, target, meal_type, timezone_name):
    if not isinstance(name,str) or not name.strip() or len(name)>200:
        raise NutritionError("Indica el nombre de la comida.")
    try:
        date.fromisoformat(target)
        ZoneInfo(timezone_name)
    except (ValueError,TypeError,KeyError) as error:
        raise NutritionError("Fecha o zona horaria inválida.") from error
    if meal_type not in {"breakfast","lunch","dinner","snack","other"}:
        raise NutritionError("Momento de comida inválido.")
    return {"schema_version":"2.0", "calculation_method":"decimal_scaled_v1",
        "name":name.strip(), "local_date":target, "meal_type":meal_type, "timezone":timezone_name,
        "ingredients":entries, "summary":summarize(entries)}


def create_draft(user_id, *, target=None, name="Mi comida", meal_type="lunch", entries=None):
    enabled()
    owner = lock_owner(user_id)
    if entries is not None and (not isinstance(entries,list) or len(entries)>100):
        raise NutritionError("Demasiados ingredientes.")
    resolved = []
    for entry in entries or []:
        if set(entry)-{"ref","revision","amount","unit","serving_id"}:
            raise NutritionError("Campos no permitidos en selección.")
    for entry,food in zip(entries or [],details(user_id,entries or []),strict=True):
        resolved.append(ingredient(food,entry["amount"],entry["unit"],entry.get("serving_id")))
    snapshot = make_snapshot(resolved,name,target or datetime.now(ZoneInfo(owner.timezone or 'UTC')).date().isoformat(),meal_type,owner.timezone or "UTC")
    row = MealDraft(user_id=user_id, snapshot_json=snapshot, accepted_json=[])
    db.session.add(row)
    db.session.flush()
    return row


def mutate_draft(user_id, key, revision, action, data):
    enabled()
    lock_owner(user_id)
    row = owned_draft(user_id,key,True)
    if row.state != "pending" or row.revision != int(revision):
        raise NutritionError("El borrador cambió. Reabre y revisa.",409)
    snapshot = copy.deepcopy(row.snapshot_json)
    entries = snapshot["ingredients"]
    accepted = set(row.accepted_json)
    if action == "add":
        if len(entries)>=100:
            raise NutritionError("Máximo 100 ingredientes.")
        food = detail(user_id,data["ref"],data.get("food_revision"))
        entries.append(ingredient(food,data["amount"],data["unit"],data.get("serving_id") or None))
    elif action in {"amount","accept","remove"}:
        index = int(data["index"])
        if index < 0 or index >= len(entries):
            raise NutritionError("Ingrediente no encontrado.")
        if action == "amount":
            entries[index] = ingredient(entries[index]["food"],data["amount"],data["unit"],data.get("serving_id") or None)
            accepted.discard(index)
        elif action == "accept":
            accepted.add(index)
        else:
            entries.pop(index)
            accepted = {a if a<index else a-1 for a in accepted if a != index}
    elif action == "metadata":
        snapshot = dict(snapshot, **make_snapshot(entries,data["name"],data["date"],data["meal_type"],snapshot["timezone"]))
    else:
        raise NutritionError("Acción inválida.")
    snapshot["summary"] = summarize(entries)
    row.snapshot_json, row.accepted_json = snapshot, sorted(accepted)
    row.revision += 1
    db.session.flush()
    return row


def confirmation_token(row):
    return URLSafeTimedSerializer(current_app.secret_key,salt="nutrition-meal-confirm-v2").dumps({
        "owner":row.user_id,"draft":row.public_id,"revision":row.revision,"sha":hash_document(row.snapshot_json)})


def pending(row):
    return len(row.snapshot_json["ingredients"]) - len(row.accepted_json)


def day_items(day, lock=False):
    query=db.select(NutritionItem).join(NutritionMeal).where(
        NutritionMeal.daily_nutrition_id==day.id, NutritionItem.user_id==day.user_id)
    if lock:
        query=query.with_for_update().execution_options(populate_existing=True)
    return db.session.execute(query).scalars().all()


def resolve_authority(day, choice=None):
    if day.authority:
        return
    items = day_items(day,lock=True)
    # No legacy data is invented; every existing day requires reviewed authority.
    if choice not in {"derive_items","disjoint_aggregate"}:
        raise NutritionError("El día tiene datos legacy. Revisa y elige si el agregado se solapa con esta comida.",409)
    day.authority_baseline_json = {"original_totals":{k:str(getattr(day,k)) if getattr(day,k) is not None else None for k in LEGACY.values()},
                                  "included_item_ids":[i.id for i in items], "choice":choice}
    day.authority = "derived" if choice == "derive_items" else "disjoint_aggregate"


def recalculate(day):
    items = day_items(day,lock=True)
    baseline = day.authority_baseline_json or {}
    excluded = set(baseline.get("included_item_ids",[])) if day.authority == "disjoint_aggregate" else set()
    for field in LEGACY.values():
        values = [getattr(i,field) for i in items if i.id not in excluded and getattr(i,field) is not None]
        if day.authority == "disjoint_aggregate" and baseline.get("original_totals",{}).get(field) is not None:
            values.append(Decimal(baseline["original_totals"][field]))
        if sum(values,Decimal(0)) >= Decimal('1000000000'):
            raise NutritionError('El total diario supera la capacidad del formato legacy.')
        setattr(day,field,sum(values,Decimal(0)) if values else None)
    day.updated_at = datetime.now(timezone.utc)
    day.nutrition_summary_json = daily_summary(day.user_id,day.date,lock=True)['summary']


def confirm(user_id, token, *, authority=None):
    enabled()
    try:
        claims = URLSafeTimedSerializer(current_app.secret_key,salt="nutrition-meal-confirm-v2").loads(token,max_age=1800)
    except BadSignature as error:
        raise NutritionError("Confirmación inválida o vencida.",409) from error
    if claims.get("owner") != user_id:
        raise NutritionError("Confirmación no encontrada.",404)
    lock_owner(user_id)
    row = owned_draft(user_id,claims["draft"],True)
    if claims["revision"] != row.revision or claims["sha"] != hash_document(row.snapshot_json):
        raise NutritionError("El preview cambió. Revisa de nuevo.",409)
    existing = db.session.execute(db.select(MealLog).where(MealLog.user_id==user_id,
        MealLog.client_event_id==row.public_id).with_for_update()).scalar_one_or_none()
    if existing is not None:
        return existing, True
    if row.state != "pending" or pending(row) or not row.snapshot_json["ingredients"]:
        raise NutritionError("Confirma identidad y cantidad de todos los ingredientes.")
    snapshot = copy.deepcopy(row.snapshot_json)
    # Only server-owned food snapshots are inputs; never trust client totals.
    entries = [ingredient(e["food"],e["amount"],e["unit"],e.get("serving_id")) for e in snapshot["ingredients"]]
    snapshot["ingredients"], snapshot["summary"] = entries, summarize(entries)
    target = date.fromisoformat(snapshot["local_date"])
    day = db.session.execute(db.select(DailyNutrition).where(DailyNutrition.user_id==user_id,
        DailyNutrition.date==target).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if day is None:
        day = DailyNutrition(user_id=user_id,date=target,source="manual",authority="derived")
        db.session.add(day)
        db.session.flush()
    else:
        resolve_authority(day,authority)
    sort = (db.session.execute(db.select(db.func.max(NutritionMeal.sort_order)).where(NutritionMeal.daily_nutrition_id==day.id).with_for_update()).scalar_one() or 0)+1
    meal = NutritionMeal(user_id=user_id,daily_nutrition_id=day.id,meal_type=snapshot["meal_type"],name=snapshot["name"],sort_order=sort)
    db.session.add(meal)
    db.session.flush()
    values = {column:Decimal(snapshot["summary"][key]["value"]).quantize(Decimal('0.001'),rounding=ROUND_HALF_UP) if snapshot["summary"][key]["value"] is not None else None for key,column in LEGACY.items()}
    if any(value is not None and value >= Decimal('1000000000') for value in values.values()):
        raise NutritionError('El aporte supera la capacidad del formato legacy. Revisa las cantidades.')
    item = NutritionItem(user_id=user_id,nutrition_meal_id=meal.id,name=snapshot["name"],sort_order=1,
        source="manual",client_event_id=row.public_id,**values)
    db.session.add(item)
    db.session.flush()
    log = MealLog(user_id=user_id,client_event_id=row.public_id,local_date=target,
        timezone=snapshot["timezone"],projection_item_id=item.id,snapshot_json=snapshot,
        recipe_id=snapshot.get("recipe_id"))
    db.session.add(log)
    row.state = "completed"
    recalculate(day)
    db.session.flush()
    return log, False


def repeat(user_id,key, target=None):
    enabled()
    source = owned_log(user_id,key)
    draft = create_draft(user_id,target=target,name=source.snapshot_json["name"],meal_type=source.snapshot_json["meal_type"])
    doc = copy.deepcopy(source.snapshot_json)
    doc["local_date"],doc['timezone'] = draft.snapshot_json['local_date'],draft.snapshot_json['timezone']
    draft.snapshot_json, draft.accepted_json = doc, []
    db.session.flush()
    return draft


def save_template(user_id,key, revision, *, recipe_key=None, base_revision=None):
    enabled()
    lock_owner(user_id)
    draft = owned_draft(user_id,key,True)
    if draft.state!='pending' or draft.revision!=int(revision) or pending(draft) or not draft.snapshot_json['ingredients']:
        raise NutritionError("Revisa los ingredientes antes de guardar.",409)
    doc = copy.deepcopy(draft.snapshot_json)
    if any(e['normalized']['mass_g'] is None for e in doc['ingredients']):
        raise NutritionError("La receta legacy necesita masa conocida; registra volumen sólo como consumo.")
    validate_recipe_projection(doc)
    if recipe_key:
        recipe = db.session.execute(db.select(Recipe).where(Recipe.user_id==user_id,Recipe.public_id==recipe_key)
            .with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
        if not recipe:
            raise NutritionError("Comida guardada no encontrada.",404)
        receipt=(recipe.raw_payload_json or {}).get('nutrition_save',{})
        if receipt=={'draft':key,'revision':int(revision)}:
            return recipe
        if recipe.revision!=int(base_revision):
            raise NutritionError("La comida guardada cambió.",409)
        recipe.ingredients.clear()
        db.session.flush()
        recipe.revision += 1
    else:
        if db.session.execute(db.select(Recipe.id).where(Recipe.user_id==user_id,Recipe.name==doc['name'])).first():
            raise NutritionError("Ya existe una receta con este nombre. Elige editar.",409)
        recipe = Recipe(user_id=user_id,name=doc['name'],servings=Decimal(1),source='manual')
        db.session.add(recipe)
        db.session.flush()
    recipe.name, recipe.nutrition_snapshot_json = doc['name'], doc
    recipe.raw_payload_json=dict(recipe.raw_payload_json or {},nutrition_save={'draft':key,'revision':int(revision)})
    # A saved draft keeps the optimistic revision for subsequent explicit edits.
    draft.snapshot_json = dict(doc, recipe_id=recipe.id, recipe_revision=recipe.revision,
        save_target=recipe.public_id, save_base_revision=recipe.revision)
    recipe.yield_weight_g = sum((Decimal(e['normalized']['mass_g']) for e in doc['ingredients']),Decimal(0))
    for index,e in enumerate(doc['ingredients'],1):
        mass = Decimal(e['normalized']['mass_g'])
        fields = {column:Decimal(e['contribution'][n]['value'])*100/mass if e['contribution'][n]['state']=='known' else None for n,column in PRODUCT.items()}
        product_id = None
        if e['food']['scope']=='user':
            product_id = db.session.execute(db.select(FoodProduct.id).where(FoodProduct.user_id==user_id,FoodProduct.public_id==e['food']['source_food_id'])).scalar_one_or_none()
        recipe.ingredients.append(RecipeIngredient(user_id=user_id,name_snapshot=e['food']['name'],quantity_g=mass,
            sort_order=index,food_product_id=product_id,nutrition_snapshot_json=e,**fields))
    db.session.flush()
    return recipe


def template_draft(user_id,key,target=None):
    recipe = db.session.execute(db.select(Recipe).where(Recipe.user_id==user_id,Recipe.public_id==key,Recipe.is_active.is_(True))
        .options(selectinload(Recipe.ingredients))).scalar_one_or_none()
    if not recipe:
        raise NutritionError("Comida guardada no encontrada.",404)
    draft = create_draft(user_id,target=target,name=recipe.name)
    if recipe.nutrition_snapshot_json:
        doc = copy.deepcopy(recipe.nutrition_snapshot_json)
        doc['local_date'],doc['timezone'] = draft.snapshot_json['local_date'],draft.snapshot_json['timezone']
    else:
        entries=[]
        for row in recipe.ingredients:
            vector={n:{'value':str(getattr(row,col)) if getattr(row,col) is not None else None,
                       'state':'known' if getattr(row,col) is not None else 'unknown','unit':NUTRIENTS[n][1]} for n,col in PRODUCT.items()}
            food={'name':row.name_snapshot,'revision':str(recipe.revision),'ref':None,'scope':'legacy',
                'source':'legacy_recipe','preparation':'Snapshot de receta legacy','basis_unit':'g','basis_amount':'100',
                'nutrients':vector,'servings':[],'density_g_ml':None,'provenance':{'method':'legacy_declared'}}
            entries.append(ingredient(food,row.quantity_g/recipe.servings,'g'))
        doc=make_snapshot(entries,recipe.name,draft.snapshot_json['local_date'],'lunch',draft.snapshot_json['timezone'])
    doc['recipe_id'],doc['recipe_revision']=recipe.id,recipe.revision
    draft.snapshot_json=doc
    db.session.flush()
    return draft


def legacy_ingredient(item):
    vector={n:{'value':str(getattr(item,col)) if getattr(item,col) is not None else None,
               'state':'known' if getattr(item,col) is not None else 'unknown','unit':NUTRIENTS[n][1]} for n,col in LEGACY.items()}
    # Values already consumed: base 1, amount 1; don't invent legacy mass.
    return {'food':{'source':'legacy','name':item.name},'normalized':{'mass_g':None},'contribution':vector}


def daily_summary(user_id,target,lock=False):
    day_query=db.select(DailyNutrition).where(DailyNutrition.user_id==user_id,DailyNutrition.date==target)
    log_query=db.select(MealLog).where(MealLog.user_id==user_id,MealLog.local_date==target).order_by(MealLog.id)
    if lock:
        day_query=day_query.with_for_update().execution_options(populate_existing=True)
        log_query=log_query.with_for_update().execution_options(populate_existing=True)
    day = db.session.execute(day_query).scalar_one_or_none()
    logs=db.session.execute(log_query).scalars().all()
    if not day:
        return {'day':None,'logs':[],'summary':summarize([]),'legacy_detail_missing':False}
    projections={l.projection_item_id for l in logs}
    baseline=day.authority_baseline_json or {}
    excluded=set(baseline.get('included_item_ids',[])) if day.authority=='disjoint_aggregate' else set()
    items=day_items(day,lock=lock)
    legacy=[i for i in items if i.id not in projections and i.id not in excluded]
    entries=[e for l in logs for e in l.snapshot_json['ingredients']]+[legacy_ingredient(i) for i in legacy]
    if day.authority=='disjoint_aggregate' or not items:
        totals=baseline.get('original_totals',{}) if day.authority=='disjoint_aggregate' else {c:str(getattr(day,c)) if getattr(day,c) is not None else None for c in LEGACY.values()}
        pseudo=type('LegacyValues',(),dict(name='Agregado legacy',**{c:totals.get(c) for c in LEGACY.values()}))()
        entries.append(legacy_ingredient(pseudo))
    summary=summarize(entries)
    # Legacy daily totals remain authoritative where their detailed basis is unavailable.
    if day.authority is None:
        for nutrient,field in LEGACY.items():
            value=getattr(day,field)
            summary[nutrient]['value']=str(value) if value is not None else None
            summary[nutrient]['state']='partial' if value is not None else 'unknown'
            summary[nutrient]['coverage']=None
            summary[nutrient]['total_weight']=None
    return {'day':day,'logs':logs,'summary':summary,'legacy_detail_missing':bool(legacy or not items or excluded)}


def guard_legacy_item(item):
    """Old Android must not flatten or destroy a full consumed snapshot."""
    if db.session.execute(db.select(MealLog.id).where(MealLog.user_id==item.user_id,MealLog.projection_item_id==item.id)).first():
        raise NutritionError("Esta comida tiene snapshot completo. Revisa desde Nutrition Intelligence.",409)
    baseline=item.meal.daily_nutrition.authority_baseline_json or {}
    if item.meal.daily_nutrition.authority is None and item.meal.daily_nutrition.raw_payload_json is not None:
        raise NutritionError('El día importado necesita revisión explícita de autoridad antes de editar sus entradas.',409)
    if item.id in baseline.get('included_item_ids',[]) and item.meal.daily_nutrition.authority=='disjoint_aggregate':
        raise NutritionError("Esta entrada pertenece al agregado legacy conservado.",409)


def comparison_value(day,field):
    """Legacy behavior retained; partial new subtotals cannot imply deficits."""
    if day is None:
        return None
    nutrient=next((n for n,c in LEGACY.items() if c==field),None)
    quality=(day.nutrition_summary_json or {}).get(nutrient)
    if quality and quality['state']!='complete':
        return None
    return getattr(day,field)


def validate_recipe_projection(snapshot):
    masses=[Decimal(e['normalized']['mass_g']) for e in snapshot['ingredients'] if e['normalized']['mass_g'] is not None]
    if len(masses)!=len(snapshot['ingredients']) or sum(masses,Decimal(0))>=Decimal('1000000000') or any(m.quantize(Decimal('0.001'),rounding=ROUND_HALF_UP)==0 for m in masses):
        raise NutritionError('La masa no se puede representar en la receta legacy; el snapshot consumido conserva su precisión.')
    for e,mass in zip(snapshot['ingredients'],masses,strict=True):
        if any(Decimal(e['contribution'][n]['value'])*100/mass>=Decimal('10000000') for n in PRODUCT if e['contribution'][n]['state']=='known'):
            raise NutritionError('El valor supera la capacidad de la receta legacy.')


def restore_recipe_snapshot(user_id, name, snapshot, revision, existing=None):
    """Official versioned restore adapter; caller validates and owns transaction."""
    if existing and existing.user_id != user_id:
        raise NutritionError("Receta no encontrada.",404)
    validate_recipe_projection(snapshot)
    recipe=existing or Recipe(user_id=user_id,name=name,servings=Decimal(1),source='manual')
    if existing:
        recipe.ingredients.clear()
        db.session.flush()
    db.session.add(recipe)
    recipe.revision=revision
    recipe.nutrition_snapshot_json=copy.deepcopy(snapshot)
    recipe.yield_weight_g=sum((Decimal(e['normalized']['mass_g']) for e in snapshot['ingredients']),Decimal(0))
    for index,e in enumerate(snapshot['ingredients'],1):
        mass=Decimal(e['normalized']['mass_g'])
        fields={column:Decimal(e['contribution'][n]['value'])*100/mass if e['contribution'][n]['state']=='known' else None for n,column in PRODUCT.items()}
        recipe.ingredients.append(RecipeIngredient(user_id=user_id,name_snapshot=e['food']['name'],quantity_g=mass,sort_order=index,nutrition_snapshot_json=e,**fields))
    db.session.flush()
    return recipe
