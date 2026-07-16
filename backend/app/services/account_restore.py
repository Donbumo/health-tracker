from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import hashlib
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.extensions import db
from app.models import (
    Activity,
    DailyEnergy,
    DailyNutrition,
    FoodProduct,
    MedicalLabReport,
    MedicalLabResult,
    NutritionItem,
    NutritionMeal,
    Recipe,
    RecipeIngredient,
    Route,
    TrainingPlan,
    TrainingPlanVersion,
    TrainingSession,
    TrainingSessionExercise,
    TrainingSet,
    User,
    WeighIn,
)
from app.services.import_audit import ImportAuditService
from app.services.importers.standard_import_executor import (
    GENERIC_WRITE_FAILURE_MESSAGE,
    StandardImportError,
    canonical_sha256,
)
from app.services.training_plans import serialize_training_plan
from app.services.validation import JsonSchemaValidationError, validate_json_document


RESTORE_TARGET_TYPE = "user_data_restore"
RESTORE_SOURCE_TYPE = "uploaded"
RESTORE_TOKEN_SALT = "account-restore-confirmation-v1"
RESTORE_MAX_AGE_SECONDS = 15 * 60
MAX_EXPORT_BYTES = 10 * 1024 * 1024
MAX_SECTION_ITEMS = 1000
MAX_JSON_DEPTH = 24
MAX_JSON_ARRAY_ITEMS = 1000
MAX_JSON_STRING_LENGTH = 10000
MAX_JSON_OBJECT_KEYS = 2000
MAX_JSON_TOTAL_NODES = 50000
SCHEMA_VERSION = "1.0"
RESTORE_TOKEN_VERSION = "1"
RESTORE_MODE = "account_restore"

RESTORABLE_SECTIONS = (
    "food_products",
    "recipes",
    "weigh_ins",
    "daily_energy",
    "daily_nutrition",
    "medical_lab_reports",
    "training_plans",
    "training_sessions",
    "exercise_load_profiles",
    "activities",
    "routes",
)
UNSUPPORTED_SECTIONS = ("uploads", "daily_balances", "export_records")


class AccountRestoreError(ValueError):
    pass


class AccountRestoreTokenError(AccountRestoreError):
    pass


@dataclass(frozen=True)
class RestoreOperation:
    operation: str
    section: str
    index: int
    label: str
    existing_id: int | None = None
    source_id: int | None = None
    model: str | None = None
    errors: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "section": self.section,
            "index": self.index,
            "label": self.label,
            "existing_id": self.existing_id,
            "source_id": self.source_id,
            "model": self.model,
            "errors": list(self.errors),
        }


