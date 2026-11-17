"""Phase B detector, strict public schema and source observations."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.importers.nutrition_exchange import intake
from app.services.nutrition_math import NUTRIENTS

FIXTURES = Path(__file__).resolve().parents[2] / "examples" / "qa" / "nutrition-exchange"


def parse_document(document):
    return intake.parse(json.dumps(document, ensure_ascii=False).encode("utf-8"))


def test_explicit_htnx_preserves_the_catalog_and_source_states():
    parsed = intake.parse((FIXTURES / "valid-explicit.json").read_bytes())
    batch = parsed.batch
    assert parsed.profile == batch.profile == "htnx_1_0"
    assert batch.destination_hint == "consumed"
    assert [meal.type for meal in batch.meals] == ["breakfast", "lunch", "dinner", "snack"]
    breakfast, lunch, dinner, snack = (meal.foods[0].nutrition for meal in batch.meals)
    assert {key: value.unit for key, value in breakfast.values.items()} == {
        key: entry[1] for key, entry in NUTRIENTS.items()
    }
    assert breakfast.values["energy"].quality == "label"
    assert breakfast.values["zinc"].quality == "estimated"
    assert breakfast.values["zinc"].evidence.source == "Etiqueta ficticia de QA"
    assert breakfast.values["zinc"].evidence.path == "/meals/0/foods/0/nutrition/values/zinc"
    assert breakfast.values["zinc"].evidence.raw["value"] == "1.125"
    assert breakfast.values["zinc"].value == Decimal("1.125")
    assert lunch.values["vitamin_d"].state == "trace"
    assert lunch.values["vitamin_d"].value is None
    assert lunch.values["sodium"].state == "below_limit"
    assert lunch.values["sodium"].limit == Decimal("0.25")
    chromium, = lunch.additional
    assert chromium.name == "Cromo" and chromium.value == Decimal("0.2")
    assert chromium.evidence.path == "/meals/1/foods/0/nutrition/additional_nutrients/0/observation"
    assert dinner.basis_kind == "consumed" and dinner.basis is None
    assert "fiber" not in dinner.values
    assert dinner.values["protein"].state == "unknown"
    assert dinner.values["protein"].value is None
    assert dinner.values["protein"].evidence.raw == {"state": "unknown"}
    assert snack.values["fiber"].state == "known" and snack.values["fiber"].value == Decimal(0)
    assert snack.basis.unit == "piece" and snack.basis.label == "galleta de este tipo"


def test_partial_htnx_keeps_missing_fields_and_ingredient_paths():
    parsed = intake.parse((FIXTURES / "valid-needs-review.json").read_bytes())
    batch = parsed.batch
    assert batch.default_date is None and batch.destination_hint is None
    first, second = batch.meals
    assert first.date is None and first.date_path is None
    assert first.foods[0].nutrition.basis_kind == "absent"
    assert first.foods[0].nutrition.values["energy"].value == Decimal(85)
    assert first.foods[1].quantity.unit == "ml"
    assert first.foods[1].nutrition.basis.unit == "g"
    assert first.foods[2].quantity is None and first.foods[2].nutrition is None
    assert second.date == date(2030, 1, 16) and second.date_path == "/meals/1/date"
    dish, = second.foods
    assert [child.path for child in dish.ingredients] == [
        "/meals/1/foods/0/ingredients/0", "/meals/1/foods/0/ingredients/1",
    ]


def test_default_date_and_explicit_local_override_retain_provenance():
    document = {
        "format": "health-tracker-nutrition",
        "version": "1.0",
        "date": "2035-06-07",
        "note": 'QA ficticia con llaves {, ] y "comillas".',
        "meals": [
            {"foods": [{"name": "QA plato A", "note": "Fuente de prueba"}]},
            {"date": "2035-06-08", "foods": [{"name": "QA plato B"}]},
        ],
    }
    batch = parse_document(document).batch
    assert batch.default_date == date(2035, 6, 7)
    assert batch.evidence[0].note == document["note"]
    assert batch.meals[0].date == date(2035, 6, 7)
    assert batch.meals[0].date_path == "/date"
    assert batch.meals[0].foods[0].evidence[0].note == "Fuente de prueba"
    assert batch.meals[1].date == date(2035, 6, 8)
    assert batch.meals[1].date_path == "/meals/1/date"


@pytest.mark.parametrize(("document", "profile"), [
    ({"type": "nutrition_import", "schema_version": "2.1", "data": {}}, "standard_2_1"),
    ({"record_type": "daily_nutrition", "schema_version": "1.0", "data": {}}, "daily_1_0"),
    ({"meals": [{"foods": [{"name": "Synthetic QA meal"}]}]}, "common"),
    ({"alimentos": [{"nombre": "Alimento ficticio de QA"}]}, "common"),
    ({"comidas": [], "meals": [], "foods": []}, "common"),
])
def test_detector_hands_recognized_families_to_their_own_adapters(document, profile):
    detected = parse_document(document)
    assert detected.profile == profile
    assert detected.batch is None
    assert detected.document == document


def test_utf8_bom_is_tolerated_at_the_byte_boundary():
    payload = (FIXTURES / "valid-explicit.json").read_bytes()
    assert intake.parse(b"\xef\xbb\xbf" + payload) == intake.parse(payload)


@pytest.mark.parametrize(("document", "code", "path"), [
    ({"format": "health-tracker-nutrition", "version": "9", "foods": []}, "unsupported_version", "/version"),
    ({"format": "health-tracker-nutrition", "meals": []}, "schema_error", ""),
    ({"format": "health-tracker-nutrition", "version": "1.0", "record_type": "daily_nutrition"}, "format_conflict", ""),
    ({"type": "nutrition_import", "record_type": "daily_nutrition"}, "format_conflict", ""),
    ({"type": "nutrition_import", "schema_version": "2.0", "foods": []}, "unsupported_version", "/schema_version"),
    ({"record_type": "daily_nutrition", "schema_version": "2.1"}, "unsupported_version", "/schema_version"),
    ({"format": "unknown", "foods": []}, "unsupported_format", ""),
    ({"records": []}, "unsupported_format", ""),
    ({"meals": "not an array"}, "unsupported_format", ""),
])
def test_explicit_structure_prevents_heuristic_fallback(document, code, path):
    with pytest.raises(intake.IntakeError) as failure:
        parse_document(document)
    assert failure.value.status == 422
    diagnostic = failure.value.diagnostics[0]
    assert diagnostic.code == code and diagnostic.path == path
    assert diagnostic.severity == "invalid"
    assert diagnostic.message_key and diagnostic.action_key


@pytest.mark.parametrize(("name", "path"), [
    ("invalid-internal-field.json", "/meals/0/foods/0"),
    ("invalid-nutrient-unit.json", "/meals/0/foods/0/nutrition/values/sodium/unit"),
    ("invalid-nutrient-state.json", "/meals/0/foods/0/nutrition/values/vitamin_d"),
])
def test_bad_explicit_htnx_keeps_safe_field_diagnostic(name, path):
    with pytest.raises(intake.IntakeError) as failure:
        intake.parse((FIXTURES / name).read_bytes())
    assert failure.value.status == 422
    assert all(diagnostic.code == "schema_error" for diagnostic in failure.value.diagnostics)
    assert path in {diagnostic.path for diagnostic in failure.value.diagnostics}


@pytest.mark.parametrize(("payload", "code", "path"), [
    (b"", "invalid_json", ""),
    (b'{"meals":[}', "invalid_json", ""),
    (b'{"foods":[{"quantity":NaN}]}', "invalid_json", "/foods/0/quantity"),
    (b'{"foods":[{"quantity":Infinity}]}', "invalid_json", "/foods/0/quantity"),
    (b'{"foods":[{"quantity":-Infinity}]}', "invalid_json", "/foods/0/quantity"),
    (b'{"foods":[{"name":"\xff"}]}', "invalid_utf8", ""),
    (br'{"foods":[{"name":"\ud800"}]}', "invalid_json", ""),
    (br'{"meals":[],"me\u0061ls":[]}', "duplicate_key", "/meals"),
    (b'{"foods":[{"a/~":1,"a/~":2}]}', "duplicate_key", "/foods/0/a~1~0"),
    (b'{"foods":[{"quantity":1e1001}]}', "numeric_limit", "/foods/0/quantity"),
    (
        b'{"foods":[{"quantity":' + b"9" * (intake.MAX_NUMBER_LENGTH + 1) + b'}]}',
        "numeric_limit",
        "/foods/0/quantity",
    ),
])
def test_unsafe_json_is_controlled_with_no_payload_in_the_error(payload, code, path):
    with pytest.raises(intake.IntakeError) as failure:
        intake.parse(payload)
    assert failure.value.status == 422
    assert str(failure.value) == code
    assert failure.value.diagnostics[0].path == path


@pytest.mark.parametrize(("payload", "path"), [
    (b" " * (intake.MAX_BYTES + 1), ""),
    (b"[" * (intake.MAX_DEPTH + 1) + b"]" * (intake.MAX_DEPTH + 1), ""),
    (b'{"foods":[],"note":"' + b"x" * (intake.MAX_TEXT_LENGTH + 1) + b'"}', ""),
    (b'{"foods":[],"noise":[' + b"0," * intake.MAX_MEMBERS + b"0]}", ""),
    (b'{"foods":[' + b"{}," * intake.MAX_FOODS + b"{}]}", "/foods"),
    (b'{"foods":[{"ingredients":[' + b"{}," * (intake.MAX_FOODS - 1) + b"{}]}]}", "/foods/0/ingredients"),
], ids=["bytes", "depth", "text", "members", "foods", "ingredients"])
def test_exceeded_resource_budgets_return_413(payload, path):
    with pytest.raises(intake.IntakeError) as failure:
        intake.parse(payload)
    assert failure.value.status == 413
    assert failure.value.diagnostics[0].code == "limit_exceeded"
    assert failure.value.diagnostics[0].path == path


def test_decimal_precision_is_exact_and_does_not_silently_round():
    text = (FIXTURES / "valid-explicit.json").read_text(encoding="utf-8")
    precise = text.replace('"amount": 150', '"amount": 150.12345678901200', 1)
    parsed = intake.parse(precise.encode("utf-8"))
    quantity = parsed.batch.meals[0].foods[0].quantity
    assert quantity.amount.as_tuple() == Decimal("150.123456789012").as_tuple()
    assert quantity.evidence.raw["amount"].as_tuple() == Decimal("150.12345678901200").as_tuple()

    excessive = text.replace('"amount": 150', '"amount": 150.1234567890121', 1)
    with pytest.raises(intake.IntakeError) as failure:
        intake.parse(excessive.encode("utf-8"))
    assert failure.value.status == 422
    diagnostic, = failure.value.diagnostics
    assert diagnostic.code == "numeric_limit"
    assert diagnostic.path == "/meals/0/foods/0/quantity/amount"


def test_htnx_range_violation_stays_on_the_declared_format():
    text = (FIXTURES / "valid-explicit.json").read_text(encoding="utf-8")
    excessive = text.replace('"amount": 150', '"amount": 1e100', 1)
    with pytest.raises(intake.IntakeError) as failure:
        intake.parse(excessive.encode("utf-8"))
    assert failure.value.status == 422
    assert {diagnostic.path for diagnostic in failure.value.diagnostics} >= {"/meals/0/foods/0/quantity/amount"}
