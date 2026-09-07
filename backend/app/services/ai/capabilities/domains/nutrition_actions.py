from __future__ import annotations

from decimal import Decimal

from app.services.ai.capabilities.domains.action_support import (
    METADATA_FIELDS,
    action_schema,
    bounded_decimal,
    clean_optional_strings,
    idempotency_uuid,
    preview_field,
    today_for_user,
)
from app.services.ai.capabilities.types import ActionApplyResult, ActionCapability
from app.services.mobile_health import create_nutrition_item


FOOD_METRIC_FIELDS = (
    "calories_kcal",
    "protein_g",
    "fat_g",
    "net_carbs_g",
    "total_carbs_g",
    "fiber_g",
    "sugar_g",
    "sodium_mg",
)
FOOD_FIELDS = (
    "date",
    "meal_type",
    "meal_name",
    "items",
    *METADATA_FIELDS,
)
FOOD_SCHEMA = action_schema(
    {
        "date": {"type": "string", "format": "date"},
        "meal_type": {
            "type": "string",
            "enum": ["breakfast", "lunch", "dinner", "snack", "extra", "other"],
        },
        "meal_name": {"type": ["string", "null"], "maxLength": 200},
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 1, "maxLength": 200},
                    "quantity": {"type": ["string", "number", "null"]},
                    "unit": {"type": ["string", "null"], "maxLength": 32},
                    **{
                        name: {"type": ["string", "number", "null"]}
                        for name in FOOD_METRIC_FIELDS
                    },
                    "notes": {"type": ["string", "null"], "maxLength": 2000},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    }
)


def _normalize(_user, payload: dict) -> dict:
    clean = clean_optional_strings(payload, ("date", "meal_name"))
    for field_name in ("date", "meal_name"):
        if clean.get(field_name) is None:
            clean.pop(field_name, None)
    items = []
    for raw_item in clean.get("items", []):
        if not isinstance(raw_item, dict):
            items.append(raw_item)
            continue
        item = clean_optional_strings(
            raw_item, ("quantity", "unit", *FOOD_METRIC_FIELDS, "notes")
        )
        if item.get("quantity") is not None:
            bounded_decimal(item["quantity"], "quantity", Decimal("0"), Decimal("1000000"))
        for field_name in FOOD_METRIC_FIELDS:
            if field_name in item:
                bounded_decimal(item[field_name], field_name, Decimal("0"), Decimal("1000000"))
        items.append(item)
    if "items" in clean:
        clean["items"] = items
    return clean


def _preview(_user, payload: dict, _context) -> dict:
    fields = [
        preview_field("date", "Fecha", payload.get("date"), kind="date"),
        preview_field(
            "meal_type",
            "Comida",
            payload.get("meal_type"),
            required=True,
            options=("breakfast", "lunch", "dinner", "snack", "extra", "other"),
        ),
        preview_field("meal_name", "Nombre de comida", payload.get("meal_name")),
    ]
    return {"fields": fields, "items": payload.get("items") or []}


def apply_food(user, draft, payload: dict, _context, _now) -> ActionApplyResult:
    target_date = payload.get("date") or today_for_user(user)
    resource_ids = []
    for index, item in enumerate(payload["items"]):
        document = {
            "date": target_date,
            "meal_type": payload["meal_type"],
            "meal_name": payload.get("meal_name"),
            "name": item["name"],
            "quantity": item.get("quantity"),
            "unit": item.get("unit"),
            "source": "manual",
            "client_event_id": idempotency_uuid(draft.public_id, f"food:{index}"),
        }
        for field_name in (*FOOD_METRIC_FIELDS, "notes"):
            if field_name in item:
                document[field_name] = item[field_name]
        record = create_nutrition_item(user.id, document)
        resource_ids.append(record.public_id)
    return ActionApplyResult("nutrition_item", tuple(resource_ids))


FOOD_CREATE = ActionCapability(
    action_id="nutrition.food.create",
    domain="nutrition",
    entity="food_entry",
    operation="create",
    label="Registrar comida",
    description="Prepara uno o más alimentos para una comida.",
    supported_fields=FOOD_FIELDS,
    required_fields=("meal_type", "items"),
    optional_fields=tuple(field for field in FOOD_FIELDS if field not in {"meal_type", "items"}),
    input_schema=FOOD_SCHEMA,
    apply_handler=apply_food,
    draft_type="food_entry",
    normalizer=_normalize,
    previewer=_preview,
)