class AccountRestoreService:
    """Preview and confirm full account exports without trusting exported identity."""

    def __init__(self, audit_service: ImportAuditService | None = None) -> None:
        self.audit_service = audit_service or ImportAuditService()

    def preview(self, payload: dict[str, Any], *, user_id: int) -> dict[str, Any]:
        self._validate_export(payload)
        plan = self._build_plan(payload, user_id=user_id)
        return {
            "valid": plan["invalid"] == 0 and plan["conflicts"] == 0,
            "read_only": True,
            "writes_performed": False,
            "payload_sha256": canonical_sha256(payload),
            "plan_sha256": self.plan_sha256(plan),
            "exported_user": _safe_exported_user(payload),
            "ignored_user_metadata": True,
            "plan": plan,
            "sections": self._section_counts(payload),
            "warnings": self._warnings(payload, plan),
            "confirmation_token": self.build_confirmation_token(
                user_id=user_id,
                payload=payload,
                plan=plan,
            ),
        }

    def build_confirmation_token(
        self,
        *,
        user_id: int,
        payload: dict[str, Any],
        plan: dict[str, Any],
    ) -> str:
        return _serializer().dumps(
            {
                "user_id": user_id,
                "schema_version": payload.get("schema_version"),
                "version": RESTORE_TOKEN_VERSION,
                "mode": RESTORE_MODE,
                "target_type": RESTORE_TARGET_TYPE,
                "payload_sha256": canonical_sha256(payload),
                "plan_sha256": self.plan_sha256(plan),
            },
            salt=RESTORE_TOKEN_SALT,
        )

    def verify_confirmation_token(
        self,
        token: str,
        *,
        user_id: int,
        payload: dict[str, Any],
        plan: dict[str, Any],
        max_age: int = RESTORE_MAX_AGE_SECONDS,
    ) -> None:
        try:
            data = _serializer().loads(token, salt=RESTORE_TOKEN_SALT, max_age=max_age)
        except SignatureExpired as error:
            raise AccountRestoreTokenError("Restore confirmation token expired") from error
        except BadSignature as error:
            raise AccountRestoreTokenError("Restore confirmation token is invalid") from error

        expected = {
            "user_id": user_id,
            "schema_version": payload.get("schema_version"),
            "version": RESTORE_TOKEN_VERSION,
            "mode": RESTORE_MODE,
            "target_type": RESTORE_TARGET_TYPE,
            "payload_sha256": canonical_sha256(payload),
            "plan_sha256": self.plan_sha256(plan),
        }
        if any(data.get(key) != value for key, value in expected.items()):
            raise AccountRestoreTokenError(
                "Restore preview changed; review the new plan and confirm again"
            )

    def commit(
        self,
        payload: dict[str, Any],
        *,
        user_id: int,
        confirmation_token: str,
    ) -> dict[str, Any]:
        self._validate_export(payload)
        plan = self._build_plan(payload, user_id=user_id)
        self.verify_confirmation_token(
            confirmation_token,
            user_id=user_id,
            payload=payload,
            plan=plan,
        )

        blocking = [
            item for item in plan["operations"]
            if item["operation"] in {"invalid", "conflict"}
        ]
        only_unsupported = (
            plan["total"] > 0
            and plan["valid"] == 0
            and plan["unsupported"] == plan["total"]
        )
        payload_sha256 = canonical_sha256(payload)
        plan_sha256 = self.plan_sha256(plan)
        metadata = {
            "route": "/account/restore/confirm",
            "mode": "account_restore",
            "contract_version": "account-restore-v1",
            "document_count": plan["total"],
        }
        if blocking or only_unsupported:
            block_errors = [
                error
                for item in blocking
                for error in item.get("errors", [])
            ]
            if only_unsupported:
                block_errors.insert(
                    0,
                    "Restore contains only unsupported metadata or derived records.",
                )
            result = {
                **plan,
                "committed": False,
                "rollback": False,
                "errors": [
                    "Restore contains invalid, conflicting, or unsupported-only records.",
                    *block_errors,
                ],
            }
            run = self.audit_service.record_blocked(
                user_id=user_id,
                target_type=RESTORE_TARGET_TYPE,
                source_type=RESTORE_SOURCE_TYPE,
                payload_sha256=payload_sha256,
                plan_sha256=plan_sha256,
                summary=result,
                error_message=result["errors"][0],
                metadata=metadata,
            )
            return {**result, "audit_run_id": run.id}

        audit_run = self.audit_service.record_pending(
            user_id=user_id,
            target_type=RESTORE_TARGET_TYPE,
            source_type=RESTORE_SOURCE_TYPE,
            payload_sha256=payload_sha256,
            plan_sha256=plan_sha256,
            summary=plan,
            metadata=metadata,
        )

        try:
            committed = self._apply_payload(payload, user_id=user_id)
            result = {
                **self._summary(
                    [
                        {
                            **item,
                            "existing_id": committed.get(
                                f"{item['section']}:{item['index']}",
                                item.get("existing_id"),
                            ),
                        }
                        for item in plan["operations"]
                    ],
                    committed=True,
                    rollback=False,
                ),
                "created_or_updated_ids": committed,
            }
            self.audit_service.finalize_succeeded(audit_run, result)
            db.session.commit()
        except Exception:
            db.session.rollback()
            result = {
                **plan,
                "committed": False,
                "rollback": True,
                "errors": [GENERIC_WRITE_FAILURE_MESSAGE],
            }
            run = self.audit_service.record_failed_existing(
                run_id=audit_run.id,
                summary=result,
                error_message=GENERIC_WRITE_FAILURE_MESSAGE,
                fallback={
                    "user_id": user_id,
                    "target_type": RESTORE_TARGET_TYPE,
                    "source_type": RESTORE_SOURCE_TYPE,
                    "payload_sha256": payload_sha256,
                    "plan_sha256": plan_sha256,
                    "metadata": metadata,
                },
            )
            return {**result, "audit_run_id": run.id}

        return {**result, "audit_run_id": audit_run.id}

    def apply_in_transaction(
        self,
        payload: dict[str, Any],
        *,
        user_id: int,
        expected_plan_sha256: str,
    ) -> dict[str, Any]:
        """Apply a previously reviewed plan without committing or auditing.

        This narrow entry point exists for coordinators that must include the
        account restore in a larger database/filesystem transaction.  Callers
        remain responsible for a persisted pending audit run, commit/rollback,
        and compensating any filesystem changes.
        """
        self._validate_export(payload)
        plan = self._build_plan(payload, user_id=user_id)
        if self.plan_sha256(plan) != expected_plan_sha256:
            raise AccountRestoreTokenError(
                "Restore preview changed; review the new plan and confirm again"
            )
        blocking = [
            item
            for item in plan["operations"]
            if item["operation"] in {"invalid", "conflict"}
        ]
        if blocking:
            raise AccountRestoreError(
                "Restore contains invalid or conflicting records"
            )

        committed = self._apply_payload(payload, user_id=user_id)
        result = {
            **self._summary(
                [
                    {
                        **item,
                        "existing_id": committed.get(
                            f"{item['section']}:{item['index']}",
                            item.get("existing_id"),
                        ),
                    }
                    for item in plan["operations"]
                ],
                committed=True,
                rollback=False,
            ),
            "created_or_updated_ids": committed,
        }
        return result

    @staticmethod
    def plan_sha256(plan: dict[str, Any]) -> str:
        fingerprint = {
            key: plan.get(key)
            for key in (
                "total",
                "valid",
                "invalid",
                "inserts",
                "updates",
                "skips",
                "conflicts",
                "unsupported",
                "operations",
            )
        }
        return canonical_sha256(fingerprint)

    def _validate_export(self, payload: dict[str, Any]) -> None:
        _validate_json_limits(payload)
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise AccountRestoreError("Unsupported user_data_export schema version")
        try:
            validate_json_document(payload, "user_data_export")
        except JsonSchemaValidationError as error:
            raise AccountRestoreError("Invalid user_data_export schema") from error
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise AccountRestoreError("Export data must be an object")
        for section, items in data.items():
            if section in RESTORABLE_SECTIONS or section in UNSUPPORTED_SECTIONS:
                if not isinstance(items, list):
                    raise AccountRestoreError(f"Export section {section} must be a list")
                if len(items) > MAX_SECTION_ITEMS:
                    raise AccountRestoreError(f"Export section {section} is too large")

    def _build_plan(self, payload: dict[str, Any], *, user_id: int) -> dict[str, Any]:
        data = payload.get("data") or {}
        operations: list[RestoreOperation] = []
        known_product_keys = _known_product_keys(user_id)
        id_maps: dict[str, dict[int, int]] = {
            "training_plans": {},
            "training_plan_versions": {},
        }
        for section in UNSUPPORTED_SECTIONS:
            for index, item in enumerate(data.get(section) or []):
                operations.append(
                    RestoreOperation(
                        "unsupported",
                        section,
                        index,
                        _label(item, section),
                        source_id=_source_id(item),
                        errors=("Section is export metadata or derived data; it is not restored.",),
                    )
                )
        for section in RESTORABLE_SECTIONS:
            for index, item in enumerate(data.get(section) or []):
                operation = self._plan_item(
                    section,
                    index,
                    item,
                    user_id=user_id,
                    id_maps=id_maps,
                    known_product_keys=known_product_keys,
                )
                operations.append(operation)
                if section == "food_products" and operation.operation in {
                    "insert",
                    "update",
                    "skip",
                }:
                    try:
                        product_document = self._normalized_item(
                            "food_products",
                            item,
                            user_id=user_id,
                        )
                    except Exception:
                        pass
                    else:
                        known_product_keys.add(_product_key(product_document))
                if section == "training_plans":
                    self._extend_existing_training_maps(
                        item,
                        operation=operation,
                        user_id=user_id,
                        id_maps=id_maps,
                    )
        return self._summary([item.as_dict() for item in operations], committed=False, rollback=False)

    def _plan_item(
        self,
        section: str,
        index: int,
        item: dict[str, Any],
        *,
        user_id: int,
        id_maps: dict[str, dict[int, int]] | None = None,
        known_product_keys: set[tuple[str, str | None]] | None = None,
    ) -> RestoreOperation:
        source_id = _source_id(item)
        try:
            normalized = self._normalized_item(
                section,
                item,
                user_id=user_id,
                id_maps=id_maps,
            )
            if section == "recipes":
                _validate_recipe_product_references(
                    normalized,
                    known_product_keys or _known_product_keys(user_id),
                )
            existing = self._find_existing(section, normalized, user_id=user_id)
        except Exception as error:
            return RestoreOperation(
                "invalid",
                section,
                index,
                _label(item, section),
                source_id=source_id,
                errors=(safe_error(error),),
            )

        if existing is None:
            return RestoreOperation("insert", section, index, _label(normalized, section), source_id=source_id, model=_model(section))
        if self._same(section, existing, normalized, user_id=user_id):
            return RestoreOperation(
                "skip",
                section,
                index,
                _label(normalized, section),
                existing_id=existing.id,
                source_id=source_id,
                model=_model(section),
            )
        if section == "training_sessions":
            return RestoreOperation(
                "conflict",
                section,
                index,
                _label(normalized, section),
                existing_id=existing.id,
                source_id=source_id,
                model=_model(section),
                errors=("Completed workout updates are not supported safely yet.",),
            )
        return RestoreOperation(
            "update",
            section,
            index,
            _label(normalized, section),
            existing_id=existing.id,
            source_id=source_id,
            model=_model(section),
        )

    def _normalized_item(
        self,
        section: str,
        item: dict[str, Any],
        *,
        user_id: int,
        id_maps: dict[str, dict[int, int]] | None = None,
    ) -> dict[str, Any]:
        document = deepcopy(item)
        if section == "training_plans":
            return document
        if section == "exercise_load_profiles":
            from app.services.workout_loads import SUPPORTED_MODES, calculate_workout_load

            if document.get("load_mode") not in SUPPORTED_MODES:
                raise AccountRestoreError("Unsupported exercise load mode")
            if document.get("preferred_unit") not in {"kg", "lb"}:
                raise AccountRestoreError("Unsupported exercise load unit")
            if not isinstance(document.get("exercise_name"), str) or not document["exercise_name"].strip():
                raise AccountRestoreError("Exercise load profile requires a name")
            configuration = document.get("configuration") or {}
            if set(configuration) - {
                "schema_version",
                "calculation_version",
                "components",
            }:
                raise AccountRestoreError("Exercise load profile configuration is invalid")
            calculate_workout_load(
                document["load_mode"],
                document["preferred_unit"],
                configuration.get("components") or {},
            )
            increments = document.get("quick_increments") or []
            if not isinstance(increments, list) or len(increments) > 10:
                raise AccountRestoreError("Exercise load quick increments are invalid")
            return document
        if section == "training_sessions":
            document["user_id"] = user_id
            maps = id_maps or {}
            data = document.get("data") or {}
            old_plan_id = data.get("training_plan_id")
            old_version_id = data.get("training_plan_version_id")
            if old_plan_id in maps.get("training_plans", {}):
                data["training_plan_id"] = maps["training_plans"][old_plan_id]
            if old_version_id in maps.get("training_plan_versions", {}):
                data["training_plan_version_id"] = maps["training_plan_versions"][old_version_id]
            document["data"] = data
            validate_json_document(document, "completed_workout")
            try:
                from app.services.workout_loads import validate_completed_workout_loads

                validate_completed_workout_loads(document)
            except ValueError as error:
                raise AccountRestoreError(str(error)) from error
            return document
        if section == "medical_lab_reports":
            document["user_id"] = user_id
            validate_json_document(document, "medical_lab")
            return document
        if section == "recipes":
            document.pop("id", None)
            document["user_id"] = user_id
            document.setdefault("source_type", "uploaded")
            validate_json_document(document, "recipe")
            return document
        if section == "activities":
            document["user_id"] = user_id
            document.pop("source_file_id", None)
            validate_json_document(document, "activity")
            return document
        if section == "routes":
            document["user_id"] = user_id
            document.pop("source_file_id", None)
            validate_json_document(document, "route")
            return document
        if section == "food_products":
            document.pop("id", None)
            document.pop("is_active", None)
            document.setdefault("schema_version", SCHEMA_VERSION)
            document.setdefault("type", "food_product")
            document["user_id"] = user_id
            document.setdefault("source_type", "uploaded")
            validate_json_document(document, "food_product")
            return document
        schema = {
            "weigh_ins": "weigh_in",
            "daily_energy": "daily_energy",
            "daily_nutrition": "daily_nutrition",
        }[section]
        document["user_id"] = user_id
        validate_json_document(document, schema)
        return document

    def _find_existing(self, section: str, item: dict[str, Any], *, user_id: int) -> Any | None:
        if section == "food_products":
            name = item["name"].strip()
            brand = item.get("brand")
            brand = brand.strip() if brand else None
            query = db.select(FoodProduct).where(FoodProduct.user_id == user_id, FoodProduct.name == name)
            query = query.where(FoodProduct.brand.is_(None) if brand is None else FoodProduct.brand == brand)
            return db.session.execute(query).scalar_one_or_none()
        if section == "recipes":
            return db.session.execute(
                db.select(Recipe).where(Recipe.user_id == user_id, Recipe.name == item["name"].strip())
            ).scalar_one_or_none()
        if section == "exercise_load_profiles":
            from app.models import ExerciseLoadProfile
            from app.services.exercise_identity import find_exercise_identity

            exercise = find_exercise_identity(user_id, item["exercise_name"])
            if exercise is None:
                return None
            return db.session.execute(
                db.select(ExerciseLoadProfile).where(
                    ExerciseLoadProfile.user_id == user_id,
                    ExerciseLoadProfile.exercise_id == exercise.id,
                )
            ).scalar_one_or_none()
        if section == "weigh_ins":
            recorded_at = datetime.fromisoformat(item["data"]["recorded_at"].replace("Z", "+00:00"))
            source = item["data"].get("source", item.get("source_type", "uploaded")).strip()
            return db.session.execute(
                db.select(WeighIn).where(
                    WeighIn.user_id == user_id,
                    WeighIn.recorded_at == recorded_at,
                    WeighIn.source == source,
                )
            ).scalar_one_or_none()
        if section == "daily_energy":
            return db.session.execute(
                db.select(DailyEnergy).where(
                    DailyEnergy.user_id == user_id,
                    DailyEnergy.date == date.fromisoformat(item["data"]["date"]),
                )
            ).scalar_one_or_none()
        if section == "daily_nutrition":
            return db.session.execute(
                db.select(DailyNutrition).where(
                    DailyNutrition.user_id == user_id,
                    DailyNutrition.date == date.fromisoformat(item["data"]["date"]),
                )
            ).scalar_one_or_none()
        if section == "medical_lab_reports":
            lab = item.get("laboratory_name")
            lab = lab.strip() if lab else None
            query = db.select(MedicalLabReport).where(
                MedicalLabReport.user_id == user_id,
                MedicalLabReport.date == date.fromisoformat(item["date"]),
            )
            query = query.where(MedicalLabReport.laboratory_name.is_(None) if lab is None else MedicalLabReport.laboratory_name == lab)
            return db.session.execute(query).scalar_one_or_none()
        if section == "training_plans":
            return db.session.execute(
                db.select(TrainingPlan).where(
                    TrainingPlan.user_id == user_id,
                    TrainingPlan.name == item["name"].strip(),
                )
            ).scalar_one_or_none()
        if section == "training_sessions":
            data = item["data"]
            performed_at = datetime.fromisoformat(data["performed_at"].replace("Z", "+00:00"))
            return db.session.execute(
                db.select(TrainingSession).where(
                    TrainingSession.user_id == user_id,
                    TrainingSession.training_plan_version_id == data["training_plan_version_id"],
                    TrainingSession.performed_at == performed_at,
                )
            ).scalar_one_or_none()
        if section == "activities":
            return db.session.execute(
                db.select(Activity).where(
                    Activity.user_id == user_id,
                    Activity.fingerprint_sha256 == _activity_route_sha(item),
                )
            ).scalar_one_or_none()
        if section == "routes":
            return db.session.execute(
                db.select(Route).where(
                    Route.user_id == user_id,
                    Route.fingerprint_sha256 == _activity_route_sha(item),
                )
            ).scalar_one_or_none()
        return None

    def _same(self, section: str, existing: Any, item: dict[str, Any], *, user_id: int) -> bool:
        if section == "training_plans":
            existing_hashes = {version.sha256 for version in existing.versions}
            return all(
                _training_version_sha(version["document"], user_id) in existing_hashes
                for version in item.get("versions", [])
            )
        if section == "training_sessions":
            from app.services.exporters.training_session import (
                build_completed_workout_document,
            )

            return build_completed_workout_document(existing, user_id) == item
        if section in {"activities", "routes"}:
            return existing.fingerprint_sha256 == _activity_route_sha(item)
        if section == "exercise_load_profiles":
            return (
                existing.load_mode == item["load_mode"]
                and existing.preferred_unit == item["preferred_unit"]
                and (existing.configuration_json or {}) == (item.get("configuration") or {})
                and (existing.quick_increments_json or []) == (item.get("quick_increments") or [])
            )
        if hasattr(existing, "raw_payload_json") and existing.raw_payload_json is not None:
            return existing.raw_payload_json == item
        return False

    def _apply_payload(self, payload: dict[str, Any], *, user_id: int) -> dict[str, int]:
        data = payload.get("data") or {}
        plan = self._build_plan(payload, user_id=user_id)
        operation_map = {
            (operation["section"], operation["index"]): operation
            for operation in plan["operations"]
        }
        committed: dict[str, int] = {}
        id_maps: dict[str, dict[int, int]] = {
            "food_products": {},
            "recipes": {},
            "training_plans": {},
            "training_plan_versions": {},
        }

        for index, item in enumerate(data.get("food_products") or []):
            operation = operation_map.get(("food_products", index), {})
            if operation.get("operation") == "skip":
                if _source_id(item) is not None and operation.get("existing_id"):
                    id_maps["food_products"][_source_id(item)] = operation["existing_id"]
                continue
            document = self._normalized_item("food_products", item, user_id=user_id)
            record = self._apply_food_product(document, user_id=user_id)
            db.session.flush()
            committed[f"food_products:{index}"] = record.id
            if _source_id(item) is not None:
                id_maps["food_products"][_source_id(item)] = record.id

        for index, item in enumerate(data.get("recipes") or []):
            operation = operation_map.get(("recipes", index), {})
            if operation.get("operation") == "skip":
                if _source_id(item) is not None and operation.get("existing_id"):
                    id_maps["recipes"][_source_id(item)] = operation["existing_id"]
                continue
            document = self._normalized_item("recipes", item, user_id=user_id)
            record = self._apply_recipe(document, user_id=user_id)
            db.session.flush()
            committed[f"recipes:{index}"] = record.id
            if _source_id(item) is not None:
                id_maps["recipes"][_source_id(item)] = record.id

        for section in ("weigh_ins", "daily_energy", "daily_nutrition", "medical_lab_reports"):
            for index, item in enumerate(data.get(section) or []):
                operation = operation_map.get((section, index), {})
                if operation.get("operation") == "skip":
                    continue
                document = self._normalized_item(section, item, user_id=user_id)
                record = self._apply_simple(section, document, user_id=user_id)
                db.session.flush()
                committed[f"{section}:{index}"] = record.id

        for index, item in enumerate(data.get("training_plans") or []):
            operation = operation_map.get(("training_plans", index), {})
            if operation.get("operation") == "skip":
                self._extend_existing_training_maps(
                    item,
                    operation=RestoreOperation(
                        "skip",
                        "training_plans",
                        index,
                        _label(item, "training_plans"),
                        existing_id=operation.get("existing_id"),
                    ),
                    user_id=user_id,
                    id_maps=id_maps,
                )
                continue
            record, version_map = self._apply_training_plan_bundle(item, user_id=user_id)
            db.session.flush()
            committed[f"training_plans:{index}"] = record.id
            if _source_id(item) is not None:
                id_maps["training_plans"][_source_id(item)] = record.id
            id_maps["training_plan_versions"].update(version_map)

        for index, item in enumerate(data.get("training_sessions") or []):
            operation = operation_map.get(("training_sessions", index), {})
            if operation.get("operation") == "skip":
                continue
            document = self._normalized_item(
                "training_sessions",
                item,
                user_id=user_id,
                id_maps=id_maps,
            )
            record = self._apply_training_session(document, user_id=user_id)
            db.session.flush()
            committed[f"training_sessions:{index}"] = record.id

        for section in ("activities", "routes"):
            for index, item in enumerate(data.get(section) or []):
                operation = operation_map.get((section, index), {})
                if operation.get("operation") == "skip":
                    continue
                document = self._normalized_item(section, item, user_id=user_id)
                record = self._apply_activity_or_route(section, document, user_id=user_id)
                db.session.flush()
                committed[f"{section}:{index}"] = record.id

        for index, item in enumerate(data.get("exercise_load_profiles") or []):
            operation = operation_map.get(("exercise_load_profiles", index), {})
            if operation.get("operation") == "skip":
                continue
            from app.services.workout_loads import (
                calculate_workout_load,
                upsert_exercise_load_profile,
            )

            restored_load_details = calculate_workout_load(
                item["load_mode"],
                item["preferred_unit"],
                (item.get("configuration") or {}).get("components", {}),
            ).details

            profile = upsert_exercise_load_profile(
                user_id=user_id,
                exercise_name=item["exercise_name"],
                load_details=restored_load_details,
            )
            profile.quick_increments_json = item.get("quick_increments") or ["2.5", "5"]
            db.session.flush()
            committed[f"exercise_load_profiles:{index}"] = profile.id

        exported_user = payload.get("user") or {}
        destination_user = db.session.get(User, user_id)
        preferred_unit = exported_user.get("preferred_load_unit")
        if preferred_unit in {"kg", "lb"}:
            destination_user.preferred_load_unit = preferred_unit
        display_name = _optional_text(exported_user.get("display_name"))
        if display_name is not None and len(display_name) <= 100:
            destination_user.display_name = display_name
        timezone_name = _optional_text(exported_user.get("timezone"))
        if timezone_name is not None and len(timezone_name) <= 64:
            try:
                ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError:
                pass
            else:
                destination_user.timezone = timezone_name

        return committed

    def _apply_food_product(self, document: dict[str, Any], *, user_id: int) -> FoodProduct:
        record = self._find_existing("food_products", document, user_id=user_id) or FoodProduct(user_id=user_id)
        for field in (
            "name",
            "brand",
            "serving_size_g",
            "serving_label",
            "calories_per_100g",
            "protein_g_per_100g",
            "fat_g_per_100g",
            "carbs_g_per_100g",
            "net_carbs_g_per_100g",
            "fiber_g_per_100g",
            "sodium_mg_per_100g",
            "source",
            "notes",
            "is_active",
        ):
            if field in document:
                setattr(record, field, _decimal(document.get(field)) if field.endswith("_g") or field.endswith("_mg") else document.get(field))
        record.source = record.source or document.get("source_type", "uploaded")
        record.raw_payload_json = document
        db.session.add(record)
        return record

    def _apply_recipe(self, document: dict[str, Any], *, user_id: int) -> Recipe:
        record = self._find_existing("recipes", document, user_id=user_id) or Recipe(user_id=user_id)
        record.name = document["name"].strip()
        for field in ("description", "notes"):
            if field in document:
                setattr(record, field, _optional_text(document.get(field)))
        record.servings = _decimal(document.get("servings", 1))
        if "yield_weight_g" in document:
            record.yield_weight_g = _decimal(document.get("yield_weight_g"))
        record.source = _optional_text(document.get("source")) or document.get("source_type", "uploaded")
        record.raw_payload_json = document
        if record.id is not None:
            record.ingredients.clear()
            db.session.flush()
        db.session.add(record)
        db.session.flush()
        for order, ingredient in enumerate(document["ingredients"], start=1):
            product = _find_product_for_ingredient(user_id, ingredient)
            if product is None:
                raise AccountRestoreError("Recipe ingredient food product was not found")
            db.session.add(
                RecipeIngredient(
                    user_id=user_id,
                    recipe_id=record.id,
                    food_product_id=product.id if product else None,
                    name_snapshot=(
                        product.name if product else ingredient.get("food_product_name", "ingredient")
                    ),
                    brand_snapshot=product.brand if product else ingredient.get("food_product_brand"),
                    quantity_g=_decimal(ingredient["quantity_g"]),
                    sort_order=ingredient.get("sort_order", order),
                    calories_per_100g=product.calories_per_100g if product else None,
                    protein_g_per_100g=product.protein_g_per_100g if product else None,
                    fat_g_per_100g=product.fat_g_per_100g if product else None,
                    carbs_g_per_100g=product.carbs_g_per_100g if product else None,
                    net_carbs_g_per_100g=product.net_carbs_g_per_100g if product else None,
                    fiber_g_per_100g=product.fiber_g_per_100g if product else None,
                    sodium_mg_per_100g=product.sodium_mg_per_100g if product else None,
                    notes=ingredient.get("notes"),
                )
            )
        return record

    def _apply_simple(self, section: str, document: dict[str, Any], *, user_id: int) -> Any:
        if section == "weigh_ins":
            return self._apply_weigh_in(document, user_id=user_id)
        if section == "daily_energy":
            return self._apply_daily_energy(document, user_id=user_id)
        if section == "daily_nutrition":
            return self._apply_daily_nutrition(document, user_id=user_id)
        if section == "medical_lab_reports":
            return self._apply_medical_lab(document, user_id=user_id)
        raise AccountRestoreError("Unsupported restore section")

    def _apply_weigh_in(self, document: dict[str, Any], *, user_id: int) -> WeighIn:
        data = document["data"]
        record = self._find_existing("weigh_ins", document, user_id=user_id) or WeighIn(user_id=user_id)
        record.recorded_at = datetime.fromisoformat(data["recorded_at"].replace("Z", "+00:00"))
        record.weight_kg = _decimal(data["weight_kg"])
        record.body_fat_percentage = _decimal(data.get("body_fat_percent"))
        record.muscle_mass_kg = _decimal(data.get("muscle_mass_kg"))
        record.water_percentage = _decimal(data.get("water_percent"))
        record.visceral_fat = _decimal(data.get("visceral_fat"))
        record.bmr_kcal = _decimal(data.get("bmr_kcal"))
        record.bmi = _decimal(data.get("bmi"))
        record.source = data.get("source", document["source_type"]).strip()
        record.notes = data.get("notes")
        record.raw_payload_json = document
        db.session.add(record)
        return record

    def _apply_daily_energy(self, document: dict[str, Any], *, user_id: int) -> DailyEnergy:
        data = document["data"]
        record = self._find_existing("daily_energy", document, user_id=user_id) or DailyEnergy(user_id=user_id)
        record.date = date.fromisoformat(data["date"])
        record.total_calories = _decimal(data.get("total_expenditure_kcal"))
        record.active_calories = _decimal(data.get("active_expenditure_kcal"))
        record.resting_calories = _decimal(data.get("resting_expenditure_kcal"))
        record.steps = data.get("steps")
        record.distance_meters = _decimal(data.get("distance_meters"))
        record.source = data.get("source", document["source_type"]).strip()
        record.notes = data.get("notes")
        record.raw_payload_json = document
        db.session.add(record)
        return record

    def _apply_daily_nutrition(self, document: dict[str, Any], *, user_id: int) -> DailyNutrition:
        data = document["data"]
        record = self._find_existing("daily_nutrition", document, user_id=user_id) or DailyNutrition(user_id=user_id)
        record.date = date.fromisoformat(data["date"])
        record.source = data.get("source", document["source_type"]).strip()
        record.notes = data.get("notes")
        for model_field, doc_field in (
            ("calories", "calories_kcal"),
            ("protein_g", "protein_g"),
            ("fat_g", "fat_g"),
            ("net_carbs_g", "net_carbs_g"),
            ("total_carbs_g", "total_carbs_g"),
            ("fiber_g", "fiber_g"),
            ("sugar_g", "sugar_g"),
            ("sodium_mg", "sodium_mg"),
        ):
            setattr(record, model_field, _decimal(data.get(doc_field)))
        record.raw_payload_json = document
        if record.id is not None:
            record.meals.clear()
            db.session.flush()
        db.session.add(record)
        db.session.flush()
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
            for item_index, item_data in enumerate(meal_data.get("items", []), start=1):
                db.session.add(
                    NutritionItem(
                        user_id=user_id,
                        nutrition_meal_id=meal.id,
                        name=item_data["name"],
                        quantity=_decimal(item_data.get("quantity")),
                        unit=item_data.get("unit"),
                        sort_order=item_data.get("sort_order", item_index),
                        calories=_decimal(item_data.get("calories_kcal")),
                        protein_g=_decimal(item_data.get("protein_g")),
                        fat_g=_decimal(item_data.get("fat_g")),
                        net_carbs_g=_decimal(item_data.get("net_carbs_g")),
                        total_carbs_g=_decimal(item_data.get("total_carbs_g")),
                        fiber_g=_decimal(item_data.get("fiber_g")),
                        sugar_g=_decimal(item_data.get("sugar_g")),
                        sodium_mg=_decimal(item_data.get("sodium_mg")),
                        notes=item_data.get("notes"),
                    )
                )
        return record

    def _apply_medical_lab(self, document: dict[str, Any], *, user_id: int) -> MedicalLabReport:
        report = self._find_existing("medical_lab_reports", document, user_id=user_id) or MedicalLabReport(user_id=user_id)
        report.date = date.fromisoformat(document["date"])
        report.laboratory_name = document.get("laboratory_name")
        report.doctor_name = document.get("doctor_name")
        report.source = document.get("source") or document.get("source_type", "uploaded")
        report.notes = document.get("notes")
        report.raw_payload_json = document
        if report.id is not None:
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

    def _apply_training_plan_bundle(
        self,
        item: dict[str, Any],
        *,
        user_id: int,
    ) -> tuple[TrainingPlan, dict[int, int]]:
        plan = self._find_existing("training_plans", item, user_id=user_id)
        if plan is None:
            plan = TrainingPlan(
                user_id=user_id,
                name=item["name"].strip(),
                description=_optional_text(item.get("description")),
                active_version_number=1,
            )
            db.session.add(plan)
            db.session.flush()
        version_map: dict[int, int] = {}
        existing_hashes = {version.sha256: version for version in plan.versions}
        next_version_number = max(
            (version.version_number for version in plan.versions),
            default=0,
        ) + 1
        for version_data in sorted(item.get("versions", []), key=lambda row: row.get("version_number", 0)):
            document = deepcopy(version_data["document"])
            document["user_id"] = user_id
            validate_json_document(document, "training_plan")
            sha256 = _training_version_sha(document, user_id)
            existing_version = existing_hashes.get(sha256)
            if existing_version is None:
                existing_version = TrainingPlanVersion(
                    user_id=user_id,
                    training_plan_id=plan.id,
                    version_number=next_version_number,
                    created_by_user_id=user_id,
                    change_reason="Account restore",
                    schema_version=document["schema_version"],
                    sha256=sha256,
                    content=document,
                )
                next_version_number += 1
                db.session.add(existing_version)
                db.session.flush()
                existing_hashes[sha256] = existing_version
            if version_data.get("id") is not None:
                version_map[int(version_data["id"])] = existing_version.id
            if version_data.get("active"):
                plan.active_version_number = existing_version.version_number
                plan.name = document["data"]["name"].strip()
                if "description" in document["data"]:
                    plan.description = _optional_text(document["data"].get("description"))
        return plan, version_map

    def _extend_existing_training_maps(
        self,
        item: dict[str, Any],
        *,
        operation: RestoreOperation,
        user_id: int,
        id_maps: dict[str, dict[int, int]],
    ) -> None:
        if operation.existing_id is None:
            return
        plan = db.session.get(TrainingPlan, operation.existing_id)
        if plan is None or plan.user_id != user_id:
            return
        if _source_id(item) is not None:
            id_maps["training_plans"][_source_id(item)] = plan.id
        versions_by_sha = {version.sha256: version for version in plan.versions}
        for version_data in item.get("versions", []):
            source_version_id = version_data.get("id")
            if not isinstance(source_version_id, int):
                continue
            try:
                sha256 = _training_version_sha(version_data["document"], user_id)
            except Exception:
                continue
            existing_version = versions_by_sha.get(sha256)
            if existing_version is not None:
                id_maps["training_plan_versions"][source_version_id] = existing_version.id

    def _apply_training_session(self, document: dict[str, Any], *, user_id: int) -> TrainingSession:
        data = document["data"]
        version = db.session.execute(
            db.select(TrainingPlanVersion).where(
                TrainingPlanVersion.id == data["training_plan_version_id"],
                TrainingPlanVersion.user_id == user_id,
            )
        ).scalar_one_or_none()
        if version is None or version.training_plan_id != data["training_plan_id"]:
            raise AccountRestoreError("Training session plan reference could not be restored")
        existing = self._find_existing("training_sessions", document, user_id=user_id)
        if existing is not None:
            return existing
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
            client_submission_id=data.get("client_submission_id"),
            client_payload_sha256=(
                canonical_sha256(document)
                if data.get("client_submission_id")
                else None
            ),
        )
        db.session.add(session)
        db.session.flush()
        for exercise_data in data["exercises"]:
            exercise = TrainingSessionExercise(
                user_id=user_id,
                training_session_id=session.id,
                exercise_order=exercise_data["exercise_order"],
                planned_exercise_order=exercise_data["planned_exercise_order"],
                name=exercise_data["name"],
                notes=exercise_data.get("notes"),
            )
            db.session.add(exercise)
            db.session.flush()
            for set_data in exercise_data["sets"]:
                from app.services.workout_loads import validate_load_details

                db.session.add(
                    TrainingSet(
                        user_id=user_id,
                        training_session_exercise_id=exercise.id,
                        set_number=set_data["set_number"],
                        planned_set_number=set_data["planned_set_number"],
                        weight_kg=_decimal(set_data["weight_kg"]),
                        load_details_json=validate_load_details(
                            set_data["weight_kg"], set_data.get("load_details")
                        ),
                        reps=set_data["reps"],
                        rir=_decimal(set_data.get("rir")),
                        rpe=_decimal(set_data.get("rpe")),
                        rest_seconds=set_data.get("rest_seconds"),
                        notes=set_data.get("notes"),
                    )
                )
        return session

    def _apply_activity_or_route(self, section: str, document: dict[str, Any], *, user_id: int) -> Activity | Route:
        existing = self._find_existing(section, document, user_id=user_id)
        model = Activity if section == "activities" else Route
        record = existing or model(user_id=user_id)
        if record.user_id != user_id:
            raise AccountRestoreError("Activity/route restore target does not belong to this user")
        data = document["data"]
        if section == "activities":
            record.activity_type = data["activity_type"].strip()
            record.started_at = datetime.fromisoformat(data["started_at"].replace("Z", "+00:00"))
            record.ended_at = (
                datetime.fromisoformat(data["ended_at"].replace("Z", "+00:00"))
                if data.get("ended_at")
                else None
            )
            for field in (
                "duration_seconds",
                "moving_time_seconds",
                "avg_heart_rate_bpm",
                "max_heart_rate_bpm",
                "avg_power_watts",
                "max_power_watts",
            ):
                setattr(record, field, data.get(field))
            for field in (
                "distance_meters",
                "calories_kcal",
                "avg_cadence_rpm",
                "max_cadence_rpm",
                "avg_speed_mps",
                "max_speed_mps",
                "elevation_gain_meters",
                "elevation_loss_meters",
            ):
                setattr(record, field, _decimal(data.get(field)))
            for field in ("sport_profile", "manufacturer", "product", "source_app", "notes"):
                setattr(record, field, data.get(field))
            record.laps_json = data.get("laps")
            record.track_json = data.get("track")
            record.bounds_json = data.get("bounds")
            record.point_count = len(data.get("track") or [])
            record.warnings_json = data.get("warnings")
        else:
            record.name = data["name"].strip()
            record.route_type = data["route_type"].strip()
            record.distance_meters = _decimal(data.get("distance_meters"))
            record.elevation_gain_meters = _decimal(data.get("elevation_gain_meters"))
            record.elevation_loss_meters = _decimal(data.get("elevation_loss_meters"))
            record.bounds_json = data.get("bounds")
            record.points_json = data.get("points")
            record.point_count = len(data.get("points") or [])
            record.source_app = data.get("source_app")
            record.notes = data.get("notes")
            record.warnings_json = data.get("warnings")
        record.source_type = document.get("source_type", "uploaded")
        record.source_file_id = None
        record.fingerprint_sha256 = _activity_route_sha(document)
        record.canonical_json = document
        db.session.add(record)
        return record

    @staticmethod
    def _summary(
        operations: list[dict[str, Any]],
        *,
        committed: bool,
        rollback: bool,
    ) -> dict[str, Any]:
        counts = {
            "insert": 0,
            "update": 0,
            "skip": 0,
            "conflict": 0,
            "invalid": 0,
            "unsupported": 0,
        }
        for operation in operations:
            counts[operation["operation"]] += 1
        return {
            "total": len(operations),
            "valid": counts["insert"] + counts["update"] + counts["skip"],
            "invalid": counts["invalid"],
            "inserts": counts["insert"],
            "updates": counts["update"],
            "skips": counts["skip"],
            "conflicts": counts["conflict"],
            "unsupported": counts["unsupported"],
            "errors": [
                error
                for operation in operations
                for error in operation.get("errors", [])
                if operation["operation"] in {"invalid", "conflict"}
            ],
            "rollback": rollback,
            "committed": committed,
            "operations": operations,
        }

    @staticmethod
    def _section_counts(payload: dict[str, Any]) -> dict[str, int]:
        data = payload.get("data") or {}
        return {
            section: len(items)
            for section, items in data.items()
            if isinstance(items, list)
        }

    @staticmethod
    def _warnings(payload: dict[str, Any], plan: dict[str, Any]) -> list[str]:
        warnings = []
        unsupported = plan.get("unsupported", 0)
        if unsupported:
            warnings.append(
                f"{unsupported} registro(s) son metadatos o derivados y no se restauran."
            )
        exported_user = _safe_exported_user(payload)
        if exported_user:
            warnings.append(
                "El usuario/rol/email del export se ignoran; el destino es la cuenta autenticada."
            )
        return warnings


