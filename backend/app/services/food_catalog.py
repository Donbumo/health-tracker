"""Administrative bounded local snapshots; everyday lookups never use Internet."""
import copy
import hashlib
import json
import re
import unicodedata
from uuid import NAMESPACE_URL, uuid5
from decimal import Decimal
from sqlalchemy import or_, case, func
from app.extensions import db
from app.models import FoodProduct
from app.models.nutrition_intelligence import (FoodCatalogSource as SourceState,
    FoodCatalogRevision, CatalogFood, Nutrient, FoodNutrient, FoodServing)
from app.services.nutrition_math import NUTRIENTS, PRODUCT, NutritionError, decimal, validate_vector


def search_text(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value)).casefold() if not unicodedata.combining(c))


# Reviewed lexical translations only. They retrieve candidates, never select
# an identity, merge vectors or equate raw/cooked foods or tortilla/chips.
SEARCH_WORDS = {
    'arroz': ('arroz', 'rice'), 'rice': ('rice', 'arroz'),
    'blanco': ('blanco', 'white'), 'white': ('white', 'blanco'),
    'integral': ('integral', 'brown'),
    'pollo': ('pollo', 'chicken'), 'chicken': ('chicken', 'pollo'),
    'pechuga': ('pechuga', 'breast'), 'breast': ('breast', 'pechuga'),
    'frijol': ('frijol', 'frijoles', 'bean', 'beans'), 'frijoles': ('frijol', 'frijoles', 'bean', 'beans'), 'beans': ('bean', 'beans', 'frijol', 'frijoles'),
    'negro': ('negro', 'black'), 'negros': ('negro', 'black'),
    'maiz': ('maiz', 'maíz', 'corn'), 'corn': ('corn', 'maiz', 'maíz'),
    'tortilla': ('tortilla','tortillas'), 'tortillas': ('tortilla','tortillas'),
    'totopos': ('tortilla chips', 'chips de tortilla', 'totopos'),
    'avena': ('avena', 'oat', 'oats', 'oatmeal'), 'oats': ('oat', 'oats', 'avena'),
    'harina': ('harina', 'flour'), 'leche': ('leche', 'milk'),
    'refritos': ('refritos','refrito','refried'),
}
SEARCH_STATES = {'crudo': 'raw', 'cruda': 'raw', 'raw': 'raw',
                 'crudos':'raw','crudas':'raw','cocidos':'cooked','cocidas':'cooked',
                 'cocido': 'cooked', 'cocida': 'cooked', 'cooked': 'cooked'}


def like_pattern(text, *, prefix=False):
    escaped = text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return ('' if prefix else '%') + escaped + '%'


def search_metadata(food):
    metadata = food.get('metadata') or {}
    aliases = metadata.get('aliases', [])
    if not isinstance(aliases, list) or len(aliases) > 100 or any(not isinstance(a, str) or len(a) > 1000 for a in aliases):
        raise NutritionError('Aliases del catálogo inválidos.')
    for key, length in [('brand', 200), ('barcode', 32), ('food_type', 64), ('preparation_state', 16)]:
        if metadata.get(key) is not None and (not isinstance(metadata[key], str) or len(metadata[key]) > length):
            raise NutritionError('Metadata de catálogo inválida.')
    return {'search_text': search_text(' '.join([food['name'], food['preparation'], food.get('source_name', ''), *aliases,
                           metadata.get('brand') or '', metadata.get('barcode') or ''])),
            **{key: metadata.get(key) for key in ['brand', 'barcode', 'food_type', 'preparation_state']}}


