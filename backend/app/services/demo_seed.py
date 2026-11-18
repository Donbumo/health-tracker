"""Explicit local DEMO history, atomic and owner-scoped via official services."""
import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from flask import current_app
from sqlalchemy import func, or_

from app.extensions import db
from app.models import DailyNutrition, FoodProduct, NutritionItem, Recipe, TrainingPlan, TrainingSession, User, WeighIn
from app.services import food_catalog, gym_programs, gym_sessions
from app.services import nutrition_intelligence as nutrition
from app.services.demo_fixtures import (
    DEMO_EMAIL, DEMO_NAME, DEMO_SOURCE, DEMO_NOTE, DEMO_PUBLIC_ID, DEMO_PLAN_NAME,
    FOODS, MENUS, MOVEMENTS, DAY_MOVEMENTS, EXTERNAL_MOVEMENTS, identity, variation, performance,
    DEMO_BODY_SOURCE, DEMO_BODY_NOTE, body_document,
)
from app.services.energy_days import upsert_document, view as energy_view
from app.services.importers.routine_draft import RoutineImportDraft
from app.services.nutrition_math import NUTRIENTS, ingredient
from app.services.training_plans import get_active_version


class DemoSeedError(ValueError):
    pass


def _authorize(confirmed, production=False, body_only=False):
    if not confirmed or current_app.config.get("DEMO_SEED_ENABLED") is not True:
        raise DemoSeedError("Requiere DEMO_SEED_ENABLED=true y confirmación explícita del entorno.")
    environment = current_app.config.get("DEMO_SEED_ENVIRONMENT", "")
    if production and environment != "production":
        raise DemoSeedError("--confirm-production requiere DEMO_SEED_ENVIRONMENT=production.")
    if not (production and environment == "production") and (environment not in {"local", "test"} or (environment == "test" and not current_app.testing)):
        raise DemoSeedError("DEMO_SEED_ENVIRONMENT debe ser local (o test bajo TESTING).")
    labels = [current_app.config.get(k, "") for k in ("ENV", "APP_ENV", "FLASK_ENV")]
    labels += [os.environ.get(k, "") for k in ("APP_ENV", "FLASK_ENV")]
    if not production and any(str(label).lower() in {"production", "prod"} for label in labels):
        raise DemoSeedError("Generación DEMO prohibida en producción.")
    if db.engine.url.host not in {None, "localhost", "127.0.0.1", "::1", "db"}:
        raise DemoSeedError("La base DEMO debe ser local; no se permiten hosts remotos.")
    if not body_only and not current_app.config.get("NUTRITION_INTELLIGENCE_ENABLED"):
        raise DemoSeedError("Requiere NUTRITION_INTELLIGENCE_ENABLED=true.")
    password = os.environ.get("DEMO_USER_PASSWORD", "")
    if len(password) < 12:
        raise DemoSeedError("DEMO_USER_PASSWORD debe contener al menos 12 caracteres.")
    return password


def _account(password, created, *, existing_only=False):
    accounts = db.session.scalars(db.select(User).where(or_(
        func.lower(User.email) == DEMO_EMAIL, func.lower(User.username) == DEMO_EMAIL,
        User.public_id == DEMO_PUBLIC_ID,
    )).with_for_update()).all()
    if accounts:
        if len(accounts) != 1:
            raise DemoSeedError("La identidad DEMO está en conflicto; no se modificó la cuenta.")
        user = accounts[0]
        if (user.public_id, user.username, user.email, user.role, user.display_name) != (
            DEMO_PUBLIC_ID, DEMO_EMAIL, DEMO_EMAIL, "user", DEMO_NAME
        ):
            raise DemoSeedError("La cuenta existente no está identificada como DEMO de este generador.")
        if not user.check_password(password):
            raise DemoSeedError("La contraseña suministrada no coincide; usa la administración para cambiarla.")
        return user
    if existing_only:
        raise DemoSeedError("--body-only requiere la cuenta DEMO existente; no creará otra cuenta.")
    user = User(public_id=DEMO_PUBLIC_ID, username=DEMO_EMAIL, email=DEMO_EMAIL,
                display_name=DEMO_NAME, role="user", timezone=current_app.config["APP_TIMEZONE"])
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    created["users"] += 1
    return user