def _training_version_sha(document: dict[str, Any], user_id: int) -> str:
    normalized = deepcopy(document)
    normalized["user_id"] = user_id
    return hashlib.sha256(serialize_training_plan(normalized)).hexdigest()


def _activity_route_sha(document: dict[str, Any]) -> str:
    normalized = deepcopy(document)
    normalized.pop("user_id", None)
    normalized.pop("source_file_id", None)
    return canonical_sha256(normalized)


def _find_product_for_ingredient(user_id: int, ingredient: dict[str, Any]) -> FoodProduct | None:
    name = ingredient.get("food_product_name")
    if not name:
        return None
    brand = ingredient.get("food_product_brand")
    brand = brand.strip() if brand else None
    query = db.select(FoodProduct).where(
        FoodProduct.user_id == user_id,
        FoodProduct.name == name.strip(),
    )
    query = query.where(FoodProduct.brand.is_(None) if brand is None else FoodProduct.brand == brand)
    return db.session.execute(query).scalar_one_or_none()


def _known_product_keys(user_id: int) -> set[tuple[str, str | None]]:
    products = db.session.execute(
        db.select(FoodProduct).where(FoodProduct.user_id == user_id)
    ).scalars()
    return {_product_key({"name": product.name, "brand": product.brand}) for product in products}