class FoodCatalogSource:
    """Neutral adapter interface; source aliases are confined to normalization."""
    def normalize(self, document):
        raise NotImplementedError

    def validate(self, document):
        if document.get("schema_version") != "2.0" or not isinstance(document.get("foods"), list):
            raise NutritionError("Snapshot de catálogo inválido.")
        if not document.get("license") or not document.get("source") or not document.get("revision"):
            raise NutritionError("Falta licencia, fuente o revisión.")
        if len(document["foods"]) > 100000:
            raise NutritionError("Snapshot excede el límite revisado de indexado.")
        identities = set()
        for food in document["foods"]:
            identity = food.get("source_food_id")
            if not identity or len(identity)>64 or identity in identities:
                raise NutritionError("Identidad duplicada o inválida.")
            identities.add(identity)
            if food.get("source") != document["source"] or not food.get("revision"):
                raise NutritionError("Procedencia inconsistente.")
            for key in ("name", "preparation"):
                if not isinstance(food.get(key), str) or not food[key].strip() or len(food[key])>200:
                    raise NutritionError("Nombre o preparación inválidos.")
            search_metadata(food)
            if food.get("basis_unit") not in {"g", "ml"}:
                raise NutritionError("Base incompatible.")
            decimal(food["basis_amount"], positive=True)
            if food.get("density_g_ml") is not None:
                decimal(food["density_g_ml"], positive=True)
            validate_vector(food["nutrients"])
            serving_ids = set()
            for serving in food.get("servings", []):
                if serving.get("id") in serving_ids or not serving.get("id") or len(serving['id'])>64:
                    raise NutritionError("Porción duplicada o inválida.")
                serving_ids.add(serving["id"])
                decimal(serving["amount"], positive=True)
                if serving.get("unit") not in {"g", "ml"} or not serving.get('label') or len(serving['label'])>200:
                    raise NutritionError("Equivalencia de porción inválida.")
        if not identities:
            raise NutritionError("Catálogo vacío.")
        return document


class LocalSnapshotSource(FoodCatalogSource):
    def normalize(self, document):
        return self.validate(document)


def stage(document, adapter=None):
    document = (adapter or LocalSnapshotSource()).normalize(document)
    source_id, revision = document["source"], document["revision"]
    if len(source_id)>64 or len(revision)>64:
        raise NutritionError("Identidad de catálogo demasiado larga.")
    encoded = json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    state = db.session.get(SourceState, source_id)
    if state is None:
        state = SourceState(id=source_id, name=source_id, license=document["license"])
        db.session.add(state)
        db.session.flush()
    existing = db.session.execute(db.select(FoodCatalogRevision).where(
        FoodCatalogRevision.source_id==source_id, FoodCatalogRevision.revision==revision)).scalar_one_or_none()
    if existing:
        if existing.sha256 != digest:
            raise NutritionError("Una revisión publicada no puede cambiar.", 409)
        return existing
    for key, (name, unit, group) in NUTRIENTS.items():
        if db.session.get(Nutrient, key) is None:
            db.session.add(Nutrient(id=key, name=name, unit=unit, group=group))
    record = FoodCatalogRevision(source_id=source_id, revision=revision, sha256=digest,
        state="staged", manifest_json={k:v for k,v in document.items() if k!='foods'} | {"food_count":len(document["foods"]), "bytes":len(encoded)})
    db.session.add(record)
    db.session.flush()
    # Bounded batches avoid a flush and ORM object per nutrient for a full USDA
    # source. IDs are deterministic within the immutable source revision.
    for start in range(0, len(document['foods']), 250):
        foods = document['foods'][start:start + 250]
        rows = [CatalogFood(catalog_revision_id=record.id, source_food_id=food['source_food_id'],
                 public_id=str(uuid5(NAMESPACE_URL, f"health-tracker/catalog/{source_id}/{revision}/{food['source_food_id']}")),
                 name=food['name'], preparation=food['preparation'], snapshot_json=food, **search_metadata(food)) for food in foods]
        db.session.add_all(rows)
        db.session.flush()
        nutrients, servings = [], []
        for row, food in zip(rows, foods, strict=True):
            for key, value in validate_vector(food['nutrients']).items():
                nutrients.append({'food_id':row.id, 'nutrient_id':key, 'state':value['state'],
                    'value':Decimal(value['value']) if value['value'] is not None else None, 'provenance_json':value})
            for serving in food.get('servings', []):
                servings.append({'food_id':row.id, 'source_serving_id':serving['id'], 'label':serving['label'],
                                 'amount':Decimal(serving['amount']), 'unit':serving['unit']})
        if nutrients:
            db.session.execute(db.insert(FoodNutrient), nutrients)
        if servings:
            db.session.execute(db.insert(FoodServing), servings)
    db.session.flush()
    return record