def _food_refs(user, created):
    from app.models.nutrition_intelligence import CatalogFood, FoodCatalogRevision
    refs = {}
    for key, (source_id, name, protein, carbs, fat, fiber) in FOODS.items():
        row = db.session.scalar(food_catalog.catalog_query().where(
            FoodCatalogRevision.source_id == "usda_sr_legacy", CatalogFood.source_food_id == source_id))
        if row:
            refs[key] = "catalog:" + row.public_id
            continue
        public_id = identity("food/" + key)
        existing = db.session.scalar(db.select(FoodProduct).where(FoodProduct.user_id == user.id, FoodProduct.public_id == public_id))
        values = {"protein": Decimal(str(protein)), "carbohydrate_total": Decimal(str(carbs)),
                  "fat": Decimal(str(fat)), "fiber": Decimal(str(fiber))}
        values["net_carbs"] = values["carbohydrate_total"] - values["fiber"]
        values["energy"] = 4 * (values["protein"] + values["carbohydrate_total"]) + 9 * values["fat"]
        vector = {k: {"state": "known", "value": str(v), "unit": NUTRIENTS[k][1]} for k, v in values.items()}
        product = food_catalog.save_personal_definition(user.id, {
            "public_id": public_id, "name": "DEMO · " + name, "brand": "DEMO sintético",
            "basis_amount": "100", "basis_unit": "g", "nutrients": vector,
            "provenance": {"method": DEMO_SOURCE, "note": DEMO_NOTE},
        })
        product.source, product.notes = DEMO_SOURCE, DEMO_NOTE
        refs[key] = "user:" + product.public_id
        created["foods"] += int(existing is None)
    return refs


def _recipes(user, created):
    recipes, refs = {}, None
    for menu in MENUS:
        for kind, name, foods in menu:
            label = "DEMO · " + name
            recipe = db.session.scalar(db.select(Recipe).where(Recipe.user_id == user.id, Recipe.name == label))
            if recipe is None:
                if refs is None:
                    refs = _food_refs(user, created)
                draft = nutrition.create_draft(user.id, target="2020-01-01", name=label, meal_type=kind,
                    entries=[{"ref": refs[key], "amount": str(amount), "unit": "g"} for key, amount in foods])
                draft.accepted_json = list(range(len(foods)))
                recipe = nutrition.save_template(user.id, draft.public_id, draft.revision)
                recipe.notes = DEMO_NOTE
                created["recipes"] += 1
            elif recipe.notes != DEMO_NOTE or not recipe.nutrition_snapshot_json:
                raise DemoSeedError("Una receta DEMO coincide con contenido ajeno al generador.")
            recipes[name] = recipe
    return recipes


def _plan(user, start, created, *, existing_only=False):
    plans = db.session.scalars(db.select(TrainingPlan).where(
        TrainingPlan.user_id == user.id, TrainingPlan.name == DEMO_PLAN_NAME)).all()
    if plans:
        if len(plans) != 1 or plans[0].deleted_at:
            raise DemoSeedError("La rutina DEMO fue eliminada o es ambigua; no se recreará silenciosamente.")
        plan = plans[0]
        version = get_active_version(plan, user.id)
        try:
            marker, anchor = version.content["data"].get("description", "").split(" | ")
            if marker != DEMO_NOTE:
                raise ValueError()
            start = date.fromisoformat(anchor)
        except ValueError as error:
            raise DemoSeedError("La rutina existente carece de procedencia DEMO verificable.") from error
        return plan, version, start
    if existing_only:
        raise DemoSeedError("--body-only requiere la rutina DEMO que identifica el inicio histórico.")
    draft = RoutineImportDraft({"name": DEMO_PLAN_NAME, "description": DEMO_NOTE + " | " + start.isoformat()}, [
        {"name": "Full Body " + chr(65 + index), "exercises": [
            {"raw_name": MOVEMENTS[m][0], "create_new": True, "sets": [
                {"set_number": s, "reps_min": 8, "reps_max": 12, "rir": 2, "rest_seconds": 120 if m < 3 else 90}
                for s in range(1, 4)]} for m in movements]}
        for index, movements in enumerate(DAY_MOVEMENTS)])
    from app.services.exercise_catalog import external_catalog
    references = {row.external_id: row for row in external_catalog() if row.source == "free-exercise-db"}
    for day, movements in zip(draft.days, DAY_MOVEMENTS, strict=True):
        for exercise, movement in zip(day["exercises"], movements, strict=True):
            reference = references.get(EXTERNAL_MOVEMENTS[movement])
            if reference:
                exercise.update(raw_name=reference.name, resolved_catalog_id=reference.public_id, create_new=False)
    gym_programs.resolve_draft(draft, user.id)
    plan, _ = gym_programs.confirm_program(draft, user.id, gym_programs.preview_token(draft, user.id))
    created["training_plans"] += 1
    return plan, get_active_version(plan, user.id), start