def _product_key(item: dict[str, Any]) -> tuple[str, str | None]:
    brand = item.get("brand")
    return (
        str(item["name"]).strip().casefold(),
        str(brand).strip().casefold() if brand else None,
    )


def _ingredient_product_key(item: dict[str, Any]) -> tuple[str, str | None]:
    brand = item.get("food_product_brand")
    return (
        str(item["food_product_name"]).strip().casefold(),
        str(brand).strip().casefold() if brand else None,
    )


def _validate_recipe_product_references(
    document: dict[str, Any],
    known_product_keys: set[tuple[str, str | None]],
) -> None:
    for ingredient in document.get("ingredients", []):
        if ingredient.get("food_product_name") is None:
            raise AccountRestoreError(
                "Recipe restore requires product names, not source IDs"
            )
        if _ingredient_product_key(ingredient) not in known_product_keys:
            raise AccountRestoreError(
                "Recipe ingredient food product was not found for restore"
            )


def _source_id(item: Any) -> int | None:
    if isinstance(item, dict) and isinstance(item.get("id"), int):
        return item["id"]
    return None


def _label(item: Any, section: str) -> str:
    if not isinstance(item, dict):
        return section
    if section == "training_plans":
        return str(item.get("name") or section)
    if section == "training_sessions":
        return str((item.get("data") or {}).get("performed_at") or section)
    if section == "activities":
        data = item.get("data") or {}
        return str(data.get("started_at") or data.get("activity_type") or section)
    if section == "routes":
        return str((item.get("data") or {}).get("name") or section)
    if section in {"weigh_ins", "daily_energy", "daily_nutrition"}:
        data = item.get("data") or {}
        return str(data.get("date") or data.get("recorded_at") or section)
    if section == "medical_lab_reports":
        return str(item.get("date") or section)
    return str(item.get("name") or item.get("original_filename") or section)


