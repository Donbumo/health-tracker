import csv
from io import StringIO

from app.models import DailyEnergy, DailyNutrition
from app.services.exporters.base import BaseExporter, ExportArtifact, serialize_json
from app.services.validation import validate_json_document


def _number(value):
    return float(value) if value is not None else None


def _source_type(resource) -> str:
    if resource.source_file is not None and resource.source_file.source_type in {
        "manual_generated",
        "uploaded",
        "device_sync",
    }:
        return resource.source_file.source_type
    return "uploaded"


def build_daily_energy_document(record: DailyEnergy, user_id: int) -> dict:
    if record.user_id != user_id:
        raise ValueError("Daily energy does not belong to this user")
    data = {"date": record.date.isoformat(), "source": record.source}
    optional = {
        "total_expenditure_kcal": record.total_calories,
        "active_expenditure_kcal": record.active_calories,
        "resting_expenditure_kcal": record.resting_calories,
        "steps": record.steps,
        "distance_meters": record.distance_meters,
    }
    for field, value in optional.items():
        if value is not None:
            data[field] = value if field == "steps" else _number(value)
    if record.notes:
        data["notes"] = record.notes
    return {
        "schema_version": "1.0",
        "record_type": "daily_energy",
        "user_id": user_id,
        "source_type": _source_type(record),
        "data": data,
    }


def build_daily_nutrition_document(record: DailyNutrition, user_id: int) -> dict:
    if record.user_id != user_id:
        raise ValueError("Daily nutrition does not belong to this user")
    data = {"date": record.date.isoformat(), "source": record.source, "meals": []}
    totals = {
        "calories_kcal": record.calories,
        "protein_g": record.protein_g,
        "fat_g": record.fat_g,
        "net_carbs_g": record.net_carbs_g,
        "total_carbs_g": record.total_carbs_g,
        "fiber_g": record.fiber_g,
        "sugar_g": record.sugar_g,
        "sodium_mg": record.sodium_mg,
    }
    for field, value in totals.items():
        if value is not None:
            data[field] = _number(value)
    if record.notes:
        data["notes"] = record.notes

    for meal in record.meals:
        meal_data = {
            "meal_type": meal.meal_type,
            "sort_order": meal.sort_order,
            "items": [],
        }
        if meal.name:
            meal_data["name"] = meal.name
        for item in meal.items:
            item_data = {"name": item.name, "sort_order": item.sort_order}
            if item.quantity is not None:
                item_data["quantity"] = _number(item.quantity)
            if item.unit:
                item_data["unit"] = item.unit
            for model_field, document_field in (
                ("calories", "calories_kcal"),
                ("protein_g", "protein_g"),
                ("fat_g", "fat_g"),
                ("net_carbs_g", "net_carbs_g"),
                ("total_carbs_g", "total_carbs_g"),
                ("fiber_g", "fiber_g"),
                ("sugar_g", "sugar_g"),
                ("sodium_mg", "sodium_mg"),
            ):
                value = getattr(item, model_field)
                if value is not None:
                    item_data[document_field] = _number(value)
            if item.notes:
                item_data["notes"] = item.notes
            meal_data["items"].append(item_data)
        data["meals"].append(meal_data)
    return {
        "schema_version": "1.0",
        "record_type": "daily_nutrition",
        "user_id": user_id,
        "source_type": _source_type(record),
        "data": data,
    }


class DailyEnergyJsonExporter(BaseExporter):
    format_name = "json"

    def export(self, resource: DailyEnergy, user_id: int) -> ExportArtifact:
        self.ensure_owner(resource, user_id)
        document = build_daily_energy_document(resource, user_id)
        validate_json_document(document, "daily_energy")
        return ExportArtifact(
            content=serialize_json(document),
            mimetype="application/json",
            extension="json",
        )


class DailyEnergyCsvExporter(BaseExporter):
    format_name = "csv"

    def export(self, resource: DailyEnergy, user_id: int) -> ExportArtifact:
        self.ensure_owner(resource, user_id)
        output = StringIO(newline="")
        fieldnames = (
            "date",
            "total_calories",
            "active_calories",
            "resting_calories",
            "steps",
            "distance_meters",
            "source",
        )
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({field: getattr(resource, field) for field in fieldnames})
        return ExportArtifact(
            content=output.getvalue().encode("utf-8-sig"),
            mimetype="text/csv",
            extension="csv",
        )


class DailyNutritionJsonExporter(BaseExporter):
    format_name = "json"

    def export(self, resource: DailyNutrition, user_id: int) -> ExportArtifact:
        self.ensure_owner(resource, user_id)
        document = build_daily_nutrition_document(resource, user_id)
        validate_json_document(document, "daily_nutrition")
        return ExportArtifact(
            content=serialize_json(document),
            mimetype="application/json",
            extension="json",
        )


class DailyNutritionCsvExporter(BaseExporter):
    format_name = "csv"

    def export(self, resource: DailyNutrition, user_id: int) -> ExportArtifact:
        self.ensure_owner(resource, user_id)
        output = StringIO(newline="")
        fieldnames = (
            "date",
            "calories",
            "protein_g",
            "fat_g",
            "net_carbs_g",
            "total_carbs_g",
            "fiber_g",
            "sugar_g",
            "sodium_mg",
            "source",
        )
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({field: getattr(resource, field) for field in fieldnames})
        return ExportArtifact(
            content=output.getvalue().encode("utf-8-sig"),
            mimetype="text/csv",
            extension="csv",
            warning="CSV conserva solo el resumen diario; usa JSON para comidas e items.",
        )
