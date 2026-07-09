"""Confirmed, transactional import of already-standard JSON documents.

This service starts after Phase 5B. Detection, mapping, standard generation,
and validation remain read-only; this module only persists documents after an
explicit confirmation from the authenticated user.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from typing import Any

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.extensions import db
from app.models import (
    DailyEnergy,
    DailyNutrition,
    FoodProduct,
    MedicalLabReport,
    MedicalLabResult,
    NutritionItem,
    NutritionMeal,
    Recipe,
    RecipeIngredient,
    TrainingPlan,
    TrainingPlanVersion,
    TrainingSession,
    TrainingSessionExercise,
    TrainingSet,
    WeighIn,
)
from app.services.importers.assisted_import_service import AssistedImportService
from app.services.training_plans import serialize_training_plan
from app.services.validation import JsonSchemaValidationError, validate_json_document


class StandardImportError(ValueError):
    pass


class StandardImportTokenError(StandardImportError):
    pass


CONFIRMATION_TOKEN_SALT = "standard-import-confirmation-v1"
DEFAULT_CONFIRMATION_MAX_AGE_SECONDS = 15 * 60


TARGET_SCHEMAS = {
    "weigh_in_batch": "weigh_in",
    "weigh_in": "weigh_in",
    "food_products": "food_product",
    "food_product": "food_product",
    "daily_energy": "daily_energy",
    "daily_nutrition": "daily_nutrition",
    "completed_workout": "completed_workout",
    "medical_lab": "medical_lab",
    "training_plan": "training_plan",
    "recipe": "recipe",
    "recipe_bundle": "recipe_bundle",
}

EXPECTED_SECTIONS = (
    "insert",
    "update",
    "skip",
    "conflict",
    "invalid",
)


@dataclass(frozen=True)
class PlannedOperation:
    operation: str
    target_type: str
    document_index: int
    label: str
    model: str | None = None
    existing_id: int | None = None
    recipe_index: int | None = None
    errors: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "target_type": self.target_type,
            "document_index": self.document_index,
            "label": self.label,
            "model": self.model,
            "existing_id": self.existing_id,
            "recipe_index": self.recipe_index,
            "errors": list(self.errors),
        }


class StandardImportExecutor:
    """Plan and commit standard JSON documents for the authenticated user."""

    def __init__(self, assisted_import_service: AssistedImportService | None = None) -> None:
        self.assisted_import_service = assisted_import_service or AssistedImportService()

    def preview_payload(
        self,
        payload: dict[str, Any],
        *,
        user_id: int,
        requested_type: str | None = None,
        target_type: str | None = None,
        source_type: str = "uploaded",
        candidate_index: int = 0,
    ) -> dict[str, Any]:
        preview = self.assisted_import_service.preview(
            payload,
            user_id=user_id,
            requested_type=requested_type,
            target_type=target_type,
            source_type=source_type,
            candidate_index=candidate_index,
            generate_standard_json=True,
        )
        documents, resolved_target = self._documents_from_preview(preview, payload)
        plan = self.plan_documents(
            documents,
            user_id=user_id,
            target_type=resolved_target,
        )
        return {
            "preview": preview,
            "target_type": resolved_target,
            "documents": documents,
            "plan": plan,
            "read_only": True,
        }

    def build_confirmation_token(
        self,
        *,
        user_id: int,
        target_type: str,
        payload: dict[str, Any],
        plan: dict[str, Any],
    ) -> str:
        return _serializer().dumps(
            {
                "user_id": user_id,
                "target_type": target_type,
                "payload_sha256": canonical_sha256(payload),
                "plan_sha256": canonical_sha256(_plan_fingerprint(plan)),
            },
            salt=CONFIRMATION_TOKEN_SALT,
        )

    def verify_confirmation_token(
        self,
        token: str,
        *,
        user_id: int,
        target_type: str,
        payload: dict[str, Any],
        plan: dict[str, Any],
        max_age: int = DEFAULT_CONFIRMATION_MAX_AGE_SECONDS,
    ) -> None:
        try:
            data = _serializer().loads(
                token,
                salt=CONFIRMATION_TOKEN_SALT,
                max_age=max_age,
            )
        except SignatureExpired as error:
            raise StandardImportTokenError("Import confirmation token expired") from error
        except BadSignature as error:
            raise StandardImportTokenError("Import confirmation token is invalid") from error

        expected = {
            "user_id": user_id,
            "target_type": target_type,
            "payload_sha256": canonical_sha256(payload),
            "plan_sha256": canonical_sha256(_plan_fingerprint(plan)),
        }
        for key, value in expected.items():
            if data.get(key) != value:
                raise StandardImportTokenError(
                    "Import preview changed; review the new plan and confirm again"
                )

    def plan_documents(
        self,
        documents: list[dict[str, Any]],
        *,
        user_id: int,
        target_type: str,
    ) -> dict[str, Any]:
        if not target_type or target_type not in TARGET_SCHEMAS:
            raise StandardImportError("Unsupported or empty import target")
        if not documents:
            raise StandardImportError("No standard documents were generated for import")

        if target_type == "recipe_bundle":
            operations = self._plan_recipe_bundle_documents(
                documents,
                user_id=user_id,
                target_type=target_type,
            )
        else:
            operations = [
                self._plan_document(
                    document,
                    user_id=user_id,
                    target_type=target_type,
                    index=index,
                )
                for index, document in enumerate(documents)
            ]
        return self._summary(operations, committed=False, rollback=False)

    def commit_documents(
        self,
        documents: list[dict[str, Any]],
        *,
        user_id: int,
        target_type: str,
        confirmed: bool,
    ) -> dict[str, Any]:
        if not confirmed:
            raise StandardImportError("Import confirmation is required")

        plan = self.plan_documents(documents, user_id=user_id, target_type=target_type)
        blocking = [
            item for item in plan["operations"]
            if item["operation"] in {"invalid", "conflict"}
        ]
        if blocking:
            return {
                **plan,
                "committed": False,
                "rollback": False,
                "errors": ["Import contains invalid or conflicting documents."],
            }

        committed_operations: list[PlannedOperation] = []
        try:
            for operation in plan["operations"]:
                planned = PlannedOperation(
                    operation=operation["operation"],
                    target_type=operation["target_type"],
                    document_index=operation["document_index"],
                    label=operation["label"],
                    model=operation["model"],
                    existing_id=operation["existing_id"],
                    recipe_index=operation.get("recipe_index"),
                    errors=tuple(operation["errors"]),
                )
                if planned.operation == "skip":
                    committed_operations.append(planned)
                    continue
                document = self._operation_document(documents, planned)
                record = self._apply_document(
                    document,
                    user_id=user_id,
                    target_type=planned.target_type,
                    operation=planned.operation,
                    existing_id=planned.existing_id,
                )
                db.session.flush()
                committed_operations.append(
                    PlannedOperation(
                        operation=planned.operation,
                        target_type=planned.target_type,
                        document_index=planned.document_index,
                        label=planned.label,
                        model=planned.model,
                        existing_id=getattr(record, "id", planned.existing_id),
                        recipe_index=planned.recipe_index,
                    )
                )
            db.session.commit()
        except Exception as error:
            db.session.rollback()
            return {
                **self._summary(plan["operations"], committed=False, rollback=True),
                "errors": [str(error) or error.__class__.__name__],
            }

        return self._summary(committed_operations, committed=True, rollback=False)

    def _documents_from_preview(
        self,
        preview: dict[str, Any],
        payload: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str]:
        if preview["mode"] == "standard_ready":
            target_type = preview["target_type"]
            return [payload], target_type

        generation = preview.get("standard_generation") or {}
        documents = generation.get("generated_documents") or []
        target_type = preview.get("target_type") or generation.get("target_type")
        return documents, target_type

    def _plan_document(
        self,
        document: dict[str, Any],
        *,
        user_id: int,
        target_type: str,
        index: int,
    ) -> PlannedOperation:
        schema_name = TARGET_SCHEMAS.get(target_type)
        if schema_name is None:
            return PlannedOperation("invalid", target_type, index, "Unsupported target")

        try:
            validate_json_document(document, schema_name)
            self._validate_document_owner(document, user_id=user_id, schema_name=schema_name)
        except (JsonSchemaValidationError, StandardImportError) as error:
            errors = getattr(error, "errors", None) or [str(error)]
            return PlannedOperation(
                "invalid",
            target_type,
            index,
            self._document_label(document, schema_name),
            errors=tuple(errors),
        )

        try:
            existing = self._find_existing(document, user_id=user_id, target_type=target_type)
        except StandardImportError as error:
            return PlannedOperation(
                "conflict",
                target_type,
                index,
                self._document_label(document, schema_name),
                errors=(str(error),),
            )

        label = self._document_label(document, schema_name)
        model = self._model_name(target_type)
        if existing is None:
            return PlannedOperation("insert", target_type, index, label, model=model)

        if self._is_same_payload(existing, document):
            return PlannedOperation(
                "skip",
                target_type,
                index,
                label,
                model=model,
                existing_id=existing.id,
            )

        if target_type == "completed_workout":
            return PlannedOperation(
                "conflict",
                target_type,
                index,
                label,
                model=model,
                existing_id=existing.id,
                errors=("Completed workout updates are not supported safely yet.",),
            )

        return PlannedOperation(
            "update",
            target_type,
            index,
            label,
            model=model,
            existing_id=existing.id,
        )

    def _plan_recipe_bundle_documents(
        self,
        documents: list[dict[str, Any]],
        *,
        user_id: int,
        target_type: str,
    ) -> list[PlannedOperation]:
        operations: list[PlannedOperation] = []
        for index, document in enumerate(documents):
            try:
                validate_json_document(document, "recipe_bundle")
                self._validate_document_owner(
                    document,
                    user_id=user_id,
                    schema_name="recipe_bundle",
                )
            except (JsonSchemaValidationError, StandardImportError) as error:
                errors = getattr(error, "errors", None) or [str(error)]
                operations.append(
                    PlannedOperation(
                        "invalid",
                        target_type,
                        index,
                        self._document_label(document, "recipe_bundle"),
                        errors=tuple(errors),
                    )
                )
                continue

            recipes = document.get("recipes") or []
            if not recipes:
                operations.append(
                    PlannedOperation(
                        "invalid",
                        target_type,
                        index,
                        "recipe_bundle",
                        errors=("Recipe bundle must contain at least one recipe.",),
                    )
                )
                continue

            for recipe_index, recipe_document in enumerate(recipes):
                operation = self._plan_document(
                    recipe_document,
                    user_id=user_id,
                    target_type="recipe",
                    index=index,
                )
                operations.append(
                    PlannedOperation(
                        operation=operation.operation,
                        target_type=target_type,
                        document_index=index,
                        label=operation.label,
                        model="Recipe",
                        existing_id=operation.existing_id,
                        recipe_index=recipe_index,
                        errors=operation.errors,
                    )
                )

        return operations

    @staticmethod
    def _operation_document(
        documents: list[dict[str, Any]],
        operation: PlannedOperation,
    ) -> dict[str, Any]:
        document = documents[operation.document_index]
        if operation.target_type == "recipe_bundle":
            if operation.recipe_index is None:
                raise StandardImportError("Recipe bundle operation is missing recipe_index")
            return document["recipes"][operation.recipe_index]
        return document

    def _validate_document_owner(
        self,
        document: dict[str, Any],
        *,
        user_id: int,
        schema_name: str,
    ) -> None:
        document_user_id = document.get("user_id")
        if document_user_id is not None and document_user_id != user_id:
            raise StandardImportError("Document user_id does not match authenticated user")
        if schema_name not in {"recipe", "recipe_bundle"} and document_user_id is None:
            raise StandardImportError("Document is missing user_id")

    def _find_existing(
        self,
        document: dict[str, Any],
        *,
        user_id: int,
        target_type: str,
    ) -> Any | None:
        if target_type in {"weigh_in", "weigh_in_batch"}:
            data = document["data"]
            recorded_at = datetime.fromisoformat(data["recorded_at"].replace("Z", "+00:00"))
            source = data.get("source", document["source_type"]).strip()
            return db.session.execute(
                db.select(WeighIn).where(
                    WeighIn.user_id == user_id,
                    WeighIn.recorded_at == recorded_at,
                    WeighIn.source == source,
                )
            ).scalar_one_or_none()

        if target_type == "daily_energy":
            record_date = date.fromisoformat(document["data"]["date"])
            return db.session.execute(
                db.select(DailyEnergy).where(
                    DailyEnergy.user_id == user_id,
                    DailyEnergy.date == record_date,
                )
            ).scalar_one_or_none()

        if target_type == "daily_nutrition":
            record_date = date.fromisoformat(document["data"]["date"])
            return db.session.execute(
                db.select(DailyNutrition).where(
                    DailyNutrition.user_id == user_id,
                    DailyNutrition.date == record_date,
                )
            ).scalar_one_or_none()

        if target_type in {"food_product", "food_products"}:
            name = document["name"].strip()
            brand = document.get("brand")
            brand = brand.strip() if brand else None
            query = db.select(FoodProduct).where(
                FoodProduct.user_id == user_id,
                FoodProduct.name == name,
            )
            query = query.where(FoodProduct.brand.is_(None) if brand is None else FoodProduct.brand == brand)
            return db.session.execute(query).scalar_one_or_none()

        if target_type == "recipe":
            return self._recipe_by_name(user_id, document["name"])

        if target_type == "recipe_bundle":
            return None

        if target_type == "training_plan":
            name = document["data"]["name"].strip()
            return db.session.execute(
                db.select(TrainingPlan).where(
                    TrainingPlan.user_id == user_id,
                    TrainingPlan.name == name,
                )
            ).scalar_one_or_none()

        if target_type == "completed_workout":
            data = document["data"]
            performed_at = datetime.fromisoformat(data["performed_at"].replace("Z", "+00:00"))
            return db.session.execute(
                db.select(TrainingSession).where(
                    TrainingSession.user_id == user_id,
                    TrainingSession.training_plan_version_id == data["training_plan_version_id"],
                    TrainingSession.performed_at == performed_at,
                )
            ).scalar_one_or_none()

        if target_type == "medical_lab":
            laboratory_name = document.get("laboratory_name")
            laboratory_name = laboratory_name.strip() if laboratory_name else None
            report_date = date.fromisoformat(document["date"])
            query = db.select(MedicalLabReport).where(
                MedicalLabReport.user_id == user_id,
                MedicalLabReport.date == report_date,
            )
            query = query.where(
                MedicalLabReport.laboratory_name.is_(None)
                if laboratory_name is None
                else MedicalLabReport.laboratory_name == laboratory_name
            )
            return db.session.execute(query).scalar_one_or_none()

        return None

    @staticmethod
    def _is_same_payload(existing: Any, document: dict[str, Any]) -> bool:
        if hasattr(existing, "raw_payload_json") and existing.raw_payload_json is not None:
            return existing.raw_payload_json == document
        if isinstance(existing, TrainingPlan):
            serialized = serialize_training_plan(document)
            sha256 = hashlib.sha256(serialized).hexdigest()
            return any(version.sha256 == sha256 for version in existing.versions)
        return False

    def _apply_document(
        self,
        document: dict[str, Any],
        *,
        user_id: int,
        target_type: str,
        operation: str,
        existing_id: int | None,
    ) -> Any:
        if target_type in {"weigh_in", "weigh_in_batch"}:
            return self._apply_weigh_in(document, user_id, existing_id)
        if target_type == "daily_energy":
            return self._apply_daily_energy(document, user_id, existing_id)
        if target_type == "daily_nutrition":
            return self._apply_daily_nutrition(document, user_id, existing_id)
        if target_type in {"food_product", "food_products"}:
            return self._apply_food_product(document, user_id, existing_id)
        if target_type == "recipe":
            return self._apply_recipe(document, user_id, existing_id)
        if target_type == "recipe_bundle":
            return self._apply_recipe(document, user_id, existing_id)
        if target_type == "training_plan":
            return self._apply_training_plan(document, user_id, existing_id, operation)
        if target_type == "completed_workout":
            return self._apply_completed_workout(document, user_id)
        if target_type == "medical_lab":
            return self._apply_medical_lab(document, user_id, existing_id)
        raise StandardImportError("Unsupported target")

    def _apply_weigh_in(self, document: dict[str, Any], user_id: int, existing_id: int | None) -> WeighIn:
        data = document["data"]
        record = db.session.get(WeighIn, existing_id) if existing_id else WeighIn(user_id=user_id)
        if record is None or record.user_id != user_id:
            raise StandardImportError("Weigh-in target does not belong to this user")
        record.recorded_at = datetime.fromisoformat(data["recorded_at"].replace("Z", "+00:00"))
        if "weight_kg" in data:
            record.weight_kg = _decimal(data.get("weight_kg"))
        if "body_fat_percent" in data:
            record.body_fat_percentage = _decimal(data.get("body_fat_percent"))
        if "muscle_mass_kg" in data:
            record.muscle_mass_kg = _decimal(data.get("muscle_mass_kg"))
        if "water_percent" in data:
            record.water_percentage = _decimal(data.get("water_percent"))
        if "visceral_fat" in data:
            record.visceral_fat = _decimal(data.get("visceral_fat"))
        if "bmr_kcal" in data:
            record.bmr_kcal = _decimal(data.get("bmr_kcal"))
        if "bmi" in data:
            record.bmi = _decimal(data.get("bmi"))
        if "source" in data or not existing_id:
            record.source = data.get("source", document["source_type"]).strip()
        if "notes" in data:
            record.notes = data.get("notes")
        record.raw_payload_json = document
        db.session.add(record)
        return record

    def _apply_daily_energy(self, document: dict[str, Any], user_id: int, existing_id: int | None) -> DailyEnergy:
        data = document["data"]
        record = db.session.get(DailyEnergy, existing_id) if existing_id else DailyEnergy(user_id=user_id)
        if record is None or record.user_id != user_id:
            raise StandardImportError("Daily energy target does not belong to this user")
        record.date = date.fromisoformat(data["date"])
        if "total_expenditure_kcal" in data:
            record.total_calories = _decimal(data.get("total_expenditure_kcal"))
        if "active_expenditure_kcal" in data:
            record.active_calories = _decimal(data.get("active_expenditure_kcal"))
        if "resting_expenditure_kcal" in data:
            record.resting_calories = _decimal(data.get("resting_expenditure_kcal"))
        if "steps" in data:
            record.steps = data.get("steps")
        if "distance_meters" in data:
            record.distance_meters = _decimal(data.get("distance_meters"))
        if "source" in data or not existing_id:
            record.source = data.get("source", document["source_type"]).strip()
        if "notes" in data:
            record.notes = data.get("notes")
        record.raw_payload_json = document
        db.session.add(record)
        return record

    def _apply_daily_nutrition(self, document: dict[str, Any], user_id: int, existing_id: int | None) -> DailyNutrition:
        from app.services.importers.daily_nutrition import _totals, _validate_ordering, _validate_recipe_references

        data = document["data"]
        _validate_ordering(data)
        _validate_recipe_references(data, user_id)
        record = db.session.get(DailyNutrition, existing_id) if existing_id else DailyNutrition(user_id=user_id)
        if record is None or record.user_id != user_id:
            raise StandardImportError("Daily nutrition target does not belong to this user")
        record.date = date.fromisoformat(data["date"])
        if "source" in data or not existing_id:
            record.source = data.get("source", document["source_type"]).strip()
        if "notes" in data:
            record.notes = data.get("notes")
        record.raw_payload_json = document
        for field, value in _nutrition_totals_for_present_fields(data).items():
            setattr(record, field, value)
        if existing_id and "meals" in data:
            record.meals.clear()
            db.session.flush()
        db.session.add(record)
        db.session.flush()
        if "meals" in data and not record.meals:
            self._add_nutrition_meals(record, data, user_id)
        return record

    def _add_nutrition_meals(self, record: DailyNutrition, data: dict[str, Any], user_id: int) -> None:
        from app.services.importers.daily_nutrition import FIELD_MAP

        for meal_index, meal_data in enumerate(data.get("meals", []), start=1):
            meal = NutritionMeal(
                user_id=user_id,
                daily_nutrition_id=record.id,
                meal_type=meal_data["meal_type"],
                name=meal_data.get("name"),
                sort_order=meal_data.get("sort_order", meal_index),
            )
            db.session.add(meal)
            db.session.flush()
            for item_index, item_data in enumerate(meal_data["items"], start=1):
                item_values = {
                    model_field: _decimal(item_data.get(document_field))
                    for model_field, document_field in FIELD_MAP.items()
                }
                db.session.add(
                    NutritionItem(
                        user_id=user_id,
                        nutrition_meal_id=meal.id,
                        name=item_data["name"].strip(),
                        quantity=_decimal(item_data.get("quantity")),
                        unit=item_data.get("unit"),
                        food_product_id=item_data.get("food_product_id"),
                        recipe_id=item_data.get("recipe_id"),
                        sort_order=item_data.get("sort_order", item_index),
                        notes=item_data.get("notes"),
                        calories=item_values.pop("calories", None),
                        **item_values,
                    )
                )

    def _apply_food_product(self, document: dict[str, Any], user_id: int, existing_id: int | None) -> FoodProduct:
        from app.services.importers.food_product import _product_data

        data = _product_data(document)
        record = db.session.get(FoodProduct, existing_id) if existing_id else FoodProduct(user_id=user_id)
        if record is None or record.user_id != user_id:
            raise StandardImportError("Food product target does not belong to this user")
        for field in (
            "name",
            "brand",
            "serving_label",
            "source",
            "notes",
        ):
            if field in data:
                setattr(record, field, data[field])
        for field in (
            "serving_size_g",
            "calories_per_100g",
            "protein_g_per_100g",
            "fat_g_per_100g",
            "carbs_g_per_100g",
            "net_carbs_g_per_100g",
            "fiber_g_per_100g",
            "sodium_mg_per_100g",
        ):
            if field in data:
                setattr(record, field, _decimal(data.get(field)))
        if not record.source:
            record.source = document.get("source_type", "uploaded")
        record.raw_payload_json = document
        db.session.add(record)
        return record

    def _apply_recipe(self, document: dict[str, Any], user_id: int, existing_id: int | None) -> Recipe:
        record = db.session.get(Recipe, existing_id) if existing_id else Recipe(user_id=user_id)
        if record is None or record.user_id != user_id:
            raise StandardImportError("Recipe target does not belong to this user")
        record.name = document["name"].strip()
        if "description" in document:
            record.description = _optional_text(document.get("description"))
        if "servings" in document:
            record.servings = _decimal(document.get("servings"))
        if "yield_weight_g" in document:
            record.yield_weight_g = _decimal(document.get("yield_weight_g"))
        if "source" in document or not existing_id:
            record.source = _optional_text(document.get("source")) or document.get("source_type", "uploaded")
        if "notes" in document:
            record.notes = _optional_text(document.get("notes"))
        record.raw_payload_json = document
        if existing_id:
            record.ingredients.clear()
            db.session.flush()
        db.session.add(record)
        db.session.flush()
        self._add_recipe_ingredients(record, document, user_id)
        return record

    def _apply_recipe_bundle(self, document: dict[str, Any], user_id: int) -> Recipe:
        last_recipe: Recipe | None = None
        for recipe_document in document["recipes"]:
            validate_json_document(recipe_document, "recipe")
            existing = self._recipe_by_name(user_id, recipe_document["name"])
            last_recipe = self._apply_recipe(
                recipe_document,
                user_id,
                existing.id if existing else None,
            )
        if last_recipe is None:
            raise StandardImportError("Recipe bundle contains no recipes")
        return last_recipe

    def _add_recipe_ingredients(self, record: Recipe, document: dict[str, Any], user_id: int) -> None:
        for index, item in enumerate(document["ingredients"], start=1):
            product = self._resolve_food_product(user_id, item)
            db.session.add(
                RecipeIngredient(
                    user_id=user_id,
                    recipe_id=record.id,
                    food_product_id=product.id,
                    name_snapshot=product.name,
                    brand_snapshot=product.brand,
                    quantity_g=_decimal(item["quantity_g"]),
                    sort_order=item.get("sort_order", index),
                    calories_per_100g=product.calories_per_100g,
                    protein_g_per_100g=product.protein_g_per_100g,
                    fat_g_per_100g=product.fat_g_per_100g,
                    carbs_g_per_100g=product.carbs_g_per_100g,
                    net_carbs_g_per_100g=product.net_carbs_g_per_100g,
                    fiber_g_per_100g=product.fiber_g_per_100g,
                    sodium_mg_per_100g=product.sodium_mg_per_100g,
                    notes=item.get("notes"),
                )
            )

    def _apply_training_plan(
        self,
        document: dict[str, Any],
        user_id: int,
        existing_id: int | None,
        operation: str,
    ) -> TrainingPlan:
        from app.services.importers.training_plan import _validate_plan_ordering

        _validate_plan_ordering(document)
        content_sha256 = hashlib.sha256(serialize_training_plan(document)).hexdigest()
        if existing_id:
            plan = db.session.get(TrainingPlan, existing_id)
            if plan is None or plan.user_id != user_id:
                raise StandardImportError("Training plan target does not belong to this user")
            latest = max((version.version_number for version in plan.versions), default=0)
            version_number = latest + 1 if operation == "update" else 1
        else:
            plan = TrainingPlan(
                user_id=user_id,
                name=document["data"]["name"].strip(),
                description=_optional_text(document["data"].get("description")),
                active_version_number=1,
            )
            db.session.add(plan)
            db.session.flush()
            version_number = 1
        plan.name = document["data"]["name"].strip()
        if "description" in document["data"] or not existing_id:
            plan.description = _optional_text(document["data"].get("description"))
        plan.active_version_number = version_number
        version = TrainingPlanVersion(
            user_id=user_id,
            training_plan_id=plan.id,
            version_number=version_number,
            created_by_user_id=user_id,
            change_reason="Confirmed assisted import",
            schema_version=document["schema_version"],
            sha256=content_sha256,
            content=document,
        )
        db.session.add(version)
        return plan

    def _apply_completed_workout(self, document: dict[str, Any], user_id: int) -> TrainingSession:
        data = document["data"]
        version = db.session.execute(
            db.select(TrainingPlanVersion).where(
                TrainingPlanVersion.id == data["training_plan_version_id"],
                TrainingPlanVersion.user_id == user_id,
            )
        ).scalar_one_or_none()
        if version is None or version.training_plan_id != data["training_plan_id"]:
            raise StandardImportError("Training plan version does not belong to this user")
        session = TrainingSession(
            user_id=user_id,
            training_plan_id=data["training_plan_id"],
            training_plan_version_id=data["training_plan_version_id"],
            performed_at=datetime.fromisoformat(data["performed_at"].replace("Z", "+00:00")),
            planned_week_number=data["planned_week_number"],
            planned_day_number=data["planned_day_number"],
            duration_seconds=data.get("duration_seconds"),
            average_heart_rate_bpm=data.get("average_heart_rate_bpm"),
            calories_burned=_decimal(data.get("calories_burned")),
            notes=data.get("notes"),
        )
        db.session.add(session)
        db.session.flush()
        for exercise_data in data["exercises"]:
            exercise = TrainingSessionExercise(
                user_id=user_id,
                training_session_id=session.id,
                exercise_order=exercise_data["exercise_order"],
                planned_exercise_order=exercise_data.get(
                    "planned_exercise_order",
                    exercise_data["exercise_order"],
                ),
                name=exercise_data["name"],
                notes=exercise_data.get("notes"),
            )
            db.session.add(exercise)
            db.session.flush()
            for set_data in exercise_data["sets"]:
                db.session.add(
                    TrainingSet(
                        user_id=user_id,
                        training_session_exercise_id=exercise.id,
                        set_number=set_data["set_number"],
                        planned_set_number=set_data.get(
                            "planned_set_number",
                            set_data["set_number"],
                        ),
                        weight_kg=_decimal(set_data["weight_kg"]),
                        reps=set_data["reps"],
                        rir=_decimal(set_data.get("rir")),
                        rpe=_decimal(set_data.get("rpe")),
                        rest_seconds=set_data.get("rest_seconds"),
                        notes=set_data.get("notes"),
                    )
                )
        return session

    def _apply_medical_lab(self, document: dict[str, Any], user_id: int, existing_id: int | None) -> MedicalLabReport:
        report = db.session.get(MedicalLabReport, existing_id) if existing_id else MedicalLabReport(user_id=user_id)
        if report is None or report.user_id != user_id:
            raise StandardImportError("Medical lab report target does not belong to this user")
        report.date = date.fromisoformat(document["date"])
        if "laboratory_name" in document:
            report.laboratory_name = document.get("laboratory_name")
        if "doctor_name" in document:
            report.doctor_name = document.get("doctor_name")
        if "source" in document or "source_type" in document or not existing_id:
            report.source = document.get("source") or document.get("source_type", "uploaded")
        if "notes" in document:
            report.notes = document.get("notes")
        report.raw_payload_json = document
        if existing_id:
            report.results.clear()
            db.session.flush()
        db.session.add(report)
        db.session.flush()
        for marker in document["markers"]:
            value = marker["value"]
            db.session.add(
                MedicalLabResult(
                    user_id=user_id,
                    report_id=report.id,
                    marker_name=marker["name"],
                    marker_code=marker.get("code"),
                    value=_decimal(value) if isinstance(value, (int, float)) else None,
                    value_text=None if isinstance(value, (int, float)) else str(value),
                    unit=marker["unit"],
                    reference_min=_decimal(marker.get("reference_min")),
                    reference_max=_decimal(marker.get("reference_max")),
                    reference_text=marker.get("reference_text"),
                    status=marker.get("status", "unknown"),
                    notes=marker.get("notes"),
                )
            )
        return report

    def _resolve_food_product(self, user_id: int, item: dict[str, Any]) -> FoodProduct:
        if item.get("food_product_id") is not None:
            product = db.session.execute(
                db.select(FoodProduct).where(
                    FoodProduct.id == item["food_product_id"],
                    FoodProduct.user_id == user_id,
                )
            ).scalar_one_or_none()
        else:
            name = item["food_product_name"].strip()
            brand = item.get("food_product_brand")
            brand = brand.strip() if brand else None
            query = db.select(FoodProduct).where(
                FoodProduct.user_id == user_id,
                FoodProduct.name == name,
                FoodProduct.is_active.is_(True),
            )
            query = query.where(FoodProduct.brand.is_(None) if brand is None else FoodProduct.brand == brand)
            product = db.session.execute(query).scalar_one_or_none()
        if product is None:
            raise StandardImportError("Recipe ingredient food product was not found for this user")
        return product

    @staticmethod
    def _recipe_by_name(user_id: int, name: str) -> Recipe | None:
        return db.session.execute(
            db.select(Recipe).where(
                Recipe.user_id == user_id,
                Recipe.name == name.strip(),
            )
        ).scalar_one_or_none()

    @staticmethod
    def _document_label(document: dict[str, Any], schema_name: str) -> str:
        if schema_name in {"weigh_in", "daily_energy", "daily_nutrition"}:
            return str(document.get("data", {}).get("date") or document.get("data", {}).get("recorded_at") or schema_name)
        if schema_name == "training_plan":
            return str(document.get("data", {}).get("name") or schema_name)
        if schema_name in {"recipe", "food_product"}:
            return str(document.get("name") or schema_name)
        if schema_name == "recipe_bundle":
            return str(document.get("name") or "recipe_bundle")
        if schema_name == "medical_lab":
            return str(document.get("date") or schema_name)
        if schema_name == "completed_workout":
            return str(document.get("data", {}).get("performed_at") or schema_name)
        return schema_name

    @staticmethod
    def _model_name(target_type: str) -> str:
        return {
            "weigh_in": "WeighIn",
            "weigh_in_batch": "WeighIn",
            "food_product": "FoodProduct",
            "food_products": "FoodProduct",
            "daily_energy": "DailyEnergy",
            "daily_nutrition": "DailyNutrition",
            "completed_workout": "TrainingSession",
            "medical_lab": "MedicalLabReport",
            "training_plan": "TrainingPlan",
            "recipe": "Recipe",
            "recipe_bundle": "Recipe",
        }.get(target_type, target_type)

    @staticmethod
    def _summary(
        operations: list[PlannedOperation] | list[dict[str, Any]],
        *,
        committed: bool,
        rollback: bool,
    ) -> dict[str, Any]:
        operation_dicts = [
            operation.as_dict() if isinstance(operation, PlannedOperation) else operation
            for operation in operations
        ]
        counts = {key: 0 for key in EXPECTED_SECTIONS}
        for operation in operation_dicts:
            counts[operation["operation"]] += 1
        errors = [
            error
            for operation in operation_dicts
            for error in operation.get("errors", [])
        ]
        return {
            "total": len(operation_dicts),
            "valid": counts["insert"] + counts["update"] + counts["skip"],
            "invalid": counts["invalid"],
            "inserts": counts["insert"],
            "updates": counts["update"],
            "skips": counts["skip"],
            "conflicts": counts["conflict"],
            "errors": errors,
            "rollback": rollback,
            "committed": committed,
            "operations": operation_dicts,
        }


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _nutrition_totals_for_present_fields(data: dict[str, Any]) -> dict[str, Decimal | None]:
    from app.services.importers.daily_nutrition import FIELD_MAP, _totals

    if data.get("meals"):
        return _totals(data)

    totals = _totals(data)
    present: dict[str, Decimal | None] = {}
    for model_field, document_field in FIELD_MAP.items():
        if document_field in data or (
            model_field == "total_carbs_g" and "carbohydrate_g" in data
        ):
            present[model_field] = totals[model_field]
    return present


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _plan_fingerprint(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "total": plan.get("total"),
        "valid": plan.get("valid"),
        "invalid": plan.get("invalid"),
        "inserts": plan.get("inserts"),
        "updates": plan.get("updates"),
        "skips": plan.get("skips"),
        "conflicts": plan.get("conflicts"),
        "operations": plan.get("operations", []),
    }


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