def _nutrition_day(user, day, recipes, created):
    existing = db.session.scalar(db.select(DailyNutrition).where(DailyNutrition.user_id == user.id, DailyNutrition.date == day))
    if existing:
        if existing.source != DEMO_SOURCE or existing.notes != DEMO_NOTE:
            raise DemoSeedError("Ya existe un día nutricional ajeno al generador; se canceló el lote.")
        return existing
    menu = MENUS[variation(day, "menu", len(MENUS))]
    factor = Decimal(92 + variation(day, "portions", 17)) / 100
    # Split or combine existing ingredients: never count a dish and its parts.
    count = 3 + variation(day, "meals", 3)
    selections = [(kind, name, list(recipes[name].nutrition_snapshot_json["ingredients"])) for kind, name, _ in menu]
    if count == 3:
        selections[0][2].extend(selections.pop()[2])
    elif count == 5:
        kind, name, ingredients = selections.pop()
        selections.extend([(kind, name, ingredients[:1]), (kind, "Fruta / colación", ingredients[1:])])
    for kind, name, ingredients in selections:
        draft = nutrition.create_draft(user.id, target=day.isoformat(), name="DEMO · " + name, meal_type=kind)
        entries = [ingredient(e["food"], str((Decimal(e["amount"]) * factor).quantize(Decimal(".01"))), e["unit"], e.get("serving_id")) for e in ingredients]
        draft.snapshot_json = nutrition.make_snapshot(entries, "DEMO · " + name, day.isoformat(), kind, user.timezone)
        if count == 4:
            recipe = recipes[name]
            draft.snapshot_json = dict(draft.snapshot_json, recipe_id=recipe.id, recipe_revision=recipe.revision)
        draft.accepted_json = list(range(len(entries)))
        log, _ = nutrition.confirm(user.id, nutrition.confirmation_token(draft))
        item = db.session.scalar(db.select(NutritionItem).where(NutritionItem.user_id == user.id, NutritionItem.id == log.projection_item_id))
        item.source, item.notes = DEMO_SOURCE, DEMO_NOTE
        created["meals"] += 1
    record = db.session.scalar(db.select(DailyNutrition).where(DailyNutrition.user_id == user.id, DailyNutrition.date == day))
    record.source, record.notes = DEMO_SOURCE, DEMO_NOTE
    created["nutrition_days"] += 1
    return record


def _energy_day(user, day, food, created):
    existing = energy_view(user.id, day)
    if existing:
        if len(existing.evidence) != 1 or existing.evidence[0].source != DEMO_SOURCE:
            raise DemoSeedError("Ya existe energía ajena al generador; se canceló el lote.")
        return
    training = day.weekday() in {0, 2, 4}
    delta = (-160, -30, 0, 90, 150, 240, 320)[variation(day, "balance", 7)]
    total = max(Decimal(2250), min(Decimal(3000), food.calories + delta + (70 if training else 0)))
    resting = Decimal(1690 + variation(day, "resting", 61))
    upsert_document({"schema_version": "1.0", "record_type": "daily_energy", "user_id": user.id, "source_type": "manual_generated",
        "data": {"date": day.isoformat(), "source": DEMO_SOURCE, "notes": DEMO_NOTE,
                 "total_expenditure_kcal": float(total), "resting_expenditure_kcal": float(resting),
                 "active_expenditure_kcal": float(total - resting),
                 "steps": (8500 if training else 5500) + variation(day, "steps", 3000)}}, user.id)
    created["energy_days"] += 1


def _session(user, plan, version, day, anchor, created):
    if day.weekday() not in {0, 2, 4}:
        return
    submission = identity("session/" + day.isoformat())
    existing = db.session.scalar(db.select(TrainingSession).where(TrainingSession.user_id == user.id, TrainingSession.client_submission_id == submission))
    if existing:
        if existing.notes != DEMO_NOTE or existing.deleted_at or existing.status != "completed":
            raise DemoSeedError("Una sesión DEMO fue modificada; no se sobrescribirá.")
        return
    day_number = {0: 1, 2: 2, 4: 3}[day.weekday()]
    started = datetime.combine(day, time(18), ZoneInfo(user.timezone)).astimezone(timezone.utc)
    duration = 3300 + variation(day, "duration", 901)
    record = gym_sessions.start_session(user.id, plan.public_id, version.public_id, 1, day_number, submission, performed_at=started)
    if record.client_submission_id != submission:
        raise DemoSeedError("Hay una sesión en curso ajena a este día DEMO; se canceló el lote.")
    record.notes = DEMO_NOTE
    for order, movement in enumerate(DAY_MOVEMENTS[day_number - 1], 1):
        for number in range(1, 4):
            gym_sessions.complete_set(user.id, record.public_id, order, number, performance(day, anchor, movement, number))
            created["training_sets"] += 1
    gym_sessions.finish_session(user.id, record.public_id, "completed", completed_at=started + timedelta(seconds=duration))
    created["training_sessions"] += 1


