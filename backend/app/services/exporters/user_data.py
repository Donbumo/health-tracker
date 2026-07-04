from datetime import datetime, timezone
from typing import Any

from app.extensions import db
from app.models import (
    DailyEnergy,
    DailyNutrition,
    FoodProduct,
    MedicalLabReport,
    TrainingPlan,
    TrainingSession,
    UploadedFile,
    User,
    WeighIn,
)
from app.services.exporters.base import (
    BaseExporter,
    ExportArtifact,
    ExportError,
    serialize_json,
)
from app.services.exporters.medical_lab import build_medical_lab_document
from app.services.exporters.training_session import build_completed_workout_document
from app.services.exporters.weigh_in import build_weigh_in_document
from app.services.exporters.wellness import (
    build_daily_energy_document,
    build_daily_nutrition_document,
)
from app.services.validation import validate_json_document


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _number(value):
    return float(value) if value is not None else None


def _records(model, user_id: int, *order_by):
    statement = db.select(model).where(model.user_id == user_id)
    if order_by:
        statement = statement.order_by(*order_by)
    return db.session.execute(statement).scalars().all()


def _daily_balances(
    nutrition_records: list[DailyNutrition],
    energy_records: list[DailyEnergy],
) -> list[dict[str, Any]]:
    nutrition_by_date = {record.date: record for record in nutrition_records}
    energy_by_date = {record.date: record for record in energy_records}
    balances = []
    for target_date in sorted(nutrition_by_date.keys() | energy_by_date.keys()):
        nutrition = nutrition_by_date.get(target_date)
        energy = energy_by_date.get(target_date)
        consumed = nutrition.calories if nutrition is not None else None
        expended = energy.total_calories if energy is not None else None
        balances.append(
            {
                "date": target_date.isoformat(),
                "calories_consumed": _number(consumed),
                "calories_expended": _number(expended),
                "balance": (
                    _number(consumed - expended)
                    if consumed is not None and expended is not None
                    else None
                ),
                "complete": consumed is not None and expended is not None,
            }
        )
    return balances


def _training_plan_document(plan: TrainingPlan, user_id: int) -> dict[str, Any]:
    if plan.user_id != user_id:
        raise ExportError("Training plan does not belong to this user")
    versions = []
    for version in plan.versions:
        if version.user_id != user_id:
            raise ExportError("Training plan version does not belong to this user")
        versions.append(
            {
                "id": version.id,
                "version_number": version.version_number,
                "active": version.version_number == plan.active_version_number,
                "schema_version": version.schema_version,
                "sha256": version.sha256,
                "source_file_id": version.source_file_id,
                "created_by_user_id": version.created_by_user_id,
                "change_reason": version.change_reason,
                "created_at": _iso(version.created_at),
                "document": version.content,
            }
        )
    return {
        "id": plan.id,
        "name": plan.name,
        "description": plan.description,
        "active_version_number": plan.active_version_number,
        "created_at": _iso(plan.created_at),
        "updated_at": _iso(plan.updated_at),
        "versions": versions,
    }


def _upload_metadata(upload: UploadedFile, user_id: int) -> dict[str, Any]:
    if upload.user_id != user_id:
        raise ExportError("Uploaded file does not belong to this user")
    return {
        "id": upload.id,
        "original_filename": upload.original_filename,
        "source_type": upload.source_type,
        "detected_type": upload.detected_type,
        "import_status": upload.import_status,
        "sha256": upload.sha256,
        "size_bytes": upload.size_bytes,
        "mime_type": upload.mime_type,
        "created_at": _iso(upload.created_at),
    }


def _food_product_document(product: FoodProduct, user_id: int) -> dict[str, Any]:
    if product.user_id != user_id:
        raise ExportError("Food product does not belong to this user")
    data = {
        "id": product.id,
        "name": product.name,
        "source": product.source,
        "is_active": product.is_active,
    }
    for field in (
        "brand",
        "serving_label",
        "notes",
    ):
        value = getattr(product, field)
        if value is not None:
            data[field] = value
    for number_field in (
        "serving_size_g",
        "calories_per_100g",
        "protein_g_per_100g",
        "fat_g_per_100g",
        "carbs_g_per_100g",
        "net_carbs_g_per_100g",
        "fiber_g_per_100g",
        "sodium_mg_per_100g",
    ):
        value = getattr(product, number_field)
        if value is not None:
            data[number_field] = float(value)
    return data


def build_user_data_document(user: User, user_id: int) -> dict[str, Any]:
    if user.id != user_id:
        raise ExportError("User export does not belong to this user")

    weigh_ins = _records(WeighIn, user_id, WeighIn.recorded_at, WeighIn.id)
    nutrition = _records(DailyNutrition, user_id, DailyNutrition.date, DailyNutrition.id)
    energy = _records(DailyEnergy, user_id, DailyEnergy.date, DailyEnergy.id)
    food_products = _records(FoodProduct, user_id, FoodProduct.id)
    plans = _records(TrainingPlan, user_id, TrainingPlan.created_at, TrainingPlan.id)
    sessions = _records(
        TrainingSession,
        user_id,
        TrainingSession.performed_at,
        TrainingSession.id,
    )
    medical_reports = _records(
        MedicalLabReport,
        user_id,
        MedicalLabReport.date,
        MedicalLabReport.id,
    )
    uploads = _records(UploadedFile, user_id, UploadedFile.created_at, UploadedFile.id)

    return {
        "schema_version": "1.0",
        "type": "user_data_export",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user": {"id": user.id, "email": user.email, "role": user.role},
        "data": {
            "food_products": [
                _food_product_document(product, user_id) for product in food_products
            ],
            "weigh_ins": [
                build_weigh_in_document(record, user_id) for record in weigh_ins
            ],
            "daily_nutrition": [
                build_daily_nutrition_document(record, user_id)
                for record in nutrition
            ],
            "daily_energy": [
                build_daily_energy_document(record, user_id) for record in energy
            ],
            "daily_balances": _daily_balances(nutrition, energy),
            "training_plans": [
                _training_plan_document(plan, user_id) for plan in plans
            ],
            "training_sessions": [
                build_completed_workout_document(session, user_id)
                for session in sessions
            ],
            "medical_lab_reports": [
                build_medical_lab_document(report, user_id)
                for report in medical_reports
            ],
            "uploads": [_upload_metadata(upload, user_id) for upload in uploads],
        },
    }


class UserDataJsonExporter(BaseExporter):
    format_name = "json"

    def export(self, resource: User, user_id: int) -> ExportArtifact:
        document = build_user_data_document(resource, user_id)
        validate_json_document(document, "user_data_export")
        return ExportArtifact(
            content=serialize_json(document),
            mimetype="application/json",
            extension="json",
        )