def activate(source_id, revision, base_revision):
    state = db.session.execute(db.select(SourceState).where(SourceState.id==source_id)
        .with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if not state:
        raise NutritionError("Fuente no encontrada.",404)
    if state.revision != base_revision:
        raise NutritionError("Otra operación cambió el catálogo.",409)
    record = db.session.execute(db.select(FoodCatalogRevision).where(
        FoodCatalogRevision.source_id==source_id, FoodCatalogRevision.revision==revision)).scalar_one_or_none()
    if not record or record.state not in {"staged", "validated"}:
        raise NutritionError("Revisión no validada.")
    state.previous_revision, state.active_revision = state.active_revision, revision
    state.revision += 1
    record.state = "validated"
    db.session.flush()
    return state


def rollback(source_id, base_revision):
    state = db.session.execute(db.select(SourceState).where(SourceState.id==source_id)
        .with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if not state or state.revision != base_revision or not state.previous_revision:
        raise NutritionError("Rollback no disponible o revisión cambió.",409)
    state.active_revision, state.previous_revision = state.previous_revision, state.active_revision
    state.revision += 1
    db.session.flush()
    return state


def status():
    return [{"source":s.id, "active":s.active_revision, "previous":s.previous_revision,
             "revision":s.revision, "license":s.license} for s in db.session.execute(db.select(SourceState)).scalars()]


def catalog_query():
    return db.select(CatalogFood).join(FoodCatalogRevision).join(SourceState).where(
        SourceState.active_revision==FoodCatalogRevision.revision)


def search(user_id, text="", limit=50, *, source=None, state=None, food_type=None, brand=None, barcode=None, offset=0):
    text = text.strip()[:100]
    tokens = [token for token in search_text(text).split()[:10] if token not in {'de', 'del', 'la', 'el', 'los', 'las'}]
    query = catalog_query()
    cooked_name = func.lower(CatalogFood.name).regexp_match(r'\b(?:baked|broiled|roasted|cooked|fried|boiled|grilled|stewed)\b')
    raw_name = func.lower(CatalogFood.name).regexp_match(r'\braw\b')
    from_raw = func.lower(CatalogFood.name).regexp_match(r'\bfrom raw\b')
    # FNDDS "baked ... from raw" names describe a cooked final preparation.
    # Refine this read-only search label, never the published identity/vector
    # or historical snapshot. Raw/cooked ambiguous source rows remain mixed.
    classified = or_(CatalogFood.preparation_state.is_(None),CatalogFood.preparation_state!='mixed')
    final_state = case((db.and_(raw_name,cooked_name,~from_raw),'mixed'),
                       (db.and_(cooked_name,classified),'cooked'),
                       (db.and_(raw_name,classified),'raw'),else_=CatalogFood.preparation_state)
    private = db.select(FoodProduct).where(FoodProduct.user_id == user_id, FoodProduct.is_active.is_(True))
    for token in tokens:
        alternatives = SEARCH_WORDS.get(token, (token,))
        words = r'\b(?:' + '|'.join(re.escape(word) for word in alternatives) + r')\b'
        if token in SEARCH_STATES:
            query = query.where(final_state == SEARCH_STATES[token])
        else:
            query = query.where(or_(CatalogFood.search_text.regexp_match(words), func.lower(CatalogFood.name).regexp_match(words)))
        private = private.where(or_(func.lower(FoodProduct.name).regexp_match(words),func.lower(FoodProduct.brand).regexp_match(words)))
    if set(tokens) & {'frijol','frijoles'}:
        # English green/snap beans are ejotes, not the mature-seed frijol.
        query=query.where(~func.lower(CatalogFood.name).regexp_match(
            r'\b(?:green|string|snap|wax)\s+beans?\b|\bbeans?,\s*(?:snap|string|wax|green)\b'))
    for column, value in [(FoodCatalogRevision.source_id, source), (final_state, state),
                          (CatalogFood.food_type, food_type), (CatalogFood.barcode, barcode)]:
        if value:
            query = query.where(column == value)
    if barcode:
        private = private.where(FoodProduct.nutrition_json['barcode'].as_string() == barcode)
    if brand:
        pattern='%'+brand[:200].replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        query=query.where(CatalogFood.brand.ilike(pattern,escape='\\'))
        private = private.where(FoodProduct.brand.ilike(pattern,escape='\\'))
    limit = max(1, min(int(limit), 100))
    offset = max(0, min(int(offset), 50000))
    starts = like_pattern(' '.join(tokens), prefix=True)
    ordered_prefix = '%'.join(like_pattern(token,prefix=True)[:-1] for token in tokens) + '%'
    ingredient_intent = bool(set(tokens) & {'arroz', 'rice', 'pollo', 'chicken', 'frijol', 'frijoles', 'beans', 'avena', 'oats', 'tortilla', 'tortillas'})
    compound_requested = bool(set(tokens) & {'con', 'with', 'and', 'mezcla', 'mix', 'totopos', 'chips', 'ensalada', 'sopa','refritos','refried'})
    compound = or_(*(func.lower(CatalogFood.name).like('%'+word+'%') for word in
        (' with ', ' and ', ' con ', 'mixture', 'mixed', 'blend', 'salad', 'pilaf', 'flavored',
         'sake', 'snack', 'chips', 'taco', 'burrito', 'soup', 'cookie', 'pan dulce', 'cake', 'dessert', 'babyfood',
         'bratwurst','sausage','frankfurter','breaded','battered','nugget','restaurant','cracker barrel','refried','volteados','atole',
         'baby toddler','infant')))
    compound = or_(compound,CatalogFood.food_type=='commercial')
    ranks = [case((CatalogFood.barcode == text, 0), else_=1),
             case((func.lower(CatalogFood.name) == text.casefold(), 0), else_=1)]
    if ingredient_intent and not compound_requested: ranks.append(case((compound, 1), else_=0))
    # A rice query asks for the grain unless a derivative is explicit. This
    # changes candidate order only: flour/pasta retain their own IDs and vectors.
    derivatives = {'harina','flour','pasta','pastas','fideo','fideos','noodle','noodles'}
    if set(tokens) & {'arroz','rice'} and not (set(tokens) & derivatives):
        derived = func.lower(CatalogFood.name).regexp_match(
            r'\b(?:flour|harina|pastas?|fideos?|noodles?)\b')
        ranks.append(case((derived, 1), else_=0))
    literal_nouns = [{'frijoles':'frijol','tortillas':'tortilla'}.get(token,token) for token in tokens
                     if token in {'arroz', 'pollo', 'pechuga', 'frijol', 'frijoles', 'avena', 'tortilla', 'tortillas'}]
    if literal_nouns:
        ranks.append(case((or_(*(CatalogFood.name.ilike(like_pattern(token), escape='\\') for token in literal_nouns)), 0), else_=1))
    ranks.append(case((or_(CatalogFood.search_text.like(starts, escape='\\'),
                           CatalogFood.search_text.like(ordered_prefix,escape='\\'),
                           CatalogFood.search_text.like(like_pattern(search_text(text),prefix=True),escape='\\')), 0), else_=1))
    rows = db.session.execute(query.order_by(*ranks, CatalogFood.name, CatalogFood.id).offset(offset).limit(limit)).scalars().all()
    products = [] if source or state or food_type else db.session.execute(private.order_by(FoodProduct.name, FoodProduct.id).offset(offset).limit(limit)).scalars().all()
    def visible_state(row):
        cooked=bool(re.search(r'\b(?:baked|broiled|roasted|cooked|fried|boiled|grilled|stewed)\b',row.name.casefold()))
        raw=bool(re.search(r'\braw\b',row.name.casefold()))
        if cooked and raw and not re.search(r'\bfrom raw\b',row.name.casefold()):return 'mixed'
        if row.preparation_state!='mixed' and cooked:return 'cooked'
        if row.preparation_state!='mixed' and raw:return 'raw'
        return row.preparation_state
    return [{'ref':'catalog:'+r.public_id, 'name':r.name, 'preparation':r.preparation, 'scope':'catalog',
             'source':r.snapshot_json['source'], 'source_food_id':r.source_food_id,
             'brand':r.brand, 'barcode':r.barcode, 'state':visible_state(r)} for r in rows] + [
        {'ref':'user:'+r.public_id, 'name':r.name, 'preparation':r.brand or 'Declarado por ti', 'scope':'user',
         'source':'user', 'source_food_id':r.public_id, 'brand':r.brand, 'barcode':(r.nutrition_json or {}).get('barcode'), 'state':None} for r in products]


def detail(user_id, ref, revision=None, preloaded=None):
    scope, _, key = str(ref).partition(":")
    if scope == "catalog":
        query = catalog_query() if revision is None else db.select(CatalogFood).join(FoodCatalogRevision).where(FoodCatalogRevision.state=='validated')
        row = preloaded.get(ref) if preloaded is not None else db.session.execute(query.where(CatalogFood.public_id==key)).scalar_one_or_none()
        if not row or (revision is not None and str(row.snapshot_json["revision"]) != str(revision)):
            raise NutritionError("Alimento o revisión no disponible.",404)
        return copy.deepcopy(row.snapshot_json) | {"ref":ref, "scope":"catalog",
            "catalog_revision":row.catalog_revision.revision,"catalog_sha256":row.catalog_revision.sha256}
    if scope == "user":
        row = preloaded.get(ref) if preloaded is not None else db.session.execute(db.select(FoodProduct).where(FoodProduct.public_id==key,
            FoodProduct.user_id==user_id, FoodProduct.is_active.is_(True))).scalar_one_or_none()
        if not row:
            raise NutritionError("Alimento no encontrado.",404)
        if revision is not None and str(row.revision) != str(revision):
            raise NutritionError("El alimento cambió; revisa de nuevo.",409)
        vector = {n:{"state":"known" if getattr(row,column) is not None else "unknown",
            "value":str(getattr(row,column)) if getattr(row,column) is not None else None,
            "unit":NUTRIENTS[n][1]} for n,column in PRODUCT.items()}
        extras = row.nutrition_json or {}
        vector.update(extras.get("nutrients", {}))
        servings = extras.get("servings", [])
        if row.serving_size_g:
            servings = [{"id":"legacy", "label":row.serving_label or "Porción", "amount":str(row.serving_size_g), "unit":"g"}] + servings
        return {"ref":ref, "scope":"user", "revision":str(row.revision), "source":"user",
            "source_food_id":row.public_id, "name":row.name, "preparation":row.brand or "Declarado por ti",
            "basis_amount":extras.get('basis_amount','100'), "basis_unit":extras.get('basis_unit','g'), "density_g_ml":extras.get("density_g_ml"),
            "nutrients":validate_vector(vector), "servings":servings,
            "provenance":extras.get('provenance',{"method":"user_declared", "verified_at":None}),
            **({'metadata':dict(extras.get('metadata') or {},brand=row.brand,barcode=extras.get('barcode'))} if extras.get('metadata') or row.brand or extras.get('barcode') else {})}
    raise NutritionError("Referencia no válida.",404)


def details(user_id, entries):
    """Two bounded queries for any number of selected foods, never N+1."""
    catalog_keys = [e['ref'][8:] for e in entries if e['ref'].startswith('catalog:')]
    personal_keys = [e['ref'][5:] for e in entries if e['ref'].startswith('user:')]
    query = db.select(CatalogFood).join(FoodCatalogRevision).where(FoodCatalogRevision.state=='validated') if any(e.get('revision') is not None for e in entries) else catalog_query()
    rows = db.session.execute(query.where(CatalogFood.public_id.in_(catalog_keys))).scalars().all() if catalog_keys else []
    products = db.session.execute(db.select(FoodProduct).where(FoodProduct.user_id==user_id,FoodProduct.is_active.is_(True),FoodProduct.public_id.in_(personal_keys))).scalars().all() if personal_keys else []
    loaded = {'catalog:'+r.public_id:r for r in rows} | {'user:'+r.public_id:r for r in products}
    return [detail(user_id,e['ref'],e.get('revision'),loaded) for e in entries]


def refresh_personal_vector(product, user_id, changes):
    """Preserve full Decimal precision and micros across explicit legacy edits."""
    if product.user_id != user_id:
        raise NutritionError('Alimento no encontrado.',404)
    if product.nutrition_json is None:
        return
    document=copy.deepcopy(product.nutrition_json)
    if document.get('basis_unit','g') != 'g' and any(column in changes and changes[column]!=getattr(product,column) for column in PRODUCT.values()):
        raise NutritionError('Este producto usa una base de volumen. Edita su declaración explícita; no hay densidad para convertir a 100 g.')
    vector=document.setdefault('nutrients',{})
    for nutrient,column in PRODUCT.items():
        if column in changes:
            raw=changes[column]
            if raw==getattr(product,column):continue
            if raw is not None:
                raw=Decimal(str(raw))*Decimal(document.get('basis_amount','100'))/100
            vector[nutrient]={'state':'known' if raw is not None else 'unknown',
                'value':str(raw) if raw is not None else None,'unit':NUTRIENTS[nutrient][1],
                'provenance':{'method':'user_declared'}}
    product.nutrition_json=document


def save_personal_definition(user_id,document):
    """Official full-basis edit, with owner lock and optimistic revision.

Historical snapshots never reference the mutable vector for recalculation.
Legacy fields are projected only from an explicit gram basis, never ml.
"""
    from app.services.nutrition_intelligence import lock_owner
    from app.services.mobile_health import create_food,patch_food
    lock_owner(user_id)
    vector=validate_vector(document['nutrients']);basis=decimal(document['basis_amount'],positive=True)
    if document['basis_unit'] not in {'g','ml'}:raise NutritionError('Base explícita inválida.')
    nutrition={'basis_amount':str(basis),'basis_unit':document['basis_unit'],'nutrients':vector,
        'density_g_ml':None,'servings':[],'barcode':document.get('barcode'),
        'metadata':{'net_content_text':document.get('net_content_text',''),'quality':'user_confirmed'}}
    if document.get('provenance'):nutrition['provenance']=copy.deepcopy(document['provenance'])
    projection={}
    for key,column in PRODUCT.items():
        value=vector.get(key,{})
        projected=Decimal(value['value'])*100/basis if document['basis_unit']=='g' and value.get('state')=='known' else None
        if projected is not None and projected>=Decimal('10000000'):raise NutritionError('El valor supera la capacidad legacy del alimento por 100 g.')
        projection[column]=projected
    product=db.session.execute(db.select(FoodProduct).where(FoodProduct.user_id==user_id,FoodProduct.public_id==document['public_id'])
        .with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if document.get('base_revision') is not None:
        if not product:raise NutritionError('Alimento no encontrado.',404)
        previous=product.nutrition_json or {}
        if previous.get('provenance'):nutrition.setdefault('provenance',copy.deepcopy(previous['provenance']))
        nutrition['metadata']=dict(previous.get('metadata') or {},
            net_content_text=document.get('net_content_text',(previous.get('metadata') or {}).get('net_content_text','')),quality='user_confirmed')
        nutrition['servings']=[s for s in previous.get('servings',[]) if s['unit']==document['basis_unit']]
        if previous.get('basis_unit','g')==document['basis_unit']:nutrition['density_g_ml']=previous.get('density_g_ml')
        if product.revision==document['base_revision']+1 and product.nutrition_json==nutrition and product.name==document['name'] and product.brand==document.get('brand'):
            return product
        if product.revision!=document['base_revision']:raise NutritionError('El producto cambió. Reabre su declaración actual.',409)
        product=patch_food(user_id,product.public_id,{'base_revision':product.revision,'name':document['name'],'brand':document.get('brand')})
    elif product:
        if product.nutrition_json!=nutrition or product.name!=document['name']:raise NutritionError('La identidad existente difiere.',409)
        return product
    else:product=create_food(user_id,{'public_id':document['public_id'],'name':document['name'],'brand':document.get('brand'),**projection})
    for column,value in projection.items():setattr(product,column,value)
    if document['basis_unit']=='ml':product.serving_size_g=None;product.serving_label=None
    product.nutrition_json=nutrition;db.session.flush();return product