def _model(section: str) -> str:
    return {
        "food_products": "FoodProduct",
        "recipes": "Recipe",
        "weigh_ins": "WeighIn",
        "daily_energy": "DailyEnergy",
        "daily_nutrition": "DailyNutrition",
        "medical_lab_reports": "MedicalLabReport",
        "training_plans": "TrainingPlan",
        "training_sessions": "TrainingSession",
        "exercise_load_profiles": "ExerciseLoadProfile",
        "activities": "Activity",
        "routes": "Route",
    }.get(section, section)


def _safe_exported_user(payload: dict[str, Any]) -> dict[str, Any] | None:
    user = payload.get("user")
    if not isinstance(user, dict):
        return None
    return {key: user.get(key) for key in ("id", "email", "role") if key in user}


def _validate_json_limits(value: Any) -> None:
    node_count = 0

    def walk(item: Any, depth: int) -> None:
        nonlocal node_count
        node_count += 1
        if node_count > MAX_JSON_TOTAL_NODES:
            raise AccountRestoreError("Restore JSON contains too many values")
        if depth > MAX_JSON_DEPTH:
            raise AccountRestoreError("Restore JSON is too deeply nested")
        if isinstance(item, str):
            if len(item) > MAX_JSON_STRING_LENGTH:
                raise AccountRestoreError("Restore JSON contains a string that is too long")
            return
        if isinstance(item, list):
            if len(item) > MAX_JSON_ARRAY_ITEMS:
                raise AccountRestoreError("Restore JSON contains an array that is too large")
            for child in item:
                walk(child, depth + 1)
            return
        if isinstance(item, dict):
            if len(item) > MAX_JSON_OBJECT_KEYS:
                raise AccountRestoreError("Restore JSON contains an object with too many keys")
            for key, child in item.items():
                if not isinstance(key, str):
                    raise AccountRestoreError("Restore JSON object keys must be strings")
                if len(key) > MAX_JSON_STRING_LENGTH:
                    raise AccountRestoreError("Restore JSON contains an object key that is too long")
                walk(child, depth + 1)

    walk(value, 0)


def safe_error(error: Exception) -> str:
    text = str(error) or "Record is invalid"
    if isinstance(error, JsonSchemaValidationError):
        text = "Record does not match its schema"
    if len(text) > 200:
        text = text[:197] + "..."
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