def _body_history(user, anchor, as_of, created):
    from app.services.importers.weigh_in import persist_weigh_in_document
    from app.services.validation import validate_json_document
    zone = ZoneInfo(user.timezone or current_app.config["APP_TIMEZONE"])
    start_at = datetime.combine(anchor, time.min, zone).astimezone(timezone.utc)
    end_at = datetime.combine(as_of + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    rows = db.session.scalars(db.select(WeighIn).where(
        WeighIn.user_id == user.id, WeighIn.recorded_at >= start_at, WeighIn.recorded_at < end_at
    ).with_for_update()).all()
    by_day = {}
    for row in rows:
        timestamp = row.recorded_at.replace(tzinfo=timezone.utc) if row.recorded_at.tzinfo is None else row.recorded_at
        local_day = timestamp.astimezone(zone).date()
        if local_day in by_day:
            raise DemoSeedError("Hay varios pesajes en un día DEMO; no se modificó el lote.")
        by_day[local_day] = row
    missing = (as_of - anchor).days + 1 - len(by_day)
    if missing > 366:
        raise DemoSeedError("Completa los pesajes DEMO en intervalos pendientes de hasta 366 días.")
    for offset in range((as_of - anchor).days + 1):
        day = anchor + timedelta(days=offset)
        document = body_document(user.id, day, anchor, zone.key)
        validate_json_document(document, "weigh_in")
        public_id = identity("weigh-in/" + day.isoformat())
        existing = by_day.get(day)
        if existing:
            timestamp = existing.recorded_at.replace(tzinfo=timezone.utc) if existing.recorded_at.tzinfo is None else existing.recorded_at
            if (timestamp != datetime.fromisoformat(document["data"]["recorded_at"]) or
                    existing.public_id != public_id or existing.client_event_id != public_id or
                    existing.source != DEMO_BODY_SOURCE or existing.notes != DEMO_BODY_NOTE or
                    existing.raw_payload_json != document or existing.revision != 1):
                raise DemoSeedError("Un pesaje del día es manual o fue modificado; no se sobrescribirá.")
            # Also detect direct edits that retained the original JSON/markers.
            from app.services.exporters.weigh_in import build_weigh_in_document
            exported = build_weigh_in_document(existing, user.id)
            exported["source_type"] = document["source_type"]
            expected = dict(document, data=dict(document["data"], recorded_at=exported["data"]["recorded_at"]))
            if exported != expected:
                raise DemoSeedError("Los valores del pesaje DEMO cambiaron; no se sobrescribirán.")
            continue
        record, duplicate = persist_weigh_in_document(document, user.id, public_id=public_id, client_event_id=public_id)
        if duplicate:
            raise DemoSeedError("Conflicto de identidad del pesaje; se canceló el lote.")
        created["weigh_ins"] += 1
        created["body_measurements"] += int(record.body_fat_percentage is not None)


def seed_demo_data(*, as_of=None, confirmed=False, production=False, body_only=False):
    """Append missing days atomically; never reset or rewrite existing history."""
    password = _authorize(confirmed, production, body_only)
    today = datetime.now(ZoneInfo(current_app.config["APP_TIMEZONE"])).date()
    as_of = as_of or today
    if not isinstance(as_of, date) or not date(2020, 2, 1) <= as_of <= today:
        raise DemoSeedError("--as-of debe estar entre 2020-02-01 y la fecha local actual.")
    start = (as_of.replace(day=1) - timedelta(days=1)).replace(day=1)
    created = dict.fromkeys(("users", "foods", "recipes", "nutrition_days", "meals", "energy_days", "training_plans", "training_sessions", "training_sets", "weigh_ins", "body_measurements"), 0)
    try:
        user = _account(password, created, existing_only=body_only)
        plan, version, anchor = _plan(user, start, created, existing_only=body_only)
        if body_only:
            _body_history(user, anchor, as_of, created)
            db.session.commit()
            return user, created
        last_nutrition = db.session.scalar(db.select(db.func.max(DailyNutrition.date)).where(
            DailyNutrition.user_id == user.id, DailyNutrition.source == DEMO_SOURCE))
        from app.models import DailyEnergy
        last_energy = db.session.scalar(db.select(db.func.max(DailyEnergy.date)).where(
            DailyEnergy.user_id == user.id, DailyEnergy.source == DEMO_SOURCE))
        last = min(last_nutrition, last_energy) if last_nutrition and last_energy else None
        start = min(start, last + timedelta(days=1) if last else anchor)
        if (as_of - start).days > 366:
            raise DemoSeedError("Actualiza la DEMO en intervalos de hasta 366 días.")
        recipes = _recipes(user, created)
        for offset in range((as_of - start).days + 1):
            day = start + timedelta(days=offset)
            food = _nutrition_day(user, day, recipes, created)
            _energy_day(user, day, food, created)
            _session(user, plan, version, day, anchor, created)
        # Independent backfill: never inherit the nutrition/energy cursor.
        _body_history(user, anchor, as_of, created)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return user, created
