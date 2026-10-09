"""Administrative bounded local snapshots; everyday lookups never use Internet."""
import copy
import hashlib
import json
from decimal import Decimal
from sqlalchemy import or_
from app.extensions import db
from app.models import FoodProduct
from app.models.nutrition_intelligence import (FoodCatalogSource as SourceState,
    FoodCatalogRevision, CatalogFood, Nutrient, FoodNutrient, FoodServing)
from app.services.nutrition_math import NUTRIENTS, PRODUCT, NutritionError, decimal, validate_vector


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
    for food in document["foods"]:
        row = CatalogFood(catalog_revision_id=record.id, source_food_id=food["source_food_id"],
            name=food["name"], preparation=food["preparation"], snapshot_json=food)
        db.session.add(row)
        db.session.flush()
        for key, value in validate_vector(food["nutrients"]).items():
            db.session.add(FoodNutrient(food_id=row.id, nutrient_id=key, state=value["state"],
                value=Decimal(value["value"]) if value["value"] is not None else None,
                provenance_json=value))
        for serving in food.get("servings", []):
            db.session.add(FoodServing(food_id=row.id, source_serving_id=serving["id"],
                label=serving["label"], amount=Decimal(serving["amount"]), unit=serving["unit"]))
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


def search(user_id, text="", limit=50):
    text = text.strip()[:100]
    pattern = "%"+text.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%"
    rows = db.session.execute(catalog_query().where(CatalogFood.name.ilike(pattern,escape="\\"))
        .order_by(CatalogFood.name, CatalogFood.id).limit(min(limit,100))).scalars().all()
    products = db.session.execute(db.select(FoodProduct).where(FoodProduct.user_id==user_id,
        FoodProduct.is_active.is_(True), FoodProduct.name.ilike(pattern,escape="\\"))
        .order_by(FoodProduct.name).limit(min(limit,100))).scalars().all()
    return [{"ref":"catalog:"+r.public_id, "name":r.name, "preparation":r.preparation, "scope":"catalog"} for r in rows] + [
        {"ref":"user:"+r.public_id, "name":r.name, "preparation":r.brand or "Declarado por ti", "scope":"user"} for r in products]


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
            "basis_amount":"100", "basis_unit":"g", "density_g_ml":extras.get("density_g_ml"),
            "nutrients":validate_vector(vector), "servings":servings,
            "provenance":{"method":"user_declared", "verified_at":None}}
    raise NutritionError("Referencia no válida.",404)


def details(user_id, entries):
    """Two bounded queries for any number of selected foods, never N+1."""
    catalog_keys = [e['ref'][8:] for e in entries if e['ref'].startswith('catalog:')]
    personal_keys = [e['ref'][5:] for e in entries if e['ref'].startswith('user:')]
    rows = db.session.execute(catalog_query().where(CatalogFood.public_id.in_(catalog_keys))).scalars().all() if catalog_keys else []
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
    vector=document.setdefault('nutrients',{})
    for nutrient,column in PRODUCT.items():
        if column in changes:
            raw=changes[column]
            vector[nutrient]={'state':'known' if raw is not None else 'unknown',
                'value':str(raw) if raw is not None else None,'unit':NUTRIENTS[nutrient][1],
                'provenance':{'method':'user_declared'}}
    product.nutrition_json=document
